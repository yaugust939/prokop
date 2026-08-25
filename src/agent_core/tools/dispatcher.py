"""Диспетчеризация вызовов инструментов.

Маршрутизирует вызовы модели к обработчикам. Ошибки унифицируются в
формат с маркером, обрезаются по лимиту и очищаются от структурных
токенов. Ошибки контракта (не-JSON результат) превращаются в ошибки.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any, Awaitable, Callable, Optional

from agent_core.logging_setup import get_logger
from agent_core.tools.registry import Tool, ToolRegistry, get_registry, validate_result

log = get_logger("tools.dispatcher")

#: Маркер ошибки в результате инструмента.
TOOL_ERROR_MARKER = "[TOOL_ERROR]"

#: Структурные токены, вычищаемые из ошибок.
_STRUCTURAL_RE = re.compile(
    r"(</?[a-zA-Z][a-zA-Z0-9_:-]*>|<!\[CDATA\[|\]\]>|```)",
)

#: Колбэк подтверждения опасных операций.
ApprovalCallback = Callable[[str, str], Awaitable[bool]]


class ToolDispatchError(Exception):
    """Ошибка исполнения инструмента."""


def _format_error(message: str, limit: int) -> str:
    """Унифицировать ошибку: маркер, очистка, обрезка."""
    cleaned = _STRUCTURAL_RE.sub("", message)
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1] + "…"
    return json.dumps({"error": f"{TOOL_ERROR_MARKER} {cleaned}"}, ensure_ascii=False)


async def handle_function_call(
    name: str,
    args: dict[str, Any],
    *,
    registry: Optional[ToolRegistry] = None,
    approval: Optional[ApprovalCallback] = None,
) -> str:
    """Выполнить вызов инструмента и вернуть JSON-строку результата.

    Перед вызовом применяется коэрция аргументов по схеме. Если инструмент
    требует одобрения (см. ``safety``), вызывается ``approval``; отказ
    превращается в ошибку.
    """
    from agent_core.tools.coercion import coerce_arguments
    from agent_core.tools.safety import classify_command, ApprovalDecision

    reg = registry or get_registry()
    tool = reg.get(name)
    if tool is None:
        return _format_error(f"неизвестный инструмент: {name}", 2000)

    args = coerce_arguments(args, tool.openai_schema()["function"]["parameters"])

    if name == "run_command" and isinstance(args.get("command"), str):
        decision = classify_command(args["command"])
        if decision is ApprovalDecision.BLOCKED:
            return _format_error("команда в жёстком блок-листе и не выполняется", 2000)
        if decision is ApprovalDecision.NEEDS_APPROVAL:
            if approval is None or not await approval(name, args["command"]):
                return _format_error("команда не одобрена пользователем", 2000)

    handler = tool.handler
    try:
        if tool.is_async or inspect.iscoroutinefunction(handler):
            result = await handler(**args)
        else:
            result = handler(**args)
        return validate_result(result)
    except (TypeError, ValueError) as exc:
        return _format_error(f"ошибка контракта: {exc}", tool.result_limit)
    except Exception as exc:  # noqa: BLE001 — любую ошибку инструмента унифицируем
        log.warning("Инструмент %s завершился ошибкой: %s", name, exc)
        return _format_error(str(exc), tool.result_limit)
