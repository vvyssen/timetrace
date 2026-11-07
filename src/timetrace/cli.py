"""timetrace command line. Read commands print table / json / csv; every write backs up first."""
import argparse
import csv
import json
import subprocess
import sys

from . import __version__, aw, classify as C, config, onboarding, paths, queries as Q, settings


def render_table(headers, rows):
    rows = [[str(c) for c in r] for r in rows]
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)))


def emit(rows, headers, fmt):
    if fmt == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
    elif fmt == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(headers)
        for r in rows:
            w.writerow([r.get(h, "") for h in headers])
    else:
        render_table(headers, [[r.get(h, "") for h in headers] for r in rows])


def _range(a):
    return Q.resolve_range(getattr(a, "date", None), getattr(a, "from_", None), getattr(a, "to", None), getattr(a, "since", None))


# ---- read ---------------------------------------------------------------------------------------
def cmd_summary(a):
    start, end = _range(a)
    fields, rows, total = Q.summary(start, end, a.group_by, a.device, a.limit)
    if a.format == "table":
        print(f"# {start.astimezone(Q.LOCAL):%Y-%m-%d %H:%M} → {end.astimezone(Q.LOCAL):%Y-%m-%d %H:%M}  total={C.fmt_dur(total)}", file=sys.stderr)
    emit(rows, fields + ["seconds", "duration", "share"], a.format)


def cmd_timeline(a):
    start, end = _range(a)
    emit(Q.timeline(start, end, a.device, a.min_seconds, a.merge_gap, a.limit), Q.TIMELINE_FIELDS, a.format)


def cmd_query(a):
    start, end = _range(a)
    cols, rows = Q.query(start, end, a.sql, a.device, a.limit)
    emit(rows, cols, a.format)


def cmd_schema(a):
    d = Q.schema()
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return
    print("table: intervals")
    for k, v in d["columns"].items():
        print(f"  {k:12} {v}")
    print("\nbuckets:\n  " + "\n  ".join(d["buckets"]))
    print(f"\ntimezone: {d['timezone']}\nrule precedence: {d['rule_precedence']}\n\nnotes:")
    for n in d["notes"]:
        print(f"  - {n}")
    print("\nexamples:\n  " + "\n  ".join(d["examples"]))


def cmd_taxonomy(a):
    cfg = config.get()
    if a.json:
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
        return
    print("domains:")
    for d, subs in cfg["domains"].items():
        print(f"  {d}: {', '.join(subs) if subs else '-'}")
    print("\nevaluations:")
    for e, desc in cfg["evaluations"].items():
        print(f"  {e} ({cfg['evaluation_roles'].get(e, '-')}): {desc}")
    dr = cfg.get("duration_rules") or {}
    print(f"\nduration rules (sitting = gaps ≤ {dr.get('session_gap_seconds', 300) / 60:g} min):")
    for r in dr.get("rules", []):
        print(f"  {', '.join(r['subdomains'])}: one sitting > {r['over_minutes']:g} min → {r['evaluation']}")
    print(f"\nmac_rules: {len(cfg['mac_rules'])}   app_defaults (iPhone/iPad): {len(cfg['app_defaults'])}")
    for r in cfg["mac_rules"]:
        print(f"  {r['name']}: {r.get('domain')} > {r.get('subdomain') or '-'} / {r.get('evaluation')}  ({r.get('title_re')})")


def cmd_suggest(a):
    c = onboarding.candidates(a.days, a.limit)
    if a.format == "json":
        print(json.dumps(c, ensure_ascii=False, indent=2, default=str))
        return
    rows = [{"id": g["id"], "label": g["label"], "time": C.fmt_dur(g["seconds"]), "devices": "+".join(g["devices"]),
             "now": f"{g['current']['domain']}/{g['current']['subdomain'] or '-'}/{g['current']['evaluation']}"} for g in c["needs_tag"]]
    print(f"# {len(rows)} item(s) to tag from the last {a.days} days — `timetrace tag --id <id> --domain … --evaluation …`", file=sys.stderr)
    emit(rows, ["id", "label", "time", "devices", "now"], "table")


def cmd_doctor(a):
    s = onboarding.status()
    if a.json:
        print(json.dumps(s, ensure_ascii=False, indent=2, default=str))
        return
    ok = lambda b: "✓" if b else "✗"
    print(f"{ok(s['aw']['ok'])} ActivityWatch  {s['aw'].get('url')}  {s['aw'].get('version') or s['aw'].get('error', '')}")
    m = s["mac"]
    if m.get("ok"):
        tr = m.get("title_ratio")
        print(f"{ok(m['fresh'])} Mac windows  last event {m['last']}  ({'live' if m['fresh'] else 'not updating'})")
        print(f"{ok(tr is None or tr > 0.3)} Window titles  {int((tr or 0) * 100)}% of recent windows have a title"
              + ("" if tr is None or tr > 0.3 else "  → give ActivityWatch Accessibility permission"))
    else:
        print("✗ Mac windows  no aw-watcher-window data")
    imp = s["importer"]
    print(f"{ok(imp.get('fda'))} iPhone/iPad importer  state={imp.get('state')}  helper={'installed' if imp.get('helper_installed') else 'missing'}")
    if not s["ios"]:
        print("✗ iPhone/iPad data  none yet (Full Disk Access for Timetrace Importer + 'Share Across Devices' in Screen Time)")
    for d in s["ios"]:
        print(f"{ok((d['hours_since'] or 99) < 24)} {d['kind']} {d['name']}  last event {d['last']} ({d['hours_since']} h ago)")
    for name, up in s["services"].items():
        print(f"{ok(up)} service {name}")
    print(f"{ok(s['config'])} config {paths.CONFIG}")
    from . import services
    for c in services.conflicts():
        print(f"! {c}")


# ---- write --------------------------------------------------------------------------------------
def cmd_tag(a):
    if a.id:
        t = {"id": a.id}
    elif a.bundle:
        t = {"kind": "ios_app", "bundle": a.bundle, "app": a.app}
    elif a.mac_app:
        t = {"kind": "mac_app", "app": a.mac_app}
    elif a.keyword:
        t = {"kind": "mac_context", "keyword": a.keyword, "apps": a.apps.split(",") if a.apps else None}
    else:
        raise ValueError("give one of --id, --bundle, --mac-app or --keyword")
    if a.ignore:
        t["ignore"] = True
    else:
        t.update(domain=a.domain, subdomain=a.subdomain or "", evaluation=a.evaluation, project=a.project)
    print(json.dumps(onboarding.apply_tags([t]), ensure_ascii=False))


def cmd_install(a):
    from . import services
    paths.ensure_dirs()
    if a.lang:
        settings.save(lang=a.lang)
    cfg = config.init()
    print(f"config: {paths.CONFIG} ({cfg['lang']})")
    for c in services.conflicts():
        print(f"warning: {c}")
    res = services.install(start=not a.no_start)
    print(f"apps: {services.HELPER_APP}  {services.LAUNCHER_APP}" + ("  (importer helper rebuilt — grant Full Disk Access again)" if res["helper_rebuilt"] else ""))
    for name, (ok_, msg) in res["services"].items():
        print(f"service {name}: {'running' if ok_ else 'FAILED ' + msg}")


def cmd_uninstall(a):
    from . import services
    services.uninstall(remove_apps=not a.keep_apps)
    print("removed background services" + ("" if a.keep_apps else " and apps") + f". Your data and rules stay in {paths.SUPPORT}.")
    print("to remove the programs too: uv tool uninstall timetrace && uv tool uninstall aw-import-screentime")


def cmd_service(a):
    from . import services
    if a.action == "restart":
        for n in ([a.name] if a.name else services.labels()):
            print(f"{n}: {'restarted' if services.restart(n) else 'not loaded'}")
    elif a.action == "plist":
        import plistlib
        for n, pl in services.plists().items():
            print(f"--- {n}\n" + plistlib.dumps(pl).decode())
    else:
        for n, label in services.labels().items():
            print(f"{n}: {'loaded' if onboarding._launchd_loaded(label) else 'not loaded'}  ({label})")


def cmd_dash(a):
    port = settings.load()["port"]
    subprocess.run(["open", f"http://127.0.0.1:{port}/" + ("#setup" if a.setup else "")])


def cmd_demo(a):
    import os
    import threading
    os.environ["TIMETRACE_DEMO"] = "1"
    os.environ["TIMETRACE_PORT"] = str(a.port)
    from . import demo
    demo.ON = True
    from .dashboard import server
    url = f"http://127.0.0.1:{a.port}/#range=7d"
    threading.Timer(1.0, lambda: subprocess.run(["open", url])).start()
    print(f"demo dashboard with synthetic data on {url} — Ctrl-C to stop")
    try:
        server.main()
    except KeyboardInterrupt:
        pass


def cmd_sync_aw(a):
    from . import syncaw
    if a.restore:
        syncaw.restore(a.restore)
        print(f"restored ActivityWatch settings from {a.restore}")
        return
    cats, approx = syncaw.build()
    print(f"{len(cats)} categories for ActivityWatch; title-only approximations: {', '.join(approx) or 'none'}")
    if a.apply:
        print(f"written; previous ActivityWatch settings saved to {syncaw.apply(cats)}")
    else:
        print("dry run — add --apply to write")


def cmd_agent(a):
    from . import agents
    if a.action == "prompt":
        print(agents.prompt(a.lang or settings.load()["lang"]).rstrip())
        return
    res = agents.install(a.only.split(",") if a.only else None) if a.action == "install" else agents.status()
    for name, r in res.items():
        if not r.get("found"):
            print(f"- {name}: not found")
            continue
        line = f"{'✓' if r.get('mcp') else '✗'} {name}: MCP {'registered' if r.get('mcp') else 'not registered'}"
        if r.get("skill"):
            line += f"; skill → {r['skill']}"
        print(line)
        if r.get("manual"):
            print("    " + r["manual"].replace("\n", "\n    "))
    if a.action != "install":
        print("run `timetrace agent install` to register the MCP server and skill")


def cmd_config(a):
    if a.action == "path":
        print(paths.CONFIG)
    elif a.action == "import":
        config.import_file(a.file)
        print(f"imported {a.file} → {paths.CONFIG}")
    elif a.action == "reset":
        config.backup()
        config.init(lang=a.lang, force=True)
        print(f"reset {paths.CONFIG} from the built-in library (backup in {paths.BACKUPS})")
    elif a.action == "lang":
        settings.save(lang=a.lang)
        print(f"interface language: {a.lang} (rule labels stay as they are; `timetrace config reset --lang {a.lang}` regenerates them)")


def add_range(p):
    p.add_argument("--since", default=None, help="7d, 24h, 90m, 2w, today, yesterday or an ISO date")
    p.add_argument("--from", dest="from_", default=None, help="start date/datetime")
    p.add_argument("--to", default=None, help="end date/datetime")
    p.add_argument("--date", default=None, help="a single local day, e.g. 2026-11-03")


def build_parser():
    p = argparse.ArgumentParser(prog="timetrace", description="Automatic time tracking across Mac, iPhone and iPad — by purpose and value, for you and your agents.",
                                epilog="Start with: timetrace doctor · timetrace summary --since 7d · timetrace dash")
    p.add_argument("--version", action="version", version=f"timetrace {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    fmt = dict(choices=["table", "json", "csv"], default="table")

    s = sub.add_parser("summary", help="aggregate time in any range")
    add_range(s)
    s.add_argument("--group-by", default="domain,evaluation", help="comma-separated: " + ",".join(sorted(Q.GROUP_FIELDS)))
    s.add_argument("--device", default="all", help="all, mac, iphone, ipad or part of a device name")
    s.add_argument("--format", **fmt)
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_summary)

    t = sub.add_parser("timeline", help="what was used when")
    add_range(t)
    t.add_argument("--device", default="all")
    t.add_argument("--min-seconds", type=float, default=30)
    t.add_argument("--merge-gap", type=float, default=60)
    t.add_argument("--format", **fmt)
    t.add_argument("--limit", type=int, default=200)
    t.set_defaults(func=cmd_timeline)

    q = sub.add_parser("query", help="read-only SQL over the intervals table")
    add_range(q)
    q.add_argument("--sql", required=True)
    q.add_argument("--device", default="all")
    q.add_argument("--format", **fmt)
    q.add_argument("--limit", type=int, default=500)
    q.set_defaults(func=cmd_query)

    for name, fn, hlp in (("schema", cmd_schema, "table schema and data sources"), ("taxonomy", cmd_taxonomy, "domains, evaluations and rules"),
                          ("doctor", cmd_doctor, "check that data is flowing")):
        x = sub.add_parser(name, help=hlp)
        x.add_argument("--json", action="store_true")
        x.set_defaults(func=fn)

    sg = sub.add_parser("suggest", help="apps and window keywords that still need a tag")
    sg.add_argument("--days", type=int, default=14)
    sg.add_argument("--limit", type=int, default=20)
    sg.add_argument("--format", choices=["table", "json"], default="table")
    sg.set_defaults(func=cmd_suggest)

    tg = sub.add_parser("tag", help="save a tag into your rules")
    tg.add_argument("--id", help="an id from `timetrace suggest` (fills in the item and its app scope)")
    tg.add_argument("--bundle", help="iPhone/iPad bundle id")
    tg.add_argument("--mac-app", help="Mac app name")
    tg.add_argument("--keyword", help="Mac window-title keyword (e.g. a project folder)")
    tg.add_argument("--apps", help="with --keyword: limit to these apps (comma-separated); default any app")
    tg.add_argument("--app", help="with --bundle: display name")
    tg.add_argument("--domain")
    tg.add_argument("--subdomain")
    tg.add_argument("--evaluation")
    tg.add_argument("--project")
    tg.add_argument("--ignore", action="store_true", help="exclude the app from all stats instead")
    tg.set_defaults(func=cmd_tag)

    d = sub.add_parser("dash", help="open the dashboard")
    d.add_argument("--setup", action="store_true", help="open the setup wizard")
    d.set_defaults(func=cmd_dash)

    dm = sub.add_parser("demo", help="open the dashboard with synthetic data (no permissions needed)")
    dm.add_argument("--port", type=int, default=27182)
    dm.set_defaults(func=cmd_demo)

    ins = sub.add_parser("install", help="install background services and apps (run by install.sh)")
    ins.add_argument("--no-start", action="store_true", help="build apps and config, but do not load launchd services")
    ins.add_argument("--lang", choices=["zh", "en"])
    ins.set_defaults(func=cmd_install)

    un = sub.add_parser("uninstall", help="remove background services and apps (keeps your data)")
    un.add_argument("--keep-apps", action="store_true")
    un.set_defaults(func=cmd_uninstall)

    sv = sub.add_parser("service", help="background services")
    sv.add_argument("action", choices=["status", "restart", "plist"], nargs="?", default="status")
    sv.add_argument("name", nargs="?", choices=["dashboard", "importer"])
    sv.set_defaults(func=cmd_service)

    sa = sub.add_parser("sync-aw", help="mirror your domain tree into ActivityWatch's categories (optional)")
    sa.add_argument("--apply", action="store_true")
    sa.add_argument("--restore", metavar="BACKUP_JSON")
    sa.set_defaults(func=cmd_sync_aw)

    ag = sub.add_parser("agent", help="connect Claude Code / Codex / opencode / Hermes")
    ag.add_argument("action", choices=["status", "install", "prompt"], nargs="?", default="status",
                    help="status | install (register MCP + skill) | prompt (print the tagging prompt)")
    ag.add_argument("--lang", choices=["zh", "en"], help="for prompt")
    ag.add_argument("--only", help="comma-separated subset, e.g. claude,codex")
    ag.set_defaults(func=cmd_agent)

    cf = sub.add_parser("config", help="your rules file")
    cf.add_argument("action", choices=["path", "import", "reset", "lang"])
    cf.add_argument("file", nargs="?", help="for import: a categories.yaml to adopt")
    cf.add_argument("--lang", choices=["zh", "en"])
    cf.set_defaults(func=cmd_config)
    return p


def main(argv=None):
    p = build_parser()
    a = p.parse_args(argv)
    if a.cmd == "config" and a.action == "import" and not a.file:
        p.error("config import needs a file")
    if a.cmd == "config" and a.action == "lang" and not a.lang:
        p.error("config lang needs --lang zh|en")
    try:
        a.func(a)
    except (ValueError, aw.AWUnavailable) as e:
        print(f"timetrace: {e}", file=sys.stderr)
        sys.exit(1)
    except BrokenPipeError:
        pass


if __name__ == "__main__":
    main()
