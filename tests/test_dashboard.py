import json
from datetime import date

from farewatch import config, dashboard, db
from farewatch.models import FareRecord


TODAY = date(2026, 7, 9)


def _seed(conn):
    # a corridor observation (return trip, matching the example corridor's
    # trip_type: return) + its daily_min point
    sid = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", "2026-09-14", "tp:prices_latest")
    db.record_fare(conn, sid, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", return_date="2026-09-14", carrier="BA",
                   deep_link="http://d", source="tp:prices_latest"))
    db.upsert_daily_min(conn, "MEX+2-LHR", "2026-07-09", 588.0)  # config.example.yaml has origin_variants [DUB, AMS]
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
    corr = next(c for c in data["corridors"] if c["route"] == "MEX+2-LHR")
    assert corr["threshold"] == 600                      # alert_threshold from example
    assert {"date": "2026-07-09", "min_price": 588.0} in corr["history"]
    assert corr["current_cheapest"]["price"] == 588.0
    assert any(i["destination"] == "NYC" for i in data["inspiration"]["international"])
    assert "spend_this_month" in data and "est_cost_usd" in data["spend_this_month"]
    assert "options" in corr and corr["options"][0]["price"] == 588.0
    assert corr["best_seen"] == {"date": "2026-07-09", "min_price": 588.0}
    dw = data["deadline_watches"][0]
    assert "options" in dw and "best_seen" in dw


def test_top_options_one_row_per_distinct_date_pair(conn):
    sid1 = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", "2026-09-14", "tp:prices_latest",
                            ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid1, FareRecord("MEX", "LHR", 700.0, "usd",
                   depart_date="2026-09-11", return_date="2026-09-14", carrier="BA",
                   deep_link="http://expensive", source="tp:prices_latest"))
    sid2 = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", "2026-09-14", "tp:prices_latest",
                            ts="2026-07-09T00:05:00+00:00")
    db.record_fare(conn, sid2, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", return_date="2026-09-14", carrier="BA",
                   deep_link="http://cheap", source="tp:prices_latest"))
    sid3 = db.record_search(conn, 1, "MEX", "LHR", "2026-09-18", "2026-09-21", "tp:prices_latest",
                            ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid3, FareRecord("MEX", "LHR", 610.0, "usd",
                   depart_date="2026-09-18", return_date="2026-09-21", carrier="BA",
                   deep_link="http://other", source="tp:prices_latest"))
    options = dashboard.top_options(conn, ["MEX"], "LHR")
    assert len(options) == 2
    pair1 = next(o for o in options if o["depart_date"] == "2026-09-11")
    assert pair1["price"] == 588.0
    assert pair1["deep_link"] == "http://cheap"


def test_top_options_scoped_to_origins_and_latest_day(conn):
    sid_old = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix",
                               ts="2026-07-08T00:00:00+00:00")
    db.record_fare(conn, sid_old, FareRecord("MEX", "LHR", 400.0, "usd",
                   depart_date="2026-09-11", carrier="BA", source="tp:month_matrix"))
    sid_other_origin = db.record_search(conn, 1, "GDL", "LHR", "2026-09-11", None, "tp:month_matrix",
                                        ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid_other_origin, FareRecord("GDL", "LHR", 300.0, "usd",
                   depart_date="2026-09-11", carrier="BA", source="tp:month_matrix"))
    sid_new = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix",
                               ts="2026-07-09T00:00:00+00:00")
    db.record_fare(conn, sid_new, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", carrier="BA", source="tp:month_matrix"))
    options = dashboard.top_options(conn, ["MEX"], "LHR")
    assert len(options) == 1
    assert options[0]["price"] == 588.0


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


def test_duffel_test_fares_excluded_from_cheapest_and_options(conn):
    # Sandbox (duffel_test) prices are synthetic and must never surface on the
    # dashboard; real live-verified duffel fares are allowed.
    ts = "2026-07-09T12:00:00+00:00"
    sid_tp = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix", ts=ts)
    db.record_fare(conn, sid_tp, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", source="tp:month_matrix"))
    sid_sandbox = db.record_search(conn, 2, "MEX", "LHR", "2026-09-11", None, "duffel_test", ts=ts)
    db.record_fare(conn, sid_sandbox, FareRecord("MEX", "LHR", 42.0, "usd",
                   depart_date="2026-09-11", source="duffel_test"))
    sid_live = db.record_search(conn, 2, "MEX", "LHR", "2026-09-12", None, "duffel", ts=ts)
    db.record_fare(conn, sid_live, FareRecord("MEX", "LHR", 501.0, "usd",
                   depart_date="2026-09-12", source="duffel"))

    assert dashboard.cheapest_for_route(conn, "MEX", "LHR")["price"] == 501.0
    prices = [o["price"] for o in dashboard.top_options(conn, "MEX", "LHR")]
    assert 42.0 not in prices and set(prices) == {501.0, 588.0}


def test_trip_shape_filter_separates_shared_route_corridors(conn):
    # A one-way and a return corridor on the same origin/dest must not surface
    # each other's fares as "current cheapest".
    ts = "2026-07-09T12:00:00+00:00"
    sid_ow = db.record_search(conn, 1, "YVR", "LON", "2026-09-11", None, "tp:month_matrix", ts=ts)
    db.record_fare(conn, sid_ow, FareRecord("YVR", "LON", 588.0, "usd",
                   depart_date="2026-09-11", one_way=True, source="tp:month_matrix"))
    sid_rt = db.record_search(conn, 1, "YVR", "LON", "2026-09-11", "2026-09-14",
                              "tp:prices_latest", ts=ts)
    db.record_fare(conn, sid_rt, FareRecord("YVR", "LON", 612.0, "usd",
                   depart_date="2026-09-11", return_date="2026-09-14",
                   source="tp:prices_latest"))

    assert dashboard.cheapest_for_route(conn, "YVR", "LON", one_way=True)["price"] == 588.0
    assert dashboard.cheapest_for_route(conn, "YVR", "LON", one_way=False)["price"] == 612.0
    assert dashboard.cheapest_for_route(conn, "YVR", "LON")["price"] == 588.0
    assert [o["price"] for o in dashboard.top_options(conn, "YVR", "LON", one_way=False)] == [612.0]


def test_latest_day_ignores_filtered_out_searches(conn):
    # The "latest scan day" must be computed over the same rows the outer
    # query keeps: a later duffel_test-only (or wrong-shape-only) day must not
    # blank out a row whose real fares are from the previous scan.
    old = "2026-07-08T12:00:00+00:00"
    sid_tp = db.record_search(conn, 1, "YVR", "LON", "2026-09-11", None, "tp:month_matrix", ts=old)
    db.record_fare(conn, sid_tp, FareRecord("YVR", "LON", 588.0, "usd",
                   depart_date="2026-09-11", source="tp:month_matrix"))
    new = "2026-07-09T12:00:00+00:00"
    sid_sandbox = db.record_search(conn, 2, "YVR", "LON", "2026-09-11", None, "duffel_test", ts=new)
    db.record_fare(conn, sid_sandbox, FareRecord("YVR", "LON", 42.0, "usd",
                   depart_date="2026-09-11", source="duffel_test"))
    sid_rt = db.record_search(conn, 1, "YVR", "LON", "2026-09-11", "2026-09-14",
                              "tp:prices_latest", ts=new)
    db.record_fare(conn, sid_rt, FareRecord("YVR", "LON", 612.0, "usd",
                   depart_date="2026-09-11", return_date="2026-09-14",
                   source="tp:prices_latest"))

    # one-way row: latest one-way scan day is Jul 8 (Jul 9 has only sandbox +
    # return rows), so the 588 fare must still show
    assert dashboard.cheapest_for_route(conn, "YVR", "LON", one_way=True)["price"] == 588.0
    assert [o["price"] for o in dashboard.top_options(conn, "YVR", "LON", one_way=True)] == [588.0]
    # return row still sees its own Jul 9 fare
    assert dashboard.cheapest_for_route(conn, "YVR", "LON", one_way=False)["price"] == 612.0


def test_departed_and_out_of_window_fares_never_surface(conn, sample_config):
    # A deadline watch whose route stopped producing fares must not fall back
    # to a stale scan day and show departed / out-of-window departures.
    ts = "2026-07-05T12:00:00+00:00"
    for dep in ("2026-07-06", "2026-07-08", "2026-12-30"):
        sid = db.record_search(conn, 1, "MEX", "MAN", dep, None, "tp:prices_latest", ts=ts)
        db.record_fare(conn, sid, FareRecord("MEX", "MAN", 300.0, "usd",
                       depart_date=dep, source="tp:prices_latest"))
    cfg = config.load_config(str(sample_config))
    data = dashboard.build_data(conn, cfg, TODAY)   # TODAY = 2026-07-09
    w = next(x for x in data["deadline_watches"] if x["route"] == "MEX-MAN")
    # Jul 6/8 have departed; Dec 30 is after must_arrive_by (2026-12-24)
    assert w["current_cheapest"] is None
    assert w["options"] == []
