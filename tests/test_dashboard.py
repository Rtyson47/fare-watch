import json
from datetime import date

from farewatch import config, dashboard, db
from farewatch.models import FareRecord


TODAY = date(2026, 7, 9)


def _seed(conn):
    # a corridor observation (month-matrix) + its daily_min point
    sid = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix")
    db.record_fare(conn, sid, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", carrier="BA", deep_link="http://d",
                   source="tp:month_matrix"))
    db.upsert_daily_min(conn, "MEX-LHR", "2026-07-09", 588.0)
    # an inspiration find
    sid2 = db.record_search(conn, 1, "MEX", "NYC", "2026-08-03", None, "tp:city_directions")
    db.record_fare(conn, sid2, FareRecord("MEX", "NYC", 210.0, "usd",
                   depart_date="2026-08-03", carrier="AM", deep_link="http://n",
                   source="tp:city_directions"))


def test_build_data_shape(conn, sample_config):
    _seed(conn)
    cfg = config.load_config(str(sample_config))
    data = dashboard.build_data(conn, cfg, TODAY)
    assert data["base"] == "MEX"
    corr = next(c for c in data["corridors"] if c["route"] == "MEX-LHR")
    assert corr["threshold"] == 600                      # alert_threshold from example
    assert {"date": "2026-07-09", "min_price": 588.0} in corr["history"]
    assert corr["current_cheapest"]["price"] == 588.0
    assert any(i["destination"] == "NYC" for i in data["inspiration"])
    assert "spend_this_month" in data and "est_cost_usd" in data["spend_this_month"]


def test_export_writes_json(conn, sample_config, tmp_path):
    _seed(conn)
    cfg = config.load_config(str(sample_config))
    out = tmp_path / "data.json"
    dashboard.export(conn, cfg, TODAY, path=str(out))
    loaded = json.loads(out.read_text())
    assert loaded["base"] == "MEX"


def test_cheapest_for_route_ignores_stale_historical_low(conn):
    # A cheaper fare recorded on an older day should not pin the dashboard.
    sid_old = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix",
                               ts="2026-07-01T00:00:00+00:00")
    db.record_fare(conn, sid_old, FareRecord("MEX", "LHR", 400.0, "usd",
                   depart_date="2026-09-11", carrier="BA", deep_link="http://old",
                   source="tp:month_matrix"))
    # Today's pricier fare is the one that should surface.
    sid_new = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix",
                               ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid_new, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", carrier="BA", deep_link="http://new",
                   source="tp:month_matrix"))
    result = dashboard.cheapest_for_route(conn, "MEX", "LHR")
    assert result["price"] == 588.0
    assert result["deep_link"] == "http://new"


def test_inspiration_shortlist_ignores_stale_historical_low(conn):
    sid_old = db.record_search(conn, 1, "MEX", "NYC", "2026-08-03", None, "tp:city_directions",
                               ts="2026-07-01T00:00:00+00:00")
    db.record_fare(conn, sid_old, FareRecord("MEX", "NYC", 120.0, "usd",
                   depart_date="2026-08-03", carrier="AM", deep_link="http://old",
                   source="tp:city_directions"))
    sid_new = db.record_search(conn, 1, "MEX", "NYC", "2026-08-03", None, "tp:city_directions",
                               ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid_new, FareRecord("MEX", "NYC", 210.0, "usd",
                   depart_date="2026-08-03", carrier="AM", deep_link="http://new",
                   source="tp:city_directions"))
    rows = dashboard.inspiration_shortlist(conn, 10)
    assert len(rows) == 1
    assert rows[0]["price"] == 210.0
    assert rows[0]["deep_link"] == "http://new"


def test_inspiration_shortlist_keeps_origins_separate_for_same_destination(conn):
    sid1 = db.record_search(conn, 1, "MEX", "NYC", "2026-08-03", None, "tp:city_directions",
                            ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid1, FareRecord("MEX", "NYC", 210.0, "usd",
                   depart_date="2026-08-03", carrier="AM", deep_link="http://mex",
                   source="tp:city_directions"))
    sid2 = db.record_search(conn, 1, "GDL", "NYC", "2026-08-03", None, "tp:city_directions",
                            ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid2, FareRecord("GDL", "NYC", 180.0, "usd",
                   depart_date="2026-08-03", carrier="AM", deep_link="http://gdl",
                   source="tp:city_directions"))
    rows = dashboard.inspiration_shortlist(conn, 10)
    assert len(rows) == 2
    assert {r["origin"] for r in rows} == {"MEX", "GDL"}


def test_inspiration_shortlist_unaffected_by_same_day_corridor_run(conn):
    # A --corridors-only run just after UTC midnight records a corridor
    # search "today" but no city_directions rows. That must not blank the
    # inspiration shortlist: it should still surface yesterday's discovery
    # scan rather than being scoped to the (corridor-only) global latest day.
    sid_corridor = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None,
                                    "tp:month_matrix", ts="2026-07-09T00:05:00+00:00")
    db.record_fare(conn, sid_corridor, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", carrier="BA", deep_link="http://corridor",
                   source="tp:month_matrix"))
    sid_insp = db.record_search(conn, 1, "MEX", "NYC", "2026-08-03", None,
                                "tp:city_directions", ts="2026-07-08T00:00:00+00:00")
    db.record_fare(conn, sid_insp, FareRecord("MEX", "NYC", 210.0, "usd",
                   depart_date="2026-08-03", carrier="AM", deep_link="http://n",
                   source="tp:city_directions"))
    rows = dashboard.inspiration_shortlist(conn, 10)
    assert len(rows) == 1
    assert rows[0]["destination"] == "NYC"
    assert rows[0]["price"] == 210.0


def test_cheapest_for_route_unaffected_by_other_routes_fresher_data(conn):
    # If today's fetch for one route fails entirely but another route has
    # fresh data, the failed route's "current cheapest" should still surface
    # its own most recent scan (yesterday) rather than going null because the
    # global latest observation day belongs to a different route.
    sid_old = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix",
                               ts="2026-07-08T00:00:00+00:00")
    db.record_fare(conn, sid_old, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", carrier="BA", deep_link="http://yesterday",
                   source="tp:month_matrix"))
    sid_other = db.record_search(conn, 1, "MEX", "NYC", "2026-08-03", None, "tp:city_directions",
                                 ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid_other, FareRecord("MEX", "NYC", 210.0, "usd",
                   depart_date="2026-08-03", carrier="AM", deep_link="http://today",
                   source="tp:city_directions"))
    result = dashboard.cheapest_for_route(conn, "MEX", "LHR")
    assert result is not None
    assert result["price"] == 588.0
    assert result["deep_link"] == "http://yesterday"
