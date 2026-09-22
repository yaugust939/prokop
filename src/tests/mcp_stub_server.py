"""MCP-сервер-заглушка для тестов (только стандартная библиотека).

Читает построчные JSON-RPC 2.0 запросы из stdin и отвечает в stdout.
Флаги:
- ``--silent`` — не отвечать вовсе (проверка таймаута);
- ``--fail-init`` — отвечать ошибкой на ``initialize`` (проверка устойчивости).
"""

from __future__ import annotations

import json
import sys
from typing import Any

TOOLS: list[dict[str, Any]] = [
    {
        "name": "echo",
        "description": "Вернуть переданный текст",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "fail",
        "description": "Всегда завершается ошибкой",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "weird.tool/name",
        "description": "Имя с недопустимыми символами",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "no_schema",
        "description": "Инструмент без схемы",
    },
]


def respond(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _text_result(req_id: Any, text: str, *, is_error: bool = False) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


def handle(request: dict[str, Any]) -> None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "notifications/initialized":
        return
    if method == "initialize":
        respond(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stub", "version": "0.0.1"},
                },
            }
        )
        return
    if method == "tools/list":
        respond({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        return
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name == "echo":
            respond(_text_result(req_id, str(arguments.get("text", ""))))
        elif name == "fail":
            respond(_text_result(req_id, "не получилось", is_error=True))
        elif name == "weird.tool/name":
            respond(_text_result(req_id, "странное имя"))
        elif name == "no_schema":
            respond(_text_result(req_id, "без схемы"))
        else:
            respond(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"неизвестный инструмент: {name}"},
                }
            )
        return

    if req_id is not None:
        respond(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"метод не поддержан: {method}"},
            }
        )


def main(argv: list[str]) -> int:
    silent = "--silent" in argv
    fail_init = "--fail-init" in argv

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict):
            continue

        if silent:
            continue
        if fail_init and request.get("method") == "initialize":
            respond(
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32000, "message": "инициализация отклонена"},
                }
            )
            continue
        handle(request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
