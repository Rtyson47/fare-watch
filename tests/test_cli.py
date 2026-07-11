import json
import urllib.error
from datetime import date

from farewatch import config, db, runner
from farewatch.testing import FixtureTP


TODAY = date(2026, 7, 9)


class _FlakyTP(FixtureTP):
    """Like FixtureTP, but every live-pricing call blows up like a real HTTP failure."""

    def prices_latest(self, *a, **kw):
        self.calls += 1
        raise urllib.error.URLError("boom")

    def month_matrix(self, *a, **kw):
        self.calls += 1
        raise urllib.error.URLError("boom")


def test_runner_tier1_dry_run_writes_data_and_alerts(conn, sample_config, tmp_path):
    cfg = config.load_config(str(sample_config))
    data = tmp_path / "data.json"
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(data))
    assert conn.execute("SELECT COUNT(*) c FROM searches").fetchone()["c"] > 0
    assert conn.execute("SELECT COUNT(*) c FROM fares").fetchone()["c"] > 0
    # The MEX->LHR corridor ("any Fri-Mon in 2026-09", flex 3) is a return
    # corridor, so it now prices via prices_latest: the fixture's two rows
    # (2026-09-11->09-14 @ 612 and 2026-09-18->09-21 @ 705) both land on a
    # Fri->Mon inside the windows and are kept -> corridor cheapest = 612,
    # which is NOT below alert_threshold 600 -> no corridor alert.
    # The MAN deadline watch (must_arrive_by 2026-12-24, max_price 650) prices
    # via month_matrix (one-way, per-day): the fixture's three rows all fall
    # inside the Aug27-Dec24 watch window -> cheapest 588 < 650 -> a
    # below_max_price dry-run alert still fires.
    channels = {r["channel"] for r in conn.execute("SELECT channel FROM alerts")}
    assert "dry-run" in channels
    assert summary["alerts"] >= 1
    # dashboard written
    assert json.loads(data.read_text())["base"] == "MEX"
    # Tier 1 only: no Duffel spend
    assert conn.execute("SELECT COUNT(*) c FROM spend").fetchone()["c"] == 0


def test_runner_full_run_gates_tier2_no_spend(conn, sample_config, tmp_path):
    cfg = config.load_config(str(sample_config))
    summary = runner.run(cfg, conn, TODAY, tier1_only=False, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"))
    assert summary["tier2_gated"] is True
    assert conn.execute("SELECT COUNT(*) c FROM spend").fetchone()["c"] == 0


def test_cli_set_base(sample_config):
    from farewatch.cli import main
    assert main(["--config", str(sample_config), "set-base", "LHR"]) == 0
    assert config.load_config(str(sample_config))["current_base"] == "LHR"


def test_cli_set_base_rejects_bad(sample_config):
    from farewatch.cli import main
    assert main(["--config", str(sample_config), "set-base", "nope"]) == 2


def test_cli_backfill_seeds_daily_min(sample_config, tmp_path, monkeypatch):
    from farewatch.cli import main
    monkeypatch.setenv("FAREWATCH_FAKE_TP", "1")
    dbp = tmp_path / "fw.db"
    rc = main(["--config", str(sample_config), "--db", str(dbp),
               "backfill", "--route", "MEX-LHR"])
    assert rc == 0
    conn2 = db.connect(str(dbp))
    n = conn2.execute("SELECT COUNT(*) c FROM daily_min WHERE route='MEX-LHR'").fetchone()["c"]
    assert n >= 1


def _minimal_cfg(**overrides):
    cfg = {
        "current_base": "MEX",
        "corridors": [],
        "deadline_watches": [],
        "inspiration": {"origins": [], "horizon_weeks": 8, "price_ceiling": 450,
                        "currency": "usd", "market": "us", "region_whitelist": [],
                        "top_n_to_verify": 10},
    }
    cfg.update(overrides)
    return cfg


def test_deadline_watch_before_fixture_departs_records_nothing(conn, tmp_path):
    # must_arrive_by is well before the fixture's Sept depart dates, so every
    # kept-candidate depart date is filtered out -> no fares, no alert.
    cfg = _minimal_cfg(deadline_watches=[
        {"destination": "MAN", "origin": "MEX", "must_arrive_by": "2026-08-01",
         "max_price": 650, "currency": "usd"},
    ])
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"))
    assert conn.execute("SELECT COUNT(*) c FROM searches WHERE dest='MAN'").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) c FROM alerts").fetchone()["c"] == 0
    assert summary["alerts"] == 0


def _return_corridor_cfg(alert_threshold):
    return _minimal_cfg(corridors=[{
        "origin": "MEX", "destination": "LHR",
        "date_windows": ["any Fri-Mon in 2026-09"],
        "trip_type": "return", "flex_days": 3,
        "max_price": 650, "alert_threshold": alert_threshold, "currency": "usd",
    }])


def test_corridor_alert_threshold_700_fires(conn, tmp_path):
    # cheapest kept return fare is 612; alert_threshold 700 -> alerts.
    cfg = _return_corridor_cfg(alert_threshold=700)
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"))
    assert summary["alerts"] >= 1


def test_corridor_alert_threshold_600_silent(conn, tmp_path):
    # same 612 cheapest fare; alert_threshold 600 -> no alert.
    cfg = _return_corridor_cfg(alert_threshold=600)
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"))
    assert summary["alerts"] == 0


def test_corridor_one_way_keeps_matching_month_matrix_rows(conn, tmp_path):
    # explicit range window + flex_days 0 -> one-way specs for 09-11 and 09-12
    # only; fixture month-matrix has 09-01@640 (dropped), 09-11@588, 09-12@690
    # -> cheapest kept is 588, which alerts below the 650 threshold.
    cfg = _minimal_cfg(corridors=[{
        "origin": "MEX", "destination": "LHR",
        "date_windows": ["2026-09-11:2026-09-12"],
        "trip_type": "one_way", "flex_days": 0,
        "max_price": 650, "currency": "usd",
    }])
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=FixtureTP(), export_path=str(tmp_path / "d.json"))
    cheapest = conn.execute("SELECT MIN(price) p FROM fares").fetchone()["p"]
    assert cheapest == 588
    assert summary["alerts"] >= 1


def test_cli_run_corridors_only_skips_inspiration(sample_config, tmp_path, monkeypatch):
    # --corridors-only should skip inspiration discovery entirely (no
    # tp:city_directions searches recorded) while corridor + deadline-watch
    # fares (from the sample config's MEX->LHR corridor and MAN deadline
    # watch) are still recorded as usual.
    from farewatch.cli import main
    monkeypatch.setenv("FAREWATCH_FAKE_TP", "1")
    dbp = tmp_path / "fw.db"
    rc = main(["--config", str(sample_config), "--db", str(dbp),
               "run", "--tier1-only", "--dry-run", "--corridors-only",
               "--data", str(tmp_path / "data.json")])
    assert rc == 0
    conn2 = db.connect(str(dbp))
    sources = {r["source"] for r in
               conn2.execute("SELECT DISTINCT source FROM searches").fetchall()}
    assert "tp:city_directions" not in sources
    assert conn2.execute("SELECT COUNT(*) c FROM fares").fetchone()["c"] > 0


def test_run_swallows_tp_errors_and_counts_them(conn, sample_config, tmp_path):
    # A URLError from the underlying Travelpayouts client (simulating a real
    # HTTPError/timeout) must not abort the run: the loop keeps going, the
    # failure is counted in summary["errors"], and the dashboard is still
    # exported.
    cfg = config.load_config(str(sample_config))
    data = tmp_path / "data.json"
    summary = runner.run(cfg, conn, TODAY, tier1_only=True, dry_run=True,
                         tp_client=_FlakyTP(), export_path=str(data))
    assert summary["errors"] >= 1
    assert data.exists()
    assert json.loads(data.read_text())["base"] == "MEX"


def test_cli_backfill_months_scales_recorded_fares(sample_config, tmp_path, monkeypatch):
    # FixtureTP's month_matrix fixture has 3 rows per call, so N months of
    # backfill should record 3*N fares.
    from farewatch.cli import main
    monkeypatch.setenv("FAREWATCH_FAKE_TP", "1")

    dbp1 = tmp_path / "fw1.db"
    assert main(["--config", str(sample_config), "--db", str(dbp1),
                 "backfill", "--route", "MEX-LHR", "--months", "1"]) == 0
    conn1 = db.connect(str(dbp1))
    n1 = conn1.execute("SELECT COUNT(*) c FROM fares").fetchone()["c"]
    assert n1 == 3

    dbp2 = tmp_path / "fw2.db"
    assert main(["--config", str(sample_config), "--db", str(dbp2),
                 "backfill", "--route", "MEX-LHR", "--months", "2"]) == 0
    conn2 = db.connect(str(dbp2))
    n2 = conn2.execute("SELECT COUNT(*) c FROM fares").fetchone()["c"]
    assert n2 == 6


def test_cli_run_missing_token_fails_fast(monkeypatch):
    # No FAREWATCH_FAKE_TP and no TP_TOKEN -> fail fast before touching the
    # network (or even opening the DB), returning exit code 2.
    from farewatch.cli import main
    from farewatch.providers import http

    def _boom(*a, **kw):
        raise AssertionError("must not touch the network")

    monkeypatch.setattr(http, "get_json", _boom)
    monkeypatch.delenv("FAREWATCH_FAKE_TP", raising=False)
    monkeypatch.delenv("TP_TOKEN", raising=False)
    assert main(["run", "--tier1-only"]) == 2
