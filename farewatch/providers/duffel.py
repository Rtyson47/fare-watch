"""Tier 2 (paid) Duffel client — real offer-request search, gate preserved.

Duffel live mode is billed. ``search`` raises :class:`DuffelGateError` unless
the *double gate* is satisfied: config ``duffel.live_confirmed: true`` AND env
``DUFFEL_ENABLE_LIVE=1`` (checked at construction time via ``live=True,
live_confirmed=True``) — or the client is built with ``test_mode=True`` for
the free/sandbox ``duffel_test_*`` key, which never charges.

Only the runner may build a *live* client, and only after passing every
search through ``spend.guard``/``spend.record_duffel_search`` first. This
module has no knowledge of guardrails — it just makes (or refuses to make)
the HTTP call.
"""
import os

from . import http
from ..models import FareRecord

API_URL = "https://api.duffel.com/air/offer_requests?return_offers=true"
DUFFEL_VERSION = "v2"
MAX_OFFERS_KEPT = 3


class DuffelGateError(RuntimeError):
    """Raised when a Duffel live/test search is attempted without the gate open."""


class DuffelClient:
    def __init__(self, api_key=None, live=False, live_confirmed=False, test_mode=False,
                 post_json=http.post_json):
        self.api_key = api_key
        self.test_mode = test_mode
        self._post_json = post_json
        # test_mode uses a duffel_test_* key (no charge). Live requires the double gate.
        self.enabled = test_mode or (
            live and live_confirmed and os.environ.get("DUFFEL_ENABLE_LIVE") == "1")

    def search(self, origin, dest, depart_date, return_date=None, cabin="economy"):
        if not self.enabled:
            raise DuffelGateError(
                "Duffel is gated — no charge made. To enable live verification set "
                "config duffel.live_confirmed: true AND env DUFFEL_ENABLE_LIVE=1 "
                "(or construct with test_mode=True for the sandbox).")

        slices = [{"origin": origin, "destination": dest, "departure_date": depart_date}]
        if return_date:
            slices.append({"origin": dest, "destination": origin, "departure_date": return_date})
        payload = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"}],
                "cabin_class": cabin,
            }
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Duffel-Version": DUFFEL_VERSION,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        resp = self._post_json(API_URL, payload, headers=headers)
        offers = (resp.get("data") or {}).get("offers") or []
        offers = sorted(offers, key=lambda o: float(o["total_amount"]))[:MAX_OFFERS_KEPT]
        source = "duffel_test" if self.test_mode else "duffel"
        return [from_duffel_offer(o, origin, dest, depart_date, return_date, source)
                for o in offers]


def from_duffel_offer(offer, origin, dest, depart_date, return_date, source):
    """Map a Duffel offer dict to a :class:`FareRecord`.

    Duffel has no public booking deep link — the offer id is the actionable
    handle for a follow-up booking flow, so ``deep_link`` stays ``None``.
    Offers are large; only a trimmed subset is retained in ``raw``.
    """
    owner = offer.get("owner") or {}
    carrier = owner.get("iata_code") or owner.get("name")
    trimmed = {
        "id": offer.get("id"),
        "total_amount": offer.get("total_amount"),
        "total_currency": offer.get("total_currency"),
        "owner_name": owner.get("name"),
    }
    return FareRecord(
        origin=origin,
        destination=dest,
        price=float(offer["total_amount"]),
        currency=(offer.get("total_currency") or "").lower(),
        depart_date=depart_date,
        return_date=return_date,
        carrier=carrier,
        one_way=return_date is None,
        source=source,
        deep_link=None,
        raw=trimmed,
    )
