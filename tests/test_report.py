from datetime import date

from farewatch import config, db, report
from farewatch.models import FareRecord


TODAY = date(2026, 7, 9)


def test_build_report_mentions_route_and_cheapest(conn, sample_config):
    sid = db.record_search(conn, 1, "MEX", "LHR", "2026-09-11", None, "tp:month_matrix")
    db.record_fare(conn, sid, FareRecord("MEX", "LHR", 588.0, "usd",
                   depart_date="2026-09-11", carrier="BA", source="tp:month_matrix"))
    db.upsert_daily_min(conn, "MEX-LHR", "2026-07-09", 588.0)
    cfg = config.load_config(str(sample_config))
    text = report.build_report(conn, cfg, TODAY)
    assert "MEX-LHR" in text
    assert "588" in text
    assert "Duffel spend" in text
