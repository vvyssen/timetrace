"""Connect coding agents to timetrace: register the MCP server and install one shared skill file.

One source (data/agent-guide.md) is distributed to every agent found on the machine.
Config files are backed up before they are touched; if a file can't be parsed safely, the snippet is
printed for the user to paste instead of rewriting it.
"""
import json
import shutil
import subprocess
import time
from pathlib import Path

from . import paths

GUIDE = paths.DATA / "agent-guide.md"


def mcp_command():
    found = shutil.which("timetrace-mcp")
    return found or str(paths.HOME / ".local" / "bin" / "timetrace-mcp")


def _backup(p):
    if p.exists():
        shutil.copy2(p, p.with_name(p.name + f".bak-timetrace-{time.strftime('%Y%m%d%H%M%S')}"))


def _skill(dirpath):
    d = Path(dirpath) / "timetrace"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(GUIDE, d / "SKILL.md")
    return str(d / "SKILL.md")


def claude(apply):
    if not shutil.which("claude"):
        return {"found": False}
    r = subprocess.run(["claude", "mcp", "get", "timetrace"], capture_output=True, text=True)
    has = r.returncode == 0
    res = {"found": True, "mcp": has}
    if apply:
        if not has:
            r = subprocess.run(["claude", "mcp", "add", "--scope", "user", "timetrace", "--", mcp_command()], capture_output=True, text=True)
            res["mcp"] = r.returncode == 0
            res["mcp_msg"] = (r.stderr or r.stdout).strip()[-200:]
        res["skill"] = _skill(paths.HOME / ".claude" / "skills")
    return res


def codex(apply):
    cfg = paths.HOME / ".codex" / "config.toml"
    if not (shutil.which("codex") or cfg.exists()):
        return {"found": False}
    text = cfg.read_text() if cfg.exists() else ""
    has = "[mcp_servers.timetrace]" in text
    res = {"found": True, "mcp": has}
    if apply:
        if not has:
            _backup(cfg)
            cfg.parent.mkdir(parents=True, exist_ok=True)
            with open(cfg, "a") as f:
                f.write(f'\n[mcp_servers.timetrace]\ncommand = "{mcp_command()}"\nargs = []\n')
            res["mcp"] = True
        res["skill"] = _skill(paths.HOME / ".codex" / "skills")
    return res


def opencode(apply):
    cfg = paths.HOME / ".config" / "opencode" / "opencode.json"
    if not (shutil.which("opencode") or cfg.exists()):
        return {"found": False}
    try:
        data = json.loads(cfg.read_text()) if cfg.exists() else {}
    except json.JSONDecodeError:
        snippet = {"mcp": {"timetrace": {"type": "local", "command": [mcp_command()], "enabled": True}}}
        return {"found": True, "mcp": False, "manual": f"add to {cfg}: {json.dumps(snippet)}"}
    has = "timetrace" in (data.get("mcp") or {})
    res = {"found": True, "mcp": has}
    if apply:
        if not has:
            _backup(cfg)
            data.setdefault("mcp", {})["timetrace"] = {"type": "local", "command": [mcp_command()], "enabled": True}
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            res["mcp"] = True
        res["skill"] = _skill(paths.HOME / ".config" / "opencode" / "skills")
    return res


def hermes(apply):
    cfg = paths.HOME / ".hermes" / "config.yaml"
    if not cfg.exists():
        return {"found": False}
    has = "timetrace-mcp" in cfg.read_text()
    res = {"found": True, "mcp": has}
    if not has:  # YAML with comments: never rewrite it, just say what to add
        res["manual"] = f"add under mcp_servers in {cfg}:\n  timetrace:\n    command: {mcp_command()}"
    return res


AGENTS = {"claude": claude, "codex": codex, "opencode": opencode, "hermes": hermes}


def status():
    return {name: fn(False) for name, fn in AGENTS.items()}


def install(only=None):
    return {name: fn(True) for name, fn in AGENTS.items() if not only or name in only}
