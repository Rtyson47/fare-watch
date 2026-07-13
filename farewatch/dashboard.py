"""Export a run's state to ``docs/data.json`` for the static Chart.js dashboard."""
import json

from . import db, inspiration, spend
from .models import route_label


def _trip_clause(one_way, alias="s"):
    """SQL filter for trip shape: True=one-way rows, False=return rows, None=both.

    Needed when two watches share origin/dest (e.g. a one-way and a return
    corridor on the same route) so each row shows fares of its own shape.
    """
    if one_way is True:
        return f" AND {alias}.return_date IS NULL"
    if one_way is False:
        return f" AND {alias}.return_date IS NOT NULL"
    return ""


def _watch_clauses(one_way, depart_min, depart_max, alias="s"):
    """Shared row filters for a watch's fares: shape, date bounds, no sandbox."""
    sql, args = f" AND {alias}.source != 'duffel_test'", []
    sql += _trip_clause(one_way, alias)
    if depart_min:
        sql += f" AND {alias}.depart_date >= ?"
        args.append(depart_min)
    if depart_max:
        sql += f" AND {alias}.depart_date <= ?"
        args.append(depart_max)
    return sql, args


def _latest_scan_rows(conn, origins, dest, one_way, depart_min, depart_max):
    """All fares for the watch's latest scan day, cheapest first.

    Every filter is applied both to the rows and to the "latest scan day"
    subquery, so a day whose rows are all filtered out (sandbox-only, wrong
    shape, already departed) can't blank out a watch that has older data.
    """
    if isinstance(origins, str):
        origins = [origins]
    placeholders = ",".join("?" for _ in origins)
    where, args = _watch_clauses(one_way, depart_min, depart_max)
    sub_where, sub_args = _watch_clauses(one_way, depart_min, depart_max, "s2")
    return conn.execute(
        f"SELECT f.price, f.carrier, f.deep_link, s.origin, s.depart_date, s.return_date"
        f" FROM fares f JOIN searches s ON f.search_id = s.id"
        f" WHERE s.origin IN ({placeholders}) AND s.dest=?{where}"
        f" AND substr(s.ts, 1, 10) = (SELECT substr(MAX(s2.ts), 1, 10) FROM searches s2"
        f" WHERE s2.origin IN ({placeholders}) AND s2.dest=?{sub_where})"
        f" ORDER BY f.price ASC",
        (*origins, dest, *args, *origins, dest, *sub_args),
    ).fetchall()


def cheapest_for_route(conn, origins, dest, one_way=None, depart_min=None, depart_max=None):
    """Cheapest fare for ``dest`` from any of ``origins`` (a list, or a single code)."""
    rows = _latest_scan_rows(conn, origins, dest, one_way, depart_min, depart_max)
    return dict(rows[0]) if rows else None


def top_options(conn, origins, dest, limit=8, one_way=None, depart_min=None, depart_max=None):
    """Cheapest fare per distinct (depart_date, return_date) for the watch's latest scan day."""
    rows = _latest_scan_rows(conn, origins, dest, one_way, depart_min, depart_max)
    best_by_pair = {}
    for r in rows:
        key = (r["depart_date"], r["return_date"])
        if key not in best_by_pair:            # rows already ordered by price ASC
            best_by_pair[key] = dict(r)
    options = sorted(best_by_pair.values(), key=lambda d: d["price"])
    return options[:limit]


def best_seen(conn, route):
    row = conn.execute(
        "SELECT date, min_price FROM daily_min WHERE route=? ORDER BY min_price ASC LIMIT 1",
        (route,),
    ).fetchone()
    return {"date": row["date"], "min_price": row["min_price"]} if row else None


def history_for_route(conn, route):
    rows = conn.execute(
        "SELECT date, min_price FROM daily_min WHERE route=? ORDER BY date",
        (route,),
    ).fetchall()
    return [{"date": r["date"], "min_price": r["min_price"]} for r in rows]


def _inspiration_rows(conn):
    rows = conn.execute(
        "SELECT s.dest AS destination, s.origin AS origin, MIN(f.price) AS price,"
        "       f.deep_link AS deep_link, s.depart_date AS depart_date"
        " FROM fares f JOIN searches s ON f.search_id = s.id"
        " WHERE s.source = 'tp:city_directions'"
        " AND substr(s.ts, 1, 10) = (SELECT substr(MAX(ts), 1, 10) FROM searches"
        " WHERE source='tp:city_directions')"
        " GROUP BY s.origin, s.dest ORDER BY price ASC",
    ).fetchall()
    return [dict(r) for r in rows]


def inspiration_shortlist(conn, limit):
    return _inspiration_rows(conn)[:limit]


def inspiration_by_scope(conn, base, domestic_origin, airports, limit):
    """Split the shortlist into domestic (same country as ``base``) vs international.

    A flat cheapest-N cut is dominated by short domestic hops (which are
    structurally cheaper than long-haul), crowding out the international
    fares that make an "inspiration" list actually inspiring. The domestic
    bucket is further scoped to fares departing ``domestic_origin`` (which
    may differ from ``base``, e.g. a separate home-region airport), while
    the international bucket stays scoped to ``base``.
    """
    home_country = inspiration.country_of(base, airports)
    domestic, international = [], []
    for row in _inspiration_rows(conn):
        is_home_country = inspiration.country_of(row["destination"], airports) == home_country
        if is_home_country and row["origin"] == domestic_origin:
            domestic.append(row)
        elif not is_home_country and row["origin"] == base:
            international.append(row)
    return {"domestic": domestic[:limit], "international": international[:limit]}


def build_data(conn, cfg, today):
    today_iso = today.isoformat()
    corridors = []
    for c in cfg.get("corridors", []) or []:
        origins = [c["origin"]] + list(c.get("origin_variants", []) or [])
        dest = c["destination"]
        route = c.get("label") or route_label(origins, dest)
        trip = c.get("trip_type")
        one_way = True if trip == "one_way" else (False if trip == "return" else None)
        corridors.append({
            "route": route,
            "threshold": c.get("alert_threshold") or c.get("max_price"),
            "max_price": c.get("max_price"),
            "history": history_for_route(conn, route),
            "current_cheapest": cheapest_for_route(conn, origins, dest, one_way=one_way,
                                                   depart_min=today_iso),
            "options": top_options(conn, origins, dest, one_way=one_way,
                                   depart_min=today_iso),
            "best_seen": best_seen(conn, route),
        })
    base = cfg.get("current_base")
    deadline_watches = []
    for w in cfg.get("deadline_watches", []) or []:
        origins = [w.get("origin") or base] + list(w.get("origin_variants", []) or [])
        dest = w["destination"]
        route = route_label(origins, dest)
        # scope to the watch's actual window so stale scans of a wider (or
        # already-departed) window never surface as "current cheapest"
        depart_min = max(today_iso, w.get("earliest_depart") or today_iso)
        deadline_watches.append({
            "route": route,
            "must_arrive_by": w.get("must_arrive_by"),
            "max_price": w.get("max_price"),
            "history": history_for_route(conn, route),
            "current_cheapest": cheapest_for_route(conn, origins, dest, one_way=True,
                                                   depart_min=depart_min,
                                                   depart_max=w.get("must_arrive_by")),
            "options": top_options(conn, origins, dest, one_way=True,
                                   depart_min=depart_min,
                                   depart_max=w.get("must_arrive_by")),
            "best_seen": best_seen(conn, route),
        })
    insp_cfg = cfg.get("inspiration", {}) or {}
    top_n = insp_cfg.get("top_n_to_verify", 10)
    domestic_origin = insp_cfg.get("domestic_origin") or base
    airports = inspiration.load_airports()
    return {
        "generated_at": db.now_iso(),
        "base": base,
        "corridors": corridors,
        "deadline_watches": deadline_watches,
        "inspiration": inspiration_by_scope(conn, base, domestic_origin, airports, top_n),
        "spend_this_month": spend.spend_this_month(conn, "duffel", today.strftime("%Y-%m")),
    }


def export(conn, cfg, today, path="docs/data.json"):
    data = build_data(conn, cfg, today)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data
