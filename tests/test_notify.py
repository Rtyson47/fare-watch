from farewatch import notify
from farewatch.notify import smtp_stub, telegram


def test_telegram_posts_with_fake_poster():
    calls = []
    ok = telegram.send("hi", token="T", chat_id="C",
                       poster=lambda url, payload: calls.append((url, payload)))
    assert ok is True
    assert calls[0][0] == "https://api.telegram.org/botT/sendMessage"
    assert calls[0][1]["chat_id"] == "C"
    assert calls[0][1]["text"] == "hi"


def test_telegram_missing_creds_returns_false(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    posted = []
    ok = telegram.send("hi", poster=lambda url, payload: posted.append(1))
    assert ok is False
    assert posted == []


def test_smtp_stub_is_noop_false():
    assert smtp_stub.send("subject", "body") is False


def test_build_notifier_dry_run_never_posts():
    label, send = notify.build_notifier({}, dry_run=True)
    assert label == "dry-run"
    assert send("anything") is True


def test_build_notifier_live_telegram(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "T")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "C")
    calls = []
    cfg = {"alerting": {"telegram": {"enabled": True}, "smtp": {"enabled": False}}}
    label, send = notify.build_notifier(cfg, dry_run=False,
                                        poster=lambda url, payload: calls.append((url, payload)))
    assert label == "telegram"
    assert send("hi") is True
    assert "sendMessage" in calls[0][0]
