"""Живой smoke-тест: один ход агента через реальную модель DeepSeek.

Запуск: ``python smoke_live.py [модель]``
Ключ берётся из ``DEEPSEEK_API_KEY`` (или из ``src/.env``, который не
коммитится — см. корневой ``.gitignore``).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent_core.loop.streaming import StreamCallbacks
from agent_core.loop.turn import AgentTurn
from agent_core.providers.registry import ProviderRegistry
from agent_core.transport.http_transport import ChatCompletionsTransport

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


async def main(model: str) -> int:
    key = load_key()
    if not key:
        print("[smoke] НЕТ КЛЮЧА: задайте DEEPSEEK_API_KEY или положите его в src/.env")
        return 1

    registry = ProviderRegistry()
    registry.discover()
    profile = registry.get("deepseek")
    if profile is None:
        print("[smoke] Профиль deepseek не найден в реестре")
        return 1

    transport = ChatCompletionsTransport(profile, api_key=key, timeout=60.0)
    callbacks = StreamCallbacks(on_text=lambda delta: print(delta, end="", flush=True))

    turn = AgentTurn(
        transport=transport,
        model=model,
        provider="deepseek",
        identity="Ты — лаконичный полезный ассистент.",
        max_tokens=200,
        callbacks=callbacks,
    )

    print(f"[smoke] модель={model}, провайдер=deepseek")
    result = await turn.run("Ответь одним словом: столица Франции?")
    print()
    print(
        f"[smoke] completed={result.completed} failed={result.failed} "
        f"api_calls={result.api_calls}"
    )
    if result.error:
        print(f"[smoke] error={result.error}")
    if result.final_response:
        print(f"[smoke] ответ: {result.final_response}")
    await transport.close()
    return 0 if result.completed else 1


if __name__ == "__main__":
    model = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_MODEL
    raise SystemExit(asyncio.run(main(model)))
