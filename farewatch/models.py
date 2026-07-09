"""The single normalized fare shape and adapters from provider payloads.

Travelpayouts is deliberately inconsistent:
  * v2 (prices/latest, month-matrix): price is ``value``; dates are
    ``depart_date`` / ``return_date``; ``data`` is a *list*.
  * v1 (city-directions, prices/cheap): price is ``price``; dates are
    ``departure_at`` / ``return_at`` (ISO datetimes); ``data`` is a *dict*.
Everything collapses to :class:`FareRecord`.
"""
from dataclasses import dataclass, field
from datetime import date


@dataclass
class FareRecord:
    origin: str
    destination: str
    price: float
    currency: str
    depart_date: str | None = None
    return_date: str | None = None
    carrier: str | None = None
    one_way: bool = False
    source: str = ""
    deep_link: str | None = None
    raw: dict = field(default_factory=dict)


def route_key(origin, destination):
    return f"{origin}-{destination}"


def _date_only(s):
    return s[:10] if s else None


def from_tp_v2_row(row, currency, source):
    """Adapt a Travelpayouts v2 row (prices/latest, month-matrix)."""
    rd = _date_only(row.get("return_date") or None)
    return FareRecord(
        origin=row["origin"],
        destination=row["destination"],
        price=float(row["value"]),
        currency=currency,
        depart_date=_date_only(row.get("depart_date")),
        return_date=rd,
        one_way=rd is None,
        source=source,
        raw=row,
    )


def from_tp_v1_entry(entry, currency, source):
    """Adapt a Travelpayouts v1 entry (city-directions, prices/cheap)."""
    rd = _date_only(entry.get("return_at") or None)
    return FareRecord(
        origin=entry["origin"],
        destination=entry["destination"],
        price=float(entry["price"]),
        currency=currency,
        depart_date=_date_only(entry.get("departure_at")),
        return_date=rd,
        carrier=entry.get("airline"),
        one_way=rd is None,
        source=source,
        raw=entry,
    )


def aviasales_deep_link(origin, dest, depart_date, return_date=None, marker=None, pax=1):
    """Build an Aviasales search deep link (cached Data API rarely returns one)."""
    def ddmm(s):
        d = date.fromisoformat(s[:10])
        return f"{d.day:02d}{d.month:02d}"

    path = f"{origin}{ddmm(depart_date)}{dest}"
    if return_date:
        path += ddmm(return_date)
    path += str(pax)
    url = f"https://www.aviasales.com/search/{path}"
    return f"{url}?marker={marker}" if marker else url
