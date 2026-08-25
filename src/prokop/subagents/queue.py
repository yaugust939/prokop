"""Асинхронная очередь завершённых делегирований.

Результат делегирования приходит асинхронно и лежит в очереди, пока
владелец (сессия родителя) его не заберёт. Событие завершения создаёт новый
ход, когда агент свободен, и никогда не вклинивается между результатом
инструмента и сообщением ассистента.
"""

from __future__ import annotations

import asyncio

from prokop.subagents.model import SubagentResult


class CompletionQueue:
    """Очередь самодостаточных результатов делегирования."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[SubagentResult] = asyncio.Queue()

    async def put(self, result: SubagentResult) -> None:
        await self._queue.put(result)

    def put_nowait(self, result: SubagentResult) -> None:
        self._queue.put_nowait(result)

    async def next_completion(self) -> SubagentResult:
        """Дождаться следующего завершения (когда агент свободен)."""
        return await self._queue.get()

    def drain_nowait(self) -> list[SubagentResult]:
        """Забрать все готовые завершения без ожидания."""
        results: list[SubagentResult] = []
        while True:
            try:
                results.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                return results

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()
