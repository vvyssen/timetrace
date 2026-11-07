"""The user's taxonomy and rules.

config.yaml (in ~/Library/Application Support/timetrace) is the single source of truth. On first
use it is generated from the built-in library in the user's language; after that every tool —
CLI, MCP, dashboard, setup wizard — reads and writes the same file, and edits apply without a restart.
"""
import copy
import os
import re
import shutil
import time

import yaml

from . import paths, settings

ROLES = ["create", "grow", "keep", "leisure"]
KNOWN_ROLES = {
    "创造": "create", "create": "create", "提升": "grow", "grow": "grow",
    "保值": "keep", "维护": "keep", "maintain": "keep", "keep": "keep",
    "消遣": "leisure", "消费": "leisure", "unwind": "leisure", "leisure": "leisure",
}
_cache = {"mtime": None, "cfg": None}


def load_library():
    with open(paths.DATA / "library.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def materialize(lang="zh"):
    """Turn the key-based library into a label-based config in one language."""
    lib = load_library()
    L = lib["labels"]
    d = lambda k: L["domains"][k][lang]
    s = lambda k: L["subdomains"][k][lang] if k else ""
    e = lambda k: L["evaluations"][k][lang][0]
    proj = lambda k: L["projects"].get(k, {}).get(lang, k) if k else None

    cfg = {
        "lang": lang,
        "uncategorized": d("uncategorized"),
        "domains": {d(k): [s(x) for x in subs] for k, subs in lib["taxonomy"].items()},
        "evaluations": {e(k): L["evaluations"][k][lang][1] for k in ROLES},
        "evaluation_roles": {e(k): k for k in ROLES},
        "duration_rules": {
            "session_gap_seconds": lib["duration_rules"]["session_gap_seconds"],
            "rules": [
                {"name": r["name"], "subdomains": [s(x) for x in r["subdomains"]],
                 "over_minutes": r["over_minutes"], "evaluation": e(r["evaluation"])}
                for r in lib["duration_rules"]["rules"]
            ],
        },
        "app_names": {},
        "app_defaults": {},
        "mac_rules": [],
        "ignore_bundles": list(lib["ignore_bundles"]),
        "ignore_apps": list(lib["ignore_apps"]),
    }
    for bundle, (dom, sub, ev, zh, en) in lib["ios_apps"].items():
        name = zh if lang == "zh" else en
        cfg["app_names"][bundle] = name
        cfg["app_defaults"][bundle] = {"domain": d(dom), "subdomain": s(sub), "project": name, "evaluation": e(ev)}
    for r in lib["mac_rules"]:
        rule = {"name": r["name"], "apps": r["apps"], "title_re": r["title_re"],
                "domain": d(r["domain"]), "subdomain": s(r.get("subdomain")), "evaluation": e(r["evaluation"])}
        if r.get("project"):
            rule["project"] = proj(r["project"])
        cfg["mac_rules"].append(rule)
    return cfg


def normalize(cfg):
    """Fill fields that older configs (e.g. a hand-written categories.yaml) may lack."""
    cfg = cfg or {}
    cfg.setdefault("domains", {})
    cfg.setdefault("evaluations", {})
    has_cjk = any(re.search(r"[一-鿿]", k) for k in list(cfg["domains"]) + list(cfg["evaluations"]))
    cfg.setdefault("lang", "zh" if has_cjk else "en")
    cfg.setdefault("uncategorized", "未分类" if cfg["lang"] == "zh" else "Uncategorized")
    if not cfg.get("evaluation_roles"):
        roles, free = {}, [r for r in ROLES]
        for name in cfg["evaluations"]:  # recognise known labels first; order is only a fallback
            role = KNOWN_ROLES.get(name.strip().lower())
            if role in free:
                roles[name] = role
                free.remove(role)
        for name in cfg["evaluations"]:
            if name not in roles and free:
                roles[name] = free.pop(0)
        cfg["evaluation_roles"] = roles
    for key in ("app_names", "app_defaults"):
        cfg[key] = cfg.get(key) or {}
    for key in ("mac_rules", "ignore_bundles", "ignore_apps"):
        cfg[key] = cfg.get(key) or []
    cfg.setdefault("duration_rules", {"session_gap_seconds": 300, "rules": []})
    return cfg


def get():
    """Current config, re-read whenever the file changes on disk."""
    if os.environ.get("TIMETRACE_DEMO"):
        if _cache["cfg"] is None:
            _cache.update(mtime="demo", cfg=normalize(materialize(settings.load()["lang"])))
        return _cache["cfg"]
    try:
        m = os.path.getmtime(paths.CONFIG)
    except FileNotFoundError:
        if _cache["cfg"] is None or _cache["mtime"] is not None:
            _cache.update(mtime=None, cfg=normalize(materialize(settings.load()["lang"])))
        return _cache["cfg"]
    if m != _cache["mtime"]:
        with open(paths.CONFIG, encoding="utf-8") as f:
            _cache.update(mtime=m, cfg=normalize(yaml.safe_load(f)))
    return _cache["cfg"]


def exists():
    return paths.CONFIG.exists()


def backup():
    if paths.CONFIG.exists():
        paths.ensure_dirs()
        dst = paths.BACKUPS / f"config-{time.strftime('%Y%m%d-%H%M%S')}.yaml"
        shutil.copy2(paths.CONFIG, dst)
        return dst
    return None


def save(cfg):
    if os.environ.get("TIMETRACE_DEMO"):
        raise ValueError("demo mode: nothing is saved")
    paths.ensure_dirs()
    backup()
    tmp = paths.CONFIG.with_suffix(".yaml.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# timetrace config — taxonomy and rules. Edited by the setup wizard, `timetrace tag`, or by hand.\n")
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, width=120)
    os.replace(tmp, paths.CONFIG)
    _cache.update(mtime=None, cfg=None)
    return get()


def init(lang=None, force=False):
    """Create config.yaml from the library if it does not exist yet."""
    if exists() and not force:
        return get()
    return save(materialize(lang or settings.load()["lang"]))


def import_file(path):
    """Adopt an existing categories.yaml (same schema) as this user's config."""
    with open(path, encoding="utf-8") as f:
        cfg = normalize(yaml.safe_load(f))
    return save(cfg)


# ---- helpers shared by classification and the UI ------------------------------------------------
def unc(cfg=None):
    return (cfg or get())["uncategorized"]


def eval_order(cfg=None):
    """Evaluation labels in role order, plus the uncategorized label."""
    cfg = cfg or get()
    roles = cfg["evaluation_roles"]
    names = sorted(roles, key=lambda n: ROLES.index(roles[n]) if roles[n] in ROLES else 9)
    return names + [unc(cfg)]


def copy_cfg():
    return copy.deepcopy(get())
