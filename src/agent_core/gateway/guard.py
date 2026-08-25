"""Защита от параллельных ходов.

На одну сессию допускается не более одного активного хода. Управляющие
команды (стоп/новый/сброс) обходят защиту и обрабатываются сразу; обычный
текст при активном ходе либо прерывает его (режим «прервать»), либо
складывается в очередь (режим «в очередь»).
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import Optional


class TurnMode(str, Enum):
    """Поведение при поступлении обычного текста во время активного хода."""

    INTERRUPT = "interrupt"
    QUEUE = "queue"


class Admit(str, Enum):
    """Итог пропуска входящего сообщения через защиту."""

    RUN = "run"            # нет активного хода — запустить
    BYPASS = "bypass"      # управляющая команда — обработать сразу
    INTERRUPT = "interrupt"  # прервать текущий ход и обработать новое
    QUEUE = "queue"        # поставить в очередь


class SessionGuard:
    """Трекинг активных ходов по сессиям и очередь отложенных ходов."""

    def __init__(self, mode: TurnMode = TurnMode.INTERRUPT) -> None:
        self.mode = mode
        #: session_key -> id активного хода.
        self._active: dict[str, str] = {}
        #: session_key -> очередь id ходов.
        self._queue: dict[str, deque[str]] = {}

    # --- решение о пропуске -------------------------------------------------

    def admit(self, session: str, *, control: bool = False) -> Admit:
        """Решить, как пропустить входящее сообщение в сессию.

        ``control=True`` означает управляющую команду — она всегда обходит
        защиту. Обычный текст при активном ходе прерывает его или ставится в
        очередь согласно ``mode``.
        """
        if control:
            return Admit.BYPASS
        if session not in self._active:
            return Admit.RUN
        if self.mode is TurnMode.INTERRUPT:
            return Admit.INTERRUPT
        return Admit.QUEUE

    # --- жизненный цикл хода ------------------------------------------------

    def start(self, session: str, turn_id: str) -> None:
        """Пометить ход активным для сессии."""
        self._active[session] = turn_id

    def finish(self, session: str, turn_id: str) -> Optional[str]:
        """Завершить ход; возвращает следующий из очереди (или None).

        Завершение чужого хода игнорируется (защита от гонок).
        """
        if self._active.get(session) == turn_id:
            del self._active[session]
        return self._pop_queued(session)

    def enqueue(self, session: str, turn_id: str) -> None:
        """Поставить ход в очередь сессии."""
        self._queue.setdefault(session, deque()).append(turn_id)

    def _pop_queued(self, session: str) -> Optional[str]:
        queue = self._queue.get(session)
        if queue:
            turn_id = queue.popleft()
            if not queue:
                del self._queue[session]
            return turn_id
        return None

    # --- интроспекция -------------------------------------------------------

    def has_active(self, session: str) -> bool:
        return session in self._active

    def active_turn(self, session: str) -> Optional[str]:
        return self._active.get(session)

    def queue_length(self, session: str) -> int:
        return len(self._queue.get(session, ()))
