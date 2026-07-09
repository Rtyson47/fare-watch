"""Alert delivery channels. Telegram primary; SMTP fallback stub."""
import logging

from . import smtp_stub, telegram

log = logging.getLogger("farewatch.notify")


def build_notifier(cfg, dry_run, poster=None):
    """Return ``(label, send)`` where ``send(text) -> bool``.

    ``--dry-run`` returns a fake logger that never touches the network.
    ``poster`` is injectable so tests exercise the live path offline.
    """
    if dry_run:
        def send(text):
            log.info("[dry-run alert] %s", text)
            return True
        return "dry-run", send

    alerting = cfg.get("alerting", {}) or {}
    tg_on = bool((alerting.get("telegram") or {}).get("enabled"))
    smtp_on = bool((alerting.get("smtp") or {}).get("enabled"))

    def send(text):
        ok = False
        if tg_on:
            ok = telegram.send(text, poster=poster)
        if not ok and smtp_on:
            ok = smtp_stub.send("fare-watch alert", text)
        return ok

    label = "telegram" if tg_on else ("smtp" if smtp_on else "none")
    return label, send
