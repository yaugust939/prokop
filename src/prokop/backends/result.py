"""Результат исполнения команды и его обрезка."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class CommandResult:
    """Результат исполнения одной команды."""

    exit_code: int
    output: str = ""
    stderr: str = ""
    truncated: bool = False
    dump_path: Optional[str] = None
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    @property
    def is_infra_error(self) -> bool:
        """Инфраструктурная ошибка кодируется кодом ``-100``."""
        return self.exit_code == INFRA_EXIT_CODE


#: Код выхода, которым кодируется инфраструктурный сбой.
INFRA_EXIT_CODE = -100

#: Потолок вывода по умолчанию (символы).
DEFAULT_MAX_OUTPUT_CHARS = 8000

#: Доля «головы» окна (остальное — «хвост»).
HEAD_RATIO = 0.4

#: Маркер места обрезки.
TRUNCATION_MARKER = "\n…[вывод обрезан — полный текст в файле]…\n"


def truncate_output(output: str, max_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Обрезать вывод скользящим окном «голова+хвост».

    Если вывод короче потолка — возвращается как есть. Иначе — голова
    (40%) и хвост (60%) от потолка с маркером между ними.
    """
    if not output:
        return output, False
    if len(output) <= max_chars:
        return output, False
    head_size = int(max_chars * HEAD_RATIO)
    tail_size = max_chars - head_size - len(TRUNCATION_MARKER)
    if tail_size <= 0:
        tail_size = 0
    truncated = output[:head_size] + TRUNCATION_MARKER + (output[-tail_size:] if tail_size else "")
    return truncated, True


def write_dump(dump_dir: Path, output: str, job_tag: str) -> Path:
    """Записать полный вывод в файл-свалку с приватными правами."""
    dump_dir.mkdir(parents=True, exist_ok=True)
    path = dump_dir / f"{job_tag}.out"
    path.write_text(output, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
