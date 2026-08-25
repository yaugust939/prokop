"""Нормализованное входящее событие.

Все адаптеры приводят сырое сообщение платформы к единому представлению:
текст, тип сообщения, автор, источник (дескриптор происхождения),
вложения (локальные пути), контекст ответа, отметка времени.

Командность определяется по ведущему ``/``; отдельно выделяются управляющие
команды (стоп/новый/сброс), которые гейтвей обрабатывает без агентного хода.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from prokop.gateway.keys import session_key
from prokop.timeutil import utcnow

#: Имена управляющих команд (канонические).
CONTROL_STOP = "stop"
CONTROL_NEW = "new"
CONTROL_RESET = "reset"

#: Алиасы (с синонимами на русском) → каноническое имя команды.
_CONTROL_ALIASES = {
    "stop": CONTROL_STOP,
    "стоп": CONTROL_STOP,
    "halt": CONTROL_STOP,
    "new": CONTROL_NEW,
    "новый": CONTROL_NEW,
    "reset": CONTROL_RESET,
    "сброс": CONTROL_RESET,
    "clear": CONTROL_RESET,
}


class MessageType(str, Enum):
    """Тип входящего сообщения."""

    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    STICKER = "sticker"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Author:
    """Автор сообщения."""

    user_id: str
    name: str | None = None


@dataclass(frozen=True)
class Source:
    """Дескриптор происхождения события (платформа + чат + опционально тред)."""

    platform: str
    chat_type: str
    chat_id: str
    thread_id: str | None = None


def parse_control_command(text: str) -> str | None:
    """Распознать управляющую команду (стоп/новый/сброс).

    Принимает формы ``/stop`` и ``стоп``; возвращает каноническое имя или
    ``None``, если текст не является управляющей командой.
    """
    token = text.strip()
    if token.startswith("/"):
        token = token[1:]
    token = token.split(None, 1)[0].lower()
    return _CONTROL_ALIASES.get(token)


@dataclass
class InboundEvent:
    """Нормализованное входящее событие."""

    text: str
    author: Author
    source: Source
    message_type: MessageType = MessageType.TEXT
    attachments: list[str] = field(default_factory=list)
    reply_to: str | None = None
    timestamp: datetime = field(default_factory=utcnow)

    @property
    def session_key(self) -> str:
        """Детерминированный ключ сессии события."""
        return session_key(
            self.source.platform,
            self.source.chat_type,
            self.source.chat_id,
            self.source.thread_id,
        )

    @property
    def is_command(self) -> bool:
        """Командность по ведущему ``/``."""
        return self.text.lstrip().startswith("/")

    @property
    def control(self) -> str | None:
        """Управляющая команда (стоп/новый/сброс) или ``None``."""
        return parse_control_command(self.text)
