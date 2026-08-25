"""Настройка логирования ядра.

Предоставляет единый корневой логгер ``prokop`` и функцию конфигурации,
которая:

- задаёт уровень из конфигурации или переменной окружения ``PROKOP_LOG_LEVEL``;
- опционально добавляет файловый обработчик в каталог логов профиля;
- не добавляет дублирующиеся обработчики при повторных вызовах.

Модули ядра получают логгер через :func:`get_logger` и не конфигурируют
логирование самостоятельно.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

from .paths import ensure_logs_dir, resolve_logs_path

#: Корневой логгер ядра.
ROOT_LOGGER = "prokop"

#: Переменная окружения, переопределяющая уровень логирования.
ENV_LEVEL = "PROKOP_LOG_LEVEL"

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Маркер уже добавленного файлового обработчика (для идемпотентности).
_MARKER = "_prokop_file_handler"


def _resolve_level(level: str | None) -> int:
    if not level:
        return logging.INFO
    normalized = level.upper()
    return getattr(logging, normalized, logging.INFO)


def get_logger(name: str | None = None) -> logging.Logger:
    """Возвращает логгер под именем ``prokop[.<name>]``."""
    if name:
        return logging.getLogger(f"{ROOT_LOGGER}.{name}")
    return logging.getLogger(ROOT_LOGGER)


def configure(
    level: str | None = None,
    to_file: bool = False,
    profile: str | None = None,
    filename: str | None = None,
) -> logging.Logger:
    """Конфигурирует корневой логгер и возвращает его.

    Параметры:
        level: уровень логирования (по умолчанию — из ``PROKOP_LOG_LEVEL``).
        to_file: добавлять ли файловый обработчик.
        profile: профиль, в каталог логов которого пишется файл.
        filename: имя файла лога (по умолчанию ``prokop.log``).
    """
    root = get_logger()
    effective = level or os.environ.get(ENV_LEVEL)
    root.setLevel(_resolve_level(effective))

    if not root.handlers:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
        root.addHandler(console)

    if to_file:
        existing = getattr(root, _MARKER, None)
        if existing is None:
            logs_dir = resolve_logs_path(profile)
            try:
                ensure_logs_dir(profile)
            except OSError:
                return root
            fh = logging.FileHandler(
                logs_dir / (filename or "prokop.log"), encoding="utf-8"
            )
            fh.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
            root.addHandler(fh)
            setattr(root, _MARKER, fh)

    root.propagate = False
    return root
