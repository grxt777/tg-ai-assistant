"""Дневник: итоги дня, оценки 1–10, события и заметки, доходы/расходы в сумах + аналитика за период."""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import config
import db

# оценки дня по 10-балльной шкале; score — итоговая
PARAMS = {"busy": "насыщенность", "mood": "настроение", "energy": "энергия", "productivity": "продуктивность"}
SCORES = ("score", *PARAMS)

db.conn.executescript("""
CREATE TABLE IF NOT EXISTS journal_days (
    date TEXT PRIMARY KEY, summary TEXT DEFAULT '', verdict TEXT DEFAULT '',
    score INTEGER, busy INTEGER, mood INTEGER, energy INTEGER, productivity INTEGER,
    embedding BLOB, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY, date TEXT, kind TEXT,  -- event | note
    category TEXT, text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS journal_entries_date ON journal_entries(date);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY, date TEXT, type TEXT,  -- income | expense
    amount REAL, category TEXT, note TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS transactions_date ON transactions(date);
""")
if "verdict" not in {r[1] for r in db.conn.execute("PRAGMA table_info(journal_days)")}:
    db.conn.execute("ALTER TABLE journal_days ADD COLUMN verdict TEXT DEFAULT ''")
db.conn.commit()
db.conn.create_function("ulower", 1, lambda s: s.lower() if isinstance(s, str) else s, deterministic=True)  # LIKE в SQLite не знает кириллицу


def today():
    return datetime.now(ZoneInfo(config.TZ)).date()


def _day(d):
    return date.fromisoformat(str(d).strip()[:10]).isoformat() if d else today().isoformat()


def _score(v):
    return None if v in (None, "") else max(1, min(10, round(float(v))))


def _cat(c):
    return (c or "другое").strip().lower() or "другое"


def log_day(d=None, summary=None, scores=None, entries=(), transactions=(), emb=None, verdict=None):
    """Записывает день. summary, verdict и оценки перезаписываются, записи и деньги добавляются."""
    d = _day(d)
    scores = {k: _score(v) for k, v in (scores or {}).items() if k in SCORES and v not in (None, "")}
    if summary is not None or scores or verdict is not None:
        db.ex("INSERT INTO journal_days(date) VALUES(?) ON CONFLICT(date) DO NOTHING", (d,))
        sets, p = [f"{k}=?" for k in scores], list(scores.values())
        if summary is not None:
            sets += ["summary=?", "embedding=?"]
            p += [summary.strip(), db._blob(emb) if emb is not None else None]
        if verdict is not None:
            sets.append("verdict=?"); p.append(verdict.strip())
        db.ex(f"UPDATE journal_days SET {', '.join(sets)}, updated_at=CURRENT_TIMESTAMP WHERE date=?", (*p, d))
    for e in entries or ():
        if (e.get("text") or "").strip():
            db.ex("INSERT INTO journal_entries(date,kind,category,text) VALUES(?,?,?,?)",
                  (d, "note" if e.get("kind") == "note" else "event", _cat(e.get("category")), e["text"].strip()))
    for t in transactions or ():
        amount = abs(float(t.get("amount") or 0))
        if amount:
            db.ex("INSERT INTO transactions(date,type,amount,category,note) VALUES(?,?,?,?,?)",
                  (d, "income" if t.get("type") == "income" else "expense", amount, _cat(t.get("category")),
                   (t.get("note") or "").strip()))
    return get_day(d)


def get_day(d=None):
    d = _day(d)
    row = db.q(f"SELECT summary, verdict, {', '.join(SCORES)}, updated_at FROM journal_days WHERE date=?", (d,), one=True)
    tx = [dict(r) for r in db.q("SELECT id, type, amount, category, note FROM transactions WHERE date=? ORDER BY id", (d,))]
    return {
        "date": d,
        **(dict(row) if row else {"summary": "", "verdict": "", **{k: None for k in SCORES}, "updated_at": None}),
        "entries": [dict(r) for r in db.q("SELECT id, kind, category, text FROM journal_entries WHERE date=? ORDER BY id", (d,))],
        "transactions": tx,
        "income": sum(t["amount"] for t in tx if t["type"] == "income"),
        "expense": sum(t["amount"] for t in tx if t["type"] == "expense"),
    }


def is_logged(d):
    return bool(db.q("SELECT 1 FROM journal_days WHERE date=? AND (score IS NOT NULL OR summary!='')", (d,), one=True))


def delete(kind, id=None, d=None):
    if kind == "entry":
        db.ex("DELETE FROM journal_entries WHERE id=?", (int(id),))
    elif kind == "transaction":
        db.ex("DELETE FROM transactions WHERE id=?", (int(id),))
    elif kind == "day":
        d = _day(d)
        for t in ("journal_days", "journal_entries", "transactions"):
            db.ex(f"DELETE FROM {t} WHERE date=?", (d,))
    else:
        raise ValueError("kind: entry | transaction | day")


def list_days(before=None, limit=30, q=None):
    """Лента дней (новые сверху): все даты, где есть хоть что-то."""
    sql = f"""
        WITH d AS (SELECT date FROM journal_days UNION SELECT date FROM journal_entries UNION SELECT date FROM transactions)
        SELECT d.date, COALESCE(j.summary,'') summary, {', '.join('j.' + k for k in SCORES)},
          (SELECT COALESCE(SUM(amount),0) FROM transactions t WHERE t.date=d.date AND t.type='income') income,
          (SELECT COALESCE(SUM(amount),0) FROM transactions t WHERE t.date=d.date AND t.type='expense') expense,
          (SELECT COUNT(*) FROM journal_entries e WHERE e.date=d.date) entries
        FROM d LEFT JOIN journal_days j ON j.date=d.date WHERE d.date < ?"""
    p = [before or "9999"]
    if q:
        sql += """ AND (ulower(j.summary) LIKE ?
                   OR EXISTS(SELECT 1 FROM journal_entries e WHERE e.date=d.date AND ulower(e.text) LIKE ?)
                   OR EXISTS(SELECT 1 FROM transactions t WHERE t.date=d.date AND ulower(t.note || ' ' || t.category) LIKE ?))"""
        p += [f"%{q.lower()}%"] * 3
    return [dict(r) for r in db.q(sql + " ORDER BY d.date DESC LIMIT ?", (*p, limit))]


def recent(n=14, before=None):
    """Последние записанные дни (до даты before) — чтобы модель держала шкалу оценок и видела тренд."""
    return [dict(r) for r in db.q(f"""
        SELECT j.date, j.summary, {', '.join('j.' + k for k in SCORES)},
          (SELECT COALESCE(SUM(amount),0) FROM transactions t WHERE t.date=j.date AND t.type='expense') expense
        FROM journal_days j WHERE j.date < ? AND j.score IS NOT NULL ORDER BY j.date DESC LIMIT ?""",
        (before or today().isoformat(), n))]


def search(qv, k=5, min_score=0.5):
    rows = db.q("SELECT date, summary, score, embedding FROM journal_days WHERE embedding IS NOT NULL")
    return db._topk(rows, qv, k, min_score)


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 1) if vals else None


def _period(days_rows, tx_rows, start, end):
    days = [r for r in days_rows if start <= r["date"] <= end]
    tx = [r for r in tx_rows if start <= r["date"] <= end]
    income = sum(r["amount"] for r in tx if r["type"] == "income")
    expense = sum(r["amount"] for r in tx if r["type"] == "expense")
    return {
        "income": income, "expense": expense, "net": income - expense,
        "avg": {k: _avg(r[k] for r in days) for k in SCORES},
        "logged": sum(1 for r in days if r["score"] is not None or r["summary"]),
    }


def _by_cat(tx, kind):
    out = {}
    for r in tx:
        if r["type"] == kind:
            out[r["category"]] = out.get(r["category"], 0) + r["amount"]
    return [{"category": c, "amount": a} for c, a in sorted(out.items(), key=lambda x: -x[1])]


def stats(n=7):
    """Аналитика за последние n дней (включая сегодня) и сравнение с предыдущими n днями."""
    n = max(1, min(int(n), 3660))
    end = today()
    start, pstart = end - timedelta(days=n - 1), end - timedelta(days=2 * n - 1)
    s, e, ps, pe = start.isoformat(), end.isoformat(), pstart.isoformat(), (start - timedelta(days=1)).isoformat()
    days_rows = [dict(r) for r in db.q(f"SELECT date, summary, {', '.join(SCORES)} FROM journal_days "
                                       "WHERE date BETWEEN ? AND ?", (ps, e))]
    tx_rows = [dict(r) for r in db.q("SELECT date, type, amount, category FROM transactions WHERE date BETWEEN ? AND ?", (ps, e))]
    cur_tx = [r for r in tx_rows if r["date"] >= s]
    by_date = {r["date"]: r for r in days_rows}

    series = []
    for i in range(n):
        d = (start + timedelta(days=i)).isoformat()
        r = by_date.get(d, {})
        series.append({"date": d, **{k: r.get(k) for k in SCORES},
                       "income": sum(t["amount"] for t in cur_tx if t["date"] == d and t["type"] == "income"),
                       "expense": sum(t["amount"] for t in cur_tx if t["date"] == d and t["type"] == "expense")})

    months = {}
    for p in series:
        m = months.setdefault(p["date"][:7], {"month": p["date"][:7], "income": 0, "expense": 0, "scores": []})
        m["income"] += p["income"]; m["expense"] += p["expense"]
        if p["score"] is not None:
            m["scores"].append(p["score"])
    by_month = [{"month": m["month"], "income": m["income"], "expense": m["expense"],
                 "score": _avg(m["scores"]), "logged": len(m["scores"])} for m in months.values()]

    # серия: дни подряд с записью, считая от сегодня (или вчера, если сегодня ещё не записан)
    streak, d = 0, end if is_logged(e) else end - timedelta(days=1)
    while is_logged(d.isoformat()):
        streak += 1
        d -= timedelta(days=1)

    scored = sorted((r for r in days_rows if r["date"] >= s and r["score"] is not None), key=lambda r: r["score"])
    pick = lambda rows: [{"date": r["date"], "score": r["score"], "summary": r["summary"]} for r in rows]
    cur = _period(days_rows, tx_rows, s, e)
    return {
        "days": n, "from": s, "to": e, "params": PARAMS,
        **cur,
        "prev": _period(days_rows, tx_rows, ps, pe),
        "streak": streak,
        "expense_by_category": _by_cat(cur_tx, "expense"),
        "income_by_category": _by_cat(cur_tx, "income"),
        "event_categories": [dict(r) for r in db.q(
            "SELECT category, COUNT(*) n FROM journal_entries WHERE date BETWEEN ? AND ? AND kind='event' "
            "GROUP BY category ORDER BY n DESC LIMIT 10", (s, e))],
        "best_days": pick(scored[::-1][:3]),
        "worst_days": pick(scored[:3]),
        "series": series,
        "by_month": by_month,
    }
