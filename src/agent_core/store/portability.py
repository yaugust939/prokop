"""Портабельность состояния сессий: экспорт и импорт в JSONL.

Экспорт — одна сессия или все сессии. Импорт — с валидацией и лимитами
(число сессий, сообщений на сессию, размер байт), пропуском уже
существующих идентификаторов.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable

from agent_core.store.sessions import SessionStore

#: Ограничения импорта.
MAX_IMPORT_SESSIONS = 1000
MAX_MESSAGES_PER_SESSION = 10000
MAX_IMPORT_BYTES = 256 * 1024 * 1024


@dataclass
class ImportResult:
    imported: int = 0
    skipped_existing: int = 0
    rejected: int = 0
    errors: list[str] | None = None


def export_session(store: SessionStore, session_id: str, fh: IO[str]) -> None:
    """Экспортировать одну сессию как объект в JSONL."""
    session = store.get_session(session_id)
    if not session:
        raise KeyError(f"Сессия не найдена: {session_id}")
    messages = store.get_messages(session_id, active_only=False)
    fh.write(json.dumps({"session": session, "messages": messages}, ensure_ascii=False) + "\n")


def export_sessions(store: SessionStore, fh: IO[str], include_archived: bool = True) -> int:
    """Экспортировать все сессии; возвращает число записанных строк."""
    count = 0
    for session in store.list_sessions(include_archived=include_archived):
        export_session(store, session["id"], fh)
        count += 1
    return count


def _valid_session_record(record: dict) -> bool:
    session = record.get("session")
    messages = record.get("messages")
    return isinstance(session, dict) and isinstance(messages, list) and "id" in session


def import_sessions(
    store: SessionStore,
    fh: Iterable[str],
    *,
    max_sessions: int = MAX_IMPORT_SESSIONS,
    max_messages_per_session: int = MAX_MESSAGES_PER_SESSION,
    max_bytes: int = MAX_IMPORT_BYTES,
) -> ImportResult:
    """Импортировать сессии из строк JSONL.

    Существующие идентификаторы пропускаются, записи сверх лимитов
    отклоняются.
    """
    result = ImportResult(errors=[])
    read_bytes = 0
    for line in fh:
        read_bytes += len(line.encode("utf-8"))
        if read_bytes > max_bytes:
            result.errors.append("Превышен лимит размера импорта")
            break
        line = line.strip()
        if not line:
            continue
        if result.imported + result.skipped_existing >= max_sessions:
            result.rejected += 1
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            result.rejected += 1
            result.errors.append(f"Неверный JSON: {exc}")
            continue
        if not _valid_session_record(record):
            result.rejected += 1
            continue
        session = record["session"]
        messages = record["messages"]
        if len(messages) > max_messages_per_session:
            result.rejected += 1
            continue
        if store.get_session(session["id"]):
            result.skipped_existing += 1
            continue
        store.create_session(
            session_id=session["id"],
            source=session.get("source") or "import",
            user_id=session.get("user_id"),
            model=session.get("model"),
        )
        for message in messages:
            store.add_message(
                session["id"],
                message.get("role") or "user",
                message.get("content"),
                tool_name=message.get("tool_name"),
                tool_call_id=message.get("tool_call_id"),
                reasoning=message.get("reasoning"),
                token_count=message.get("token_count"),
            )
        result.imported += 1
    return result
