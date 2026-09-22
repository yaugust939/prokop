"""Адаптер платформы MAX поверх HTTP Bot API.

Официальная документация: https://dev.max.ru/docs-api
Схема OpenAPI: https://github.com/max-messenger/api-schema

Отличия от Telegram, учтённые здесь:

- база `platform-api2.max.ru`, авторизация заголовком `Authorization`
  (передача токена в query-параметрах больше не поддерживается);
- указатель длинного опроса — `marker`, а не числовое смещение;
- идентификатор сообщения (`mid`) — строка, а не число;
- адресация получателя: `chat_id` для чата или канала, `user_id` для
  пользователя; поддерживается явный префикс `user:<id>`;
- действие «набор текста» доступно только в групповых чатах;
- медиа загружается в два шага: `POST /uploads` выдаёт ссылку и токен,
  файл загружается по ссылке, затем токен прикладывается к сообщению.

Клиент `httpx` инжектируется — тесты подменяют транспорт и не выходят в сеть.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import httpx

from prokop.gateway.adapters import (
    ChatInfo,
    ErrorCategory,
    PlatformAdapter,
    SendError,
    SendResult,
    split_text,
)
from prokop.gateway.events import Author, InboundEvent, MessageType, Source
from prokop.logging_setup import get_logger

log = get_logger("gateway.max")

#: База Bot API MAX (вместо устаревшего platform-api.max.ru).
DEFAULT_BASE_URL = "https://platform-api2.max.ru"

#: Таймаут HTTP-клиента по умолчанию, секунд (больше длинного опроса).
DEFAULT_TIMEOUT = 60.0

#: Предел длины текста одного сообщения.
MAX_TEXT_LENGTH = 4000

#: Виды чатов платформы → вид чата события.
CHAT_KINDS: dict[str, str] = {
    "dialog": "dm",
    "chat": "group",
    "channel": "channel",
}

#: Действия контракта → действия платформы.
SENDER_ACTIONS: dict[str, str] = {
    "typing": "typing_on",
    "typing_on": "typing_on",
    "photo": "sending_photo",
    "image": "sending_photo",
    "video": "sending_video",
    "audio": "sending_audio",
    "file": "sending_file",
    "document": "sending_file",
}

#: Расширение файла → тип вложения платформы.
MEDIA_TYPES: dict[str, str] = {
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".gif": "image",
    ".tiff": "image",
    ".bmp": "image",
    ".heic": "image",
    ".mp4": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
}

#: Тип вложения платформы → тип сообщения события.
ATTACHMENT_TYPES: dict[str, MessageType] = {
    "image": MessageType.PHOTO,
    "video": MessageType.VIDEO,
    "audio": MessageType.AUDIO,
    "file": MessageType.DOCUMENT,
    "sticker": MessageType.STICKER,
}

#: Префикс получателя-пользователя (MAX различает чат и пользователя).
USER_PREFIX = "user:"


def error_category(status: int) -> ErrorCategory:
    """Категория ошибки контракта по коду ответа платформы."""
    if status == 401:
        return ErrorCategory.AUTH
    if status == 429:
        return ErrorCategory.RATE_LIMIT
    if status >= 500:
        return ErrorCategory.TRANSIENT
    if 400 <= status < 500:
        return ErrorCategory.INVALID
    return ErrorCategory.UNKNOWN


def upload_type_for(path: str | Path) -> str:
    """Тип вложения платформы по расширению файла."""
    return MEDIA_TYPES.get(Path(path).suffix.lower(), "file")


def recipient_params(chat_id: str) -> dict[str, Any]:
    """Параметры адресации сообщения.

    Значение ``user:<id>`` уходит как ``user_id``, любое другое — как
    ``chat_id`` (именно его платформа присылает в событии).
    """
    value = str(chat_id or "").strip()
    if value.lower().startswith(USER_PREFIX):
        return {"user_id": _as_int(value[len(USER_PREFIX) :])}
    return {"chat_id": _as_int(value)}


def message_mid(message: Any) -> Optional[str]:
    """Идентификатор сообщения (строка) из объекта ``Message``."""
    if not isinstance(message, dict):
        return None
    body = message.get("body")
    if isinstance(body, dict) and body.get("mid") is not None:
        return str(body["mid"])
    return None


def _as_int(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _detail(response: httpx.Response) -> str:
    body = _safe_json(response)
    return str(body.get("message") or body.get("code") or f"HTTP {response.status_code}")


def _extract_token(body: dict[str, Any]) -> Optional[str]:
    """Токен вложения: платформа отдаёт его в разных местах для разных типов."""
    direct = body.get("token")
    if isinstance(direct, str) and direct:
        return direct
    photos = body.get("photos")
    if isinstance(photos, dict):
        ids = photos.get("photoIds")
        if isinstance(ids, dict):
            nested = ids.get("token")
            if isinstance(nested, str) and nested:
                return nested
    return None


def _display_name(user: Any) -> str:
    if not isinstance(user, dict):
        return ""
    parts = [user.get("first_name"), user.get("last_name")]
    name = " ".join(str(part) for part in parts if part)
    return name or str(user.get("username") or "")


class MaxAdapter(PlatformAdapter):
    """Адаптер мессенджера MAX (Bot API, длинный опрос)."""

    platform = "max"
    max_text_length = MAX_TEXT_LENGTH

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if not token:
            raise ValueError("не задан токен бота MAX")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None
        #: Сведения о боте после подключения.
        self.bot: dict[str, Any] = {}
        #: Указатель продолжения длинного опроса.
        self.marker: Optional[int] = None

    # ── HTTP ──────────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.token}

    async def _call(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> tuple[int, dict[str, Any]]:
        """Вызвать метод платформы. Сетевые ошибки пробрасываются наружу."""
        response = await self._http().request(
            method, self._url(path), params=params, json=json, headers=self._headers
        )
        return response.status_code, _safe_json(response)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
    ) -> SendResult:
        """Вызвать метод и вернуть результат контракта (без исключений)."""
        try:
            response = await self._http().request(
                method, self._url(path), params=params, json=json, headers=self._headers
            )
        except httpx.HTTPError as exc:
            return SendResult.failure(ErrorCategory.NETWORK, detail=str(exc))
        return self._to_result(response)

    @staticmethod
    def _to_result(response: httpx.Response) -> SendResult:
        if response.status_code != 200:
            return SendResult.failure(
                error_category(response.status_code), detail=_detail(response)
            )
        body = _safe_json(response)
        if body.get("success") is False:
            return SendResult.failure(
                ErrorCategory.UNKNOWN, detail=str(body.get("message") or "")
            )
        return SendResult.success(message_mid(body.get("message")))

    # ── контракт ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Проверить токен (``GET /me``)."""
        try:
            status, body = await self._call("GET", "me")
        except httpx.HTTPError as exc:
            raise SendError(f"MAX: подключение не удалось (сеть): {exc}") from exc

        if status != 200:
            category = error_category(status).value
            detail = body.get("message") or f"HTTP {status}"
            raise SendError(f"MAX: подключение не удалось ({category}): {detail}")

        self.bot = body

    async def disconnect(self) -> None:
        """Закрыть HTTP-клиент, если адаптер его создал."""
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to: Optional[str] = None,
    ) -> SendResult:
        """Отправить текст, разбив его по лимиту платформы."""
        parts = split_text(text, self.max_text_length)
        if not parts:
            return SendResult.failure(ErrorCategory.INVALID, detail="пустой текст")

        params = recipient_params(chat_id)
        last_id: Optional[str] = None
        for index, part in enumerate(parts):
            payload: dict[str, Any] = {"text": part}
            if reply_to and index == 0:
                payload["link"] = {"type": "reply", "mid": str(reply_to)}
            result = await self._send("POST", "messages", params=params, json=payload)
            if not result.ok:
                return result
            last_id = result.message_id or last_id
        return SendResult.success(last_id)

    async def set_typing(self, chat_id: str, *, action: str = "typing") -> None:
        """Показать действие бота (только групповые чаты; сбой не поднимается)."""
        value = str(chat_id or "").strip()
        if value.lower().startswith(USER_PREFIX):
            log.debug("MAX: действие %s неприменимо к диалогу", action)
            return
        sender_action = SENDER_ACTIONS.get(str(action or "typing").lower(), "typing_on")
        await self._send(
            "POST", f"chats/{value}/actions", json={"action": sender_action}
        )

    async def chat_info(self, chat_id: str) -> ChatInfo:
        """Информация о чате; при сбое — минимальные сведения."""
        value = str(chat_id or "").strip()
        if value.lower().startswith(USER_PREFIX):
            return ChatInfo(chat_id=value[len(USER_PREFIX) :], kind="dm")

        try:
            status, body = await self._call("GET", f"chats/{value}")
        except httpx.HTTPError as exc:
            log.warning("MAX getChat: %s", exc)
            return ChatInfo(chat_id=value)

        if status != 200:
            log.warning("MAX getChat: %s", body.get("message") or status)
            return ChatInfo(chat_id=value)

        count = body.get("participants_count")
        return ChatInfo(
            chat_id=str(body.get("chat_id", value)),
            title=body.get("title"),
            kind=CHAT_KINDS.get(str(body.get("type") or ""), "dm"),
            member_count=count if isinstance(count, int) else None,
        )

    async def send_media(
        self,
        chat_id: str,
        path: str,
        *,
        caption: Optional[str] = None,
    ) -> SendResult:
        """Отправить файл: ссылка для загрузки → загрузка → вложение."""
        file_path = Path(path)
        if not file_path.is_file():
            return SendResult.failure(
                ErrorCategory.INVALID, detail=f"файл не найден: {path}"
            )

        media_type = upload_type_for(file_path)
        try:
            status, body = await self._call("POST", "uploads", params={"type": media_type})
        except httpx.HTTPError as exc:
            return SendResult.failure(ErrorCategory.NETWORK, detail=str(exc))

        upload_url = body.get("url")
        if status != 200 or not isinstance(upload_url, str) or not upload_url:
            return SendResult.failure(
                error_category(status),
                detail=str(body.get("message") or f"HTTP {status}"),
            )

        token = _extract_token(body)
        try:
            with open(file_path, "rb") as handle:
                upload = await self._http().post(
                    upload_url,
                    headers={"Content-Type": "multipart/form-data"},
                    files={"data": (file_path.name, handle)},
                )
        except httpx.HTTPError as exc:
            return SendResult.failure(ErrorCategory.NETWORK, detail=str(exc))
        except OSError as exc:
            return SendResult.failure(ErrorCategory.INVALID, detail=str(exc))

        if upload.status_code != 200:
            return SendResult.failure(
                error_category(upload.status_code), detail=_detail(upload)
            )

        token = token or _extract_token(_safe_json(upload))
        if not token:
            return SendResult.failure(
                ErrorCategory.UNKNOWN, detail="платформа не вернула токен вложения"
            )

        attachment: dict[str, Any] = {
            "type": media_type,
            "payload": {"token": str(token)},
        }
        if caption:
            attachment["text"] = caption
        return await self._send(
            "POST",
            "messages",
            params=recipient_params(chat_id),
            json={"attachments": [attachment]},
        )

    # ── входящие ──────────────────────────────────────────────────

    async def get_updates(
        self,
        *,
        timeout: int = 25,
        limit: int = 100,
        types: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        """Забрать обновления длинным опросом (указатель хранит адаптер)."""
        params: dict[str, Any] = {"timeout": int(timeout), "limit": int(limit)}
        if self.marker is not None:
            params["marker"] = int(self.marker)
        if types:
            params["types"] = ",".join(str(item) for item in types)

        try:
            status, body = await self._call("GET", "updates", params=params)
        except httpx.HTTPError as exc:
            log.warning("MAX getUpdates: %s", exc)
            return []

        if status != 200:
            log.warning("MAX getUpdates: %s", body.get("message") or status)
            return []

        marker = body.get("marker")
        if isinstance(marker, int):
            self.marker = marker

        updates = body.get("updates")
        return [item for item in (updates or []) if isinstance(item, dict)]

    def normalize(self, update: dict[str, Any]) -> Optional[InboundEvent]:
        """Привести событие платформы к событию гейтвея."""
        if not isinstance(update, dict):
            return None
        update_type = str(update.get("update_type") or "")
        if update_type == "message_created":
            message = update.get("message")
            if not isinstance(message, dict):
                return None
            return self._normalize_message(update, message)
        if update_type == "message_callback":
            return self._normalize_callback(update)
        return None

    def _normalize_message(
        self, update: dict[str, Any], message: dict[str, Any]
    ) -> Optional[InboundEvent]:
        recipient = message.get("recipient")
        recipient = recipient if isinstance(recipient, dict) else {}

        chat_id = recipient.get("chat_id") or update.get("chat_id")
        if chat_id is None:
            return None
        chat_type = str(
            recipient.get("chat_type")
            or ("channel" if update.get("is_channel") else "dialog")
        )

        sender = message.get("sender")
        if not isinstance(sender, dict):
            sender = update.get("user") if isinstance(update.get("user"), dict) else {}

        author = Author(
            user_id=str(sender.get("user_id") or recipient.get("user_id") or chat_id),
            name=_display_name(sender) or None,
        )
        source = Source(
            platform=self.platform,
            chat_type=CHAT_KINDS.get(chat_type, "dm"),
            chat_id=str(chat_id),
            thread_id=None,
        )

        body = message.get("body")
        body = body if isinstance(body, dict) else {}
        message_type, attachments = self._content(body.get("attachments"))

        return InboundEvent(
            text=str(body.get("text") or ""),
            author=author,
            source=source,
            message_type=message_type,
            attachments=attachments,
            reply_to=self._reply_to(message.get("link")),
        )

    def _normalize_callback(self, update: dict[str, Any]) -> Optional[InboundEvent]:
        callback = update.get("callback")
        if not isinstance(callback, dict):
            return None

        message = update.get("message") if isinstance(update.get("message"), dict) else {}
        recipient = message.get("recipient") if isinstance(message.get("recipient"), dict) else {}
        chat_id = update.get("chat_id") or recipient.get("chat_id")
        if chat_id is None:
            return None

        user = callback.get("user") if isinstance(callback.get("user"), dict) else {}
        return InboundEvent(
            text=str(callback.get("payload") or ""),
            author=Author(
                user_id=str(user.get("user_id") or chat_id),
                name=_display_name(user) or None,
            ),
            source=Source(
                platform=self.platform,
                chat_type=CHAT_KINDS.get(str(recipient.get("chat_type") or "dialog"), "dm"),
                chat_id=str(chat_id),
                thread_id=None,
            ),
            message_type=MessageType.TEXT,
        )

    @staticmethod
    def _content(attachments: Any) -> tuple[MessageType, list[str]]:
        if not isinstance(attachments, list):
            return MessageType.TEXT, []

        message_type = MessageType.TEXT
        found: list[str] = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            mapped = ATTACHMENT_TYPES.get(str(item.get("type") or ""))
            if mapped is None:
                continue
            if message_type is MessageType.TEXT:
                message_type = mapped
            payload = item.get("payload")
            if isinstance(payload, dict):
                token = payload.get("token") or payload.get("url")
                if token:
                    found.append(str(token))
        return message_type, found

    @staticmethod
    def _reply_to(link: Any) -> Optional[str]:
        if not isinstance(link, dict):
            return None
        if str(link.get("type") or "") != "reply":
            return None
        message = link.get("message")
        if isinstance(message, dict) and message.get("mid") is not None:
            return str(message["mid"])
        return None
