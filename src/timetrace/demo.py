"""Synthetic data for `TIMETRACE_DEMO=1`: try the dashboard (and take screenshots) without real data.

Raw demo events go through the normal classifier, so the demo shows real rule behaviour.
"""
import datetime as dt
import os
import random
from datetime import timedelta

from . import classify as C

ON = bool(os.environ.get("TIMETRACE_DEMO"))

MAC = [  # (weight, app, title)
    (6, "Code", "pricing.py — shop-backend"), (5, "Ghostty", "shop-backend — npm run dev"),
    (4, "Ghostty", "thesis — latexmk -pvc"), (4, "Texifier", "thesis.tex"), (3, "Zotero", "Library"),
    (3, "Preview", "attention-is-all-you-need.pdf"), (3, "Figma", "Landing page v3"),
    (3, "zoom.us", "Weekly sync"), (2, "Slack", "#product"), (3, "Mail", "Inbox"),
    (4, "Safari", "Docs — React"), (3, "Safari", "Some talk - YouTube"), (2, "Arc", "Reddit - r/programming"),
    (2, "Safari", "Gmail"), (2, "Messages", "Messages"), (1, "Finder", "Downloads"), (1, "System Settings", "Wi-Fi"),
    (1, "Spotify", "Spotify"), (1, "Notion", "Weekly plan"),
]
PHONE = [  # (weight, bundle, title, typical minutes)
    (6, "com.tencent.xin", "WeChat", 3), (5, "com.burbn.instagram", "Instagram", 12), (4, "com.google.ios.youtube", "YouTube", 18),
    (3, "com.xingin.discover", "Xiaohongshu", 15), (2, "com.amazon.Amazon", "Amazon", 8), (2, "com.ubercab.UberEats", "Uber Eats", 5),
    (2, "com.google.Maps", "Google Maps", 4), (2, "com.apple.MobileSMS", "Messages", 2), (2, "com.spotify.client", "Spotify", 4),
    (1, "com.apple.Health", "Health", 3), (1, "com.duolingo.DuolingoMobile", "Duolingo", 10), (1, "com.alipay.iphoneclient", "Alipay", 2),
]
TABLET = [(4, "com.apple.iBooks", "Books", 25), (3, "com.netflix.Netflix", "Netflix", 40), (2, "notion.id", "Notion", 15)]


def _pick(rng, items):
    return rng.choices(items, weights=[x[0] for x in items])[0]


def _day(rng, day, cfg):
    out = []
    local = day
    weekend = local.weekday() >= 5
    # Mac: work blocks
    for (h0, h1) in ([] if weekend and rng.random() < 0.6 else [(9.2, 12.3), (13.6, 18.1)] + ([(20.5, 22.0)] if rng.random() < 0.4 else [])):
        t = local + timedelta(hours=h0 + rng.random() * 0.3)
        stop = local + timedelta(hours=h1)
        while t < stop:
            _, app, title = _pick(rng, MAC)
            mins = max(1.0, rng.expovariate(1 / 9))
            e = min(stop, t + timedelta(minutes=mins))
            cls = C.classify_mac(app, title, cfg)
            out.append(_iv("Mac", "Mac", "mac", app, "", title, C.context_key(app, title), cls, t, e))
            t = e + timedelta(seconds=rng.randint(5, 120))
    # iPhone: short bursts all day, longer in the evening
    for h in [7.6, 8.3, 10.5, 12.4, 13.1, 15.2, 17.0, 18.7, 19.5, 20.6, 21.4, 22.3, 23.1] + ([11, 14, 16] if weekend else []):
        if rng.random() < 0.25:
            continue
        t = local + timedelta(hours=h + rng.random() * 0.4)
        for _ in range(rng.randint(1, 4)):
            _, bundle, name, typical = _pick(rng, PHONE)
            mins = max(0.3, rng.expovariate(1 / (typical * (1.6 if h > 19 else 1))))
            cls = C.classify_ios(bundle, C.ios_name(bundle, name, cfg), cfg)
            out.append(_iv("Demo iPhone", "iPhone", "ios", C.ios_name(bundle, name, cfg), bundle, name, name, cls, t, t + timedelta(minutes=mins)))
            t += timedelta(minutes=mins + rng.random() * 2)
    if rng.random() < 0.5:  # iPad some evenings
        t = local + timedelta(hours=21 + rng.random())
        _, bundle, name, typical = _pick(rng, TABLET)
        cls = C.classify_ios(bundle, C.ios_name(bundle, name, cfg), cfg)
        out.append(_iv("Demo iPad", "iPad", "ios", C.ios_name(bundle, name, cfg), bundle, name, name, cls, t, t + timedelta(minutes=typical * (0.6 + rng.random()))))
    return out


def _iv(device, kind, source, app, bundle, title, context, cls, s, e):
    return {"device": device, "kind": kind, "source": source, "app": app, "bundle": bundle, "title": title, "context": context,
            "domain": cls["domain"], "subdomain": cls["subdomain"], "project": cls["project"] or app,
            "evaluation": cls["evaluation"], "rule": cls["rule"], "start": s, "end": e, "seconds": (e - s).total_seconds()}


def intervals(start, end, device, cfg):
    from .intervals import device_match
    tz = dt.datetime.now().astimezone().tzinfo
    d = start.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    while d < end:
        rng = random.Random(d.date().toordinal())  # same day -> same data
        out += [r for r in _day(rng, d, cfg) if r["end"] > start and r["start"] < end and device_match(r["source"], r["device"], device)]
        d += timedelta(days=1)
    C.apply_duration_rules(out, cfg)
    return out


def devices():
    return [{"name": "Mac", "kind": "Mac", "source": "mac"}, {"name": "Demo iPhone", "kind": "iPhone", "source": "ios"},
            {"name": "Demo iPad", "kind": "iPad", "source": "ios"}]


def status():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    return {"aw": {"ok": True, "url": "demo", "version": "demo"}, "mac": {"ok": True, "last": now, "fresh": True, "title_ratio": 0.97, "afk": True},
            "ios": [{"name": "Demo iPhone", "kind": "iPhone", "last": now, "hours_since": 0.2}, {"name": "Demo iPad", "kind": "iPad", "last": now, "hours_since": 3.0}],
            "importer": {"fda": True, "state": "running", "helper_installed": True}, "services": {"dashboard": True, "importer": True}, "config": True}
