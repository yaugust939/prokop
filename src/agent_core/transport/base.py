"""Абстракция транспорта вызовов модели.

Транспорт читает из профиля провайдера (а не из параллельных данных) и
применяет хуки профиля на каждом вызове: подготовку сообщений, доп. поля
тела запроса, разделение доп. полей. Построение клиента и стриминг
остаются вне профиля.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from agent_core.providers.profile import ProviderProfile


@dataclass
class TransportConfig:
    """Параметры одного вызова."""

    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = field(default_factory=list)
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    reasoning_effort: Optional[str] = None


@dataclass
class ModelResponse:
    """Ответ модели."""

    content: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    reasoning: Optional[str] = None
    finish_reason: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class ModelTransport(ABC):
    """Транспорт вызовов модели."""

    def __init__(self, profile: ProviderProfile) -> None:
        self.profile = profile

    def prepare_request(self, config: TransportConfig) -> dict[str, Any]:
        """Подготовить тело запроса, применив хуки профиля."""
        messages = config.messages
        if self.profile.prepare_messages is not None:
            messages = self.profile.prepare_messages(messages)

        body: dict[str, Any] = {
            "model": config.model,
            "messages": messages,
        }
        if config.tools:
            body["tools"] = config.tools
        if config.max_tokens is not None:
            body["max_tokens"] = config.max_tokens
        if config.temperature is not None:
            body["temperature"] = config.temperature
        if config.reasoning_effort is not None:
            body["reasoning_effort"] = config.reasoning_effort

        if self.profile.build_extra_body is not None:
            extra = self.profile.build_extra_body(body)
            body.update(extra)
        return body

    @abstractmethod
    async def call(self, config: TransportConfig) -> ModelResponse:
        """Выполнить один вызов модели."""

    async def health_check(self) -> bool:
        """Проверка доступности провайдера (если поддерживается)."""
        return False
