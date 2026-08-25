"""Общая подготовка тестов: путь к пакету + временные домашние каталоги."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """Изолированный домашний каталог профиля для каждого теста."""
    from agent_core import home as home_mod

    home_dir = tmp_path / "home"
    monkeypatch.setenv(home_mod.ENV_HOME, str(home_dir))
    monkeypatch.setenv(home_mod.ENV_PROFILE, "test")
    home_mod.reset_cache()
    yield home_dir
    home_mod.reset_cache()
