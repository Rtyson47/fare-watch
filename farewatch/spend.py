"""Duffel cost guardrail + spend tracking.

Tier 2 must call :func:`guard` before every Duffel search; on the daily cap it
raises :class:`GuardrailHit`, which the caller logs and treats as a hard stop.
Estimated spend is recorded at ``duffel_cost_per_search_usd`` per search.
"""
from . import db


class GuardrailHit(Exception):
    """Raised when the per-day Duffel search cap is reached."""


def searches_today(conn, provider, day):
    row = conn.execute(
        "SELECT COALESCE(SUM(searches), 0) AS n FROM spend WHERE provider=? AND day=?",
        (provider, day),
    ).fetchone()
    return int(row["n"])


def can_spend(conn, guardrails, day):
    cap = guardrails.get("max_duffel_searches_per_day", 100)
    return searches_today(conn, "duffel", day) < cap


def record_duffel_search(conn, guardrails, day, count=1):
    cost = guardrails.get("duffel_cost_per_search_usd", 0.005) * count
    conn.execute(
        "INSERT INTO spend (ts, day, provider, searches, est_cost_usd) VALUES (?,?,?,?,?)",
        (db.now_iso(), day, "duffel", count, cost),
    )
    conn.commit()


def guard(conn, guardrails, day):
    if not can_spend(conn, guardrails, day):
        cap = guardrails.get("max_duffel_searches_per_day", 100)
        raise GuardrailHit(f"Daily Duffel cap reached ({cap} searches) for {day}")


def spend_this_month(conn, provider, month_prefix):
    row = conn.execute(
        "SELECT COALESCE(SUM(searches),0) AS n, COALESCE(SUM(est_cost_usd),0) AS c"
        " FROM spend WHERE provider=? AND day LIKE ?",
        (provider, month_prefix + "%"),
    ).fetchone()
    return {"searches": int(row["n"]), "est_cost_usd": float(row["c"])}
