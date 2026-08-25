"""Потокобезопасный бюджет итераций субагента.

Каждый субагент владеет собственным счётчиком с потолком, независимым от
родителя. После исчерпания лимита допускается один «грациозный»
завершающий вызов. Счётчик потокобезопасен, потому что субагент может
исполняться в отдельной задаче/потоке параллельно с родителем.
"""

from __future__ import annotations

import threading


class IterationBudget:
    """Потокобезопасный счётчик итераций с потолком и грациозным вызовом."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._used = 0
        self._grace_used = False

    def can_call_model(self) -> bool:
        """Разрешён ли следующий вызов модели."""
        with self._lock:
            if self.limit is None:
                return True
            if self._used < self.limit:
                return True
            return not self._grace_used

    def consume_iteration(self) -> None:
        """Учесть выполненный вызов модели."""
        with self._lock:
            self._used += 1
            if self.limit is not None and self._used > self.limit:
                self._grace_used = True

    @property
    def iterations_used(self) -> int:
        with self._lock:
            return self._used

    @property
    def grace_allowed(self) -> bool:
        """Доступен ли грациозный завершающий вызов."""
        with self._lock:
            if self.limit is None:
                return False
            return self._used >= self.limit and not self._grace_used

    @property
    def exhausted(self) -> bool:
        """Потолок достигнут (ребёнок усечён по бюджету)."""
        with self._lock:
            return self.limit is not None and self._used >= self.limit
