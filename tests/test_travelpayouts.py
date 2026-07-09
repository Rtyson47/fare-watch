import pytest

from farewatch.providers.travelpayouts import TravelpayoutsClient


class FakeGetJson:
    """Records the last (url, params) and returns a canned payload."""
    def __init__(self, payload):
        self.payload = payload
        self.url = None
        self.params = None

    def __call__(self, url, params, headers=None, opener=None):
        self.url = url
        self.params = params
        return self.payload


def make_client(payload):
    fake = FakeGetJson(payload)
    client = TravelpayoutsClient(token="TESTTOKEN", get_json=fake)
    return client, fake


def test_prices_latest_sends_market_currency_token(load_fixture):
    client, fake = make_client(load_fixture("tp_prices_latest.json"))
    fares = client.prices_latest("MEX", destination="LHR",
                                 beginning_of_period="2026-09-01", one_way=False)
    assert fake.url.endswith("/v2/prices/latest")
    assert fake.params["market"] == "us"
    assert fake.params["currency"] == "usd"
    assert fake.params["token"] == "TESTTOKEN"
    assert fake.params["one_way"] == "false"
    assert [f.price for f in fares] == [612.0, 705.0]
    assert fares[0].depart_date == "2026-09-11"
    assert fares[0].source == "tp:prices_latest"
    assert fares[0].deep_link and "MEX1109LHR1409" in fares[0].deep_link


def test_month_matrix_returns_records(load_fixture):
    client, fake = make_client(load_fixture("tp_month_matrix.json"))
    fares = client.month_matrix("MEX", "LHR", "2026-09-01")
    assert fake.url.endswith("/v2/prices/month-matrix")
    assert fake.params["month"] == "2026-09-01"
    assert len(fares) == 3
    assert fares[1].price == 588.0
    assert all(f.source == "tp:month_matrix" for f in fares)


def test_city_directions_flattens_dict(load_fixture):
    client, fake = make_client(load_fixture("tp_city_directions.json"))
    fares = client.city_directions("MEX")
    assert fake.url.endswith("/v1/city-directions")
    assert fake.params["market"] == "us" and fake.params["currency"] == "usd"
    by_dest = {f.destination: f for f in fares}
    assert set(by_dest) == {"BKK", "MAD", "NYC"}
    assert by_dest["BKK"].price == 388.0
    assert by_dest["BKK"].carrier == "TG"
    assert by_dest["BKK"].depart_date == "2026-08-25"
