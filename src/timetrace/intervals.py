"""Fetch classified intervals for any time range — the one data path every surface shares."""
import datetime as dt
from datetime import timedelta

from . import aw, classify as C, config

LOCAL = dt.datetime.now().astimezone().tzinfo
SCREENTIME_CLIENT = "aw-import-screentime"


def device_kind(source, name):
    if source == "mac":
        return "Mac"
    return "iPad" if "ipad" in (name or "").lower() else "iPhone"


def device_match(source, name, filt):
    if not filt or filt == "all":
        return True
    f = filt.lower()
    if f.startswith("name:"):  # one specific device, exact name (from the dashboard's device menu)
        return (name or "").lower() == f[5:]
    if f in ("mac", "macbook"):
        return source == "mac"
    if f in ("ios", "mobile"):
        return source == "ios"
    if f in ("iphone", "phone"):
        return source == "ios" and device_kind(source, name) == "iPhone"
    if f == "ipad":
        return source == "ios" and device_kind(source, name) == "iPad"
    return f in (name or "").lower()


def devices():
    """Devices ActivityWatch has data buckets for: [{name, kind, source}], Macs, then iPhones, then iPads.
    Mac names follow fetch_intervals: plain "Mac" unless there is more than one."""
    from . import demo
    if demo.ON:
        return demo.devices()
    buckets = aw.buckets().values()
    hosts = sorted({b.get("hostname") or "Mac" for b in buckets if b.get("type") == "currentwindow"})
    out = [{"name": h if len(hosts) > 1 else "Mac", "kind": "Mac", "source": "mac"} for h in hosts]
    ios = sorted({b.get("hostname") or "iPhone" for b in buckets if b.get("client") == SCREENTIME_CLIENT})
    out += [{"name": n, "kind": device_kind("ios", n), "source": "ios"} for n in ios]
    rank = {"Mac": 0, "iPhone": 1, "iPad": 2}
    return sorted(out, key=lambda d: (rank[d["kind"]], d["name"].lower()))


def _utc(t):
    return t.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_intervals(start, end, device="all", cfg=None):
    cfg = cfg or config.get()
    from . import demo
    if demo.ON:
        return demo.intervals(start, end, device, cfg)
    start_s, end_s = _utc(start), _utc(end)
    buckets = aw.buckets()
    ignore_b, ignore_a = set(cfg["ignore_bundles"]), set(cfg["ignore_apps"])
    out = []

    for b in buckets.values():
        if b.get("client") != SCREENTIME_CLIENT:
            continue
        name = b.get("hostname") or "iPhone"
        if not device_match("ios", name, device):
            continue
        for e in aw.events(b["id"], start_s, end_s):
            d = e.get("data") or {}
            bundle = d.get("app") or "?"
            dur = e.get("duration") or 0
            if bundle in ignore_b or dur <= 0:
                continue
            app = C.ios_name(bundle, d.get("title"), cfg)
            cls = C.classify_ios(bundle, app, cfg)
            ts = C.iso(e["timestamp"])
            out.append({
                "device": name, "kind": device_kind("ios", name), "source": "ios", "app": app, "bundle": bundle,
                "title": d.get("title") or app, "context": app,
                "domain": cls["domain"], "subdomain": cls["subdomain"], "project": cls["project"],
                "evaluation": cls["evaluation"], "rule": cls["rule"],
                "start": ts, "end": ts + timedelta(seconds=dur), "seconds": dur,
            })

    windows = [b for b in buckets.values() if b.get("type") == "currentwindow"]
    afks = [b for b in buckets.values() if b.get("type") == "afkstatus"]
    multi = len({b.get("hostname") for b in windows}) > 1
    for b in windows:
        host = b.get("hostname") or "Mac"
        name = host if multi else "Mac"
        if not device_match("mac", name, device):
            continue
        afk = []
        for a in afks:
            if a.get("hostname") == b.get("hostname"):
                afk = C.afk_intervals(aw.events(a["id"], start_s, end_s))
                break
        for e in aw.events(b["id"], start_s, end_s):
            dur = e.get("duration") or 0
            if dur <= 1:
                continue
            d = e.get("data") or {}
            app = d.get("app") or "?"
            if app in ignore_a:
                continue
            title = d.get("title") or ""
            ts = C.iso(e["timestamp"])
            en = ts + timedelta(seconds=dur)
            if afk:
                dur = C.overlap_seconds(ts, en, afk)
            if dur <= 1:
                continue
            cls = C.classify_mac_at(app, title, ts, en, cfg)
            out.append({
                "device": name, "kind": "Mac", "source": "mac", "app": app, "bundle": "",
                "title": title, "context": C.context_key(app, title),
                "domain": cls["domain"], "subdomain": cls["subdomain"], "project": cls["project"],
                "evaluation": cls["evaluation"], "rule": cls["rule"],
                "start": ts, "end": ts + timedelta(seconds=dur), "seconds": dur,
            })
    C.apply_duration_rules(out, cfg)
    return out


def merge_timeline(intervals, gap):
    intervals = sorted(intervals, key=lambda x: x["start"])
    out = []
    for iv in intervals:
        if out:
            last = out[-1]
            same = all(last[k] == iv[k] for k in ("device", "app", "context", "domain", "subdomain", "project", "evaluation"))
            if same and (iv["start"] - last["end"]).total_seconds() <= gap:
                last["end"] = max(last["end"], iv["end"])
                last["seconds"] += iv["seconds"]
                continue
        out.append(dict(iv))
    for iv in out:
        iv["seconds"] = (iv["end"] - iv["start"]).total_seconds()
    return out
