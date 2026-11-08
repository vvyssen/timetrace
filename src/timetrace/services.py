"""Install / remove the background pieces: two launchd agents and two tiny apps.

  Timetrace Importer.app  — holds Full Disk Access and runs the iPhone/iPad importer (launchd agent)
  Timetrace.app           — opens the dashboard; findable with Spotlight ("Timetrace" / "时间看板")
  dashboard               — local web server on 127.0.0.1 (launchd agent)
"""
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import paths, settings

HELPER_APP = paths.APPS / "Timetrace Importer.app"
LAUNCHER_APP = paths.APPS / "Timetrace.app"
IMPORTER_PIN = "1297039793819b25f926289fb033d77c66786c50"  # ActivityWatch/aw-import-screentime
IMPORTER_SPEC = f"git+https://github.com/ActivityWatch/aw-import-screentime@{IMPORTER_PIN}"


def labels():
    p = settings.LABEL_PREFIX
    return {"dashboard": f"{p}.dashboard", "importer": f"{p}.importer", "docs": f"{p}.docs"}


def plist_path(label):
    return paths.LAUNCH_AGENTS / f"{label}.plist"


def _run(cmd, check=False):
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _sign(app, identifier):
    _run(["codesign", "--force", "--deep", "-s", "-", "--identifier", identifier, str(app)], check=True)


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---- Timetrace Importer.app -------------------------------------------------------------------
def build_helper():
    """(Re)build the helper only when its binary changed: an unchanged bundle keeps its code
    signature, so a Full Disk Access grant survives reinstalls."""
    src = paths.HELPER / "timetrace-importer"
    exe = HELPER_APP / "Contents" / "MacOS" / "timetrace-importer"
    marker = HELPER_APP / "Contents" / "Resources" / "source.sha256"  # signing rewrites exe, so compare the source
    if exe.exists() and marker.exists() and marker.read_text().strip() == _sha(src):
        return False
    if HELPER_APP.exists():
        shutil.rmtree(HELPER_APP)
    (HELPER_APP / "Contents" / "MacOS").mkdir(parents=True)
    (HELPER_APP / "Contents" / "Resources").mkdir(parents=True)
    shutil.copy2(src, exe)
    exe.chmod(0o755)
    shutil.copy2(paths.HELPER / "AppIcon.icns", HELPER_APP / "Contents" / "Resources" / "AppIcon.icns")
    info = {
        "CFBundleIdentifier": f"{settings.LABEL_PREFIX}.importer",
        "CFBundleName": "Timetrace Importer",
        "CFBundleDisplayName": "Timetrace Importer",
        "CFBundleExecutable": "timetrace-importer",
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "12.0",
        "NSHumanReadableCopyright": "timetrace — reads Screen Time data synced from your iPhone/iPad, locally.",
    }
    with open(HELPER_APP / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    marker.write_text(_sha(src))
    _sign(HELPER_APP, info["CFBundleIdentifier"])
    return True


# ---- Timetrace.app (dashboard launcher) ---------------------------------------------------------
def build_launcher(port):
    if LAUNCHER_APP.exists():
        shutil.rmtree(LAUNCHER_APP)
    paths.APPS.mkdir(parents=True, exist_ok=True)
    _run(["osacompile", "-o", str(LAUNCHER_APP), "-e", f'open location "http://127.0.0.1:{port}/"'], check=True)
    res = LAUNCHER_APP / "Contents" / "Resources"
    shutil.copy2(paths.HELPER / "AppIcon.icns", res / "applet.icns")
    (res / "Assets.car").unlink(missing_ok=True)
    plist = LAUNCHER_APP / "Contents" / "Info.plist"
    with open(plist, "rb") as f:
        info = plistlib.load(f)
    info.pop("CFBundleIconName", None)
    info.update(CFBundleIdentifier=f"{settings.LABEL_PREFIX}.launcher", CFBundleName="Timetrace",
                CFBundleDisplayName="Timetrace", LSHasLocalizedDisplayName=True)
    with open(plist, "wb") as f:
        plistlib.dump(info, f)
    for loc in ("zh_CN", "zh-Hans", "zh_TW", "zh-Hant"):
        d = res / f"{loc}.lproj"
        d.mkdir(exist_ok=True)
        (d / "InfoPlist.strings").write_text('CFBundleDisplayName = "时间看板";\nCFBundleName = "时间看板";\n', encoding="utf-16")
    _sign(LAUNCHER_APP, info["CFBundleIdentifier"])
    _run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister", "-f", str(LAUNCHER_APP)])


# ---- launchd ----------------------------------------------------------------------------------
def importer_bin():
    found = shutil.which("aw-import-screentime")
    return found or str(paths.HOME / ".local" / "bin" / "aw-import-screentime")


def plists():
    s = settings.load()
    lb = labels()
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    dash = {
        "Label": lb["dashboard"],
        "ProgramArguments": [sys.executable, "-m", "timetrace.dashboard.server"],
        "RunAtLoad": True, "KeepAlive": True,
        "StandardOutPath": str(paths.LOGS / "dashboard.log"), "StandardErrorPath": str(paths.LOGS / "dashboard.log"),
    }
    args = [str(HELPER_APP / "Contents" / "MacOS" / "timetrace-importer"), "--status", str(paths.IMPORTER_STATUS), "--",
            importer_bin(), "watch"]
    for sf in s.get("storefronts") or ["us"]:
        args += ["--storefront", sf]
    imp = {
        "Label": lb["importer"], "ProgramArguments": args,
        "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 30,
        "ProcessType": "Background", "LowPriorityIO": True,
        "EnvironmentVariables": {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:" + str(paths.HOME / ".local" / "bin")},
        "StandardOutPath": str(paths.LOGS / "importer.log"), "StandardErrorPath": str(paths.LOGS / "importer.log"),
    }
    # which files PDF / editor windows show: read the guarded Open Recent lists with the helper's access
    docs = {
        "Label": lb["docs"],
        "ProgramArguments": [str(HELPER_APP / "Contents" / "MacOS" / "timetrace-importer"), "--status", str(paths.DOCS_STATUS), "--",
                             sys.executable, "-m", "timetrace.docsnap"],
        "RunAtLoad": True, "StartInterval": 300, "ProcessType": "Background", "LowPriorityIO": True,
        "StandardOutPath": str(paths.LOGS / "docs.log"), "StandardErrorPath": str(paths.LOGS / "docs.log"),
    }
    return {"dashboard": dash, "importer": imp, "docs": docs}


def _domain():
    return f"gui/{os.getuid()}"


def load(name, pl):
    path = plist_path(pl["Label"])
    path.parent.mkdir(parents=True, exist_ok=True)
    _run(["launchctl", "bootout", f"{_domain()}/{pl['Label']}"])
    with open(path, "wb") as f:
        plistlib.dump(pl, f)
    r = _run(["launchctl", "bootstrap", _domain(), str(path)])
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def unload(label, remove=True):
    _run(["launchctl", "bootout", f"{_domain()}/{label}"])
    if remove:
        plist_path(label).unlink(missing_ok=True)


def restart(name):
    return _run(["launchctl", "kickstart", "-k", f"{_domain()}/{labels()[name]}"]).returncode == 0


def conflicts():
    """Things that would fight with our services: another server on the port, or another importer
    (two importers writing the same buckets would duplicate events)."""
    out = []
    port = settings.load()["port"]
    r = _run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"])
    pids = [l[1:] for l in r.stdout.splitlines() if l.startswith("p")]
    mine = _run(["launchctl", "print", f"{_domain()}/{labels()['dashboard']}"]).stdout
    for pid in pids:
        if f"pid = {pid}" not in mine:
            out.append(f"port {port} is already used by pid {pid}")
    # only processes actually running an importer, not any command line that happens to mention the name
    r = _run(["pgrep", "-fl", "aw-import-screentime watch|aw_import_screentime watch"])
    imp = _run(["launchctl", "print", f"{_domain()}/{labels()['importer']}"]).stdout
    helper_pid = next((l.split("=")[1].strip() for l in imp.splitlines() if l.strip().startswith("pid =")), None)
    for line in r.stdout.splitlines():
        pid = line.split()[0]
        ppid = _run(["ps", "-o", "ppid=", "-p", pid]).stdout.strip()
        ours = "timetrace-importer" in line or pid == helper_pid or (helper_pid and ppid == helper_pid)
        if not ours:  # the importer our helper spawned is a child of the helper, not a rival
            out.append(f"another Screen Time importer is running (pid {pid}): {line[:120]}")
    return out


def install(start=True):
    paths.ensure_dirs()
    s = settings.load()
    built = build_helper()
    build_launcher(s["port"])
    results = {"helper_rebuilt": built, "services": {}}
    if start:
        for name, pl in plists().items():
            results["services"][name] = load(name, pl)
    return results


def uninstall(remove_apps=True):
    for label in labels().values():
        unload(label)
    if remove_apps:
        for app in (HELPER_APP, LAUNCHER_APP):
            if app.exists():
                shutil.rmtree(app)
