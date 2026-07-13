"""Expand corridor + deadline config into concrete search specs.

Handles the two date-window grammars from the spec:
  * explicit ranges ``"YYYY-MM-DD:YYYY-MM-DD"`` (per-day one-way anchors), and
  * ``"any <Dow>-<Dow> in YYYY-MM"`` (e.g. weekend trips: depart on the first
    weekday, return on the next occurrence of the second).
Plus ±N-day flex around anchors and per-corridor ``origin_variants``.
"""
import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

_DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_ANY_RE = re.compile(r"^\s*any\s+(\w{3})\w*-(\w{3})\w*\s+in\s+(\d{4})-(\d{2})\s*$", re.I)
_RANGE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2}):(\d{4}-\d{2}-\d{2})\s*$")
_SINGLE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*$")


@dataclass
class SearchSpec:
    origin: str
    destination: str
    depart_date: str
    return_date: str | None
    one_way: bool
    cabin: str | None = None
    max_price: float | None = None
    currency: str | None = None
    alert_threshold: float | None = None
    tier_hint: int = 2


def _iso(d):
    return d.isoformat()


def parse_date_window(entry, today):
    """Return a list of ``(depart, return_or_None)`` ISO-date tuples."""
    m = _ANY_RE.match(entry)
    if m:
        d1, d2, year, month = m.group(1).lower(), m.group(2).lower(), int(m.group(3)), int(m.group(4))
        first, second = _DOW[d1], _DOW[d2]
        delta = (second - first) % 7 or 7          # next occurrence, never same day
        pairs = []
        _, days_in_month = calendar.monthrange(year, month)
        for day in range(1, days_in_month + 1):
            d = date(year, month, day)
            if d.weekday() == first:
                pairs.append((_iso(d), _iso(d + timedelta(days=delta))))
        return pairs

    m = _RANGE_RE.match(entry)
    if m:
        start = max(date.fromisoformat(m.group(1)), today)
        end = date.fromisoformat(m.group(2))
        out = []
        d = start
        while d <= end:
            out.append((_iso(d), None))
            d += timedelta(days=1)
        return out

    m = _SINGLE_RE.match(entry)
    if m:
        return [(m.group(1), None)]

    raise ValueError(f"Unrecognized date_window: {entry!r}")


def flex_dates(depart, return_, flex):
    """Cartesian ±0..flex around each anchor (full grid, incl. the anchor)."""
    d0 = date.fromisoformat(depart)
    depart_opts = [_iso(d0 + timedelta(days=n)) for n in range(-flex, flex + 1)]
    if return_ is None:
        return [(d, None) for d in depart_opts]
    r0 = date.fromisoformat(return_)
    return_opts = [_iso(r0 + timedelta(days=n)) for n in range(-flex, flex + 1)]
    return [(d, r) for d in depart_opts for r in return_opts]


def expand_corridor(corridor, today):
    origins = [corridor["origin"]] + list(corridor.get("origin_variants", []) or [])
    flex = corridor.get("flex_days", 3)
    force_oneway = corridor.get("trip_type") == "one_way"
    today_iso = _iso(today)
    specs = []
    for window in corridor.get("date_windows", []) or []:
        # Explicit ranges already enumerate every day, so flex would only add
        # days *outside* the window (e.g. "Sep onwards" searching late Aug).
        window_flex = 0 if _RANGE_RE.match(window) else flex
        for dep, ret in parse_date_window(window, today):
            for d, r in flex_dates(dep, ret if not force_oneway else None, window_flex):
                if d < today_iso:
                    continue                       # never search departed dates
                if r is not None and r < d:
                    continue                       # never return before departure
                for origin in origins:
                    specs.append(SearchSpec(
                        origin=origin, destination=corridor["destination"],
                        depart_date=d, return_date=r,
                        one_way=r is None,
                        cabin=corridor.get("cabin"), max_price=corridor.get("max_price"),
                        currency=corridor.get("currency"),
                        alert_threshold=corridor.get("alert_threshold"), tier_hint=2))
    return specs


def expand_deadline(watch, base, today, horizon_days=120):
    """One-way ``base(+variants) -> destination`` for each day up to ``must_arrive_by``.

    ``earliest_depart``, if set, floors the window so departures before it
    (e.g. dates you don't actually want to travel) aren't searched.
    ``origin_variants`` (like corridors) also checks fares from those origins.
    """
    arrive_by = date.fromisoformat(watch["must_arrive_by"])
    origins = [watch.get("origin") or base] + list(watch.get("origin_variants", []) or [])
    floor = today
    if watch.get("earliest_depart"):
        floor = max(floor, date.fromisoformat(watch["earliest_depart"]))
    start = max(floor, arrive_by - timedelta(days=horizon_days - 1))
    specs = []
    d = start
    while d <= arrive_by:
        for origin in origins:
            specs.append(SearchSpec(
                origin=origin, destination=watch["destination"],
                depart_date=_iso(d), return_date=None, one_way=True,
                max_price=watch.get("max_price"), currency=watch.get("currency"),
                alert_threshold=watch.get("max_price"), tier_hint=2))
        d += timedelta(days=1)
    return specs
