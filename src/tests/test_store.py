"""Тесты хранилища сессий и поиска."""

from __future__ import annotations

import io

import pytest

from prokop.store.sessions import SessionStore
from prokop.store.search import (
    search_messages,
    search_sessions,
    sanitize_query,
)
from prokop.store.portability import export_sessions, import_sessions


@pytest.fixture()
def store(home):
    s = SessionStore(home)
    yield s
    s.close()


def test_session_and_messages(store):
    sid = store.create_session(source="cli", model="m1")
    p0 = store.add_message(sid, "user", "привет")
    p1 = store.add_message(sid, "assistant", "здравствуй", tool_calls=[{"id": "1"}])
    assert (p0, p1) == (0, 1)
    messages = store.get_messages(sid)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    session = store.get_session(sid)
    assert session["message_count"] == 2
    assert session["tool_call_count"] == 1


def test_system_prompt_content_addressed(store):
    store.save_system_prompt("hash-a", "текст промпта")
    store.save_system_prompt("hash-a", "другой текст")  # не перезаписывает
    assert store.get_system_prompt("hash-a") == "текст промпта"


def test_usage_recorded(store):
    sid = store.create_session()
    store.record_usage(sid, "m1", tokens_in=10, tokens_out=5)
    usage = store.get_usage(sid)
    assert usage[0]["calls"] == 1
    session = store.get_session(sid)
    assert session["tokens_in"] == 10


def test_lease_blocks_second_owner(store):
    sid = store.create_session()
    assert store.acquire_lease(sid, "owner-1")
    assert not store.acquire_lease(sid, "owner-2")
    store.release_lease(sid, "owner-1")
    assert store.acquire_lease(sid, "owner-2")


def test_fts5_search_finds_text(store):
    sid = store.create_session()
    store.add_message(sid, "user", "квантовая запутанность в кремнии")
    store.add_message(sid, "assistant", "совершенно другое сообщение")
    results = search_messages(store._conn, "квантовая запутанность")
    assert len(results) == 1
    assert results[0]["session_id"] == sid


def test_search_sessions_bookends(store):
    sid = store.create_session()
    store.add_message(sid, "user", "начало разговора")
    store.add_message(sid, "assistant", "ищем именно это слово маркер")
    store.add_message(sid, "user", "конец разговора")
    hits = search_sessions(store._conn, "маркер")
    assert len(hits) == 1
    bookends = hits[0]["bookends"]
    assert bookends["first"]["content"] == "начало разговора"
    assert bookends["last"]["content"] == "конец разговора"
    assert len(hits[0]["window"]) >= 1


def test_sanitize_query_strips_fts_operators():
    cleaned = sanitize_query('drop * AND "table"')
    assert "*" not in cleaned
    # Каждое слово обёрнуто в литеральную фразу — операторы обезврежены.
    for word in ("drop", "AND", "table"):
        assert f'"{word}"' in cleaned


def test_export_import_roundtrip(store, home):
    sid = store.create_session(model="m1")
    store.add_message(sid, "user", "сообщение")
    buffer = io.StringIO()
    count = export_sessions(store, buffer)
    assert count == 1

    target = SessionStore(home / "second")
    result = import_sessions(target, io.StringIO(buffer.getvalue()))
    assert result.imported == 1
    # Повторный импорт — пропуск существующих.
    again = import_sessions(target, io.StringIO(buffer.getvalue()))
    assert again.skipped_existing == 1
    target.close()
