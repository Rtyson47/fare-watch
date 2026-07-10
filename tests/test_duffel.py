"""Payload shape + offer-mapping tests for the Duffel client (no network)."""
from farewatch.providers import duffel


def _fake_post_json(fixture):
    def _post(url, payload, headers=None, opener=None, timeout=20):
        _post.calls.append({"url": url, "payload": payload, "headers": headers})
        return fixture
    _post.calls = []
    return _post


def test_return_trip_builds_two_slices_and_passenger(load_fixture):
    fixture = load_fixture("duffel_offer_requests.json")
    post = _fake_post_json(fixture)
    client = duffel.DuffelClient(api_key="duffel_test_x", test_mode=True, post_json=post)
    client.search("MEX", "LHR", "2026-09-11", return_date="2026-09-18", cabin="premium_economy")

    payload = post.calls[0]["payload"]
    slices = payload["data"]["slices"]
    assert len(slices) == 2
    assert slices[0] == {"origin": "MEX", "destination": "LHR", "departure_date": "2026-09-11"}
    assert slices[1] == {"origin": "LHR", "destination": "MEX", "departure_date": "2026-09-18"}
    assert payload["data"]["passengers"] == [{"type": "adult"}]
    assert payload["data"]["cabin_class"] == "premium_economy"


def test_one_way_builds_single_slice(load_fixture):
    fixture = load_fixture("duffel_offer_requests.json")
    post = _fake_post_json(fixture)
    client = duffel.DuffelClient(api_key="duffel_test_x", test_mode=True, post_json=post)
    client.search("MEX", "LHR", "2026-09-11")

    slices = post.calls[0]["payload"]["data"]["slices"]
    assert len(slices) == 1
    assert slices[0]["origin"] == "MEX"


def test_search_maps_offers_sorted_cheapest_first(load_fixture):
    fixture = load_fixture("duffel_offer_requests.json")
    post = _fake_post_json(fixture)
    client = duffel.DuffelClient(api_key="duffel_test_x", test_mode=True, post_json=post)
    fares = client.search("MEX", "LHR", "2026-09-11", return_date="2026-09-18")

    prices = [f.price for f in fares]
    assert prices == sorted(prices)
    assert prices[0] == 588.40

    cheapest = fares[0]
    assert cheapest.currency == "usd"
    assert cheapest.carrier == "BA"
    assert cheapest.one_way is False
    assert cheapest.deep_link is None
    assert cheapest.source == "duffel_test"
    assert set(cheapest.raw.keys()) == {"id", "total_amount", "total_currency", "owner_name"}


def test_from_duffel_offer_one_way_when_no_return_date():
    offer = {"id": "off_x", "total_amount": "100.00", "total_currency": "GBP",
              "owner": {"name": "Test Air"}}
    fare = duffel.from_duffel_offer(offer, "MEX", "LHR", "2026-09-11", None, "duffel")
    assert fare.one_way is True
    assert fare.carrier == "Test Air"
    assert fare.price == 100.0
    assert fare.currency == "gbp"
