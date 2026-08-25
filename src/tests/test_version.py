"""Проверка синхронности версии пакета и pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

import prokop


def test_version_matches_pyproject():
    pyproject_path = Path(prokop.__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert prokop.__version__ == data["project"]["version"]
