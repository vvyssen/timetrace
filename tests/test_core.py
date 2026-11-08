"""Core behaviour without ActivityWatch: config generation, classification, duration rules, tagging."""
import datetime as dt
import importlib
import sqlite3
import time

import pytest
import yaml


@pytest.fixture()
def tt(tmp_path, monkeypatch):
    monkeypatch.setenv("TIMETRACE_HOME", str(tmp_path / "home"))
    import timetrace.paths as paths
    importlib.reload(paths)
    import timetrace.settings as settings
    import timetrace.config as config
    import timetrace.classify as classify
    import timetrace.onboarding as onboarding
    for m in (settings, config, classify, onboarding):
        importlib.reload(m)
    monkeypatch.setattr(settings, "system_lang", lambda: "zh")
    monkeypatch.setattr(paths, "OPENCODE_DB", tmp_path / "opencode.db")
    monkeypatch.setattr(paths, "RECENT_DOCS", tmp_path / "recent")
    config._cache.update(mtime=None, cfg=None)
    config.init(lang="zh")
    return {"paths": paths, "config": config, "C": classify, "O": onboarding, "settings": settings, "tmp": tmp_path}


T0 = dt.datetime(2026, 11, 5, 10, 0, tzinfo=dt.timezone.utc)


def row(minutes_from, minutes_long, subdomain="购物", project="淘宝", ev="保值"):
    s = T0 + dt.timedelta(minutes=minutes_from)
    return {"source": "ios", "device": "iPhone", "project": project, "subdomain": subdomain, "evaluation": ev,
            "start": s, "end": s + dt.timedelta(minutes=minutes_long), "seconds": minutes_long * 60}


def test_library_materializes_in_both_languages(tt):
    zh = tt["config"].materialize("zh")
    en = tt["config"].materialize("en")
    assert list(zh["evaluations"]) == ["创造", "提升", "保值", "消遣"]
    assert list(en["evaluations"]) == ["Create", "Grow", "Maintain", "Unwind"]
    assert zh["app_defaults"]["com.tencent.xin"]["domain"] == "社交"
    assert en["app_defaults"]["com.tencent.xin"]["subdomain"] == "Messaging"
    for cfg in (zh, en):  # every rule points at labels that exist in the taxonomy
        for r in cfg["mac_rules"] + list(cfg["app_defaults"].values()):
            assert r["domain"] in cfg["domains"]
            assert not r["subdomain"] or r["subdomain"] in cfg["domains"][r["domain"]]
            assert r["evaluation"] in cfg["evaluations"]


def test_any_title_rule_matches_empty_title(tt):
    c = tt["C"].classify_mac("Texifier", "")
    assert (c["domain"], c["evaluation"]) == ("工作", "创造")
    assert tt["C"].classify_mac("NoSuchApp", "x")["domain"] == "未分类"


def test_title_rules_win_over_app_fallbacks(tt):
    c = tt["C"].classify_mac("Dia", "Some video - YouTube")
    assert c["rule"] == "site-video"
    assert tt["C"].classify_mac("Dia", "Random page")["rule"] == "browsers"


def test_duration_rules_judge_whole_sittings(tt):
    C = tt["C"]
    # one sitting: 20 + 30 min with a 3-minute break (gap 5 min) -> 53 min > 45 -> leisure
    rows = [row(0, 20), row(23, 30)]
    C.apply_duration_rules(rows)
    assert {r["evaluation"] for r in rows} == {"消遣"}
    # a 10-minute break splits it into two short sittings -> keep
    rows = [row(0, 20), row(30, 30)]
    C.apply_duration_rules(rows)
    assert {r["evaluation"] for r in rows} == {"保值"}
    # chat threshold is 20 minutes
    rows = [row(0, 25, subdomain="即时通讯", project="微信")]
    C.apply_duration_rules(rows)
    assert rows[0]["evaluation"] == "消遣"


def test_apply_tags_orders_rules_and_backs_up(tt):
    O, config = tt["O"], tt["config"]
    O.apply_tags([
        {"kind": "mac_context", "keyword": "my-repo", "domain": "工作", "subdomain": "开发", "evaluation": "创造"},
        {"kind": "mac_app", "app": "magpie", "domain": "生活", "subdomain": "新子领域", "evaluation": "保值"},
        {"kind": "ios_app", "bundle": "com.example.x", "app": "X App", "domain": "生活", "subdomain": "购物", "evaluation": "保值"},
        {"kind": "ios_app", "bundle": "com.example.noise", "ignore": True},
    ])
    cfg = config.get()
    names = [r["name"] for r in cfg["mac_rules"]]
    assert names[0] == "user-title-my-repo"
    first_app_level = next(i for i, r in enumerate(cfg["mac_rules"]) if r["title_re"] == "." and "*" not in r["apps"])
    assert names[first_app_level] == "user-app-magpie"
    assert "新子领域" in cfg["domains"]["生活"]
    assert cfg["app_defaults"]["com.example.x"]["project"] == "X App"
    assert "com.example.noise" in cfg["ignore_bundles"]
    assert list(tt["paths"].BACKUPS.glob("config-*.yaml"))
    c = tt["C"].classify_mac("Ghostty", "my-repo — zsh")
    assert (c["domain"], c["project"]) == ("工作", "my-repo")
    with pytest.raises(ValueError):
        O.apply_tags([{"kind": "mac_app", "app": "y", "domain": "不存在", "evaluation": "保值"}])


def test_site_of(tt):
    O = tt["O"]
    assert O.site_of("五时 - Google Search") == "Google Search"
    assert O.site_of("Mac at any scale | Namespace") == "Namespace"
    assert O.site_of("Control Pane…") is None
    assert O.site_of("just a title") is None


def test_opencode_session_recovers_project(tt):
    db = sqlite3.connect(tt["tmp"] / "opencode.db")
    db.execute("create table session (id text, directory text)")
    db.execute("create table message (session_id text, time_created integer)")
    db.execute("insert into session values ('s1', '/Users/me/code/my-repo')")
    for k in range(5):
        db.execute("insert into message values ('s1', ?)", (int((T0 + dt.timedelta(minutes=k)).timestamp() * 1000),))
    db.commit()
    db.close()
    O, C = tt["O"], tt["C"]
    O.apply_tags([{"kind": "mac_context", "keyword": "my-repo", "domain": "学习", "subdomain": "科研", "evaluation": "提升"}])
    c = C.classify_mac_at("Ghostty", "OpenCode", T0, T0 + dt.timedelta(minutes=3))
    assert (c["domain"], c["project"]) == ("学习", "my-repo")
    assert c["rule"].startswith(C.OPENCODE_GENERIC_RULE + ">")
    far = T0 + dt.timedelta(days=3)
    assert C.classify_mac_at("Ghostty", "OpenCode", far, far)["rule"] == C.OPENCODE_GENERIC_RULE


def bookmark(path):
    """A minimal macOS bookmark blob: path components (key 0x1004) as a string array."""
    import struct
    data, offs = bytearray(4), []  # 4 bytes reserved for the first-TOC offset
    for part in path.strip("/").split("/"):
        raw = part.encode()
        offs.append(len(data))
        data += struct.pack("<II", len(raw), 0x0101) + raw + b"\0" * (-len(raw) % 4)
    arr = len(data)
    data += struct.pack("<II", 4 * len(offs), 0x0601) + b"".join(struct.pack("<I", o) for o in offs)
    toc = len(data)
    data += struct.pack("<IIIII", 20, 0xFFFFFFFE, 1, 0, 1) + struct.pack("<III", 0x1004, arr, 0)
    data[0:4] = struct.pack("<I", toc)
    return b"book" + struct.pack("<III", 0x30 + len(data), 0x10040000, 0x30) + b"\0" * 32 + bytes(data)


def test_document_folder_decides_when_only_the_app_matched(tt):
    import plistlib
    C, O, paths = tt["C"], tt["O"], tt["paths"]
    client = "/Users/me/ClientWork/acme/报价单.pdf"
    assert C.bookmark_path(bookmark(client)) == client
    paths.RECENT_DOCS.mkdir(parents=True)
    (paths.RECENT_DOCS / "com.readdle.pdfexpert-mac.sfl4").write_bytes(plistlib.dumps(
        {"$objects": ["$null", bookmark(client), bookmark("/Users/me/Papers/main.pdf"), b"not a bookmark"]},
        fmt=plistlib.FMT_BINARY))
    O.apply_tags([{"kind": "mac_context", "keyword": "ClientWork", "domain": "工作", "subdomain": "客户项目", "evaluation": "保值"}])
    O.apply_tags([{"kind": "mac_context", "keyword": "Papers", "domain": "学习", "subdomain": "科研", "evaluation": "提升"}])
    at = lambda app, title: C.classify_mac_at(app, title, T0, T0)
    # PDF Expert drops the extension and adds " - Locked"; Preview adds " – Page n of m"
    c = at("PDF Expert", "报价单 - Locked")
    assert (c["subdomain"], c["evaluation"], c["rule"]) == ("客户项目", "保值", "doc-path>user-title-ClientWork")
    assert at("Preview", "报价单.pdf – Page 3 of 9")["subdomain"] == "客户项目"
    assert at("Preview", "main.pdf – Page 1 of 2")["subdomain"] == "科研"
    # unknown files, and browsers (page titles, not files), keep their normal rule
    assert not at("Preview", "other.pdf – Page 1 of 1")["rule"].startswith("doc-path")
    assert not at("Dia", "报价单")["rule"].startswith("doc-path")
    # a matched file is remembered after it drops out of macOS's short recent list
    (paths.RECENT_DOCS / "com.readdle.pdfexpert-mac.sfl4").unlink()
    C._docs["t"] = 0
    assert at("PDF Expert", "报价单")["subdomain"] == "客户项目"


def test_without_access_the_helper_snapshot_is_used(tt, monkeypatch):
    import json
    import plistlib
    import timetrace.docsnap as docsnap
    import timetrace.services as services
    C, O, paths = tt["C"], tt["O"], tt["paths"]
    paths.RECENT_DOCS.mkdir(parents=True)
    (paths.RECENT_DOCS / "com.apple.preview.sfl4").write_bytes(plistlib.dumps(
        {"$objects": [bookmark("/Users/me/ClientWork/a.pdf")]}, fmt=plistlib.FMT_BINARY))
    docsnap.main()  # what the helper runs every few minutes
    assert json.loads(paths.RECENT_SNAPSHOT.read_text()) == {"a.pdf": "/Users/me/ClientWork/a.pdf"}
    monkeypatch.setattr(C, "recent_docs", lambda: None)  # a launchd process without Full Disk Access
    O.apply_tags([{"kind": "mac_context", "keyword": "ClientWork", "domain": "工作", "subdomain": "客户项目", "evaluation": "保值"}])
    assert C.classify_mac_at("Preview", "a.pdf – Page 1 of 2", T0, T0)["subdomain"] == "客户项目"
    job = services.plists()["docs"]
    assert job["ProgramArguments"][0].endswith("Timetrace Importer.app/Contents/MacOS/timetrace-importer")
    assert job["ProgramArguments"][-2:] == ["-m", "timetrace.docsnap"] and job["StartInterval"] == 300


def test_config_hot_reload_and_legacy_import(tt):
    config, paths = tt["config"], tt["paths"]
    legacy = tt["tmp"] / "categories.yaml"
    legacy.write_text(yaml.safe_dump({
        "domains": {"工作": ["创业"], "未分类": []},
        "evaluations": {"创造": "a", "提升": "b", "保值": "c", "消遣": "d"},
        "app_defaults": {}, "mac_rules": [{"name": "x", "apps": ["*"], "title_re": "my-startup", "domain": "工作", "subdomain": "创业", "evaluation": "创造"}],
    }, allow_unicode=True))
    config.import_file(legacy)
    cfg = config.get()
    assert cfg["evaluation_roles"] == {"创造": "create", "提升": "grow", "保值": "keep", "消遣": "leisure"}
    assert cfg["uncategorized"] == "未分类"
    data = yaml.safe_load(paths.CONFIG.read_text())
    data["domains"]["工作"].append("新")
    time.sleep(0.01)
    paths.CONFIG.write_text(yaml.safe_dump(data, allow_unicode=True))
    import os
    os.utime(paths.CONFIG, (time.time() + 5, time.time() + 5))
    assert "新" in config.get()["domains"]["工作"]


def test_keyword_tag_stays_in_its_app_family(tt):
    O, C = tt["O"], tt["C"]
    O.apply_tags([{"kind": "mac_context", "keyword": "wissen", "apps": O.DEV_APPS,
                   "domain": "生活", "subdomain": "个人项目", "evaluation": "创造", "project": "个人项目"}])
    assert C.classify_mac("Terminal", "wissen — zsh")["project"] == "个人项目"
    assert C.classify_mac("1Password", "wissen — All Items")["rule"] == "passwords"


def test_tag_by_suggest_id_fills_item_and_scope(tt, monkeypatch):
    O, C = tt["O"], tt["C"]
    fake = {"needs_tag": [{"id": "mac_context:my-repo", "kind": "mac_context", "app": "Ghostty", "keyword": "my-repo",
                           "apps": O.DEV_APPS}], "review": []}
    monkeypatch.setattr(O, "candidates", lambda *a, **k: fake)
    O.apply_tags([{"id": "mac_context:my-repo", "domain": "工作", "subdomain": "开发", "evaluation": "创造", "project": "my-repo"}])
    assert C.classify_mac("Ghostty", "my-repo — zsh")["project"] == "my-repo"
    assert C.classify_mac("Safari", "my-repo pull request")["project"] != "my-repo"   # scoped to dev apps
    with pytest.raises(ValueError):
        O.apply_tags([{"id": "mac_context:nope", "domain": "工作", "evaluation": "创造"}])


@pytest.fixture()
def srv(tt, monkeypatch):
    import timetrace.lan as lan
    import timetrace.intervals as I
    import timetrace.dashboard.server as server
    importlib.reload(lan)
    importlib.reload(server)
    monkeypatch.setattr(lan, "hostname", lambda: "test-mac.local")
    monkeypatch.setattr(lan, "lan_ips", lambda: ["192.168.1.25"])
    return {"lan": lan, "server": server, "I": I, **tt}


def handler(server, ip, host="127.0.0.1:27181", cookie=None):
    h = server.Handler.__new__(server.Handler)
    h.client_address = (ip, 50000)
    h.headers = {"Host": host, **({"Cookie": cookie} if cookie else {})}
    return h


def test_phone_access_is_read_only_and_needs_the_token(srv):
    lan, server = srv["lan"], srv["server"]
    assert handler(server, "127.0.0.1").access({}) == "rw"
    assert handler(server, "127.0.0.1", host="evil.example:27181").access({}) is None  # DNS rebinding
    assert handler(server, "192.168.1.30", host="192.168.1.25:27181").access({"t": "x"}) is None  # off by default
    lan.enable()
    tok = srv["settings"].load()["lan_token"]
    phone = handler(server, "192.168.1.30", host="test-mac.local:27181")
    assert phone.access({"t": tok}) == "ro"
    assert phone.access({"t": tok + "x"}) is None
    own_name = handler(server, "127.0.0.1", host="test-mac.local:27181")  # macOS resolves its own .local to loopback
    assert own_name.access({"t": tok}) == "ro" and own_name.access({}) is None
    assert handler(server, "192.168.1.30", host="test-mac.local:27181", cookie=f"{server.COOKIE}={tok}").access({}) == "ro"
    assert "/api/setup/candidates" not in server.READ_ONLY_ROUTES and "/api/data" in server.READ_ONLY_ROUTES
    lan.rotate()
    assert phone.access({"t": tok}) is None  # old links stop working
    lan.disable()
    assert phone.access({"t": srv["settings"].load()["lan_token"]}) is None


def test_lan_links_put_the_stable_name_first(srv):
    lan = srv["lan"]
    assert lan.urls() == []
    lan.enable()
    tok = srv["settings"].load()["lan_token"]
    assert lan.urls("2026-11-07") == [f"http://test-mac.local:27181/?t={tok}#range=day&date=2026-11-07",
                                      f"http://192.168.1.25:27181/?t={tok}#range=day&date=2026-11-07"]


def test_heat_cells_add_up_to_the_daily_totals(srv, monkeypatch):
    server, I = srv["server"], srv["I"]
    now = dt.datetime.now(I.LOCAL).replace(minute=0, second=0, microsecond=0)
    y = now - dt.timedelta(days=1)

    def r(start, minutes, ev, active=None):
        return {"start": start, "end": start + dt.timedelta(minutes=minutes), "seconds": (active or minutes) * 60, "evaluation": ev,
                "kind": "Mac", "device": "Mac", "context": "", "domain": "休闲", "subdomain": "视频", "project": "", "app": "Video"}
    rows = [r(y.replace(hour=22, minute=30), 90, "消遣"), r(y.replace(hour=9), 60, "创造", active=30)]
    monkeypatch.setattr(I, "fetch_intervals", lambda *a, **k: rows)
    d = server.build({"range": "7d"})
    h = d["heat"]
    assert len(h["days"]) == 7
    li = h["evals"].index("消遣")
    yd = next(x for x in h["days"] if x["date"] == y.date().isoformat())
    assert yd["h"][22][li] == 1800 and yd["h"][23][li] == 3600       # 22:30–24:00
    assert yd["h"][9][h["evals"].index("创造")] == 1800              # active share of a 60-min span
    for day in h["days"]:
        daily = next(x for x in d["daily"] if x["date"] == day["date"])
        assert sum(map(sum, day["h"])) == pytest.approx(sum(daily["evals"].values()), abs=2)
    assert server.build({"range": "today"})["heat"] is None


def test_devices_come_from_activitywatch_buckets(srv, monkeypatch):
    I = srv["I"]
    import timetrace.aw as aw
    monkeypatch.setattr(aw, "buckets", lambda: {
        "w": {"type": "currentwindow", "hostname": "Yans-MacBook-Air.local"},
        "a": {"type": "afkstatus", "hostname": "Yans-MacBook-Air.local"},
        "p1": {"client": "aw-import-screentime", "hostname": "Wissen's iPhone"},
        "p2": {"client": "aw-import-screentime", "hostname": "Work iPhone"},
        "s": {"type": "general.stopwatch", "hostname": "unknown"}})
    assert I.devices() == [{"name": "Mac", "kind": "Mac", "source": "mac"},
                           {"name": "Wissen's iPhone", "kind": "iPhone", "source": "ios"},
                           {"name": "Work iPhone", "kind": "iPhone", "source": "ios"}]  # no iPad
    assert srv["server"].meta()["devices"][1]["name"] == "Wissen's iPhone"
    # the menu filters one device by exact name; a plain word still matches part of a name
    assert I.device_match("ios", "Work iPhone", "name:work iphone")
    assert not I.device_match("ios", "Work iPhone 2", "name:work iphone")
    assert I.device_match("ios", "Work iPhone 2", "work iphone")


def test_detailed_view_splits_devices_of_one_kind(srv, monkeypatch):
    server, I = srv["server"], srv["I"]
    now = dt.datetime.now(I.LOCAL).replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)

    def r(device, kind, minutes):
        return {"start": now, "end": now + dt.timedelta(minutes=minutes), "seconds": minutes * 60, "evaluation": "创造", "kind": kind,
                "device": device, "context": "", "domain": "工作", "subdomain": "开发", "project": "x", "app": "A"}
    rows = [r("Mac", "Mac", 30), r("Wissen's iPhone", "iPhone", 20), r("Work iPhone", "iPhone", 10)]
    monkeypatch.setattr(I, "fetch_intervals", lambda *a, **k: rows)
    combined = server.build({"range": "7d"})
    assert list(combined["by_device"]) == ["Mac", "iPhone"] and not combined["split"]
    detailed = server.build({"range": "7d", "split": "1"})
    assert list(detailed["by_device"]) == ["Mac", "iPhone:Wissen's iPhone", "iPhone:Work iPhone"]  # a lone Mac stays "Mac"
    assert sum(detailed["by_device"]["iPhone:Work iPhone"].values()) == pytest.approx(600)
    cal = server.build_calendar({"split": "1"})
    assert cal["lanes"] == ["Mac", "iPhone:Wissen's iPhone", "iPhone:Work iPhone"]


def test_reset_rules_backs_up_then_restores_defaults(srv):
    server, config, O = srv["server"], srv["config"], srv["O"]
    O.apply_tags([{"kind": "mac_app", "app": "Some Editor", "domain": "工作", "subdomain": "新子领域", "evaluation": "创造"}])
    assert "新子领域" in config.get()["domains"]["工作"]
    res = server.action("reset-rules", {})
    assert res["backup"] and "新子领域" in open(res["backup"], encoding="utf-8").read()
    config._cache.update(mtime=None, cfg=None)
    assert "新子领域" not in config.get()["domains"]["工作"]
