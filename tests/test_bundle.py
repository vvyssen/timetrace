"""Running from the self-contained Timetrace.app: the services and MCP command must use the bundled Python."""
import importlib
import sys

import pytest


@pytest.fixture()
def bundled(tmp_path, monkeypatch):
    app = tmp_path / "Some Folder" / "Timetrace.app"
    py = app / "Contents" / "Resources" / "python" / "bin" / "python3"
    py.parent.mkdir(parents=True)
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "Timetrace").touch()
    monkeypatch.setenv("TIMETRACE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys, "executable", str(py))
    import timetrace.paths as paths
    importlib.reload(paths)
    yield app, py
    monkeypatch.undo()
    importlib.reload(paths)


def test_bundle_detected(bundled):
    app, py = bundled
    from timetrace import agents, paths, services
    assert paths.BUNDLE == app and paths.BUNDLE_BIN == py.parent
    assert services.importer_cmd() == [str(py), "-m", "aw_import_screentime"]
    assert services.plists()["dashboard"]["ProgramArguments"][0] == str(py)
    assert agents.mcp_command() == str(py.parent / "timetrace-mcp")


def test_not_bundled_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv" / "bin" / "python3"))
    import timetrace.paths as paths
    importlib.reload(paths)
    try:
        assert paths.BUNDLE is None and paths.BUNDLE_BIN is None
    finally:
        monkeypatch.undo()
        importlib.reload(paths)
