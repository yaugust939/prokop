"""Бэкенд cua-driver: фоновое управление десктопом через MCP-демон.

``cua-driver`` — демон компьютерного управления (macOS/Windows/Linux),
общающийся по MCP over stdio. Транспорт берётся у общего MCP-клиента
(:mod:`prokop.mcp.client`): здесь остаётся только предметная логика —
преобразование результатов демона в модели бэкенда.

Рукопожатие MCP не выполняется: демон принимает ``tools/call`` напрямую,
поэтому используется сырой вызов метода.

Если демон не установлен или не отвечает — ``available()`` вернёт false,
а вызовы — честную ошибку.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any, Optional

from prokop.computer.backend import (
    ActionResult,
    CaptureResult,
    ComputerUseBackend,
    ComputerUseError,
    UIElement,
)
from prokop.computer.capture import make_capture_result
from prokop.logging_setup import get_logger
from prokop.mcp.client import McpClient, McpError

log = get_logger("computer.cua")

#: Имя бинарника демона в PATH.
DRIVER_BINARY = "cua-driver"
#: Аргументы запуска демона.
DRIVER_ARGS = ["stdio"]
#: Таймаут ожидания ответа демона, секунд (щедрый: операции GUI бывают долгими).
DRIVER_TIMEOUT = 120.0


class CuaBackend(ComputerUseBackend):
    """MCP-клиент к cua-driver через stdio."""

    name = "cua"

    def __init__(
        self,
        binary: str | None = None,
        args: Optional[list[str]] = None,
        timeout: float = DRIVER_TIMEOUT,
    ) -> None:
        self._binary = binary or shutil.which(DRIVER_BINARY)
        self._args = args if args is not None else list(DRIVER_ARGS)
        self._timeout = timeout
        self._client: Optional[McpClient] = None

    @classmethod
    def available(cls) -> bool:
        return bool(shutil.which(DRIVER_BINARY))

    # ── запуск / JSON-RPC ─────────────────────────────────────────

    async def _ensure_started(self) -> McpClient:
        if self._client is not None:
            return self._client
        if not self._binary:
            raise ComputerUseError(
                f"{DRIVER_BINARY} не найден в PATH. Установите cua-driver."
            )
        client = McpClient(
            DRIVER_BINARY,
            [self._binary, *self._args],
            timeout=self._timeout,
        )
        try:
            await client.start()
        except McpError as exc:
            raise ComputerUseError(f"cua-driver: {exc}") from exc
        self._client = client
        return client

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        client = await self._ensure_started()
        try:
            return await client.call_method(method, params)
        except McpError as exc:
            raise ComputerUseError(f"cua-driver: {exc}") from exc

    async def _call_tool(self, name: str, args: dict[str, Any]) -> Any:
        client = await self._ensure_started()
        try:
            return await client.call_tool_text(name, args)
        except McpError as exc:
            raise ComputerUseError(f"cua-driver: {exc}") from exc

    # ── реализация контракта ──────────────────────────────────────

    async def capture(
        self,
        *,
        mode: str = "som",
        app: Optional[str] = None,
        pid: Optional[int] = None,
        window_id: Optional[int] = None,
        max_elements: int = 100,
    ) -> CaptureResult:
        raw = await self._call_tool("capture", {
            "mode": mode,
            "app": app,
            "pid": pid,
            "window_id": window_id,
            "max_elements": max_elements,
        })
        data = self._coerce_dict(raw)
        image = data.get("image")
        if isinstance(image, str) and image.startswith("data:image"):
            import base64

            b64 = image.split(",", 1)[-1]
            image = base64.b64decode(b64)
        elements = [
            UIElement(
                index=int(el.get("index", i + 1)),
                name=str(el.get("name", "")),
                control_type=str(el.get("control_type", "")),
                role=str(el.get("role", "")),
                value=el.get("value"),
                rect=tuple(el["rect"]) if isinstance(el.get("rect"), (list, tuple)) else None,
            )
            for i, el in enumerate(data.get("elements") or [])
        ]
        result = CaptureResult(
            image=image if isinstance(image, bytes) else None,
            mode=mode,
            elements=elements,
            target=app or "",
        )
        return make_capture_result(result, max_elements=max_elements,
                                   som_overlay=False)

    async def click(
        self,
        *,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        button: str = "left",
        modifiers: Optional[list[str]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        return await self._action("click", element=element, coordinate=coordinate,
                                  button=button, modifiers=modifiers,
                                  delivery_mode=delivery_mode)

    async def drag(
        self,
        *,
        from_element: Optional[int] = None,
        to_element: Optional[int] = None,
        from_coordinate: Optional[list[int]] = None,
        to_coordinate: Optional[list[int]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        return await self._action("drag", from_element=from_element,
                                  to_element=to_element,
                                  from_coordinate=from_coordinate,
                                  to_coordinate=to_coordinate,
                                  delivery_mode=delivery_mode)

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 3,
        delivery_mode: str = "background",
    ) -> ActionResult:
        return await self._action("scroll", direction=direction, amount=amount,
                                  delivery_mode=delivery_mode)

    async def type_text(
        self,
        *,
        text: str,
        delivery_mode: str = "background",
    ) -> ActionResult:
        return await self._action("type", text=text, delivery_mode=delivery_mode)

    async def key(
        self,
        *,
        keys: str,
        delivery_mode: str = "background",
    ) -> ActionResult:
        return await self._action("key", keys=keys, delivery_mode=delivery_mode)

    async def set_value(
        self,
        *,
        element: int,
        value: str,
    ) -> ActionResult:
        return await self._action("set_value", element=element, value=value)

    async def wait(self, *, seconds: float) -> ActionResult:
        await asyncio.sleep(min(max(seconds, 0.0), 30.0))
        return ActionResult(description=f"waited {seconds}s")

    async def list_apps(self) -> list[dict[str, Any]]:
        return self._coerce_list(await self._call_tool("list_apps", {}))

    async def list_windows(self) -> list[dict[str, Any]]:
        return self._coerce_list(await self._call_tool("list_windows", {}))

    async def focus_app(
        self,
        *,
        app: str,
        raise_window: bool = False,
    ) -> ActionResult:
        return await self._action("focus_app", app=app, raise_window=raise_window)

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.close()
        except Exception as exc:  # noqa: BLE001 — закрытие не должно падать
            log.warning("cua-driver: ошибка закрытия: %s", exc)

    # ── помощники ─────────────────────────────────────────────────

    async def _action(self, name: str, **kwargs: Any) -> ActionResult:
        args = {k: v for k, v in kwargs.items() if v is not None}
        try:
            raw = await self._call_tool(name, args)
            data = self._coerce_dict(raw)
            if data.get("ok") is False or data.get("error"):
                return ActionResult(ok=False, error=str(data.get("error")))
            return ActionResult(description=str(data.get("description", name)))
        except ComputerUseError as exc:
            return ActionResult(ok=False, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    @staticmethod
    def _coerce_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
        return {}

    @staticmethod
    def _coerce_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [v for v in value if isinstance(v, dict)]
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [v for v in parsed if isinstance(v, dict)]
            except json.JSONDecodeError:
                pass
        return []
