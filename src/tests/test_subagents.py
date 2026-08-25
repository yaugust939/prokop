"""Тесты подсистемы субагентов и делегирования."""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from prokop.subagents.budget import IterationBudget
from prokop.subagents.config import SubagentsConfig
from prokop.subagents.engine import DelegationEngine, consolidate_batch_results
from prokop.subagents.isolation import (
    BLOCKED_TOOL_NAMES,
    build_child_system_prompt,
    filter_child_tools,
)
from prokop.subagents.model import (
    SubagentRecord,
    SubagentResult,
    SubagentStatus,
    new_subagent_id,
)
from prokop.subagents.queue import CompletionQueue
from prokop.subagents.registry import RegistrySaturatedError, SubagentRegistry
from prokop.subagents.roles import (
    DepthError,
    Role,
    normalize_max_depth,
    resolve_role,
    validate_depth,
)
from prokop.subagents.tool import (
    DELEGATION_TOOL_NAME,
    build_delegation_handler,
    delegation_tool_schema,
    make_delegation_tool,
)


def _names(tools):
    return {t.get("function", {}).get("name") for t in tools}


def _parent_tools():
    def fn(name):
        return {
            "type": "function",
            "function": {"name": name, "description": "", "parameters": {}},
        }

    return [
        fn("read_file"),
        fn("delegate"),
        fn("ask_user"),
        fn("memory_write"),
        fn("send_message"),
        fn("schedule_job"),
    ]


# --- 1. бюджет итераций -----------------------------------------------------


def test_budget_ceiling_and_single_grace_call():
    budget = IterationBudget(limit=3)
    assert budget.can_call_model() is True
    for _ in range(3):
        budget.consume_iteration()
    assert budget.iterations_used == 3
    assert budget.exhausted is True
    assert budget.grace_allowed is True
    assert budget.can_call_model() is True
    budget.consume_iteration()
    assert budget.can_call_model() is False
    assert budget.grace_allowed is False


def test_budget_unlimited():
    budget = IterationBudget(limit=None)
    for _ in range(100):
        assert budget.can_call_model() is True
        budget.consume_iteration()
    assert budget.exhausted is False
    assert budget.grace_allowed is False


def test_budget_instances_are_independent():
    parent = IterationBudget(limit=5)
    child = IterationBudget(limit=2)
    for _ in range(3):
        child.consume_iteration()
    assert child.exhausted is True
    assert parent.iterations_used == 0


def test_budget_is_thread_safe():
    budget = IterationBudget(limit=4000)

    def worker():
        for _ in range(1000):
            budget.consume_iteration()

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert budget.iterations_used == 4000


# --- 2. роли и глубина -----------------------------------------------------


def test_resolve_role_downgrades_orchestrator_when_disabled():
    assert resolve_role("orchestrator", orchestration_enabled=True) is Role.ORCHESTRATOR
    assert resolve_role("orchestrator", orchestration_enabled=False) is Role.LEAF
    assert resolve_role("leaf", orchestration_enabled=True) is Role.LEAF
    assert resolve_role("bogus", orchestration_enabled=True) is Role.LEAF
    assert resolve_role(None, orchestration_enabled=True) is Role.LEAF


def test_normalize_max_depth_lower_bound():
    assert normalize_max_depth(0) == 1
    assert normalize_max_depth(-5) == 1
    assert normalize_max_depth(3) == 3


def test_validate_depth_rejects_too_deep():
    validate_depth(1, 1)
    validate_depth(2, 3)
    with pytest.raises(DepthError):
        validate_depth(2, 1)


def test_config_clamps_lower_bounds():
    config = SubagentsConfig(max_depth=0, max_children=-3)
    assert config.max_depth == 1
    assert config.max_children == 1


# --- 3. схема инструмента делегирования -------------------------------------


def test_delegation_tool_schema_is_openai_function_calling():
    schema = delegation_tool_schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == DELEGATION_TOOL_NAME
    params = fn["parameters"]
    assert params["required"] == ["action"]
    assert params["properties"]["action"]["enum"] == ["spawn", "list", "steer", "stop"]
    assert "tasks" in params["properties"]
    assert "goal" in params["properties"]


def test_make_delegation_tool_registers_async_tool():
    tool = make_delegation_tool(object())
    assert tool.name == DELEGATION_TOOL_NAME
    assert tool.is_async is True
    assert tool.openai_schema()["function"]["name"] == DELEGATION_TOOL_NAME


# --- 4. реестр -------------------------------------------------------------


def test_registry_saturation_rejected():
    reg = SubagentRegistry(2)
    reg.register(SubagentRecord(id="a", goal="g"))
    reg.register(SubagentRecord(id="b", goal="g"))
    with pytest.raises(RegistrySaturatedError):
        reg.register(SubagentRecord(id="c", goal="g"))


def test_registry_list_stop_progress_steer():
    reg = SubagentRegistry(4)
    reg.register(SubagentRecord(id="a", goal="g", owner="me"))
    assert reg.active_count() == 1
    assert reg.update_progress("a", "50%") is True
    assert reg.list()[0]["progress"] == "50%"
    assert reg.steer("a", "hint1") is True
    assert reg.steer("a", "hint2") is True
    assert reg.take_steer("a") == "hint1\nhint2"
    assert reg.take_steer("a") is None
    assert reg.stop("a") is True
    snap = reg.list()[0]
    assert snap["status"] == SubagentStatus.STOPPED.value
    assert snap["stop_requested"] is True
    assert reg.remove("a") is True
    assert reg.get("a") is None
    assert reg.stop("missing") is False


def test_new_subagent_id_is_unique():
    ids = {new_subagent_id() for _ in range(200)}
    assert len(ids) == 200


# --- 5. очередь завершений ---------------------------------------------------


def test_completion_queue_drain_nowait():
    queue = CompletionQueue()
    queue.put_nowait(SubagentResult(goal="a"))
    queue.put_nowait(SubagentResult(goal="b"))
    assert queue.qsize() == 2
    drained = queue.drain_nowait()
    assert [r.goal for r in drained] == ["a", "b"]
    assert queue.empty() is True


def test_completion_queue_next_completion():
    async def scenario():
        queue = CompletionQueue()
        await queue.put(SubagentResult(goal="a", summary="s"))
        result = await queue.next_completion()
        return result.goal, result.summary

    assert asyncio.run(scenario()) == ("a", "s")


# --- 6. изоляция ребёнка ------------------------------------------------------


def test_filter_child_tools_blocks_and_readds_for_orchestrator():
    parent = _parent_tools()
    delegation_tool = delegation_tool_schema()

    leaf = filter_child_tools(
        parent, role="leaf", orchestration_enabled=True, delegation_tool=delegation_tool
    )
    assert _names(leaf) == {"read_file"}

    orch = filter_child_tools(
        parent,
        role="orchestrator",
        orchestration_enabled=True,
        delegation_tool=delegation_tool,
    )
    names = _names(orch)
    assert "read_file" in names
    assert "delegate" in names
    assert not names & BLOCKED_TOOL_NAMES.difference({"delegate"})

    downgraded = filter_child_tools(
        parent,
        role="orchestrator",
        orchestration_enabled=False,
        delegation_tool=delegation_tool,
    )
    assert "delegate" not in _names(downgraded)


def test_child_system_prompt_from_goal_and_context():
    prompt = build_child_system_prompt(goal="собери отчёт", context="из файла X", role="leaf")
    assert "собери отчёт" in prompt
    assert "из файла X" in prompt
    assert "leaf" in prompt


# --- 7. движок делегирования ----------------------------------------------------


def test_engine_single_delegate_returns_self_contained_result():
    async def spawn(goal, context, role):
        return SubagentResult(
            goal=goal,
            context=context,
            role=role,
            summary="готово",
            api_calls=3,
            model="m1",
        )

    async def scenario():
        engine = DelegationEngine(spawn_fn=spawn)
        receipt = await engine.delegate(goal="g", context="c", role="leaf")
        assert receipt["ok"] is True
        assert len(receipt["subagent_ids"]) == 1
        result = await engine.completions.next_completion()
        return result

    result = asyncio.run(scenario())
    assert result.goal == "g"
    assert result.context == "c"
    assert result.summary == "готово"
    assert result.api_calls == 3
    assert result.model == "m1"
    assert result.status == SubagentStatus.DONE.value


def test_engine_batch_runs_in_parallel_and_consolidates():
    async def scenario():
        gate = asyncio.Event()
        active = 0
        max_active = 0

        async def spawn(goal, context, role):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await gate.wait()
            active -= 1
            return SubagentResult(goal=goal, summary=f"r:{goal}", api_calls=1)

        engine = DelegationEngine(spawn_fn=spawn)
        receipt = await engine.delegate(
            tasks=[{"goal": "a"}, {"goal": "b"}, {"goal": "c"}]
        )
        assert receipt["ok"] is True
        assert len(receipt["subagent_ids"]) == 3
        await asyncio.sleep(0.05)
        assert max_active == 3
        gate.set()
        result = await engine.completions.next_completion()
        return result

    result = asyncio.run(scenario())
    assert result.status == SubagentStatus.DONE.value
    assert result.api_calls == 3
    assert "r:a" in result.summary
    assert "r:b" in result.summary
    assert "r:c" in result.summary


def test_engine_rejects_when_children_saturated():
    async def spawn(goal, context, role):
        await asyncio.sleep(0.1)
        return SubagentResult(goal=goal)

    async def scenario():
        engine = DelegationEngine(spawn_fn=spawn, config=SubagentsConfig(max_children=2))
        first = await engine.handle_action("spawn", goal="a")
        second = await engine.handle_action("spawn", goal="b")
        third = await engine.handle_action("spawn", goal="c")
        return first, second, third

    first, second, third = asyncio.run(scenario())
    assert first["ok"] is True
    assert second["ok"] is True
    assert third["ok"] is False
    assert "потолок" in third["error"].lower()


def test_engine_rejects_depth_beyond_limit():
    async def spawn(goal, context, role):
        return SubagentResult(goal=goal)

    async def scenario():
        child_engine = DelegationEngine(
            spawn_fn=spawn, config=SubagentsConfig(max_depth=1), depth=1
        )
        return await child_engine.handle_action("spawn", goal="grandchild")

    result = asyncio.run(scenario())
    assert result["ok"] is False
    assert "глубина" in result["error"].lower()


def test_engine_stop_cancels_child_and_emits_stopped():
    async def scenario():
        started = asyncio.Event()

        async def spawn(goal, context, role):
            started.set()
            await asyncio.Event().wait()
            return SubagentResult(goal=goal)

        engine = DelegationEngine(spawn_fn=spawn)
        receipt = await engine.delegate(goal="долгая задача")
        subagent_id = receipt["subagent_ids"][0]
        await started.wait()
        assert engine.stop(subagent_id) is True
        assert engine.stop(subagent_id) is False
        result = await engine.completions.next_completion()
        return result

    result = asyncio.run(scenario())
    assert result.status == SubagentStatus.STOPPED.value


def test_engine_steer_and_list_via_actions():
    async def spawn(goal, context, role):
        await asyncio.sleep(0.05)
        return SubagentResult(goal=goal, summary="s")

    async def scenario():
        engine = DelegationEngine(spawn_fn=spawn)
        receipt = await engine.handle_action("spawn", goal="g")
        subagent_id = receipt["subagent_ids"][0]
        listed = await engine.handle_action("list")
        steered = await engine.handle_action("steer", subagent_id=subagent_id, steer="поправь")
        return subagent_id, listed, steered

    subagent_id, listed, steered = asyncio.run(scenario())
    assert listed["ok"] is True
    assert any(s["id"] == subagent_id for s in listed["subagents"])
    assert steered["ok"] is True


def test_engine_child_failure_is_captured():
    async def spawn(goal, context, role):
        raise RuntimeError("ребёнок упал")

    async def scenario():
        engine = DelegationEngine(spawn_fn=spawn)
        receipt = await engine.delegate(goal="g")
        result = await engine.completions.next_completion()
        return receipt, result

    receipt, result = asyncio.run(scenario())
    assert receipt["ok"] is True
    assert result.status == SubagentStatus.FAILED.value
    assert "ребёнок упал" in result.error


def test_delegation_handler_serializes_json():
    async def spawn(goal, context, role):
        return SubagentResult(goal=goal, summary="s")

    async def scenario():
        engine = DelegationEngine(spawn_fn=spawn)
        handler = build_delegation_handler(engine)
        out = await handler(action="spawn", goal="x")
        return out

    payload = json.loads(asyncio.run(scenario()))
    assert payload["ok"] is True
    assert len(payload["subagent_ids"]) == 1


def test_consolidate_batch_results_aggregates():
    results = [
        SubagentResult(goal="a", summary="A", api_calls=2, model="m1"),
        SubagentResult(
            goal="b", summary="B", api_calls=3, model="m2",
            status=SubagentStatus.FAILED.value, error="boom",
        ),
    ]
    consolidated = consolidate_batch_results("d1", results)
    assert consolidated.status == SubagentStatus.FAILED.value
    assert consolidated.api_calls == 5
    assert "A" in consolidated.summary
    assert "B" in consolidated.summary
    assert consolidated.error == "boom"
    assert "d1" in consolidated.goal
