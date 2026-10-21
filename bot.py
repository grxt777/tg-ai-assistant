"""Telegram-бот: точка входа. Запуск: python bot.py"""
import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from google.genai import types

import agent
import config
import db
from tools import _to_local

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

bot = Bot(config.TELEGRAM_TOKEN)
dp = Dispatcher()

DOC_EXT = (".txt", ".md", ".pdf", ".csv", ".json", ".py", ".html")


# ---------- доступ только владельцу ----------
@dp.message.outer_middleware()
async def owner_only(handler, event: Message, data):
    uid = event.from_user.id if event.from_user else 0
    owner = config.OWNER_ID or int(db.kv_get("owner_id") or 0)
    if not owner:
        db.kv_set("owner_id", uid)
        owner = uid
        log.info("Владелец назначен: %s", uid)
    if uid != owner:
        await event.answer("Это приватный ассистент 🙂")
        return
    return await handler(event, data)


async def send_long(chat_id, text):
    for i in range(0, len(text), 4000):
        await bot.send_message(chat_id, text[i:i + 4000])


async def typing_while(chat_id, coro):
    async def keep():
        while True:
            await bot.send_chat_action(chat_id, "typing")
            await asyncio.sleep(4)
    t = asyncio.create_task(keep())
    try:
        return await coro
    finally:
        t.cancel()


async def answer(m: Message, parts, history_text, query_text=None):
    try:
        reply = await typing_while(m.chat.id, agent.run(m.chat.id, parts, history_text, query_text))
    except Exception as e:
        log.exception("agent error")
        reply = f"⚠️ Ошибка: {type(e).__name__}: {e}"
    await send_long(m.chat.id, reply)


# ---------- команды ----------
@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_start(m: Message):
    await m.answer(
        "Привет! Я твой личный ассистент с памятью.\n\n"
        "Просто пиши (или шли голосовые/фото). Я запоминаю важное о тебе, веду свои таблицы, "
        "ставлю напоминания. Пришли .txt/.md/.pdf — добавлю в базу знаний.\n\n"
        "/memory — что я о тебе помню\n/forget <id> — удалить запись памяти\n"
        "/tables — мои таблицы\n/docs — документы\n/deldoc <id> — удалить документ\n"
        "/reminders — напоминания\n/reset — очистить историю диалога (память останется)"
    )


@dp.message(Command("memory"))
async def cmd_memory(m: Message):
    rows = db.list_memories(limit=100)
    text = "\n".join(f"#{r['id']} [{r['category']}] {r['content']}" for r in rows) or "Память пока пуста."
    await send_long(m.chat.id, text)


@dp.message(Command("forget"))
async def cmd_forget(m: Message):
    arg = (m.text or "").split(maxsplit=1)[1:] or [""]
    if arg[0].strip().isdigit():
        db.delete_memory(int(arg[0]))
        await m.answer("Удалил.")
    else:
        await m.answer("Использование: /forget 12")


@dp.message(Command("tables"))
async def cmd_tables(m: Message):
    ts = db.user_tables()
    if not ts:
        return await m.answer("Таблиц пока нет.")
    lines = []
    for t in ts:
        n = db.q(f'SELECT COUNT(*) c FROM "{t["name"]}"', one=True)["c"]
        lines.append(f"• {t['name']} ({n} строк) — {t['description']}\n{t['schema']}")
    await send_long(m.chat.id, "\n\n".join(lines))


@dp.message(Command("docs"))
async def cmd_docs(m: Message):
    rows = db.list_documents()
    await m.answer("\n".join(f"#{r['id']} {r['title']} ({r['n']} фрагм.)" for r in rows) or "Документов нет.")


@dp.message(Command("deldoc"))
async def cmd_deldoc(m: Message):
    arg = (m.text or "").split(maxsplit=1)[1:] or [""]
    if arg[0].strip().isdigit():
        db.delete_document(int(arg[0]))
        await m.answer("Документ удалён.")
    else:
        await m.answer("Использование: /deldoc 3")


@dp.message(Command("reminders"))
async def cmd_reminders(m: Message):
    rows = db.list_reminders(m.chat.id)
    await m.answer("\n".join(f"#{r['id']} {_to_local(r['due_at'])} [{r['repeat']}/{r['kind']}] {r['text']}"
                             for r in rows) or "Напоминаний нет.")


@dp.message(Command("reset"))
async def cmd_reset(m: Message):
    db.reset_history(m.chat.id)
    await m.answer("История диалога очищена. Долговременная память на месте.")


# ---------- контент ----------
@dp.message(F.document)
async def on_document(m: Message):
    name = m.document.file_name or "file.txt"
    mime = m.document.mime_type or ""
    if mime.startswith("image/"):  # картинка, отправленная файлом (без сжатия)
        return await on_photo(m)
    if not name.lower().endswith(DOC_EXT):
        return await m.answer("Пока понимаю только: " + ", ".join(DOC_EXT))
    data = (await bot.download(m.document)).read()
    await bot.send_chat_action(m.chat.id, "typing")
    try:
        n = await agent.ingest_document(name, data)
        await m.answer(f"📚 «{name}» добавлен в базу знаний ({n} фрагментов). Спрашивай по нему что угодно.")
    except Exception as e:
        log.exception("ingest")
        await m.answer(f"⚠️ Не смог обработать файл: {e}")


@dp.message(F.voice | F.audio)
async def on_voice(m: Message):
    media = m.voice or m.audio
    data = (await bot.download(media)).read()
    mime = getattr(media, "mime_type", None) or "audio/ogg"
    parts = [types.Part.from_bytes(data=data, mime_type=mime),
             types.Part.from_text(text="(Это голосовое сообщение владельца. Пойми его и ответь как на обычное.)")]
    await answer(m, parts, "[голосовое сообщение]", query_text="")


@dp.message(F.photo)
async def on_photo(m: Message):
    media = m.photo[-1] if m.photo else m.document
    data = (await bot.download(media)).read()
    mime = "image/jpeg" if m.photo else m.document.mime_type
    caption = m.caption or "Что на фото?"
    parts = [types.Part.from_bytes(data=data, mime_type=mime), types.Part.from_text(text=caption)]
    await answer(m, parts, f"[фото] {caption}", query_text=caption)


@dp.message(F.text)
async def on_text(m: Message):
    await answer(m, [types.Part.from_text(text=m.text)], m.text)


# ---------- фоновые напоминания ----------
async def reminder_loop():
    while True:
        try:
            for r in db.due_reminders():
                db.advance_reminder(r)
                if r["kind"] == "task":
                    prompt = f"[Плановая задача, которую владелец поставил заранее] {r['text']}"
                    try:
                        text = await agent.run(r["chat_id"], [types.Part.from_text(text=prompt)], prompt)
                    except Exception as e:
                        text = f"⚠️ Не смог выполнить задачу «{r['text']}»: {e}"
                    await send_long(r["chat_id"], text)
                else:
                    await bot.send_message(r["chat_id"], f"⏰ {r['text']}")
        except Exception:
            log.exception("reminder loop")
        await asyncio.sleep(20)


async def main():
    asyncio.create_task(reminder_loop())
    log.info("Бот запущен, модель: %s", config.MODEL)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
