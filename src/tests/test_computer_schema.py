"""Тесты схемы инструмента computer_use."""

from __future__ import annotations

import json

from prokop.computer.schema import (
    ACTIONS,
    COMPUTER_USE_SCHEMA,
    get_computer_use_schema,
)


def test_schema_shape_and_required_action():
    schema = get_computer_use_schema()
    assert schema["name"] == "computer_use"
    params = schema["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["action"]
    assert "action" in params["properties"]


def test_actions_enum_covers_contract():
    actions = COMPUTER_USE_SCHEMA["parameters"]["properties"]["action"]["enum"]
    for expected in (
        "capture", "click", "double_click", "right_click", "middle_click",
        "drag", "scroll", "type", "key", "set_value", "wait",
        "list_apps", "list_windows", "focus_app",
    ):
        assert expected in actions, expected
    assert set(actions) == set(ACTIONS)


def test_capture_modes_and_limits():
    props = COMPUTER_USE_SCHEMA["parameters"]["properties"]
    assert props["mode"]["enum"] == ["som", "vision", "ax"]
    assert props["max_elements"]["default"] == 100
    assert props["max_elements"]["maximum"] == 1000


def test_delivery_modes_and_button_enum():
    props = COMPUTER_USE_SCHEMA["parameters"]["properties"]
    assert props["delivery_mode"]["enum"] == ["background", "foreground"]
    assert props["button"]["enum"] == ["left", "right", "middle"]


def test_schema_is_json_serializable():
    json.dumps(COMPUTER_USE_SCHEMA, ensure_ascii=False)
