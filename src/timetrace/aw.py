"""Minimal ActivityWatch REST client (stdlib only)."""
import json
import urllib.error
import urllib.parse
import urllib.request

from . import settings


class AWUnavailable(RuntimeError):
    pass


def base():
    return settings.load()["aw_url"].rstrip("/") + "/api/0"


def request(method, path, body=None, timeout=60):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(base() + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.URLError as e:
        raise AWUnavailable(f"ActivityWatch is not reachable at {base()} ({e.reason}). Is ActivityWatch running?") from e
    return json.loads(raw) if raw else None


def get(path, **kw):
    return request("GET", path, **kw)


def buckets():
    return get("/buckets/")


def events(bucket_id, start_s, end_s):
    return get(f"/buckets/{urllib.parse.quote(bucket_id)}/events?start={start_s}&end={end_s}&limit=-1")


def info():
    return get("/info", timeout=5)
