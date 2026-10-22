"""e-class INHA (Coursemos на базе Moodle): дедлайны заданий через мобильный веб-сервис Moodle.

Пароль не храним: один раз меняем логин/пароль на токен (как приложение Coursemos), дальше работаем по токену.
Список берём из «Таймлайна» Moodle (core_calendar_get_action_events_by_timesort): там только то, что ещё
нужно сделать — сданное задание из него пропадает само.
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import aiohttp

import config
import db

log = logging.getLogger(__name__)
BASE = "https://eclass.inha.ac.kr"
# сайт обрывает соединение с клиентами, которые не похожи на браузер
UA = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
                    "(KHTML, like Gecko) Mobile/15E148 Safari/604.1"}
CHECK_EVERY = 2 * 3600  # как часто ходить на сайт

db.conn.executescript("""
CREATE TABLE IF NOT EXISTS eclass_tasks (
    id INTEGER PRIMARY KEY,            -- id события Moodle
    course TEXT, name TEXT, module TEXT, url TEXT,
    due INTEGER,                       -- unix-время дедлайна
    open INTEGER DEFAULT 1,            -- 1 — есть в таймлайне (не сдано), 0 — пропало (сдано/закрыто)
    reminded TEXT DEFAULT '',          -- какие напоминания уже отправлены: "new,24h,3h"
    seen_at TEXT DEFAULT CURRENT_TIMESTAMP
);
""")
db.conn.commit()


class EclassError(Exception):
    pass


def connected():
    return bool(db.kv_get("eclass_token"))


async def _post(path, data):
    async with aiohttp.ClientSession(headers=UA, timeout=aiohttp.ClientTimeout(total=40)) as s:
        async with s.post(BASE + path, data=data) as r:
            text = await r.text()
    try:
        return json.loads(text)
    except ValueError:
        raise EclassError(f"сайт ответил не JSON (HTTP {r.status}): {text[:150]}")


async def login(username, password):
    """Логин/пароль → токен. Пароль нигде не сохраняется."""
    res = await _post("/login/token.php", {"username": username, "password": password, "service": "moodle_mobile_app"})
    if not isinstance(res, dict) or not res.get("token"):
        raise EclassError(res.get("error") if isinstance(res, dict) else str(res)[:200])
    db.kv_set("eclass_token", res["token"])
    info = await call("core_webservice_get_site_info")
    db.kv_set("eclass_user", f"{info.get('fullname', '')} ({info.get('username', username)})")
    return info


def logout():
    db.kv_set("eclass_token", "")
    db.ex("DELETE FROM eclass_tasks")


async def call(fn, **params):
    token = db.kv_get("eclass_token")
    if not token:
        raise EclassError("e-class не подключён — /eclass_login")
    res = await _post("/webservice/rest/server.php",
                      {"wstoken": token, "wsfunction": fn, "moodlewsrestformat": "json", **params})
    if isinstance(res, dict) and res.get("exception"):
        if res.get("errorcode") in ("invalidtoken", "accessexception"):
            db.kv_set("eclass_token", "")
            raise EclassError("токен e-class больше не действует — подключи заново: /eclass_login")
        raise EclassError(f"{res.get('errorcode')}: {res.get('message')}")
    return res


async def fetch():
    """Что сейчас висит в таймлайне: задания, тесты и т.п. с дедлайнами начиная с сегодня."""
    now = int(datetime.now().timestamp())
    res = await call("core_calendar_get_action_events_by_timesort",
                     timesortfrom=now - 86400, limitnum=50, limittononsuspendedevents=1)
    out = []
    for e in res.get("events", []):
        action = e.get("action") or {}
        if action and not action.get("actionable", True):
            continue  # например, ещё не открыто для сдачи
        out.append({"id": e["id"], "name": e.get("activityname") or e.get("name", ""),
                    "course": (e.get("course") or {}).get("fullname", ""), "module": e.get("modulename", ""),
                    "url": e.get("url", ""), "due": e.get("timesort") or e.get("timestart")})
    return out


def _fmt(ts):
    return datetime.fromtimestamp(ts, ZoneInfo(config.TZ)).strftime("%d.%m %H:%M")


def _windows(due, now):
    """Окна напоминаний, в которые дедлайн уже попал: 3h включает и 24h, чтобы не слать оба сразу."""
    left = due - now
    return {"24h", "3h"} if left <= 3 * 3600 else {"24h"} if left <= 24 * 3600 else set()


def _line(t):
    return f"• {t['course']}: {t['name']} — до {_fmt(t['due'])}"


async def sync():
    """Обновляет таблицу и возвращает тексты уведомлений (новые задания и напоминания о дедлайнах)."""
    tasks = await fetch()
    now = int(datetime.now().timestamp())
    known = {r["id"]: dict(r) for r in db.q("SELECT * FROM eclass_tasks")}
    ids = {t["id"] for t in tasks}
    new, soon = [], []
    for t in tasks:
        if t["id"] not in known:
            db.ex("INSERT INTO eclass_tasks(id,course,name,module,url,due,reminded) VALUES(?,?,?,?,?,?,?)",
                  (t["id"], t["course"], t["name"], t["module"], t["url"], t["due"],
                   ",".join(sorted({"new"} | _windows(t["due"], now)))))  # о новом и так сообщим
            new.append(t)
            continue
        db.ex("UPDATE eclass_tasks SET course=?, name=?, url=?, due=?, open=1 WHERE id=?",
              (t["course"], t["name"], t["url"], t["due"], t["id"]))
        sent = set(known[t["id"]]["reminded"].split(","))
        fresh = _windows(t["due"], now) - sent
        if fresh and t["due"] > now:
            soon.append((t, "3h" if "3h" in fresh else "24h"))
            sent |= fresh
        db.ex("UPDATE eclass_tasks SET reminded=? WHERE id=?", (",".join(sorted(s for s in sent if s)), t["id"]))
    # пропало из таймлайна — сдано или закрыто
    for i in set(known) - ids:
        db.ex("UPDATE eclass_tasks SET open=0 WHERE id=?", (i,))
    db.kv_set("eclass_checked", now)

    msgs = []
    if new:
        msgs.append("📚 Новое в e-class:\n" + "\n".join(_line(t) for t in sorted(new, key=lambda x: x["due"])))
    for t, tag in soon:
        msgs.append(f"⏰ {'Меньше суток' if tag == '24h' else 'Меньше 3 часов'} до дедлайна, а задание ещё не сдано:\n{_line(t)}"
                    + (f"\n{t['url']}" if t["url"] else ""))
    return msgs


def upcoming():
    now = int(datetime.now().timestamp())
    rows = db.q("SELECT course, name, module, url, due FROM eclass_tasks WHERE open=1 AND due >= ? ORDER BY due", (now,))
    return [{**dict(r), "due_local": _fmt(r["due"])} for r in rows]


def due_check():
    last = int(db.kv_get("eclass_checked") or 0)
    return connected() and datetime.now().timestamp() - last >= CHECK_EVERY
