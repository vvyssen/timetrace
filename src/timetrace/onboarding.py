"""Setup-wizard logic shared by the dashboard and the CLI (`timetrace suggest` / `timetrace tag`):
environment checks, a first look at the data, what still needs tagging, and writing tags back."""
import collections
import datetime as dt
import json
import os
import re
import subprocess
import time

from . import aw, classify as C, config, intervals as I, paths, settings

# Windows that only matched a broad guess are worth asking about: an app-level fallback for a browser,
# terminal or editor (whatever the rule is called), or an unresolved agent session.
BROWSERS = {"safari", "google chrome", "arc", "firefox", "microsoft edge", "dia", "brave browser", "opera", "vivaldi", "orion", "zen"}
GENERIC_APPS = BROWSERS | C.TERMINALS | C.EDITORS


def _is_broad(rule_name, app, rules_by_name):
    if rule_name in ("shell-idle", C.OPENCODE_GENERIC_RULE):
        return True
    rule = rules_by_name.get(rule_name)
    return bool(rule) and rule.get("title_re", "") in ("", ".", ".*") and (app or "").lower() in GENERIC_APPS


def _launchd_loaded(label):
    try:
        return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def status():
    """Everything the wizard's checklist needs, without side effects."""
    from . import demo
    if demo.ON:
        return demo.status()
    s = settings.load()
    out = {"aw": {"ok": False, "url": s["aw_url"]}, "mac": {}, "ios": [], "importer": {}, "services": {}, "config": config.exists()}
    try:
        info = aw.info()
        out["aw"].update(ok=True, version=info.get("version"), hostname=info.get("hostname"))
        buckets = aw.buckets()
    except aw.AWUnavailable as e:
        out["aw"]["error"] = str(e)
        buckets = {}
    now = dt.datetime.now(dt.timezone.utc)
    win = [b for b in buckets.values() if b.get("type") == "currentwindow"]
    if win:
        b = max(win, key=lambda x: x.get("last_updated") or "")
        last = b.get("last_updated")
        recent = aw.events(b["id"], I._utc(now - dt.timedelta(hours=24)), I._utc(now))
        titled = sum(1 for e in recent if (e.get("data") or {}).get("title"))
        out["mac"] = {"ok": True, "bucket": b["id"], "last": last,
                      "fresh": bool(last) and (now - C.iso(last)).total_seconds() < 900,
                      "title_ratio": round(titled / len(recent), 2) if recent else None,
                      "afk": any(x.get("type") == "afkstatus" for x in buckets.values())}
    else:
        out["mac"] = {"ok": False}
    for b in buckets.values():
        if b.get("client") == I.SCREENTIME_CLIENT:
            last = b.get("last_updated")
            out["ios"].append({"name": b.get("hostname"), "kind": I.device_kind("ios", b.get("hostname")), "bucket": b["id"], "last": last,
                               "hours_since": round((now - C.iso(last)).total_seconds() / 3600, 1) if last else None})
    try:
        out["importer"] = json.loads(paths.IMPORTER_STATUS.read_text())
        out["importer"]["age_s"] = round(time.time() - out["importer"].get("updated", 0))
    except (FileNotFoundError, json.JSONDecodeError):
        out["importer"] = {"state": "not-started"}
    from . import services
    out["importer"]["helper_installed"] = services.HELPER_APP.exists()
    for name, label in services.labels().items():
        out["services"][name] = _launchd_loaded(label)
    return out


def first_look(days=14):
    cfg = config.get()
    u = cfg["uncategorized"]
    now = dt.datetime.now(I.LOCAL)
    ivs = I.fetch_intervals(now - dt.timedelta(days=days), now, "all", cfg)
    dev = collections.defaultdict(lambda: {"seconds": 0.0, "categorized": 0.0, "apps": collections.Counter(), "first": None})
    for r in ivs:
        d = dev[(r["kind"], r["device"])]
        d["seconds"] += r["seconds"]
        if r["domain"] != u:
            d["categorized"] += r["seconds"]
        d["apps"][r["app"]] += r["seconds"]
        d["first"] = min(d["first"] or r["start"], r["start"])
    devices = []
    for (kind, name), d in sorted(dev.items(), key=lambda kv: -kv[1]["seconds"]):
        span_days = max(1, min(days, (now - d["first"]).days + 1)) if d["first"] else days
        devices.append({"kind": kind, "name": name, "seconds": d["seconds"], "per_day": d["seconds"] / span_days,
                        "coverage": d["categorized"] / d["seconds"] if d["seconds"] else 0,
                        "top_apps": d["apps"].most_common(6), "days": span_days})
    total = sum(x["seconds"] for x in devices)
    covered = sum(x["seconds"] * x["coverage"] for x in devices)
    return {"days": days, "devices": devices, "total": total, "coverage": covered / total if total else 0}


def site_of(title):
    """Trailing site name of a browser tab title ('… - YouTube' -> 'YouTube'), if it looks like one."""
    t = C.clean_title(title)
    parts = re.split(r"\s+[-–—|·/]\s+|_", t)
    if len(parts) >= 2:
        last = parts[-1].strip()
        truncated = last.endswith(("…", "...")) or t.endswith(("…", "..."))
        if 1 < len(last) <= 30 and not truncated and not re.fullmatch(r"[\d\W]+", last):
            return last
    return None


def candidates(days=14, limit=20, review=8):
    """Items worth tagging: uncategorized apps, and windows that only matched a broad guess."""
    cfg = config.get()
    u = cfg["uncategorized"]
    now = dt.datetime.now(I.LOCAL)
    ivs = I.fetch_intervals(now - dt.timedelta(days=days), now, "all", cfg)
    groups = {}

    def bump(key, base, r):
        g = groups.setdefault(key, {**base, "seconds": 0.0, "devices": set(), "samples": collections.Counter(), "current": None})
        g["seconds"] += r["seconds"]
        g["devices"].add(r["kind"])
        if r["source"] == "mac" and r["title"]:
            g["samples"][r["title"][:90]] += r["seconds"]
        g["current"] = g["current"] or {k: r[k] for k in ("domain", "subdomain", "project", "evaluation", "rule")}

    agent_placeholder = {r.get("project") for r in cfg["mac_rules"] if r.get("name") == C.OPENCODE_GENERIC_RULE}
    rules_by_name = {r.get("name"): r for r in cfg["mac_rules"]}
    for r in ivs:
        rule = r.get("rule")
        if rule and ">" in rule:  # e.g. an "OpenCode" terminal already resolved to a project: not a guess
            rule = "resolved"
        if rule == C.OPENCODE_GENERIC_RULE:  # unresolved agent session: ask about its folder, not "OpenCode"
            if r["project"] in agent_placeholder:
                continue
            r = {**r, "context": r["project"]}
        if r["source"] == "ios":
            bump(("ios_app", r["bundle"]), {"kind": "ios_app", "bundle": r["bundle"], "app": r["app"], "label": r["app"],
                                            "needs_tag": r["domain"] == u}, r)
        elif r["domain"] == u:
            bump(("mac_app", r["app"]), {"kind": "mac_app", "app": r["app"], "label": r["app"], "needs_tag": True}, r)
        elif _is_broad(rule, r["app"], rules_by_name):
            if r["app"].lower() in BROWSERS:
                site = site_of(r["title"])
                if not site:
                    continue
                key, label = site, f"{r['app']} · {site}"
            else:
                key = r["context"]
                if r["app"].lower() in C.EDITORS and " / " in key:  # "file / project": ask about the project
                    key = key.split(" / ")[-1]
                if not key or key in ("(untitled)", "~"):
                    continue
                label = f"{r['app']} · {key}"
            bump(("mac_context", key), {"kind": "mac_context", "app": r["app"], "keyword": key, "label": label, "needs_tag": True}, r)
        else:
            bump(("mac_app", r["app"]), {"kind": "mac_app", "app": r["app"], "label": r["app"], "needs_tag": False}, r)

    rows = []
    for g in groups.values():
        g["devices"] = sorted(g["devices"])
        g["samples"] = [t for t, _ in g["samples"].most_common(3)]
        g["id"] = f"{g['kind']}:{g.get('bundle') or g.get('keyword') or g['app']}"
        rows.append(g)
    need = sorted((g for g in rows if g["needs_tag"] and g["seconds"] >= 120), key=lambda g: -g["seconds"])[:limit]
    ok = sorted((g for g in rows if not g["needs_tag"]), key=lambda g: -g["seconds"])[:review]
    return {"days": days, "needs_tag": need, "review": ok,
            "domains": cfg["domains"], "evaluations": config.eval_order(cfg)[:-1],
            "evaluation_roles": cfg["evaluation_roles"], "uncategorized": u}


def _slug(s):
    return re.sub(r"[^\w一-鿿]+", "-", s or "").strip("-")[:40] or "item"


def _is_app_level(rule):
    return rule.get("title_re", "") in ("", ".", ".*") and "*" not in rule.get("apps", [])


def apply_tags(tags):
    """Write user tags into config.yaml. Each tag: kind (ios_app | mac_app | mac_context), the item key
    (bundle | app | keyword), domain, subdomain, evaluation, optional project, optional ignore."""
    cfg = config.copy_cfg()
    evals = set(cfg["evaluations"])
    applied = []
    for t in tags:
        kind = t.get("kind")
        if t.get("ignore"):
            if kind == "ios_app" and t.get("bundle") and t["bundle"] not in cfg["ignore_bundles"]:
                cfg["ignore_bundles"].append(t["bundle"])
            elif kind == "mac_app" and t.get("app") and t["app"] not in cfg["ignore_apps"]:
                cfg["ignore_apps"].append(t["app"])
            applied.append({**t, "result": "ignored"})
            continue
        dom, sub, ev = t.get("domain"), (t.get("subdomain") or "").strip(), t.get("evaluation")
        if dom not in cfg["domains"]:
            raise ValueError(f"unknown domain {dom!r}; choose one of {list(cfg['domains'])}")
        if ev not in evals:
            raise ValueError(f"unknown evaluation {ev!r}; choose one of {sorted(evals)}")
        if sub and sub not in cfg["domains"][dom]:
            cfg["domains"][dom].append(sub)  # new subdomains are allowed; they join the taxonomy
        project = (t.get("project") or "").strip() or None
        if kind == "ios_app":
            b = t["bundle"]
            cfg["app_defaults"][b] = {"domain": dom, "subdomain": sub, "project": project or t.get("app") or cfg["app_names"].get(b, b), "evaluation": ev}
            if t.get("app") and b not in cfg["app_names"]:
                cfg["app_names"][b] = t["app"]
        elif kind == "mac_app":
            name = f"user-app-{_slug(t['app'])}"
            rule = {"name": name, "apps": [t["app"]], "title_re": ".", "domain": dom, "subdomain": sub, "evaluation": ev}
            if project:
                rule["project"] = project
            rules = [r for r in cfg["mac_rules"] if r.get("name") != name]
            at = next((i for i, r in enumerate(rules) if _is_app_level(r)), len(rules))
            rules.insert(at, rule)
            cfg["mac_rules"] = rules
        elif kind == "mac_context":
            kw = (t.get("keyword") or "").strip()
            if len(kw) < 2:
                raise ValueError("keyword must be at least 2 characters")
            pattern = t.get("title_re") or re.escape(kw)
            re.compile(pattern)
            name = f"user-title-{_slug(kw)}"
            rule = {"name": name, "apps": t.get("apps") or ["*"], "title_re": pattern, "domain": dom, "subdomain": sub,
                    "project": project or kw, "evaluation": ev}
            cfg["mac_rules"] = [rule] + [r for r in cfg["mac_rules"] if r.get("name") != name]
        else:
            raise ValueError(f"unknown kind {kind!r}")
        applied.append({**t, "result": "saved"})
    config.save(cfg)
    return applied


def set_duration_rules(gap_minutes=None, thresholds=None):
    cfg = config.copy_cfg()
    d = cfg.setdefault("duration_rules", {"session_gap_seconds": 300, "rules": []})
    if gap_minutes is not None:
        d["session_gap_seconds"] = int(float(gap_minutes) * 60)
    for name, minutes in (thresholds or {}).items():
        for r in d["rules"]:
            if r.get("name") == name:
                r["over_minutes"] = float(minutes)
    config.save(cfg)
    return d
