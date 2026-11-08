"""Copy every app's Open Recent list (file name -> path) into timetrace's folder.

Run every few minutes by launchd through Timetrace Importer.app, which holds Full Disk Access:
macOS keeps the lists in a guarded folder, so the dashboard (a plain launchd process) reads this copy.
"""
import json
import os

from . import classify, paths


def main():
    docs = classify.recent_docs()
    if docs is None:
        raise SystemExit("cannot read the recent-documents lists (Full Disk Access missing?)")
    paths.RECENT_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.RECENT_SNAPSHOT.with_suffix(".tmp")
    tmp.write_text(json.dumps(docs, ensure_ascii=False, indent=0))
    os.replace(tmp, paths.RECENT_SNAPSHOT)


if __name__ == "__main__":
    main()
