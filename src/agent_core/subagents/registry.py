"""Реестр активных субагентов (в рамках одного процесса).

Потокобезопасный реестр с потолком одновременных детей. Операции: регистрация
(с отказом при насыщении), список, получить, обновить прогресс, подрулить
(steer), остановить, удалить. Внутреннее состояние записей мутируется только
под замком реестра.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

from agent_core.subagents.model import SubagentRecord, SubagentStatus


class RegistrySaturatedError(Exception):
    """Потолок одновременных детей исчерпан."""


class SubagentRegistry:
    """Потокобезопасный реестр активных субагентов."""

    def __init__(self, max_children: int) -> None:
        self.max_children = max(1, int(max_children))
        self._lock = threading.Lock()
        self._records: dict[str, SubagentRecord] = {}

    # --- регистрация -----------------------------------------------------

    def register(self, record: SubagentRecord) -> SubagentRecord:
        """Зарегистрировать субагента; при насыщении — отказ."""
        with self._lock:
            if len(self._records) >= self.max_children:
                raise RegistrySaturatedError(
                    f"Потолок одновременных детей исчерпан ({self.max_children})"
                )
            self._records[record.id] = record
            return record

    # --- чтение ------------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        """Публичный список активных субагентов."""
        with self._lock:
            return [r.snapshot() for r in self._records.values()]

    def get(self, subagent_id: str) -> Optional[SubagentRecord]:
        with self._lock:
            return self._records.get(subagent_id)

    def active_count(self) -> int:
        with self._lock:
            return len(self._records)

    # --- управление ----------------------------------------------------------

    def update_progress(self, subagent_id: str, progress: str) -> bool:
        with self._lock:
            record = self._records.get(subagent_id)
            if record is None:
                return False
            record.progress = progress
            return True

    def steer(self, subagent_id: str, text: str) -> bool:
        """Накопить steer-текст для субагента."""
        with self._lock:
            record = self._records.get(subagent_id)
            if record is None:
                return False
            record.steer_texts.append(text)
            return True

    def take_steer(self, subagent_id: str) -> Optional[str]:
        """Забрать накопленный steer-текст (несколько конкатенируются)."""
        with self._lock:
            record = self._records.get(subagent_id)
            if record is None or not record.steer_texts:
                return None
            merged = "\n".join(record.steer_texts)
            record.steer_texts.clear()
            return merged

    def stop(self, subagent_id: str) -> bool:
        """Пометить субагента остановленным и запросить остановку.

        Идемпотентно: повторный вызов по уже остановленному субагенту
        возвращает ``False``.
        """
        with self._lock:
            record = self._records.get(subagent_id)
            if record is None or record.stop_requested:
                return False
            record.status = SubagentStatus.STOPPED.value
            record.stop_requested = True
            return True

    def stop_requested(self, subagent_id: str) -> bool:
        with self._lock:
            record = self._records.get(subagent_id)
            return bool(record and record.stop_requested)

    def remove(self, subagent_id: str) -> bool:
        with self._lock:
            return self._records.pop(subagent_id, None) is not None
