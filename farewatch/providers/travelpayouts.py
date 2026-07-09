"""Tier 1 (free, cached) client for the Travelpayouts / Aviasales Data API.

Only the v2 latest + month-matrix and v1 city-directions endpoints are used.
``market`` and ``currency`` are always sent explicitly — the API defaults to
the ``ru`` market otherwise.
"""
import os

from .. import models
from . import http

BASE = "https://api.travelpayouts.com"


class TravelpayoutsClient:
    def __init__(self, token, market="us", currency="usd", get_json=http.get_json,
                 marker=None):
        self.token = token
        self.market = market
        self.currency = currency
        self.get_json = get_json
        self.marker = marker if marker is not None else os.environ.get("TP_MARKER")

    # -- shared param scaffold ------------------------------------------------
    def _base_params(self, **extra):
        params = {
            "token": self.token,
            "currency": self.currency,
            "market": self.market,
        }
        params.update(extra)
        return params

    def _with_link(self, fare):
        if fare.depart_date:
            fare.deep_link = models.aviasales_deep_link(
                fare.origin, fare.destination, fare.depart_date,
                fare.return_date, marker=self.marker)
        return fare

    # -- endpoints ------------------------------------------------------------
    def prices_latest(self, origin, destination=None, beginning_of_period=None,
                      period_type="month", one_way=False, limit=30):
        """/v2/prices/latest — cheapest cached tickets (list payload, ``value``)."""
        params = self._base_params(
            origin=origin,
            destination=destination,
            beginning_of_period=beginning_of_period,
            period_type=period_type,
            one_way=str(one_way).lower(),
            limit=limit,
            show_to_affiliates="true",
            sorting="price",
        )
        resp = self.get_json(f"{BASE}/v2/prices/latest", params)
        return [self._with_link(models.from_tp_v2_row(r, self.currency, "tp:prices_latest"))
                for r in resp.get("data", [])]

    def month_matrix(self, origin, destination, month):
        """/v2/prices/month-matrix — one row per day of a month (list, ``value``)."""
        params = self._base_params(
            origin=origin, destination=destination, month=month,
            show_to_affiliates="true",
        )
        resp = self.get_json(f"{BASE}/v2/prices/month-matrix", params)
        return [self._with_link(models.from_tp_v2_row(r, self.currency, "tp:month_matrix"))
                for r in resp.get("data", [])]

    def city_directions(self, origin):
        """/v1/city-directions — cheapest from a city to everywhere (dict, ``price``)."""
        params = self._base_params(origin=origin)
        resp = self.get_json(f"{BASE}/v1/city-directions", params)
        data = resp.get("data") or {}
        return [self._with_link(models.from_tp_v1_entry(entry, self.currency, "tp:city_directions"))
                for entry in data.values()]
