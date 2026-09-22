"""Адаптер платформы Telegram поверх HTTP Bot API.

Реализация контракта :class:`~prokop.gateway.adapters.PlatformAdapter` без
новых зависимостей: HTTP через уже используемый `httpx`. Клиент можно
инжектировать — тесты подменяют транспорт и не выходят в сеть.

Входящие сообщения приводятся к нормализованному событию гейтвея
(:meth:`TelegramAdapter.normalize`), обновления забираются длинным опросом
(:meth:`TelegramAdapter.get_updates`). Цикл опроса намеренно не входит в
адаптер: политику запуска определяет вызывающий код.
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
)
from prokop.gateway.events import Author, InboundEvent, MessageType, Source
from prokop.logging_setup import get_logger

log = get_logger("gateway.telegram")

#: Базовый адрес Bot API.
DEFAULT_BASE_URL = "https://api.telegram.org"

#: Таймаут HTTP-клиента по умолчанию, секунд (больше длинного опроса).
DEFAULT_TIMEOUT = 60.0

#: Виды чатов платформы → вид чата события.
CHAT_KINDS: dict[str, str] = {
    "private": "dm",
    "group": "group",
    "supergroup": "group",
    "channel": "channel",
}

#: Ключи сообщения → тип вложения (порядок проверки важен).
MEDIA_KEYS: tuple[tuple[str, MessageType], ...] = (
    ("photo", MessageType.PHOTO),
    ("video", MessageType.VIDEO),
    ("audio", MessageType.AUDIO),
    ("voice", MessageType.AUDIO),
    ("document", MessageType.DOCUMENT),
    ("sticker", MessageType.STICKER),
)


def error_category(status: int) -> ErrorCategory:
    """Категория ошибки контракта по коду ответа платформы."""
    if status in (401, 403):
        return ErrorCategory.AUTH
    if status == 429:
        return ErrorCategory.RATE_LIMIT
    if status >= 500:
        return ErrorCategory.TRANSIENT
    if 400 <= status < 500:
        return ErrorCategory.INVALID
    return ErrorCategory.UNKNOWN


def split_text(text: str, limit: int) -> list[str]:
    """Разбить текст на части не длиннее лимита.

    По возможности режем по границе строки, затем по пробелу; если границы нет
    — жёстко по лимиту. Пустой текст даёт пустой список.
    """
    text = text or ""
    if not text:
        return []
    if limit <= 0 or len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        part = remaining[:cut].strip()
        if not part:
            cut = limit
            part = remaining[:cut]
        parts.append(part)
        remaining = remaining[cut:].lstrip("\n")
    if remaining.strip():
        parts.append(remaining.strip())
    return parts


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _detail(response: httpx.Response) -> str:
    body = _safe_json(response)
    description = body.get("description")
    return str(description) if description else f"HTTP {response.status_code}"


def _display_name(sender: dict[str, Any]) -> str:
    parts = [sender.get("first_name"), sender.get("last_name")]
    name = " ".join(str(part) for part in parts if part)
    return name or str(sender.get("username") or "")


class TelegramAdapter(PlatformAdapter):
    """Адаптер Telegram (Bot API, длинный опрос)."""

    platform = "telegram"
    max_text_length = 4096

    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        if not token:
            raise ValueError("не задан токен бота Telegram")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None
        #: Сведения о боте после подключения.
        self.bot: dict[str, Any] = {}

    # ── HTTP ──────────────────────────────────────────────────────

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _url(self, method: str) -> str:
        return f"{self.base_url}/bot{self.token}/{method}"

    async def _call(
        self, method: str, payload: Optional[dict[str, Any]] = None
    ) -> tuple[int, dict[str, Any]]:
        """Вызвать метод Bot API. Сетевые ошибки пробрасываются наружу."""
        response = await self._http().post(self._url(method), json=payload or {})
        return response.status_code, _safe_json(response)

    async def _post(self, method: str, payload: dict[str, Any]) -> SendResult:
        """Вызвать метод и вернуть результат контракта (без исключений)."""
        try:
            response = await self._http().post(self._url(method), json=payload)
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
        if body.get("ok") is False:
            code = body.get("error_code")
            category = error_category(int(code)) if isinstance(code, int) else ErrorCategory.UNKNOWN
            return SendResult.failure(category, detail=str(body.get("description") or ""))
        result = body.get("result")
        message_id = None
        if isinstance(result, dict) and result.get("message_id") is not None:
            message_id = str(result["message_id"])
        return SendResult.success(message_id)

    # ── контракт ──────────────────────────────────────────────────

    async def connect(self) -> None:
        """Проверить учётные данные (``getMe``)."""
        try:
            status, body = await self._call("getMe")
        except httpx.HTTPError as exc:
            raise SendError(f"Telegram: подключение не удалось (сеть): {exc}") from exc

        if status != 200 or not body.get("ok"):
            category = error_category(status).value
            detail = body.get("description") or f"HTTP {status}"
            raise SendError(f"Telegram: подключение не удалось ({category}): {detail}")

        result = body.get("result")
        self.bot = result if isinstance(result, dict) else {}

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

        last_id: Optional[str] = None
        for index, part in enumerate(parts):
            payload: dict[str, Any] = {"chat_id": chat_id, "text": part}
            if reply_to and index == 0:
                payload["reply_to_message_id"] = _as_int(reply_to)
            result = await self._post("sendMessage", payload)
            if not result.ok:
                return result
            last_id = result.message_id or last_id
        return SendResult.success(last_id)

    async def set_typing(self, chat_id: str, *, action: str = "typing") -> None:
        """Показать индикатор набора (сбой не поднимается наружу)."""
        await self._post("sendChatAction", {"chat_id": chat_id, "action": action})

    async def chat_info(self, chat_id: str) -> ChatInfo:
        """Информация о чате; при сбое — минимальные сведения."""
        try:
            status, body = await self._call("getChat", {"chat_id": chat_id})
        except httpx.HTTPError as exc:
            log.warning("getChat: %s", exc)
            return ChatInfo(chat_id=str(chat_id))

        if status != 200 or not body.get("ok"):
            log.warning("getChat: %s", body.get("description") or status)
            return ChatInfo(chat_id=str(chat_id))

        data = body.get("result")
        if not isinstance(data, dict):
            return ChatInfo(chat_id=str(chat_id))
        return ChatInfo(
            chat_id=str(data.get("id", chat_id)),
            title=data.get("title") or data.get("username") or data.get("first_name"),
            kind=CHAT_KINDS.get(str(data.get("type") or ""), "dm"),
        )

    async def send_media(
        self,
        chat_id: str,
        path: str,
        *,
        caption: Optional[str] = None,
    ) -> SendResult:
        """Отправить файл как документ."""
        file_path = Path(path)
        if not file_path.is_file():
            return SendResult.failure(
                ErrorCategory.INVALID, detail=f"файл не найден: {path}"
            )

        data: dict[str, Any] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption
        try:
            with open(file_path, "rb") as handle:
                response = await self._http().post(
                    self._url("sendDocument"),
                    data=data,
                    files={"document": (file_path.name, handle)},
                )
        except httpx.HTTPError as exc:
            return SendResult.failure(ErrorCategory.NETWORK, detail=str(exc))
        except OSError as exc:
            return SendResult.failure(ErrorCategory.INVALID, detail=str(exc))
        return self._to_result(response)

    # ── входящие ──────────────────────────────────────────────────

    async def get_updates(
        self,
        offset: Optional[int] = None,
        *,
        timeout: int = 25,
    ) -> list[dict[str, Any]]:
        """Забрать обновления длинным опросом."""
        payload: dict[str, Any] = {"timeout": int(timeout)}
        if offset is not None:
            payload["offset"] = int(offset)
        try:
            status, body = await self._call("getUpdates", payload)
        except httpx.HTTPError as exc:
            log.warning("getUpdates: %s", exc)
            return []

        if status != 200 or not body.get("ok"):
            log.warning("getUpdates: %s", body.get("description") or status)
            return []

        updates = body.get("result")
        return [item for item in (updates or []) if isinstance(item, dict)]

    def normalize(self, update: dict[str, Any]) -> Optional[InboundEvent]:
        """Привести сырое обновление к событию гейтвея."""
        if not isinstance(update, dict):
            return None
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
        )
        if not isinstance(message, dict):
            return None

        chat = message.get("chat")
        if not isinstance(chat, dict) or chat.get("id") is None:
            return None

        sender = message.get("from")
        sender = sender if isinstance(sender, dict) else {}
        author = Author(
            user_id=str(sender.get("id") or chat.get("id")),
            name=_display_name(sender) or None,
        )

        thread_id = message.get("message_thread_id")
        source = Source(
            platform=self.platform,
            chat_type=CHAT_KINDS.get(str(chat.get("type") or ""), "dm"),
            chat_id=str(chat.get("id")),
            thread_id=str(thread_id) if thread_id is not None else None,
        )

        message_type, attachments = self._content(message)
        reply = message.get("reply_to_message")
        reply_to = (
            str(reply.get("message_id"))
            if isinstance(reply, dict) and reply.get("message_id") is not None
            else None
        )

        return InboundEvent(
            text=str(message.get("text") or message.get("caption") or ""),
            author=author,
            source=source,
            message_type=message_type,
            attachments=attachments,
            reply_to=reply_to,
        )

    @staticmethod
    def _content(message: dict[str, Any]) -> tuple[MessageType, list[str]]:
        for key, kind in MEDIA_KEYS:
            value = message.get(key)
            if not value:
                continue
            file_id: Optional[str] = None
            if isinstance(value, list) and value:
                last = value[-1]
                if isinstance(last, dict):
                    file_id = last.get("file_id")
            elif isinstance(value, dict):
                file_id = value.get("file_id")
            return kind, ([str(file_id)] if file_id else [])
        if message.get("text"):
            return MessageType.TEXT, []
        return MessageType.UNKNOWN, []


def _as_int(value: Any) -> Any:
    """Привести идентификатор к числу, если это возможно (платформа ждёт число)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return value
