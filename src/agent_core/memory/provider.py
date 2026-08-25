"""Контракт провайдера памяти.

Провайдер памяти — подключаемый бэкенд, активируемый именем через
конфигурацию. Встроенный провайдер всегда первый; одновременно активен
максимум один внешний.
"""

from __future__ import annotations

import json
from abc import ABC
from typing import Any, Optional


class MemoryProvider(ABC):
    """Абстрактный провайдер памяти."""

    #: Имя провайдера (ключ в конфигурации ``memory.provider``).
    name: str = "abstract"

    def init(
        self,
        *,
        session_id: Optional[str] = None,
        home: Optional[str] = None,
        platform: Optional[str] = None,
        agent_context: Optional[dict[str, Any]] = None,
        agent_identity: Optional[dict[str, Any]] = None,
    ) -> None:
        """Инициализация перед первым ходом."""

    def is_available(self) -> bool:
        """Доступен ли провайдер в текущем окружении."""
        return True

    def system_prompt_block(self) -> str:
        """Статичный блок системного промпта (может быть пустым)."""
        return ""

    async def prefetch(self, query: str) -> str:
        """Предзагрузка контекста перед ходом."""
        return ""

    async def queue_prefetch(self, query: str) -> None:
        """Фоновая предзагрузка на следующий ход."""

    async def sync_turn(
        self,
        user_message: str,
        assistant_message: str,
        messages: list[dict[str, Any]],
    ) -> None:
        """Синхронизация завершённого хода."""

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Схемы инструментов провайдера (могут быть пустыми)."""
        return []

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> str:
        """Обработка вызова инструмента провайдера (возврат — JSON-строка)."""
        return json.dumps({"error": "неизвестный инструмент"}, ensure_ascii=False)

    async def shutdown(self) -> None:
        """Остановка и сброс ресурсов."""

    # --- опциональные хуки -------------------------------------------

    async def on_turn_start(self) -> None:
        pass

    async def on_session_end(self) -> None:
        pass

    async def on_session_switch(self, session_id: str) -> None:
        pass

    async def on_pre_compress(self, messages: list[dict[str, Any]]) -> None:
        pass

    async def on_memory_write(self, key: str, value: str) -> None:
        pass

    async def on_delegation(self, task: str) -> None:
        pass

    def backup_paths(self) -> list[str]:
        return []


class BuiltinMemoryProvider(MemoryProvider):
    """Встроенный провайдер памяти (всегда первый в менеджере)."""

    name = "builtin"

    def __init__(self) -> None:
        self._facts: dict[str, str] = {}

    def system_prompt_block(self) -> str:
        return "У агента есть постоянная память; важные факты сохраняются через инструменты памяти."

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> str:
        if name == "memory_write":
            key = str(args.get("key") or "")
            value = str(args.get("value") or "")
            if not key:
                return json.dumps({"error": "не задан ключ"}, ensure_ascii=False)
            self._facts[key] = value
            await self.on_memory_write(key, value)
            return json.dumps({"ok": True}, ensure_ascii=False)
        if name == "memory_read":
            return json.dumps(self._facts, ensure_ascii=False)
        return await super().handle_tool_call(name, args)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory_write",
                    "description": "Сохранить факт в постоянную память.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string"},
                            "value": {"type": "string"},
                        },
                        "required": ["key", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_read",
                    "description": "Прочитать все сохранённые факты.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]
