"""Telegram Bot API sender. Token + chat id come from env, never hardcoded."""
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger("farewatch.notify.telegram")


def _default_post(url, payload):
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def send(text, token=None, chat_id=None, poster=None):
    """POST ``text`` to the chat. Returns False (logged) if creds are missing."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.warning("Telegram credentials missing (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID); skipping.")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    post = poster or _default_post
    try:
        post(url, payload)
        return True
    except Exception as exc:  # noqa: BLE001 — network errors shouldn't crash a run
        log.warning("Telegram send failed: %s", exc)
        return False
