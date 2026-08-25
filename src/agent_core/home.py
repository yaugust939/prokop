"""Единый резолвер домашнего каталога профиля.

Весь код, читающий или пишущий состояние, резолвит пути через этот модуль,
а не использует жёсткие пути. Поддерживаются множественные изолированные
профили с собственным домашним каталогом.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

ENV_HOME = "AGENT_CORE_HOME"
ENV_PROFILE = "AGENT_CORE_PROFILE"
DEFAULT_ROOT_NAME = ".agent_core"
DEFAULT_PROFILE = "default"


@lru_cache(maxsize=None)
def _root() -> Path:
    """Корневой каталог профилей (кэшируется)."""
    root = os.environ.get(ENV_HOME)
    if root:
        return Path(root).expanduser().resolve()
    return Path.home() / DEFAULT_ROOT_NAME


def root_dir() -> Path:
    """Корневой каталог всех профилей."""
    return _root()


def profile_name() -> str:
    """Имя активного профиля (из окружения, иначе ``default``)."""
    return os.environ.get(ENV_PROFILE) or DEFAULT_PROFILE


def home_dir() -> Path:
    """Домашний каталог активного профиля (создаётся при отсутствии)."""
    path = _root() / profile_name()
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve(*parts: str) -> Path:
    """Разрешить путь относительно домашнего каталога профиля."""
    return home_dir().joinpath(*parts)


def reset_cache() -> None:
    """Сбросить кэш корня (переключение профиля в тестах)."""
    _root.cache_clear()
