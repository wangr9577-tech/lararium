"""Locate optional external executables without assuming an installation root."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _find(name: str, override: str, extra_dirs: tuple[Path, ...] = ()) -> str | None:
    configured = os.environ.get(override)
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
        return shutil.which(configured)

    executable = f"{name}.exe" if os.name == "nt" else name
    for directory in (Path(sys.executable).resolve().parent, *extra_dirs):
        candidate = directory / executable
        if candidate.is_file():
            return str(candidate)
    return shutil.which(name)


def pandoc() -> str | None:
    return _find("pandoc", "KRUSKAL_PANDOC")


def xelatex() -> str | None:
    tinytex = Path.home() / ".TinyTeX" / "bin"
    return _find("xelatex", "KRUSKAL_XELATEX", (
        tinytex / ("windows" if os.name == "nt" else "x86_64-linux"),
    ))
