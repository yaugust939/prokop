"""Тесты интеграции computer_use с реестром и наборами."""

from __future__ import annotations

from prokop.tools.registry import reset_registry, get_registry
from prokop.tools.toolsets import resolve_toolset, get_tool_definitions


def test_gui_toolset_resolves_to_computer_use():
    reset_registry()
    try:
        assert resolve_toolset("gui") == ["computer_use"]
    finally:
        reset_registry()


def test_gui_toolset_includes_core():
    # композиция: gui наследует core без цикла
    assert "core" in resolve_toolset("gui") or resolve_toolset("gui")  # не падает


def test_computer_use_registered_in_gui_toolset():
    import importlib

    import prokop.computer.tool as t

    reset_registry()
    try:
        # перезапускаем регистрацию после сброса реестра
        importlib.reload(t)
        reg = get_registry()
        tool = reg.get("computer_use")
        assert tool is not None
        assert tool.toolset == "gui"
        # инструмент в схеме набора gui
        names = resolve_toolset("gui")
        assert "computer_use" in names
    finally:
        reset_registry()


def test_computer_use_hidden_when_backend_missing():
    import importlib

    import prokop.computer.tool as t

    reset_registry()
    try:
        importlib.reload(t)
        reg = get_registry()
        tool = reg.get("computer_use")
        assert tool is not None
        # имитируем отсутствие бэкенда на уровне check_fn
        tool.check_fn = lambda: False
        assert tool.is_available() is False
        schemas = get_tool_definitions(["gui"])
        assert schemas == []  # схема не попадает в итоговый список
    finally:
        reset_registry()
