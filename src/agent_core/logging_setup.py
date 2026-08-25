"""Настройка логирования ядра."""

from __future__ import annotations

import logging
import sys

LOGGER_NAME = "agent_core"


def get_logger(name: str | None = None) -> logging.Logger:
    """Логгер внутри пространства имён ``agent_core``."""
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)


def configure(level: str = "INFO", stream=sys.stderr) -> logging.Logger:
    """Инициализировать логирование (идемпотентно)."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if not logger.handlers:
        handler = logging.StreamHandler(stream)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    return logger
