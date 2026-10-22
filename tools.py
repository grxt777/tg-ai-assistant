"""Инструменты, которые агент вызывает сам (function calling)."""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from google.genai import types

import alarms
import config
import db
import eclass
import journal
import llm

S, I = {"type": "STRING"}, {"type": "INTEGER"}
DATE = {"type": "STRING", "description": "YYYY-MM-DD, по умолчанию сегодня"}
SCORE = {"type": "INTEGER", "description": "1–10"}


def _fn(name, desc, props=None, required=()):
    params = {"type": "OBJECT", "properties": props, "required": list(required)} if props else None
    return types.FunctionDeclaration(name=name, description=desc, parameters=params)


DECLARATIONS = [
    _fn("save_memory",
        "Сохранить в долговременную память факт о пользователе: предпочтения, привычки, люди, цели, "
        "важные события, решения. Вызывай САМ, без просьбы, когда узнаёшь что-то полезное надолго. "
        "Одна мысль — одна запись, формулируй от третьего лица.",
        {"content": S,
         "category": {"type": "STRING", "enum": ["profile", "preference", "person", "goal", "event", "note"],
                      "description": "profile — базовые факты о пользователе (всегда в контексте)"}},
        ["content", "category"]),
    _fn("search_memory", "Семантический поиск по памяти и загруженным документам.", {"query": S}, ["query"]),
    _fn("update_memory", "Изменить запись памяти, если факт устарел.", {"id": I, "content": S}, ["id", "content"]),
    _fn("delete_memory", "Удалить запись памяти.", {"id": I}, ["id"]),
    _fn("list_tables", "Показать таблицы, созданные агентом (их схемы и описание)."),
    _fn("create_table",
        "Создать свою таблицу для структурированных данных (расходы, тренировки, задачи, книги...). "
        "Имя без префикса, он добавится сам (u_). Колонка id INTEGER PRIMARY KEY и created_at добавятся автоматически.",
        {"name": {"type": "STRING", "description": "латиница, snake_case, напр. expenses"},
         "columns": {"type": "STRING", "description": "SQL-определения колонок, напр. 'amount REAL, category TEXT, note TEXT'"},
         "description": S},
        ["name", "columns", "description"]),
    _fn("run_sql",
        "Выполнить SQL (SQLite) над СВОИМИ таблицами u_*: SELECT/INSERT/UPDATE/DELETE/ALTER/CREATE INDEX. "
        "Используй ? и params для значений.",
        {"sql": S, "params": {"type": "ARRAY", "items": {"type": "STRING"}}},
        ["sql"]),
    _fn("add_reminder",
        "Поставить напоминание или плановую задачу. kind=notify — просто прислать текст; "
        "kind=task — в это время ты сам выполнишь задачу (например утренний брифинг) и пришлёшь результат.",
        {"when": {"type": "STRING", "description": "локальное время пользователя 'YYYY-MM-DD HH:MM'"},
         "text": S,
         "repeat": {"type": "STRING", "enum": ["none", "daily", "weekly"]},
         "kind": {"type": "STRING", "enum": ["notify", "task"]}},
        ["when", "text"]),
    _fn("list_reminders", "Список активных напоминаний."),
    _fn("cancel_reminder", "Отменить напоминание по id.", {"id": I}, ["id"]),
    _fn("set_alarm",
        "Поставить настоящий будильник на iPhone владельца (звонит даже в беззвучном режиме, в отличие от "
        "add_reminder). Используй, когда просят разбудить или поставить будильник. Повторяющиеся будильники "
        "не поддерживаются — для них посоветуй поставить в «Часах» вручную.",
        {"when": {"type": "STRING", "description": "локальное время 'YYYY-MM-DD HH:MM'"},
         "label": {"type": "STRING", "description": "подпись, напр. «Подъём» или «Созвон»"}},
        ["when"]),
    _fn("list_alarms", "Будильники iPhone, которые ждут отправки или уже поставлены."),
    _fn("cancel_alarm", "Отменить будильник iPhone по id.", {"id": I}, ["id"]),
    _fn("eclass_tasks",
        "Несданные задания и дедлайны из e-class INHA (университет владельца). refresh=true — сначала "
        "сходить на сайт за свежими данными (иначе — из последней проверки, она бывает раз в 2 часа).",
        {"refresh": {"type": "BOOLEAN"}}),
    _fn("journal_log",
        "Записать в дневник: итоги дня, оценки, события, заметки, доходы и расходы (в сумах). Оценки ставишь САМ "
        "по правилам из системного промпта, владельца не спрашиваешь. Вызывай, когда "
        "владелец рассказывает, как прошёл день, что делал, или сообщает о трате/заработке — даже об одной. "
        "Можно вызывать сколько угодно раз за день: события и деньги ДОБАВЛЯЮТСЯ (не повторяй уже записанное), "
        "summary и оценки ПЕРЕЗАПИСЫВАЮТСЯ — передавай их только когда есть что обновить.",
        {"date": DATE,
         "summary": {"type": "STRING", "description": "резюме всего дня в 1–3 предложения; если за день уже "
                     "было резюме — объедини старое с новым"},
         "score": {"type": "INTEGER", "description": "итоговая оценка дня 1–10 (твоя)"},
         "verdict": {"type": "STRING", "description": "твоё объяснение оценок в 1–3 предложения: что было "
                     "хорошо/плохо и как день выглядит на фоне последних дней (лучше/хуже обычного, тренд)"},
         "scores": {"type": "ARRAY", "description": "твои оценки по критериям из системного промпта (ключ критерия → 1–10); "
                    "критерий, по которому в дне нет информации, пропусти",
                    "items": {"type": "OBJECT", "properties": {"param": S, "value": I}, "required": ["param", "value"]}},
         "entries": {"type": "ARRAY", "description": "что происходило: события и заметки/мысли, по одному на пункт",
                     "items": {"type": "OBJECT", "properties": {
                         "kind": {"type": "STRING", "enum": ["event", "note"]},
                         "category": {"type": "STRING", "description": "работа, учёба, спорт, здоровье, люди, "
                                      "семья, отдых, быт, финансы, другое"},
                         "text": S}, "required": ["kind", "text"]}},
         "transactions": {"type": "ARRAY", "description": "деньги в сумах (переведи «50к» → 50000, «1.2 млн» → 1200000)",
                          "items": {"type": "OBJECT", "properties": {
                              "type": {"type": "STRING", "enum": ["income", "expense"]},
                              "amount": {"type": "NUMBER"},
                              "category": {"type": "STRING", "description":
                                           "расход: еда, кафе, транспорт, жильё, связь, здоровье, одежда, развлечения, "
                                           "подарки, образование, техника, долги, другое; доход: зарплата, фриланс, "
                                           "бизнес, подарок, долги, другое"},
                              "note": S}, "required": ["type", "amount", "category"]}}}),
    _fn("journal_params",
        "Критерии оценки дня. action=list — показать все (вкл. выключенные); action=save — добавить новый или "
        "изменить существующий (label, description, active=false — выключить). Новый критерий добавляй ТОЛЬКО после "
        "явного согласия владельца; сам можешь лишь предложить, если тема часто повторяется.",
        {"action": {"type": "STRING", "enum": ["list", "save"]},
         "key": {"type": "STRING", "description": "латиница snake_case, напр. sleep"},
         "label": {"type": "STRING", "description": "название по-русски, напр. Сон"},
         "description": {"type": "STRING", "description": "как оценивать: что тянет вверх, что вниз, что считать 5"},
         "active": {"type": "BOOLEAN"}},
        ["action"]),
    _fn("journal_day", "Показать запись дневника за день: резюме, оценки, события, деньги (с id для удаления).",
        {"date": DATE}),
    _fn("journal_delete", "Удалить ошибочную запись дневника: entry или transaction по id, либо day целиком по date.",
        {"kind": {"type": "STRING", "enum": ["entry", "transaction", "day"]}, "id": I, "date": DATE}, ["kind"]),
    _fn("journal_stats",
        "Аналитика дневника за последние N дней (7 — неделя, 30 — месяц, 365 — год) со сравнением с предыдущим "
        "таким же периодом: доходы, расходы, баланс, траты по категориям, средние оценки, лучшие/худшие дни, серия. "
        "Цифры уже посчитаны — не пересчитывай их сам.",
        {"days": I}, ["days"]),
]

TOOLS = [types.Tool(function_declarations=DECLARATIONS)]


async def _save_memory(content, category="note", **_):
    v = (await llm.embed([content]))[0]
    dup = db.search_memories(v, k=1, min_score=0.92)
    if dup:
        db.update_memory(dup[0][0]["id"], content, v, category)
        return {"ok": True, "updated_id": dup[0][0]["id"]}
    return {"ok": True, "id": db.add_memory(content, category, v)}


async def _search_memory(query, **_):
    v = (await llm.embed([query], "RETRIEVAL_QUERY"))[0]
    mem = [{"id": r["id"], "category": r["category"], "content": r["content"], "score": round(s, 3)}
           for r, s in db.search_memories(v, k=10, min_score=0.45)]
    docs = [{"doc": r["title"], "content": r["content"], "score": round(s, 3)}
            for r, s in db.search_chunks(v, k=5, min_score=0.45)]
    return {"memories": mem, "documents": docs}


async def _update_memory(id, content, **_):
    v = (await llm.embed([content]))[0]
    db.update_memory(int(id), content, v)
    return {"ok": True}


async def _delete_memory(id, **_):
    db.delete_memory(int(id))
    return {"ok": True}


async def _list_tables(**_):
    return {"tables": db.user_tables()}


async def _create_table(name, columns, description="", **_):
    name = re.sub(r"[^a-z0-9_]", "", name.lower().removeprefix(db.PREFIX))
    if not name:
        return {"error": "некорректное имя"}
    full = db.PREFIX + name
    sql = (f"CREATE TABLE IF NOT EXISTS {full} (id INTEGER PRIMARY KEY, {columns}, "
           f"created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    db.run_sandbox_sql(sql)
    db.register_table(full, description)
    return {"ok": True, "table": full}


async def _run_sql(sql, params=None, **_):
    return db.run_sandbox_sql(sql, tuple(params or ()))


def _tz():
    return ZoneInfo(config.TZ)


async def _add_reminder(when, text, repeat="none", kind="notify", chat_id=None, **_):
    local = datetime.strptime(when.strip()[:16], "%Y-%m-%d %H:%M").replace(tzinfo=_tz())
    utc = local.astimezone(timezone.utc).replace(tzinfo=None)
    rid = db.add_reminder(chat_id, utc, text, repeat or "none", kind or "notify")
    return {"ok": True, "id": rid, "when_local": local.strftime("%Y-%m-%d %H:%M")}


def _to_local(utc_str):
    dt = datetime.strptime(utc_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt.astimezone(_tz()).strftime("%Y-%m-%d %H:%M")


async def _list_reminders(chat_id=None, **_):
    return {"reminders": [{"id": r["id"], "when": _to_local(r["due_at"]), "text": r["text"],
                           "repeat": r["repeat"], "kind": r["kind"]} for r in db.list_reminders(chat_id)]}


async def _cancel_reminder(id, **_):
    db.cancel_reminder(int(id))
    return {"ok": True}


async def _set_alarm(when, label="", **_):
    return {"ok": True, **alarms.add(when, label)}


async def _list_alarms(**_):
    return {"alarms": alarms.listing()}


async def _cancel_alarm(id, **_):
    return alarms.cancel(id)


async def _eclass_tasks(refresh=False, **_):
    if not eclass.connected():
        return {"error": "e-class не подключён: владелец должен один раз отправить /eclass_login логин пароль"}
    if refresh:
        await eclass.sync()
    return {"tasks": eclass.upcoming(), "checked_at": db.kv_get("eclass_checked")}


async def _journal_log(date=None, summary=None, entries=None, transactions=None, verdict=None, **kw):
    emb = (await llm.embed([f"{date or journal.today()}: {summary}"]))[0] if summary else None
    scores = {s.get("param"): s.get("value") for s in kw.get("scores") or []}
    scores["score"] = kw.get("score")
    day = journal.log_day(date, summary, scores, entries, transactions, emb, verdict)
    day.pop("params", None)
    day.pop("updated_at", None)
    return {"ok": True, "day": day}


async def _journal_params(action="list", key=None, label=None, description=None, active=None, **_):
    if action == "save":
        return {"ok": True, "param": journal.save_param(key, label, description, active)}
    return {"params": journal.params(all=True)}


async def _journal_day(date=None, **_):
    return journal.get_day(date)


async def _journal_delete(kind, id=None, date=None, **_):
    journal.delete(kind, id, date)
    return {"ok": True}


async def _journal_stats(days=7, **_):
    s = journal.stats(days)
    if s["days"] > 31:  # за длинный период модели хватит помесячной разбивки
        s.pop("series")
    else:
        s.pop("by_month")
    return s


HANDLERS = {
    "save_memory": _save_memory, "search_memory": _search_memory, "update_memory": _update_memory,
    "delete_memory": _delete_memory, "list_tables": _list_tables, "create_table": _create_table,
    "run_sql": _run_sql, "add_reminder": _add_reminder, "list_reminders": _list_reminders,
    "cancel_reminder": _cancel_reminder, "journal_log": _journal_log, "journal_day": _journal_day,
    "journal_params": _journal_params, "set_alarm": _set_alarm, "list_alarms": _list_alarms,
    "cancel_alarm": _cancel_alarm, "eclass_tasks": _eclass_tasks,
    "journal_delete": _journal_delete, "journal_stats": _journal_stats,
}


async def call(name, args, chat_id):
    fn = HANDLERS.get(name)
    if not fn:
        return {"error": f"нет инструмента {name}"}
    try:
        return await fn(**args, chat_id=chat_id)
    except Exception as e:  # ошибку отдаём модели — она сама поправит запрос
        return {"error": f"{type(e).__name__}: {e}"}


def short(result):
    s = json.dumps(result, ensure_ascii=False, default=str)
    return s if len(s) < 300 else s[:300] + "…"
