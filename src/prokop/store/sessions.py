"""SQLite-хранилище сессий.

Единая база ``state.db`` в домашнем каталоге профиля: таблицы сессий,
сообщений, снапшотов системных промптов (по хэшу), учёта использования
модели и мета-ключей. Запись — в транзакции (атомарна на уровне БД);
аренда хода не даёт двум процессам писать в один разговор одновременно.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from prokop.timeutil import utcnow

DB_FILENAME = "state.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT,
    user_id TEXT,
    title TEXT,
    model TEXT,
    model_config TEXT,
    system_prompt_hash TEXT,
    parent_session_id TEXT,
    started_at TEXT,
    ended_at TEXT,
    end_reason TEXT,
    archived INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    message_count INTEGER NOT NULL DEFAULT 0,
    tool_call_count INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    tokens_cache INTEGER NOT NULL DEFAULT 0,
    last_activity TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    position INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    tool_call_id TEXT,
    reasoning TEXT,
    finish_reason TEXT,
    token_count INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    compacted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, position);

CREATE TABLE IF NOT EXISTS system_prompts (
    hash TEXT PRIMARY KEY,
    content TEXT NOT NULL,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS session_model_usage (
    session_id TEXT NOT NULL,
    model TEXT NOT NULL,
    task TEXT,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    calls INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS state_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS leases (
    session_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""


class SessionStore:
    """Хранилище сессий и сообщений."""

    def __init__(self, home: Path, db_name: str = DB_FILENAME) -> None:
        self.path = Path(home) / db_name
        Path(home).mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # --- сессии ------------------------------------------------------

    def create_session(
        self,
        *,
        source: str = "cli",
        user_id: Optional[str] = None,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        model_config: Optional[dict[str, Any]] = None,
        parent_session_id: Optional[str] = None,
    ) -> str:
        sid = session_id or uuid.uuid4().hex
        now = utcnow().isoformat()
        self._conn.execute(
            """INSERT INTO sessions
               (id, source, user_id, model, model_config, parent_session_id, started_at, last_activity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                sid,
                source,
                user_id,
                model,
                json.dumps(model_config or {}, ensure_ascii=False),
                parent_session_id,
                now,
                now,
            ),
        )
        return sid

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_sessions(self, include_archived: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM sessions"
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY last_activity DESC"
        return [dict(r) for r in self._conn.execute(query)]

    def end_session(self, session_id: str, end_reason: str = "finished") -> None:
        self._conn.execute(
            "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?",
            (utcnow().isoformat(), end_reason, session_id),
        )

    def touch(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET last_activity = ? WHERE id = ?",
            (utcnow().isoformat(), session_id),
        )

    # --- сообщения ----------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: Optional[str],
        *,
        tool_calls: Optional[list[dict[str, Any]]] = None,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        reasoning: Optional[str] = None,
        finish_reason: Optional[str] = None,
        token_count: Optional[int] = None,
    ) -> int:
        """Добавить сообщение; возвращает его позицию.

        Рассуждения сохраняются отдельно и не попадают в ``content``.
        """
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) AS p FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        position = int(row["p"]) + 1
        cur = self._conn.execute(
            """INSERT INTO messages
               (session_id, position, role, content, tool_calls, tool_name, tool_call_id,
                reasoning, finish_reason, token_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                position,
                role,
                content,
                json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                tool_name,
                tool_call_id,
                reasoning,
                finish_reason,
                token_count,
                utcnow().isoformat(),
            ),
        )
        self._conn.execute(
            "UPDATE sessions SET message_count = message_count + 1, last_activity = ? WHERE id = ?",
            (utcnow().isoformat(), session_id),
        )
        if role == "assistant" and tool_calls:
            self._conn.execute(
                "UPDATE sessions SET tool_call_count = tool_call_count + ? WHERE id = ?",
                (len(tool_calls), session_id),
            )
        return position

    def get_messages(self, session_id: str, active_only: bool = True) -> list[dict[str, Any]]:
        query = "SELECT * FROM messages WHERE session_id = ?"
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY position"
        return [dict(r) for r in self._conn.execute(query, (session_id,))]

    def mark_compacted(self, session_id: str, positions: Iterable[int]) -> None:
        positions = list(positions)
        if not positions:
            return
        self._conn.executemany(
            "UPDATE messages SET compacted = 1, active = 0 WHERE session_id = ? AND position = ?",
            [(session_id, p) for p in positions],
        )

    # --- системные промпты (по хэшу) ---------------------------------

    def save_system_prompt(self, prompt_hash: str, content: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO system_prompts (hash, content, created_at) VALUES (?, ?, ?)",
            (prompt_hash, content, utcnow().isoformat()),
        )

    def get_system_prompt(self, prompt_hash: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT content FROM system_prompts WHERE hash = ?", (prompt_hash,)
        ).fetchone()
        return row["content"] if row else None

    # --- учёт использования моделей ----------------------------------

    def record_usage(
        self,
        session_id: str,
        model: str,
        *,
        tokens_in: int = 0,
        tokens_out: int = 0,
        task: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            """INSERT INTO session_model_usage (session_id, model, task, tokens_in, tokens_out, calls)
               VALUES (?, ?, ?, ?, ?, 1)""",
            (session_id, model, task, tokens_in, tokens_out),
        )
        self._conn.execute(
            """UPDATE sessions SET tokens_in = tokens_in + ?, tokens_out = tokens_out + ?
               WHERE id = ?""",
            (tokens_in, tokens_out, session_id),
        )

    def get_usage(self, session_id: str) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM session_model_usage WHERE session_id = ?", (session_id,)
            )
        ]

    # --- мета ---------------------------------------------------------

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO state_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM state_meta WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    # --- аренда хода ----------------------------------------------------

    def acquire_lease(
        self, session_id: str, owner: str, ttl_seconds: int = 60
    ) -> bool:
        """Взять аренду на сессию; чужая живая аренда блокирует запись."""
        now = utcnow()
        row = self._conn.execute(
            "SELECT owner, expires_at FROM leases WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row and row["owner"] != owner:
            if datetime.fromisoformat(row["expires_at"]) > now:
                return False
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        self._conn.execute(
            """INSERT INTO leases (session_id, owner, expires_at) VALUES (?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET owner = excluded.owner,
               expires_at = excluded.expires_at""",
            (session_id, owner, expires),
        )
        return True

    def refresh_lease(self, session_id: str, owner: str, ttl_seconds: int = 60) -> bool:
        """Продлить аренду, если она всё ещё наша."""
        row = self._conn.execute(
            "SELECT owner FROM leases WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row or row["owner"] != owner:
            return False
        expires = (utcnow() + timedelta(seconds=ttl_seconds)).isoformat()
        self._conn.execute(
            "UPDATE leases SET expires_at = ? WHERE session_id = ? AND owner = ?",
            (expires, session_id, owner),
        )
        return True

    def release_lease(self, session_id: str, owner: str) -> None:
        """Освободить аренду (только свою)."""
        self._conn.execute(
            "DELETE FROM leases WHERE session_id = ? AND owner = ?", (session_id, owner)
        )
