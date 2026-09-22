"""Журнал решений безопасности.

Формат — JSONL (одно решение на строку), только добавление. Запись
best-effort: сбой журнала не должен прерывать операцию, поэтому ошибка
попадает в лог ядра, а не наружу. Чтение — по хвосту с ограничением числа
записей.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from prokop.logging_setup import get_logger
from prokop.paths import resolve_logs_path
from prokop.security.policy import PolicyDecision, get_policy

log = get_logger("security.audit")

#: Имя файла журнала в каталоге логов профиля.
AUDIT_FILENAME = "security.jsonl"

#: Сколько последних записей читать по умолчанию.
DEFAULT_TAIL = 50


class AuditLog:
    """Журнал решений политики."""

    def __init__(
        self,
        home: Optional[Path] = None,
        *,
        enabled: bool = True,
        filename: str = AUDIT_FILENAME,
    ) -> None:
        self.home = Path(home) if home is not None else None
        self.enabled = bool(enabled)
        self.filename = filename

    def path(self) -> Path:
        """Путь к файлу журнала."""
        if self.home is not None:
            return self.home / "logs" / self.filename
        return resolve_logs_path() / self.filename

    def record(self, decision: PolicyDecision, *, source: str = "") -> None:
        """Записать решение (best-effort, без исключений наружу)."""
        if not self.enabled:
            return
        payload = {
            "at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
            **decision.to_dict(),
        }
        try:
            target = self.path()
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("Не удалось записать решение в журнал: %s", exc)

    def tail(self, limit: int = DEFAULT_TAIL) -> list[dict[str, Any]]:
        """Последние записи журнала (в обратном порядке), не более ``limit``."""
        limit = max(0, int(limit))
        target = self.path()
        if limit == 0 or not target.exists():
            return []
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            log.warning("Не удалось прочитать журнал: %s", exc)
            return []

        records: list[dict[str, Any]] = []
        for line in reversed(lines):
            if len(records) >= limit:
                break
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


_audit: Optional[AuditLog] = None


def get_audit() -> AuditLog:
    """Журнал активного профиля (кэшируется)."""
    global _audit
    if _audit is None:
        _audit = AuditLog(enabled=get_policy().audit_enabled)
    return _audit


def reset_audit() -> None:
    """Сбросить кэш журнала (для тестов и смены конфигурации)."""
    global _audit
    _audit = None
