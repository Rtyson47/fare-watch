import pytest

from farewatch import spend


GUARD = {"max_duffel_searches_per_day": 2, "duffel_cost_per_search_usd": 0.005}


def test_cap_blocks_after_limit(conn):
    day = "2026-07-09"
    assert spend.can_spend(conn, GUARD, day) is True
    spend.record_duffel_search(conn, GUARD, day)
    spend.record_duffel_search(conn, GUARD, day)
    assert spend.searches_today(conn, "duffel", day) == 2
    assert spend.can_spend(conn, GUARD, day) is False
    with pytest.raises(spend.GuardrailHit):
        spend.guard(conn, GUARD, day)


def test_spend_this_month_sums_cost(conn):
    for _ in range(4):
        spend.record_duffel_search(conn, GUARD, "2026-07-09")
    spend.record_duffel_search(conn, GUARD, "2026-08-01")   # different month
    got = spend.spend_this_month(conn, "duffel", "2026-07")
    assert got["searches"] == 4
    assert got["est_cost_usd"] == pytest.approx(4 * 0.005)
