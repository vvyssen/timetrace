"""Where timetrace keeps its files. Override the data dir with TIMETRACE_HOME (used by tests)."""
import os
import sys
from pathlib import Path

HOME = Path.home()
SUPPORT = Path(os.environ.get("TIMETRACE_HOME") or HOME / "Library" / "Application Support" / "timetrace")
CONFIG = SUPPORT / "config.yaml"            # the user's taxonomy + rules (single source of truth)
SETTINGS = SUPPORT / "settings.json"        # language, ports, setup state
IMPORTER_STATUS = SUPPORT / "importer-status.json"  # written by the Full Disk Access helper
BACKUPS = SUPPORT / "backups"
LOGS = HOME / "Library" / "Logs" / "timetrace"
APPS = HOME / "Applications"
LAUNCH_AGENTS = HOME / "Library" / "LaunchAgents"

PKG = Path(__file__).resolve().parent
DATA = PKG / "data"
STATIC = PKG / "dashboard" / "static"
HELPER = PKG / "helper"


def _bundle():
    """The self-contained Timetrace.app we run from (its Python lives in Contents/Resources/python/bin), else None."""
    exe = Path(sys.executable)
    p = exe.parents
    if len(p) > 4 and p[1].name == "python" and p[2].name == "Resources" and p[4].suffix == ".app" \
            and (p[3] / "MacOS" / "Timetrace").exists():
        return p[4]
    return None


BUNDLE = _bundle()                                     # set when installed from the Timetrace.app release
BUNDLE_BIN = Path(sys.executable).parent if BUNDLE else None   # its python3 and the timetrace / timetrace-mcp wrappers

OPENCODE_DB = HOME / ".local" / "share" / "opencode" / "opencode.db"
# each app's "Open Recent" list, with full paths (one .sfl4 per bundle id)
RECENT_DOCS = HOME / "Library" / "Application Support" / "com.apple.sharedfilelist" / "com.apple.LSSharedFileList.ApplicationRecentDocuments"
DOC_PATHS = SUPPORT / "doc-paths.json"      # file name -> path once matched, kept after macOS forgets it
RECENT_SNAPSHOT = SUPPORT / "recent-docs.json"  # copy of those lists, written by the Full Disk Access helper
DOCS_STATUS = SUPPORT / "docs-status.json"
BIOME_SYNC_DB = HOME / "Library" / "Biome" / "sync" / "sync.db"


def ensure_dirs():
    for p in (SUPPORT, BACKUPS, LOGS):
        p.mkdir(parents=True, exist_ok=True)
