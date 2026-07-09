"""Minimal stdlib HTTP JSON helper (no third-party HTTP dependency).

``get_json`` is the seam the whole app mocks in tests — nothing else performs
network I/O, so tests inject a fake ``get_json`` and never hit the wire.
"""
import json
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 20


def get_json(url, params, headers=None, opener=None, timeout=DEFAULT_TIMEOUT):
    """GET ``url?params`` and parse the JSON body into a dict."""
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    full = f"{url}?{query}" if query else url
    req = urllib.request.Request(full, headers=headers or {}, method="GET")
    _open = opener.open if opener is not None else urllib.request.urlopen
    with _open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
