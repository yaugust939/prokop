"""Пути состояния профиля — тонкий слой над ``prokop.home``.

Единственный источник истины о расположении состояния — модуль
:mod:`prokop.home` (``PROKOP_HOME`` или ``~/.prokop``; профиль —
``PROKOP_PROFILE`` или ``default``). Здесь живут только именованные
подкаталоги и файлы профиля (логи, база сессий, провайдеры).

Модуль намеренно **не знает о платформе**: раскладка каталогов одинакова на
Windows, macOS и Linux. Различия окружения задаются переменной
``PROKOP_HOME``, а не ветвлением по операционной системе.
"""

from __future__ import annotations

from pathlib import Path

from . import home

#: Имя профиля по умолчанию (реэкспорт из ``home``).
DEFAULT_PROFILE = home.DEFAULT_PROFILE

#: Переменная окружения, переопределяющая базу домашних каталогов.
ENV_HOME = home.ENV_HOME

#: Имя подкаталога с пользовательскими провайдерами (YAML/Python).
PROVIDERS_DIR = "providers"

#: Имя подкаталога с пользовательскими провайдерами памяти.
MEMORY_PROVIDERS_DIR = "memory_providers"

#: Имя подкаталога логов.
LOGS_DIR = "logs"

#: Имя файла базы данных сессий.
DATABASE_NAME = "sessions.db"


def resolve_base() -> Path:
    """Возвращает базу домашних каталогов (без профиля)."""
    return home.root_dir()


def resolve_home(profile: str | None = None) -> Path:
    """Возвращает домашний каталог указанного профиля.

    Каталог не создаётся на диске — только вычисляется путь.
    """
    name = profile or home.profile_name()
    return home.root_dir() / name


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
    path = resolve_home(profile)
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_logs_dir(profile: str | None = None) -> Path:
    """Создаёт и возвращает каталог логов профиля."""
    path = resolve_logs_path(profile)
    path.mkdir(parents=True, exist_ok=True)
    return path
