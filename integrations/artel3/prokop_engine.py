#!/usr/bin/env python3
"""Мозг роли OS3 на ядре prokop.

Роль из ``ARTEL_PROKOP_ROLES`` (по умолчанию ``prokopiy``) обслуживается
``AgentTurn`` из prokop вместо собственного цикла ``llm_call`` раннера:
тот же персонаж, та же память, тот же набор инструментов (MCP-шлюзы, vault,
правки сайтов) — но цикл хода, бюджеты, ретраи и обработка ошибок берутся из
ядра prokop.

Инструменты не меняются: реестр prokop получает схемы, переданные раннером, а
вызовы уходят в его же ``call_tool`` — слой доступа к MCP/vault/сайтам остаётся
единственным.

Отказобезопасность: при любой ошибке (импорт, инициализация, ход) возвращается
``None`` — раннер откатывается на прежний ``llm_call``. Полностью выключить
можно пустым ``ARTEL_PROKOP_ROLES``.

Переменные окружения:

- ``ARTEL_PROKOP_ROLES``  — роли на prokop (по умолчанию ``prokopiy``);
- ``ARTEL_PROKOP_MODEL``  — модель (по умолчанию ``deepseek-chat``, как в раннере);
- ``ARTEL_PROKOP_TIMEOUT``— таймаут HTTP, секунд (по умолчанию 180).
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from typing import Any, Callable, Optional

#: Роли, обслуживаемые ядром prokop.
PROKOP_ROLES = {
    a.strip()
    for a in os.environ.get("ARTEL_PROKOP_ROLES", "prokopiy").split(",")
    if a.strip()
}

#: Модель роли (совпадает с моделью раннера, чтобы поведение было сопоставимым).
PROKOP_MODEL = os.environ.get("ARTEL_PROKOP_MODEL", "deepseek-chat")

#: Таймаут HTTP до провайдера, секунд.
PROKOP_TIMEOUT = float(os.environ.get("ARTEL_PROKOP_TIMEOUT", "180"))

#: Эндпоинт провайдера (тот же, что у раннера).
DEEPSEEK_URL = os.environ.get(
    "DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"
)


def _log(message: str) -> None:
    """Локальный лог (раннер подставляет свой через параметр ``log_fn``)."""
    print(f"[prokop-engine] {message}", flush=True)


def role_enabled(agent: str) -> bool:
    """Обслуживается ли роль ядром prokop."""
    return (agent or "").split(":")[-1] in PROKOP_ROLES


def available() -> bool:
    """Установлено ли ядро prokop в текущем окружении."""
    try:
        import prokop  # noqa: F401
    except Exception:
        return False
    return True


def base_url() -> str:
    """Базовый URL провайдера из ``DEEPSEEK_URL`` (как у раннера)."""
    url = (DEEPSEEK_URL or "").rstrip("/")
    for suffix in ("/chat/completions", "/v1/chat/completions"):
        if url.endswith(suffix):
            return url[: -len(suffix)]
    return url


def _profile() -> Any:
    """Профиль провайдера prokop с базовым URL раннера."""
    from prokop.providers.profile import ProviderProfile
    from prokop.providers.registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.discover()
    profile = registry.get("deepseek")
    if profile is None:
        return ProviderProfile(name="deepseek", base_url=base_url())
    return replace(profile, base_url=base_url())


def _identity(persona: Optional[str], memory_block: Optional[str]) -> str:
    """Системная часть промпта: персона роли + релевантная память."""
    parts = []
    if persona:
        parts.append(persona)
    if memory_block:
        parts.append(
            "Факты из твоей долгосрочной памяти (используй их, если релевантно):\n"
            + memory_block
        )
    parts.append(
        "Ты — агент AI ARTEL OS 3. Выполни задачу и верни краткий практичный "
        "результат. Числа и факты бери ТОЛЬКО из вызовов инструментов, ничего не "
        "выдумывай. Если инструмент вернул ошибку или пусто — так и напиши. Не "
        "пересказывай свои возможности, а вызови инструмент и покажи данные."
    )
    return "\n\n".join(parts)


def _build_registry(specs: list[dict[str, Any]], bridge: Callable[[str, dict], str]) -> Any:
    """Реестр prokop с инструментами раннера (схемы — от раннера, вызов — в bridge)."""
    from prokop.tools.registry import Tool, ToolRegistry

    registry = ToolRegistry()
    for spec in specs or []:
        function = (spec or {}).get("function") or {}
        name = function.get("name")
        if not name:
            continue

        def make_handler(tool_name: str) -> Callable[..., str]:
            def handler(**kwargs: Any) -> str:
                return bridge(tool_name, kwargs)

            return handler

        registry.register(
            Tool(
                name=name,
                toolset="os3",
                schema={
                    "description": function.get("description", ""),
                    "parameters": function.get("parameters")
                    or {"type": "object", "properties": {}},
                },
                handler=make_handler(name),
            )
        )
    return registry


def run(
    *,
    agent: str,
    role_prompt: str,
    title: str,
    description: Optional[str],
    key: Optional[str],
    persona: Optional[str] = None,
    memory_block: Optional[str] = None,
    specs: Optional[list[dict[str, Any]]] = None,
    tool_bridge: Optional[Callable[[str, dict], str]] = None,
    model: Optional[str] = None,
    max_tokens: Optional[int] = None,
    max_iterations: Optional[int] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> Optional[tuple[str, bool]]:
    """Выполнить задачу роли через ядро prokop.

    Возвращает ``(текст, ok)`` или ``None``, если ход через prokop невозможен —
    тогда раннер обязан откатиться на свой ``llm_call``.
    """
    logger = log_fn or (lambda _agent, message: _log(message))

    if not key:
        return None

    try:
        from prokop.loop.turn import AgentTurn
        from prokop.transport.http_transport import ChatCompletionsTransport
    except Exception as exc:  # ядро не установлено — не роняем флот
        logger(agent, f"prokop недоступен ({type(exc).__name__}: {exc}) — откат на llm_call")
        return None

    prompt = (
        f"Задача: {title}"
        + (f" Контекст: {description}" if description else "")
    )

    try:
        profile = _profile()
        registry = (
            _build_registry(specs or [], tool_bridge) if specs and tool_bridge else None
        )
        schemas = [
            {
                "type": "function",
                "function": {
                    "name": (spec.get("function") or {}).get("name"),
                    "description": (spec.get("function") or {}).get("description", ""),
                    "parameters": (spec.get("function") or {}).get("parameters")
                    or {"type": "object", "properties": {}},
                },
            }
            for spec in (specs or [])
            if (spec.get("function") or {}).get("name")
        ]

        transport = ChatCompletionsTransport(
            profile, api_key=key, timeout=PROKOP_TIMEOUT
        )
        turn = AgentTurn(
            transport=transport,
            tool_registry=registry,
            tool_schemas=schemas or None,
            model=model or PROKOP_MODEL,
            provider=profile.name,
            identity=_identity(persona, memory_block),
            max_tokens=max_tokens,
            max_iterations=max_iterations or 12,
        )

        async def _execute() -> Any:
            try:
                return await turn.run(prompt)
            finally:
                await transport.close()

        result = asyncio.run(_execute())
    except Exception as exc:  # любая ошибка — откат, флот не должен падать
        logger(agent, f"prokop: ход не удался ({type(exc).__name__}: {str(exc)[:200]}) — откат")
        return None

    text = (result.final_response or "").strip()
    ok = bool(result.completed) and not bool(result.failed)
    logger(
        agent,
        f"prokop: ход завершён api_calls={result.api_calls} "
        f"tools={len(result.messages)} failed={result.failed} символов={len(text)}",
    )
    if not text:
        return None
    return text, ok


if __name__ == "__main__":  # диагностика: python3 prokop_engine.py
    print("prokop установлен:", available())
    print("роли на prokop:", sorted(PROKOP_ROLES))
    print("base_url:", base_url())
    print("модель:", PROKOP_MODEL)
