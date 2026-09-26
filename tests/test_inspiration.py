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


def _fare(dest, price, depart, ret=None, origin="LON", source="tp:city_directions"):
    return models.FareRecord(origin, dest, price, "usd", depart_date=depart,
                             return_date=ret, source=source)


class FakeTPWithLatest(FakeTP):
    def __init__(self, fares_by_origin, latest_by_month):
        super().__init__(fares_by_origin)
        self.latest_by_month = latest_by_month
        self.latest_calls = []

    def prices_latest(self, origin, destination=None, beginning_of_period=None,
                      period_type="month", one_way=False, limit=30):
        self.latest_calls.append((origin, destination, beginning_of_period, one_way))
        return list(self.latest_by_month.get(beginning_of_period, []))


def test_run_inspiration_trip_type_return_drops_one_ways():
    airports = {"BCN": "ES", "LIS": "PT"}
    tp = FakeTP({"LON": [_fare("BCN", 60, "2026-07-20", "2026-07-24"),
                         _fare("LIS", 40, "2026-07-20")]})           # one-way: dropped
    cfg = {"origins": ["LON"], "trip_type": "return", "horizon_days": 31}
    assert [f.destination for f in inspiration.run_inspiration(tp, cfg, TODAY, airports)] == ["BCN"]


def test_within_horizon_days_overrides_weeks():
    assert inspiration.within_horizon("2026-08-09", TODAY, horizon_days=31) is True
    assert inspiration.within_horizon("2026-08-10", TODAY, horizon_days=31) is False
    assert inspiration.within_horizon("2026-08-10", TODAY, 8, horizon_days=31) is False


def test_run_inspiration_prices_latest_source_merges_and_dedupes():
    # city_directions' only Rome fare is outside the 31-day horizon; the
    # per-month prices_latest pull supplies an in-horizon one. Two Barcelona
    # fares collapse to the cheaper; GB and non-whitelisted cities are dropped.
    airports = {"BCN": "ES", "ROM": "IT", "EDI": "GB", "NYC": "US"}
    tp = FakeTPWithLatest(
        {"LON": [_fare("ROM", 50, "2026-09-30", "2026-10-03"),
                 _fare("BCN", 90, "2026-07-15", "2026-07-18")]},
        {"2026-07-01": [_fare("BCN", 70, "2026-07-16", "2026-07-19", source="tp:prices_latest"),
                        _fare("EDI", 30, "2026-07-16", "2026-07-19", source="tp:prices_latest")],
         "2026-08-01": [_fare("ROM", 80, "2026-08-02", "2026-08-06", source="tp:prices_latest"),
                        _fare("NYC", 20, "2026-08-02", "2026-08-06", source="tp:prices_latest")]})
    europe = ["ES", "IT"]
    cfg = {"origins": ["LON"], "sources": ["city_directions", "prices_latest"],
           "trip_type": "return", "horizon_days": 31, "price_ceiling": 450,
           "region_whitelist": europe}
    shortlist = inspiration.run_inspiration(tp, cfg, TODAY, airports)
    assert [(f.destination, f.price) for f in shortlist] == [("BCN", 70), ("ROM", 80)]
    assert shortlist[0].source == "tp:inspiration_latest"
    assert [c[2] for c in tp.latest_calls] == ["2026-07-01", "2026-08-01"]
    assert all(c[1] is None and c[3] is False for c in tp.latest_calls)   # no dest, returns


def test_airports_table_covers_european_city_codes():
    airports = inspiration.load_airports()
    for code, country in {"ROM": "IT", "MIL": "IT", "TYO": "JP", "SPK": "JP",
                          "PER": "AU", "LON": "GB", "MEX": "MX"}.items():
        assert airports.get(code) == country, code
