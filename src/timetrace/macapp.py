"""What Timetrace.app does when opened (its Contents/MacOS/Timetrace runs `python3 -I -m timetrace.macapp`).

Every launch makes sure the background services run from this copy of the app, then opens the dashboard.
The first launch, and the first one after an update or a move, (re)installs the services and links the
`timetrace` / `timetrace-mcp` commands into ~/.local/bin. The very first launch also walks the user
through ActivityWatch and Full Disk Access, like install.sh does.
"""
import json
import plistlib
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import __version__, paths, services, settings

STATE = paths.SUPPORT / "app-install.json"
LOCAL_BIN = paths.HOME / ".local" / "bin"
AW_DOWNLOAD = "https://activitywatch.net/downloads/"


def _t(zh, en):
    return zh if settings.load().get("lang") == "zh" else en


def _dialog(msg, buttons=("OK",)):
    """A plain AppleScript dialog; returns the button clicked ("" if dismissed)."""
    script = ['on run argv',
              'set n to count of argv',
              'set bs to items 2 thru n of argv',
              'display dialog (item 1 of argv) with title "Timetrace" buttons bs default button (item n of argv)',
              'return button returned of result',
              'end run']
    cmd = ["osascript"] + sum((["-e", l] for l in script), []) + [msg, *buttons]
    return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()


def _services_run_here():
    try:
        with open(services.plist_path(services.labels()["dashboard"]), "rb") as f:
            return plistlib.load(f)["ProgramArguments"][0] == sys.executable
    except Exception:
        return False


def _link_cli():
    """Put the bundled commands on PATH, without touching a real install (e.g. from uv)."""
    LOCAL_BIN.mkdir(parents=True, exist_ok=True)
    for name in ("timetrace", "timetrace-mcp"):
        dst, src = LOCAL_BIN / name, paths.BUNDLE_BIN / name
        if dst.is_symlink() and (not dst.exists() or ".app/Contents/" in str(dst.readlink())):
            dst.unlink()  # dangling, or pointing into an old copy of the app
        if not dst.exists() and not dst.is_symlink():
            dst.symlink_to(src)


def _install():
    paths.ensure_dirs()
    log = paths.LOGS / "app.log"
    with open(log, "a") as f:
        f.write(f"\n== {time.strftime('%Y-%m-%d %H:%M:%S')} install from {paths.BUNDLE} (v{__version__})\n")
        f.flush()
        r = subprocess.run([sys.executable, "-m", "timetrace.cli", "install"], stdout=f, stderr=subprocess.STDOUT)
    return r.returncode == 0, log


def _wait_dashboard(port, secs=20):
    for _ in range(secs * 2):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/meta", timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def _activitywatch_installed():
    return any((d / "ActivityWatch.app").exists() for d in (paths.HOME / "Applications", Path("/Applications")))


def _has_full_disk_access():
    try:
        return json.loads(paths.IMPORTER_STATUS.read_text()).get("fda") is True
    except Exception:
        return False


def main():
    if not paths.BUNDLE:
        print("timetrace.macapp runs inside Timetrace.app; from a terminal use `timetrace install`.")
        return 1
    if "/AppTranslocation/" in str(paths.BUNDLE):  # opened straight from Downloads: macOS runs a read-only copy
        _dialog(_t("请先把 Timetrace 拖到「应用程序」文件夹，再从那里打开。",
                   "Move Timetrace to the Applications folder first, then open it from there."))
        return 1
    # the user already let the app through Gatekeeper; clear the flag so launchd can run the bundled Python
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(paths.BUNDLE)], capture_output=True)

    first = not STATE.exists()
    want = {"version": __version__, "app": str(paths.BUNDLE), "python": sys.executable}
    try:
        have = json.loads(STATE.read_text())
    except Exception:
        have = None
    if have != want or not _services_run_here():
        ok, log = _install()
        if not ok:
            _dialog(_t(f"安装后台服务失败，详情见 {log}", f"Couldn't install the background services. See {log}"))
            return 1
        STATE.write_text(json.dumps(want, indent=2))
        try:
            _link_cli()
        except OSError:
            pass

    if _activitywatch_installed():
        subprocess.run(["open", "-g", "-a", "ActivityWatch"], capture_output=True)
    elif first:
        go = _t("下载", "Download")
        if _dialog(_t("Timetrace 依靠 ActivityWatch 记录 Mac 上的时间。请先安装 ActivityWatch（免费、开源），装好后再打开 Timetrace。",
                      "Timetrace reads your Mac time from ActivityWatch. Install ActivityWatch (free, open source), "
                      "then open Timetrace again."), (_t("稍后", "Later"), go)) == go:
            subprocess.run(["open", AW_DOWNLOAD])

    port = settings.load()["port"]
    _wait_dashboard(port)
    if first and not _has_full_disk_access():  # someone coming from install.sh may have granted it already
        subprocess.run(["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"])
        subprocess.run(["open", "-R", str(services.HELPER_APP)])
        _dialog(_t("要导入 iPhone/iPad 的屏幕使用时间，请在刚打开的「完全磁盘访问权限」里点 +，选中访达里高亮的「Timetrace Importer」并打开开关。"
                   "iPhone/iPad 和 Mac 上还要打开：设置 › 屏幕使用时间 › 跨设备共享。",
                   "To import Screen Time from your iPhone/iPad: in the Full Disk Access settings that just opened, click +, "
                   "choose the highlighted “Timetrace Importer” and turn it on. Also turn on Settings › Screen Time › "
                   "Share Across Devices on your iPhone/iPad and on this Mac."))
    subprocess.run(["open", f"http://127.0.0.1:{port}/" + ("" if settings.load().get("setup_done") else "#setup")])
    return 0


if __name__ == "__main__":
    sys.exit(main())
