"""Командная строка `prokop`.

Точка входа делает ядро самодостаточным: ход агента, сессии, планировщик,
навыки, провайдеры, конфигурация и диагностика — из терминала, одинаково на
Windows, macOS и Linux.

Модуль не содержит логики ядра: команды вызывают существующие модули
(`loop`, `store`, `cron`, `skills`, `providers`, `config`), а расположение
состояния резолвится только через `prokop.home` / `prokop.paths`.
"""

from __future__ import annotations

from prokop.cli.main import main

__all__ = ["main"]
