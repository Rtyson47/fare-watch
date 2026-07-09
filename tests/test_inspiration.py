from datetime import date, timedelta

from farewatch import inspiration, models


TODAY = date(2026, 7, 9)


class FakeTP:
    def __init__(self, fares_by_origin):
        self.fares_by_origin = fares_by_origin

    def city_directions(self, origin):
        return self.fares_by_origin[origin]


def _fares_from_fixture(load_fixture):
    data = load_fixture("tp_city_directions.json")["data"]
    return [models.from_tp_v1_entry(e, "usd", "tp:city_directions") for e in data.values()]


def test_country_of_and_whitelist(load_fixture):
    airports = load_fixture("airports_min.json")
    assert inspiration.country_of("BKK", airports) == "TH"
    assert inspiration.passes_whitelist("NYC", [], airports) is True         # empty = anywhere
    assert inspiration.passes_whitelist("NYC", ["US"], airports) is True     # by country
    assert inspiration.passes_whitelist("BKK", ["US"], airports) is False
    assert inspiration.passes_whitelist("MAD", ["MAD"], airports) is True    # explicit IATA


def test_within_horizon():
    assert inspiration.within_horizon("2026-08-03", TODAY, 8) is True
    assert inspiration.within_horizon("2027-01-01", TODAY, 8) is False
    assert inspiration.within_horizon("2026-07-01", TODAY, 8) is False       # in the past


def test_run_inspiration_filters_and_sorts(load_fixture):
    airports = load_fixture("airports_min.json")
    tp = FakeTP({"MEX": _fares_from_fixture(load_fixture)})
    cfg = {"origins": ["MEX"], "horizon_weeks": 8, "price_ceiling": 400,
           "region_whitelist": []}
    shortlist = inspiration.run_inspiration(tp, cfg, TODAY, airports)
    assert [f.destination for f in shortlist] == ["NYC", "BKK"]   # 455 MAD dropped, sorted asc
    assert inspiration.top_candidates(shortlist, 1)[0].destination == "NYC"


def test_run_inspiration_whitelist(load_fixture):
    airports = load_fixture("airports_min.json")
    tp = FakeTP({"MEX": _fares_from_fixture(load_fixture)})
    cfg = {"origins": ["MEX"], "horizon_weeks": 8, "price_ceiling": 1000,
           "region_whitelist": ["US"]}
    shortlist = inspiration.run_inspiration(tp, cfg, TODAY, airports)
    assert [f.destination for f in shortlist] == ["NYC"]


def test_run_inspiration_horizon_drops_far_future(load_fixture):
    airports = load_fixture("airports_min.json")
    fares = _fares_from_fixture(load_fixture)
    fares[0].depart_date = "2030-01-01"          # push BKK out of horizon
    tp = FakeTP({"MEX": fares})
    cfg = {"origins": ["MEX"], "horizon_weeks": 8, "price_ceiling": 1000,
           "region_whitelist": []}
    shortlist = inspiration.run_inspiration(tp, cfg, TODAY, airports)
    assert "BKK" not in [f.destination for f in shortlist]
