"""Тесты фундамента: профиль, конфигурация, время, логирование."""

from __future__ import annotations

from datetime import datetime

from prokop import home as home_mod
from prokop.config import Config, load_config, save_config, config_path
from prokop.timeutil import now, reset_cache
from prokop.logging_setup import configure, get_logger


def test_home_resolves_profile(home):
    assert home_mod.home_dir() == home / "test"
    assert home_mod.resolve("a", "b") == home / "test" / "a" / "b"


def test_home_switch_profile(home, monkeypatch):
    monkeypatch.setenv(home_mod.ENV_PROFILE, "second")
    home_mod.reset_cache()
    assert home_mod.profile_name() == "second"
    assert home_mod.home_dir().name == "second"


def test_config_roundtrip(home):
    config = Config()
    config.model.provider = "openai-compatible"
    config.model.model = "gpt-test"
    config.memory.provider = "builtin"
    config.toolsets.enabled = ["core", "coding"]
    config.auxiliary["compression"] = __import__(
        "prokop.config", fromlist=["AuxiliaryModelConfig"]
    ).AuxiliaryModelConfig(model="aux-model", timeout=10.0)
    save_config(config, home)
    loaded = load_config(home)
    assert loaded.model.provider == "openai-compatible"
    assert loaded.toolsets.enabled == ["core", "coding"]
    assert loaded.aux("compression").model == "aux-model"
    assert loaded.aux("vision").model is None


def test_config_missing_file_defaults(home):
    loaded = load_config(home)
    assert loaded.model.provider is None


def test_now_is_timezone_aware(home):
    reset_cache()
    value = now("UTC")
    assert value.tzinfo is not None


def test_logger_namespaced():
    configure(level="WARNING")
    logger = get_logger("tools")
    assert logger.name == "prokop.tools"
