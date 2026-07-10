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


def test_duffel_test_mode_searches_via_injected_post_json(load_fixture):
    calls = {}

    def fake_post_json(url, payload, headers=None, opener=None, timeout=20):
        calls["url"] = url
        calls["headers"] = headers
        calls["payload"] = payload
        return load_fixture("duffel_offer_requests.json")

    client = duffel.DuffelClient(api_key="duffel_test_x", test_mode=True,
                                 post_json=fake_post_json)
    fares = client.search("MEX", "LHR", "2026-09-11")
    assert fares
    assert all(f.price > 0 for f in fares)
    assert calls["url"] == "https://api.duffel.com/air/offer_requests?return_offers=true"
    assert calls["headers"]["Authorization"] == "Bearer duffel_test_x"


def test_seats_aero_disabled_returns_empty():
    assert seats_aero.check_award_space({"origin": "MEX", "destination": "LHR"},
                                        {"awards": {"enabled": False}}) == []
