"""Цикл агента: контекст (профиль + RAG + история) → Gemini → инструменты → ответ."""
import io
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from google.genai import types

import config
import db
import journal
import llm
import tools

log = logging.getLogger(__name__)

SYSTEM = """Ты — личный ИИ-ассистент одного человека (владельца) в Telegram. Ты работаешь с ним каждый день.
Отвечай на языке пользователя, по делу, дружелюбно, без воды. Пиши простым текстом без Markdown
(никаких **, #, таблиц) — сообщения показываются как есть. Для списков используй «•» или «—».

Твои возможности:
- Долговременная память (save_memory/search_memory/update_memory/delete_memory). Сам сохраняй всё, что
  поможет лучше понимать владельца: кто он, чем занимается, предпочтения, люди вокруг, цели, планы.
  Не сохраняй мелочи и одноразовые вещи. Если факт изменился — обнови старую запись.
- Свои таблицы в БД (list_tables/create_table/run_sql). Когда данные структурированные и будут
  накапливаться (расходы, привычки, задачи, вес, книги, контакты) — заведи таблицу и пиши туда.
  Перед созданием проверь list_tables, не дублируй. Для аналитики делай SELECT с агрегатами.
- Напоминания и плановые задачи (add_reminder/list_reminders/cancel_reminder).
- Загруженные документы ищутся через search_memory.
- Дневник (journal_log/journal_day/journal_delete/journal_stats). Когда владелец рассказывает, как прошёл
  день, что делал, о событиях, мыслях, тратах или заработке — записывай через journal_log: резюме дня,
  события и заметки по пунктам, деньги в сумах. Деньги и дни веди ТОЛЬКО в дневнике, не заводи для них
  свои таблицы. Если владелец пишет ночью (до 5 утра) про «сегодня» — скорее всего, это про вчерашнюю дату.
- Оценки дня (1–10) ставишь ТЫ САМ, владельца не спрашиваешь — как честный наставник, без лести:
  • насыщенность — сколько значимого произошло (рутина дома ≈ 3, обычный рабочий день ≈ 5, много дел и встреч ≈ 8+);
  • настроение — по тону рассказа и событиям;
  • энергия — сон, спорт, здоровье, усталость;
  • продуктивность — что реально сделано по работе, учёбе и целям владельца из памяти;
  • итог — общий вклад дня в жизнь владельца: прогресс к целям, здоровье, отношения, деньги
    (заработок — плюс, траты сильно выше обычного или импульсивные — минус).
  5 — обычный средний день. Держи шкалу стабильной: сравнивай с последними днями ниже, чтобы похожий день
  получал похожую оценку. В verdict объясни оценку и сравни с историей: лучше или хуже обычного, растёт ли
  тренд за неделю против предыдущих недель, что тянет вверх и что вниз. В ответе владельцу коротко: оценки,
  почему, и улучшается ли он. Если владелец не согласен с оценкой — пересмотри (это его жизнь).
  Если данных о дне мало — оцени то, что можно, остальное оставь пустым, и спроси одну-две детали.
- Для аналитики («как неделя», «сколько потратил за месяц», «прогресс за год») вызывай journal_stats и
  опирайся на его цифры, сравнивай с прошлым периодом, отмечай тренды и давай 1–2 конкретных наблюдения.

Если не уверен в фактах о владельце — сначала поищи в памяти. Не выдумывай.

Сейчас: {now} ({tz}).

Профиль владельца:
{profile}

Возможно релевантное из памяти:
{relevant}

Из документов:
{docs}

Дневник за сегодня: {today}

Последние дни дневника (для калибровки оценок и тренда):
{recent}

Твои таблицы: {tables}
{instructions}"""


def _sum(x):
    return f"{x:,.0f}".replace(",", " ")


def _today_journal():
    d = journal.get_day()
    scores = ", ".join(f"{k}={d[k]}" for k in journal.SCORES if d[k] is not None)
    parts = [d["summary"], scores and f"оценки: {scores}",
             d["entries"] and f"записей: {len(d['entries'])}",
             d["transactions"] and f"доход {_sum(d['income'])}, расход {_sum(d['expense'])} сум"]
    return " · ".join(p for p in parts if p) or "пока ничего не записано"


def _recent_journal():
    rows = journal.recent(14)
    if not rows:
        return "— (записей пока нет: шкала с нуля, 5 = обычный день)"
    short = {"busy": "нас", "mood": "настр", "energy": "эн", "productivity": "прод"}
    lines = [f"{r['date']} итог {r['score']} ("
             + ", ".join(f"{short[k]} {r[k]}" for k in journal.PARAMS if r[k] is not None)
             + f"), расход {_sum(r['expense'])}: {r['summary'][:100]}" for r in rows]
    s7, s30 = journal.stats(7), journal.stats(30)
    lines.append(f"Средний итог: 7 дней {s7['avg']['score']}, предыдущие 7 {s7['prev']['avg']['score']}, "
                 f"30 дней {s30['avg']['score']}, предыдущие 30 {s30['prev']['avg']['score']}")
    return "\n".join(lines)


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
        today=_today_journal(),
        recent=_recent_journal(),
        tables=", ".join(t["name"] for t in db.user_tables()) or "пока нет",
        instructions=(f"\nДополнительные указания владельца:\n{extra}\n"
                      if (extra := db.setting("instructions", "")) else ""),
    )


async def run(chat_id, user_parts, history_text, query_text=None, save_history=True):
    """user_parts — список types.Part (текст, аудио, картинка). history_text — что записать в историю."""
    system = await _system_prompt(query_text if query_text is not None else history_text)
    contents = [types.Content(role="user" if m["role"] == "user" else "model",
                              parts=[types.Part.from_text(text=m["content"])])
                for m in db.get_history(chat_id, db.setting("history_limit", config.HISTORY_LIMIT, int))]
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
            t0 = time.monotonic()
            result = await tools.call(c.name, dict(c.args or {}), chat_id)
            used.append(c.name)
            log.info("tool %s(%s) -> %s", c.name, dict(c.args or {}), tools.short(result))
            db.log_event("error" if isinstance(result, dict) and "error" in result else "tool", c.name,
                         tools.short({"args": dict(c.args or {}), "result": result}),
                         int((time.monotonic() - t0) * 1000))
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
