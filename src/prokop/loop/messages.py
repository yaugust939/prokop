"""Модель сообщений и канонизация истории.

Формат сообщений — OpenAI-совместимый: ``role`` (system/user/assistant/tool),
``content``, ``tool_calls``, ``tool_call_id``. Рассуждения хранятся отдельно
и никогда не сериализуются в ``content``. Перед каждым вызовом модели
сообщения структурно клонируются и канонизируются: чинится чередование
ролей, отбрасываются «только-думающие» ходы, санитизируются суррогаты.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

#: Допустимые роли.
ROLES = ("system", "user", "assistant", "tool")

#: Служебные поля, вычищаемые при клонировании.
SERVICE_FIELDS = ("api_content", "display_kind", "_row_id", "finish_reason", "codex")


@dataclass
class Message:
    """Одно сообщение истории."""

    role: str
    content: Optional[str] = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    #: Рассуждения — только отображаемое состояние, никогда не в контенте.
    reasoning: Optional[str] = None

    def to_api(self) -> dict[str, Any]:
        """Сообщение в формате для API (без служебных полей)."""
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        else:
            payload["content"] = ""
        if self.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": tc.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": tc.get("name") or "",
                        "arguments": tc.get("arguments")
                        if isinstance(tc.get("arguments"), str)
                        else json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                    },
                }
                for tc in self.tool_calls
            ]
        if self.role == "tool":
            payload["tool_call_id"] = self.tool_call_id or ""
            if self.tool_name:
                payload["name"] = self.tool_name
        return payload

    def clone(self) -> "Message":
        """Структурная копия сообщения."""
        return Message(
            role=self.role,
            content=self.content,
            tool_calls=copy.deepcopy(self.tool_calls),
            tool_name=self.tool_name,
            tool_call_id=self.tool_call_id,
            reasoning=self.reasoning,
        )


def sanitize_text(text: Optional[str]) -> Optional[str]:
    """Санитизировать текст: убрать несуррогатные артефакты кодировки."""
    if text is None:
        return None
    return text.encode("utf-8", errors="ignore").decode("utf-8")


def fix_role_alternation(messages: list[Message]) -> list[Message]:
    """Починить чередование ролей.

    Правило: два сообщения одной роли подряд не допускаются; соседние
    ``user``-сообщения объединяются, лишние ``tool``-сообщения без пары
    отбрасываются, синтетические ``user`` внутрь цикла не вставляются.
    """
    fixed: list[Message] = []
    for message in messages:
        if fixed and fixed[-1].role == message.role == "user":
            previous = fixed[-1]
            left = previous.content or ""
            right = message.content or ""
            previous.content = f"{left}\n{right}" if left and right else (left or right)
            continue
        if fixed and fixed[-1].role == message.role == "assistant" and not message.tool_calls:
            previous = fixed[-1]
            left = previous.content or ""
            right = message.content or ""
            previous.content = f"{left}\n{right}" if left and right else (left or right)
            continue
        fixed.append(message)
    return fixed


def drop_thinking_only(messages: list[Message]) -> list[Message]:
    """Отбросить ассистентские ходы, в которых только рассуждения."""
    result: list[Message] = []
    for message in messages:
        if (
            message.role == "assistant"
            and not message.content
            and not message.tool_calls
            and message.reasoning
        ):
            continue
        result.append(message)
    return result


def clone_messages(messages: list[Message]) -> list[Message]:
    """Структурно клонировать и канонизировать историю перед вызовом.

    Порядок: клонирование → санитизация → удаление «только-думающих» →
    починка чередования ролей. Исходный список не изменяется.
    """
    clones = [m.clone() for m in messages]
    for clone in clones:
        clone.content = sanitize_text(clone.content)
    clones = drop_thinking_only(clones)
    clones = fix_role_alternation(clones)
    return clones


def to_api_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """История в списке словарей для API."""
    return [m.to_api() for m in clone_messages(messages)]
