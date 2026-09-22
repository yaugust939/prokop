"""Клиент MCP-сервера через stdio (JSON-RPC 2.0).

Запускает процесс сервера списком аргументов (без shell), обменивается
построчными JSON-сообщениями в UTF-8, выполняет рукопожатие
(``initialize`` → ``notifications/initialized``), перечисляет инструменты
(``tools/list``) и вызывает их (``tools/call``).

Зависимостей, кроме стандартной библиотеки, нет: MCP SDK не требуется.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from prokop import __version__
from prokop.logging_setup import get_logger

log = get_logger("mcp.client")

#: Версия протокола MCP, которую объявляет клиент.
PROTOCOL_VERSION = "2024-11-05"

#: Таймаут ожидания ответа по умолчанию, секунд.
DEFAULT_TIMEOUT = 30.0

#: Кодировка обмена.
ENCODING = "utf-8"


class McpError(Exception):
    """Ошибка MCP-клиента (запуск, протокол, таймаут)."""


@dataclass
class McpTool:
    """Инструмент, объявленный MCP-сервером."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


def default_schema() -> dict[str, Any]:
    """Схема входных параметров по умолчанию (объект без свойств)."""
    return {"type": "object", "properties": {}}


def _content_text(result: Any) -> str:
    """Склеенный текст контент-блоков результата ``tools/call``.

    Используется потребителями, которым нужен текст ответа (а не конверт):
    например бэкенд `cua-driver`. Результат без контент-блоков возвращается
    как JSON-строка, чтобы вызывающий код не терял данные.
    """
    if isinstance(result, dict):
        blocks = result.get("content")
        if isinstance(blocks, list):
            parts = [
                str(block.get("text", ""))
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(parts)
        return json.dumps(result, ensure_ascii=False, default=str)
    if isinstance(result, str):
        return result
    if result is None:
        return ""
    return json.dumps(result, ensure_ascii=False, default=str)


def _result_to_json(result: Any) -> str:
    """Привести результат ``tools/call`` к JSON-строке контракта ядра."""
    if not isinstance(result, dict):
        return json.dumps(
            {"content": [], "isError": False, "raw": result},
            ensure_ascii=False,
            default=str,
        )

    is_error = bool(result.get("isError"))
    texts: list[str] = []
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(str(block.get("text", "")))
        elif isinstance(block, dict):
            texts.append(json.dumps(block, ensure_ascii=False, default=str))

    payload: dict[str, Any] = {"content": texts, "isError": is_error}
    if is_error:
        payload["error"] = "\n".join(texts) or "ошибка инструмента MCP"
    return json.dumps(payload, ensure_ascii=False, default=str)


class McpClient:
    """Клиент одного MCP-сервера."""

    def __init__(
        self,
        name: str,
        command: list[str],
        *,
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not command:
            raise McpError(f"{name}: пустая команда запуска сервера")
        self.name = name
        self.command = list(command)
        self.env = dict(env or {})
        self.cwd = cwd
        self.timeout = float(timeout)
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._req_id = 0
        self._lock = asyncio.Lock()
        self._closed = False

    # ── процесс ───────────────────────────────────────────────────

    def _child_env(self) -> dict[str, str]:
        merged = dict(os.environ)
        merged.update(self.env)
        merged.setdefault("PYTHONUTF8", "1")
        merged.setdefault("PYTHONIOENCODING", ENCODING)
        return merged

    async def start(self) -> None:
        """Запустить процесс сервера (идемпотентно)."""
        if self._proc is not None and self._proc.poll() is None:
            return
        if self._closed:
            raise McpError(f"{self.name}: клиент закрыт")
        try:
            self._proc = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.cwd,
                env=self._child_env(),
            )
        except OSError as exc:
            raise McpError(f"{self.name}: не удалось запустить сервер: {exc}") from exc

    async def close(self) -> None:
        """Завершить процесс и освободить ресурсы (идемпотентно)."""
        self._closed = True
        proc, self._proc = self._proc, None
        if proc is None:
            return
        await asyncio.to_thread(self._terminate, proc)

    @staticmethod
    def _terminate(proc: subprocess.Popen[bytes]) -> None:
        try:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                except OSError:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except OSError:
            pass

    # ── протокол ──────────────────────────────────────────────────

    async def initialize(self) -> dict[str, Any]:
        """Рукопожатие: ``initialize`` → ``notifications/initialized``."""
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "prokop", "version": __version__},
            },
        )
        await self._rpc("notifications/initialized", None, notification=True)
        return result if isinstance(result, dict) else {}

    async def list_tools(self) -> list[McpTool]:
        """Список инструментов сервера."""
        result = await self._rpc("tools/list", {})
        raw = (result or {}).get("tools") if isinstance(result, dict) else None
        tools: list[McpTool] = []
        for item in raw or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name:
                continue
            schema = item.get("inputSchema")
            tools.append(
                McpTool(
                    name=str(name),
                    description=str(item.get("description") or ""),
                    input_schema=schema if isinstance(schema, dict) else default_schema(),
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: Optional[dict[str, Any]] = None) -> str:
        """Вызвать инструмент сервера; вернуть JSON-строку результата."""
        result = await self._rpc(
            "tools/call", {"name": name, "arguments": dict(arguments or {})}
        )
        return _result_to_json(result)

    async def call_tool_text(self, name: str, arguments: Optional[dict[str, Any]] = None) -> str:
        """Вызвать инструмент и вернуть склеенный текст контент-блоков.

        Нужно потребителям, работающим с текстовым ответом сервера (например
        бэкенд `cua-driver`), а не с конвертом результата.
        """
        result = await self._rpc(
            "tools/call", {"name": name, "arguments": dict(arguments or {})}
        )
        return _content_text(result)

    async def call_method(self, method: str, params: Optional[dict[str, Any]] = None) -> Any:
        """Вызвать произвольный метод без рукопожатия.

        Нужно потребителям, которые уже знают протокол сервера и не выполняют
        MCP-рукопожатие (бэкенд `cua-driver` общается с демоном напрямую).
        """
        return await self._rpc(method, params)

    async def _rpc(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        notification: bool = False,
    ) -> Any:
        await self.start()
        request: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            request["params"] = params

        expected: Optional[int] = None
        if not notification:
            self._req_id += 1
            expected = self._req_id
            request["id"] = expected

        payload = json.dumps(request, ensure_ascii=False).encode(ENCODING) + b"\n"

        async with self._lock:
            await self._write(payload)
            if notification:
                return None
            line = await self._read(method)

        response = self._parse(line, method)
        if response.get("id") != expected:
            raise McpError(f"{self.name}: несовпадение id ответа на {method}")
        error = response.get("error")
        if error:
            code = error.get("code") if isinstance(error, dict) else None
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise McpError(f"{self.name}: ошибка {method} ({code}): {message}")
        return response.get("result")

    async def _write(self, payload: bytes) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpError(f"{self.name}: процесс сервера не запущен")
        try:
            await asyncio.to_thread(self._write_sync, payload)
        except OSError as exc:
            raise McpError(f"{self.name}: не удалось записать запрос: {exc}") from exc

    def _write_sync(self, payload: bytes) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None:
            raise McpError(f"{self.name}: процесс сервера не запущен")
        proc.stdin.write(payload)
        proc.stdin.flush()

    async def _read(self, method: str) -> bytes:
        """Прочитать строку ответа; при таймауте завершить процесс."""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._read_line_sync), self.timeout
            )
        except asyncio.TimeoutError as exc:
            # Завершение процесса разблокирует читающий поток.
            await self.close()
            raise McpError(
                f"{self.name}: таймаут ответа на {method} ({self.timeout:g} с)"
            ) from exc

    def _read_line_sync(self) -> bytes:
        """Читать строки, пропуская пустые и не-JSON (логи сервера)."""
        deadline = time.monotonic() + self.timeout
        while True:
            proc = self._proc
            if proc is None or proc.stdout is None:
                raise McpError(f"{self.name}: процесс сервера не запущен")
            line = proc.stdout.readline()
            if line == b"":
                raise McpError(f"{self.name}: сервер закрыл поток без ответа")
            stripped = line.strip()
            if not stripped:
                continue
            if not stripped.startswith(b"{"):
                log.debug("%s: пропущена не-JSON строка: %r", self.name, stripped[:120])
                continue
            return stripped

    def _parse(self, line: bytes, method: str) -> dict[str, Any]:
        try:
            data = json.loads(line.decode(ENCODING, errors="replace"))
        except json.JSONDecodeError as exc:
            raise McpError(f"{self.name}: невалидный JSON в ответе на {method}") from exc
        if not isinstance(data, dict):
            raise McpError(f"{self.name}: ответ на {method} не является объектом")
        return data
