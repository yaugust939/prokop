"""Бюджеты хода: итерации и настенные часы.

Число вызовов модели ограничено бюджетом итераций (общим для родителя и
субагентов); после исчерпания допускается один «грациозный» завершающий
вызов. Отдельный бюджет по настенным часам: при пересечении 80% в контекст
впрыскивается одноразовая заметка о необходимости свернуть работу.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

#: Доля настенного бюджета, после которой впрыскивается заметка.
WALL_CLOCK_NOTE_THRESHOLD = 0.80

#: Текст одноразовой заметки о сворачивании.
WIND_DOWN_NOTE = (
    "Бюджет времени почти исчерпан. Сверни работу и выдай результат "
    "из текущего состояния; не начинай новые большие шаги."
)


@dataclass
class Budgets:
    """Бюджеты одного хода."""

    #: Лимит вызовов модели (None = без лимита).
    iteration_budget: int | None = None
    #: Лимит настенных секунд (None = без лимита).
    run_budget_seconds: float | None = None

    _iterations_used: int = field(default=0, init=False)
    _started_at: float | None = field(default=None, init=False)
    _grace_used: bool = field(default=False, init=False)
    _note_injected: bool = field(default=False, init=False)

    def start(self) -> None:
        """Отметить начало хода."""
        self._started_at = time.monotonic()

    # --- итерации -----------------------------------------------------

    def can_call_model(self) -> bool:
        """Разрешён ли следующий вызов модели."""
        if self.iteration_budget is None:
            return True
        if self._iterations_used < self.iteration_budget:
            return True
        # Один грациозный завершающий вызов.
        if not self._grace_used:
            return True
        return False

    def consume_iteration(self) -> None:
        """Учесть выполненный вызов модели."""
        self._iterations_used += 1
        if self.iteration_budget is not None and self._iterations_used > self.iteration_budget:
            self._grace_used = True

    @property
    def iterations_used(self) -> int:
        return self._iterations_used

    @property
    def grace_allowed(self) -> bool:
        """Доступен ли грациозный вызов."""
        if self.iteration_budget is None:
            return False
        return self._iterations_used >= self.iteration_budget and not self._grace_used

    # --- настенные часы ---------------------------------------------------

    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    def wall_time_exceeded(self) -> bool:
        if self.run_budget_seconds is None:
            return False
        return self.elapsed() >= self.run_budget_seconds

    def wind_down_note(self) -> str | None:
        """Одноразовая заметка при пересечении порога времени."""
        if self.run_budget_seconds is None or self._note_injected:
            return None
        if self.elapsed() >= self.run_budget_seconds * WALL_CLOCK_NOTE_THRESHOLD:
            self._note_injected = True
            return WIND_DOWN_NOTE
        return None
