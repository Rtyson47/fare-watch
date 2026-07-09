"""SMTP fallback — stub only.

TODO: implement with ``smtplib`` using SMTP_HOST / SMTP_PORT / SMTP_USER /
SMTP_PASSWORD / SMTP_FROM / SMTP_TO env vars. Kept a no-op so the fallback
path is wired but never silently "succeeds" until real SMTP is configured.
"""
import logging

log = logging.getLogger("farewatch.notify.smtp")


def send(subject, body):
    log.info("[smtp-stub] would send %r: %s", subject, body)
    return False
