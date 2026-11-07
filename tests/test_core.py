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
