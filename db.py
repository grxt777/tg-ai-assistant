"""SQLite: системные таблицы агента + песочница для таблиц, которые агент создаёт сам (префикс u_)."""
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import numpy as np

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, chat_id INTEGER, role TEXT, content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY, category TEXT, content TEXT, embedding BLOB,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY, title TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    idx INTEGER, content TEXT, embedding BLOB
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY, chat_id INTEGER, due_at TEXT, text TEXT,
    repeat TEXT DEFAULT 'none',      -- none | daily | weekly
    kind TEXT DEFAULT 'notify',      -- notify (просто прислать) | task (агент выполняет задачу)
    done INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS user_tables (
    name TEXT PRIMARY KEY, description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- журнал для админки: вызовы инструментов, запросы к модели, ошибки
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, kind TEXT, name TEXT, data TEXT, ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS events_created ON events(created_at);
"""

_lock = threading.Lock()
conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("PRAGMA foreign_keys=ON")
conn.executescript(SCHEMA)
conn.commit()


def q(sql, params=(), one=False):
    with _lock:
        cur = conn.execute(sql, params)
        rows = cur.fetchall()
        conn.commit()
        return (rows[0] if rows else None) if one else rows


def ex(sql, params=()):
    with _lock:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid


# ---------- kv ----------
def kv_get(key):
    r = q("SELECT value FROM kv WHERE key=?", (key,), one=True)
    return r["value"] if r else None


def kv_set(key, value):
    ex("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


# ---------- настройки (меняются из админки без редеплоя) ----------
def setting(key, default=None, cast=str):
    v = kv_get(f"set_{key}")
    if v in (None, ""):
        return default
    try:
        return cast(v)
    except ValueError:
        return default


def owner_chat():
    return config.OWNER_ID or int(kv_get("owner_id") or 0)


# ---------- журнал событий ----------
def log_event(kind, name, data="", ms=None):
    ex("INSERT INTO events(kind,name,data,ms) VALUES(?,?,?,?)", (kind, name, str(data)[:4000], ms))


# ---------- история ----------
def add_message(chat_id, role, content):
    ex("INSERT INTO messages(chat_id,role,content) VALUES(?,?,?)", (chat_id, role, content))


def get_history(chat_id, limit):
    rows = q("SELECT role, content FROM messages WHERE chat_id=? AND id > ? ORDER BY id DESC LIMIT ?",
             (chat_id, int(kv_get(f"reset_{chat_id}") or 0), limit))
    return list(reversed(rows))


def reset_history(chat_id):
    r = q("SELECT MAX(id) m FROM messages", one=True)
    kv_set(f"reset_{chat_id}", r["m"] or 0)


# ---------- векторы ----------
def _blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def _topk(rows, qv, k, min_score):
    if not rows:
        return []
    mat = np.vstack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
    scores = mat @ qv
    order = np.argsort(-scores)[:k]
    return [(rows[i], float(scores[i])) for i in order if scores[i] >= min_score]


# ---------- память ----------
def add_memory(content, category, emb):
    return ex("INSERT INTO memories(category,content,embedding) VALUES(?,?,?)", (category, content, _blob(emb)))


def update_memory(mid, content, emb, category=None):
    if category:
        ex("UPDATE memories SET content=?, embedding=?, category=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
           (content, _blob(emb), category, mid))
    else:
        ex("UPDATE memories SET content=?, embedding=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
           (content, _blob(emb), mid))


def delete_memory(mid):
    ex("DELETE FROM memories WHERE id=?", (mid,))


def list_memories(category=None, limit=200):
    if category:
        return q("SELECT id,category,content FROM memories WHERE category=? ORDER BY id DESC LIMIT ?", (category, limit))
    return q("SELECT id,category,content FROM memories ORDER BY id DESC LIMIT ?", (limit,))


def search_memories(qv, k=8, min_score=0.55):
    rows = q("SELECT id,category,content,embedding FROM memories")
    return _topk(rows, qv, k, min_score)


# ---------- документы (RAG) ----------
def add_document(title, chunks, embs):
    did = ex("INSERT INTO documents(title) VALUES(?)", (title,))
    with _lock:
        conn.executemany("INSERT INTO chunks(doc_id,idx,content,embedding) VALUES(?,?,?,?)",
                         [(did, i, c, _blob(e)) for i, (c, e) in enumerate(zip(chunks, embs))])
        conn.commit()
    return did


def list_documents():
    return q("SELECT d.id, d.title, COUNT(c.id) n FROM documents d LEFT JOIN chunks c ON c.doc_id=d.id GROUP BY d.id ORDER BY d.id DESC")


def delete_document(did):
    ex("DELETE FROM documents WHERE id=?", (did,))


def search_chunks(qv, k=5, min_score=0.55):
    rows = q("SELECT c.id, c.content, c.embedding, d.title FROM chunks c JOIN documents d ON d.id=c.doc_id")
    return _topk(rows, qv, k, min_score)


# ---------- напоминания (время хранится в UTC) ----------
def add_reminder(chat_id, due_utc: datetime, text, repeat="none", kind="notify"):
    return ex("INSERT INTO reminders(chat_id,due_at,text,repeat,kind) VALUES(?,?,?,?,?)",
              (chat_id, due_utc.strftime("%Y-%m-%d %H:%M:%S"), text, repeat, kind))


def list_reminders(chat_id):
    return q("SELECT id,due_at,text,repeat,kind FROM reminders WHERE chat_id=? AND done=0 ORDER BY due_at", (chat_id,))


def cancel_reminder(rid):
    ex("UPDATE reminders SET done=1 WHERE id=?", (rid,))


def due_reminders():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return q("SELECT * FROM reminders WHERE done=0 AND due_at<=?", (now,))


def advance_reminder(r):
    if r["repeat"] in ("daily", "weekly"):
        due = datetime.strptime(r["due_at"], "%Y-%m-%d %H:%M:%S")
        step = timedelta(days=1 if r["repeat"] == "daily" else 7)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        while due <= now:
            due += step
        ex("UPDATE reminders SET due_at=? WHERE id=?", (due.strftime("%Y-%m-%d %H:%M:%S"), r["id"]))
    else:
        ex("UPDATE reminders SET done=1 WHERE id=?", (r["id"],))


# ---------- песочница для таблиц агента ----------
PREFIX = "u_"
_SYS_OK = {"sqlite_master", "sqlite_schema", "sqlite_temp_master", "sqlite_sequence"}
_ARG1 = {sqlite3.SQLITE_READ, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_INSERT, sqlite3.SQLITE_DELETE,
         sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_CREATE_VIEW,
         sqlite3.SQLITE_DROP_VIEW}
_ARG2 = {sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX, sqlite3.SQLITE_ALTER_TABLE,
         sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_DROP_TRIGGER}
_ALWAYS = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_TRANSACTION,
           sqlite3.SQLITE_SAVEPOINT, getattr(sqlite3, "SQLITE_RECURSIVE", 33)}


def _ok(name):
    return bool(name) and (name.lower().startswith(PREFIX) or name.lower() in _SYS_OK)


def _authorizer(action, a1, a2, dbname, src):
    if action in _ALWAYS:
        return sqlite3.SQLITE_OK
    if action in _ARG1:
        return sqlite3.SQLITE_OK if _ok(a1) else sqlite3.SQLITE_DENY
    if action in _ARG2:
        return sqlite3.SQLITE_OK if _ok(a2) else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_PRAGMA and a1 in ("table_info", "table_xinfo", "index_list") and _ok(a2):
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY  # ATTACH, PRAGMA, доступ к системным таблицам и т.д.


sandbox = sqlite3.connect(config.DB_PATH, check_same_thread=False)
sandbox.row_factory = sqlite3.Row
sandbox.set_authorizer(_authorizer)


def run_sandbox_sql(sql, params=(), max_rows=50):
    with _lock:
        cur = sandbox.execute(sql, params)
        if cur.description:
            cols = [d[0] for d in cur.description]
            rows = cur.fetchmany(max_rows + 1)
            sandbox.commit()
            more = len(rows) > max_rows
            data = [{c: (v if not isinstance(v, bytes) else f"<{len(v)} bytes>") for c, v in zip(cols, r)}
                    for r in rows[:max_rows]]
            return {"columns": cols, "rows": data, "truncated": more}
        sandbox.commit()
        return {"rowcount": cur.rowcount, "lastrowid": cur.lastrowid}


def user_tables():
    rows = q("SELECT name, sql FROM sqlite_master WHERE type='table' AND name LIKE 'u\\_%' ESCAPE '\\'")
    desc = {r["name"]: r["description"] for r in q("SELECT name, description FROM user_tables")}
    return [{"name": r["name"], "schema": r["sql"], "description": desc.get(r["name"], "")} for r in rows]


def register_table(name, description):
    ex("INSERT INTO user_tables(name,description) VALUES(?,?) ON CONFLICT(name) DO UPDATE SET description=excluded.description",
       (name, description))
