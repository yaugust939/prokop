"""Разрешение провайдера памяти по конфигурации профиля.

Закрывает разрыв, из-за которого `memory.provider` из конфигурации ни на что не
влиял: имя превращается в реализацию и подключается к менеджеру памяти как
внешний провайдер.

Правила: пустое имя и ``builtin`` означают «только встроенная память»;
неизвестное имя даёт предупреждение и тоже оставляет встроенную память —
опечатка в конфигурации не должна ломать запуск агента.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from prokop.config import Config
from prokop.logging_setup import get_logger
from prokop.memory.file_provider import (
    DEFAULT_MAX_RECORDS,
    DEFAULT_PREFETCH_LIMIT,
    MEMORY_FILENAME,
    FileMemoryProvider,
)
from prokop.memory.manager import MemoryManager
from prokop.memory.provider import MemoryProvider

log = get_logger("memory.factory")

#: Имя, означающее «только встроенная память».
BUILTIN = "builtin"

ProviderFactory = Callable[[Path, Mapping[str, Any]], MemoryProvider]


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value) if value > 0 else default


def _build_file(home: Path, options: Mapping[str, Any]) -> MemoryProvider:
    return FileMemoryProvider(
        home,
        filename=str(options.get("filename") or MEMORY_FILENAME),
        max_records=_positive_int(options.get("max_records"), DEFAULT_MAX_RECORDS),
        prefetch_limit=_positive_int(options.get("prefetch_limit"), DEFAULT_PREFETCH_LIMIT),
    )


#: Доступные внешние провайдеры: имя → фабрика.
PROVIDERS: dict[str, ProviderFactory] = {
    "file": _build_file,
}


def available_providers() -> list[str]:
    """Имена доступных провайдеров (включая встроенный)."""
    return [BUILTIN, *sorted(PROVIDERS)]


def build_provider(config: Config, home: Path) -> Optional[MemoryProvider]:
    """Внешний провайдер по конфигурации профиля (или ``None``)."""
    name = (config.memory.provider or "").strip().lower()
    if not name or name == BUILTIN:
        return None

    factory = PROVIDERS.get(name)
    if factory is None:
        log.warning(
            "Провайдер памяти %r неизвестен; используется встроенная память. Доступны: %s",
            name,
            ", ".join(available_providers()),
        )
        return None

    try:
        return factory(Path(home), config.memory.options or {})
    except Exception as exc:  # noqa: BLE001 — сбой провайдера не роняет агента
        log.warning("Провайдер памяти %r не инициализирован: %s", name, exc)
        return None


def build_manager(config: Config, home: Path) -> MemoryManager:
    """Менеджер памяти с подключённым внешним провайдером (если задан)."""
    manager = MemoryManager()
    provider = build_provider(config, home)
    if provider is not None:
        manager.set_external(provider)
    return manager
