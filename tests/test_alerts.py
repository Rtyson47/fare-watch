from datetime import date, datetime, timedelta, timezone

from farewatch import alerts, db
from farewatch.models import FareRecord


TODAY = date(2026, 7, 9)
NOW = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _fare(price):
    return FareRecord(origin="MEX", destination="LHR", price=price, currency="usd",
                      depart_date="2026-09-11", source="tp:prices_latest")


def _seed_daily_min(conn, prices):
    d = TODAY
    for p in prices:
        db.upsert_daily_min(conn, "MEX-LHR", d.isoformat(), p)
        d -= timedelta(days=1)


def test_dedupe_key_bands_price():
    assert alerts.dedupe_key("MEX-LHR", "below_max_price", 500, 20) == "MEX-LHR|below_max_price|25"
    assert alerts.dedupe_key("MEX-LHR", "below_max_price", 511, 20) == "MEX-LHR|below_max_price|25"


def test_below_max_price_rule(conn):
    ctx = alerts.AlertContext(max_price=650, today=TODAY)
    a = alerts.evaluate_fare(conn, _fare(500), ctx)
    assert a is not None and a.reason == "below_max_price" and a.route == "MEX-LHR"


def test_below_median_rule(conn):
    _seed_daily_min(conn, [600, 600, 600, 600, 600, 600])   # median 600, 6 samples
    ctx = alerts.AlertContext(max_price=None, median_ratio=0.80, min_samples=5, today=TODAY)
    assert alerts.evaluate_fare(conn, _fare(470), ctx).reason == "below_median"  # < 480
    assert alerts.evaluate_fare(conn, _fare(500), ctx) is None                   # >= 480


def test_below_median_rule_uses_ctx_route_for_labeled_watch(conn):
    # History seeded under the watch's label, not the bare route_key.
    d = TODAY
    for p in [600, 600, 600, 600, 600, 600]:
        db.upsert_daily_min(conn, "YVR-LON return", d.isoformat(), p)
        d -= timedelta(days=1)
    ctx = alerts.AlertContext(max_price=None, median_ratio=0.80, min_samples=5, today=TODAY,
                              route="YVR-LON return")
    fare = FareRecord(origin="YVR", destination="LON", price=470, currency="usd",
                      depart_date="2026-09-11", source="tp:prices_latest")
    alert = alerts.evaluate_fare(conn, fare, ctx)
    assert alert is not None and alert.reason == "below_median"
    assert alert.route == "YVR-LON return"


def test_below_median_rule_no_alert_when_history_only_under_bare_route_key(conn):
    # History seeded under the bare "ORI-DST" key, NOT the label; lookup must
    # use ctx.route (the label), so no median alert should fire.
    d = TODAY
    for p in [600, 600, 600, 600, 600, 600]:
        db.upsert_daily_min(conn, "YVR-LON", d.isoformat(), p)
        d -= timedelta(days=1)
    ctx = alerts.AlertContext(max_price=None, median_ratio=0.80, min_samples=5, today=TODAY,
                              route="YVR-LON return")
    fare = FareRecord(origin="YVR", destination="LON", price=470, currency="usd",
                      depart_date="2026-09-11", source="tp:prices_latest")
    assert alerts.evaluate_fare(conn, fare, ctx) is None


def test_median_needs_min_samples(conn):
    _seed_daily_min(conn, [600, 600, 600, 600])            # only 4 samples
    ctx = alerts.AlertContext(max_price=None, min_samples=5, today=TODAY)
    assert alerts.evaluate_fare(conn, _fare(300), ctx) is None


def test_should_send_dedupes_within_window(conn):
    a = alerts.Alert("MEX-LHR", 500, "below_max_price", "MEX-LHR|below_max_price|25")
    db.record_alert(conn, a.route, a.price, a.reason, "dry-run", a.dedupe_key, ts=NOW.isoformat())
    assert alerts.should_send(conn, a, window_hours=24, now=NOW) is False
    later = NOW + timedelta(hours=25)
    assert alerts.should_send(conn, a, window_hours=24, now=later) is True


def test_digest_collects_without_sending(conn):
    sent = []
    ctx = alerts.AlertContext(max_price=650, today=TODAY)
    a = alerts.process_fare(conn, _fare(500), ctx, send=sent.append, label="dry-run",
                            window_hours=24, now=NOW, digest=True)
    assert a is not None
    assert sent == []                                        # nothing sent yet
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 0


def test_dispatch_records_only_on_successful_delivery(conn):
    a = alerts.Alert("MEX-LHR", 500, "below_max_price", "MEX-LHR|below_max_price|25")
    delivered = alerts.dispatch(conn, a, send=lambda text: True, label="dry-run", now=NOW)
    assert delivered is True
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 1


def test_dispatch_failed_delivery_records_nothing(conn):
    a = alerts.Alert("MEX-LHR", 500, "below_max_price", "MEX-LHR|below_max_price|25")
    delivered = alerts.dispatch(conn, a, send=lambda text: False, label="dry-run", now=NOW)
    assert delivered is False
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 0


def test_process_fare_failed_delivery_not_recorded_and_retries_next_run(conn):
    ctx = alerts.AlertContext(max_price=650, today=TODAY)
    calls = []

    def failing_send(text):
        calls.append(text)
        return False

    first = alerts.process_fare(conn, _fare(500), ctx, send=failing_send, label="dry-run",
                                window_hours=24, now=NOW, digest=False)
    assert first is None
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 0

    # Nothing was recorded, so should_send is still True and delivery is retried.
    second = alerts.process_fare(conn, _fare(500), ctx, send=failing_send, label="dry-run",
                                 window_hours=24, now=NOW, digest=False)
    assert second is None
    assert len(calls) == 2
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 0


def test_process_fare_success_recorded_once_then_deduped(conn):
    ctx = alerts.AlertContext(max_price=650, today=TODAY)
    calls = []

    def ok_send(text):
        calls.append(text)
        return True

    first = alerts.process_fare(conn, _fare(500), ctx, send=ok_send, label="dry-run",
                                window_hours=24, now=NOW, digest=False)
    assert first is not None
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 1

    second = alerts.process_fare(conn, _fare(500), ctx, send=ok_send, label="dry-run",
                                 window_hours=24, now=NOW, digest=False)
    assert second is None                                    # deduped within window
    assert len(calls) == 1                                   # no second delivery attempt
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 1


def test_send_digest_failed_delivery_records_nothing(conn):
    a = alerts.Alert("MEX-LHR", 500, "below_max_price", "MEX-LHR|below_max_price|25")
    alerts.send_digest(conn, [a], send=lambda text: False, label="dry-run", now=NOW)
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 0


def test_send_digest_success_records_all(conn):
    a1 = alerts.Alert("MEX-LHR", 500, "below_max_price", "MEX-LHR|below_max_price|25")
    a2 = alerts.Alert("MEX-NYC", 210, "below_max_price", "MEX-NYC|below_max_price|10")
    alerts.send_digest(conn, [a1, a2], send=lambda text: True, label="dry-run", now=NOW)
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 2
