"""Контроль активного хода: прерывание, steer, redirect.

Прерывание — мягкая остановка цикла из другого потока; сигнал
распространяется на долгие инструменты, параллельные воркеры и субагентов.
Есть «жёсткая» форма — явная остановка, не маскируемая даже во время
компрессии. Steer — впрыск текста в результат последнего инструмента без
остановки. Redirect — отмена текущего запроса модели с сохранением
завершённых результатов и повтором хода с коррекцией.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SteerState:
    """Накопленные steer-тексты до точки слия."""

    pending: list[str] = field(default_factory=list)

    def add(self, text: str) -> None:
        self.pending.append(text)

    def take_all(self) -> Optional[str]:
        """Слить накопленные тексты; несколько конкатенируются."""
        if not self.pending:
            return None
        merged = "\n".join(self.pending)
        self.pending.clear()
        return merged


class TurnControl:
    """Сигналы управления активным ходом (потокобезопасные)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._soft_stop = False
        self._hard_stop = False
        self.steer = SteerState()
        self.redirect_text: Optional[str] = None

    # --- прерывание -----------------------------------------------------

    def interrupt(self, *, hard: bool = False) -> None:
        """Запросить остановку цикла.

        ``hard=True`` — жёсткая остановка, не маскируемая даже во время
        компрессии.
        """
        with self._lock:
            if hard:
                self._hard_stop = True
            else:
                self._soft_stop = True

    @property
    def stop_requested(self) -> bool:
        with self._lock:
            return self._soft_stop or self._hard_stop

    @property
    def hard_stop(self) -> bool:
        with self._lock:
            return self._hard_stop

    def clear_stop(self) -> None:
        with self._lock:
            self._soft_stop = False
            self._hard_stop = False

    # --- steer -------------------------------------------------------------

    def steer_text(self, text: str) -> None:
        """Добавить steer-текст (впрыскивается в вывод инструмента)."""
        self.steer.add(text)

    def take_steer(self) -> Optional[str]:
        """Забрать накопленный steer-текст для следующей итерации."""
        return self.steer.take_all()

    # --- redirect -------------------------------------------------------------

    def redirect(self, correction: str) -> None:
        """Запросить перенаправление хода с коррекцией.

        Отменяется только текущий запрос модели; завершённые результаты
        инструментов сохраняются, коррекция добавляется как пользовательское
        сообщение, ход повторяется.
        """
        with self._lock:
            self.redirect_text = correction

    def take_redirect(self) -> Optional[str]:
        with self._lock:
            text = self.redirect_text
            self.redirect_text = None
            return text

    @property
    def redirect_pending(self) -> bool:
        with self._lock:
            return self.redirect_text is not None
