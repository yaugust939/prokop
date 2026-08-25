"""Тесты постоянной памяти."""

from __future__ import annotations

import asyncio
import json

from agent_core.memory.manager import MemoryManager
from agent_core.memory.provider import BuiltinMemoryProvider, MemoryProvider
from agent_core.memory.injection import (
    wrap_memory_context,
    scrub_memory_context,
    inject_into_user_message,
    MEMORY_CONTEXT_MARKER,
)


def test_wrap_and_scrub_memory_context():
    block = wrap_memory_context("факт о пользователе")
    assert MEMORY_CONTEXT_MARKER in block
    cleaned = scrub_memory_context(f"до {block} после")
    assert "факт о пользователе" not in cleaned
    assert cleaned.startswith("до")


def test_wrap_empty_returns_empty():
    assert wrap_memory_context("") == ""
    assert wrap_memory_context(None) == ""


def test_inject_into_user_message_keeps_text():
    merged = inject_into_user_message("вопрос", "контекст")
    assert merged.endswith("вопрос")
    assert MEMORY_CONTEXT_MARKER in merged


class _FailingProvider(MemoryProvider):
    name = "failing"

    async def prefetch(self, query):
        raise RuntimeError("сбой")


def test_builtin_always_first_and_max_one_external():
    manager = MemoryManager()
    external = BuiltinMemoryProvider()
    external.name = "external"
    manager.set_external(external)
    providers = manager.providers()
    assert providers[0].name == "builtin"
    assert len(providers) == 2


def test_prefetch_failure_does_not_block_others():
    manager = MemoryManager()
    manager.set_external(_FailingProvider())
    combined = asyncio.run(manager.prefetch("запрос"))
    # Встроенный вернул пустой контекст, сбой внешнего не уронил вызов.
    assert isinstance(combined, str)


def test_builtin_memory_tools():
    provider = BuiltinMemoryProvider()
    written = asyncio.run(provider.handle_tool_call("memory_write", {"key": "k", "value": "v"}))
    assert json.loads(written)["ok"] is True
    read = asyncio.run(provider.handle_tool_call("memory_read", {}))
    assert json.loads(read)["k"] == "v"


def test_manager_routes_tool_calls():
    manager = MemoryManager()
    result = asyncio.run(manager.handle_tool_call("memory_write", {"key": "a", "value": "b"}))
    assert result is not None
    unknown = asyncio.run(manager.handle_tool_call("no_such_tool", {}))
    assert unknown is None
