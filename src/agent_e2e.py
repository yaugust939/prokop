"""Живой e2e-тест агента: ход с использованием инструмента через реальную модель.

Проверяет весь цикл: модель -> вызов инструмента -> результат инструмента ->
финальный ответ. Запуск: ``python agent_e2e.py`` (ключ из DEEPSEEK_API_KEY
или src/.env).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from prokop.loop.turn import AgentTurn
from prokop.providers.registry import ProviderRegistry
from prokop.tools.registry import ToolRegistry, register
from prokop.transport.http_transport import ChatCompletionsTransport

DEFAULT_MODEL = "deepseek-chat"


def load_key() -> str | None:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    env_file = SRC / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def build_registry() -> ToolRegistry:
    """Простой детерминированный инструмент для проверки цикла."""
    registry = ToolRegistry()
    register(
        "multiply",
        "core",
        {
            "description": "Умножить два числа и вернуть результат.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "Первый множитель"},
                    "b": {"type": "number", "description": "Второй множитель"},
                },
                "required": ["a", "b"],
            },
        },
        lambda a, b: json.dumps({"result": float(a) * float(b)}),
        registry=registry,
    )
    return registry


async def main() -> int:
    key = load_key()
    if not key:
        print("[e2e] НЕТ КЛЮЧА: задайте DEEPSEEK_API_KEY или положите в src/.env")
        return 1

    registry_provider = ProviderRegistry()
    registry_provider.discover()
    profile = registry_provider.get("deepseek")
    transport = ChatCompletionsTransport(profile, api_key=key, timeout=180.0)

    tools = build_registry()
    turn = AgentTurn(
        transport=transport,
        tool_registry=tools,
        tool_schemas=[tools.get("multiply").openai_schema()],
        model=DEFAULT_MODEL,
        provider="deepseek",
        identity="Ты — точный ассистент. Если есть подходящий инструмент — используй его.",
        max_tokens=500,
    )

    print(f"[e2e] модель={DEFAULT_MODEL}, инструмент=multiply")
    result = await turn.run("Сколько будет 17 умножить на 23? Обязательно используй инструмент multiply.")
    await transport.close()

    print(f"[e2e] completed={result.completed} failed={result.failed} api_calls={result.api_calls}")
    print(f"[e2e] ответ: {result.final_response}")

    # Проверки: ход завершился, было >=2 вызова модели (тул-колл + ответ),
    # в истории есть tool-сообщение, в ответе — правильный результат 391.
    roles = [m.role for m in result.messages]
    has_tool = "tool" in roles
    ok = (
        result.completed
        and result.api_calls >= 2
        and has_tool
        and result.final_response is not None
        and "391" in result.final_response
    )
    print(f"[e2e] tool-вызов в истории: {has_tool}; ролей: {roles}")
    print("[e2e] ИТОГ:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
