"""Telegram-бот: точка входа. Запуск: python bot.py"""
import asyncio
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo
from google.genai import types

import agent
import alarms
import api
import config
import db
import eclass
import journal
import llm
from tools import _to_local

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

bot = Bot(config.TELEGRAM_TOKEN)
dp = Dispatcher()

DOC_EXT = (".txt", ".md", ".pdf", ".csv", ".json", ".py", ".html")


# ---------- доступ только владельцу ----------
NAME = re.compile(r"(?<!\w)(сан(я|ь|ю|е|ёк|ек)|sanya)(?!\w)", re.I)  # имя ассистента: «Саня, ...»


def _is_boss(user):
    """Старший ассистент из настроек (юзернеймы или id через запятую) — ему можно поручать изменения."""
    allowed = {x.strip().lstrip("@").lower() for x in db.setting("boss_bots", "").split(",") if x.strip()}
    return str(user.id) in allowed or (user.username or "").lower() in allowed


def _addressed(m: Message, me, owner=False):
    """Обращаются ли к нам: по имени, @упоминанием или /команда@бот.
    Владельцу хватает и /команды без @ и ответа на наше сообщение."""
    text, at = m.text or m.caption or "", f"@{me.username}".lower()
    if NAME.search(text):
        return True
    for e in m.entities or m.caption_entities or []:
        chunk = e.extract_from(text).lower()
        if e.type == "mention" and chunk == at or e.type == "text_mention" and e.user and e.user.id == me.id:
            return True
        if e.type == "bot_command" and (chunk.endswith(at) or owner and "@" not in chunk):
            return True
    return owner and bool(m.reply_to_message and m.reply_to_message.from_user
                          and m.reply_to_message.from_user.id == me.id)


@dp.message.outer_middleware()
async def owner_only(handler, event: Message, data):
    group = event.chat.type != "private"
    if event.from_user and event.from_user.is_bot:
        # другие ИИ-ассистенты в группе: отвечаем, только если упомянули нас; остальным молчим
        if group and (event.text or event.caption) and _addressed(event, await bot.me()):
            await guest_answer(event, boss=_is_boss(event.from_user))
        return
    uid = event.from_user.id if event.from_user else 0
    owner = config.OWNER_ID or int(db.kv_get("owner_id") or 0)
    if not owner:
        db.kv_set("owner_id", uid)
        owner = uid
        log.info("Владелец назначен: %s", uid)
        await api.setup_menu_button(bot)
    if group and not _addressed(event, await bot.me(), owner=uid == owner):
        return  # в группе слушаем только обращения к себе, а не всю переписку
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


async def answer(m: Message, parts, history_text, query_text=None, guest=None, boss=False):
    try:
        reply = await typing_while(m.chat.id, agent.run(m.chat.id, parts, history_text, query_text,
                                                        guest=guest, boss=boss))
    except Exception as e:
        if isinstance(e, llm.QuotaExhausted):
            reply = f"⏳ {e}"
        else:
            log.exception("agent error")
            db.log_event("error", "agent", f"{type(e).__name__}: {e}")
            reply = f"⚠️ Ошибка: {type(e).__name__}: {str(e)[:300]}"
    if guest:  # @упоминание бота в ответе разбудит его, и он ответит нам — так начинается бесконечный круг
        reply = re.sub(r"@(\w+bot)\b", r"\1", reply, flags=re.I)
    await send_long(m.chat.id, reply)


async def guest_answer(m: Message, boss=False):
    """Сообщение от другого бота, который к нам обратился: отвечаем; менять что-то можно только старшему."""
    name = m.from_user.full_name or m.from_user.username or "бот"
    text = m.text or m.caption
    await answer(m, [types.Part.from_text(text=f"[{name}]: {text}")], f"[{name}]: {text}", guest=name, boss=boss)


# ---------- команды ----------
@dp.message(CommandStart())
@dp.message(Command("help"))
async def cmd_start(m: Message):
    await m.answer(
        "Привет! Я твой личный ассистент с памятью.\n\n"
        "Просто пиши (или шли голосовые/фото). Я запоминаю важное о тебе, веду свои таблицы, "
        "ставлю напоминания. Пришли .txt/.md/.pdf — добавлю в базу знаний.\n\n"
        "Вечером расскажи, как прошёл день, что делал и сколько потратил/заработал — я веду дневник "
        "и считаю аналитику за неделю, месяц и год (смотри в панели → Дневник).\n\n"
        "/memory — что я о тебе помню\n/forget <id> — удалить запись памяти\n"
        "/tables — мои таблицы\n/docs — документы\n/deldoc <id> — удалить документ\n"
        "/eclass — дедлайны e-class\n/reminders — напоминания\n/alarms — будильники iPhone\n/alarm_setup — настройка будильников\n/panel — веб-панель\n/reset — очистить историю диалога (память останется)"
    )


@dp.message(Command("panel"))
async def cmd_panel(m: Message):
    url = os.getenv("ADMIN_URL")
    if not url:
        return await m.answer("Адрес панели не настроен (ADMIN_URL).")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть панель", web_app=WebAppInfo(url=url))]])
    await m.answer("Панель управления ассистентом:", reply_markup=kb)


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


ALARM_SETUP = """⏰ Настройка будильников — 3 действия, один раз

Открой приложение «Команды» → «+» (новая команда).

1. Нажми «Добавить действие», в поиске набери «URL» → выбери «Получить содержимое URL».
   Нажми на синее слово URL и вставь ссылку из следующего сообщения.
2. В поиске набери «Повторить» → выбери «Повторить с каждым». Больше ничего не трогай.
3. В поиске набери «будильник» → выбери «Добавить будильник» (Часы).
   Перетащи его ВНУТРЬ повтора (между «Повторить» и «Конец повтора»).
   Нажми на поле времени → «Выбрать переменную» → «Повторяемый объект».

Вверху нажми на название и назови «Будильники бота». Нажми ▶️ один раз и разреши всё, что спросит.
Ошибок быть не должно, даже если будильников пока нет."""

ALARM_AUTOMATION = """Последний шаг — чтобы срабатывало само:

«Команды» → вкладка «Автоматизация» → «+» → «Приложение» → выбери Telegram → отметь «Закрыто» (сними «Открыто») → «Запускать сразу» → «Далее» → выбери «Будильники бота».

Готово. Проверь: напиши мне «поставь будильник через 5 минут» и сверни Telegram — будильник появится в «Часах»."""


@dp.message(Command("alarms"))
async def cmd_alarms(m: Message):
    rows = alarms.listing()
    status = {"pending": "ждёт отправки на iPhone", "sent": "стоит на iPhone"}
    await m.answer("\n".join(f"#{r['id']} {r['at']} {r['label'] or ''} — {status[r['status']]}" for r in rows)
                   or "Будильников нет.")
    await m.answer("Настроить iPhone (один раз): /alarm_setup")


@dp.message(Command("alarm_setup"))
async def cmd_alarm_setup(m: Message):
    url = alarms.pull_url()
    if not url:
        return await m.answer("Не знаю свой публичный адрес — задай переменную PUBLIC_URL.")
    await m.answer(ALARM_SETUP)
    await m.answer(url)  # отдельным сообщением: долгое нажатие → «Скопировать»
    await m.answer(ALARM_AUTOMATION)


@dp.message(Command("eclass_login"))
async def cmd_eclass_login(m: Message):
    """Логин/пароль сюда, а не в обычный чат: команда не идёт в Gemini и в историю, сообщение удаляется."""
    args = (m.text or "").split()[1:]
    try:
        await m.delete()
    except Exception as e:
        log.warning("не смог удалить сообщение с паролем: %s", e)
    if len(args) != 2:
        return await m.answer("Отправь одним сообщением: /eclass_login логин пароль\n"
                              "Я обменяю их на токен (как приложение Coursemos), пароль не сохраню, сообщение удалю.")
    try:
        info = await eclass.login(*args)
        msgs = await eclass.sync()
    except Exception as e:
        return await m.answer(f"⚠️ Не получилось подключить e-class: {e}")
    await m.answer(f"✅ e-class подключён: {info.get('fullname', '')}. Пароль не сохранён, твоё сообщение удалено.\n"
                   f"Проверяю задания каждые 2 часа и напоминаю за сутки и за 3 часа до дедлайна, если не сдано.\n\n"
                   f"Совет: смени пароль в e-class — токену бота это обычно не мешает.")
    for t in msgs or ["Несданных заданий сейчас нет 👌"]:
        await m.answer(t)


@dp.message(Command("eclass"))
async def cmd_eclass(m: Message):
    if not eclass.connected():
        return await m.answer("e-class не подключён. Отправь: /eclass_login логин пароль")
    try:
        for t in await eclass.sync():
            await m.answer(t)
    except Exception as e:
        await m.answer(f"⚠️ Не смог проверить сайт: {e}\nПоказываю данные с прошлой проверки.")
    rows = eclass.upcoming()
    await send_long(m.chat.id, "Несданное в e-class:\n" + "\n".join(
        f"• {r['course']}: {r['name']} — до {r['due_local']}" for r in rows) if rows else "Несданных заданий нет 👌")
    await m.answer(f"Аккаунт: {db.kv_get('eclass_user') or '—'}. Отключить: /eclass_logout")


@dp.message(Command("eclass_logout"))
async def cmd_eclass_logout(m: Message):
    eclass.logout()
    await m.answer("e-class отключён, токен удалён.")


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


# ---------- вечерний вопрос для дневника ----------
NUDGE = ("📓 Как прошёл день? Расскажи, что делал, какие были события, как себя чувствовал, "
         "сколько потратил и заработал — я запишу, оценю день и сравню с прошлыми.")


async def journal_nudge():
    at, owner = db.setting("journal_time", "22:00"), db.owner_chat()
    if not owner or not re.fullmatch(r"\d{2}:\d{2}", at):  # «off» — выключено
        return
    now = datetime.now(ZoneInfo(config.TZ))
    day = now.date().isoformat()
    if now.strftime("%H:%M") < at or db.kv_get("journal_nudged") == day:
        return
    db.kv_set("journal_nudged", day)
    if not journal.is_logged(day):
        db.add_message(owner, "model", NUDGE)  # чтобы ответ владельца модель поняла как итоги дня
        await bot.send_message(owner, NUDGE)


# ---------- e-class: проверка дедлайнов ----------
async def eclass_check():
    if not eclass.due_check() or not db.owner_chat():
        return
    db.kv_set("eclass_checked", int(datetime.now().timestamp()))  # даже при ошибке не долбим сайт каждые 20 с
    try:
        msgs = await eclass.sync()
    except eclass.EclassError as e:
        db.log_event("error", "eclass", str(e))
        if not eclass.connected():  # токен умер — скажем один раз
            await bot.send_message(db.owner_chat(), f"⚠️ e-class: {e}")
        return
    except Exception as e:
        db.log_event("error", "eclass", f"{type(e).__name__}: {e}")
        return
    for t in msgs:
        await bot.send_message(db.owner_chat(), t)


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
                        db.log_event("error", "reminder_task", f"{type(e).__name__}: {e}")
                        text = f"⚠️ Не смог выполнить задачу «{r['text']}»: {e}"
                    await send_long(r["chat_id"], text)
                else:
                    await bot.send_message(r["chat_id"], f"⏰ {r['text']}")
            await journal_nudge()
            await eclass_check()
        except Exception:
            log.exception("reminder loop")
        await asyncio.sleep(20)


async def main():
    asyncio.create_task(reminder_loop())
    await api.start(bot)
    log.info("Бот запущен, модель: %s", llm.current_model())
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
