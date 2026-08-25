"""Детерминированный ключ сессии.

Ключ строится из дескриптора источника события и обязан быть стабильным:
одинаковые источники дают одинаковый ключ. Правила:

- личное сообщение (``dm``) — ``платформа + "dm" + ид чата``;
- группа/канал — ``платформа + тип + ид чата`` (плюс ид треда, если задан).
"""

from __future__ import annotations

#: Типы чатов, которые различает ключ.
DM = "dm"
GROUP = "group"
CHANNEL = "channel"

#: Разделитель частей ключа.
_SEPARATOR = ":"


def session_key(
    platform: str,
    chat_type: str,
    chat_id: str,
    thread_id: str | None = None,
) -> str:
    """Построить детерминированный ключ сессии.

    Для личного сообщения тип нормализуется к ``dm``, а ид треда
    игнорируется (у ЛС нет тредов). Для группы/канала тред добавляется
    отдельной частью.
    """
    kind = DM if chat_type == DM else str(chat_type)
    parts = [str(platform), kind, str(chat_id)]
    if thread_id and kind != DM:
        parts.append(str(thread_id))
    return _SEPARATOR.join(parts)
