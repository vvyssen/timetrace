#!/usr/bin/env bash
# Packages build/Timetrace.app (from scripts/build-app.sh) into dist/Timetrace-<version>-arm64.dmg:
# the app next to an Applications shortcut, on a background with an arrow and a hint.
# Runs dmgbuild through uvx (override with DMGBUILD=/path/to/dmgbuild).
set -euo pipefail
cd "$(dirname "$0")/.."
V=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
[ -d build/Timetrace.app ] || { echo "build/Timetrace.app missing; run scripts/build-app.sh first" >&2; exit 1; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
swift dmg/make-background.swift "$tmp/bg.png" 1
swift dmg/make-background.swift "$tmp/bg@2x.png" 2
tiffutil -cathidpicheck "$tmp/bg.png" "$tmp/bg@2x.png" -out "$tmp/bg.tiff" 2>/dev/null
mkdir -p dist
DMG=dist/Timetrace-$V-arm64.dmg
rm -f "$DMG"
${DMGBUILD:-uvx dmgbuild} -s dmg/settings.py -D app=build/Timetrace.app -D background="$tmp/bg.tiff" \
  -D volume_icon=src/timetrace/helper/AppIcon.icns "Timetrace" "$DMG"
echo "Built $DMG ($(du -h "$DMG" | cut -f1))"
