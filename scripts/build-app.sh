#!/usr/bin/env bash
# Builds the self-contained build/Timetrace.app (Apple Silicon) and zips it into dist/.
# The bundle holds a relocatable CPython (python-build-standalone, via uv), timetrace and the pinned
# iPhone/iPad Screen Time importer, so users need nothing but ActivityWatch. Needs uv and the Command Line Tools.
set -euo pipefail
cd "$(dirname "$0")/.."

PYVER=3.12
V=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
IMPORTER=$(sed -n 's/^IMPORTER_SPEC = f"\(.*\)"$/\1/p' src/timetrace/services.py)
PIN=$(sed -n 's/^IMPORTER_PIN = "\([0-9a-f]*\)".*/\1/p' src/timetrace/services.py)
IMPORTER=${IMPORTER/\{IMPORTER_PIN\}/$PIN}
[ "$(uname -m)" = arm64 ] || { echo "build on Apple Silicon" >&2; exit 1; }

APP=build/Timetrace.app
C=$APP/Contents
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
rm -rf "$APP" && mkdir -p "$C/MacOS" "$C/Resources" dist

echo "==> Python $PYVER"
UV_PYTHON_INSTALL_DIR="$WORK/py" uv python install "$PYVER" --no-bin >/dev/null
SRC=$(find "$WORK/py" -maxdepth 1 -type d -name "cpython-$PYVER.*-macos-aarch64-none" | head -1)
ditto "$SRC" "$C/Resources/python"
PYDIR=$C/Resources/python
PY=$PYDIR/bin/python$PYVER

echo "==> timetrace $V + importer"
uv pip install --quiet --python "$PY" --break-system-packages --no-cache . "$IMPORTER"

echo "==> trim"
LIB=$PYDIR/lib/python$PYVER
rm -rf "$LIB"/{test,idlelib,tkinter,turtledemo,ensurepip,lib2to3,pydoc_data} "$LIB"/config-* \
       "$PYDIR"/include "$PYDIR"/share "$PYDIR"/lib/{tcl,tk,itcl,thread}* "$PYDIR"/lib/*.a "$PYDIR"/lib/lib*.dylib "$PYDIR"/lib/pkgconfig "$LIB"/site-packages/pip* \
       "$LIB"/lib-dynload/_tkinter*
find "$PYDIR/bin" -mindepth 1 ! -name "python3" ! -name "python$PYVER" -delete
find "$PYDIR" -name __pycache__ -type d -prune -exec rm -rf {} +
"$PY" -m compileall -q -j0 "$LIB" >/dev/null   # ship bytecode so nothing writes into the signed bundle

# console scripts with relative paths (pip's shebangs point at the build machine)
for pair in "timetrace:timetrace.cli" "timetrace-mcp:timetrace.mcp"; do
  name=${pair%%:*} mod=${pair#*:}
  printf '#!/bin/sh\nexec "$(dirname "$(readlink -f "$0")")/python3" -m %s "$@"\n' "$mod" > "$PYDIR/bin/$name"
  chmod 755 "$PYDIR/bin/$name"
done

echo "==> bundle"
clang -O2 -arch arm64 -mmacosx-version-min=12.0 macapp/launcher.c -o "$C/MacOS/Timetrace"
cp src/timetrace/helper/AppIcon.icns "$C/Resources/AppIcon.icns"
for loc in zh_CN zh-Hans zh_TW zh-Hant; do
  mkdir -p "$C/Resources/$loc.lproj"
  printf 'CFBundleDisplayName = "时间看板";\nCFBundleName = "时间看板";\n' | iconv -f UTF-8 -t UTF-16 > "$C/Resources/$loc.lproj/InfoPlist.strings"
done
cat > "$C/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Timetrace</string>
  <key>CFBundleDisplayName</key><string>Timetrace</string>
  <key>CFBundleIdentifier</key><string>com.github.vvyssen.timetrace</string>
  <key>CFBundleExecutable</key><string>Timetrace</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$V</string>
  <key>CFBundleVersion</key><string>$V</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSArchitecturePriority</key><array><string>arm64</string></array>
  <key>LSHasLocalizedDisplayName</key><true/>
  <key>LSUIElement</key><true/>
  <key>NSHumanReadableCopyright</key><string>MIT · github.com/vvyssen/timetrace</string>
</dict>
</plist>
PLIST
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

ZIP=dist/Timetrace-$V-arm64.zip
rm -f "$ZIP" && ditto -c -k --sequesterRsrc --keepParent "$APP" "$ZIP"
echo "Built $APP ($(du -sh "$APP" | cut -f1)) → $ZIP ($(du -h "$ZIP" | cut -f1))"
