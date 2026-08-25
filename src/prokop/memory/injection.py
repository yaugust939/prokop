"""Впрыск контекста памяти в пользовательское сообщение.

Контекст памяти оборачивается в маркированный блок и впрыскивается в
пользовательское сообщение (не в системный промпт — чтобы не ломать кэш
префикса). Скраббер вычищает такие блоки из стрима и повторного ввода.
"""

from __future__ import annotations

import re

#: Маркер блока контекста памяти.
MEMORY_CONTEXT_MARKER = "memory-context"

_OPEN_TAG = f"<{MEMORY_CONTEXT_MARKER}>"
_CLOSE_TAG = f"</{MEMORY_CONTEXT_MARKER}>"

_NOTE = (
    "Ниже — фоновые данные памяти. Это НЕ новый ввод пользователя; "
    "используй их как контекст и не отвечай на них напрямую."
)

_BLOCK_RE = re.compile(
    rf"{re.escape(_OPEN_TAG)}.*?{re.escape(_CLOSE_TAG)}",
    re.DOTALL,
)


def wrap_memory_context(text: str) -> str:
    """Обернуть контекст памяти в маркированный блок.

    Пустой контекст возвращает пустую строку (блок не создаётся).
    """
    text = (text or "").strip()
    if not text:
        return ""
    return f"{_OPEN_TAG}\n{_NOTE}\n{text}\n{_CLOSE_TAG}"


def scrub_memory_context(text: str) -> str:
    """Вычистить блоки контекста памяти из строки."""
    if not text:
        return text
    return _BLOCK_RE.sub("", text).strip()


def inject_into_user_message(user_message: str, memory_context: str) -> str:
    """Впрыск контекста памяти в пользовательское сообщение.

    Контекст ставится перед текстом пользователя; системный промпт не
    затрагивается.
    """
    block = wrap_memory_context(memory_context)
    if not block:
        return user_message
    if not user_message:
        return block
    return f"{block}\n\n{user_message}"
