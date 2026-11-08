"""Where timetrace keeps its files. Override the data dir with TIMETRACE_HOME (used by tests)."""
import os
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
