"""Сценарии спеки computer-use (spec.md) через мок-бэкенд."""

from __future__ import annotations

import asyncio
import json

import pytest

from prokop.computer.backend import ActionResult, CaptureResult, UIElement
from prokop.computer import tool as tool_mod
from prokop.computer.tool import handle_computer_use


class RecordingBackend:
    """Мок, фиксирующий параметры вызовов для проверки сценариев."""

    name = "recording"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    async def capture(self, **kwargs):
        self.calls.append(("capture", kwargs))
        return CaptureResult(
            image=b"\x89PNG\r\n\x1a\nimg",
            mode=kwargs.get("mode", "som"),
            elements=[UIElement(index=1, name="Поле", control_type="Edit",
                                rect=(5, 5, 80, 20))],
        )

    async def click(self, **kwargs):
        self.calls.append(("click", kwargs))
        return ActionResult(description="ok")

    async def scroll(self, **kwargs):
        self.calls.append(("scroll", kwargs))
        return ActionResult(description="ok")

    async def type_text(self, **kwargs):
        self.calls.append(("type", kwargs))
        return ActionResult(description="ok")

    async def focus_app(self, **kwargs):
        self.calls.append(("focus_app", kwargs))
        return ActionResult(description="ok")

    async def set_value(self, **kwargs):
        self.calls.append(("set_value", kwargs))
        return ActionResult(description="ok")

    async def list_windows(self):
        self.calls.append(("list_windows", {}))
        return [{"title": "Окно", "pid": 1}]

    async def list_apps(self):
        return [{"title": "App", "pid": 1}]

    async def wait(self, **kwargs):
        self.calls.append(("wait", kwargs))
        return ActionResult(description="ok")

    async def drag(self, **kwargs):
        self.calls.append(("drag", kwargs))
        return ActionResult(description="ok")


@pytest.fixture()
def rec(monkeypatch):
    backend = RecordingBackend()
    monkeypatch.setattr(tool_mod, "get_backend", lambda: backend)
    return backend


def test_som_capture_passes_mode_and_app(rec):
    asyncio.run(handle_computer_use("capture", mode="som", app="Notepad"))
    call = dict(rec.calls[0][1])
    assert call["mode"] == "som" and call["app"] == "Notepad"


def test_vision_capture_no_tree(rec):
    result = asyncio.run(handle_computer_use("capture", mode="vision"))
    assert result["_multimodal"] is True


def test_click_targets_element(rec):
    asyncio.run(handle_computer_use("click", element=3))
    call = dict(rec.calls[0][1])
    assert call["element"] == 3


def test_click_targets_coordinate(rec):
    asyncio.run(handle_computer_use("click", coordinate=[120, 40]))
    call = dict(rec.calls[0][1])
    assert call["coordinate"] == [120, 40]


def test_scroll_direction_and_amount(rec):
    asyncio.run(handle_computer_use("scroll", direction="down", amount=5))
    call = dict(rec.calls[0][1])
    assert call["direction"] == "down" and call["amount"] == 5


def test_type_passes_text(rec):
    asyncio.run(handle_computer_use("type", text="текст"))
    assert dict(rec.calls[0][1])["text"] == "текст"


def test_delivery_mode_background_default(rec):
    asyncio.run(handle_computer_use("click", element=1))
    assert dict(rec.calls[0][1]).get("delivery_mode", "background") == "background"


def test_delivery_mode_foreground_passed(rec):
    asyncio.run(handle_computer_use("click", element=1, delivery_mode="foreground"))
    assert dict(rec.calls[0][1])["delivery_mode"] == "foreground"


def test_focus_app_raise_window(rec):
    asyncio.run(handle_computer_use("focus_app", app="Calc", raise_window=True))
    call = dict(rec.calls[0][1])
    assert call["app"] == "Calc" and call["raise_window"] is True


def test_set_value_for_select(rec):
    asyncio.run(handle_computer_use("set_value", element=4, value="Blue"))
    call = dict(rec.calls[0][1])
    assert call["element"] == 4 and call["value"] == "Blue"


def test_max_elements_cap(rec, monkeypatch):
    async def many_capture(**kwargs):
        return CaptureResult(
            image=b"x",
            mode=kwargs.get("mode", "ax"),
            elements=[UIElement(index=i, name=f"E{i}", control_type="Text")
                      for i in range(1, 120)],
        )

    monkeypatch.setattr(rec, "capture", many_capture)
    result = asyncio.run(handle_computer_use("capture", mode="ax", max_elements=20))
    assert "показано 20" in result["text_summary"]
    assert "всего 119" in result["text_summary"]


def test_capture_after_fresh_snapshot(rec):
    result = asyncio.run(handle_computer_use("click", element=1, capture_after=True))
    assert result["_multimodal"] is True
    # после действия выполнен повторный захват
    actions = [name for name, _ in rec.calls]
    assert actions == ["click", "capture"]


def test_unknown_action_reports_valid_list(rec):
    with pytest.raises(ValueError) as exc:
        asyncio.run(handle_computer_use("nope"))
    assert "capture" in str(exc.value) and "click" in str(exc.value)
