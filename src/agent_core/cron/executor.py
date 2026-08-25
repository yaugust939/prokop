"""Исполнение заданий «без агента» (скрипт в подпроцессе)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional

#: Таймаут исполнения скрипта по умолчанию, секунд.
DEFAULT_SCRIPT_TIMEOUT = 120.0


@dataclass
class ExecutionResult:
    """Результат исполнения скрипта."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def silent(self) -> bool:
        """Тихий прогон: успех и пустой вывод."""
        return self.ok and not self.stdout.strip()


def execute_script(
    script: str,
    *,
    workdir: Optional[str] = None,
    timeout: float = DEFAULT_SCRIPT_TIMEOUT,
    shell: Optional[str] = None,
) -> ExecutionResult:
    """Исполнить скрипт в подпроцессе с таймаутом.

    Скрипт передаётся оболочке; возвращается код выхода, вывод и признак
    таймаута. Нулевой код и пустой вывод означают тихий прогон.
    """
    try:
        completed = subprocess.run(
            script,
            shell=True,
            cwd=workdir,
            executable=shell,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return ExecutionResult(
            exit_code=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            exit_code=-1,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
            timed_out=True,
        )
    except OSError as exc:
        return ExecutionResult(exit_code=-1, stderr=str(exc))
