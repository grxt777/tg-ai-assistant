"""Будильники iPhone: бот складывает их в очередь, команда в «Командах» iOS забирает и ставит в «Часы».

iOS-будильник знает только время (HH:MM) и звонит в ближайшее такое время, поэтому отдаём только те,
что сработают в ближайшие 24 часа — дальние ждут в очереди до следующего запуска команды.
"""
import hmac
import os
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
import db

db.conn.executescript("""
CREATE TABLE IF NOT EXISTS alarms (
    id INTEGER PRIMARY KEY, at TEXT, label TEXT,  -- at: локальное время 'YYYY-MM-DD HH:MM'
    status TEXT DEFAULT 'pending',                 -- pending | sent | cancelled | missed
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, sent_at TEXT
);
""")
db.conn.commit()

FMT = "%Y-%m-%d %H:%M"


def _now():
    return datetime.now(ZoneInfo(config.TZ)).replace(tzinfo=None, second=0, microsecond=0)


def key():
    """Отдельный секрет для команды на iPhone (не токен админки)."""
    k = db.kv_get("alarm_key")
    if not k:
        k = secrets.token_urlsafe(24)
        db.kv_set("alarm_key", k)
    return k


def check_key(got):
    return bool(got) and hmac.compare_digest(got, key())


def pull_url():
    base = os.getenv("PUBLIC_URL") or (f"https://{os.environ['FLY_APP_NAME']}.fly.dev" if os.getenv("FLY_APP_NAME") else "")
    return f"{base.rstrip('/')}/alarms/pull"


def add(when, label=""):
    at = datetime.strptime(when.strip()[:16], FMT)
    if at <= _now():
        raise ValueError(f"время {at.strftime(FMT)} уже прошло")
    aid = db.ex("INSERT INTO alarms(at,label) VALUES(?,?)", (at.strftime(FMT), (label or "").strip()[:60]))
    return {"id": aid, "at": at.strftime(FMT), "label": label,
            "delivery": "поставится при следующем закрытии Telegram" if at - _now() <= timedelta(hours=24)
            else "поставится вечером накануне (iPhone-будильник знает только время, без даты)"}


def listing(limit=30):
    return [dict(r) for r in db.q("SELECT id, at, label, status, sent_at FROM alarms "
                                  "WHERE status IN ('pending','sent') AND at >= ? ORDER BY at LIMIT ?",
                                  ((_now() - timedelta(hours=12)).strftime(FMT), limit))]


def cancel(aid):
    r = db.q("SELECT status FROM alarms WHERE id=?", (int(aid),), one=True)
    if not r:
        raise ValueError("нет такого будильника")
    if r["status"] == "pending":
        db.ex("UPDATE alarms SET status='cancelled' WHERE id=?", (int(aid),))
        return {"ok": True, "note": "убран из очереди, на iPhone он не попадёт"}
    return {"ok": False, "note": "уже стоит на iPhone — выключить его можно только в приложении «Часы»"}


def pull():
    """Что поставить сейчас: всё, что сработает в ближайшие 24 часа. Отданное помечается sent."""
    now = _now()
    db.ex("UPDATE alarms SET status='missed' WHERE status='pending' AND at <= ?", (now.strftime(FMT),))
    rows = [dict(r) for r in db.q("SELECT id, at, label FROM alarms WHERE status='pending' AND at <= ? ORDER BY at",
                                  ((now + timedelta(hours=24)).strftime(FMT),))]
    if rows:
        db.ex(f"UPDATE alarms SET status='sent', sent_at=CURRENT_TIMESTAMP WHERE id IN ({','.join('?' * len(rows))})",
              [r["id"] for r in rows])
    return [{"time": r["at"][11:], "label": r["label"] or "Будильник"} for r in rows]
