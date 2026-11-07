#!/usr/bin/env bash
# timetrace installer
#   curl -fsSL https://raw.githubusercontent.com/vvyssen/timetrace/main/install.sh | bash
#
# Installs: uv (if missing) · ActivityWatch (via Homebrew if missing) · timetrace · the iPhone/iPad
# Screen Time importer · two small apps in ~/Applications · two background services. Re-running is safe.
set -euo pipefail

REPO="${TIMETRACE_REPO:-vvyssen/timetrace}"
REF="${TIMETRACE_REF:-main}"
SOURCE="${TIMETRACE_SOURCE:-git+https://github.com/${REPO}@${REF}}"   # or a local checkout path
IMPORTER="git+https://github.com/ActivityWatch/aw-import-screentime@1297039793819b25f926289fb033d77c66786c50"
PY="3.12"

LANG_UI=en
if defaults read -g AppleLanguages 2>/dev/null | sed -n 2p | grep -qi '"\{0,1\}zh'; then LANG_UI=zh; fi
say() { if [ "$LANG_UI" = zh ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$(say "$1" "$2")"; }

[ "$(uname -s)" = "Darwin" ] || { say "timetrace 只支持 macOS。" "timetrace runs on macOS only."; exit 1; }

step "检查 uv（Python 工具管理器）" "Checking uv (Python tool manager)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version

step "检查 ActivityWatch" "Checking ActivityWatch"
if [ -d "/Applications/ActivityWatch.app" ] || [ -d "$HOME/Applications/ActivityWatch.app" ]; then
  say "已安装。" "Already installed."
elif command -v brew >/dev/null 2>&1; then
  brew install --cask activitywatch
else
  say "没有找到 ActivityWatch，也没有 Homebrew。请先从 https://activitywatch.net/downloads/ 安装 ActivityWatch，然后重新运行这个脚本。" \
      "ActivityWatch is not installed and Homebrew is not available. Install ActivityWatch from https://activitywatch.net/downloads/, then run this script again."
  open "https://activitywatch.net/downloads/" || true
  exit 1
fi
open -g -a ActivityWatch || true

step "安装 timetrace 和 iPhone/iPad 导入器" "Installing timetrace and the iPhone/iPad importer"
uv tool install --force --reinstall --python "$PY" "$SOURCE"   # --reinstall: never reuse a stale build of the same version
uv tool install --force --python "$PY" "$IMPORTER"

step "安装后台服务和应用" "Installing background services and apps"
if [ "$LANG_UI" = zh ]; then timetrace install --lang zh; else timetrace install; fi

step "还差一步：授予完全磁盘访问权限" "One more step: grant Full Disk Access"
say "iPhone/iPad 的屏幕使用时间数据在受保护的目录里。请在刚打开的「完全磁盘访问权限」设置中点 +，选中访达里高亮的「Timetrace Importer」，并打开开关。授权后约 30 秒内自动开始导入。
iPhone/iPad 上还需要打开：设置 › 屏幕使用时间 › 跨设备共享（Mac 上同样打开）。" \
    "Screen Time data from your iPhone/iPad lives in a protected folder. In the Full Disk Access settings that just opened, click +, choose the highlighted “Timetrace Importer” and turn it on. Importing starts within about 30 seconds.
Also turn on Settings › Screen Time › Share Across Devices on your iPhone/iPad (and on the Mac)."
open "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles" || true
open -R "$HOME/Applications/Timetrace Importer.app" || true

PORT="${TIMETRACE_PORT:-27181}"
for _ in 1 2 3 4 5 6 7 8 9 10; do curl -fsS "http://127.0.0.1:${PORT}/api/meta" >/dev/null 2>&1 && break; sleep 1; done
open "http://127.0.0.1:${PORT}/#setup" || true

step "完成" "Done"
say "· 看板：Spotlight 搜「时间看板」或「Timetrace」，或运行 timetrace dash
· 命令行：timetrace summary --since 7d    · 自检：timetrace doctor
· 连接 AI Agent（Claude Code / Codex / opencode）：timetrace agent install
· 如果提示找不到 timetrace 命令：运行 uv tool update-shell 后重开终端" \
    "· Dashboard: search “Timetrace” in Spotlight, or run timetrace dash
· CLI: timetrace summary --since 7d    · Self-check: timetrace doctor
· Connect AI agents (Claude Code / Codex / opencode): timetrace agent install
· If the timetrace command is not found: run uv tool update-shell and reopen the terminal"
