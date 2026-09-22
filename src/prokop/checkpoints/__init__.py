"""Снимки состояния и откат.

- :mod:`prokop.checkpoints.store` — хранилище снимков (создание, список,
  восстановление, удаление старых) поверх домашнего каталога профиля;
- :mod:`prokop.checkpoints.tool` — инструмент агента `checkpoint`
  (регистрируется в наборе `checkpoints` при импорте).

Никаких теней ФС и симлинков: содержимое копируется, поэтому поведение
одинаково на Windows, macOS и Linux.
"""

from __future__ import annotations

from prokop.checkpoints.store import (
    CheckpointError,
    CheckpointStore,
    RestoreReport,
    Snapshot,
    SnapshotEntry,
)

# Импорт регистрирует инструмент агента (пакетный шаблон саморегистрации).
from prokop.checkpoints import tool as _tool  # noqa: F401

__all__ = [
    "CheckpointError",
    "CheckpointStore",
    "RestoreReport",
    "Snapshot",
    "SnapshotEntry",
]
