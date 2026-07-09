"""Export a run's state to ``docs/data.json`` for the static Chart.js dashboard."""
import json

from . import db, spend


def cheapest_for_route(conn, origin, dest):
    row = conn.execute(
        "SELECT f.price, f.carrier, f.deep_link, s.depart_date, s.return_date"
        " FROM fares f JOIN searches s ON f.search_id = s.id"
        " WHERE s.origin=? AND s.dest=?"
        " AND substr(s.ts, 1, 10) = (SELECT substr(MAX(ts), 1, 10) FROM searches"
        " WHERE origin=? AND dest=?)"
        " ORDER BY f.price ASC LIMIT 1",
        (origin, dest, origin, dest),
    ).fetchone()
    return dict(row) if row else None


def history_for_route(conn, route):
    rows = conn.execute(
        "SELECT date, min_price FROM daily_min WHERE route=? ORDER BY date",
        (route,),
    ).fetchall()
    return [{"date": r["date"], "min_price": r["min_price"]} for r in rows]


def inspiration_shortlist(conn, limit):
    rows = conn.execute(
        "SELECT s.dest AS destination, s.origin AS origin, MIN(f.price) AS price,"
        "       f.deep_link AS deep_link, s.depart_date AS depart_date"
        " FROM fares f JOIN searches s ON f.search_id = s.id"
        " WHERE s.source = 'tp:city_directions'"
        " AND substr(s.ts, 1, 10) = (SELECT substr(MAX(ts), 1, 10) FROM searches"
        " WHERE source='tp:city_directions')"
        " GROUP BY s.origin, s.dest ORDER BY price ASC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def build_data(conn, cfg, today):
    corridors = []
    for c in cfg.get("corridors", []) or []:
        origin, dest = c["origin"], c["destination"]
        route = f"{origin}-{dest}"
        corridors.append({
            "route": route,
            "threshold": c.get("alert_threshold") or c.get("max_price"),
            "max_price": c.get("max_price"),
            "history": history_for_route(conn, route),
            "current_cheapest": cheapest_for_route(conn, origin, dest),
        })
    top_n = (cfg.get("inspiration", {}) or {}).get("top_n_to_verify", 10)
    return {
        "generated_at": db.now_iso(),
        "base": cfg.get("current_base"),
        "corridors": corridors,
        "inspiration": inspiration_shortlist(conn, top_n),
        "spend_this_month": spend.spend_this_month(conn, "duffel", today.strftime("%Y-%m")),
    }


def export(conn, cfg, today, path="docs/data.json"):
    data = build_data(conn, cfg, today)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data
