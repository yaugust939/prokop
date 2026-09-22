"""Тесты адаптера MAX.

HTTP подменяется транспортом `httpx` — реальных запросов нет, токен фиктивный.
Факты о платформе взяты из официальной документации (dev.max.ru/docs-api) и
OpenAPI-схемы (github.com/max-messenger/api-schema).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import pytest

from prokop.gateway.adapters import ErrorCategory, SendError, is_retryable, split_text
from prokop.gateway.events import MessageType
from prokop.gateway.max import (
    DEFAULT_BASE_URL,
    MaxAdapter,
    error_category,
    message_mid,
    recipient_params,
    upload_type_for,
)

TOKEN = "test-access-token"


class Recorder:
    """Записывает запросы и отдаёт ответы по маршрутам."""

    def __init__(self, responder: Callable[[httpx.Request], httpx.Response]) -> None:
        self.responder = responder
        self.requests: list[httpx.Request] = []
        self.json_bodies: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body: dict[str, Any] = {}
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("application/json") and request.content:
            try:
                parsed = json.loads(request.content.decode("utf-8"))
                if isinstance(parsed, dict):
                    body = parsed
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {}
        self.json_bodies.append(body)
        return self.responder(request)


def make_adapter(
    responder: Callable[[httpx.Request], httpx.Response],
    **kwargs: Any,
) -> tuple[MaxAdapter, Recorder]:
    recorder = Recorder(responder)
    client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    return MaxAdapter(TOKEN, client=client, **kwargs), recorder


def ok(payload: Any) -> Callable[[httpx.Request], httpx.Response]:
    return lambda request: httpx.Response(200, json=payload)


def message_response(mid: str = "msg-1") -> Callable[[httpx.Request], httpx.Response]:
    return ok({"message": {"body": {"mid": mid}}})


def run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)


def auth_header(recorder: Recorder) -> Optional[str]:
    return recorder.requests[0].headers.get("authorization")


# --- вспомогательные функции ----------------------------------------------


def test_error_category_mapping():
    assert error_category(401) is ErrorCategory.AUTH
    assert error_category(429) is ErrorCategory.RATE_LIMIT
    assert error_category(503) is ErrorCategory.TRANSIENT
    assert error_category(500) is ErrorCategory.TRANSIENT
    assert error_category(400) is ErrorCategory.INVALID
    assert error_category(404) is ErrorCategory.INVALID
    assert error_category(405) is ErrorCategory.INVALID
    assert error_category(302) is ErrorCategory.UNKNOWN


def test_retryable_categories():
    assert is_retryable(error_category(429)) is True
    assert is_retryable(error_category(503)) is True
    assert is_retryable(error_category(401)) is False


def test_upload_type_by_extension():
    assert upload_type_for("a.png") == "image"
    assert upload_type_for("a.JPEG") == "image"
    assert upload_type_for("a.mp4") == "video"
    assert upload_type_for("a.webm") == "video"
    assert upload_type_for("a.mp3") == "audio"
    assert upload_type_for("a.pdf") == "file"
    assert upload_type_for("без-расширения") == "file"


def test_recipient_params():
    assert recipient_params("12345") == {"chat_id": 12345}
    assert recipient_params("user:678") == {"user_id": 678}
    assert recipient_params("USER:678") == {"user_id": 678}
    # Нечисловой идентификатор уходит как есть, без падения.
    assert recipient_params("abc") == {"chat_id": "abc"}


def test_message_mid_is_string():
    assert message_mid({"body": {"mid": "abc-1"}}) == "abc-1"
    assert message_mid({"body": {}}) is None
    assert message_mid("не объект") is None


def test_split_text_is_shared_with_telegram():
    assert split_text("короткий", 4096) == ["короткий"]
    assert split_text("", 4096) == []


def test_adapter_requires_token():
    with pytest.raises(ValueError):
        MaxAdapter("")


def test_default_base_url_is_current():
    # Документация платформы требует platform-api2 вместо platform-api.
    assert DEFAULT_BASE_URL == "https://platform-api2.max.ru"


# --- подключение ----------------------------------------------------------


def test_connect_success():
    adapter, recorder = make_adapter(ok({"user_id": 1, "name": "My Bot", "is_bot": True}))
    run(adapter.connect())

    assert adapter.bot["name"] == "My Bot"
    assert "/me" in str(recorder.requests[0].url)
    assert auth_header(recorder) == TOKEN


def test_connect_auth_failure():
    adapter, _ = make_adapter(
        lambda request: httpx.Response(401, json={"code": "verify.token", "message": "invalid token"})
    )
    with pytest.raises(SendError) as exc:
        run(adapter.connect())
    assert "auth" in str(exc.value)
    assert "invalid token" in str(exc.value)


def test_connect_network_failure():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения")

    adapter, _ = make_adapter(boom)
    with pytest.raises(SendError) as exc:
        run(adapter.connect())
    assert "сеть" in str(exc.value)


def test_disconnect_closes_owned_client_only():
    adapter, _ = make_adapter(ok({}))
    run(adapter.disconnect())  # клиент инжектирован — закрывать не должен

    owned = MaxAdapter(TOKEN)
    run(owned.disconnect())  # клиент ещё не создан — не падает


# --- отправка текста ------------------------------------------------------


def test_send_text_success():
    adapter, recorder = make_adapter(message_response("mid-777"))
    result = run(adapter.send_text("100", "привет"))

    assert result.ok is True
    assert result.message_id == "mid-777"
    assert recorder.requests[0].url.params["chat_id"] == "100"
    assert recorder.json_bodies[0]["text"] == "привет"


def test_send_text_to_user():
    adapter, recorder = make_adapter(message_response())
    run(adapter.send_text("user:42", "привет"))

    params = recorder.requests[0].url.params
    assert params["user_id"] == "42"
    assert "chat_id" not in params


def test_send_text_splits_long_text():
    adapter, recorder = make_adapter(message_response())
    text = "\n".join("строка " + "x" * 50 for _ in range(200))

    result = run(adapter.send_text("100", text))
    assert result.ok is True
    assert len(recorder.json_bodies) > 1
    assert all(len(body["text"]) <= adapter.max_text_length for body in recorder.json_bodies)


def test_send_text_reply_only_on_first_part():
    adapter, recorder = make_adapter(message_response())
    run(adapter.send_text("100", "y" * 5000, reply_to="mid-original"))

    assert recorder.json_bodies[0]["link"] == {"type": "reply", "mid": "mid-original"}
    assert all("link" not in body for body in recorder.json_bodies[1:])


def test_send_text_empty_is_invalid():
    adapter, recorder = make_adapter(message_response())
    result = run(adapter.send_text("100", ""))

    assert result.ok is False
    assert result.error is ErrorCategory.INVALID
    assert recorder.requests == []


def test_send_text_auth_error():
    adapter, _ = make_adapter(lambda request: httpx.Response(401, json={"message": "unauthorized"}))
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.AUTH
    assert result.retryable is False


def test_send_text_rate_limit():
    adapter, _ = make_adapter(lambda request: httpx.Response(429, json={"message": "too many"}))
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.RATE_LIMIT
    assert result.retryable is True


def test_send_text_service_unavailable():
    adapter, _ = make_adapter(lambda request: httpx.Response(503, json={"message": "down"}))
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.TRANSIENT
    assert result.retryable is True


def test_send_text_invalid_request():
    adapter, _ = make_adapter(lambda request: httpx.Response(400, json={"message": "bad"}))
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.INVALID


def test_send_text_network_error():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("таймаут")

    adapter, _ = make_adapter(boom)
    result = run(adapter.send_text("100", "привет"))
    assert result.error is ErrorCategory.NETWORK
    assert result.retryable is True


def test_send_text_success_false_body():
    adapter, _ = make_adapter(ok({"success": False, "message": "не отправлено"}))
    result = run(adapter.send_text("100", "привет"))
    assert result.ok is False
    assert "не отправлено" in (result.detail or "")


# --- действие бота --------------------------------------------------------


def test_set_typing_in_group_chat():
    adapter, recorder = make_adapter(ok({"success": True}))
    run(adapter.set_typing("100", action="typing"))

    assert "/chats/100/actions" in str(recorder.requests[0].url)
    assert recorder.json_bodies[0] == {"action": "typing_on"}


def test_set_typing_maps_media_actions():
    adapter, recorder = make_adapter(ok({"success": True}))
    run(adapter.set_typing("100", action="photo"))
    assert recorder.json_bodies[0]["action"] == "sending_photo"


def test_set_typing_skipped_for_dialog():
    adapter, recorder = make_adapter(ok({"success": True}))
    run(adapter.set_typing("user:42"))
    assert recorder.requests == []


def test_set_typing_does_not_raise_on_failure():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения")

    adapter, _ = make_adapter(boom)
    run(adapter.set_typing("100"))  # не должно бросить


# --- информация о чате ----------------------------------------------------


def test_chat_info_success():
    adapter, recorder = make_adapter(
        ok({"chat_id": -100, "type": "chat", "title": "Рабочий чат", "participants_count": 5})
    )
    info = run(adapter.chat_info("-100"))

    assert info.chat_id == "-100"
    assert info.title == "Рабочий чат"
    assert info.kind == "group"
    assert info.member_count == 5
    assert "/chats/-100" in str(recorder.requests[0].url)


def test_chat_info_channel_and_dialog_kinds():
    adapter, _ = make_adapter(ok({"chat_id": -200, "type": "channel", "title": "Канал"}))
    assert run(adapter.chat_info("-200")).kind == "channel"

    adapter2, _ = make_adapter(ok({"chat_id": 42, "type": "dialog"}))
    assert run(adapter2.chat_info("42")).kind == "dm"


def test_chat_info_fallback_on_error():
    adapter, _ = make_adapter(lambda request: httpx.Response(404, json={"message": "not found"}))
    info = run(adapter.chat_info("100"))
    assert info.chat_id == "100"
    assert info.kind == "dm"


def test_chat_info_for_user_prefix_makes_no_request():
    adapter, recorder = make_adapter(ok({}))
    info = run(adapter.chat_info("user:42"))
    assert info.chat_id == "42"
    assert info.kind == "dm"
    assert recorder.requests == []


# --- медиа ----------------------------------------------------------------


def upload_router(
    upload_token: Optional[str] = "upload-token",
    *,
    nested: bool = False,
    first_token: Optional[str] = "first-token",
) -> Callable[[httpx.Request], httpx.Response]:
    """Маршрутизация: /uploads → ссылка, upload-URL → токен, /messages → сообщение."""

    def responder(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/uploads" in url:
            payload: dict[str, Any] = {"url": "https://upload.example/media"}
            if first_token:
                payload["token"] = first_token
            return httpx.Response(200, json=payload)
        if url.startswith("https://upload.example/"):
            if nested:
                return httpx.Response(
                    200, json={"photos": {"photoIds": {"token": "nested-token"}}}
                )
            return httpx.Response(200, json={"token": upload_token})
        return httpx.Response(200, json={"message": {"body": {"mid": "media-1"}}})

    return responder


def test_send_media_two_step_with_first_token(tmp_path):
    file_path = tmp_path / "документ.pdf"
    file_path.write_text("данные", encoding="utf-8")

    adapter, recorder = make_adapter(upload_router(first_token="first-token"))
    result = run(adapter.send_media("100", str(file_path), caption="подпись"))

    assert result.ok is True
    urls = [str(request.url) for request in recorder.requests]
    assert any("/uploads" in url for url in urls)
    assert any(url.startswith("https://upload.example/") for url in urls)

    attachment = recorder.json_bodies[-1]["attachments"][0]
    assert attachment["type"] == "file"
    assert attachment["payload"]["token"] == "first-token"
    assert attachment["text"] == "подпись"


def test_send_media_token_from_upload_response(tmp_path):
    file_path = tmp_path / "audio.mp3"
    file_path.write_bytes(b"data")

    adapter, recorder = make_adapter(upload_router(upload_token="second-token", first_token=None))
    result = run(adapter.send_media("100", str(file_path)))

    assert result.ok is True
    attachment = recorder.json_bodies[-1]["attachments"][0]
    assert attachment["type"] == "audio"
    assert attachment["payload"]["token"] == "second-token"


def test_send_media_nested_photo_token(tmp_path):
    file_path = tmp_path / "photo.png"
    file_path.write_bytes(b"png")

    adapter, recorder = make_adapter(upload_router(nested=True, first_token=None))
    result = run(adapter.send_media("100", str(file_path)))

    assert result.ok is True
    attachment = recorder.json_bodies[-1]["attachments"][0]
    assert attachment["type"] == "image"
    assert attachment["payload"]["token"] == "nested-token"


def test_send_media_upload_type_from_extension(tmp_path):
    file_path = tmp_path / "video.mp4"
    file_path.write_bytes(b"mp4")

    adapter, recorder = make_adapter(upload_router())
    run(adapter.send_media("100", str(file_path)))
    assert recorder.requests[0].url.params["type"] == "video"


def test_send_media_missing_file(tmp_path):
    adapter, recorder = make_adapter(upload_router())
    result = run(adapter.send_media("100", str(tmp_path / "нет.pdf")))

    assert result.error is ErrorCategory.INVALID
    assert recorder.requests == []


def test_send_media_no_token_from_platform(tmp_path):
    file_path = tmp_path / "file.bin"
    file_path.write_bytes(b"x")

    adapter, _ = make_adapter(upload_router(first_token=None, upload_token=None))
    result = run(adapter.send_media("100", str(file_path)))
    assert result.ok is False
    assert "токен" in (result.detail or "")


def test_send_media_upload_failure(tmp_path):
    file_path = tmp_path / "file.bin"
    file_path.write_bytes(b"x")

    def responder(request: httpx.Request) -> httpx.Response:
        if "/uploads" in str(request.url):
            return httpx.Response(200, json={"url": "https://upload.example/media"})
        return httpx.Response(503, json={"message": "down"})

    adapter, _ = make_adapter(responder)
    result = run(adapter.send_media("100", str(file_path)))
    assert result.error is ErrorCategory.TRANSIENT


# --- длинный опрос --------------------------------------------------------


def test_get_updates_stores_marker():
    adapter, recorder = make_adapter(ok({"updates": [{"update_type": "message_created"}], "marker": 10}))
    updates = run(adapter.get_updates(timeout=5, limit=10))

    assert updates == [{"update_type": "message_created"}]
    assert adapter.marker == 10
    assert "marker" not in recorder.requests[0].url.params
    assert recorder.requests[0].url.params["timeout"] == "5"
    assert recorder.requests[0].url.params["limit"] == "10"


def test_get_updates_passes_stored_marker():
    adapter, recorder = make_adapter(ok({"updates": [], "marker": 11}))
    adapter.marker = 10
    run(adapter.get_updates())

    assert recorder.requests[0].url.params["marker"] == "10"
    assert adapter.marker == 11


def test_get_updates_error_returns_empty():
    adapter, _ = make_adapter(lambda request: httpx.Response(500, json={"message": "boom"}))
    assert run(adapter.get_updates()) == []


def test_get_updates_network_error_returns_empty():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет соединения")

    adapter, _ = make_adapter(boom)
    assert run(adapter.get_updates()) == []


def test_get_updates_types_filter():
    adapter, recorder = make_adapter(ok({"updates": [], "marker": 1}))
    run(adapter.get_updates(types=["message_created", "message_callback"]))
    assert recorder.requests[0].url.params["types"] == "message_created,message_callback"


# --- нормализация ---------------------------------------------------------


def normalize(update: dict[str, Any]) -> Any:
    adapter = MaxAdapter(
        TOKEN, client=httpx.AsyncClient(transport=httpx.MockTransport(ok({})))
    )
    return adapter.normalize(update)


def test_normalize_message_created_dialog():
    event = normalize(
        {
            "update_type": "message_created",
            "timestamp": 1737500130100,
            "chat_id": 42,
            "message": {
                "sender": {"user_id": 42, "first_name": "Иван", "last_name": "Петров"},
                "recipient": {"chat_id": 42, "chat_type": "dialog", "user_id": 42},
                "body": {"mid": "mid-1", "text": "привет"},
            },
        }
    )
    assert event is not None
    assert event.text == "привет"
    assert event.message_type is MessageType.TEXT
    assert event.author.user_id == "42"
    assert event.author.name == "Иван Петров"
    assert event.source.platform == "max"
    assert event.source.chat_type == "dm"
    assert event.source.chat_id == "42"
    assert event.source.thread_id is None


def test_normalize_chat_and_channel_kinds():
    group = normalize(
        {
            "update_type": "message_created",
            "chat_id": -100,
            "message": {
                "recipient": {"chat_id": -100, "chat_type": "chat"},
                "body": {"text": "в чате"},
            },
        }
    )
    assert group is not None
    assert group.source.chat_type == "group"

    channel = normalize(
        {
            "update_type": "message_created",
            "chat_id": -200,
            "is_channel": True,
            "message": {
                "recipient": {"chat_id": -200, "chat_type": "channel"},
                "body": {"text": "пост"},
            },
        }
    )
    assert channel is not None
    assert channel.source.chat_type == "channel"


def test_normalize_channel_post_without_sender():
    event = normalize(
        {
            "update_type": "message_created",
            "chat_id": -200,
            "is_channel": True,
            "message": {
                "recipient": {"chat_id": -200, "chat_type": "channel"},
                "body": {"mid": "post-1", "text": "новость"},
            },
        }
    )
    assert event is not None
    assert event.text == "новость"
    assert event.author.user_id == "-200"


def test_normalize_attachments():
    event = normalize(
        {
            "update_type": "message_created",
            "chat_id": 1,
            "message": {
                "recipient": {"chat_id": 1, "chat_type": "dialog"},
                "body": {
                    "mid": "m",
                    "text": "смотри",
                    "attachments": [{"type": "image", "payload": {"token": "tok-1"}}],
                },
            },
        }
    )
    assert event is not None
    assert event.message_type is MessageType.PHOTO
    assert event.attachments == ["tok-1"]


def test_normalize_reply_context():
    event = normalize(
        {
            "update_type": "message_created",
            "chat_id": 1,
            "message": {
                "recipient": {"chat_id": 1, "chat_type": "dialog"},
                "body": {"mid": "m", "text": "ответ"},
                "link": {"type": "reply", "message": {"mid": "original-1"}},
            },
        }
    )
    assert event is not None
    assert event.reply_to == "original-1"


def test_normalize_forward_is_not_reply():
    event = normalize(
        {
            "update_type": "message_created",
            "chat_id": 1,
            "message": {
                "recipient": {"chat_id": 1, "chat_type": "dialog"},
                "body": {"text": "переслано"},
                "link": {"type": "forward", "message": {"mid": "other"}},
            },
        }
    )
    assert event is not None
    assert event.reply_to is None


def test_normalize_callback_as_text():
    event = normalize(
        {
            "update_type": "message_callback",
            "chat_id": 77,
            "callback": {
                "timestamp": 1,
                "callback_id": "cb-1",
                "payload": "Кнопка 1 нажата",
                "user": {"user_id": 5, "first_name": "Пётр"},
            },
        }
    )
    assert event is not None
    assert event.text == "Кнопка 1 нажата"
    assert event.author.user_id == "5"
    assert event.author.name == "Пётр"
    assert event.source.chat_id == "77"


def test_normalize_ignores_other_updates():
    assert normalize({"update_type": "bot_added", "chat_id": 1}) is None
    assert normalize({"update_type": "message_removed", "chat_id": 1}) is None
    assert normalize({"chat_id": 1}) is None
    assert normalize("не объект") is None


def test_normalize_message_created_without_message():
    assert normalize({"update_type": "message_created", "chat_id": 1}) is None


def test_normalize_without_chat_id():
    assert (
        normalize(
            {
                "update_type": "message_created",
                "message": {"body": {"text": "нет получателя"}},
            }
        )
        is None
    )


def test_normalized_event_session_key_and_command():
    event = normalize(
        {
            "update_type": "message_created",
            "chat_id": 1,
            "message": {
                "recipient": {"chat_id": 1, "chat_type": "dialog"},
                "body": {"text": "/stop"},
            },
        }
    )
    assert event is not None
    assert event.session_key
    assert event.is_command is True
    assert event.control == "stop"


def test_normalized_event_is_platform_distinct():
    """Ключи сессий MAX и Telegram не должны совпадать при одинаковых чатах."""
    max_event = normalize(
        {
            "update_type": "message_created",
            "chat_id": 1,
            "message": {
                "recipient": {"chat_id": 1, "chat_type": "dialog"},
                "body": {"text": "x"},
            },
        }
    )
    assert max_event is not None
    assert "max" in max_event.session_key


# --- гигиена --------------------------------------------------------------


def test_max_source_has_no_personal_paths():
    import prokop.gateway.max as module

    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert not rx.search(source)
