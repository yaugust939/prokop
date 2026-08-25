"""Тесты гейтвея и абстракции платформ (обвес)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from prokop.gateway.adapters import (
    ChatInfo,
    ErrorCategory,
    PlatformAdapter,
    SendResult,
    is_retryable,
)
from prokop.gateway.auth import SenderGate, UnauthorizedPolicy
from prokop.gateway.cache import AgentCache
from prokop.gateway.engine import Gateway, HandleOutcome
from prokop.gateway.events import (
    CONTROL_NEW,
    CONTROL_RESET,
    CONTROL_STOP,
    Author,
    InboundEvent,
    MessageType,
    Source,
    parse_control_command,
)
from prokop.gateway.guard import Admit, SessionGuard, TurnMode
from prokop.gateway.keys import CHANNEL, DM, GROUP, session_key
from prokop.gateway.response import (
    mask_secrets,
    prepare_response,
    replace_provider_errors,
    sanitize_surrogates,
    truncate,
)


# --- 1. ключ сессии ---------------------------------------------------------


def test_session_key_dm_normalizes_type():
    assert session_key("telegram", "dm", "100") == "telegram:dm:100"


def test_session_key_group_includes_type():
    assert session_key("telegram", "group", "200") == "telegram:group:200"


def test_session_key_channel_includes_thread():
    assert (
        session_key("telegram", "channel", "300", "77")
        == "telegram:channel:300:77"
    )


def test_session_key_stable_for_same_source():
    a = session_key("telegram", "group", "200", "5")
    b = session_key("telegram", "group", "200", "5")
    assert a == b


def test_session_key_dm_ignores_thread():
    assert session_key("telegram", "dm", "100", "99") == "telegram:dm:100"


def test_session_key_distinct_sources():
    keys = {
        session_key("telegram", "dm", "100"),
        session_key("telegram", "group", "100"),
        session_key("discord", "dm", "100"),
        session_key("telegram", "channel", "100", "1"),
        session_key("telegram", "channel", "100", "2"),
    }
    assert len(keys) == 5


# --- 2. нормализованное событие --------------------------------------------


def _event(text="привет", **kwargs):
    source = Source(platform="telegram", chat_type="dm", chat_id="100")
    return InboundEvent(text=text, author=Author("u1", "Иван"), source=source, **kwargs)


def test_event_command_by_leading_slash():
    assert _event("/stop").is_command is True
    assert _event("привет").is_command is False


def test_event_photo_type_and_attachment():
    event = _event(
        text="",
        message_type=MessageType.PHOTO,
        attachments=["/tmp/photo.jpg"],
    )
    assert event.message_type is MessageType.PHOTO
    assert event.attachments == ["/tmp/photo.jpg"]


def test_event_session_key_derived():
    event = _event()
    assert event.session_key == "telegram:dm:100"


def test_event_timestamp_defaults_to_now():
    assert isinstance(_event().timestamp, datetime)


def test_parse_control_command():
    assert parse_control_command("/stop") == CONTROL_STOP
    assert parse_control_command("стоп") == CONTROL_STOP
    assert parse_control_command("/new") == CONTROL_NEW
    assert parse_control_command("сброс") == CONTROL_RESET
    assert parse_control_command("привет") is None


def test_event_control_property():
    assert _event("/reset").control == CONTROL_RESET
    assert _event("привет").control is None


# --- 3. контракт адаптера ---------------------------------------------------


class _FakeAdapter(PlatformAdapter):
    platform = "telegram"

    def __init__(self):
        self.connected = False
        self.sent = []
        self.typing = []

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def send_text(self, chat_id, text, *, reply_to=None):
        self.sent.append((chat_id, text, reply_to))
        return SendResult.success("mid-1")

    async def set_typing(self, chat_id, *, action="typing"):
        self.typing.append((chat_id, action))

    async def chat_info(self, chat_id):
        return ChatInfo(chat_id=chat_id, kind="dm")


def test_adapter_optional_stubs_unsupported():
    async def run():
        adapter = _FakeAdapter()
        media = await adapter.send_media("100", "/tmp/x.jpg")
        cards = await adapter.send_cards("100", [])
        edit = await adapter.edit_message("100", "m", "текст")
        return media, cards, edit

    media, cards, edit = asyncio.run(run())
    for result in (media, cards, edit):
        assert result.ok is False
        assert result.error is ErrorCategory.UNSUPPORTED
        assert result.retryable is False


def test_adapter_lifecycle_and_send():
    async def run():
        adapter = _FakeAdapter()
        await adapter.connect()
        await adapter.set_typing("100")
        result = await adapter.send_text("100", "привет", reply_to="5")
        info = await adapter.chat_info("100")
        await adapter.disconnect()
        return adapter, result, info

    adapter, result, info = asyncio.run(run())
    assert adapter.connected is False
    assert result.ok is True and result.message_id == "mid-1"
    assert adapter.typing == [("100", "typing")]
    assert info.kind == "dm"


def test_send_result_failure_classification():
    result = SendResult.failure(ErrorCategory.RATE_LIMIT)
    assert result.ok is False
    assert result.retryable is True
    assert is_retryable(ErrorCategory.NETWORK) is True
    assert is_retryable(ErrorCategory.INVALID) is False


# --- 4. авторизация отправителя --------------------------------------------


def test_auth_allow_all_explicit():
    gate = SenderGate(allow_all=True)
    assert gate.authorize("telegram", "u1").allowed is True


def test_auth_whitelist_per_platform():
    gate = SenderGate()
    gate.grant("telegram", "u1")
    assert gate.authorize("telegram", "u1").allowed is True
    assert gate.authorize("telegram", "u2").allowed is False
    assert gate.authorize("discord", "u1").allowed is False


def test_auth_unauthorized_ignore_policy():
    gate = SenderGate()
    decision = gate.authorize("telegram", "unknown")
    assert decision.allowed is False
    assert decision.policy is UnauthorizedPolicy.IGNORE


def test_auth_unauthorized_pair_policy():
    gate = SenderGate(policy=UnauthorizedPolicy.PAIR)
    decision = gate.authorize("telegram", "unknown")
    assert decision.policy is UnauthorizedPolicy.PAIR


def test_auth_revoke():
    gate = SenderGate()
    gate.grant("telegram", "u1")
    assert gate.revoke("telegram", "u1") is True
    assert gate.authorize("telegram", "u1").allowed is False
    assert gate.revoke("telegram", "u1") is False


# --- 5. защита от параллельных ходов ---------------------------------------


def test_guard_run_when_idle():
    guard = SessionGuard()
    assert guard.admit("s1") is Admit.RUN


def test_guard_control_bypasses_active_turn():
    guard = SessionGuard()
    guard.start("s1", "t1")
    assert guard.admit("s1", control=True) is Admit.BYPASS


def test_guard_interrupt_mode():
    guard = SessionGuard(mode=TurnMode.INTERRUPT)
    guard.start("s1", "t1")
    assert guard.admit("s1") is Admit.INTERRUPT


def test_guard_queue_mode():
    guard = SessionGuard(mode=TurnMode.QUEUE)
    guard.start("s1", "t1")
    assert guard.admit("s1") is Admit.QUEUE


def test_guard_finish_pops_queue():
    guard = SessionGuard(mode=TurnMode.QUEUE)
    guard.start("s1", "t1")
    guard.enqueue("s1", "t2")
    guard.enqueue("s1", "t3")
    assert guard.finish("s1", "t1") == "t2"
    assert guard.finish("s1", "t2") == "t3"
    assert guard.finish("s1", "t3") is None


def test_guard_finish_foreign_turn_ignored():
    guard = SessionGuard()
    guard.start("s1", "t1")
    assert guard.finish("s1", "other") is None
    assert guard.has_active("s1") is True


# --- 6. кэш агентов по сессиям ---------------------------------------------


class _Agent:
    def __init__(self):
        self.unloaded = False

    def unload(self):
        self.unloaded = True


def test_cache_reuses_agent():
    cache = AgentCache(max_size=4)
    agent = _Agent()
    cache.put("s1", agent)
    assert cache.get("s1") is agent


def test_cache_size_evicts_lru_and_unloads():
    evicted = []
    cache = AgentCache(max_size=2, on_evict=lambda s, a: evicted.append(s))
    for i in range(3):
        cache.put(f"s{i}", _Agent())
    # s0 вытеснен (LRU).
    assert "s0" not in cache
    assert evicted == ["s0"]
    # Обращение к s1 делает s2 LRU.
    cache.get("s1")
    cache.put("s3", _Agent())
    assert "s2" not in cache
    assert evicted == ["s0", "s2"]


def test_cache_ttl_idle_evicts():
    now = [0.0]
    cache = AgentCache(ttl_seconds=10, clock=lambda: now[0])
    agent = _Agent()
    cache.put("s1", agent)
    assert cache.get("s1") is agent
    now[0] = 11.0
    assert cache.get("s1") is None
    assert agent.unloaded is True


def test_cache_unload_uses_agent_method():
    cache = AgentCache()
    agent = _Agent()
    cache.put("s1", agent)
    assert cache.evict("s1") is True
    assert agent.unloaded is True
    assert cache.evict("s1") is False


def test_cache_clear_unloads_all():
    cache = AgentCache()
    agents = [_Agent(), _Agent()]
    cache.put("s1", agents[0])
    cache.put("s2", agents[1])
    cache.clear()
    assert len(cache) == 0
    assert all(a.unloaded for a in agents)


# --- 7. подготовка ответа ---------------------------------------------------


def test_sanitize_surrogates():
    bad = "привет\ud800 мир"
    clean = sanitize_surrogates(bad)
    assert "\ud800" not in clean
    assert "привет" in clean and "мир" in clean


def test_sanitize_keeps_valid_astral():
    text = "улыбка 😀 ок"
    assert sanitize_surrogates(text) == text


def test_mask_secrets_openai_key():
    text = "ключ sk-abcdefghijklmnopqrstuvwxyz123456"
    assert "sk-" not in mask_secrets(text)
    assert "[REDACTED]" in mask_secrets(text)


def test_mask_secrets_telegram_token():
    text = "токен 123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"
    masked = mask_secrets(text)
    assert "123456789" not in masked
    assert "[REDACTED]" in masked


def test_mask_secrets_jwt():
    text = "token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def456ghi789"
    assert "eyJ" not in mask_secrets(text)


def test_replace_provider_errors():
    assert "лимит" in replace_provider_errors("OpenAI rate limit reached")
    assert "перегружен" in replace_provider_errors("server overloaded 503")


def test_truncate_to_limit():
    assert truncate("abcdef", 3) == "abc"


def test_prepare_response_full_pipeline():
    raw = "секрет sk-abcdefghijklmnopqrstuvwxyz123456 и rate limit"
    prepared = prepare_response(raw, max_length=100)
    assert "sk-" not in prepared
    assert "лимит" in prepared


# --- оркестратор гейтвея ----------------------------------------------------


def _make_event(text, platform="telegram", chat_id="100", user_id="u1"):
    source = Source(platform=platform, chat_type="dm", chat_id=chat_id)
    return InboundEvent(text=text, author=Author(user_id, "Иван"), source=source)


async def _echo(session, text):
    return "ответ: " + text


def test_gateway_responds_via_run_turn():
    async def run():
        gw = Gateway(_echo, authorizer=SenderGate(allow_all=True))
        result = await gw.handle(_make_event("привет"))
        return result

    result = asyncio.run(run())
    assert result.outcome is HandleOutcome.RESPONDED
    assert result.text == "ответ: привет"


def test_gateway_ignores_unauthorized():
    async def run():
        gw = Gateway(_echo, authorizer=SenderGate())
        result = await gw.handle(_make_event("привет"))
        return result

    result = asyncio.run(run())
    assert result.outcome is HandleOutcome.IGNORED
    assert result.text is None


def test_gateway_pairing_for_unauthorized():
    async def run():
        gate = SenderGate(policy=UnauthorizedPolicy.PAIR)
        gw = Gateway(_echo, authorizer=gate)
        result = await gw.handle(_make_event("привет"))
        return result

    result = asyncio.run(run())
    assert result.outcome is HandleOutcome.PAIRING
    assert "Код" in result.text


def test_gateway_control_command_bypasses_guard():
    async def run():
        gw = Gateway(_echo, authorizer=SenderGate(allow_all=True))
        result = await gw.handle(_make_event("/stop"))
        return result

    result = asyncio.run(run())
    assert result.outcome is HandleOutcome.CONTROL
    assert result.text == "Ход остановлен."


def test_gateway_queue_mode_queues_during_active_turn():
    async def run():
        guard = SessionGuard(mode=TurnMode.QUEUE)
        gw = Gateway(_echo, guard=guard, authorizer=SenderGate(allow_all=True))
        guard.start("telegram:dm:100", "active")
        result = await gw.handle(_make_event("привет"))
        return result, guard

    result, guard = asyncio.run(run())
    assert result.outcome is HandleOutcome.QUEUED
    assert guard.queue_length("telegram:dm:100") == 1


def test_gateway_reuses_agent_across_turns():
    created = []

    def factory(session):
        created.append(session)
        return _Agent()

    async def run():
        cache = AgentCache(max_size=4)
        gw = Gateway(
            _echo,
            cache=cache,
            agent_factory=factory,
            authorizer=SenderGate(allow_all=True),
        )
        await gw.handle(_make_event("один"))
        await gw.handle(_make_event("два"))
        return cache, created

    cache, created = asyncio.run(run())
    assert created == ["telegram:dm:100"]
    assert "telegram:dm:100" in cache


def test_gateway_new_control_evicts_agent():
    async def run():
        cache = AgentCache(max_size=4)
        cache.put("telegram:dm:100", _Agent())
        gw = Gateway(_echo, cache=cache, authorizer=SenderGate(allow_all=True))
        result = await gw.handle(_make_event("/new"))
        return result, cache

    result, cache = asyncio.run(run())
    assert result.outcome is HandleOutcome.CONTROL
    assert "telegram:dm:100" not in cache


def test_gateway_trims_response_to_limit():
    async def run():
        gw = Gateway(_echo, max_response_length=5, authorizer=SenderGate(allow_all=True))
        result = await gw.handle(_make_event("привет"))
        return result

    result = asyncio.run(run())
    assert result.text == "ответ"


def test_gateway_masks_secret_in_response():
    async def run():
        async def leak(session, text):
            return "секрет sk-abcdefghijklmnopqrstuvwxyz123456"

        gw = Gateway(leak, authorizer=SenderGate(allow_all=True))
        result = await gw.handle(_make_event("дай ключ"))
        return result

    result = asyncio.run(run())
    assert "sk-" not in result.text
    assert "[REDACTED]" in result.text
