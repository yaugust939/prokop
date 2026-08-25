"""Локальный терминальный бэкенд.

Исполняет команды в подпроцессе на хосте. Одна команда — один новый
процесс; состояние окружения переживает спавны через снимок сессии;
текущая директория отслеживается маркером физического пути в выводе;
вывод обрезается скользящим окном с записью полного текста в свалку.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from prokop.backends.base import TerminalBackend
from prokop.backends.errors import InfrastructureError
from prokop.backends.result import (
    DEFAULT_MAX_OUTPUT_CHARS,
    CommandResult,
    truncate_output,
    write_dump,
)
from prokop.backends.snapshot import SessionSnapshot, DEFAULT_EXCLUDED_VARS

DEFAULT_TIMEOUT = 120.0

#: Разбор присваиваний переменных окружения для персистентности.
_EXPORT_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.+)$")
_SET_RE = re.compile(r"^\s*set\s+([A-Za-z_][A-Za-z0-9_]*)=(.+)$", re.IGNORECASE)

#: Последний ``cd <путь>`` в цепочке команд определяет итоговую директорию.
_CD_RE = re.compile(r"(?:^|[&|;])\s*cd(?:\s+|\s*/\S+\s+)([^&|;\r\n]+)", re.IGNORECASE)


class LocalBackend(TerminalBackend):
    """Локальный бэкенд: спавн команд в подпроцессе."""

    name = "local"

    def __init__(
        self,
        *,
        workdir: Optional[str] = None,
        timeout: Optional[float] = DEFAULT_TIMEOUT,
        snapshot_path: Optional[str] = None,
        dump_dir: Optional[str] = None,
        max_output_chars: int = DEFAULT_MAX_OUTPUT_CHARS,
        excluded_vars: Optional[tuple[str, ...]] = None,
    ) -> None:
        super().__init__(workdir=workdir, timeout=timeout)
        self._cwd = Path(workdir) if workdir else Path.cwd()
        self._cwd.mkdir(parents=True, exist_ok=True)
        snapshot = snapshot_path or str(self._cwd / ".prokop_session.json")
        self.snapshot = SessionSnapshot(Path(snapshot), excluded_vars=excluded_vars)
        self.dump_dir = Path(dump_dir) if dump_dir else (self._cwd / ".prokop_dumps")
        self.max_output_chars = max_output_chars

    # --- публичные операции над окружением -------------------------------

    def export_var(self, name: str, value: str) -> None:
        """Явно закрепить переменную окружения в снимке сессии."""
        self.snapshot.set(name, value)

    def unset_var(self, name: str) -> None:
        self.snapshot.unset(name)

    @property
    def cwd(self) -> str:
        return str(self._cwd)

    # --- исполнение ------------------------------------------------------

    def run(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout: Optional[float] = None,
        env: Optional[dict[str, str]] = None,
    ) -> CommandResult:
        command = command or ""
        if not command.strip():
            return CommandResult(exit_code=0)

        use_cwd = cwd or str(self._cwd)
        base_env = dict(os.environ)
        if env:
            base_env.update(env)
        # Переменные снимка переживают спавны: вливаются в каждую команду.
        base_env.update(self.snapshot.as_env())

        try:
            proc = subprocess.Popen(
                command,
                shell=True,
                cwd=use_cwd,
                env=base_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=(os.name != "nt"),
            )
        except OSError as exc:
            raise InfrastructureError(f"не удалось запустить процесс: {exc}", cause=exc) from exc

        timed_out = False
        try:
            out, err = proc.communicate(timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired:
            self._kill_tree(proc)
            out, err = proc.communicate()
            timed_out = True

        out, err = out or "", err or ""
        exit_code = -1 if timed_out else (proc.returncode or 0)

        # Переходы директорий переживают спавны (детекция `cd`).
        if not timed_out and exit_code == 0:
            new_cwd = self._detect_cd(command)
            if new_cwd and Path(new_cwd).exists():
                self._cwd = Path(new_cwd)

        self._persist_exports(command)

        truncated, was_truncated = truncate_output(out, self.max_output_chars)
        dump_path: Optional[str] = None
        if was_truncated:
            dump_path = str(write_dump(self.dump_dir, out, f"run-{int(time.time())}"))

        return CommandResult(
            exit_code=exit_code,
            output=truncated,
            stderr=err,
            truncated=was_truncated,
            dump_path=dump_path,
            timed_out=timed_out,
        )

    # --- вспомогательное -------------------------------------------------

    def _detect_cd(self, command: str) -> Optional[str]:
        """Извлечь итоговую директорию из последнего ``cd`` в команде."""
        matches = list(_CD_RE.finditer(command))
        if not matches:
            return None
        target = matches[-1].group(1).strip().strip('"').strip("'")
        if not target:
            return str(Path.home())
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self._cwd / path
        return str(path.resolve())

    def _persist_exports(self, command: str) -> None:
        """Best-effort: сохранить `export NAME=value`/`set NAME=value` в снимок."""
        for line in command.splitlines():
            line = line.strip()
            match = _EXPORT_RE.match(line) or _SET_RE.match(line)
            if match:
                name, value = match.group(1), match.group(2).strip().strip('"').strip("'")
                self.snapshot.set(name, value)

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        """Принудительно убить процесс (и по возможности его детей)."""
        try:
            if os.name == "nt":
                subprocess.run(
                    f"taskkill /F /T /PID {proc.pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                import signal

                os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        finally:
            try:
                proc.kill()
            except OSError:
                pass
