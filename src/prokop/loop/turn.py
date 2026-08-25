"""Ход агента: пролог → основной цикл → финализация.

Обрабатывает один пользовательский ход от ввода до финального ответа.
Пролог выполняет одноразовую настройку (санитизация ввода, восстановление
или построение системного промпта, префлайт, предзагрузка памяти), цикл
итеративно вызывает модель и исполняет инструменты, финализация сбрасывает
счётчики, пишет транскрипт и запускает фоновые пост-обработчики.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from prokop.loop.budgets import Budgets
from prokop.loop.compressor import compress_context
from prokop.loop.control import TurnControl
from prokop.loop.errors import classify_error, retry_transient
from prokop.loop.messages import Message, clone_messages, sanitize_text, to_api_messages
from prokop.loop.streaming import StreamCallbacks
from prokop.loop.system_prompt import SystemPromptState, build_system_prompt, is_stale
from prokop.memory.injection import inject_into_user_message
from prokop.memory.manager import MemoryManager
from prokop.tools.dispatcher import handle_function_call
from prokop.tools.registry import ToolRegistry
from prokop.transport.base import ModelResponse, ModelTransport, TransportConfig

#: Максимум ходов цикла на один вызов (защита от бесконечности).
DEFAULT_MAX_ITERATIONS = 50


@dataclass
class TurnResult:
    """Результат одного хода."""

    final_response: Optional[str] = None
    messages: list[Message] = field(default_factory=list)
    api_calls: int = 0
    completed: bool = False
    interrupted: bool = False
    failed: bool = False
    error: Optional[str] = None
    retryable: bool = False


class AgentTurn:
    """Один ход агента."""

    def __init__(
        self,
        *,
        transport: ModelTransport,
        tool_registry: Optional[ToolRegistry] = None,
        memory: Optional[MemoryManager] = None,
        system_prompt: Optional[SystemPromptState] = None,
        identity: str = "Агент",
        model: str = "unknown-model",
        provider: str = "unknown-provider",
        platform: str = "cli",
        tool_schemas: Optional[list[dict[str, Any]]] = None,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        budgets: Optional[Budgets] = None,
        control: Optional[TurnControl] = None,
        callbacks: Optional[StreamCallbacks] = None,
        max_tokens: Optional[int] = None,
        history: Optional[list[Message]] = None,
    ) -> None:
        self.transport = transport
        self.tool_registry = tool_registry
        self.memory = memory
        self.system_prompt_state = system_prompt or SystemPromptState()
        self.identity = identity
        self.model = model
        self.provider = provider
        self.platform = platform
        self.tool_schemas = tool_schemas or []
        self.max_iterations = max_iterations
        self.budgets = budgets or Budgets()
        self.control = control or TurnControl()
        self.callbacks = callbacks or StreamCallbacks()
        self.max_tokens = max_tokens
        self.messages: list[Message] = list(history or [])

    # --- пролог ---------------------------------------------------------

    async def _prologue(self, user_input: str) -> str:
        """Одноразовая настройка хода. Возвращает финальный текст ввода."""
        text = sanitize_text(user_input) or ""

        if self.system_prompt_state.content is None or is_stale(
            self.system_prompt_state, model=self.model, provider=self.provider, platform=self.platform
        ):
            self.system_prompt_state = build_system_prompt(
                identity=self.identity,
                model=self.model,
                provider=self.provider,
                platform=self.platform,
            )

        memory_context = ""
        if self.memory is not None:
            try:
                memory_context = await self.memory.prefetch(text)
            except Exception:  # noqa: BLE001 — сбой памяти не блокирует ход
                memory_context = ""

        # Контекст памяти впрыскивается в пользовательское сообщение,
        # а не в системный промпт (не ломаем кэш префикса).
        return inject_into_user_message(text, memory_context)

    # --- основной цикл ----------------------------------------------------

    async def run(self, user_input: str) -> TurnResult:
        """Выполнить ход до финального ответа или остановки."""
        result = TurnResult()
        self.budgets.start()

        final_input = await self._prologue(user_input)
        self.messages.append(Message(role="user", content=final_input))

        iterations = 0
        while True:
            if self.control.stop_requested:
                result.interrupted = True
                result.final_response = self._last_assistant_text()
                break

            if iterations >= self.max_iterations or not self.budgets.can_call_model():
                result.completed = True
                result.final_response = self._last_assistant_text()
                break

            iterations += 1
            self.budgets.consume_iteration()
            result.api_calls += 1

            response, error = await self._call_model()
            if error is not None:
                result.failed = True
                result.error = error.message
                result.retryable = error.retryable
                break

            redirect_text = self.control.take_redirect()
            if redirect_text is not None:
                # Redirect: частичный ответ понижается до текста, коррекция
                # добавляется как пользовательское сообщение, ход повторяется.
                if response.content:
                    self.messages.append(Message(role="assistant", content=response.content))
                self.messages.append(Message(role="user", content=redirect_text))
                continue

            if response.has_tool_calls:
                self.messages.append(
                    Message(
                        role="assistant",
                        content=response.content,
                        tool_calls=response.tool_calls,
                        reasoning=response.reasoning,
                    )
                )
                await self._execute_tools(response.tool_calls)
                note = self.budgets.wind_down_note()
                if note:
                    self.messages.append(Message(role="tool", content=note, tool_call_id="budget-note"))
                continue

            self.messages.append(
                Message(role="assistant", content=response.content, reasoning=response.reasoning)
            )
            self.callbacks.emit_text(response.content or "")
            result.final_response = response.content
            result.completed = True
            break

        await self._finalize()
        result.messages = self.messages
        return result

    # --- вызов модели -------------------------------------------------------

    async def _call_model(self):
        """Один вызов модели с ретраями транзиентных ошибок."""
        config = TransportConfig(
            model=self.model,
            messages=self._api_messages(),
            tools=self.tool_schemas,
            max_tokens=self.max_tokens,
        )

        async def factory():
            return await self.transport.call(config)

        response, error = await retry_transient(factory)
        return response, error

    def _api_messages(self) -> list[dict[str, Any]]:
        """История для API: системный промпт + клонированные сообщения."""
        api = []
        if self.system_prompt_state.content:
            api.append({"role": "system", "content": self.system_prompt_state.content})
        api.extend(to_api_messages(self.messages))
        return api

    # --- исполнение инструментов ---------------------------------------------

    async def _execute_tools(self, tool_calls: list[dict[str, Any]]) -> None:
        """Исполнить вызовы и добавить результаты как tool-сообщения."""
        for call in tool_calls:
            name = call.get("name") or ""
            args = call.get("arguments") or {}
            call_id = call.get("id") or ""
            self.callbacks.emit_tool_event("start", {"name": name})

            if self.memory is not None:
                memory_result = await self.memory.handle_tool_call(name, args)
                if memory_result is not None:
                    self.messages.append(
                        Message(role="tool", content=memory_result, tool_call_id=call_id, tool_name=name)
                    )
                    self.callbacks.emit_tool_event("finish", {"name": name})
                    continue

            if self.tool_registry is not None:
                output = await handle_function_call(name, args, registry=self.tool_registry)
            else:
                import json as _json

                output = _json.dumps({"error": "реестр инструментов не подключён"}, ensure_ascii=False)

            steer = self.control.take_steer()
            if steer:
                output = f"{output}\n\n{steer}"

            self.messages.append(
                Message(role="tool", content=output, tool_call_id=call_id, tool_name=name)
            )
            self.callbacks.emit_tool_event("finish", {"name": name})

    # --- финализация -----------------------------------------------------------

    async def _finalize(self) -> None:
        """Сброс счётчиков, синхронизация памяти, фоновые пост-обработчики."""
        if self.memory is not None:
            user_text = next(
                (m.content for m in reversed(self.messages) if m.role == "user"), ""
            ) or ""
            assistant_text = self._last_assistant_text() or ""
            try:
                await self.memory.sync_turn(user_text, assistant_text, to_api_messages(self.messages))
            except Exception:  # noqa: BLE001 — сбой синхронизации не роняет ход
                pass

    def _last_assistant_text(self) -> Optional[str]:
        for message in reversed(self.messages):
            if message.role == "assistant" and message.content:
                return message.content
        return None
