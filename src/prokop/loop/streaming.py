"""Стриминг вывода и события жизненного цикла инструментов.

Текстовые дельты доставляются через колбэк стриминга; рассуждения — через
отдельный колбэк и никогда не сериализуются в контент сообщений. Есть
события: старт инструмента, прогресс, завершение, «промежуточное»
ассистентское сообщение.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

TextCallback = Callable[[str], None]
EventCallback = Callable[[str, dict[str, Any]], None]


@dataclass
class StreamCallbacks:
    """Набор колбэков стриминга."""

    #: Текстовые дельты ответа.
    on_text: Optional[TextCallback] = None
    #: Дельты рассуждений (только отображение).
    on_reasoning: Optional[TextCallback] = None
    #: События инструментов: (старт/прогресс/завершение) + данные.
    on_tool_event: Optional[EventCallback] = None
    #: Промежуточное ассистентское сообщение.
    on_intermediate: Optional[TextCallback] = None

    def emit_text(self, delta: str) -> None:
        if delta and self.on_text:
            self.on_text(delta)

    def emit_reasoning(self, delta: str) -> None:
        """Рассуждения — только для отображения, не в контент."""
        if delta and self.on_reasoning:
            self.on_reasoning(delta)

    def emit_tool_event(self, event: str, data: Optional[dict[str, Any]] = None) -> None:
        if self.on_tool_event:
            self.on_tool_event(event, data or {})

    def emit_intermediate(self, text: str) -> None:
        if text and self.on_intermediate:
            self.on_intermediate(text)


def collect_stream(callbacks: StreamCallbacks) -> tuple[list[str], list[str]]:
    """Вспомогательная обёртка для тестов: сбор накопленных дельт."""
    texts: list[str] = []
    reasonings: list[str] = []
    original_text = callbacks.on_text
    original_reasoning = callbacks.on_reasoning

    def capture_text(delta: str) -> None:
        texts.append(delta)
        if original_text:
            original_text(delta)

    def capture_reasoning(delta: str) -> None:
        reasonings.append(delta)
        if original_reasoning:
            original_reasoning(delta)

    callbacks.on_text = capture_text
    callbacks.on_reasoning = capture_reasoning
    return texts, reasonings
