"""Терминальный интерфейс `prokop`.

- :mod:`prokop.tui.state` — чистая логика: состояние сессии и слэш-команды
  (без зависимости от терминала, тестируется в CI);
- :mod:`prokop.tui.app` — интерактивный цикл на `prompt_toolkit`
  (опциональная зависимость, extra ``tui``); импортируется лениво, чтобы
  отсутствие пакета не ломало импорт ядра.
"""

from __future__ import annotations

from prokop.tui.state import CommandOutcome, TuiState, handle_command

__all__ = ["CommandOutcome", "TuiState", "handle_command"]
