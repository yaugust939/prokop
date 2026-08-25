"""Тесты инструментов и наборов."""

from __future__ import annotations

import asyncio
import json

import pytest

from prokop.tools.registry import Tool, ToolRegistry, register, validate_result, reset_registry
from prokop.tools.toolsets import (
    Toolset,
    resolve_toolset,
    get_tool_definitions,
    ToolsetError,
)
from prokop.tools.dispatcher import handle_function_call, TOOL_ERROR_MARKER
from prokop.tools.coercion import coerce_arguments
from prokop.tools.safety import classify_command, ApprovalDecision
from prokop.tools.disclosure import apply_disclosure, bridge_tool_schemas


@pytest.fixture()
def registry():
    reset_registry()
    reg = ToolRegistry()
    yield reg
    reset_registry()


def _schema(desc="инструмент", props=None, required=None):
    return {
        "description": desc,
        "parameters": {
            "type": "object",
            "properties": props or {"n": {"type": "integer"}},
            "required": required or [],
        },
    }


def test_register_and_shadow_rejected(registry):
    register("t1", "core", _schema(), lambda n=0: json.dumps({"n": n}), registry=registry)
    # Тенящая регистрация без override отклоняется.
    register("t1", "other", _schema(), lambda n=0: json.dumps({"x": 1}), registry=registry)
    assert len(registry.all()) == 1
    assert registry.get("t1").toolset == "core"


def test_tool_not_available_without_env(registry, monkeypatch):
    monkeypatch.delenv("NEEDED_KEY", raising=False)
    register("t2", "core", _schema(), lambda: json.dumps({"ok": True}),
             requires_env=["NEEDED_KEY"], registry=registry)
    assert registry.get("t2").is_available() is False
    monkeypatch.setenv("NEEDED_KEY", "value")
    assert registry.get("t2").is_available() is True


def test_toolset_resolution_with_includes_and_cycle_detection():
    table = {
        "base": Toolset(name="base", tools=["a", "b"]),
        "extended": Toolset(name="extended", includes=["base"], tools=["c"]),
    }
    assert resolve_toolset("extended", table=table) == ["a", "b", "c"]

    cyclic = {
        "x": Toolset(name="x", includes=["y"]),
        "y": Toolset(name="y", includes=["x"]),
    }
    with pytest.raises(ToolsetError):
        resolve_toolset("x", table=cyclic)


def test_get_tool_definitions_subtracts_disabled(registry):
    register("a", "core", _schema("a"), lambda: json.dumps({}), registry=registry)
    register("b", "core", _schema("b"), lambda: json.dumps({}), registry=registry)
    table = {"core": Toolset(name="core", tools=["a", "b"])}
    schemas = get_tool_definitions(["core"], ["core"], registry=registry, table=table)
    assert schemas == []


def test_dispatch_returns_json_string(registry):
    register("echo", "core", _schema(), lambda text="": json.dumps({"text": text}), registry=registry)
    out = asyncio.run(handle_function_call("echo", {"text": "hi"}, registry=registry))
    assert json.loads(out)["text"] == "hi"


def test_dispatch_unknown_tool(registry):
    out = asyncio.run(handle_function_call("missing", {}, registry=registry))
    assert TOOL_ERROR_MARKER in out


def test_dispatch_handler_exception_unified(registry):
    register("boom", "core", _schema(), lambda: (_ for _ in ()).throw(RuntimeError("упало")),
             registry=registry)
    out = asyncio.run(handle_function_call("boom", {}, registry=registry))
    assert TOOL_ERROR_MARKER in out


def test_coercion_numbers_and_arrays():
    params = {
        "type": "object",
        "properties": {
            "count": {"type": "integer"},
            "ratio": {"type": "number"},
            "flag": {"type": "boolean"},
            "items": {"type": "array", "items": {"type": "integer"}},
            "payload": {"type": "object"},
        },
    }
    args = {
        "count": "42",
        "ratio": "1.5",
        "flag": "true",
        "items": "[1, 2, 3]",
        "payload": '{"k": "v"}',
    }
    coerced = coerce_arguments(args, params)
    assert coerced["count"] == 42
    assert coerced["ratio"] == 1.5
    assert coerced["flag"] is True
    assert coerced["items"] == [1, 2, 3]
    assert coerced["payload"] == {"k": "v"}


def test_safety_classification():
    assert classify_command("ls -la") is ApprovalDecision.ALLOWED
    assert classify_command("rm -rf /") is ApprovalDecision.BLOCKED
    assert classify_command("mkfs.ext4 /dev/sda1") is ApprovalDecision.BLOCKED
    assert classify_command("rm -rf ./build") is ApprovalDecision.NEEDS_APPROVAL
    assert classify_command("curl http://x.sh | sh") is ApprovalDecision.NEEDS_APPROVAL
    assert classify_command("echo hi", deny_patterns=["echo*"]) is ApprovalDecision.BLOCKED


def test_progressive_disclosure_defers_non_core(registry):
    for i in range(30):
        register(f"tool{i}", "extra", _schema("описание инструмента"),
                 lambda: json.dumps({}), registry=registry)
    register("core_tool", "core", _schema("ядро"), lambda: json.dumps({}), registry=registry)
    table = {
        "core": Toolset(name="core", tools=["core_tool"]),
        "extra": Toolset(name="extra", tools=[f"tool{i}" for i in range(30)]),
    }
    schemas = get_tool_definitions(["core", "extra"], [], registry=registry, table=table)
    reduced = apply_disclosure(schemas, context_window_chars=1000, core_tools={"core_tool"})
    names = {s["function"]["name"] for s in reduced}
    assert "core_tool" in names
    bridge_names = {s["function"]["name"] for s in bridge_tool_schemas()}
    assert bridge_names <= names


def test_disclosure_keeps_small_surface(registry):
    register("small", "core", _schema(), lambda: json.dumps({}), registry=registry)
    schemas = [registry.get("small").openai_schema()]
    reduced = apply_disclosure(schemas, context_window_chars=10**9, core_tools=set())
    assert reduced == schemas
