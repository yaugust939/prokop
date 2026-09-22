#!/usr/bin/env python3
"""Мозг ролей OS3 на ядре prokop.

Роли из ``ARTEL_PROKOP_ROLES`` обслуживаются ``AgentTurn`` из prokop вместо
собственного цикла ``llm_call`` раннера: тот же персонаж, та же память, тот же
набор инструментов (MCP-шлюзы, vault, правки сайтов) — но цикл хода, бюджеты,
ретраи и обработка ошибок берутся из ядра prokop.

Инструменты не меняются: реестр prokop получает схемы, переданные раннером, а
вызовы уходят в его же ``call_tool`` — слой доступа к MCP/vault/сайтам остаётся
единственным.

**Защита от зацикливания портирована.** Раннер останавливал агента, который
повторяет один и тот же падающий вызов (в артели был случай: 86 вызовов, ни
одной записи). Здесь тот же учёт: после 3 повторов в результат инструмента
добавляется указание не повторять вызов, после 5 — ход прерывается через
``TurnControl``, а задача завершается честным текстом «данные получить не
удалось» с кодом ошибки.

Отказобезопасность: при любой ошибке (импорт, инициализация, ход) возвращается
``None`` — раннер откатывается на прежний ``llm_call``. Полностью выключить
можно пустым ``ARTEL_PROKOP_ROLES``.

Переменные окружения:

- ``ARTEL_PROKOP_ROLES``   — роли на prokop: ``*`` (все), список через запятую
  или пусто (выключено). По умолчанию ``prokopiy``;
- ``ARTEL_PROKOP_MODEL``   — модель (по умолчанию ``deepseek-chat``, как в раннере);
- ``ARTEL_PROKOP_TIMEOUT`` — таймаут HTTP, секунд (по умолчанию 180).
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from typing import Any, Callable, Optional

#: Значения, означающие «все роли».
_ALL_MARKERS = ("*", "all", "все")

_RAW_ROLES = os.environ.get("ARTEL_PROKOP_ROLES", "prokopiy")

#: Все роли обслуживаются ядром prokop.
PROKOP_ALL = _RAW_ROLES.strip().lower() in _ALL_MARKERS

#: Явно перечисленные роли.
PROKOP_ROLES = {
    a.strip()
    for a in _RAW_ROLES.split(",")
    if a.strip() and a.strip().lower() not in _ALL_MARKERS
}

#: Модель роли (совпадает с моделью раннера, чтобы поведение было сопоставимым).
PROKOP_MODEL = os.environ.get("ARTEL_PROKOP_MODEL", "deepseek-chat")

#: Таймаут HTTP до провайдера, секунд.
PROKOP_TIMEOUT = float(os.environ.get("ARTEL_PROKOP_TIMEOUT", "180"))

#: Сколько повторов одного падающего вызова до указания модели.
FAIL_NOTE_AFTER = int(os.environ.get("ARTEL_PROKOP_FAIL_NOTE", "3"))

#: Сколько повторов до прерывания хода.
FAIL_STOP_AFTER = int(os.environ.get("ARTEL_PROKOP_FAIL_STOP", "5"))

#: Эндпоинт провайдера (тот же, что у раннера).
DEEPSEEK_URL = os.environ.get(
    "DEEPSEEK_URL", "https://api.deepseek.com/chat/completions"
)


def _log(message: str) -> None:
    """Локальный лог (раннер подставляет свой через параметр ``log_fn``)."""
    print(f"[prokop-engine] {message}", flush=True)


def role_enabled(agent: str) -> bool:
    """Обслуживается ли роль ядром prokop."""
    if PROKOP_ALL:
        return True
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


def _make_guarded_bridge(
    tool_bridge: Callable[[str, dict], str],
    *,
    agent: str,
    control: Any,
    state: dict[str, Any],
    logger: Callable[[str, str], None],
) -> Callable[[str, dict], str]:
    """Обёртка вызова инструмента с учётом повторов (как в ``llm_call``).

    Возвращает модели только текст результата; конверт ``{text, is_error}``
    разбирается здесь, чтобы поведение совпадало с прежним раннером.
    """

    def bridge(name: str, args: dict) -> str:
        raw = tool_bridge(name, args) or "{}"
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            envelope = {"text": raw, "is_error": False}
        if not isinstance(envelope, dict):
            envelope = {"text": str(raw), "is_error": False}

        text = str(envelope.get("text") or "")
        is_error = bool(envelope.get("is_error"))
        failed = is_error or '"ok": false' in text or '"ok":false' in text

        signature = name + ":" + json.dumps(args or {}, ensure_ascii=False, sort_keys=True)
        streaks: dict[str, int] = state["fail"]
        if failed:
            streaks[signature] = streaks.get(signature, 0) + 1
        else:
            streaks.pop(signature, None)
        repeats = streaks.get(signature, 0)

        logger(
            agent,
            f"tool {name} args={json.dumps(args or {}, ensure_ascii=False)[:160]} "
            f"-> {len(text)} симв.{' (ошибка)' if is_error else ''}"
            + (f" [повтор ошибки {repeats}]" if repeats else ""),
        )

        if repeats >= FAIL_NOTE_AFTER:
            text += (
                "\n\n[СИСТЕМА] Этот же вызов падает подряд "
                + str(repeats)
                + " раз. НЕ повторяй его. Собери отчёт из уже полученных данных, "
                "явно напиши, каких данных нет и почему (с кодом ошибки), и заверши."
            )
        if repeats >= FAIL_STOP_AFTER:
            logger(
                agent,
                f"тупик: вызов {name} падает {repeats} раз — прекращаю итерации",
            )
            state["deadlock"] = True
            control.interrupt()
        return text

    return bridge


def _build_registry(
    specs: list[dict[str, Any]],
    bridge: Callable[[str, dict], str],
) -> Any:
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
        from prokop.loop.control import TurnControl
        from prokop.loop.turn import AgentTurn
        from prokop.transport.http_transport import ChatCompletionsTransport
    except Exception as exc:  # ядро не установлено — не роняем флот
        logger(agent, f"prokop недоступен ({type(exc).__name__}: {exc}) — откат на llm_call")
        return None

    prompt = f"Задача: {title}" + (f" Контекст: {description}" if description else "")

    control = TurnControl()
    state: dict[str, Any] = {"fail": {}, "deadlock": False}

    try:
        profile = _profile()
        guarded = (
            _make_guarded_bridge(
                tool_bridge, agent=agent, control=control, state=state, logger=logger
            )
            if tool_bridge is not None
            else None
        )
        registry = _build_registry(specs or [], guarded) if guarded and specs else None
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

        transport = ChatCompletionsTransport(profile, api_key=key, timeout=PROKOP_TIMEOUT)
        turn = AgentTurn(
            transport=transport,
            tool_registry=registry,
            tool_schemas=schemas or None,
            model=model or PROKOP_MODEL,
            provider=profile.name,
            identity=_identity(persona, memory_block),
            max_tokens=max_tokens,
            max_iterations=max_iterations or 12,
            control=control,
        )

        async def _execute() -> Any:
            try:
                return await turn.run(prompt)
            finally:
                await transport.close()

        result = asyncio.run(_execute())
    except Exception as exc:  # любая ошибка — откат, флот не должен падать
        logger(
            agent,
            f"prokop: ход не удался ({type(exc).__name__}: {str(exc)[:200]}) — откат",
        )
        return None

    text = (result.final_response or "").strip()
    deadlock = bool(state["deadlock"])
    if deadlock and not text:
        text = "Инструмент стабильно возвращает ошибку — данные получить не удалось."

    # Тупик инструмента завершает задачу честным ответом (как прежний раннер),
    # поэтому это не «падение», а результат с объяснением.
    ok = (bool(result.completed) and not bool(result.failed)) or deadlock

    logger(
        agent,
        f"prokop: ход завершён api_calls={result.api_calls} "
        f"messages={len(result.messages)} failed={result.failed} "
        f"deadlock={deadlock} символов={len(text)}",
    )
    if not text:
        return None
    return text, ok


if __name__ == "__main__":  # диагностика: python3 prokop_engine.py
    print("prokop установлен:", available())
    print("все роли на prokop:", PROKOP_ALL)
    print("роли на prokop:", sorted(PROKOP_ROLES) or ("*" if PROKOP_ALL else "—"))
    print("base_url:", base_url())
    print("модель:", PROKOP_MODEL)
    print("порог указания модели:", FAIL_NOTE_AFTER, "| порог остановки:", FAIL_STOP_AFTER)
