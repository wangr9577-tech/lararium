"""Path resolution must not depend on the process launch directory."""
from pathlib import Path

from app import config, external_tools


def test_configured_relative_paths_are_project_relative(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert config._configured_path("backend/data") == config.REPO_ROOT / "backend" / "data"
    assert config._configured_path(str(tmp_path)) == tmp_path
    assert config._configured_path("~/workspace") == Path.home() / "workspace"


def test_tool_override_with_spaces_and_missing_file(monkeypatch, tmp_path):
    tool = tmp_path / "tools with spaces" / "xelatex"
    tool.parent.mkdir()
    tool.write_text("", encoding="utf-8")
    monkeypatch.setenv("KRUSKAL_XELATEX", str(tool))
    assert external_tools.xelatex() == str(tool.resolve())
    monkeypatch.setenv("KRUSKAL_XELATEX", str(tmp_path / "missing"))
    assert external_tools.xelatex() is None


def test_tool_lookup_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("KRUSKAL_PANDOC", raising=False)
    monkeypatch.setattr(external_tools.shutil, "which", lambda name: "on-path" if name == "pandoc" else None)
    monkeypatch.setattr(external_tools.sys, "executable", "nonexistent/python")
    assert external_tools.pandoc() == "on-path"
