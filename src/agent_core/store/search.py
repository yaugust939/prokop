"""Полнотекстовый поиск по сообщениям сессий.

Два индекса: стандартный токенизатор и триграммный (для подстрочного
поиска по любым письменностям). Запросы санитизируются от спецсимволов
FTS5. Поиск по сессиям возвращает сниппеты, якорное окно вокруг находки
и «букенды» — первое и последнее сообщения разговора.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any

#: Максимальная длина запроса.
MAX_QUERY_LENGTH = 200

#: Размер якорного окна вокруг найденного сообщения.
ANCHOR_WINDOW = 3

_FTS_SETUP = """
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    content, session_id UNINDEXED, position UNINDEXED, role UNINDEXED
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_tri USING fts5(
    content, session_id UNINDEXED, position UNINDEXED, role UNINDEXED,
    tokenize='trigram'
);
"""

_TRIGRAM_SPECIALS = re.compile(r"[*^()\[\]{}:\"\\]")


def ensure_fts(conn: sqlite3.Connection) -> None:
    """Создать индексы и перестроить их при отсутствии."""
    conn.executescript(_FTS_SETUP)
    count = conn.execute("SELECT COUNT(*) AS c FROM messages_fts").fetchone()[0]
    total = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()[0]
    if count == 0 and total > 0:
        rebuild_fts(conn)


def rebuild_fts(conn: sqlite3.Connection) -> None:
    """Полная перестройка обоих индексов."""
    conn.executescript(_FTS_SETUP)
    conn.execute("DELETE FROM messages_fts")
    conn.execute("DELETE FROM messages_fts_tri")
    conn.execute(
        """INSERT INTO messages_fts (content, session_id, position, role)
           SELECT COALESCE(content, ''), session_id, position, role FROM messages"""
    )
    conn.execute(
        """INSERT INTO messages_fts_tri (content, session_id, position, role)
           SELECT COALESCE(content, ''), session_id, position, role FROM messages"""
    )


def index_message(
    conn: sqlite3.Connection,
    session_id: str,
    position: int,
    role: str,
    content: str,
) -> None:
    """Добавить одно сообщение в оба индекса."""
    ensure_fts(conn)
    conn.execute(
        "INSERT INTO messages_fts (content, session_id, position, role) VALUES (?, ?, ?, ?)",
        (content or "", session_id, position, role),
    )
    conn.execute(
        "INSERT INTO messages_fts_tri (content, session_id, position, role) VALUES (?, ?, ?, ?)",
        (content or "", session_id, position, role),
    )


def sanitize_query(query: str) -> str:
    """Очистить запрос от спецсимволов FTS5 и ограничить длину."""
    query = (query or "").strip()[:MAX_QUERY_LENGTH]
    cleaned = _TRIGRAM_SPECIALS.sub(" ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return ""
    # Каждое слово — как фраза: защита от оставшихся операторов.
    return " ".join(f'"{word}"' for word in cleaned.split())


def _fts_query(table: str, conn: sqlite3.Connection, fts: str, limit: int) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            f"""SELECT session_id, position, role,
                       snippet({table}, 0, '<b>', '</b>', '…', 10) AS snippet
                FROM {table} WHERE {table} MATCH ? ORDER BY rank LIMIT ?""",
            (fts, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [dict(r) for r in rows]


def search_messages(conn: sqlite3.Connection, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Найти сообщения по тексту.

    Стандартный индекс пробует первым; если он не дал результата или
    запрос подстрочный/не-латинский — используется триграммный индекс.
    """
    fts = sanitize_query(query)
    if not fts:
        return []
    ensure_fts(conn)
    results = _fts_query("messages_fts", conn, fts, limit)
    if not results:
        results = _fts_query("messages_fts_tri", conn, fts, limit)
    return results


def _bookends(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    """Первое и последнее сообщения разговора."""
    first = conn.execute(
        "SELECT role, content, position FROM messages WHERE session_id = ? AND active = 1 "
        "ORDER BY position LIMIT 1",
        (session_id,),
    ).fetchone()
    last = conn.execute(
        "SELECT role, content, position FROM messages WHERE session_id = ? AND active = 1 "
        "ORDER BY position DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return {
        "first": dict(first) if first else None,
        "last": dict(last) if last else None,
    }


def search_sessions(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20,
    window: int = ANCHOR_WINDOW,
) -> list[dict[str, Any]]:
    """Поиск по сессиям: сниппет + якорное окно + букенды.

    Для каждой находки возвращается окружающее окно сообщений и первое/
    последнее сообщения разговора — так одним вызовом видно и цель, и
    развязку длинного разговора.
    """
    hits = search_messages(conn, query, limit=limit)
    results: list[dict[str, Any]] = []
    for hit in hits:
        session_id = hit["session_id"]
        position = int(hit["position"])
        rows = conn.execute(
            "SELECT role, content, position FROM messages WHERE session_id = ? AND active = 1 "
            "AND position BETWEEN ? AND ? ORDER BY position",
            (session_id, position - window, position + window),
        ).fetchall()
        results.append(
            {
                "session_id": session_id,
                "snippet": hit["snippet"],
                "role": hit["role"],
                "position": position,
                "window": [dict(r) for r in rows],
                "bookends": _bookends(conn, session_id),
            }
        )
    return results
