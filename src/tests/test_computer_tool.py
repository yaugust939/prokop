"""Тесты диспетчера computer_use на мок-бэкенде."""

from __future__ import annotations

import asyncio
import json

import pytest

from prokop.computer.backend import ActionResult, CaptureResult, UIElement
from prokop.computer import tool as tool_mod
from prokop.computer.tool import handle_computer_use


class FakeBackend:
    """Минимальный мок-бэкенд, фиксирующий вызовы."""

    name = "fake"

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.capture_result = CaptureResult(
            image=b"\x89PNG\r\n\x1a\nfakepng",
            mode="som",
            elements=[UIElement(index=1, name="Кнопка", control_type="Button",
                                rect=(10, 20, 100, 30))],
        )

    async def capture(self, **kwargs):
        self.calls.append(("capture", kwargs))
        return self.capture_result

    async def click(self, **kwargs):
        self.calls.append(("click", kwargs))
        return ActionResult(description="click ok")

    async def double_click(self, **kwargs):
        self.calls.append(("double_click", kwargs))
        return ActionResult(description="dbl ok")

    async def right_click(self, **kwargs):
        self.calls.append(("right_click", kwargs))
        return ActionResult(description="right ok")

    async def middle_click(self, **kwargs):
        self.calls.append(("middle_click", kwargs))
        return ActionResult(description="middle ok")

    async def drag(self, **kwargs):
        self.calls.append(("drag", kwargs))
        return ActionResult(description="drag ok")

    async def scroll(self, **kwargs):
        self.calls.append(("scroll", kwargs))
        return ActionResult(description="scroll ok")

    async def type_text(self, **kwargs):
        self.calls.append(("type", kwargs))
        return ActionResult(description="typed")

    async def key(self, **kwargs):
        self.calls.append(("key", kwargs))
        return ActionResult(description="key ok")

    async def set_value(self, **kwargs):
        self.calls.append(("set_value", kwargs))
        return ActionResult(description="set ok")

    async def wait(self, **kwargs):
        self.calls.append(("wait", kwargs))
        return ActionResult(description="waited")

    async def list_apps(self):
        self.calls.append(("list_apps", {}))
        return [{"title": "App1", "pid": 42}]

    async def list_windows(self):
        self.calls.append(("list_windows", {}))
        return [{"title": "Win1", "pid": 42}]

    async def focus_app(self, **kwargs):
        self.calls.append(("focus_app", kwargs))
        return ActionResult(description="focus ok")


@pytest.fixture()
def fake(monkeypatch):
    backend = FakeBackend()
    monkeypatch.setattr(tool_mod, "get_backend", lambda: backend)
    return backend


def test_capture_returns_multimodal(fake):
    result = asyncio.run(handle_computer_use("capture", mode="som", max_elements=100))
    assert isinstance(result, dict)
    assert result["_multimodal"] is True
    assert result["text_summary"]
    types = [block["type"] for block in result["content"]]
    assert "image_url" in types


def test_capture_respects_max_elements(fake):
    fake.capture_result.elements = [
        UIElement(index=i, name=f"E{i}", control_type="Text") for i in range(1, 51)
    ]
    result = asyncio.run(handle_computer_use("capture", mode="ax", max_elements=10))
    assert result["_multimodal"] is True
    assert "показано 10" in result["text_summary"]


def test_actions_return_json(fake):
    cases = [
        ("click", {"element": 1}, "click ok"),
        ("double_click", {"element": 1}, "dbl ok"),
        ("right_click", {"element": 1}, "right ok"),
        ("middle_click", {"element": 1}, "middle ok"),
        ("scroll", {"direction": "down", "amount": 3}, "scroll ok"),
        ("type", {"text": "привет"}, "typed"),
        ("key", {"keys": "ctrl+s"}, "key ok"),
        ("set_value", {"element": 2, "value": "Blue"}, "set ok"),
        ("focus_app", {"app": "Notepad"}, "focus ok"),
    ]
    for action, args, desc in cases:
        out = asyncio.run(handle_computer_use(action, **args))
        payload = json.loads(out)
        assert payload["ok"] is True, (action, out)
        assert payload["description"] == desc, action


def test_drag_and_wait(fake):
    out = asyncio.run(handle_computer_use(
        "drag", from_element=1, to_element=2, from_coordinate=[0, 0], to_coordinate=[5, 5]
    ))
    assert json.loads(out)["ok"] is True
    out = asyncio.run(handle_computer_use("wait", seconds=0))
    assert json.loads(out)["ok"] is True


def test_list_apps_and_windows(fake):
    out = json.loads(asyncio.run(handle_computer_use("list_apps")))
    assert out["ok"] is True and out["apps"] == [{"title": "App1", "pid": 42}]
    out = json.loads(asyncio.run(handle_computer_use("list_windows")))
    assert out["ok"] is True and out["windows"] == [{"title": "Win1", "pid": 42}]


def test_capture_after_includes_fresh_capture(fake):
    out = asyncio.run(handle_computer_use("click", element=1, capture_after=True))
    assert isinstance(out, dict) and out["_multimodal"] is True
    assert "click ok" in out["text_summary"]


def test_unknown_action_raises(fake):
    with pytest.raises(ValueError):
        asyncio.run(handle_computer_use("fly_to_moon"))


def test_backend_unavailable_returns_error(monkeypatch):
    monkeypatch.setattr(tool_mod, "get_backend", lambda: None)
    out = json.loads(asyncio.run(handle_computer_use("click", element=1)))
    assert out["ok"] is False and "недоступен" in out["error"]


def test_backend_error_surfaced(fake, monkeypatch):
    async def boom(**kwargs):
        raise tool_mod.ComputerUseError("window not found")

    monkeypatch.setattr(fake, "click", boom)
    out = json.loads(asyncio.run(handle_computer_use("click", element=1)))
    assert out["ok"] is False and "window not found" in out["error"]
