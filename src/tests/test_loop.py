"""Тесты цикла агента."""

from __future__ import annotations

import asyncio

import pytest

from agent_core.loop.messages import Message, clone_messages, fix_role_alternation, to_api_messages
from agent_core.loop.budgets import Budgets, WIND_DOWN_NOTE
from agent_core.loop.control import TurnControl
from agent_core.loop.compressor import compress_context, plan_compression, is_summary, SUMMARY_PREFIX
from agent_core.loop.errors import classify_error, ErrorKind, retry_transient
from agent_core.loop.lease import SessionLease, LeaseLostError
from agent_core.loop.system_prompt import build_system_prompt, is_stale, prompt_hash
from agent_core.loop.turn import AgentTurn
from agent_core.store.sessions import SessionStore
from agent_core.transport.base import ModelResponse, ModelTransport, TransportConfig
from agent_core.providers.profile import ProviderProfile


class FakeTransport(ModelTransport):
    """Транспорт, выдающий заранее заданную очередь ответов."""

    def __init__(self, responses: list[ModelResponse]):
        super().__init__(ProviderProfile(name="fake"))
        self.responses = list(responses)
        self.calls = 0

    async def call(self, config: TransportConfig) -> ModelResponse:
        self.calls += 1
        if not self.responses:
            return ModelResponse(content="пусто")
        return self.responses.pop(0)


def test_clone_messages_fixes_role_alternation():
    messages = [
        Message(role="user", content="а"),
        Message(role="user", content="б"),
        Message(role="assistant", content="в"),
    ]
    fixed = fix_role_alternation(messages)
    assert [m.role for m in fixed] == ["user", "assistant"]
    assert fixed[0].content == "а\nб"


def test_reasoning_not_serialized_into_api():
    messages = [Message(role="assistant", content="ответ", reasoning="секретные мысли")]
    api = to_api_messages(messages)
    assert api[0]["content"] == "ответ"
    assert "reasoning" not in api[0]


def test_tool_calls_serialized_in_openai_format():
    messages = [
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "c1", "name": "multiply", "arguments": {"a": 17, "b": 23}}],
        )
    ]
    api = to_api_messages(messages)
    tc = api[0]["tool_calls"][0]
    assert tc["id"] == "c1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "multiply"
    # arguments уходит в API как JSON-строка, а не как объект
    assert tc["function"]["arguments"] == '{"a": 17, "b": 23}'


def test_thinking_only_dropped():
    messages = [
        Message(role="user", content="вопрос"),
        Message(role="assistant", reasoning="только мысли"),
        Message(role="assistant", content="ответ"),
    ]
    api = to_api_messages(messages)
    assert len(api) == 2
    assert api[1]["content"] == "ответ"


def test_iteration_budget_grace_call():
    budgets = Budgets(iteration_budget=1)
    budgets.start()
    assert budgets.can_call_model()
    budgets.consume_iteration()
    assert budgets.grace_allowed
    assert budgets.can_call_model()  # грациозный вызов
    budgets.consume_iteration()
    assert not budgets.can_call_model()


def test_wind_down_note_once():
    budgets = Budgets(run_budget_seconds=0.0001)
    budgets.start()
    import time

    time.sleep(0.001)
    note = budgets.wind_down_note()
    assert note == WIND_DOWN_NOTE
    assert budgets.wind_down_note() is None  # только один раз


def test_steer_merges_and_redirect():
    control = TurnControl()
    control.steer_text("первая подсказка")
    control.steer_text("вторая подсказка")
    merged = control.take_steer()
    assert "первая подсказка" in merged and "вторая подсказка" in merged
    assert control.take_steer() is None

    control.redirect("сделай иначе")
    assert control.redirect_pending
    assert control.take_redirect() == "сделай иначе"
    assert not control.redirect_pending


def test_compression_protects_head_tail_and_pairs():
    messages = [
        Message(role="user", content="старт"),
        Message(role="assistant", tool_calls=[{"id": "1", "name": "t", "arguments": {}}]),
        Message(role="tool", content="результат", tool_call_id="1"),
        Message(role="user", content="середина"),
        Message(role="assistant", content="хвост-1"),
        Message(role="user", content="хвост-2"),
    ]
    plan = plan_compression(messages, head_protected=1, tail_protected=2)
    # Пара вызов/результат не разрезается: середина включает позиции 1 и 2 целиком.
    assert 1 in plan.summary_positions and 2 in plan.summary_positions
    compressed = asyncio.run(compress_context(messages, head_protected=1, tail_protected=2))
    assert compressed[0].content == "старт"
    assert compressed[-1].content == "хвост-2"
    summary = [m for m in compressed if is_summary(m.content)]
    assert len(summary) == 1


def test_error_classification():
    assert classify_error(RuntimeError("429 rate limit")).kind is ErrorKind.TRANSIENT
    assert classify_error(RuntimeError("quota exceeded")).kind is ErrorKind.BILLING
    assert classify_error(ValueError("плохо")).kind is ErrorKind.LOCAL
    transient = classify_error(asyncio.TimeoutError())
    assert transient.retryable is True


def test_retry_transient_local_not_retried():
    attempts = 0

    async def factory():
        nonlocal attempts
        attempts += 1
        raise ValueError("локальная")

    async def main():
        try:
            await retry_transient(factory, max_attempts=3, sleep=lambda s: asyncio.sleep(0))
        except ValueError:
            pass

    asyncio.run(main())
    assert attempts == 1  # локальная ошибка не ретраится


def test_system_prompt_stable_and_stale_check():
    state = build_system_prompt(identity="Я агент", model="m1", provider="p1")
    assert state.content is not None
    assert not is_stale(state, model="m1", provider="p1", platform="cli")
    assert is_stale(state, model="m2", provider="p1", platform="cli")
    assert prompt_hash(state.content) == state.hash


def test_turn_executes_tools_then_final_answer():
    responses = [
        ModelResponse(
            tool_calls=[{"id": "c1", "name": "echo", "arguments": {"text": "ок"}}],
        ),
        ModelResponse(content="финальный ответ"),
    ]
    from agent_core.tools.registry import ToolRegistry, register
    import json

    registry = ToolRegistry()
    register("echo", "core",
             {"description": "эхо", "parameters": {"type": "object", "properties": {"text": {"type": "string"}}}},
             lambda text="": json.dumps({"text": text}), registry=registry)

    turn = AgentTurn(
        transport=FakeTransport(responses),
        tool_registry=registry,
        tool_schemas=[registry.get("echo").openai_schema()],
        model="m1",
        provider="fake",
    )
    result = asyncio.run(turn.run("сделай эхо"))
    assert result.completed
    assert result.final_response == "финальный ответ"
    assert result.api_calls == 2
    roles = [m.role for m in result.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]


def test_turn_interrupt_stops_loop():
    responses = [ModelResponse(tool_calls=[{"id": "c1", "name": "echo", "arguments": {}}])] * 5
    control = TurnControl()
    turn = AgentTurn(transport=FakeTransport(responses), control=control, model="m1", provider="fake")
    control.interrupt()
    result = asyncio.run(turn.run("начни работу"))
    assert result.interrupted


def test_lease_serializes_sessions(home):
    store = SessionStore(home)
    sid = store.create_session()
    with SessionLease(store, sid, owner="первый"):
        with pytest.raises(LeaseLostError):
            SessionLease(store, sid, owner="второй").__enter__()
    # После освобождения аренда доступна снова.
    with SessionLease(store, sid, owner="второй") as lease:
        assert lease.held
    store.close()
