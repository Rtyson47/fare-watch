from datetime import datetime, timedelta, timezone

from farewatch import db
from farewatch.models import FareRecord


def _tables(conn):
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}


def test_schema_has_all_tables(conn):
    assert {"searches", "fares", "daily_min", "alerts", "spend"} <= _tables(conn)


def test_search_and_fare_roundtrip(conn):
    sid = db.record_search(conn, tier=1, origin="MEX", dest="LHR",
                           depart_date="2026-09-11", return_date="2026-09-14",
                           source="tp:prices_latest")
    assert isinstance(sid, int)
    fare = FareRecord(origin="MEX", destination="LHR", price=612.0, currency="usd",
                      depart_date="2026-09-11", return_date="2026-09-14", carrier="BA",
                      source="tp:prices_latest", deep_link="http://x", raw={"value": 612})
    fid = db.record_fare(conn, sid, fare)
    row = conn.execute("SELECT * FROM fares WHERE id=?", (fid,)).fetchone()
    assert row["price"] == 612.0 and row["currency"] == "usd"
    assert row["search_id"] == sid
    assert '"value": 612' in row["raw_json"]


def test_upsert_daily_min_keeps_minimum(conn):
    db.upsert_daily_min(conn, "MEX-LHR", "2026-07-09", 600.0)
    db.upsert_daily_min(conn, "MEX-LHR", "2026-07-09", 550.0)   # lower -> wins
    db.upsert_daily_min(conn, "MEX-LHR", "2026-07-09", 900.0)   # higher -> ignored
    rows = conn.execute("SELECT min_price FROM daily_min WHERE route=? AND date=?",
                        ("MEX-LHR", "2026-07-09")).fetchall()
    assert len(rows) == 1
    assert rows[0]["min_price"] == 550.0


def test_trailing_daily_min(conn):
    db.upsert_daily_min(conn, "MEX-LHR", "2026-07-01", 700.0)
    db.upsert_daily_min(conn, "MEX-LHR", "2026-07-05", 650.0)
    db.upsert_daily_min(conn, "OTH-XXX", "2026-07-05", 100.0)
    vals = db.trailing_daily_min(conn, "MEX-LHR", since_date="2026-07-02")
    assert vals == [650.0]   # only the in-window MEX-LHR row


def test_recent_alert_exists_window(conn):
    now = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    db.record_alert(conn, route="MEX-LHR", price=500.0, reason="below_max_price",
                    channel="dry-run", dedupe_key="MEX-LHR|below_max_price|25",
                    ts=now.isoformat())
    before = (now - timedelta(hours=1)).isoformat()
    after = (now + timedelta(hours=1)).isoformat()
    assert db.recent_alert_exists(conn, "MEX-LHR|below_max_price|25", since_ts=before) is True
    assert db.recent_alert_exists(conn, "MEX-LHR|below_max_price|25", since_ts=after) is False
