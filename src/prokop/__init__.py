"""prokop — оригинальное ядро универсального агента.

Пакет реализован по поведенческой спецификации ``openspec/changes/hermes-core``.

Подсистемы:
- ``home``, ``config``        — профили и конфигурация;
- ``providers``               — слой модельных провайдеров;
- ``store``                   — хранилище сессий и поиск;
- ``memory``                  — постоянная память;
- ``tools``                   — инструменты и наборы;
- ``skills``                  — навыки (процедурная память);
- ``loop``                    — цикл агента;
- ``transport``               — транспорт вызовов модели.
"""

from __future__ import annotations

__version__ = "0.1.0"

from prokop.home import home_dir, resolve, profile_name

__all__ = ["__version__", "home_dir", "resolve", "profile_name"]
