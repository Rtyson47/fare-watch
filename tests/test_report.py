from datetime import date

from farewatch import config, db, report
from farewatch.models import FareRecord


TODAY = date(2026, 7, 9)


def test_build_report_mentions_route_and_cheapest(conn, sample_config):
    sid = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", "2026-09-14", "tp:prices_latest")
    db.record_fare(conn, sid, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", return_date="2026-09-14", carrier="BA",
                   source="tp:prices_latest"))
    db.upsert_daily_min(conn, "MEX+2-LHR", "2026-07-09", 588.0)
    cfg = config.load_config(str(sample_config))
    text = report.build_report(conn, cfg, TODAY)
    assert "MEX+2-LHR" in text
    assert "588" in text
    assert "Duffel spend" in text


def test_build_report_shows_deadline_watches(conn, sample_config):
    sid = db.record_search(conn, 1, "MEX", "MAN", "2026-12-01", None, "tp:prices_latest")
    db.record_fare(conn, sid, FareRecord("MEX", "MAN", 400.0, "usd",
                   depart_date="2026-12-01", carrier="BA", source="tp:prices_latest"))
    db.upsert_daily_min(conn, "MEX-MAN", "2026-07-09", 400.0)
    cfg = config.load_config(str(sample_config))
    text = report.build_report(conn, cfg, TODAY)
    assert "Deadline watches:" in text
    assert "MEX-MAN" in text
    assert "2026-12-24" in text          # must_arrive_by from config.example.yaml
