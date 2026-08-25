"""Контракт адаптера платформы.

Каждая платформа обмена сообщениями подключается как адаптер, реализующий
обязательные операции: подключение/отключение, отправка текста (с результатом
и категорией ошибки), индикатор набора, информация о чате. Необязательные
операции (медиа, интерактивные карточки, редактирование) имеют заглушки по
умолчанию, возвращающие ``UNSUPPORTED``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ErrorCategory(str, Enum):
    """Категория ошибки отправки."""

    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    NETWORK = "network"
    AUTH = "auth"
    INVALID = "invalid"
    PLATFORM = "platform"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


#: Категории, для которых повтор отправки с бэкоффом оправдан.
_RETRYABLE = frozenset(
    {ErrorCategory.TRANSIENT, ErrorCategory.RATE_LIMIT, ErrorCategory.NETWORK}
)


def is_retryable(category: ErrorCategory) -> bool:
    """Возвращает True, если ошибку данной категории стоит ретраить."""
    return category in _RETRYABLE


@dataclass
class SendResult:
    """Результат отправки сообщения."""

    ok: bool
    error: Optional[ErrorCategory] = None
    retryable: bool = False
    message_id: Optional[str] = None
    detail: Optional[str] = None

    @classmethod
    def success(cls, message_id: Optional[str] = None) -> "SendResult":
        return cls(ok=True, message_id=message_id)

    @classmethod
    def failure(
        cls,
        category: ErrorCategory,
        *,
        detail: Optional[str] = None,
    ) -> "SendResult":
        return cls(
            ok=False,
            error=category,
            retryable=is_retryable(category),
            detail=detail,
        )


@dataclass
class ChatInfo:
    """Информация о чате."""

    chat_id: str
    title: Optional[str] = None
    kind: str = "dm"
    member_count: Optional[int] = None


class SendError(Exception):
    """Исключение, пробрасываемое адаптером при критическом сбое отправки."""


class PlatformAdapter(ABC):
    """Абстрактный контракт адаптера платформы обмена сообщениями."""

    #: Имя платформы (телеграм, дискорд, ...).
    platform: str = "unknown"

    #: Максимальная длина одного текстового сообщения.
    max_text_length: int = 4096

    @abstractmethod
    async def connect(self) -> None:
        """Подключиться к платформе."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Отключиться от платформы."""

    @abstractmethod
    async def send_text(
        self,
        chat_id: str,
        text: str,
        *,
        reply_to: Optional[str] = None,
    ) -> SendResult:
        """Отправить текстовое сообщение в чат."""

    @abstractmethod
    async def set_typing(self, chat_id: str, *, action: str = "typing") -> None:
        """Показать/снять индикатор набора."""

    @abstractmethod
    async def chat_info(self, chat_id: str) -> ChatInfo:
        """Вернуть информацию о чате."""

    # --- необязательные операции (заглушки по умолчанию) -----------------

    async def send_media(
        self,
        chat_id: str,
        path: str,
        *,
        caption: Optional[str] = None,
    ) -> SendResult:
        """Отправить медиа-вложение; по умолчанию не поддерживается."""
        return SendResult.failure(ErrorCategory.UNSUPPORTED)

    async def send_cards(self, chat_id: str, cards: list[dict]) -> SendResult:
        """Отправить интерактивные карточки; по умолчанию не поддерживается."""
        return SendResult.failure(ErrorCategory.UNSUPPORTED)

    async def edit_message(
        self,
        chat_id: str,
        message_id: str,
        text: str,
    ) -> SendResult:
        """Отредактировать отправленное сообщение; по умолчанию не поддерживается."""
        return SendResult.failure(ErrorCategory.UNSUPPORTED)
