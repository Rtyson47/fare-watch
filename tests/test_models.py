from farewatch import models


def test_from_tp_v2_row_maps_value_and_dates(load_fixture):
    row = load_fixture("tp_prices_latest.json")["data"][0]
    f = models.from_tp_v2_row(row, currency="usd", source="tp:prices_latest")
    assert f.price == 612.0            # "value" -> price
    assert f.depart_date == "2026-09-11"
    assert f.return_date == "2026-09-14"
    assert f.one_way is False
    assert f.origin == "MEX" and f.destination == "LHR"
    assert f.source == "tp:prices_latest"


def test_from_tp_v2_row_oneway_when_no_return(load_fixture):
    row = dict(load_fixture("tp_month_matrix.json")["data"][0])  # return_date == ""
    f = models.from_tp_v2_row(row, currency="usd", source="tp:month_matrix")
    assert f.return_date is None
    assert f.one_way is True


def test_from_tp_v1_entry_maps_price_airline_and_dates(load_fixture):
    entry = load_fixture("tp_city_directions.json")["data"]["BKK"]
    f = models.from_tp_v1_entry(entry, currency="usd", source="tp:city_directions")
    assert f.price == 388.0            # "price" -> price
    assert f.carrier == "TG"           # "airline" -> carrier
    assert f.depart_date == "2026-08-25"   # from "departure_at", date-only
    assert f.return_date == "2026-09-05"


def test_route_key():
    assert models.route_key("MEX", "LHR") == "MEX-LHR"


def test_deep_link_encodes_ddmm_and_marker():
    url = models.aviasales_deep_link("MEX", "LHR", "2026-09-11", "2026-09-14", marker="123")
    assert "MEX1109LHR1409" in url     # depart 11 Sep, return 14 Sep
    assert url.endswith("marker=123")


def test_deep_link_oneway_no_marker():
    url = models.aviasales_deep_link("MEX", "LHR", "2026-09-11")
    assert "MEX1109LHR1" in url        # no return segment, pax=1 appended
    assert "marker=" not in url
