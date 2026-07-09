"""CLI entrypoint. Subcommands: run / set-base / report / backfill."""
import argparse
import logging
import os
from datetime import datetime, timezone

from . import config, db, runner
from .report import build_report

log = logging.getLogger("farewatch.cli")


def _build_tp(cfg):
    defaults = cfg.get("defaults", {}) or {}
    market = defaults.get("market", "us")
    currency = defaults.get("currency", "usd")
    if os.environ.get("FAREWATCH_FAKE_TP") == "1":
        from .testing import FixtureTP
        return FixtureTP(currency=currency, market=market)
    from .providers.travelpayouts import TravelpayoutsClient
    return TravelpayoutsClient(os.environ.get("TP_TOKEN"), market=market, currency=currency)


def _parser():
    p = argparse.ArgumentParser(prog="monitor.py",
                                description="Personal two-tier flight-fare monitor.")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--db", default="fare_watch.db")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="scan + alert + export dashboard")
    r.add_argument("--tier1-only", action="store_true",
                   help="discovery + corridor pricing via Travelpayouts only (no Duffel)")
    r.add_argument("--dry-run", action="store_true",
                   help="Duffel test mode; fake-log alerts (never posts)")
    r.add_argument("--corridors-only", action="store_true",
                   help="skip inspiration discovery; corridor + deadline-watch pricing only")
    r.add_argument("--data", default="docs/data.json", help="dashboard export path")

    s = sub.add_parser("set-base", help="update current_base IATA in config")
    s.add_argument("iata")

    sub.add_parser("report", help="print terminal summary")

    b = sub.add_parser("backfill", help="Tier 1 seed for a single route")
    b.add_argument("--route", required=True, help="e.g. MEX-LHR")
    b.add_argument("--months", type=int, default=3)
    return p


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parser().parse_args(argv)

    if args.cmd == "set-base":
        try:
            config.set_base(args.iata, args.config)
        except ValueError as exc:
            log.error("%s", exc)
            return 2
        print(f"current_base set to {args.iata.strip().upper()}")
        return 0

    cfg = config.load_config(args.config)
    problems = config.validate_config(cfg)
    if problems:
        for pb in problems:
            log.error("config: %s", pb)
        return 2

    if args.cmd in ("run", "backfill") and os.environ.get("FAREWATCH_FAKE_TP") != "1" \
            and not os.environ.get("TP_TOKEN"):
        log.error("TP_TOKEN is not set. Set TP_TOKEN in the environment, or use "
                  "FAREWATCH_FAKE_TP=1 for offline/fixture mode.")
        return 2

    conn = db.connect(args.db)
    today = datetime.now(timezone.utc).date()

    if args.cmd == "run":
        summary = runner.run(cfg, conn, today, tier1_only=args.tier1_only,
                             dry_run=args.dry_run, tp_client=_build_tp(cfg),
                             export_path=args.data,
                             include_inspiration=not args.corridors_only)
        print(build_report(conn, cfg, today))
        log.info("run summary: %s", summary)
        return 0

    if args.cmd == "report":
        print(build_report(conn, cfg, today))
        return 0

    if args.cmd == "backfill":
        n = runner.backfill(cfg, conn, today, args.route, _build_tp(cfg), months=args.months)
        print(f"backfill {args.route}: recorded {n} fares")
        return 0

    return 1
