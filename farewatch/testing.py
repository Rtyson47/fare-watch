"""Fixture-backed Travelpayouts client for offline demos and tests.

Enable in the CLI with ``FAREWATCH_FAKE_TP=1`` — it returns the recorded
fixtures instead of hitting the network, so ``run``/``backfill`` work with no
token and no live calls.
"""
import json
from pathlib import Path

from . import models

_FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"


class FixtureTP:
    def __init__(self, fixtures_dir=_FIXTURES, currency="usd", market="us"):
        self.dir = Path(fixtures_dir)
        self.currency = currency
        self.market = market
        self.calls = 0

    def _load(self, name):
        with open(self.dir / name) as f:
            return json.load(f)

    def _link(self, fare):
        if fare.depart_date:
            fare.deep_link = models.aviasales_deep_link(
                fare.origin, fare.destination, fare.depart_date, fare.return_date)
        return fare

    def _for_route(self, fare, origin, destination):
        fare.origin, fare.destination = origin, destination
        return self._link(fare)

    def prices_latest(self, origin, destination=None, beginning_of_period=None,
                      period_type="month", one_way=False, limit=30):
        self.calls += 1
        out = []
        for r in self._load("tp_prices_latest.json")["data"]:
            fare = models.from_tp_v2_row(r, self.currency, "tp:prices_latest")
            fare.origin, fare.destination = origin, destination
            if one_way:                        # real API returns one-ways for one_way=true
                fare.return_date, fare.one_way = None, True
            out.append(self._link(fare))
        return out

    def month_matrix(self, origin, destination, month):
        self.calls += 1
        return [self._for_route(models.from_tp_v2_row(r, self.currency, "tp:month_matrix"),
                                origin, destination)
                for r in self._load("tp_month_matrix.json")["data"]]

    def city_directions(self, origin):
        self.calls += 1
        out = []
        for e in self._load("tp_city_directions.json")["data"].values():
            fare = models.from_tp_v1_entry(e, self.currency, "tp:city_directions")
            fare.origin = origin               # keep the fixture's own destination
            out.append(self._link(fare))
        return out
