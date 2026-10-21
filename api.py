"""HTTP API для веб-админки. Работает в том же процессе, что и бот, защищён токеном ADMIN_API_TOKEN."""
import hmac
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone

from aiohttp import web
from google.genai import types

import agent
import config
import db
import llm
import tools

log = logging.getLogger(__name__)
STARTED = time.time()
SETTINGS = ("model", "temperature", "history_limit", "instructions")
_bot = None


def _rows(rows):
    return [dict(r) for r in rows]


def _int(req, name, default, lo=0, hi=10_000):
    try:
        return max(lo, min(hi, int(req.query.get(name, default))))
    except ValueError:
        return default


def _rss_mb():
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS"):
                    return round(int(line.split()[1]) / 1024, 1)
    except OSError:
        return None


@web.middleware
async def auth(request, handler):
    if request.path == "/health":
        return await handler(request)
    token = os.getenv("ADMIN_API_TOKEN", "")
    got = request.headers.get("Authorization", "").removeprefix("Bearer ")
    if not token or not hmac.compare_digest(got, token):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except Exception as e:
        log.exception("api %s", request.path)
        return web.json_response({"error": f"{type(e).__name__}: {e}"}, status=400)


routes = web.RouteTableDef()


@routes.get("/health")
async def health(_):
    return web.json_response({"ok": True})


# ---------- обзор ----------
@routes.get("/api/overview")
async def overview(_):
    count = lambda sql, *p: db.q(sql, p, one=True)["c"]
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    tokens = 0
    for r in db.q("SELECT data FROM events WHERE kind='llm' AND created_at>=?", (day_ago,)):
        m = re.search(r"total=(\d+)", r["data"] or "")
        tokens += int(m.group(1)) if m else 0
    last = db.q("SELECT created_at FROM messages ORDER BY id DESC LIMIT 1", one=True)
    db_size = os.path.getsize(config.DB_PATH) if os.path.exists(config.DB_PATH) else 0
    # активность по дням за 14 дней
    activity = _rows(db.q(
        "SELECT substr(created_at,1,10) day, "
        "SUM(kind='llm') llm, SUM(kind='tool') tool, SUM(kind='error') error "
        "FROM events WHERE created_at >= date('now','-13 days') GROUP BY day ORDER BY day"))
    return web.json_response({
        "model": llm.current_model(),
        "owner_id": db.owner_chat(),
        "timezone": config.TZ,
        "uptime_sec": int(time.time() - STARTED),
        "rss_mb": _rss_mb(),
        "db_bytes": db_size,
        "counts": {
            "memories": count("SELECT COUNT(*) c FROM memories"),
            "documents": count("SELECT COUNT(*) c FROM documents"),
            "chunks": count("SELECT COUNT(*) c FROM chunks"),
            "tables": len(db.user_tables()),
            "reminders": count("SELECT COUNT(*) c FROM reminders WHERE done=0"),
            "messages": count("SELECT COUNT(*) c FROM messages"),
        },
        "day": {
            "llm_calls": count("SELECT COUNT(*) c FROM events WHERE kind='llm' AND created_at>=?", day_ago),
            "tool_calls": count("SELECT COUNT(*) c FROM events WHERE kind='tool' AND created_at>=?", day_ago),
            "errors": count("SELECT COUNT(*) c FROM events WHERE kind='error' AND created_at>=?", day_ago),
            "tokens": tokens,
        },
        "top_tools": _rows(db.q("SELECT name, COUNT(*) n FROM events WHERE kind='tool' "
                                "GROUP BY name ORDER BY n DESC LIMIT 8")),
        "activity": activity,
        "last_message_at": last["created_at"] if last else None,
    })


# ---------- переписка ----------
@routes.get("/api/messages")
async def messages(req):
    limit, before = _int(req, "limit", 50, 1, 500), _int(req, "before", 0, 0, 10**12)
    q = req.query.get("q", "").strip()
    sql, p = "SELECT id, role, content, created_at FROM messages WHERE 1=1", []
    if before:
        sql += " AND id < ?"; p.append(before)
    if q:
        sql += " AND content LIKE ?"; p.append(f"%{q}%")
    rows = _rows(db.q(sql + " ORDER BY id DESC LIMIT ?", (*p, limit)))
    return web.json_response({"messages": rows[::-1]})


@routes.post("/api/chat")
async def chat(req):
    """Написать ассистенту из админки — как будто владелец написал в Telegram."""
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        return web.json_response({"error": "пустое сообщение"}, status=400)
    chat_id = db.owner_chat()
    if not chat_id:
        return web.json_response({"error": "владелец ещё не назначен — напиши боту в Telegram"}, status=400)
    reply = await agent.run(chat_id, [types.Part.from_text(text=text)], text)
    if body.get("mirror") and _bot:
        await _bot.send_message(chat_id, f"🖥 Из админки: {text}\n\n{reply}"[:4000])
    return web.json_response({"reply": reply})


@routes.post("/api/send")
async def send(req):
    """Отправить сообщение владельцу в Telegram от имени бота."""
    text = ((await req.json()).get("text") or "").strip()
    if not text or not _bot or not db.owner_chat():
        return web.json_response({"error": "нечего отправлять или нет владельца"}, status=400)
    await _bot.send_message(db.owner_chat(), text[:4000])
    return web.json_response({"ok": True})


@routes.post("/api/reset")
async def reset(_):
    db.reset_history(db.owner_chat())
    return web.json_response({"ok": True})


# ---------- память ----------
@routes.get("/api/memories")
async def memories(req):
    q, cat = req.query.get("q", "").strip(), req.query.get("category", "")
    if q and req.query.get("semantic") == "1":
        v = (await llm.embed([q], "RETRIEVAL_QUERY"))[0]
        rows = [{"id": r["id"], "category": r["category"], "content": r["content"], "score": round(s, 3)}
                for r, s in db.search_memories(v, k=30, min_score=0.3)]
        return web.json_response({"memories": rows})
    sql, p = "SELECT id, category, content, created_at, updated_at FROM memories WHERE 1=1", []
    if cat:
        sql += " AND category=?"; p.append(cat)
    if q:
        sql += " AND content LIKE ?"; p.append(f"%{q}%")
    return web.json_response({"memories": _rows(db.q(sql + " ORDER BY id DESC LIMIT 1000", p))})


@routes.post("/api/memories")
async def memory_add(req):
    b = await req.json()
    v = (await llm.embed([b["content"]]))[0]
    return web.json_response({"id": db.add_memory(b["content"], b.get("category", "note"), v)})


@routes.patch("/api/memories/{id}")
async def memory_edit(req):
    b = await req.json()
    v = (await llm.embed([b["content"]]))[0]
    db.update_memory(int(req.match_info["id"]), b["content"], v, b.get("category"))
    return web.json_response({"ok": True})


@routes.delete("/api/memories/{id}")
async def memory_del(req):
    db.delete_memory(int(req.match_info["id"]))
    return web.json_response({"ok": True})


# ---------- таблицы агента ----------
@routes.get("/api/tables")
async def tables(_):
    out = []
    for t in db.user_tables():
        t["rows"] = db.q(f'SELECT COUNT(*) c FROM "{t["name"]}"', one=True)["c"]
        out.append(t)
    return web.json_response({"tables": out})


@routes.get("/api/tables/{name}")
async def table_rows(req):
    name = req.match_info["name"]
    if name not in {t["name"] for t in db.user_tables()}:
        return web.json_response({"error": "нет такой таблицы"}, status=404)
    limit, offset = _int(req, "limit", 100, 1, 1000), _int(req, "offset", 0, 0, 10**9)
    res = db.run_sandbox_sql(f'SELECT * FROM "{name}" ORDER BY id DESC LIMIT ? OFFSET ?', (limit, offset),
                             max_rows=limit)
    res["total"] = db.q(f'SELECT COUNT(*) c FROM "{name}"', one=True)["c"]
    return web.json_response(res, dumps=_dumps)


@routes.post("/api/sql")
async def sql(req):
    b = await req.json()
    return web.json_response(db.run_sandbox_sql(b["sql"], tuple(b.get("params") or ()), max_rows=1000),
                             dumps=_dumps)


@routes.delete("/api/tables/{name}")
async def table_drop(req):
    name = req.match_info["name"]
    if name not in {t["name"] for t in db.user_tables()}:
        return web.json_response({"error": "нет такой таблицы"}, status=404)
    db.run_sandbox_sql(f'DROP TABLE "{name}"')
    db.ex("DELETE FROM user_tables WHERE name=?", (name,))
    return web.json_response({"ok": True})


# ---------- документы ----------
@routes.get("/api/documents")
async def documents(_):
    rows = _rows(db.q("SELECT d.id, d.title, d.created_at, COUNT(c.id) chunks, COALESCE(SUM(LENGTH(c.content)),0) chars "
                      "FROM documents d LEFT JOIN chunks c ON c.doc_id=d.id GROUP BY d.id ORDER BY d.id DESC"))
    return web.json_response({"documents": rows})


@routes.get("/api/documents/{id}")
async def document_chunks(req):
    rows = _rows(db.q("SELECT idx, content FROM chunks WHERE doc_id=? ORDER BY idx", (int(req.match_info["id"]),)))
    return web.json_response({"chunks": rows})


@routes.post("/api/documents")
async def document_upload(req):
    reader = await req.multipart()
    part = await reader.next()
    if not part or not part.filename:
        return web.json_response({"error": "нужен файл"}, status=400)
    data = await part.read(decode=False)
    n = await agent.ingest_document(part.filename, bytes(data))
    return web.json_response({"ok": True, "chunks": n})


@routes.delete("/api/documents/{id}")
async def document_del(req):
    db.delete_document(int(req.match_info["id"]))
    return web.json_response({"ok": True})


# ---------- напоминания ----------
@routes.get("/api/reminders")
async def reminders(req):
    done = req.query.get("done") == "1"
    rows = _rows(db.q("SELECT id, due_at, text, repeat, kind, done FROM reminders WHERE done=? "
                      "ORDER BY due_at " + ("DESC LIMIT 200" if done else ""), (int(done),)))
    for r in rows:
        r["due_local"] = tools._to_local(r["due_at"])
    return web.json_response({"reminders": rows})


@routes.post("/api/reminders")
async def reminder_add(req):
    b = await req.json()
    return web.json_response(await tools._add_reminder(b["when"], b["text"], b.get("repeat", "none"),
                                                       b.get("kind", "notify"), chat_id=db.owner_chat()))


@routes.delete("/api/reminders/{id}")
async def reminder_del(req):
    db.cancel_reminder(int(req.match_info["id"]))
    return web.json_response({"ok": True})


# ---------- журнал ----------
@routes.get("/api/events")
async def events(req):
    kind, limit = req.query.get("kind", ""), _int(req, "limit", 200, 1, 1000)
    sql, p = "SELECT id, kind, name, data, ms, created_at FROM events", ()
    if kind:
        sql, p = sql + " WHERE kind=?", (kind,)
    return web.json_response({"events": _rows(db.q(sql + " ORDER BY id DESC LIMIT ?", (*p, limit)))})


# ---------- настройки ----------
@routes.get("/api/settings")
async def settings(_):
    return web.json_response({
        "values": {k: db.kv_get(f"set_{k}") or "" for k in SETTINGS},
        "defaults": {"model": config.MODEL, "temperature": "0.7",
                     "history_limit": str(config.HISTORY_LIMIT), "instructions": ""},
    })


@routes.put("/api/settings")
async def settings_save(req):
    b = await req.json()
    for k in SETTINGS:
        if k in b:
            db.kv_set(f"set_{k}", str(b[k]).strip())
    return web.json_response({"ok": True})


@routes.get("/api/models")
async def models(_):
    out = []
    async for m in await llm.client.aio.models.list():
        name = m.name.removeprefix("models/")
        if ("generateContent" in (m.supported_actions or []) and ("flash" in name or "pro" in name)
                and not re.search(r"tts|image|audio|live", name)):
            out.append(name)
    return web.json_response({"models": sorted(set(out))})


def _dumps(obj):
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)


async def start(bot):
    global _bot
    _bot = bot
    if not os.getenv("ADMIN_API_TOKEN"):
        log.warning("ADMIN_API_TOKEN не задан — API админки выключен")
        return
    app = web.Application(middlewares=[auth], client_max_size=25 * 1024 * 1024)
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("API админки слушает :%s", port)
