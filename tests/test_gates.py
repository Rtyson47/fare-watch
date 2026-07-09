"""Safety tests for the paid-provider gates (Phase 1 guarantees)."""
import pytest

from farewatch import seats_aero
from farewatch.providers import duffel


def test_duffel_gated_without_env(monkeypatch):
    monkeypatch.delenv("DUFFEL_ENABLE_LIVE", raising=False)
    client = duffel.DuffelClient(api_key="x", live=True, live_confirmed=True)
    with pytest.raises(duffel.DuffelGateError):
        client.search("MEX", "LHR", "2026-09-11")


def test_duffel_gated_without_config_confirm(monkeypatch):
    monkeypatch.setenv("DUFFEL_ENABLE_LIVE", "1")
    client = duffel.DuffelClient(api_key="x", live=True, live_confirmed=False)
    with pytest.raises(duffel.DuffelGateError):
        client.search("MEX", "LHR", "2026-09-11")


def test_duffel_test_mode_is_not_live_charge(monkeypatch):
    # test_mode is allowed past the gate but the live request is still Phase 2
    client = duffel.DuffelClient(api_key="duffel_test_x", test_mode=True)
    with pytest.raises(NotImplementedError):
        client.search("MEX", "LHR", "2026-09-11")


def test_seats_aero_disabled_returns_empty():
    assert seats_aero.check_award_space({"origin": "MEX", "destination": "LHR"},
                                        {"awards": {"enabled": False}}) == []
