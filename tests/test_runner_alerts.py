"""alerts_enabled: false mutes a corridor/deadline-watch's alerts without
stopping data collection (fares still stored, daily_min still updated) —
added so a route can be paused ("not flying that way right now") without
losing its price history.
"""
from datetime import date

from farewatch import runner
from farewatch.testing import FixtureTP

TODAY = date(2026, 7, 9)


def _cfg(muted_alerts_enabled):
    # No "label" set on either watch below -> route names fall back to
    # route_label(origins, dest): "AAA-ZZZ" (muted) and "BBB-YYY" (active).
    return {
        "current_base": "AAA",
        "deadline_watches": [
            {"origin": "AAA", "destination": "ZZZ",
             "must_arrive_by": "2026-09-12", "max_price": 650,
             "alerts_enabled": muted_alerts_enabled},
            {"origin": "BBB", "destination": "YYY",
             "must_arrive_by": "2026-09-12", "max_price": 650},
        ],
        "alerting": {"telegram": {"enabled": False}, "smtp": {"enabled": False}},
    }


def test_alerts_enabled_false_suppresses_alert_but_keeps_data(conn, tmp_path):
    cfg = _cfg(muted_alerts_enabled=False)
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"),
                         include_inspiration=False)
    # Only the active route alerted, even though both are below max_price 650.
    assert summary["alerts"] == 1
    alerted_routes = {r["route"] for r in conn.execute("SELECT route FROM alerts")}
    assert alerted_routes == {"BBB-YYY"}
    # Data collection is unaffected for the muted route: fares stored, daily_min recorded.
    fares_for_muted = conn.execute(
        "SELECT COUNT(*) c FROM searches WHERE origin='AAA' AND dest='ZZZ'").fetchone()["c"]
    assert fares_for_muted > 0
    daily_min_routes = {r["route"] for r in conn.execute("SELECT route FROM daily_min")}
    assert "AAA-ZZZ" in daily_min_routes and "BBB-YYY" in daily_min_routes


def test_alerts_enabled_defaults_true_when_absent(conn, tmp_path):
    # Omitting alerts_enabled entirely (the pre-existing config shape) behaves
    # exactly as before: both routes alert.
    cfg = _cfg(muted_alerts_enabled=True)
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"),
                         include_inspiration=False)
    assert summary["alerts"] == 2


def test_deadline_watch_label_overrides_auto_route_name(conn, tmp_path):
    # deadline_watches now honour "label" the same way corridors do (was
    # corridor-only; fixed 2026-09-12 so named watches like "X for
    # <festival>" don't silently collapse to "LON-MEL").
    cfg = {
        "current_base": "AAA",
        "deadline_watches": [
            {"label": "LON-MEL for Strawberry Fields", "origin": "AAA",
             "destination": "ZZZ", "must_arrive_by": "2026-09-12", "max_price": 650},
        ],
        "alerting": {"telegram": {"enabled": False}, "smtp": {"enabled": False}},
    }
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"),
                         include_inspiration=False)
    assert summary["alerts"] == 1
    alerted_routes = {r["route"] for r in conn.execute("SELECT route FROM alerts")}
    assert alerted_routes == {"LON-MEL for Strawberry Fields"}
