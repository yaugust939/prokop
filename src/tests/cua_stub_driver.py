"""Демон cua-driver-заглушка для тестов (только стандартная библиотека).

Отвечает на JSON-RPC 2.0 `tools/call` контент-блоками с JSON-текстом — так
же, как настоящий демон. Рукопожатие MCP не поддерживает: любой метод кроме
`tools/call` возвращает ошибку, поэтому случайное рукопожатие сразу видно в
тестах.

Флаг ``--silent`` — не отвечать вовсе (проверка таймаута).
"""

from __future__ import annotations

import json
import sys
from typing import Any

#: 1×1 PNG (прозрачный) — достаточно, чтобы проверить декодирование.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/"
    "q842iQAAAABJRU5ErkJggg=="
)

CAPTURE_PAYLOAD: dict[str, Any] = {
    "image": f"data:image/png;base64,{TINY_PNG_B64}",
    "elements": [
        {
            "index": 1,
            "name": "Кнопка",
            "control_type": "Button",
            "role": "Button",
            "rect": [0, 0, 10, 10],
        },
        {
            "index": 2,
            "name": "Поле",
            "control_type": "Edit",
            "role": "Edit",
            "rect": [12, 0, 40, 10],
        },
    ],
}

APPS_PAYLOAD: list[dict[str, Any]] = [{"title": "Заглушка", "pid": 4242}]


def respond(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _text_result(req_id: Any, text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {"content": [{"type": "text", "text": text}], "isError": False},
    }


def tool_payload(name: str, arguments: dict[str, Any]) -> Any:
    if name == "capture":
        return CAPTURE_PAYLOAD
    if name in ("list_apps", "list_windows"):
        return APPS_PAYLOAD
    if name == "broken":
        return {"ok": False, "error": "демон отказал"}
    return {"ok": True, "description": f"{name} ok"}


def handle(request: dict[str, Any]) -> None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "tools/call":
        params = request.get("params") or {}
        name = str(params.get("name") or "")
        if name == "boom":
            respond(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": "внутренняя ошибка демона"},
                }
            )
            return
        payload = tool_payload(name, params.get("arguments") or {})
        respond(_text_result(req_id, json.dumps(payload, ensure_ascii=False)))
        return

    # Рукопожатие MCP демон не поддерживает.
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
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(request, dict) or silent:
            continue
        handle(request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
