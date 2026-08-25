"""Терминальные бэкенды: абстракция окружения исполнения."""

from prokop.backends.base import TerminalBackend
from prokop.backends.errors import InfrastructureError
from prokop.backends.local import LocalBackend
from prokop.backends.result import CommandResult
from prokop.backends.snapshot import SessionSnapshot
from prokop.backends.config import BackendConfig, resolve_backend

__all__ = [
    "TerminalBackend",
    "InfrastructureError",
    "LocalBackend",
    "CommandResult",
    "SessionSnapshot",
    "BackendConfig",
    "resolve_backend",
]
