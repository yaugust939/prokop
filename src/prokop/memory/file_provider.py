"""Файловый провайдер памяти: факты и дайджесты ходов в профиле.

Хранилище — JSONL в домашнем каталоге профиля (``<профиль>/memory/``):
одна запись на строку. Файл только дописывается; при превышении предела
записей уплотняется атомарно. Битые строки пропускаются, поэтому частично
повреждённый файл не делает память нечитаемой.

Релевантность подбирается по пересечению токенов запроса и текста записи —
без внешних сервисов и зависимостей.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from prokop.logging_setup import get_logger
from prokop.memory.provider import MemoryProvider

log = get_logger("memory.file")

#: Каталог памяти внутри профиля.
MEMORY_DIR = "memory"

#: Имя файла хранилища по умолчанию.
MEMORY_FILENAME = "memory.jsonl"

#: Предел числа записей по умолчанию.
DEFAULT_MAX_RECORDS = 2000

#: Сколько записей возвращать в подгрузке по умолчанию.
DEFAULT_PREFETCH_LIMIT = 5

#: Сколько символов стороны хода попадает в дайджест.
DEFAULT_TURN_LIMIT = 600

#: Минимальная длина токена, учитываемого при подборе.
MIN_TOKEN_LENGTH = 3

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str) -> set[str]:
    """Токены текста (регистр не учитывается, поддержка кириллицы)."""
    return {
        token
        for token in _TOKEN_RE.findall((text or "").lower())
        if len(token) >= MIN_TOKEN_LENGTH
    }


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value) if value > 0 else default


class FileMemoryProvider(MemoryProvider):
    """Постоянная память профиля в файле JSONL."""

    name = "file"

    def __init__(
        self,
        home: Path,
        *,
        filename: str = MEMORY_FILENAME,
        max_records: int = DEFAULT_MAX_RECORDS,
        prefetch_limit: int = DEFAULT_PREFETCH_LIMIT,
        turn_limit: int = DEFAULT_TURN_LIMIT,
        session_id: Optional[str] = None,
    ) -> None:
        self.home = Path(home)
        self.path = self.home / MEMORY_DIR / filename
        self.max_records = int(max_records)
        self.prefetch_limit = int(prefetch_limit)
        self.turn_limit = int(turn_limit)
        self.session_id = session_id

    # ── контракт ──────────────────────────────────────────────────

    def init(
        self,
        *,
        session_id: Optional[str] = None,
        home: Optional[str] = None,
        platform: Optional[str] = None,
        agent_context: Optional[dict[str, Any]] = None,
        agent_identity: Optional[dict[str, Any]] = None,
    ) -> None:
        if session_id:
            self.session_id = session_id

    def is_available(self) -> bool:
        return True

    def system_prompt_block(self) -> str:
        return (
            "У агента есть постоянная память профиля, переживающая перезапуск. "
            "Факты сохраняются инструментом memory_save, ищутся memory_search, "
            "удаляются memory_forget."
        )

    async def prefetch(self, query: str) -> str:
        records = self._relevant(query, limit=self.prefetch_limit)
        if not records:
            return ""
        lines = ["Из постоянной памяти:"]
        for record in records:
            if record.get("kind") == "fact":
                lines.append(f"- {record.get('key')}: {record.get('value')}")
            else:
                lines.append(f"- (прошлый ход) {record.get('value')}")
        return "\n".join(lines)

    async def sync_turn(
        self,
        user_message: str,
        assistant_message: str,
        messages: list[dict[str, Any]],
    ) -> None:
        digest = self._digest(user_message, assistant_message)
        if digest:
            self._append({"kind": "turn", "value": digest, "session": self.session_id})

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory_save",
                    "description": "Сохранить факт в постоянную память профиля.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Ключ факта"},
                            "value": {"type": "string", "description": "Значение факта"},
                        },
                        "required": ["key", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "description": "Найти записи в постоянной памяти по запросу.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Поисковый запрос"},
                            "limit": {"type": "integer", "description": "Сколько записей вернуть"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_forget",
                    "description": "Удалить факт из постоянной памяти по ключу.",
                    "parameters": {
                        "type": "object",
                        "properties": {"key": {"type": "string", "description": "Ключ факта"}},
                        "required": ["key"],
                    },
                },
            },
        ]

    async def handle_tool_call(self, name: str, args: dict[str, Any]) -> str:
        try:
            if name == "memory_save":
                key = str(args.get("key") or "").strip()
                if not key:
                    return json.dumps({"error": "не задан ключ"}, ensure_ascii=False)
                self._append(
                    {
                        "kind": "fact",
                        "key": key,
                        "value": str(args.get("value") or ""),
                        "session": self.session_id,
                    }
                )
                return json.dumps({"ok": True, "key": key}, ensure_ascii=False)

            if name == "memory_search":
                query = str(args.get("query") or "")
                limit = _positive_int(args.get("limit"), self.prefetch_limit)
                records = self.search(query, limit=limit)
                return json.dumps(
                    {"query": query, "records": records, "count": len(records)},
                    ensure_ascii=False,
                )

            if name == "memory_forget":
                key = str(args.get("key") or "").strip()
                if not key:
                    return json.dumps({"error": "не задан ключ"}, ensure_ascii=False)
                return json.dumps(
                    {"ok": self.forget(key), "key": key}, ensure_ascii=False
                )
        except Exception as exc:  # noqa: BLE001 — ошибка инструмента не роняет ход
            log.warning("Инструмент памяти %s завершился ошибкой: %s", name, exc)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

        return await super().handle_tool_call(name, args)

    def backup_paths(self) -> list[str]:
        return [str(self.path)]

    # ── публичное (CLI, тесты) ────────────────────────────────────

    def facts(self) -> list[dict[str, Any]]:
        """Факты: последнее значение каждого ключа, свежие первыми."""
        return self._latest_facts(self._read())

    def search(
        self, query: str, *, limit: Optional[int] = None
    ) -> list[dict[str, Any]]:
        """Найти записи по запросу (по умолчанию — предел подгрузки)."""
        return self._relevant(
            query, limit=self.prefetch_limit if limit is None else limit
        )

    def forget(self, key: str) -> bool:
        """Удалить факт по ключу. Возвращает, был ли факт."""
        key = str(key or "").strip()
        if not key:
            return False
        records = self._read()
        kept = [
            record
            for record in records
            if not (record.get("kind") == "fact" and str(record.get("key")) == key)
        ]
        if len(kept) == len(records):
            return False
        self._rewrite(kept)
        return True

    # ── хранилище ─────────────────────────────────────────────────

    def _read(self) -> list[dict[str, Any]]:
        """Прочитать записи; битые строки пропускаются."""
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            log.warning("Память недоступна: %s", exc)
            return []

        records: list[dict[str, Any]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                records.append(data)
        return records

    def _append(self, record: dict[str, Any]) -> None:
        payload = {"at": datetime.now().isoformat(timespec="seconds"), **record}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("Не удалось записать в память: %s", exc)
            return
        self._compact_if_needed()

    def _rewrite(self, records: list[dict[str, Any]]) -> None:
        """Атомарно перезаписать хранилище."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    for record in records:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        except OSError as exc:
            log.warning("Не удалось перезаписать память: %s", exc)

    def _compact_if_needed(self) -> None:
        if self.max_records <= 0:
            return
        records = self._read()
        if len(records) <= self.max_records:
            return
        self._rewrite(records[-self.max_records :])

    # ── подбор ────────────────────────────────────────────────────

    @staticmethod
    def _latest_facts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Последнее значение каждого ключа, свежие первыми.

        Свежесть определяется порядком в файле (запись только дописывается),
        а не меткой времени: метки имеют секундную точность и могут совпасть.
        """
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for record in reversed(records):
            if record.get("kind") != "fact":
                continue
            key = str(record.get("key") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(record)
        return out

    def _relevant(self, query: str, *, limit: int) -> list[dict[str, Any]]:
        records = self._read()
        if not records or limit <= 0:
            return []

        query_tokens = _tokens(query)
        if not query_tokens:
            return self._latest_facts(records)[:limit]

        # Порядок в файле = порядок записи: больший индекс означает более
        # свежую запись и разрешает ничьи по оценке релевантности.
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, record in enumerate(records):
            text = f"{record.get('key') or ''} {record.get('value') or ''}"
            score = len(query_tokens & _tokens(text))
            if score:
                scored.append((score, index, record))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

        seen_keys: set[str] = set()
        out: list[dict[str, Any]] = []
        for _score, _index, record in scored:
            if record.get("kind") == "fact":
                key = str(record.get("key") or "")
                if key in seen_keys:
                    continue
                seen_keys.add(key)
            out.append(record)
            if len(out) >= limit:
                break
        return out

    def _digest(self, user_message: str, assistant_message: str) -> str:
        user = (user_message or "").strip()[: self.turn_limit]
        assistant = (assistant_message or "").strip()[: self.turn_limit]
        parts = []
        if user:
            parts.append(f"запрос: {user}")
        if assistant:
            parts.append(f"ответ: {assistant}")
        return " | ".join(parts)
