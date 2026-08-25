"""Оркестратор гейтвея.

Связывает подсистемы в единый конвейер обработки входящего события:
ключ сессии → авторизация → защита от параллельных ходов → кэш агентов →
агентный ход (инжектируемый колбэк ``run_turn``) → подготовка ответа.

Реальный запуск модельного хода не входит в ядро: он инжектируется колбэком
``run_turn(session_id, text) -> str`` (async).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Optional

from agent_core.gateway.adapters import PlatformAdapter
from agent_core.gateway.auth import SenderGate, UnauthorizedPolicy
from agent_core.gateway.cache import AgentCache
from agent_core.gateway.events import (
    CONTROL_NEW,
    CONTROL_RESET,
    CONTROL_STOP,
    InboundEvent,
)
from agent_core.gateway.guard import Admit, SessionGuard, TurnMode
from agent_core.gateway.response import prepare_response


class HandleOutcome(str, Enum):
    """Итог обработки входящего события."""

    RESPONDED = "responded"
    IGNORED = "ignored"
    PAIRING = "pairing"
    QUEUED = "queued"
    CONTROL = "control"


@dataclass
class HandleResult:
    """Результат обработки события."""

    outcome: HandleOutcome
    session_key: str
    text: Optional[str] = None


def _new_turn_id() -> str:
    return secrets.token_hex(8)


class Gateway:
    """Ядро гейтвея: приём события, маршрутизация, агентный ход, ответ."""

    def __init__(
        self,
        run_turn: Callable[[str, str], Awaitable[str]],
        *,
        authorizer: Optional[SenderGate] = None,
        guard: Optional[SessionGuard] = None,
        cache: Optional[AgentCache] = None,
        agent_factory: Optional[Callable[[str], object]] = None,
        max_response_length: Optional[int] = None,
        control_handler: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self.run_turn = run_turn
        self.authorizer = authorizer if authorizer is not None else SenderGate()
        self.guard = guard if guard is not None else SessionGuard()
        self.cache = cache if cache is not None else AgentCache()
        self.agent_factory = agent_factory
        self.max_response_length = max_response_length
        self.control_handler = control_handler

    async def handle(self, event: InboundEvent) -> HandleResult:
        """Обработать одно входящее событие."""
        session = event.session_key

        decision = self.authorizer.authorize(
            event.source.platform, event.author.user_id
        )
        if not decision.allowed:
            if decision.policy is UnauthorizedPolicy.PAIR:
                return HandleResult(HandleOutcome.PAIRING, session, self._pairing_text())
            return HandleResult(HandleOutcome.IGNORED, session)

        control = event.control
        admit = self.guard.admit(session, control=control is not None)

        if control is not None:
            text = self._handle_control(session, control)
            return HandleResult(HandleOutcome.CONTROL, session, text)

        if admit is Admit.QUEUE:
            self.guard.enqueue(session, _new_turn_id())
            return HandleResult(HandleOutcome.QUEUED, session)

        self._ensure_agent(session)

        turn_id = _new_turn_id()
        self.guard.start(session, turn_id)
        try:
            raw = await self.run_turn(session, event.text)
        finally:
            self.guard.finish(session, turn_id)

        prepared = prepare_response(raw, max_length=self.max_response_length)
        return HandleResult(HandleOutcome.RESPONDED, session, prepared)

    def _ensure_agent(self, session: str) -> None:
        if session in self.cache:
            return
        if self.agent_factory is not None:
            agent = self.agent_factory(session)
            if agent is not None:
                self.cache.put(session, agent)

    def _pairing_text(self) -> str:
        return "Код подтверждения: " + secrets.token_hex(3)

    def _handle_control(self, session: str, command: str) -> str:
        if self.control_handler is not None:
            return self.control_handler(session, command)
        if command == CONTROL_STOP:
            return "Ход остановлен."
        if command == CONTROL_NEW:
            self.cache.evict(session)
            return "Начат новый разговор."
        if command == CONTROL_RESET:
            self.cache.evict(session)
            return "Разговор сброшен."
        return "Команда обработана."
