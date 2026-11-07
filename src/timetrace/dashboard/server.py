"""timetrace dashboard — local web app on 127.0.0.1 (overview, calendar, setup wizard).

All numbers come from timetrace.intervals, so duration rules, opencode recovery and edits to
config.yaml apply as-is. Writes need a per-start token, a loopback client and a local Host header
(no CSRF, no DNS rebinding). With phone access on (see lan.py) it also listens on the local
network, where only read routes are served and only with the read-only token.
"""
import collections
import ipaddress
import json
import os
import secrets
import subprocess
import threading
import time
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import __version__, config, intervals as I, lan, onboarding, paths, services, settings

TOKEN = secrets.token_urlsafe(24)
STATIC = {"/favicon.png", "/apple-touch-icon.png", "/icon-512.png", "/manifest.webmanifest", "/i18n.js", "/app.js"}
READ_ONLY_ROUTES = {"/api/data", "/api/calendar", "/api/meta"}  # what a phone with the read-only link may fetch
COOKIE = "tt_ro"
WEEKDAYS = {"zh": "一二三四五六日", "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}
_lock = threading.Lock()
_cache = {}


def evals_dict(order):
    return {e: 0.0 for e in order}


def known_devices():
    try:
        return I.devices()
    except Exception:  # ActivityWatch down: the data routes will say so
        return []


def meta():
    cfg = config.get()
    s = settings.load()
    order = config.eval_order(cfg)
    return {
        "lang": s["lang"], "version": __version__, "setup_done": s.get("setup_done", False),
        "evaluations": [{"name": e, "role": cfg["evaluation_roles"].get(e, "none"), "desc": cfg["evaluations"].get(e, "")} for e in order],
        "uncategorized": cfg["uncategorized"], "domains": cfg["domains"],
        "duration_rules": cfg.get("duration_rules") or {},
        "devices": known_devices(),
    }


def resolve(params):
    now = datetime.now(I.LOCAL)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rng = params.get("range", "today")
    if rng == "day" and params.get("date"):
        d = datetime.strptime(params["date"], "%Y-%m-%d").replace(tzinfo=I.LOCAL)
        return rng, d, min(d + timedelta(days=1), now)
    if rng == "yesterday":
        return rng, today - timedelta(days=1), today
    if rng in ("7d", "30d", "90d"):
        return rng, today - timedelta(days=int(rng[:-1]) - 1), now
    return "today", today, now


def pieces(r, start, end, unit):
    """Split an interval's active seconds across local hours or days, clipped to [start, end]."""
    s, e = max(r["start"], start), min(r["end"], end)
    span = (r["end"] - r["start"]).total_seconds()
    if e <= s or span <= 0:
        return
    ratio = min(1.0, r["seconds"] / span)
    cur, e = s.astimezone(I.LOCAL), e.astimezone(I.LOCAL)
    while cur < e:
        if unit in ("hour", "dayhour"):
            nxt = cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            key = cur.hour if unit == "hour" else (cur.date().isoformat(), cur.hour)
        else:
            nxt, key = cur.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1), cur.date().isoformat()
        stop = min(nxt, e)
        yield key, (stop - cur).total_seconds() * ratio
        cur = stop


def build(params):
    cfg = config.get()
    order = config.eval_order(cfg)
    u = cfg["uncategorized"]
    rng, start, end = resolve(params)
    rows = I.fetch_intervals(start, end, params.get("device", "all"), cfg)
    total, by_eval = 0.0, evals_dict(order)
    by_dev = collections.defaultdict(lambda: evals_dict(order))
    days = collections.OrderedDict()
    d = start
    while d < end:
        days[d.date().isoformat()] = evals_dict(order)
        d += timedelta(days=1)
    hours = [evals_dict(order) for _ in range(24)]
    ev_idx = {e: i for i, e in enumerate(order)}
    heat = {k: [[0.0] * len(order) for _ in range(24)] for k in days} if len(days) > 1 else None  # day x hour x evaluation
    dom = collections.defaultdict(lambda: {"evals": evals_dict(order), "subs": collections.defaultdict(lambda: evals_dict(order))})
    proj = collections.defaultdict(lambda: {"evals": evals_dict(order), "devices": set()})
    apps = collections.defaultdict(lambda: {"evals": evals_dict(order), "domain": "", "project": ""})
    for r in rows:
        ev = r["evaluation"] if r["evaluation"] in by_eval else u
        clipped = 0.0
        for k, sec in pieces(r, start, end, "day"):
            if k in days:
                days[k][ev] += sec
                clipped += sec
        for k, sec in pieces(r, start, end, "hour"):
            hours[k][ev] += sec
        if heat is not None:
            for (dk, h), sec in pieces(r, start, end, "dayhour"):
                if dk in heat:
                    heat[dk][h][ev_idx[ev]] += sec
        if clipped <= 0:
            continue
        total += clipped
        by_eval[ev] += clipped
        by_dev[r["kind"]][ev] += clipped
        dm = dom[r["domain"]]
        dm["evals"][ev] += clipped
        dm["subs"][r["subdomain"] or "—"][ev] += clipped
        pk = (r["domain"], r["subdomain"] or "", r["project"] or r["app"])
        proj[pk]["evals"][ev] += clipped
        proj[pk]["devices"].add(r["kind"])
        ak = (r["kind"], r["app"])
        apps[ak]["evals"][ev] += clipped
        apps[ak]["domain"] = "/".join(x for x in (r["domain"], r["subdomain"]) if x)
        apps[ak]["project"] = r["project"]
    tot = lambda e: sum(e.values())
    domains = [{"name": n, "evals": v["evals"], "subs": [{"name": s, "evals": e} for s, e in sorted(v["subs"].items(), key=lambda kv: -tot(kv[1]))]}
               for n, v in sorted(dom.items(), key=lambda kv: -tot(kv[1]["evals"]))]
    projects = [{"project": k[2], "domain": k[0], "subdomain": k[1], "devices": sorted(v["devices"]), "evals": v["evals"]}
                for k, v in sorted(proj.items(), key=lambda kv: -tot(kv[1]["evals"]))[:15]]
    app_rows = [{"device": k[0], "app": k[1], "domain": v["domain"], "project": v["project"], "evals": v["evals"]}
                for k, v in sorted(apps.items(), key=lambda kv: -tot(kv[1]["evals"]))[:40]]
    timeline = []
    if end - start <= timedelta(days=1, hours=1):
        for r in I.merge_timeline([r for r in rows if r["seconds"] >= 5], 60):
            s, e = max(r["start"], start), min(r["end"], end)
            if (e - s).total_seconds() >= 20:
                timeline.append({"device": r["kind"], "start": s.astimezone(I.LOCAL).isoformat(), "end": e.astimezone(I.LOCAL).isoformat(),
                                 "app": r["app"], "project": r["project"], "domain": r["domain"], "subdomain": r["subdomain"],
                                 "evaluation": r["evaluation"], "rule": r.get("duration_rule") or ""})
    return {"meta": meta(), "range": {"key": rng, "start": start.isoformat(), "end": end.isoformat(), "days": len(days)},
            "device": params.get("device", "all"), "generated_at": datetime.now(I.LOCAL).isoformat(),
            "total": total, "by_eval": by_eval, "by_device": by_dev,
            "daily": [{"date": k, "evals": v} for k, v in days.items()],
            "hourly": [{"hour": h, "evals": v} for h, v in enumerate(hours)],
            "heat": {"evals": order, "days": [{"date": k, "h": [[round(x) for x in hr] for hr in v]} for k, v in heat.items()]} if heat else None,
            "domains": domains, "projects": projects, "apps": app_rows, "timeline": timeline}


def slot_pieces(r, start, end, slot_sec):
    s, e = max(r["start"], start), min(r["end"], end)
    span = (r["end"] - r["start"]).total_seconds()
    if e <= s or span <= 0:
        return
    ratio = min(1.0, r["seconds"] / span)
    t = s
    while t < e:
        idx = int((t - start).total_seconds() // slot_sec)
        stop = min(start + timedelta(seconds=(idx + 1) * slot_sec), e)
        yield idx, (stop - t).total_seconds() * ratio
        t = stop


def build_calendar(params):
    """Week grid: per device lane, fixed slots -> dominant project; adjacent slots with the same
    project and the same evaluation merge into one block."""
    cfg = config.get()
    order = config.eval_order(cfg)
    lang = settings.load()["lang"]
    now = datetime.now(I.LOCAL)
    day = datetime.strptime(params["date"], "%Y-%m-%d").replace(tzinfo=I.LOCAL) if params.get("date") else now
    week0 = day.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=day.weekday())
    week1 = week0 + timedelta(days=7)
    end = min(week1, now)
    slot_min = int(params.get("slot", 15)) if str(params.get("slot", 15)) in ("5", "10", "15", "30", "60") else 15
    slot_sec = slot_min * 60
    min_active = max(60, slot_sec * 0.1)
    rows = I.fetch_intervals(week0, end, params.get("device", "all"), cfg) if end > week0 else []
    wd = WEEKDAYS.get(lang, WEEKDAYS["en"])
    days = [{"date": (week0 + timedelta(days=i)).date().isoformat(), "weekday": ("周" + wd[i]) if lang == "zh" else wd[i], "evals": evals_dict(order)} for i in range(7)]
    slots = collections.defaultdict(lambda: {"evals": evals_dict(order), "proj": collections.Counter(), "apps": collections.Counter(), "meta": {}})
    lanes = []
    for r in rows:
        ev = r["evaluation"] if r["evaluation"] in order else cfg["uncategorized"]
        lane = r["kind"]
        if lane not in lanes:
            lanes.append(lane)
        pk = r["project"] or r["app"]
        for idx, sec in slot_pieces(r, week0, end, slot_sec):
            s = slots[(lane, idx)]
            s["evals"][ev] += sec
            s["proj"][pk] += sec
            s["apps"][r["app"]] += sec
            s["meta"].setdefault(pk, (r["domain"], r["subdomain"]))
        for k, sec in pieces(r, week0, end, "day"):
            i = (datetime.fromisoformat(k).date() - week0.date()).days
            if 0 <= i < 7:
                days[i]["evals"][ev] += sec
    lanes.sort(key=lambda x: ["Mac", "iPhone", "iPad"].index(x) if x in ("Mac", "iPhone", "iPad") else 9)
    per_day = 24 * 60 // slot_min
    blocks = []
    for lane in lanes:
        cur = None
        for idx in range(7 * per_day):
            s = slots.get((lane, idx))
            active = s is not None and sum(s["evals"].values()) >= min_active
            top = s["proj"].most_common(1)[0][0] if active else None
            top_ev = max(s["evals"], key=s["evals"].get) if active else None
            if active and cur and cur["last"] == idx - 1 and cur["project"] == top and cur["ev"] == top_ev and idx // per_day == cur["last"] // per_day:
                cur["last"] = idx
                for e, v in s["evals"].items():
                    cur["evals"][e] += v
                cur["proj"].update(s["proj"])
                cur["apps"].update(s["apps"])
                continue
            if cur:
                blocks.append(cur)
                cur = None
            if active:
                cur = {"device": lane, "first": idx, "last": idx, "project": top, "ev": top_ev, "meta": s["meta"],
                       "evals": dict(s["evals"]), "proj": collections.Counter(s["proj"]), "apps": collections.Counter(s["apps"])}
        if cur:
            blocks.append(cur)
    out = []
    for b in blocks:
        dm, sub = b["meta"].get(b["project"], ("", ""))
        out.append({"device": b["device"], "start": (week0 + timedelta(seconds=b["first"] * slot_sec)).isoformat(),
                    "end": (week0 + timedelta(seconds=(b["last"] + 1) * slot_sec)).isoformat(),
                    "project": b["project"], "domain": dm, "subdomain": sub, "evaluation": b["ev"],
                    "seconds": sum(b["evals"].values()), "evals": b["evals"],
                    "top_projects": b["proj"].most_common(4), "top_apps": b["apps"].most_common(4)})
    return {"meta": meta(), "week": {"start": week0.isoformat(), "end": week1.isoformat()}, "lanes": lanes or ["Mac"],
            "days": [{**d, "total": sum(d["evals"].values())} for d in days], "slot_minutes": slot_min,
            "device": params.get("device", "all"), "now": now.isoformat(), "generated_at": now.isoformat(), "blocks": out}


def cached(kind, params, fn):
    key = (kind, tuple(sorted(params.items())), config._cache.get("mtime"), int(time.time() // 60))
    with _lock:
        if key in _cache:
            return _cache[key]
    data = fn(params)
    with _lock:
        if len(_cache) > 48:
            _cache.clear()
        _cache[key] = data
    return data


def agent_info():
    from .. import agents
    lang = settings.load()["lang"]
    return {"agents": {k: {"found": v.get("found", False), "mcp": v.get("mcp", False)} for k, v in agents.status().items()},
            "prompt": agents.prompt(lang)}


SETTINGS_PANES = {
    "fda": "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
}


def action(name, body):
    if name == "open-aw":
        subprocess.run(["open", "-a", "ActivityWatch"])
    elif name in ("open-fda", "open-accessibility"):
        subprocess.run(["open", SETTINGS_PANES[name.split("-", 1)[1]]])
    elif name == "reveal-helper":
        subprocess.run(["open", "-R", str(services.HELPER_APP)])
    elif name == "restart-importer":
        services.restart("importer")
    elif name == "tags":
        return {"applied": onboarding.apply_tags(body.get("tags") or [])}
    elif name == "duration":
        return {"duration_rules": onboarding.set_duration_rules(body.get("gap_minutes"), body.get("thresholds"))}
    elif name == "settings":
        allowed = {k: body[k] for k in ("lang", "setup_done") if k in body}
        if allowed.get("lang") not in (None, "zh", "en"):
            raise ValueError("lang must be zh or en")
        return settings.save(**allowed)
    elif name == "lan":  # phone access: {"enabled": bool} and/or {"rotate": true}
        if "enabled" in body:
            lan.enable() if body["enabled"] else lan.disable()
        if body.get("rotate"):
            lan.rotate()
        rebind()
        return lan.status()
    elif name == "reset-labels":  # regenerate rule labels in the chosen language (only offered before any tagging)
        config.init(lang=body.get("lang") or settings.load()["lang"], force=True)
    else:
        raise ValueError(f"unknown action {name}")
    return {"ok": True}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(paths.STATIC), **kw)

    def _host_ok(self):
        h = self.headers.get("Host") or ""
        host = h[: h.rfind(":")] if h.rfind(":") > h.rfind("]") else h  # strip :port, keep [::1]
        return host in ("127.0.0.1", "localhost", "[::1]")

    def _loopback(self):
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _ro_token(self, params):
        if params.get("t"):
            return params["t"]
        c = SimpleCookie(self.headers.get("Cookie") or "")
        return c[COOKIE].value if COOKIE in c else None

    def access(self, params):
        """"rw" for this Mac at localhost, "ro" for anyone holding the read-only link (a phone, or this Mac
        opening the link: macOS resolves its own .local name to 127.0.0.1), None otherwise. A DNS-rebinding
        page reaches us as loopback with a foreign Host and no token, so it gets None."""
        if self._loopback() and self._host_ok():
            return "rw"
        return "ro" if lan.check(self._ro_token(params)) else None

    def end_headers(self):
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def _denied(self):
        msg = ("这个链接已失效，或者这台 Mac 关闭了手机访问。请在 Mac 上的看板里打开「手机查看」获取新链接。\n"
               "This link has expired, or phone access is off on the Mac. Open “Phone” in the dashboard on the Mac for a new link.")
        body = (f'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<title>Timetrace</title><body style="font:16px/1.6 system-ui;padding:24px;white-space:pre-line">{msg}</body>').encode()
        self.send_response(403)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(u.query).items()}
        mode = self.access(params)
        if u.path in STATIC and (mode or lan.enabled()):  # icons and scripts are public assets
            self.path = u.path
            return super().do_GET()
        if mode is None:
            return self._denied() if u.path in ("/", "/index.html") else self.send_error(403)
        if mode == "ro" and u.path not in READ_ONLY_ROUTES | {"/", "/index.html"}:
            return self.send_error(403)
        ro_token = self._ro_token(params) if mode == "ro" else None
        params.pop("t", None)
        routes = {"/api/data": lambda: cached("data", params, build), "/api/calendar": lambda: cached("cal", params, build_calendar),
                  "/api/meta": meta, "/api/setup/status": onboarding.status,
                  "/api/setup/first-look": lambda: onboarding.first_look(int(params.get("days", 14))),
                  "/api/setup/candidates": lambda: onboarding.candidates(int(params.get("days", 14))),
                  "/api/setup/pending": lambda: cached("pending", {}, lambda p: onboarding.pending()),
                  "/api/setup/agent": agent_info, "/api/lan": lambda: {**lan.status(), "listening": bool(_server["httpd"]) and _server["httpd"].server_address[0] != "127.0.0.1"}}
        if u.path in routes:
            try:
                return self._json(routes[u.path]())
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
        if u.path not in ("/", "/index.html"):
            return self.send_error(404)
        html = (paths.STATIC / "index.html").read_text(encoding="utf-8")
        html = html.replace("__TIMETRACE_TOKEN__", TOKEN if mode == "rw" else "").replace("__TIMETRACE_RO__", "true" if mode == "ro" else "false")
        body = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if mode == "ro":  # keep the phone signed in after the first visit, even from a bookmark without ?t=
            self.send_header("Set-Cookie", f"{COOKIE}={ro_token}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):  # the stdlib would answer HEAD for any file in the static dir, bypassing access()
        u = urlparse(self.path)
        if u.path in STATIC and (self.access({}) or lan.enabled()):
            self.path = u.path
            return super().do_HEAD()
        return self.send_error(405 if self.access({}) else 403)

    def do_POST(self):
        if not (self._loopback() and self._host_ok()) or self.headers.get("X-Timetrace-Token") != TOKEN:
            return self.send_error(403)
        u = urlparse(self.path)
        if not u.path.startswith("/api/action/"):
            return self.send_error(404)
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            res = action(u.path.rsplit("/", 1)[1], body)
            with _lock:
                _cache.clear()
            return self._json(res)
        except Exception as e:
            return self._json({"error": f"{type(e).__name__}: {e}"}, 400)

    def guess_type(self, path):
        return "application/manifest+json" if str(path).endswith(".webmanifest") else super().guess_type(path)

    def log_message(self, fmt, *args):
        pass


_server = {"httpd": None, "rebind": False}


def bind_host():
    return "0.0.0.0" if lan.enabled() else "127.0.0.1"


def rebind():
    """Listen again on the address the settings ask for, after phone access was switched on or off."""
    httpd = _server["httpd"]
    if httpd is None or httpd.server_address[0] == bind_host():
        return False
    _server["rebind"] = True
    threading.Timer(0.3, httpd.shutdown).start()  # let the current response go out first
    return True


def main():
    port = int(os.environ.get("TIMETRACE_PORT") or settings.load()["port"])
    ThreadingHTTPServer.allow_reuse_address = True
    while True:
        host = bind_host()
        with ThreadingHTTPServer((host, port), Handler) as httpd:
            _server.update(httpd=httpd, rebind=False)
            print(f"timetrace dashboard on http://127.0.0.1:{port}" + (" (+ read-only on the local network)" if host != "127.0.0.1" else ""), flush=True)
            httpd.serve_forever()
        if not _server["rebind"]:
            break


if __name__ == "__main__":
    main()
