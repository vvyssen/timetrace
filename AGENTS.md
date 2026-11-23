# timetrace

Python package in `src/timetrace` (CLI `cli.py`, MCP server `mcp.py`, dashboard `dashboard/`, launchd services and helper apps `services.py`). Tests: `uv run --python 3.12 --extra test pytest -q`. Keep `README.md` and `README.zh-CN.md` in sync.

There are two ways to install it, and both must keep working:
- **Timetrace.app** (`scripts/build-app.sh`, `macapp/launcher.c`, `src/timetrace/macapp.py`): a bundled CPython 3.12, timetrace, and the pinned Screen Time importer, for Apple Silicon. `paths.BUNDLE` / `paths.BUNDLE_BIN` are set when running from it. Its launchd services and MCP command then point into the bundle, and no separate launcher app is built.
- **install.sh**: uv tool install, any Mac.

Never run `timetrace install`, or open a built Timetrace.app, on the user's own Mac just to test something. Both re-point the user's real launchd services. Test the bundle by running its `Contents/Resources/python/bin/*` directly, with `TIMETRACE_HOME` set to a temp dir and a spare `port` in its `settings.json`.

## Releasing

A release is a `vX.Y.Z` tag on `main`. Pushing it runs `.github/workflows/release.yml`, which tests, builds `Timetrace-X.Y.Z-arm64.zip` plus the wheel and sdist, smoke-tests the bundle, and publishes the GitHub release with the tag message as its notes. Don't build or upload releases by hand.

```sh
scripts/release.sh status                    # version, last tag, commits since then
scripts/release.sh patch --yes -F notes.md   # or minor / major / X.Y.Z; -m "…" for short notes
gh run watch "$(gh run list -w release -L1 --json databaseId -q '.[0].databaseId')"
gh release view vX.Y.Z
```

The script refuses to run unless you're on `main`, the tracked tree is clean, and `main` isn't behind `origin`. It bumps `pyproject.toml` and `src/timetrace/__init__.py`, runs the tests and `build-app.sh` as a preflight, commits `Release vX.Y.Z`, makes an annotated tag, and pushes both.

**When to release (agents can decide this themselves):**
- Release when `status` shows user-visible changes (dashboard, classification, CLI/MCP, services) that are committed, pass the tests, and have been tried against real data. Don't release in the middle of a change, or for refactors, docs, or CI-only changes. Only release what is on `main`; work on other branches has to be merged first.
- Versions: `patch` for fixes, `minor` for new features, `major` only if the user asks. While the version is below 1.0, a breaking change to `config.yaml` or the CLI is `minor`, and the notes must say what to do.
- Notes: write them for users, in English and then Chinese, one line per change. Don't paste commit subjects. Then tell the user the version and the release link.
- If the workflow fails, fix it on `main`, then re-run it for the same tag: `gh workflow run release -f tag=vX.Y.Z`. Only make a new patch release if the app itself needs a fix.
- If you change the importer pin (`IMPORTER_PIN` in `services.py`), that's a release-worthy change: the app bundles that exact importer.

The app is ad-hoc signed and not notarized (there's no Developer ID). Users clear the quarantine flag once (the release notes and README explain how), and the app clears it again on every launch so launchd can run the bundled Python.
