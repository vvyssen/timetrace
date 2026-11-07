"""Turn raw ActivityWatch events into 领域 / 子领域 / 项目 / 评价 (domain / subdomain / project / evaluation)."""
import bisect
import collections
import datetime as dt
import os
import re
import sqlite3

from . import config, paths

TERMINALS = {"terminal", "iterm2", "ghostty", "warp", "alacritty", "kitty", "wezterm"}
EDITORS = {"code", "cursor", "visual studio code", "xcode", "pycharm", "intellij idea", "zed", "windsurf"}
APP_SUFFIXES = [
    "Google Chrome", "Mozilla Firefox", "Safari", "Microsoft Edge", "Arc", "Dia", "Brave",
    "Visual Studio Code", "Cursor", "Code", "Terminal", "iTerm2", "Ghostty", "Warp", "Obsidian",
    "Notion", "Slack", "Discord", "WeChat", "微信", "Finder", "Preview", "Adobe Acrobat", "Zotero",
    "Mathematica", "Wolfram", "Overleaf", "Texifier", "TeXstudio", "Xcode", "PyCharm", "IntelliJ IDEA",
]


def iso(ts):
    return dt.datetime.fromisoformat(ts)


def fmt_dur(sec):
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def clean_title(t):
    t = t or ""
    t = re.sub(r"\s*[—–-]\s*\d+\s*[×x]\s*\d+\s*$", "", t)
    for s in APP_SUFFIXES:
        t = re.sub(rf"\s*[—–-]\s*{re.escape(s)}\s*$", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" —–-|")


def context_key(app, title):
    """A stable 'what was this window about' key: project dir for terminals, file for editors."""
    t = clean_title(title)
    a = (app or "").lower()
    if a in TERMINALS:
        parts = [p.strip() for p in re.split(r"\s*(?:—|–|\||◂|·)\s*", t) if p.strip()]
        p = parts[0] if parts else t
        p = p.rstrip("/").split("/")[-1]
        return p[:70] or "(untitled)"
    if a in EDITORS:
        parts = [p.strip() for p in re.split(r"\s*(?:—|–|\|)\s*", t) if p.strip()]
        return " / ".join(parts[:2])[:80] or "(untitled)"
    return t[:80] or "(untitled)"


def ios_name(bundle, title, cfg=None):
    cfg = cfg or config.get()
    if bundle in cfg["app_names"]:
        return cfg["app_names"][bundle]
    if title:  # App Store title, e.g. "淘宝-万能的淘宝！" -> "淘宝"
        head = re.split(r"\s+[-–—|:：]\s+|[-–—：]", title, maxsplit=1)[0].strip()
        return head or title
    return bundle


def _cls(domain, subdomain, project, evaluation, rule=None):
    return {"domain": domain, "subdomain": subdomain or "", "project": project,
            "evaluation": evaluation, "rule": rule}


def classify_ios(bundle, name, cfg=None):
    cfg = cfg or config.get()
    d = cfg["app_defaults"].get(bundle)
    u = cfg["uncategorized"]
    if d:
        return _cls(d.get("domain", u), d.get("subdomain", ""), d.get("project", name), d.get("evaluation", u), f"ios:{bundle}")
    return _cls(u, "", name, u)


def classify_mac(app, title, cfg=None):
    cfg = cfg or config.get()
    u = cfg["uncategorized"]
    for r in cfg["mac_rules"]:
        apps = r.get("apps", [])
        if "*" not in apps and app not in apps:
            continue
        pat = r.get("title_re", "")
        # "." means "any title" (re.search(".", "") is None, so empty titles would otherwise fall through)
        if pat in ("", ".", ".*") or re.search(pat, title or "", re.I):
            return _cls(r.get("domain", u), r.get("subdomain", ""), r.get("project", app), r.get("evaluation", u), r.get("name"))
    return _cls(u, "", app, u)


# ---- opencode: a terminal titled just "OpenCode" hides the project; recover it from opencode's own
# session log (the directory whose session had message activity around that time). -------------
OPENCODE_GENERIC_RULE = "terminal-opencode-generic"
UNRESOLVED_RULES = {OPENCODE_GENERIC_RULE, "terminal-fallback", "shell-idle", None}
_oc = {"lo": None, "hi": None, "times": [], "dirs": []}


def _opencode_load(lo_ms, hi_ms):
    if _oc["lo"] is not None and _oc["lo"] <= lo_ms and hi_ms <= _oc["hi"]:
        return
    times, dirs = [], []
    if paths.OPENCODE_DB.exists():
        try:
            con = sqlite3.connect(f"file:{paths.OPENCODE_DB}?mode=ro", uri=True, timeout=2)
            rows = con.execute(
                "select m.time_created, s.directory from message m join session s on s.id = m.session_id "
                "where m.time_created between ? and ? order by m.time_created", (lo_ms, hi_ms)).fetchall()
            con.close()
            times, dirs = [r[0] for r in rows], [r[1] for r in rows]
        except Exception:
            pass  # locked / schema change: leave the window unresolved
    _oc.update(lo=lo_ms, hi=hi_ms, times=times, dirs=dirs)


def opencode_dir_at(start, end, lead=1800, lag=900):
    """Directory of the busiest opencode session in [start-lead, end+lag] — wide, because reading a
    long answer can mean 10-20 minutes without a new message."""
    lo = int(start.timestamp() * 1000) - lead * 1000
    hi = int(end.timestamp() * 1000) + lag * 1000
    day = 86_400_000  # on a miss, load ±2 days around the union so long queries reload rarely
    _opencode_load(min(lo, _oc["lo"] or lo) - 2 * day, max(hi, _oc["hi"] or hi) + 2 * day)
    i, j = bisect.bisect_left(_oc["times"], lo), bisect.bisect_right(_oc["times"], hi)
    if i >= j:
        return None
    return collections.Counter(_oc["dirs"][i:j]).most_common(1)[0][0]


def classify_mac_at(app, title, start, end, cfg=None):
    cfg = cfg or config.get()
    cls = classify_mac(app, title, cfg)
    if cls.get("rule") != OPENCODE_GENERIC_RULE:
        return cls
    d = opencode_dir_at(start, end)
    if not d:
        return cls
    base = os.path.basename(d.rstrip("/")) or d
    alt = classify_mac(app, f"{base} — {d}", cfg)
    if alt.get("rule") in UNRESOLVED_RULES:
        return {**cls, "project": base}
    return {**alt, "rule": f"{OPENCODE_GENERIC_RULE}>{alt['rule']}"}


def apply_duration_rules(rows, cfg=None):
    """Re-evaluate whole sittings by how long they lasted (config `duration_rules`).

    A sitting = same source + device + project, consecutive intervals whose gaps are at most
    session_gap_seconds. If its wall-clock span exceeds a rule's over_minutes, every interval in it
    takes the rule's evaluation; shorter sittings keep their base evaluation. Mutates rows in place.
    """
    cfg = cfg or config.get()
    dur = cfg.get("duration_rules") or {}
    rules = dur.get("rules") or []
    if not rules:
        return rows
    gap = float(dur.get("session_gap_seconds", 300))
    rule_of = {}
    for rule in rules:
        for sd in rule.get("subdomains") or []:
            rule_of.setdefault(sd, rule)
    by_key = collections.defaultdict(list)
    for r in rows:
        if r.get("subdomain") in rule_of:
            by_key[(r.get("source"), r.get("device"), r.get("project"))].append(r)

    def flush(session):
        rule = rule_of[session[0]["subdomain"]]
        span = (max(x["end"] for x in session) - session[0]["start"]).total_seconds()
        if span > float(rule["over_minutes"]) * 60:
            for x in session:
                x["evaluation"] = rule["evaluation"]
                x["duration_rule"] = rule.get("name")

    for items in by_key.values():
        items.sort(key=lambda x: x["start"])
        session, end = [], None
        for x in items:
            if session and (x["start"] - end).total_seconds() > gap:
                flush(session)
                session, end = [], None
            session.append(x)
            end = x["end"] if end is None else max(end, x["end"])
        if session:
            flush(session)
    return rows


def afk_intervals(events):
    out = []
    for e in events:
        if (e.get("data") or {}).get("status") == "not-afk":
            s = iso(e["timestamp"])
            out.append((s, s + dt.timedelta(seconds=e.get("duration") or 0)))
    return out


def overlap_seconds(a, b, intervals):
    total = 0.0
    for s, e in intervals:
        lo, hi = max(a, s), min(b, e)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total
