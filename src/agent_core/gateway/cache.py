"""LRU-кэш агентов по сессиям.

Гейтвей создаёт агента на сессию один раз и переиспользует его между ходами
ради кэша префикса промпта. Кэш ограничен по размеру и времени простоя
(TTL); вытеснение (по размеру, по TTL или явное) вызывает выгрузку ресурсов
агента.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class _Entry:
    agent: Any
    last_used: float


class AgentCache:
    """LRU-кэш агентов с лимитом размера и TTL простоя."""

    def __init__(
        self,
        max_size: int = 8,
        ttl_seconds: float = 600.0,
        on_evict: Optional[Callable[[str, Any], None]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.on_evict = on_evict
        self._clock = clock
        #: session_key -> _Entry (порядок — от LRU к MRU).
        self._items: OrderedDict[str, _Entry] = OrderedDict()

    def get(self, session: str) -> Any:
        """Вернуть агента сессии (и освежить его LRU-позицию).

        Агент, простоявший дольше TTL, вытесняется (выгружается) и возвращается
        ``None``.
        """
        entry = self._items.get(session)
        if entry is None:
            return None
        now = self._clock()
        if now - entry.last_used > self.ttl_seconds:
            self._evict(session, entry)
            return None
        entry.last_used = now
        self._items.move_to_end(session)
        return entry.agent

    def put(self, session: str, agent: Any) -> None:
        """Положить агента в кэш (перезапись существующего освежает его)."""
        if session in self._items:
            self._items.move_to_end(session)
        self._items[session] = _Entry(agent=agent, last_used=self._clock())
        self._trim()

    def evict(self, session: str) -> bool:
        """Явно вытеснить агента сессии; True, если он был в кэше."""
        entry = self._items.pop(session, None)
        if entry is None:
            return False
        self._unload(session, entry.agent)
        return True

    def clear(self) -> None:
        """Выгрузить всех агентов и очистить кэш."""
        for session, entry in list(self._items.items()):
            self._unload(session, entry.agent)
        self._items.clear()

    def _trim(self) -> None:
        while len(self._items) > self.max_size:
            session, entry = self._items.popitem(last=False)
            self._unload(session, entry.agent)

    def _evict(self, session: str, entry: _Entry) -> None:
        del self._items[session]
        self._unload(session, entry.agent)

    def _unload(self, session: str, agent: Any) -> None:
        if self.on_evict is not None:
            self.on_evict(session, agent)
            return
        unload = getattr(agent, "unload", None) or getattr(agent, "close", None)
        if callable(unload):
            unload()

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, session: str) -> bool:
        return session in self._items
