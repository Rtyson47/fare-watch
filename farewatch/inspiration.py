"""Tier 1 discovery scan: BASE -> anywhere, cheap, soon, optionally region-gated.

Produces a shortlist of candidate :class:`FareRecord`s. The top-N of these are
the *only* inspiration fares that Tier 2 (Duffel) is ever allowed to verify.
"""
import json
from datetime import date, timedelta
from pathlib import Path

_AIRPORTS_PATH = Path(__file__).parent / "data" / "airports.json"


def load_airports(path=_AIRPORTS_PATH):
    with open(path) as f:
        return json.load(f)


def country_of(iata, airports):
    return airports.get(iata)


def passes_whitelist(dest, whitelist, airports):
    """Empty whitelist => anywhere. Else match explicit IATA or its country code."""
    if not whitelist:
        return True
    if dest in whitelist:
        return True
    country = country_of(dest, airports)
    return country is not None and country in whitelist


def within_horizon(depart_date, today, horizon_weeks=None, horizon_days=None):
    d = date.fromisoformat(depart_date[:10])
    span = timedelta(days=horizon_days) if horizon_days is not None else timedelta(weeks=horizon_weeks)
    return today <= d <= today + span


def _horizon_months(today, insp_cfg):
    """Calendar months (``YYYY-MM-01``) the horizon touches, for per-month endpoints."""
    days = insp_cfg.get("horizon_days")
    if days is None:
        days = 7 * (insp_cfg.get("horizon_weeks") or 8)
    end = today + timedelta(days=days)
    months, d = [], today.replace(day=1)
    while d <= end:
        months.append(d.isoformat())
        d = (d + timedelta(days=32)).replace(day=1)
    return months


def _candidates(tp_client, origin, insp_cfg, today):
    """Raw fares for ``origin`` from each configured source.

    ``city_directions`` (default) is one cached fare per destination, which may
    fall outside a short horizon. ``prices_latest`` (opt-in) pulls up to 1000
    cached fares per calendar month with no destination, so a short "next month"
    horizon still finds something for most cities. Its rows are retagged so the
    dashboard can tell them apart from corridor prices_latest rows.
    """
    sources = insp_cfg.get("sources") or ["city_directions"]
    one_way = insp_cfg.get("trip_type") == "one_way"
    fares = []
    if "city_directions" in sources:
        fares += tp_client.city_directions(origin)
    if "prices_latest" in sources:
        for month in _horizon_months(today, insp_cfg):
            for fare in tp_client.prices_latest(origin, beginning_of_period=month,
                                                one_way=one_way, limit=1000):
                fare.origin = origin
                fare.source = "tp:inspiration_latest"
                fares.append(fare)
    return fares


def run_inspiration(tp_client, insp_cfg, today, airports):
    """Cheapest in-scope fare per (origin, destination), sorted by price."""
    ceiling = insp_cfg.get("price_ceiling")
    horizon_weeks = insp_cfg.get("horizon_weeks")
    horizon_days = insp_cfg.get("horizon_days")
    whitelist = insp_cfg.get("region_whitelist") or []
    trip_type = insp_cfg.get("trip_type")          # "return" | "one_way" | None = either
    best = {}
    for origin in insp_cfg.get("origins", []) or []:
        for fare in _candidates(tp_client, origin, insp_cfg, today):
            if ceiling is not None and fare.price > ceiling:
                continue
            if trip_type == "return" and not fare.return_date:
                continue
            if trip_type == "one_way" and fare.return_date:
                continue
            if (horizon_weeks is not None or horizon_days is not None) and fare.depart_date \
                    and not within_horizon(fare.depart_date, today, horizon_weeks, horizon_days):
                continue
            if not passes_whitelist(fare.destination, whitelist, airports):
                continue
            key = (fare.origin, fare.destination)
            if key not in best or fare.price < best[key].price:
                best[key] = fare
    return sorted(best.values(), key=lambda f: f.price)


def top_candidates(shortlist, n):
    return shortlist[:n]
