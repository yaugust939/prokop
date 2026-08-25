"""Терминальные бэкенды: абстракция окружения исполнения."""

from agent_core.backends.base import TerminalBackend
from agent_core.backends.errors import InfrastructureError
from agent_core.backends.local import LocalBackend
from agent_core.backends.result import CommandResult
from agent_core.backends.snapshot import SessionSnapshot
from agent_core.backends.config import BackendConfig, resolve_backend

__all__ = [
    "TerminalBackend",
    "InfrastructureError",
    "LocalBackend",
    "CommandResult",
    "SessionSnapshot",
    "BackendConfig",
    "resolve_backend",
]
