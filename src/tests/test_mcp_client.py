"""Тесты MCP-клиента, рантайма и подкоманды `prokop mcp`.

Внешние серверы подменяются локальным скриптом-заглушкой
(`tests/mcp_stub_server.py`): тесты полностью локальны, не ходят в сеть и не
зависят от внешних пакетов.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

from prokop.cli.commands import Context
from prokop.cli.main import EXIT_OK, EXIT_USAGE, main
from prokop.config import Config
from prokop.mcp.client import McpClient, McpError
from prokop.mcp.config import McpServerConfig, parse_servers
from prokop.mcp.runtime import McpRuntime, sanitize, tool_name
from prokop.tools.dispatcher import handle_function_call
from prokop.tools.registry import ToolRegistry
from prokop.tools.toolsets import DEFAULT_TOOLSETS, get_tool_definitions

STUB = Path(__file__).resolve().parent / "mcp_stub_server.py"
STUB_TOOL_COUNT = 4


def stub_command(*extra: str) -> list[str]:
    return [sys.executable, str(STUB), *extra]


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _restore_mcp_toolset():
    """Не оставлять зарегистрированные имена в глобальном наборе `mcp`."""
    entry = DEFAULT_TOOLSETS.get("mcp")
    before = list(entry.tools) if entry else None
    yield
    if entry is not None and before is not None:
        entry.tools = before


@pytest.fixture()
def server() -> McpServerConfig:
    return McpServerConfig(name="stub", command=stub_command(), enabled=True)


# --- клиент ---------------------------------------------------------------


def test_handshake_and_list_tools(server):
    async def scenario():
        client = McpClient(server.name, server.command, timeout=10.0)
        try:
            await client.initialize()
            return await client.list_tools()
        finally:
            await client.close()

    tools = run(scenario())
    names = [t.name for t in tools]
    assert len(tools) == STUB_TOOL_COUNT
    assert "echo" in names

    echo = next(t for t in tools if t.name == "echo")
    assert echo.description
    assert echo.input_schema["properties"]["text"]["type"] == "string"

    # Инструмент без схемы получает схему по умолчанию.
    no_schema = next(t for t in tools if t.name == "no_schema")
    assert no_schema.input_schema == {"type": "object", "properties": {}}


def test_call_tool_keeps_cyrillic(server):
    async def scenario():
        client = McpClient(server.name, server.command, timeout=10.0)
        try:
            await client.initialize()
            return await client.call_tool("echo", {"text": "преодолено"})
        finally:
            await client.close()

    raw = run(scenario())
    payload = json.loads(raw)
    assert payload["isError"] is False
    assert payload["content"] == ["преодолено"]


def test_call_tool_marks_server_error(server):
    async def scenario():
        client = McpClient(server.name, server.command, timeout=10.0)
        try:
            await client.initialize()
            return await client.call_tool("fail", {})
        finally:
            await client.close()

    payload = json.loads(run(scenario()))
    assert payload["isError"] is True
    assert "не получилось" in payload["error"]


def test_protocol_error_raises(server):
    async def scenario():
        client = McpClient(server.name, server.command, timeout=10.0)
        try:
            await client.initialize()
            return await client.call_tool("нет-такого", {})
        finally:
            await client.close()

    with pytest.raises(McpError) as exc:
        run(scenario())
    assert "-32602" in str(exc.value)


def test_timeout_kills_process_and_raises():
    async def scenario():
        client = McpClient("silent", stub_command("--silent"), timeout=0.6)
        try:
            return await client.initialize()
        finally:
            await client.close()

    with pytest.raises(McpError) as exc:
        run(scenario())
    message = str(exc.value)
    assert "silent" in message
    assert "таймаут" in message


def test_initialize_error_is_reported():
    async def scenario():
        client = McpClient("bad", stub_command("--fail-init"), timeout=10.0)
        try:
            return await client.initialize()
        finally:
            await client.close()

    with pytest.raises(McpError) as exc:
        run(scenario())
    assert "инициализация отклонена" in str(exc.value)


def test_missing_binary_is_reported():
    async def scenario():
        client = McpClient("nope", ["definitely-not-a-real-binary-prokop"], timeout=2.0)
        await client.start()

    with pytest.raises(McpError) as exc:
        run(scenario())
    assert "nope" in str(exc.value)


def test_close_is_idempotent():
    async def scenario():
        client = McpClient("stub", stub_command(), timeout=5.0)
        await client.start()
        await client.close()
        await client.close()

    run(scenario())


def test_empty_command_rejected():
    with pytest.raises(McpError):
        McpClient("empty", [])


# --- конфигурация ---------------------------------------------------------


def test_parse_servers_absent_section():
    assert parse_servers({}) == {}
    assert parse_servers(None) == {}
    assert parse_servers("не объект") == {}


def test_parse_servers_disabled_by_default():
    servers = parse_servers({"servers": {"a": {"command": ["python", "-m", "x"]}}})
    assert servers["a"].enabled is False


def test_parse_servers_enabled_with_options():
    servers = parse_servers(
        {
            "servers": {
                "a": {
                    "command": ["python", "-m", "x"],
                    "enabled": True,
                    "env": {"TOKEN": "t"},
                    "cwd": "/tmp",
                    "timeout": 12,
                }
            }
        }
    )
    server = servers["a"]
    assert server.enabled is True
    assert server.env == {"TOKEN": "t"}
    assert server.cwd == "/tmp"
    assert server.timeout == 12.0


def test_parse_servers_rejects_string_command():
    servers = parse_servers({"servers": {"a": {"command": "python -m x", "enabled": True}}})
    assert servers == {}


def test_parse_servers_skips_broken_entry():
    servers = parse_servers(
        {
            "servers": {
                "broken": "не объект",
                "no_command": {"enabled": True},
                "good": {"command": ["python"], "enabled": True},
            }
        }
    )
    assert list(servers) == ["good"]


def test_config_roundtrip_keeps_mcp_section():
    config = Config.from_dict({"mcp": {"servers": {"a": {"command": ["python"]}}}})
    assert "servers" in config.mcp
    assert Config().mcp == {}


# --- рантайм --------------------------------------------------------------


def test_name_sanitizing_and_route():
    assert sanitize("weird.tool/name") == "weird_tool_name"
    assert sanitize("") == "unnamed"
    assert tool_name("my server", "a.b") == "mcp__my_server__a_b"


def test_runtime_registers_tools_and_calls_through_dispatcher(server):
    registry = ToolRegistry()
    runtime = McpRuntime(servers={server.name: server}, registry=registry)

    async def scenario():
        try:
            names = await runtime.start()
            result = await handle_function_call(
                tool_name("stub", "echo"), {"text": "привет"}, registry=registry
            )
            return names, result
        finally:
            await runtime.aclose()

    names, result = run(scenario())
    assert len(names) == STUB_TOOL_COUNT
    assert all(n.startswith("mcp__stub__") for n in names)

    payload = json.loads(result)
    assert payload["content"] == ["привет"]

    # Инструменты видны в наборе `mcp`.
    schemas = get_tool_definitions(["mcp"], registry=registry)
    assert any(s["function"]["name"] == tool_name("stub", "echo") for s in schemas)


def test_runtime_routes_registered_name_to_original(server):
    registry = ToolRegistry()
    runtime = McpRuntime(servers={server.name: server}, registry=registry)

    async def scenario():
        try:
            await runtime.start()
            return await runtime.call_registered(tool_name("stub", "weird.tool/name"))
        finally:
            await runtime.aclose()

    payload = json.loads(run(scenario()))
    assert payload["content"] == ["странное имя"]
    assert runtime.routes[tool_name("stub", "weird.tool/name")] == ("stub", "weird.tool/name")


def test_runtime_skips_unavailable_server(server):
    broken = McpServerConfig(name="broken", command=stub_command("--fail-init"), enabled=True)
    registry = ToolRegistry()
    runtime = McpRuntime(servers={"broken": broken, "stub": server}, registry=registry)

    async def scenario():
        try:
            names = await runtime.start()
            return names, list(runtime.running)
        finally:
            await runtime.aclose()

    names, running = run(scenario())
    assert running == ["stub"]
    assert len(names) == STUB_TOOL_COUNT


def test_runtime_with_all_servers_down():
    broken = McpServerConfig(name="broken", command=stub_command("--fail-init"), enabled=True)
    registry = ToolRegistry()
    runtime = McpRuntime(servers={"broken": broken}, registry=registry)

    async def scenario():
        try:
            names = await runtime.start()
            return names, list(runtime.running)
        finally:
            await runtime.aclose()

    names, running = run(scenario())
    assert names == []
    assert running == []


def test_runtime_ignores_disabled_servers(server):
    disabled = McpServerConfig(name="off", command=stub_command(), enabled=False)
    registry = ToolRegistry()
    runtime = McpRuntime(servers={"off": disabled}, registry=registry)

    async def scenario():
        try:
            return await runtime.start()
        finally:
            await runtime.aclose()

    assert run(scenario()) == []


def test_runtime_call_unknown_server_raises():
    runtime = McpRuntime(servers={})

    async def scenario():
        return await runtime.call("нет-такого", "echo", {})

    with pytest.raises(McpError):
        run(scenario())


# --- CLI ------------------------------------------------------------------


def make_ctx(tmp_path: Path, mcp_section: Optional[dict[str, Any]] = None) -> Context:
    def loader(home: Path) -> Config:
        config = Config()
        config.model.provider = "deepseek"
        config.model.model = "deepseek-chat"
        config.mcp = mcp_section or {}
        return config

    return Context(
        home=tmp_path / "home",
        profile="test",
        env={},
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        config_loader=loader,
    )


def out(ctx: Context) -> str:
    return ctx.stdout.getvalue()


def test_cli_mcp_list_empty(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["mcp", "list"], context=ctx) == EXIT_OK
    assert "не настроены" in out(ctx)


def test_cli_mcp_list_shows_servers(tmp_path):
    ctx = make_ctx(
        tmp_path,
        {"servers": {"stub": {"command": stub_command(), "enabled": True}}},
    )
    assert main(["mcp", "list"], context=ctx) == EXIT_OK
    assert "stub" in out(ctx)
    assert "вкл" in out(ctx)


def test_cli_mcp_tools(tmp_path):
    ctx = make_ctx(
        tmp_path,
        {"servers": {"stub": {"command": stub_command(), "enabled": True}}},
    )
    assert main(["mcp", "tools", "stub"], context=ctx) == EXIT_OK
    assert "echo" in out(ctx)
    assert tool_name("stub", "echo") in out(ctx)


def test_cli_mcp_call(tmp_path):
    ctx = make_ctx(
        tmp_path,
        {"servers": {"stub": {"command": stub_command(), "enabled": True}}},
    )
    code = main(
        ["mcp", "call", "stub", "echo", "--args", '{"text": "привет"}'], context=ctx
    )
    assert code == EXIT_OK
    assert "привет" in out(ctx)


def test_cli_mcp_call_json_output(tmp_path):
    ctx = make_ctx(
        tmp_path,
        {"servers": {"stub": {"command": stub_command(), "enabled": True}}},
    )
    code = main(
        ["--json", "mcp", "call", "stub", "echo", "--args", '{"text": "привет"}'],
        context=ctx,
    )
    assert code == EXIT_OK
    payload = json.loads(out(ctx))
    assert payload["server"] == "stub"
    assert payload["result"]["content"] == ["привет"]


def test_cli_mcp_call_invalid_args(tmp_path):
    ctx = make_ctx(
        tmp_path,
        {"servers": {"stub": {"command": stub_command(), "enabled": True}}},
    )
    assert main(["mcp", "call", "stub", "echo", "--args", "не json"], context=ctx) == EXIT_USAGE
    assert "JSON" in ctx.stderr.getvalue()


def test_cli_mcp_call_args_must_be_object(tmp_path):
    ctx = make_ctx(
        tmp_path,
        {"servers": {"stub": {"command": stub_command(), "enabled": True}}},
    )
    assert main(["mcp", "call", "stub", "echo", "--args", "[1,2]"], context=ctx) == EXIT_USAGE


def test_cli_mcp_unknown_server(tmp_path):
    ctx = make_ctx(tmp_path, {"servers": {}})
    assert main(["mcp", "tools", "нет"], context=ctx) == EXIT_USAGE
    assert "не найден" in ctx.stderr.getvalue()


def test_cli_mcp_requires_subcommand(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["mcp"], context=ctx) == EXIT_USAGE


# --- гигиена --------------------------------------------------------------


def test_mcp_package_has_no_personal_paths():
    import prokop.mcp as mcp_pkg

    package = Path(mcp_pkg.__file__).resolve().parent
    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    offenders = []
    for file in package.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(package)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"
