#!/usr/bin/env bash
# Cut a release. See AGENTS.md › Releasing.
#
#   scripts/release.sh status                         what changed since the last release
#   scripts/release.sh patch|minor|major|X.Y.Z        bump, build, tag, push
#   scripts/release.sh current                        release the version already in the tree
#        [-m "notes" | -F notes.md]                   release notes (default: commit subjects since the last tag)
#        [--yes]                                      don't ask for confirmation (agents)
#
# Pushing the tag starts .github/workflows/release.yml, which builds Timetrace.app and publishes the
# GitHub release. Follow it with: gh run watch "$(gh run list -w release -L1 --json databaseId -q '.[0].databaseId')"
set -euo pipefail
cd "$(dirname "$0")/.."

# ---- repo-specific: where the version lives -----------------------------------------------------
get_version() { sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml; }
set_version() {
  sed -i '' "s/^version = \".*\"/version = \"$1\"/" pyproject.toml
  sed -i '' "s/^__version__ = \".*\"/__version__ = \"$1\"/" src/timetrace/__init__.py
}
VERSION_FILES=(pyproject.toml src/timetrace/__init__.py)
preflight() { uv run --quiet --python 3.12 --extra test pytest -q >/dev/null && bash -n install.sh && ./scripts/build-app.sh >/dev/null; }
# --------------------------------------------------------------------------------------------------

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
last_tag() { git describe --tags --abbrev=0 --match 'v[0-9]*' 2>/dev/null || true; }

status() {
  git fetch -q --tags origin 2>/dev/null || true
  local tag; tag=$(last_tag)
  echo "version in tree: $(get_version)"
  echo "last release:    ${tag:-none}"
  local range=${tag:+$tag..}HEAD
  local n; n=$(git rev-list --count "$range")
  echo "commits since:   $n"
  git log --format='  - %s (%h)' "$range"
  [ "$n" -gt 0 ] && [ -n "$tag" ] && { echo "files changed:"; git diff --stat ${tag:+"$tag"} HEAD | tail -1; } || true
  git diff --quiet HEAD || echo "note: uncommitted changes in the working tree"
}

bump() {  # bump <current> <patch|minor|major|X.Y.Z>
  local IFS=.; read -r ma mi pa <<<"$1"
  case $2 in
    patch) echo "$ma.$mi.$((pa + 1))" ;;
    minor) echo "$ma.$((mi + 1)).0" ;;
    major) echo "$((ma + 1)).0.0" ;;
    [0-9]*.[0-9]*.[0-9]*) echo "$2" ;;
    *) die "expected patch, minor, major or X.Y.Z, got '$2'" ;;
  esac
}

release() {
  local kind=$1; shift
  local notes="" yes=0
  while [ $# -gt 0 ]; do
    case $1 in
      -m) notes=$2; shift 2 ;;
      -F) notes=$(cat "$2"); shift 2 ;;
      --yes|-y) yes=1; shift ;;
      *) die "unknown option $1" ;;
    esac
  done
  [ "$(git branch --show-current)" = main ] || die "release from main"
  git diff --quiet HEAD || die "commit or discard tracked changes first"
  git fetch -q --tags origin
  [ "$(git rev-list --count HEAD..origin/main)" = 0 ] || die "main is behind origin/main; pull first"

  local cur tag new; cur=$(get_version); tag=$(last_tag)
  if [ "$kind" = current ]; then new=$cur; else new=$(bump "$cur" "$kind"); fi  # current: ship the version in the tree as is
  git rev-parse -q --verify "refs/tags/v$new" >/dev/null && die "v$new already exists"
  [ -n "$notes" ] || notes=$(git log --format='- %s' ${tag:+"$tag"..}HEAD)
  [ -n "$notes" ] || die "nothing to release since $tag"

  printf 'Release v%s (was %s, last tag %s)\n\n%s\n\n' "$new" "$cur" "${tag:-none}" "$notes"
  if [ $yes = 0 ]; then read -r -p "Proceed? [y/N] " a; [ "$a" = y ] || exit 1; fi

  [ "$new" = "$cur" ] || set_version "$new"
  echo "preflight build/tests…"; preflight
  if ! git diff --quiet HEAD; then git add "${VERSION_FILES[@]}"; git commit -q -m "Release v$new"; fi
  git tag -a "v$new" -m "v$new" -m "$notes"
  git push -q origin main "v$new"
  echo "pushed v$new — CI is building the release:"
  echo "  gh run list -w release -L1    then    gh release view v$new"
}

case ${1:-status} in
  status) status ;;
  -h|--help|help) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) release "$@" ;;
esac
