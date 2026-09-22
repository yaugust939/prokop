"""Тесты бэкенда cua-driver.

Демон подменяется локальной заглушкой (`tests/cua_stub_driver.py`), поэтому
тесты полностью локальны и не требуют установленного cua-driver. Заглушка
намеренно не поддерживает рукопожатие MCP — значит успешный захват доказывает,
что бэкенд общается с демоном сырыми вызовами, как и раньше.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from prokop.computer.backend import ComputerUseError
from prokop.computer.cua import CuaBackend

STUB = Path(__file__).resolve().parent / "cua_stub_driver.py"


def make_backend(**kwargs) -> CuaBackend:
    return CuaBackend(binary=sys.executable, args=[str(STUB), "stdio"], **kwargs)


def run(coro):
    return asyncio.run(coro)


# --- доступность ----------------------------------------------------------


def test_available_false_when_binary_missing(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert CuaBackend.available() is False


def test_start_with_missing_binary_raises():
    async def scenario():
        backend = CuaBackend(binary="definitely-not-a-real-cua-driver")
        try:
            await backend.capture()
        finally:
            await backend.close()

    with pytest.raises(ComputerUseError) as exc:
        run(scenario())
    assert "cua-driver" in str(exc.value)


# --- захват ---------------------------------------------------------------


def test_capture_decodes_image_and_elements():
    async def scenario():
        backend = make_backend()
        try:
            return await backend.capture(mode="som", max_elements=50)
        finally:
            await backend.close()

    result = run(scenario())
    assert result.image is not None
    assert result.image.startswith(b"\x89PNG")
    assert [el.name for el in result.elements] == ["Кнопка", "Поле"]
    assert result.elements[0].rect == (0, 0, 10, 10)
    assert result.elements[0].control_type == "Button"


def test_capture_does_not_perform_handshake():
    """Заглушка отвергает `initialize` — значит захват идёт без рукопожатия."""

    async def scenario():
        backend = make_backend()
        try:
            return await backend._rpc("initialize", {})
        finally:
            await backend.close()

    with pytest.raises(ComputerUseError) as exc:
        run(scenario())
    assert "не поддержан" in str(exc.value)


def test_capture_protocol_error_is_wrapped():
    async def scenario():
        backend = make_backend()
        try:
            return await backend._call_tool("boom", {})
        finally:
            await backend.close()

    with pytest.raises(ComputerUseError) as exc:
        run(scenario())
    assert "внутренняя ошибка демона" in str(exc.value)


def test_capture_timeout_is_wrapped():
    async def scenario():
        backend = CuaBackend(
            binary=sys.executable,
            args=[str(STUB), "stdio", "--silent"],
            timeout=0.6,
        )
        try:
            return await backend.capture()
        finally:
            await backend.close()

    with pytest.raises(ComputerUseError) as exc:
        run(scenario())
    assert "таймаут" in str(exc.value)


# --- действия -------------------------------------------------------------


def test_click_returns_description():
    async def scenario():
        backend = make_backend()
        try:
            return await backend.click(element=1, button="left")
        finally:
            await backend.close()

    result = run(scenario())
    assert result.ok is True
    assert result.description == "click ok"


def test_action_reports_driver_error():
    async def scenario():
        backend = make_backend()
        try:
            return await backend._action("broken")
        finally:
            await backend.close()

    result = run(scenario())
    assert result.ok is False
    assert result.error == "демон отказал"


@pytest.mark.parametrize(
    "call",
    [
        lambda backend: backend.drag(from_coordinate=[0, 0], to_coordinate=[5, 5]),
        lambda backend: backend.scroll(direction="down", amount=2),
        lambda backend: backend.type_text(text="привет"),
        lambda backend: backend.key(keys="ctrl+s"),
        lambda backend: backend.set_value(element=1, value="значение"),
        lambda backend: backend.focus_app(app="Заглушка"),
    ],
)
def test_actions_succeed(call):
    async def scenario():
        backend = make_backend()
        try:
            return await call(backend)
        finally:
            await backend.close()

    result = run(scenario())
    assert result.ok is True
    assert result.description


def test_list_apps_and_windows():
    async def scenario():
        backend = make_backend()
        try:
            apps = await backend.list_apps()
            windows = await backend.list_windows()
            return apps, windows
        finally:
            await backend.close()

    apps, windows = run(scenario())
    assert apps == [{"title": "Заглушка", "pid": 4242}]
    assert windows == apps


def test_wait_is_local():
    async def scenario():
        backend = make_backend()
        return await backend.wait(seconds=0.01)

    result = run(scenario())
    assert result.ok is True
    assert "waited" in result.description


# --- жизненный цикл -------------------------------------------------------


def test_close_is_idempotent_and_reusable():
    async def scenario():
        backend = make_backend()
        first = await backend.click(element=1)
        await backend.close()
        await backend.close()
        # Повторный запуск после закрытия: клиент создаётся заново.
        second = await backend.click(element=1)
        await backend.close()
        return first, second

    first, second = run(scenario())
    assert first.ok and second.ok


def test_single_process_for_many_calls():
    """Клиент переиспользуется: демон поднимается один раз."""
    backend = make_backend()

    async def scenario():
        try:
            await backend.click(element=1)
            pid_first = backend._client._proc.pid  # type: ignore[union-attr]
            await backend.click(element=2)
            pid_second = backend._client._proc.pid  # type: ignore[union-attr]
            return pid_first, pid_second
        finally:
            await backend.close()

    pid_first, pid_second = run(scenario())
    assert pid_first == pid_second
