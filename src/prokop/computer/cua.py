"""Бэкенд cua-driver: фоновое управление десктопом через MCP-демон.

``cua-driver`` — демон компьютерного управления (macOS/Windows/Linux),
общающийся по MCP over stdio. Этот бэкенд — лёгкий JSON-RPC 2.0 клиент без
зависимости от MCP SDK: стартует демон, вызывает его инструменты и не
перехватывает курсор пользователя (ввод доставляется в фоне).

Если демон не установлен или не отвечает — ``available()`` вернёт false,
а вызовы — честную ошибку.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
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

log = get_logger("computer.cua")

#: Имя бинарника демона в PATH.
DRIVER_BINARY = "cua-driver"
#: Аргументы запуска демона.
DRIVER_ARGS = ["stdio"]


class CuaBackend(ComputerUseBackend):
    """MCP-клиент к cua-driver через stdio."""

    name = "cua"

    def __init__(self, binary: str | None = None, args: Optional[list[str]] = None) -> None:
        self._binary = binary or shutil.which(DRIVER_BINARY)
        self._args = args if args is not None else list(DRIVER_ARGS)
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._req_id = 0
        self._lock = asyncio.Lock()

    @classmethod
    def available(cls) -> bool:
        return bool(shutil.which(DRIVER_BINARY))

    # ── запуск / JSON-RPC ─────────────────────────────────────────

    async def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        if not self._binary:
            raise ComputerUseError(
                f"{DRIVER_BINARY} не найден в PATH. Установите cua-driver."
            )
        self._proc = subprocess.Popen(
            [self._binary, *self._args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**os.environ},
        )
        await asyncio.sleep(0.05)

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        await self._ensure_started()
        assert self._proc and self._proc.stdin and self._proc.stdout
        self._req_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method,
            "params": params,
        }
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"
        try:
            async with self._lock:
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
                line = self._proc.stdout.readline()
        except Exception as exc:  # noqa: BLE001
            raise ComputerUseError(f"cua-driver: {exc}") from exc
        if not line:
            raise ComputerUseError("cua-driver завершился без ответа")
        try:
            response = json.loads(line.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise ComputerUseError(f"cua-driver: невалидный JSON: {line[:200]!r}") from exc
        if response.get("id") != self._req_id:
            raise ComputerUseError("cua-driver: несовпадение id ответа")
        if "error" in response and response["error"]:
            raise ComputerUseError(f"cua-driver: {response['error']}")
        result = response.get("result")
        if isinstance(result, dict) and "content" in result:
            # MCP tool-result: склеиваем текстовые блоки
            parts: list[str] = []
            for block in result["content"] or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            return "\n".join(parts)
        return result

    async def _call_tool(self, name: str, args: dict[str, Any]) -> Any:
        return await self._rpc("tools/call", {"name": name, "arguments": args})

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
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        self._proc = None

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
