"""Tiny JSON-over-HTTP helper. stdlib only."""
import json
import urllib.error
import urllib.parse
import urllib.request


class HttpError(Exception):
    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def request(url, method="GET", body=None, headers=None, timeout=30, raw=False):
    data = None
    hdrs = {"User-Agent": "channeliq/0.1"}
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode("utf-8", "replace")) from None
    if raw:
        return payload
    if not payload:
        return None
    try:
        return json.loads(payload)
    except ValueError:
        return payload.decode("utf-8", "replace")
