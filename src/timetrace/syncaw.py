"""Optional: mirror the domain > subdomain > project tree into ActivityWatch's own categories, so its
timeline and category views use the same names. Evaluations, duration rules and opencode project
recovery cannot be expressed there and stay in timetrace."""
import datetime as dt
import json
import re
from collections import OrderedDict

from . import aw, config, paths

SET_ID = "timetrace"
PALETTE = ["#2563EB", "#7C3AED", "#059669", "#D97706", "#DC2626", "#64748B", "#0891B2", "#9CA3AF"]


def build(cfg=None):
    cfg = cfg or config.get()
    u = cfg["uncategorized"]
    colors = {d: PALETTE[i % len(PALETTE)] for i, d in enumerate(cfg["domains"])}
    colors[u] = "#9CA3AF"
    rules, approx = OrderedDict(), []

    def add(path, regex, keys, prio, ic):
        k = tuple(path)
        if k in rules:
            r = rules[k]
            r["keys"] = sorted(set(r["keys"]) | set(keys))
            r["regex"].append(regex)
            r["ic"] = r["ic"] or ic
        else:
            rules[k] = {"regex": [regex], "keys": list(keys), "prio": prio, "ic": ic}

    def path_of(r):
        return [p for p in (r.get("domain") or u, r.get("subdomain"), r.get("project")) if p]

    ignored = set(cfg["ignore_bundles"])
    for bundle, d in cfg["app_defaults"].items():
        if bundle not in ignored and d.get("domain") != u:
            add(path_of(d), "^" + re.escape(bundle) + "$", ["app"], 20000, False)
    for i, r in enumerate(cfg["mac_rules"]):
        apps, title_re, prio = r.get("apps", []), r.get("title_re", ""), 10000 - 10 * i
        if "*" in apps or not apps:
            add(path_of(r), title_re, ["title"], prio, True)
        elif title_re in ("", ".", ".*"):
            add(path_of(r), "^(" + "|".join(re.escape(a) for a in apps) + ")$", ["app"], prio, False)
        else:  # AW matches one field per rule: keep the title condition only
            approx.append(r["name"])
            add(path_of(r), title_re, ["title"], prio, True)

    cats, seen = [], set()
    for path, r in rules.items():
        for depth in range(1, len(path)):
            f = path[:depth]
            if f not in seen:
                seen.add(f)
                c = {"name": list(f), "rule": {"type": "none"}}
                if depth == 1:
                    c["data"] = {"color": colors.get(f[0], "#9CA3AF")}
                cats.append(c)
        rx = r["regex"][0] if len(r["regex"]) == 1 else "|".join(f"(?:{x})" for x in r["regex"])
        rule = {"type": "regex", "regex": rx, "select_keys": r["keys"], "priority": r["prio"]}
        if r["ic"]:
            rule["ignore_case"] = True
        c = {"name": list(path), "rule": rule}
        if len(path) == 1:
            c["data"] = {"color": colors.get(path[0], "#9CA3AF")}
        cats.append(c)
        seen.add(path)
    cats.append({"name": ["Uncategorized"], "rule": {"type": "none"}, "data": {"color": "#CCCCCC"}})
    return cats, approx


def apply(cats):
    current = aw.get("/settings")
    paths.ensure_dirs()
    backup = paths.BACKUPS / f"aw-settings-{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps(current, ensure_ascii=False, indent=1))
    sets = [s for s in (current.get("category_sets") or []) if s.get("id") != SET_ID]
    sets.insert(0, {"id": SET_ID, "categories": cats})
    aw.request("POST", "/settings/category_sets", sets)
    aw.request("POST", "/settings/active_set_ids", [SET_ID])
    aw.request("POST", "/settings/classes", cats)
    return backup


def restore(backup_file):
    data = json.loads(open(backup_file).read())
    for key in ("category_sets", "active_set_ids", "classes"):
        if key in data:
            aw.request("POST", f"/settings/{key}", data[key])
