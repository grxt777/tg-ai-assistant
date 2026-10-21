"""Инструменты, которые агент вызывает сам (function calling)."""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from google.genai import types

import config
import db
import llm

S, I = {"type": "STRING"}, {"type": "INTEGER"}


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


HANDLERS = {
    "save_memory": _save_memory, "search_memory": _search_memory, "update_memory": _update_memory,
    "delete_memory": _delete_memory, "list_tables": _list_tables, "create_table": _create_table,
    "run_sql": _run_sql, "add_reminder": _add_reminder, "list_reminders": _list_reminders,
    "cancel_reminder": _cancel_reminder,
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
