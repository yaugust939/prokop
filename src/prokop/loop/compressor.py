"""Онлайн-компрессия контекста.

Когда размер контекста подходит к порогу, средние ходы сжимаются в сводку.
Защищаются «голова» (первые сообщения) и «хвост» (последние); границы
выравниваются так, чтобы не разрезать пары «вызов инструмента → результат».
Сводка имеет детерминированный префикс и генерируется вспомогательной
моделью (с фолбэком на статический шаблон при сбое). Компрессия —
единственное разрешённое исключение из байт-стабильности системного
промпта.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from prokop.loop.messages import Message

#: Детерминированный префикс сводки.
SUMMARY_PREFIX = "[CONTEXT SUMMARY]: "

#: Счётчик попыток и кулдаун против трешинга.
MAX_COMPRESSION_ATTEMPTS = 3

Summarizer = Callable[[list[Message]], Awaitable[str]]


@dataclass
class CompressionPlan:
    """План компрессии: какие позиции сжимаются в сводку."""

    summary_positions: list[int]
    head_count: int
    tail_count: int


def _tool_call_pairs(messages: list[Message]) -> list[tuple[int, int]]:
    """Пары (ассистент с вызовом, результат инструмента)."""
    pairs: list[tuple[int, int]] = []
    for i, message in enumerate(messages):
        if message.role == "assistant" and message.tool_calls:
            j = i + 1
            while j < len(messages) and messages[j].role == "tool":
                pairs.append((i, j))
                j += 1
    return pairs


def plan_compression(
    messages: list[Message],
    *,
    head_protected: int = 2,
    tail_protected: int = 4,
) -> CompressionPlan:
    """Определить границы компрессии с защитой головы/хвоста.

    Граница середины выравнивается так, чтобы не разрезать пару
    «вызов инструмента → результат».
    """
    n = len(messages)
    head = min(head_protected, n)
    tail = min(tail_protected, max(0, n - head))
    middle_end = n - tail

    pairs = _tool_call_pairs(messages)
    for call_pos, result_pos in pairs:
        # Если граница середины разрезает пару — отодвигаем её за результат.
        if call_pos < middle_end <= result_pos:
            middle_end = result_pos + 1

    positions = list(range(head, middle_end))
    return CompressionPlan(summary_positions=positions, head_count=head, tail_count=tail)


def fallback_summary(messages: list[Message]) -> str:
    """Статический шаблон сводки при сбое вспомогательной модели."""
    compressed = [m for i, m in enumerate(messages)]
    tools = sum(1 for m in compressed if m.role == "tool")
    return f"Сжато {len(compressed)} сообщений ({tools} результатов инструментов). Детали опущены."


async def compress_context(
    messages: list[Message],
    summarizer: Optional[Summarizer] = None,
    *,
    head_protected: int = 2,
    tail_protected: int = 4,
) -> list[Message]:
    """Сжать контекст и вернуть новую историю.

    Порядок: план → сводка (вспомогательная модель или фолбэк) → замена
    середины на одно маркированное сообщение. Голова и хвост сохраняются,
    пары вызов/результат не разрезаются.
    """
    plan = plan_compression(messages, head_protected=head_protected, tail_protected=tail_protected)
    if not plan.summary_positions:
        return list(messages)

    middle = [messages[i] for i in plan.summary_positions]
    summary_text: str
    if summarizer is not None:
        try:
            summary_text = await summarizer(middle)
        except Exception:  # noqa: BLE001 — фолбэк на статический шаблон
            summary_text = fallback_summary(middle)
    else:
        summary_text = fallback_summary(middle)

    summary_message = Message(
        role="user",
        content=f"{SUMMARY_PREFIX}{summary_text}",
    )
    head = messages[: plan.head_count]
    tail = messages[len(messages) - plan.tail_count :] if plan.tail_count else []
    return list(head) + [summary_message] + list(tail)


def is_summary(content: Optional[str]) -> bool:
    """Распознать маркированную сводку в истории."""
    return bool(content) and content.startswith(SUMMARY_PREFIX)
