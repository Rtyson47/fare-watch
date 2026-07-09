"""Tier 2 (paid) Duffel client — GATED STUB.

Duffel live mode is billed. This build never makes a live call: ``search``
raises :class:`DuffelGateError` unless the *double gate* is satisfied
(config ``duffel.live_confirmed: true`` AND env ``DUFFEL_ENABLE_LIVE=1``), and
even then the live request itself is a Phase-2 ``NotImplementedError`` — so no
accidental charge is possible from this code.

PHASE 2 TODO (only after the user confirms billing):
  * POST /air/offer_requests (slices, passengers, cabin_class) using the live
    or test key; read offers; map to FareRecord via ``from_duffel_offer``.
  * Wrap every search in ``spend.guard(conn, guardrails, day)`` and
    ``spend.record_duffel_search`` — hard-stop on GuardrailHit.
  * Verify only (a) corridor watchlist specs and (b) top-N inspiration
    candidates. Never open-ended discovery.
"""
import os


class DuffelGateError(RuntimeError):
    """Raised when a Duffel live/test search is attempted without the gate open."""


class DuffelClient:
    def __init__(self, api_key=None, live=False, live_confirmed=False, test_mode=False):
        self.api_key = api_key
        self.test_mode = test_mode
        # test_mode uses a duffel_test_* key (no charge). Live requires the double gate.
        self.enabled = test_mode or (
            live and live_confirmed and os.environ.get("DUFFEL_ENABLE_LIVE") == "1")

    def search(self, origin, dest, depart_date, return_date=None, cabin="economy"):
        if not self.enabled:
            raise DuffelGateError(
                "Duffel is gated — no charge made. To enable live verification set "
                "config duffel.live_confirmed: true AND env DUFFEL_ENABLE_LIVE=1 "
                "(or construct with test_mode=True for the sandbox).")
        raise NotImplementedError(
            "Duffel offer search is Phase 2 — implement /air/offer_requests here.")


def from_duffel_offer(offer, currency):
    """PHASE 2 TODO: map a Duffel offer dict to a FareRecord (real deep link / offer id)."""
    raise NotImplementedError("Phase 2: map Duffel offer -> FareRecord.")
