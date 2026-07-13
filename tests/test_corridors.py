from datetime import date

from farewatch import corridors


TODAY = date(2026, 7, 9)


def test_parse_any_fri_mon():
    pairs = corridors.parse_date_window("any Fri-Mon in 2026-09", TODAY)
    # Sep 2026: Fridays 4,11,18,25 -> Mondays 7,14,21,28
    assert pairs[0] == ("2026-09-04", "2026-09-07")
    departs = [d for d, _ in pairs]
    assert departs == ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25"]
    assert all(r is not None for _, r in pairs)


def test_parse_explicit_range_is_oneway_anchors():
    pairs = corridors.parse_date_window("2026-09-10:2026-09-12", TODAY)
    assert pairs == [("2026-09-10", None), ("2026-09-11", None), ("2026-09-12", None)]


def test_flex_dates_cartesian_includes_anchor():
    combos = corridors.flex_dates("2026-09-11", "2026-09-14", flex=3)
    assert len(combos) == 49                       # 7 x 7
    assert ("2026-09-11", "2026-09-14") in combos  # the anchor itself


def test_flex_dates_oneway_only_varies_depart():
    combos = corridors.flex_dates("2026-09-11", None, flex=2)
    assert len(combos) == 5
    assert all(r is None for _, r in combos)
    assert ("2026-09-11", None) in combos


def test_expand_corridor_covers_origin_variants():
    corridor = {
        "origin": "MEX", "destination": "LHR", "origin_variants": ["DUB"],
        "date_windows": ["any Fri-Mon in 2026-09"], "trip_type": "return",
        "cabin": "economy", "max_price": 650, "currency": "usd",
        "alert_threshold": 600, "flex_days": 3,
    }
    specs = corridors.expand_corridor(corridor, TODAY)
    origins = {s.origin for s in specs}
    assert origins == {"MEX", "DUB"}
    # no spec has a return earlier than its departure
    assert all(s.return_date is None or s.return_date >= s.depart_date for s in specs)
    assert all(s.destination == "LHR" and s.max_price == 650 for s in specs)


def test_expand_deadline_oneway_up_to_arrival():
    watch = {"destination": "MEX", "must_arrive_by": "2026-07-14",
             "max_price": 600, "currency": "usd"}
    specs = corridors.expand_deadline(watch, base="LHR", today=TODAY)
    assert all(s.one_way and s.origin == "LHR" and s.destination == "MEX" for s in specs)
    assert all(s.depart_date <= "2026-07-14" for s in specs)
    assert specs[0].depart_date >= "2026-07-09"


def test_expand_deadline_earliest_depart_floors_window():
    watch = {"destination": "MEX", "must_arrive_by": "2026-07-20",
             "earliest_depart": "2026-07-15", "max_price": 600, "currency": "usd"}
    specs = corridors.expand_deadline(watch, base="LHR", today=TODAY)
    depart_dates = sorted({s.depart_date for s in specs})
    assert depart_dates[0] == "2026-07-15"
    assert all(d >= "2026-07-15" for d in depart_dates)


def test_expand_deadline_earliest_depart_after_arrival_yields_nothing():
    watch = {"destination": "MEX", "must_arrive_by": "2026-07-14",
             "earliest_depart": "2026-07-20", "max_price": 600, "currency": "usd"}
    specs = corridors.expand_deadline(watch, base="LHR", today=TODAY)
    assert specs == []


def test_expand_deadline_origin_variants_yield_specs_for_every_origin():
    watch = {"destination": "MEX", "must_arrive_by": "2026-07-10",
             "origin_variants": ["MAN", "BHX"], "max_price": 600, "currency": "usd"}
    specs = corridors.expand_deadline(watch, base="LHR", today=TODAY)
    origins = {s.origin for s in specs}
    assert origins == {"LHR", "MAN", "BHX"}


def test_expand_corridor_never_emits_past_departures():
    # A range window whose start has already passed (plus flex) must not
    # search departed dates — cached APIs can still return fares for them.
    corridor = {
        "origin": "MEX", "destination": "YYZ",
        "date_windows": ["2026-07-01:2026-08-31"], "trip_type": "one_way",
        "flex_days": 3,
    }
    specs = corridors.expand_corridor(corridor, TODAY)
    assert specs
    assert all(s.depart_date >= "2026-07-09" for s in specs)


def test_expand_corridor_range_window_flex_does_not_bleed_outside():
    # Explicit ranges already cover every day, so flex must not extend the
    # window (e.g. "Sep onwards" searching late August).
    corridor = {
        "origin": "YVR", "destination": "LON",
        "date_windows": ["2026-09-01:2026-09-30"], "trip_type": "one_way",
        "flex_days": 3,
    }
    specs = corridors.expand_corridor(corridor, TODAY)
    departs = {s.depart_date for s in specs}
    assert min(departs) == "2026-09-01" and max(departs) == "2026-09-30"


def test_expand_corridor_expired_window_yields_nothing():
    corridor = {
        "origin": "MEX", "destination": "YYZ",
        "date_windows": ["2026-06-01:2026-06-30"], "trip_type": "one_way",
        "flex_days": 3,
    }
    assert corridors.expand_corridor(corridor, TODAY) == []
