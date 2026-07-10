"""Alert rules, dedupe, and dispatch.

Fires when a fare is below the corridor's ``max_price`` OR below
``median_ratio`` (default 0.80) of the trailing-N-day median for the route.
Dedupe: no repeat for the same route + price-band + reason within a window.
"""
import logging
import statistics
from dataclasses import dataclass
from datetime import date, timedelta

from . import db
from .models import route_key

log = logging.getLogger("farewatch.alerts")


@dataclass
class Alert:
    route: str
    price: float
    reason: str
    dedupe_key: str


@dataclass
class AlertContext:
    max_price: float | None = None
    median_ratio: float = 0.80
    lookback_days: int = 30
    min_samples: int = 5
    band_width: float = 20
    today: date | None = None
    route: str | None = None


def dedupe_key(route, reason, price, band_width):
    return f"{route}|{reason}|{int(price // band_width)}"


def _trailing_vals(conn, route, today, lookback_days):
    since = (today - timedelta(days=lookback_days)).isoformat()
    return db.trailing_daily_min(conn, route, since)


def evaluate_fare(conn, fare, ctx):
    """Return an :class:`Alert` for the first satisfied rule, else None."""
    route = ctx.route or route_key(fare.origin, fare.destination)
    if ctx.max_price is not None and fare.price < ctx.max_price:
        return Alert(route, fare.price, "below_max_price",
                     dedupe_key(route, "below_max_price", fare.price, ctx.band_width))
    if ctx.today is not None:
        vals = _trailing_vals(conn, route, ctx.today, ctx.lookback_days)
        if len(vals) >= ctx.min_samples:
            med = statistics.median(vals)
            if fare.price < ctx.median_ratio * med:
                return Alert(route, fare.price, "below_median",
                             dedupe_key(route, "below_median", fare.price, ctx.band_width))
    return None


def should_send(conn, alert, window_hours, now):
    since = (now - timedelta(hours=window_hours)).isoformat()
    return not db.recent_alert_exists(conn, alert.dedupe_key, since)


def format_alert(alert):
    verb = "under max price" if alert.reason == "below_max_price" else "below trailing median"
    return f"✈ {alert.route}: {alert.price:.0f} ({verb})"


def dispatch(conn, alert, send, label, now=None):
    """Send the alert text via ``send``; record it only if delivery succeeded.

    Returns whether the alert was actually delivered. A falsy ``send`` result
    (missing creds, network error, no channel enabled) leaves the alert
    unrecorded so ``should_send`` won't dedupe it away next run.
    """
    delivered = bool(send(format_alert(alert)))
    if delivered:
        db.record_alert(conn, alert.route, alert.price, alert.reason, label,
                        alert.dedupe_key, ts=now.isoformat() if now else None)
    else:
        log.warning("Alert delivery failed for %s (%s); will retry next run",
                    alert.route, alert.reason)
    return delivered


def process_fare(conn, fare, ctx, send, label, window_hours, now, digest=False):
    """Evaluate + (dispatch now | collect for digest). Returns the Alert or None."""
    alert = evaluate_fare(conn, fare, ctx)
    if alert is None or not should_send(conn, alert, window_hours, now):
        return None
    if digest:
        return alert                    # caller collects; send_digest records it later
    return alert if dispatch(conn, alert, send, label, now) else None


def send_digest(conn, collected, send, label, now=None):
    """Send one combined message for all collected alerts; record only on success."""
    if not collected:
        return
    lines = [format_alert(a) for a in collected]
    delivered = bool(send("Daily fare digest\n" + "\n".join(lines)))
    if not delivered:
        log.warning("Digest delivery failed for %d alert(s); will retry next run",
                    len(collected))
        return
    for a in collected:
        db.record_alert(conn, a.route, a.price, a.reason, label, a.dedupe_key,
                        ts=now.isoformat() if now else None)
