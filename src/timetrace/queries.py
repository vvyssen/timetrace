"""Range parsing and the read operations shared by the CLI and the MCP server."""
import collections
import re
import sqlite3
from datetime import datetime, timedelta

from . import classify as C, config, intervals as I

LOCAL = I.LOCAL
GROUP_FIELDS = {"domain", "subdomain", "evaluation", "project", "app", "device", "date", "hour", "weekday"}


def parse_when(s, end=False):
    if s is None:
        return None
    s = s.strip()
    now = datetime.now(LOCAL)
    if s == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if s == "yesterday":
        return (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.fullmatch(r"(\d+)([mhdw])", s)
    if m:
        n = int(m.group(1))
        return now - {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n)}[m.group(2)]
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"Invalid time: {s!r} (use 7d, 24h, today, yesterday, 2026-11-03 or an ISO datetime)")
    if d.tzinfo is None:
        d = d.replace(tzinfo=LOCAL)
    if len(s) == 10 and end:
        d = d.replace(hour=23, minute=59, second=59)
    return d


def resolve_range(date=None, from_=None, to=None, since=None):
    if date:
        start = parse_when(date)
        return start, start + timedelta(days=1)
    end = parse_when(to, end=True) or datetime.now(LOCAL)
    start = parse_when(from_) if from_ else parse_when(since) if since else end - timedelta(days=7)
    if start >= end:
        raise ValueError("start must be before end")
    return start, end


def group_value(iv, field):
    if field == "date":
        return iv["start"].astimezone(LOCAL).date().isoformat()
    if field == "hour":
        return f"{iv['start'].astimezone(LOCAL).hour:02d}"
    if field == "weekday":
        return iv["start"].astimezone(LOCAL).strftime("%a")
    return iv.get(field) or "-"


def summary(start, end, group_by="domain,evaluation", device="all", limit=50):
    fields = [f.strip() for f in group_by.split(",") if f.strip()]
    bad = [f for f in fields if f not in GROUP_FIELDS]
    if bad:
        raise ValueError(f"Unknown group field(s): {', '.join(bad)}. Use: {', '.join(sorted(GROUP_FIELDS))}")
    agg = collections.defaultdict(float)
    for iv in I.fetch_intervals(start, end, device):
        agg[tuple(group_value(iv, f) for f in fields)] += iv["seconds"]
    total = sum(agg.values())
    rows = []
    for key, sec in sorted(agg.items(), key=lambda kv: kv[1], reverse=True)[:limit]:
        row = dict(zip(fields, key))
        row.update(seconds=round(sec, 1), duration=C.fmt_dur(sec), share=f"{sec / total * 100:.1f}%" if total else "0%")
        rows.append(row)
    return fields, rows, total


def timeline(start, end, device="all", min_seconds=30, merge_gap=60, limit=200):
    ivs = [iv for iv in I.fetch_intervals(start, end, device) if iv["seconds"] >= min_seconds]
    ivs = sorted(I.merge_timeline(ivs, merge_gap), key=lambda x: x["start"])
    return [{
        "start": iv["start"].astimezone(LOCAL).strftime("%Y-%m-%d %H:%M:%S"),
        "end": iv["end"].astimezone(LOCAL).strftime("%H:%M:%S"),
        "duration": C.fmt_dur(iv["seconds"]),
        "device": iv["device"], "app": iv["app"], "context": iv["context"], "domain": iv["domain"],
        "evaluation": iv["evaluation"], "project": iv["project"], "seconds": round(iv["seconds"], 1),
    } for iv in ivs[:limit]]


TIMELINE_FIELDS = ["start", "end", "duration", "device", "app", "context", "domain", "evaluation", "project", "seconds"]


def build_db(ivs):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE intervals (device TEXT, source TEXT, app TEXT, title TEXT, context TEXT, domain TEXT, "
                 "subdomain TEXT, project TEXT, evaluation TEXT, start TEXT, end TEXT, seconds REAL)")
    conn.executemany("INSERT INTO intervals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [
        (iv["device"], iv["source"], iv["app"], iv["title"], iv["context"], iv["domain"], iv["subdomain"], iv["project"],
         iv["evaluation"], iv["start"].isoformat(), iv["end"].isoformat(), round(iv["seconds"], 3)) for iv in ivs])
    return conn


def query(start, end, sql, device="all", limit=500):
    sql = (sql or "").strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", sql, re.I):
        raise ValueError("Only SELECT / WITH queries are allowed")
    if ";" in sql:
        raise ValueError("Only a single statement is allowed")
    cur = build_db(I.fetch_intervals(start, end, device)).execute(sql)
    cols = [d[0] for d in cur.description]
    return cols, [dict(zip(cols, r)) for r in cur.fetchmany(limit)]


def schema():
    cfg = config.get()
    ev = config.eval_order(cfg)
    try:
        from . import aw
        buckets = sorted(aw.buckets())
    except Exception as e:  # schema should still answer without ActivityWatch
        buckets = [f"(ActivityWatch unavailable: {e})"]
    return {
        "table": "intervals",
        "columns": {
            "device": "device name, e.g. Mac or <name>'s iPhone / iPad",
            "source": "mac / ios",
            "app": "app name (iPhone/iPad: human-readable name)",
            "title": "raw window title on Mac; app name on iPhone/iPad",
            "context": "normalized window context (terminal project dir, editor file, page title)",
            "domain": " / ".join(cfg["domains"]),
            "subdomain": "e.g. " + " / ".join(sorted({s for v in cfg["domains"].values() for s in v})[:12]),
            "project": "project or app",
            "evaluation": " / ".join(f"{n} ({cfg['evaluation_roles'].get(n, '-')})" for n in ev),
            "start": "ISO8601 UTC", "end": "ISO8601 UTC",
            "seconds": "active seconds (Mac: trimmed by AFK)",
        },
        "buckets": buckets,
        "timezone": str(LOCAL),
        "rule_precedence": "Mac: mac_rules in order, first match wins (title rules first, app fallbacks last); iPhone/iPad: app_defaults by bundle id; otherwise uncategorized",
        "notes": [
            "iPhone/iPad data is app-level only: no window titles or page content.",
            "A Mac terminal titled just 'OpenCode' is attributed to the opencode session active at that time.",
            f"Duration rules: {cfg.get('duration_rules')}",
            "summary seconds sum raw intervals; timeline merges adjacent intervals with the same context.",
        ],
        "examples": [
            "timetrace summary --since 7d --group-by domain,evaluation",
            "timetrace timeline --date yesterday --device iphone",
            "timetrace query --sql \"select app, sum(seconds)/3600.0 as hours from intervals group by app order by hours desc limit 10\"",
        ],
    }
