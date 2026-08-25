"""Снимок сессии бэкенда.

Сохраняет окружение (переменные) между отдельными спавнами: загружается
перед командой и атомарно пересохраняется после. Из снимка исключаются
служебные переменные системы, чтобы одна сессия не «заражала» другие.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

#: Переменные, исключаемые из снимка по умолчанию.
DEFAULT_EXCLUDED_VARS: tuple[str, ...] = (
    "PROKOP_SESSION_ID",
    "PROKOP_TASK_ID",
    "PROKOP_CRON_RUN",
    "PROKOP_PROFILE",
    "PYTHONPATH",
    "PWD",
    "OLDPWD",
    "SHLVL",
    "_",
)


class SessionSnapshot:
    """Файловый снимок окружения сессии."""

    def __init__(
        self,
        path: Path,
        *,
        excluded_vars: Optional[tuple[str, ...]] = None,
    ) -> None:
        self.path = Path(path)
        self.excluded_vars = set(excluded_vars or DEFAULT_EXCLUDED_VARS)

    # --- чтение/запись --------------------------------------------------

    def load(self) -> dict[str, str]:
        """Загрузить сохранённые переменные (пустой словарь при отсутствии)."""
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def save(self, env: dict[str, str]) -> None:
        """Атомарно сохранить переменные (минус служебные).

        Запись через временный файл и переименование — параллельные
        подгрузки не видят полузаписанный файл. Права — приватные.
        """
        filtered = {
            k: v for k, v in env.items() if k not in self.excluded_vars
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(filtered, fh, ensure_ascii=False)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # --- операции над переменными ---------------------------------------

    def get(self, name: str) -> Optional[str]:
        return self.load().get(name)

    def set(self, name: str, value: str) -> None:
        env = self.load()
        env[name] = value
        self.save(env)

    def unset(self, name: str) -> None:
        env = self.load()
        env.pop(name, None)
        self.save(env)

    def as_env(self) -> dict[str, str]:
        """Переменные снимка для передачи в подпроцесс."""
        return self.load()
