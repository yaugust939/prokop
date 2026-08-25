"""Выбор терминального бэкенда из конфигурации."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from agent_core.backends.base import TerminalBackend
from agent_core.backends.errors import InfrastructureError
from agent_core.backends.local import LocalBackend

#: Значение по умолчанию.
DEFAULT_BACKEND_TYPE = "local"


@dataclass
class BackendConfig:
    """Конфигурация секции терминала."""

    type: str = DEFAULT_BACKEND_TYPE
    workdir: Optional[str] = None
    timeout: Optional[float] = None
    #: Специфичные для бэкендов настройки (образы, хосты и т.д.).
    extra: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}


def resolve_backend(
    config: BackendConfig,
    *,
    snapshot_path: Optional[str] = None,
    dump_dir: Optional[str] = None,
) -> TerminalBackend:
    """Построить бэкенд по конфигурации.

    Неизвестный тип — инфраструктурный сбой (не путать со сбоем команды).
    """
    if config.type == "local":
        return LocalBackend(
            workdir=config.workdir,
            timeout=config.timeout,
            snapshot_path=snapshot_path,
            dump_dir=dump_dir,
        )
    raise InfrastructureError(f"Неизвестный тип бэкенда: {config.type}")


def backend_config_from_dict(data: dict | None) -> BackendConfig:
    """Собрать конфигурацию бэкенда из словаря секции терминала."""
    if not data:
        return BackendConfig()
    return BackendConfig(
        type=data.get("type") or DEFAULT_BACKEND_TYPE,
        workdir=data.get("workdir"),
        timeout=data.get("timeout"),
        extra={k: v for k, v in data.items() if k not in ("type", "workdir", "timeout")},
    )
