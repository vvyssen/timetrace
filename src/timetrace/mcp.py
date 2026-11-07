"""timetrace MCP server — stdio JSON-RPC (newline-delimited), no dependencies.

Shares queries/onboarding with the CLI, so agents and the dashboard always see the same numbers.
Tools: summary, timeline, query, schema, taxonomy, suggest, tag, doctor.
"""
import json
import sys

from . import __version__, classify as C, config, onboarding, queries as Q

PROTOCOL_VERSION = "2024-11-05"
KNOWN = {"2024-11-05", "2025-03-26", "2025-06-18"}

RANGE = {
    "date": {"type": "string", "description": "single local day: 2026-11-03, today or yesterday (wins over from/to/since)"},
    "from": {"type": "string", "description": "start: ISO date or datetime, local time"},
    "to": {"type": "string", "description": "end: a bare date means through 23:59:59 that day"},
    "since": {"type": "string", "description": "relative start: 7d / 24h / 90m / 2w; all empty = last 7 days"},
}
DEVICE = {"type": "string", "description": "all, mac, iphone, ipad, or part of a device name", "default": "all"}
TAG_PROPS = {
    "kind": {"type": "string", "enum": ["ios_app", "mac_app", "mac_context"]},
    "bundle": {"type": "string", "description": "iPhone/iPad bundle id (kind=ios_app)"},
    "app": {"type": "string", "description": "app name (kind=mac_app, or display name for ios_app)"},
    "keyword": {"type": "string", "description": "window-title keyword, e.g. a project folder (kind=mac_context)"},
    "domain": {"type": "string"}, "subdomain": {"type": "string"}, "evaluation": {"type": "string"},
    "project": {"type": "string"}, "ignore": {"type": "boolean", "description": "exclude this app from all stats instead"},
}

TOOLS = [
    {"name": "summary", "description": "Aggregate time by any of domain, subdomain, evaluation, project, app, device, date, hour, weekday across Mac + iPhone + iPad. Use for 'where did my time go' and shares.",
     "inputSchema": {"type": "object", "properties": {**RANGE, "group_by": {"type": "string", "default": "domain,evaluation"}, "device": DEVICE, "limit": {"type": "integer", "default": 50}}}},
    {"name": "timeline", "description": "Interval-by-interval timeline (what was used when). Use for 'what was I doing yesterday at 3pm'.",
     "inputSchema": {"type": "object", "properties": {**RANGE, "device": DEVICE, "min_seconds": {"type": "number", "default": 30}, "merge_gap": {"type": "number", "default": 60}, "limit": {"type": "integer", "default": 200}}}},
    {"name": "query", "description": "Read-only SQL (single SELECT/WITH, no semicolons) over the `intervals` table — see `schema` for columns.",
     "inputSchema": {"type": "object", "properties": {"sql": {"type": "string"}, **RANGE, "device": DEVICE, "limit": {"type": "integer", "default": 500}}, "required": ["sql"]}},
    {"name": "schema", "description": "Columns of the intervals table, data sources and caveats. Call this first.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "taxonomy", "description": "The user's domains, subdomains, evaluation labels (with roles create/grow/keep/leisure) and rules.", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "suggest", "description": "Apps and window keywords that still need a tag (uncategorized or only broadly guessed), with time spent and sample titles.",
     "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "default": 14}, "limit": {"type": "integer", "default": 20}}}},
    {"name": "tag", "description": "WRITE: save tags into the user's rules. Propose tags to the user and get confirmation before calling.",
     "inputSchema": {"type": "object", "properties": {"tags": {"type": "array", "items": {"type": "object", "properties": TAG_PROPS, "required": ["kind"]}}}, "required": ["tags"]}},
    {"name": "doctor", "description": "Is data flowing? ActivityWatch, Mac windows, iPhone/iPad importer and its Full Disk Access, background services.", "inputSchema": {"type": "object", "properties": {}}},
]


def _range(p):
    return Q.resolve_range(p.get("date"), p.get("from"), p.get("to"), p.get("since"))


def _info(start, end):
    return {"start_local": start.astimezone(Q.LOCAL).strftime("%Y-%m-%d %H:%M:%S"), "end_local": end.astimezone(Q.LOCAL).strftime("%Y-%m-%d %H:%M:%S")}


def do_summary(p):
    start, end = _range(p)
    fields, rows, total = Q.summary(start, end, p.get("group_by") or "domain,evaluation", p.get("device") or "all", int(p.get("limit") or 50))
    return {"range": _info(start, end), "group_by": ",".join(fields), "total_seconds": round(total, 1), "total_duration": C.fmt_dur(total), "rows": rows}


def do_timeline(p):
    start, end = _range(p)
    gap = float(p["merge_gap"]) if p.get("merge_gap") is not None else 60
    rows = Q.timeline(start, end, p.get("device") or "all", float(p.get("min_seconds") or 30), gap, int(p.get("limit") or 200))
    return {"range": _info(start, end), "rows": rows}


def do_query(p):
    start, end = _range(p)
    cols, rows = Q.query(start, end, p.get("sql"), p.get("device") or "all", int(p.get("limit") or 500))
    return {"range": _info(start, end), "columns": cols, "rows": rows}


def do_suggest(p):
    return onboarding.candidates(int(p.get("days") or 14), int(p.get("limit") or 20))


HANDLERS = {
    "summary": do_summary, "timeline": do_timeline, "query": do_query,
    "schema": lambda p: Q.schema(), "taxonomy": lambda p: config.get(),
    "suggest": do_suggest, "tag": lambda p: onboarding.apply_tags(p.get("tags") or []),
    "doctor": lambda p: onboarding.status(),
}


def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        if not isinstance(req, dict):
            continue
        method, rid = req.get("method"), req.get("id")
        if method == "initialize":
            want = (req.get("params") or {}).get("protocolVersion")
            send({"jsonrpc": "2.0", "id": rid, "result": {"protocolVersion": want if want in KNOWN else PROTOCOL_VERSION,
                  "capabilities": {"tools": {}}, "serverInfo": {"name": "timetrace", "version": __version__}}})
        elif method in ("notifications/initialized", "notifications/cancelled", "notifications/roots/list_changed"):
            pass
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": rid, "result": {}})
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})
        elif method == "resources/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"resources": []}})
        elif method == "prompts/list":
            send({"jsonrpc": "2.0", "id": rid, "result": {"prompts": []}})
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            try:
                if name not in HANDLERS:
                    raise ValueError(f"Unknown tool: {name}")
                result = HANDLERS[name](params.get("arguments") or {})
                send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1, default=str)}], "isError": False}})
            except Exception as e:
                send({"jsonrpc": "2.0", "id": rid, "result": {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}})
        elif rid is not None:
            send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Unknown method: {method}"}})


if __name__ == "__main__":
    main()
