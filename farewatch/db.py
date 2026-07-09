"""SQLite storage: schema + a thin data-access layer.

Tables (per spec): searches, fares, daily_min, alerts — plus ``spend`` for the
Duffel cost guardrail. Prices are REAL; every timestamp is ISO-8601 UTC.
"""
import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT    NOT NULL,
    tier        INTEGER NOT NULL,
    origin      TEXT    NOT NULL,
    dest        TEXT    NOT NULL,
    depart_date TEXT,
    return_date TEXT,
    source      TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS fares (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES searches(id),
    carrier   TEXT,
    price     REAL    NOT NULL,
    currency  TEXT    NOT NULL,
    deep_link TEXT,
    raw_json  TEXT
);

CREATE TABLE IF NOT EXISTS daily_min (
    route     TEXT NOT NULL,
    date      TEXT NOT NULL,
    min_price REAL NOT NULL,
    ts        TEXT NOT NULL,
    PRIMARY KEY (route, date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    route      TEXT NOT NULL,
    price      REAL NOT NULL,
    reason     TEXT NOT NULL,
    channel    TEXT NOT NULL,
    dedupe_key TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spend (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT    NOT NULL,
    day          TEXT    NOT NULL,
    provider     TEXT    NOT NULL,
    searches     INTEGER NOT NULL DEFAULT 1,
    est_cost_usd REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fares_search   ON fares(search_id);
CREATE INDEX IF NOT EXISTS idx_daily_min_route ON daily_min(route);
CREATE INDEX IF NOT EXISTS idx_alerts_dedupe  ON alerts(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_spend_day      ON spend(day);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn)
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def record_search(conn, tier, origin, dest, depart_date, return_date, source, ts=None):
    cur = conn.execute(
        "INSERT INTO searches (ts, tier, origin, dest, depart_date, return_date, source)"
        " VALUES (?,?,?,?,?,?,?)",
        (ts or now_iso(), tier, origin, dest, depart_date, return_date, source),
    )
    conn.commit()
    return cur.lastrowid


def record_fare(conn, search_id, fare):
    cur = conn.execute(
        "INSERT INTO fares (search_id, carrier, price, currency, deep_link, raw_json)"
        " VALUES (?,?,?,?,?,?)",
        (search_id, fare.carrier, fare.price, fare.currency, fare.deep_link,
         json.dumps(fare.raw)),
    )
    conn.commit()
    return cur.lastrowid


def upsert_daily_min(conn, route, obs_date, price, ts=None):
    conn.execute(
        "INSERT INTO daily_min (route, date, min_price, ts) VALUES (?,?,?,?)"
        " ON CONFLICT(route, date) DO UPDATE SET"
        "   min_price = min(excluded.min_price, daily_min.min_price),"
        "   ts = excluded.ts",
        (route, obs_date, price, ts or now_iso()),
    )
    conn.commit()


def trailing_daily_min(conn, route, since_date):
    rows = conn.execute(
        "SELECT min_price FROM daily_min WHERE route=? AND date>=? ORDER BY date",
        (route, since_date),
    ).fetchall()
    return [r["min_price"] for r in rows]


def record_alert(conn, route, price, reason, channel, dedupe_key, ts=None):
    conn.execute(
        "INSERT INTO alerts (ts, route, price, reason, channel, dedupe_key)"
        " VALUES (?,?,?,?,?,?)",
        (ts or now_iso(), route, price, reason, channel, dedupe_key),
    )
    conn.commit()


def recent_alert_exists(conn, dedupe_key, since_ts):
    row = conn.execute(
        "SELECT 1 FROM alerts WHERE dedupe_key=? AND ts>=? LIMIT 1",
        (dedupe_key, since_ts),
    ).fetchone()
    return row is not None
