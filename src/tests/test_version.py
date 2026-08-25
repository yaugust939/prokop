"""Проверка синхронности версии пакета и pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

import agent_core


def test_version_matches_pyproject():
    pyproject_path = Path(agent_core.__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    assert agent_core.__version__ == data["project"]["version"]
