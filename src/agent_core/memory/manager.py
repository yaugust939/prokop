"""Менеджер памяти.

Встроенный провайдер всегда первый; максимум один внешний провайдер
одновременно. Фан-аут вызовов ко всем провайдерам: сбой одного не
блокирует остальных. Фоновый воркер сериализует записи «ход N раньше
хода N+1».
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Optional

from agent_core.logging_setup import get_logger
from agent_core.memory.provider import BuiltinMemoryProvider, MemoryProvider

log = get_logger("memory.manager")

#: Максимум внешних провайдеров одновременно.
MAX_EXTERNAL_PROVIDERS = 1


class MemoryManager:
    """Оркестрация провайдеров памяти."""

    def __init__(self, builtin: Optional[MemoryProvider] = None) -> None:
        self.builtin = builtin or BuiltinMemoryProvider()
        self.external: Optional[MemoryProvider] = None
        self._queue: asyncio.Queue[tuple[int, str, tuple, dict]] = asyncio.Queue()
        self._worker: Optional[asyncio.Task] = None
        self._turn_counter = 0

    # --- состав -------------------------------------------------------

    def providers(self) -> list[MemoryProvider]:
        """Список активных провайдеров: встроенный первый."""
        if self.external is not None:
            return [self.builtin, self.external]
        return [self.builtin]

    def set_external(self, provider: MemoryProvider) -> None:
        """Подключить внешний провайдер (не более одного)."""
        self.external = provider

    async def init(self, **kwargs: Any) -> None:
        """Инициализировать все активные провайдеры."""
        for provider in self.providers():
            with contextlib.suppress(Exception):
                provider.init(**kwargs)

    # --- системный промпт ----------------------------------------------

    def system_prompt_block(self) -> str:
        """Статичный блок системного промпта от всех провайдеров."""
        blocks = [p.system_prompt_block() for p in self.providers()]
        return "\n".join(b for b in blocks if b)

    # --- префетч ---------------------------------------------------------

    async def prefetch(self, query: str) -> str:
        """Предзагрузка контекста перед ходом (объединённая)."""
        parts: list[str] = []
        for provider in self.providers():
            try:
                text = await provider.prefetch(query)
            except Exception as exc:  # noqa: BLE001 — сбой не блокирует остальных
                log.warning("prefetch провайдера %s не удался: %s", provider.name, exc)
                continue
            if text:
                parts.append(text)
        return "\n".join(parts)

    async def queue_prefetch(self, query: str) -> None:
        """Фоновая предзагрузка на следующий ход."""
        for provider in self.providers():
            with contextlib.suppress(Exception):
                await provider.queue_prefetch(query)

    # --- синхронизация ходов (сериализованная) --------------------------

    async def sync_turn(
        self,
        user_message: str,
        assistant_message: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Запланировать синхронизацию хода в фоновом воркере.

        Записи сериализуются: ход N обрабатывается раньше хода N+1.
        """
        self._turn_counter += 1
        await self._queue.put((self._turn_counter, "sync_turn", (user_message, assistant_message, messages), {}))
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.get_event_loop().create_task(self._run())

    async def _run(self) -> None:
        while not self._queue.empty():
            _seq, method, args, kwargs = await self._queue.get()
            for provider in self.providers():
                try:
                    await getattr(provider, method)(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    log.warning("%s провайдера %s не удался: %s", method, provider.name, exc)

    # --- инструменты ------------------------------------------------------

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Объединённые схемы инструментов провайдеров."""
        schemas: list[dict[str, Any]] = []
        for provider in self.providers():
            schemas.extend(provider.get_tool_schemas())
        return schemas

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> Optional[str]:
        """Маршрутизация вызова инструмента провайдера памяти."""
        for provider in self.providers():
            known = {
                schema["function"]["name"] for schema in provider.get_tool_schemas()
            }
            if name in known:
                return await provider.handle_tool_call(name, args)
        return None

    # --- остановка ---------------------------------------------------------

    async def shutdown(self) -> None:
        """Ограниченный дренаж очереди и остановка провайдеров."""
        if self._worker is not None:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._worker, timeout=5.0)
        for provider in self.providers():
            with contextlib.suppress(Exception):
                await provider.shutdown()
