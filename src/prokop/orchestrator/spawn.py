"""Запуск headless-сессии opencode (этап 1 — MVP).

Единственная точка, где порождаются процессы ``opencode run``. Запуск идёт
через ``subprocess.Popen`` со списком аргументов (без shell), что надёжно
передаёт кириллицу и пробелы в путях на Windows. Вывод процесса собирается
в ``collect.py`` как NDJSON-поток.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

#: Список кандидатов на исполняемый файл opencode (первый найденный).
_OPCODE_CANDIDATES = (
    "OPENCODE_BIN",  # явное переопределение через переменную окружения
)

#: Времена ожидания по приоритету задачи, минуты (конфиг по умолчанию).
DEFAULT_TIMEOUTS_MINUTES: dict[str, float] = {
    "P0": 60.0,
    "P1": 30.0,
    "P2": 15.0,
}


@dataclass
class SpawnConfig:
    """Конфигурация запуска headless-сессии."""

    prompt: str
    project: str                       # абсолютный путь к проекту
    agent: str = "прокопий"            # агент opencode (primary: план/работа/прокопий)
    model: Optional[str] = None        # принудительная модель (provider/model)
    title: Optional[str] = None
    session_id: Optional[str] = None   # продолжить существующую сессию
    continue_session: bool = False     # --continue
    fork: bool = False                 # --fork (retry после таймаута)
    auto: bool = True                  # --auto (авто-одобрение permission)
    priority: str = "P1"               # P0/P1/P2 — таймаут по умолчанию
    timeout_minutes: Optional[float] = None  # переопределение таймаута

    #: Флаги, добавляемые к вызову (например, "--print-logs").
    extra_args: list[str] = field(default_factory=list)

    @property
    def timeout_seconds(self) -> float:
        minutes = self.timeout_minutes or DEFAULT_TIMEOUTS_MINUTES.get(
            self.priority, DEFAULT_TIMEOUTS_MINUTES["P1"]
        )
        return minutes * 60.0


def find_opencode() -> Optional[str]:
    """Найти исполняемый файл opencode.

    Порядок: ``OPENCODE_BIN`` → прямой бинарь в типовых каталогах установки
    → ``shutil.which``. Прямой бинарь предпочтительнее: на Windows
    ``.CMD``/``.PS1``-обёртки из PATH ненадёжны при запуске без shell.
    Возвращает ``None``, если бинарь не найден.
    """
    env = os.environ.get("OPENCODE_BIN")
    if env:
        return env
    for candidate in _npm_candidates():
        if candidate.exists():
            return str(candidate)
    resolved = shutil.which("opencode")
    if resolved:
        return resolved
    return None


def _npm_candidates() -> list[Path]:
    """Типовые пути установки opencode для текущей платформы.

    На Windows прямой ``.exe`` надёжнее ``.CMD``/``.PS1``-обёрток из PATH;
    на POSIX — бинарь без расширения. Проверяются и каталоги bin, и
    локальные ``node_modules`` (полезно, когда PATH урезан).
    """
    names = ("opencode.exe", "opencode.cmd", "opencode") if os.name == "nt" \
        else ("opencode",)
    roots: list[Path] = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            roots.append(Path(appdata) / "npm")
    else:
        home = Path.home()
        roots += [
            home / ".npm-global" / "bin",
            home / ".local" / "bin",
            Path("/usr/local/bin"),
            Path("/usr/bin"),
        ]
    out: list[Path] = []
    for root in roots:
        # Сначала сам бинарь пакета: на Windows это единственный вариант без
        # .CMD-обёртки, которая ломается при запуске без shell.
        out += [
            root / "node_modules" / "opencode-ai" / "bin" / name
            for name in names
        ]
        out += [root / name for name in names]
    return out


def build_command(cfg: SpawnConfig, binary: str) -> list[str]:
    """Собрать список аргументов для ``opencode run``."""
    cmd = [binary, "run", cfg.prompt, "--dir", cfg.project, "--agent", cfg.agent,
           "--format", "json"]
    if cfg.model:
        cmd += ["--model", cfg.model]
    if cfg.title:
        cmd += ["--title", cfg.title]
    if cfg.session_id:
        cmd += ["--session", cfg.session_id]
    if cfg.continue_session:
        cmd.append("--continue")
    if cfg.fork:
        cmd.append("--fork")
    if cfg.auto:
        cmd.append("--auto")
    cmd += cfg.extra_args
    return cmd


def spawn(cfg: SpawnConfig) -> tuple[subprocess.Popen, Optional[str]]:
    """Запустить headless-сессию opencode.

    Возвращает кортеж (процесс, путь к бинарю opencode). Бросает
    ``FileNotFoundError``, если opencode не найден, и ``OSError`` при ошибке
    запуска.
    """
    binary = find_opencode()
    if binary is None:
        raise FileNotFoundError(
            "opencode не найден: задайте OPENCODE_BIN или установите npm-пакет"
        )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        build_command(cfg, binary),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        cwd=cfg.project,
        # POSIX: ребёнок становится лидером своей группы процессов — тогда
        # kill по группе не задевает родителя (см. collect._kill_process_tree).
        start_new_session=(os.name != "nt"),
    )
    return proc, binary
