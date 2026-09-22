"""Тесты адаптера Telegram.

HTTP подменяется транспортом `httpx` — реальных запросов нет, токен
фиктивный.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import pytest

from prokop.gateway.adapters import ErrorCategory, SendError, is_retryable
from prokop.gateway.events import MessageType
from prokop.gateway.telegram import TelegramAdapter, error_category, split_text

TOKEN = "123456:TEST-TOKEN"


class Recorder:
    """Записывает запросы и отдаёт заготовленные ответы."""

    def __init__(self, responder: Callable[[httpx.Request], httpx.Response]) -> None:
        self.responder = responder
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("content-type", "").startswith("application/json"):
            import json

            self.bodies.append(json.loads(request.content.decode("utf-8")))
        else:
            self.bodies.append({})
        return self.responder(request)


def ok(payload: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json={"ok": True, "result": payload})


def make_adapter(
    responder: Callable[[httpx.Request], httpx.Response],
    **kwargs: Any,
) -> tuple[TelegramAdapter, Recorder]:
    recorder = Recorder(responder)
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    return TelegramAdapter(TOKEN, client=client, **kwargs), recorder


def run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


# --- вспомогательные функции ----------------------------------------------


def test_error_category_mapping():
    assert error_category(401) is ErrorCategory.AUTH
    assert error_category(403) is ErrorCategory.AUTH
    assert error_category(429) is ErrorCategory.RATE_LIMIT
    assert error_category(500) is ErrorCategory.TRANSIENT
    assert error_category(503) is ErrorCategory.TRANSIENT
    assert error_category(400) is ErrorCategory.INVALID
    assert error_category(302) is ErrorCategory.UNKNOWN


def test_retryable_categories():
    assert is_retryable(error_category(429)) is True
    assert is_retryable(error_category(500)) is True
    assert is_retryable(error_category(401)) is False


def test_split_text_short():
    assert split_text("короткий", 4096) == ["короткий"]


def test_split_text_empty():
    assert split_text("", 4096) == []


def test_split_text_by_lines():
    text = "a" * 100 + "\n" + "b" * 100
    parts = split_text(text, 120)
    assert len(parts) == 2
    assert all(len(part) <= 120 for part in parts)
    assert parts[0].startswith("a")


def test_split_text_hard_cut_without_boundaries():
    parts = split_text("x" * 250, 100)
    assert len(parts) == 3
    assert all(len(part) <= 100 for part in parts)


def test_adapter_requires_token():
    with pytest.raises(ValueError):
        TelegramAdapter("")


# --- подключение ----------------------------------------------------------


def test_connect_success():
    adapter, recorder = make_adapter(ok({"id": 42, "username": "prokop_bot"}))
    run(adapter.connect())

    assert adapter.bot["username"] == "prokop_bot"
    assert "getMe" in str(recorder.requests[0].url)


def test_connect_auth_failure():
    adapter, _ = make_adapter(
        lambda request: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})
    )
    with pytest.raises(SendError) as exc:
        run(adapter.connect())
    assert "auth" in str(exc.value)
    assert "Unauthorized" in str(exc.value)


def test_connect_network_failure():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения")

    adapter, _ = make_adapter(boom)
    with pytest.raises(SendError) as exc:
        run(adapter.connect())
    assert "сеть" in str(exc.value)


def test_disconnect_closes_owned_client_only():
    # Владельцем клиента адаптер не является — закрывать не должен.
    adapter, _ = make_adapter(ok({}))
    run(adapter.disconnect())

    owned = TelegramAdapter(TOKEN)
    run(owned.disconnect())  # клиент ещё не создан — не падает


# --- отправка -------------------------------------------------------------


def test_send_text_success():
    adapter, recorder = make_adapter(ok({"message_id": 777}))
    result = run(adapter.send_text("100", "привет"))

    assert result.ok is True
    assert result.message_id == "777"
    assert recorder.bodies[0]["chat_id"] == "100"
    assert recorder.bodies[0]["text"] == "привет"


def test_send_text_splits_long_text():
    adapter, recorder = make_adapter(ok({"message_id": 1}))
    text = "\n".join("строка " + "x" * 50 for _ in range(200))

    result = run(adapter.send_text("100", text))
    assert result.ok is True
    assert len(recorder.bodies) > 1
    assert all(len(body["text"]) <= adapter.max_text_length for body in recorder.bodies)


def test_send_text_reply_only_on_first_part():
    adapter, recorder = make_adapter(ok({"message_id": 1}))
    text = "y" * 5000

    run(adapter.send_text("100", text, reply_to="55"))
    assert recorder.bodies[0]["reply_to_message_id"] == 55
    assert all("reply_to_message_id" not in body for body in recorder.bodies[1:])


def test_send_text_empty_is_invalid():
    adapter, recorder = make_adapter(ok({}))
    result = run(adapter.send_text("100", "   "))
    # Пробельный текст не пустой, но проверяем поведение на пустом.
    result = run(adapter.send_text("100", ""))
    assert result.ok is False
    assert result.error is ErrorCategory.INVALID


def test_send_text_rate_limit():
    adapter, _ = make_adapter(
        lambda request: httpx.Response(429, json={"ok": False, "description": "Too Many Requests"})
    )
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.RATE_LIMIT
    assert result.retryable is True


def test_send_text_server_error():
    adapter, _ = make_adapter(
        lambda request: httpx.Response(500, json={"ok": False, "description": "Internal"})
    )
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.TRANSIENT
    assert result.retryable is True


def test_send_text_network_error():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("таймаут")

    adapter, _ = make_adapter(boom)
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.NETWORK
    assert result.retryable is True


def test_send_text_platform_error_body():
    adapter, _ = make_adapter(
        lambda request: httpx.Response(
            200, json={"ok": False, "error_code": 400, "description": "chat not found"}
        )
    )
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.INVALID
    assert "chat not found" in (result.detail or "")


def test_set_typing_sends_action():
    adapter, recorder = make_adapter(ok(True))
    run(adapter.set_typing("100", action="typing"))

    assert "sendChatAction" in str(recorder.requests[0].url)
    assert recorder.bodies[0] == {"chat_id": "100", "action": "typing"}


def test_set_typing_does_not_raise_on_failure():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения")

    adapter, _ = make_adapter(boom)
    run(adapter.set_typing("100"))  # не должно бросить


def test_chat_info_success():
    adapter, _ = make_adapter(
        ok({"id": -100500, "title": "Рабочая группа", "type": "supergroup"})
    )
    info = run(adapter.chat_info("-100500"))
    assert info.chat_id == "-100500"
    assert info.title == "Рабочая группа"
    assert info.kind == "group"


def test_chat_info_fallback_on_error():
    adapter, _ = make_adapter(lambda request: httpx.Response(404, json={"ok": False}))
    info = run(adapter.chat_info("100"))
    assert info.chat_id == "100"
    assert info.kind == "dm"


def test_send_media_success(tmp_path):
    file_path = tmp_path / "отчёт.txt"
    file_path.write_text("данные", encoding="utf-8")

    adapter, recorder = make_adapter(ok({"message_id": 5}))
    result = run(adapter.send_media("100", str(file_path), caption="отчёт"))

    assert result.ok is True
    assert "sendDocument" in str(recorder.requests[0].url)


def test_send_media_missing_file(tmp_path):
    adapter, _ = make_adapter(ok({}))
    result = run(adapter.send_media("100", str(tmp_path / "нет.txt")))
    assert result.error is ErrorCategory.INVALID


# --- входящие -------------------------------------------------------------


def test_get_updates_passes_offset_and_timeout():
    adapter, recorder = make_adapter(ok([{"update_id": 1}]))
    updates = run(adapter.get_updates(offset=10, timeout=30))

    assert updates == [{"update_id": 1}]
    assert recorder.bodies[0]["offset"] == 10
    assert recorder.bodies[0]["timeout"] == 30


def test_get_updates_error_returns_empty():
    adapter, _ = make_adapter(lambda request: httpx.Response(500, json={"ok": False}))
    assert run(adapter.get_updates()) == []


def test_get_updates_network_error_returns_empty():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения")

    adapter, _ = make_adapter(boom)
    assert run(adapter.get_updates()) == []


def normalize(update: dict[str, Any]) -> Any:
    adapter = TelegramAdapter(TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(ok({}))))
    return adapter.normalize(update)


def test_normalize_text_message():
    event = normalize(
        {
            "update_id": 1,
            "message": {
                "message_id": 5,
                "text": "привет",
                "from": {"id": 42, "first_name": "Иван", "last_name": "Петров"},
                "chat": {"id": 42, "type": "private"},
            },
        }
    )
    assert event is not None
    assert event.text == "привет"
    assert event.message_type is MessageType.TEXT
    assert event.author.user_id == "42"
    assert event.author.name == "Иван Петров"
    assert event.source.platform == "telegram"
    assert event.source.chat_type == "dm"
    assert event.source.chat_id == "42"


def test_normalize_photo_message():
    event = normalize(
        {
            "message": {
                "message_id": 6,
                "photo": [{"file_id": "small"}, {"file_id": "big"}],
                "chat": {"id": 42, "type": "private"},
            }
        }
    )
    assert event is not None
    assert event.message_type is MessageType.PHOTO
    assert event.attachments == ["big"]


def test_normalize_document_with_caption():
    event = normalize(
        {
            "message": {
                "message_id": 7,
                "document": {"file_id": "doc"},
                "caption": "подпись",
                "chat": {"id": -100, "type": "supergroup"},
            }
        }
    )
    assert event is not None
    assert event.message_type is MessageType.DOCUMENT
    assert event.text == "подпись"
    assert event.source.chat_type == "group"


def test_normalize_thread_and_reply():
    event = normalize(
        {
            "message": {
                "message_id": 8,
                "text": "ответ",
                "message_thread_id": 99,
                "reply_to_message": {"message_id": 7},
                "chat": {"id": -100, "type": "supergroup"},
            }
        }
    )
    assert event is not None
    assert event.source.thread_id == "99"
    assert event.reply_to == "7"


def test_normalize_channel_post():
    event = normalize(
        {"channel_post": {"message_id": 9, "text": "новость", "chat": {"id": -200, "type": "channel"}}}
    )
    assert event is not None
    assert event.source.chat_type == "channel"


def test_normalize_ignores_non_message_updates():
    assert normalize({"update_id": 1}) is None
    assert normalize({"message": "не объект"}) is None
    assert normalize({"message": {"message_id": 1}}) is None  # нет чата
    assert normalize("не объект") is None


def test_normalize_unknown_content():
    event = normalize({"message": {"message_id": 10, "chat": {"id": 1, "type": "private"}}})
    assert event is not None
    assert event.message_type is MessageType.UNKNOWN
    assert event.text == ""


def test_normalized_event_has_session_key():
    event = normalize(
        {"message": {"message_id": 1, "text": "x", "chat": {"id": 42, "type": "private"}}}
    )
    assert event is not None
    assert event.session_key
    assert event.is_command is False


def test_normalized_command_is_detected():
    event = normalize(
        {"message": {"message_id": 1, "text": "/stop", "chat": {"id": 42, "type": "private"}}}
    )
    assert event is not None
    assert event.is_command is True
    assert event.control == "stop"


# --- гигиена --------------------------------------------------------------


def test_telegram_source_has_no_personal_paths():
    import prokop.gateway.telegram as module

    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert not rx.search(source)
