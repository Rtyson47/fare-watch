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


def within_horizon(depart_date, today, horizon_weeks):
    d = date.fromisoformat(depart_date[:10])
    return today <= d <= today + timedelta(weeks=horizon_weeks)


def run_inspiration(tp_client, insp_cfg, today, airports):
    ceiling = insp_cfg.get("price_ceiling")
    horizon = insp_cfg.get("horizon_weeks")
    whitelist = insp_cfg.get("region_whitelist") or []
    out = []
    for origin in insp_cfg.get("origins", []) or []:
        for fare in tp_client.city_directions(origin):
            if ceiling is not None and fare.price > ceiling:
                continue
            if horizon is not None and fare.depart_date and not within_horizon(
                    fare.depart_date, today, horizon):
                continue
            if not passes_whitelist(fare.destination, whitelist, airports):
                continue
            out.append(fare)
    out.sort(key=lambda f: f.price)
    return out


def top_candidates(shortlist, n):
    return shortlist[:n]
