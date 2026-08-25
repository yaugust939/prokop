"""Единый резолвер домашнего каталога профиля.

Все файловые пути ядра (база данных, конфиг, логи, пользовательские
провайдеры) резолвятся через одну точку входа — функции этого модуля.
Никакой модуль ядра не должен жёстко прописывать абсолютные пути.

Правило разрешения базы домашних каталогов (первый подходящий выигрывает):

1. переменная окружения ``AGENT_CORE_HOME``;
2. системный каталог данных текущей платформы:
   - Windows — ``%LOCALAPPDATA%\\AgentCore``;
   - macOS — ``~/Library/Application Support/AgentCore``;
   - прочие POSIX — ``$XDG_DATA_HOME/agent_core`` или ``~/.local/share/agent_core``.

Профиль изолирует состояние: каталог профиля — это подкаталог базы
(``profiles/<имя>``), поэтому «несколько профилей» пишутся в собственные
домашние каталоги без пересечения.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

#: Имя профиля по умолчанию.
DEFAULT_PROFILE = "default"

#: Переменная окружения, переопределяющая базу домашних каталогов.
ENV_HOME = "AGENT_CORE_HOME"

#: Имя подкаталога профиля внутри базы домашних каталогов.
_PROFILES_DIR = "profiles"

#: Имя подкаталога с пользовательскими провайдерами (YAML/Python).
PROVIDERS_DIR = "providers"

#: Имя подкаталога с пользовательскими провайдерами памяти.
MEMORY_PROVIDERS_DIR = "memory_providers"

#: Имя подкаталога логов.
LOGS_DIR = "logs"

#: Имя файла базы данных сессий.
DATABASE_NAME = "sessions.db"


def _system_data_base() -> Path:
    """Возвращает системный каталог данных для данного приложения."""
    if sys.platform == "win32":
        root = os.environ.get("LOCALAPPDATA")
        if root:
            return Path(root) / "AgentCore"
        root = os.environ.get("APPDATA")
        if root:
            return Path(root) / "AgentCore"
        return Path.home() / "AppData" / "Local" / "AgentCore"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "AgentCore"
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "agent_core"
    return Path.home() / ".local" / "share" / "agent_core"


def resolve_base() -> Path:
    """Возвращает базу домашних каталогов (без профиля)."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return _system_data_base()


def resolve_home(profile: str | None = None) -> Path:
    """Возвращает домашний каталог указанного профиля.

    Каталог не создаётся на диске — только вычисляется путь.
    """
    name = profile or DEFAULT_PROFILE
    return resolve_base() / _PROFILES_DIR / name


def resolve_config_path(profile: str | None = None) -> Path:
    """Возвращает путь к ``config.yaml`` профиля."""
    return resolve_home(profile) / "config.yaml"


def resolve_data_path(profile: str | None = None) -> Path:
    """Возвращает каталог данных профиля (создаётся при записи)."""
    return resolve_home(profile)


def resolve_database_path(profile: str | None = None) -> Path:
    """Возвращает путь к SQLite-базе сессий профиля."""
    return resolve_home(profile) / DATABASE_NAME


def resolve_logs_path(profile: str | None = None) -> Path:
    """Возвращает каталог логов профиля."""
    return resolve_home(profile) / LOGS_DIR


def resolve_providers_dir(profile: str | None = None) -> Path:
    """Возвращает каталог пользовательских провайдеров профиля."""
    return resolve_home(profile) / PROVIDERS_DIR


def resolve_memory_providers_dir(profile: str | None = None) -> Path:
    """Возвращает каталог пользовательских провайдеров памяти профиля."""
    return resolve_home(profile) / MEMORY_PROVIDERS_DIR


def ensure_home(profile: str | None = None) -> Path:
    """Создаёт (при необходимости) и возвращает домашний каталог профиля."""
    home = resolve_home(profile)
    home.mkdir(parents=True, exist_ok=True)
    return home


def ensure_logs_dir(profile: str | None = None) -> Path:
    """Создаёт и возвращает каталог логов профиля."""
    path = resolve_logs_path(profile)
    path.mkdir(parents=True, exist_ok=True)
    return path
