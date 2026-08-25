"""Аренда сессии на время хода.

Перед ходом берётся устойчивая аренда на уровне БД, чтобы несколько
процессов не писали в один разговор. Аренда периодически продлевается и
освобождается в конце; потеря аренды прерывает ход.
"""

from __future__ import annotations

import uuid
from typing import Optional

from prokop.store.sessions import SessionStore

DEFAULT_TTL_SECONDS = 60


class SessionLease:
    """Контекстный менеджер аренды сессии."""

    def __init__(
        self,
        store: SessionStore,
        session_id: str,
        *,
        owner: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        self.store = store
        self.session_id = session_id
        self.owner = owner or uuid.uuid4().hex
        self.ttl_seconds = ttl_seconds
        self.held = False

    def __enter__(self) -> "SessionLease":
        self.held = self.store.acquire_lease(
            self.session_id, self.owner, ttl_seconds=self.ttl_seconds
        )
        if not self.held:
            raise LeaseLostError(f"Сессия занята другим процессом: {self.session_id}")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def refresh(self) -> bool:
        """Продлить аренду; ``False`` означает её потерю."""
        if not self.held:
            return False
        ok = self.store.refresh_lease(self.session_id, self.owner, ttl_seconds=self.ttl_seconds)
        if not ok:
            self.held = False
        return ok

    def release(self) -> None:
        if self.held:
            self.store.release_lease(self.session_id, self.owner)
            self.held = False


class LeaseLostError(RuntimeError):
    """Аренда потеряна или занята другим процессом."""
