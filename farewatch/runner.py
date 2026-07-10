"""Orchestrate one monitoring run.

Tier 1 (Travelpayouts, free/cached) is fully wired: inspiration discovery,
corridor pricing, deadline-watch pricing, alert evaluation, dashboard export.
Tier 2 (Duffel, paid) is *gated* in this build — a full ``run`` logs what it
would verify and stops before any billed call. See the Phase 2 plan.
"""
import logging
from datetime import datetime, timedelta, timezone

from . import alerts, corridors, dashboard, db, inspiration, notify
from .models import route_key, route_label

log = logging.getLogger("farewatch.runner")


# -- Travelpayouts call guard -------------------------------------------------
def _fetch(fn, *args, ctx="", on_error=None, **kwargs):
    """Call a Travelpayouts client method, swallowing transport/parse failures.

    OSError covers urllib.error.URLError/HTTPError and socket timeouts; ValueError
    covers JSON decode errors. A failed call logs a warning and yields ``[]`` so
    the rest of the run (remaining corridors/watches, dashboard export) proceeds.
    ``on_error``, if given, is called with the exception so callers can count
    failures (e.g. for the run summary's ``errors`` count).
    """
    try:
        return fn(*args, **kwargs)
    except (OSError, ValueError) as exc:
        log.warning("Travelpayouts call failed (%s): %s", ctx, exc)
        if on_error is not None:
            on_error(exc)
        return []


# -- month helpers -----------------------------------------------------------
def _months_between(start, end):
    months, d = set(), start.replace(day=1)
    last = end.replace(day=1)
    while d <= last:
        months.add(d.strftime("%Y-%m"))
        d = (d + timedelta(days=32)).replace(day=1)
    return sorted(months)


def _months_ahead(today, n):
    return _months_between(today, today + timedelta(days=31 * (n - 1)))


# -- run ---------------------------------------------------------------------
def run(cfg, conn, today, *, tp_client, tier1_only=False, dry_run=False,
        poster=None, export_path="docs/data.json", include_inspiration=True):
    al = cfg.get("alerting", {}) or {}
    ratio = al.get("median_alert_ratio", 0.80)
    lookback = al.get("median_lookback_days", 30)
    min_samples = al.get("median_min_samples", 5)
    band = al.get("dedupe_band_width", 20)
    window_hours = al.get("dedupe_window_hours", 24)
    digest = bool(al.get("digest_mode", False))

    label, send = notify.build_notifier(cfg, dry_run, poster)
    now = datetime.now(timezone.utc)
    fired, collected = [], []
    errors = [0]

    def fetch(fn, *args, ctx="", **kwargs):
        def note(exc):
            errors[0] += 1
        return _fetch(fn, *args, ctx=ctx, on_error=note, **kwargs)

    def handle(fare, max_price):
        ctx = alerts.AlertContext(max_price=max_price, median_ratio=ratio,
                                  lookback_days=lookback, min_samples=min_samples,
                                  band_width=band, today=today)
        alert = alerts.process_fare(conn, fare, ctx, send, label, window_hours, now, digest)
        if alert is not None:
            fired.append(alert)
            if digest:
                collected.append(alert)

    def store(tier, fare):
        sid = db.record_search(conn, tier, fare.origin, fare.destination,
                               fare.depart_date, fare.return_date, fare.source)
        db.record_fare(conn, sid, fare)

    # -- Tier 1: inspiration discovery --------------------------------------
    insp = cfg.get("inspiration", {}) or {}
    airports = inspiration.load_airports()
    if include_inspiration:
        shortlist = fetch(inspiration.run_inspiration, tp_client, insp, today, airports,
                          ctx="inspiration")
    else:
        shortlist = []
    for fare in shortlist:
        store(1, fare)
        handle(fare, None)                 # discovery: median rule only (no ceiling spam)
        db.upsert_daily_min(conn, route_key(fare.origin, fare.destination),
                            today.isoformat(), fare.price)
    candidates = inspiration.top_candidates(shortlist, insp.get("top_n_to_verify", 10))

    # -- Tier 1: corridor pricing (date-window aware) ------------------------
    for c in cfg.get("corridors", []) or []:
        dest = c["destination"]
        by_origin = {}
        for s in corridors.expand_corridor(c, today):
            by_origin.setdefault(s.origin, []).append(s)
        all_kept = []
        for origin, origin_specs in by_origin.items():
            return_specs = [s for s in origin_specs if not s.one_way]
            if return_specs:
                allowed_pairs = {(s.depart_date, s.return_date) for s in return_specs}
                months = sorted({s.depart_date[:7] for s in return_specs})
                for m in months:
                    for fare in fetch(tp_client.prices_latest, origin, destination=dest,
                                      beginning_of_period=m + "-01", one_way=False,
                                      ctx=f"prices_latest {origin}-{dest} {m}"):
                        if (fare.depart_date, fare.return_date) in allowed_pairs:
                            fare.origin, fare.destination = origin, dest
                            all_kept.append(fare)

            oneway_specs = [s for s in origin_specs if s.one_way]
            if oneway_specs:
                allowed_departs = {s.depart_date for s in oneway_specs}
                months = sorted({s.depart_date[:7] for s in oneway_specs})
                for m in months:
                    for fare in fetch(tp_client.month_matrix, origin, dest, m + "-01",
                                      ctx=f"month_matrix {origin}-{dest} {m}"):
                        if fare.depart_date in allowed_departs and fare.return_date is None:
                            fare.origin, fare.destination = origin, dest
                            all_kept.append(fare)

        for fare in all_kept:
            store(1, fare)
        if all_kept:
            route = c.get("label") or route_label(by_origin.keys(), dest)
            cheapest = min(all_kept, key=lambda x: x.price)
            threshold = c.get("alert_threshold") or c.get("max_price")
            handle(cheapest, threshold)
            db.upsert_daily_min(conn, route, today.isoformat(), cheapest.price)

    # -- Tier 1: deadline watches ------------------------------------------
    base = cfg.get("current_base")
    for w in cfg.get("deadline_watches", []) or []:
        dest = w["destination"]
        by_origin = {}
        for s in corridors.expand_deadline(w, base, today):
            by_origin.setdefault(s.origin, []).append(s)
        if not by_origin:
            continue                       # deadline already passed
        all_kept = []
        for origin, origin_specs in by_origin.items():
            allowed = {s.depart_date for s in origin_specs}
            months = sorted({d[:7] for d in allowed})
            for m in months:
                for fare in fetch(tp_client.prices_latest, origin, destination=dest,
                                  beginning_of_period=m + "-01", one_way=True,
                                  ctx=f"prices_latest {origin}-{dest} {m}"):
                    if fare.depart_date in allowed:
                        fare.origin, fare.destination = origin, dest
                        all_kept.append(fare)
        for fare in all_kept:
            store(1, fare)
        if all_kept:
            route = route_label(by_origin.keys(), dest)
            cheapest = min(all_kept, key=lambda x: x.price)
            handle(cheapest, w.get("max_price"))
            db.upsert_daily_min(conn, route, today.isoformat(), cheapest.price)

    # -- Tier 2 gate --------------------------------------------------------
    tier2_gated = not tier1_only
    if tier2_gated:
        log.warning(
            "Tier 2 (Duffel) is gated in this build: would verify %d inspiration "
            "candidate(s) + %d corridor(s) + %d deadline watch(es). No live call made. "
            "Enable per the Phase 2 plan.",
            len(candidates), len(cfg.get("corridors", []) or []),
            len(cfg.get("deadline_watches", []) or []))

    # -- digest + export ----------------------------------------------------
    if digest and collected:
        alerts.send_digest(conn, collected, send, label, now)
    dashboard.export(conn, cfg, today, export_path)

    return {"tier1_only": tier1_only, "dry_run": dry_run, "shortlist": len(shortlist),
            "candidates": len(candidates), "alerts": len(fired), "tier2_gated": tier2_gated,
            "errors": errors[0]}


def backfill(cfg, conn, today, route, tp_client, months: int = 3):
    """Tier 1 seed: pull month-matrix for a route and record fares + today's min.

    ``months`` is the count of months ahead of ``today`` to seed (default 3);
    it's expanded to a "YYYY-MM" list via :func:`_months_ahead`.

    Note: the Travelpayouts cached API has no true price history — real history
    accrues from daily runs going forward. This pre-populates fares and today's
    daily_min point for the route.
    """
    origin, dest = route.split("-")
    month_list = _months_ahead(today, months)
    fares = []
    for m in month_list:
        for fare in _fetch(tp_client.month_matrix, origin, dest, m + "-01",
                           ctx=f"month_matrix {origin}-{dest} {m}"):
            sid = db.record_search(conn, 1, origin, dest, fare.depart_date, None, fare.source)
            db.record_fare(conn, sid, fare)
            fares.append(fare)
    if fares:
        cheapest = min(fares, key=lambda x: x.price)
        db.upsert_daily_min(conn, route, today.isoformat(), cheapest.price)
    return len(fares)
