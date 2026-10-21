"""Цикл агента: контекст (профиль + RAG + история) → Gemini → инструменты → ответ."""
import io
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from google.genai import types

import config
import db
import llm
import tools

log = logging.getLogger(__name__)

SYSTEM = """Ты — личный ИИ-ассистент одного человека (владельца) в Telegram. Ты работаешь с ним каждый день.
Отвечай на языке пользователя, по делу, дружелюбно, без воды. Не используй Markdown-таблицы.

Твои возможности:
- Долговременная память (save_memory/search_memory/update_memory/delete_memory). Сам сохраняй всё, что
  поможет лучше понимать владельца: кто он, чем занимается, предпочтения, люди вокруг, цели, планы.
  Не сохраняй мелочи и одноразовые вещи. Если факт изменился — обнови старую запись.
- Свои таблицы в БД (list_tables/create_table/run_sql). Когда данные структурированные и будут
  накапливаться (расходы, привычки, задачи, вес, книги, контакты) — заведи таблицу и пиши туда.
  Перед созданием проверь list_tables, не дублируй. Для аналитики делай SELECT с агрегатами.
- Напоминания и плановые задачи (add_reminder/list_reminders/cancel_reminder).
- Загруженные документы ищутся через search_memory.

Если не уверен в фактах о владельце — сначала поищи в памяти. Не выдумывай.

Сейчас: {now} ({tz}).

Профиль владельца:
{profile}

Возможно релевантное из памяти:
{relevant}

Из документов:
{docs}

Твои таблицы: {tables}
"""


async def _system_prompt(query_text):
    now = datetime.now(ZoneInfo(config.TZ)).strftime("%A, %Y-%m-%d %H:%M")
    profile = db.list_memories("profile", 40)
    profile_ids = {r["id"] for r in profile}
    relevant, docs = [], []
    if query_text and query_text.strip():
        try:
            qv = (await llm.embed([query_text[:2000]], "RETRIEVAL_QUERY"))[0]
            relevant = [r for r, _ in db.search_memories(qv, k=8) if r["id"] not in profile_ids]
            docs = db.search_chunks(qv, k=4)
        except Exception as e:
            log.warning("RAG недоступен: %s", e)
    fmt = lambda rows: "\n".join(f"[#{r['id']} {r['category']}] {r['content']}" for r in rows) or "—"
    return SYSTEM.format(
        now=now, tz=config.TZ,
        profile=fmt(profile),
        relevant=fmt(relevant),
        docs="\n\n".join(f"«{r['title']}»: {r['content']}" for r, _ in docs) or "—",
        tables=", ".join(t["name"] for t in db.user_tables()) or "пока нет",
    )


async def run(chat_id, user_parts, history_text, query_text=None, save_history=True):
    """user_parts — список types.Part (текст, аудио, картинка). history_text — что записать в историю."""
    system = await _system_prompt(query_text if query_text is not None else history_text)
    contents = [types.Content(role="user" if m["role"] == "user" else "model",
                              parts=[types.Part.from_text(text=m["content"])])
                for m in db.get_history(chat_id, config.HISTORY_LIMIT)]
    contents.append(types.Content(role="user", parts=user_parts))

    text, used = None, []
    for _ in range(10):
        resp = await llm.generate(contents, system, tools.TOOLS)
        if not resp.candidates or not resp.candidates[0].content:
            text = "Модель не вернула ответ (возможно, сработал фильтр). Переформулируй, пожалуйста."
            break
        calls = resp.function_calls or []
        if not calls:
            text = resp.text
            break
        contents.append(resp.candidates[0].content)
        parts = []
        for c in calls:
            result = await tools.call(c.name, dict(c.args or {}), chat_id)
            used.append(c.name)
            log.info("tool %s(%s) -> %s", c.name, dict(c.args or {}), tools.short(result))
            parts.append(types.Part.from_function_response(name=c.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=parts))

    text = (text or "").strip()
    if not text:
        text = "Готово." if used else "Не получилось сформулировать ответ, попробуй ещё раз."
    if save_history:
        db.add_message(chat_id, "user", history_text)
        db.add_message(chat_id, "model", text)
    return text


# ---------- загрузка документов в RAG ----------
def _chunk(text, size=1200, overlap=200):
    text = text.replace("\r", "")
    out, i = [], 0
    while i < len(text):
        piece = text[i:i + size].strip()
        if piece:
            out.append(piece)
        i += size - overlap
    return out


async def ingest_document(title, data: bytes):
    if title.lower().endswith(".pdf"):
        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    else:
        text = data.decode("utf-8", errors="ignore")
    chunks = _chunk(text)
    if not chunks:
        return 0
    embs = await llm.embed(chunks, "RETRIEVAL_DOCUMENT")
    db.add_document(title, chunks, embs)
    return len(chunks)
