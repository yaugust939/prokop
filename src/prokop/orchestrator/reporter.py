"""Отчётность в трекеры ``tasks.md`` (этап 1 — MVP).

Формат строки трекера:
``- [статус] P<0..2> · <исполнитель> · <описание> (#id)``
статусы: ``[ ]`` ожидает, ``[~]`` в работе, ``[x]`` готово, ``[!]`` заблокировано.

Запись атомарная: чтение → правка → запись во временный файл + ``os.replace``
под межпроцессной файловой блокировкой (паттерн ``_FileLock`` из
``prokop/cron/store.py``).
"""

from __future__ import annotations

import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from prokop.cron.store import _FileLock, LOCK_TIMEOUT_SECONDS

#: Имя переменной окружения, переопределяющей путь к глобальному трекеру.
ENV_TRACKER = "HERMES_TRACKER"

#: Каталог штаба HERMES в домашнем каталоге пользователя (``~/.hermes``).
HERMES_HOME = Path.home() / ".hermes"


def global_tracker() -> Path:
    """Путь к глобальному трекеру HERMES (без обращения к диску).

    Приоритет: ``HERMES_TRACKER`` → ``~/.hermes/tasks.md``. Раскладка
    одинакова на всех платформах; личных абсолютных путей в ядре нет.
    """
    override = os.environ.get(ENV_TRACKER)
    if override:
        return Path(override).expanduser()
    return HERMES_HOME / "tasks.md"

#: Шаблон строки трекера.
_TRACKER_LINE_RE = re.compile(
    r"^-\s*\[(?P<status>[\s~x!])\]\s*"
    r"P(?P<priority>[0-2])\s*·\s*"
    r"(?P<executor>[^·]+?)\s*·\s*"
    r"(?P<description>.*?)\s*\(#(?P<id>\d+)\)\s*$"
)

#: Шаблон поиска строки по id в конце.
_ID_SUFFIX_RE = re.compile(r"\(#(?P<id>\d+)\)\s*$")

STATUS_WAITING = " "
STATUS_RUNNING = "~"
STATUS_DONE = "x"
STATUS_BLOCKED = "!"


class TrackerError(Exception):
    """Ошибка работы с трекером."""


def resolve_tracker(project: Optional[str]) -> Path:
    """Трекер для проекта: ``<проект>/.hermes/tasks.md``, иначе глобальный."""
    if project:
        candidate = Path(project) / ".hermes" / "tasks.md"
        if candidate.exists():
            return candidate
    return global_tracker()


@contextmanager
def locked_tracker(path: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
    """Межпроцессная блокировка трекера (по образцу JobStore.locked)."""
    lock = _FileLock(path.with_suffix(path.suffix + ".lock"), timeout=timeout)
    acquired = lock.acquire()
    try:
        yield
    finally:
        if acquired:
            lock.release()


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return text.splitlines()


def _write_lines_atomic(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(lines)
    if payload and not payload.endswith("\n"):
        payload += "\n"
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _find_line_index(lines: list[str], task_id: int) -> Optional[int]:
    for i, line in enumerate(lines):
        m = _ID_SUFFIX_RE.search(line)
        if m and int(m.group("id")) == task_id:
            return i
    return None


def _max_task_id(lines: list[str]) -> int:
    max_id = 0
    for line in lines:
        m = _ID_SUFFIX_RE.search(line)
        if m:
            max_id = max(max_id, int(m.group("id")))
    return max_id


def _build_line(status: str, priority: str, executor: str, description: str, task_id: int) -> str:
    return f"- [{status}] P{priority} · {executor} · {description} (#{task_id})"


def next_task_id(tracker: Optional[Path] = None) -> int:
    """Следующий свободный id трекера (max + 1)."""
    path = tracker or global_tracker()
    return _max_task_id(_read_lines(path)) + 1


def add_task_line(
    *,
    tracker: Optional[Path] = None,
    project: Optional[str] = None,
    status: str = STATUS_RUNNING,
    priority: str = "P1",
    executor: str = "прокопий",
    description: str,
    task_id: Optional[int] = None,
) -> int:
    """Добавить строку задачи в трекер (атомарно, под блокировкой)."""
    path = tracker or resolve_tracker(project)
    with locked_tracker(path):
        lines = _read_lines(path)
        if task_id is None:
            task_id = _max_task_id(lines) + 1
        lines.append(_build_line(status, priority, executor, description, task_id))
        _write_lines_atomic(path, lines)
    return task_id


def update_task_line(
    *,
    tracker: Optional[Path] = None,
    project: Optional[str] = None,
    task_id: int,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    executor: Optional[str] = None,
    description: Optional[str] = None,
) -> bool:
    """Обновить строку задачи по id (атомарно). Возвращает, найдена ли."""
    path = tracker or resolve_tracker(project)
    with locked_tracker(path):
        lines = _read_lines(path)
        idx = _find_line_index(lines, task_id)
        if idx is None:
            return False
        old = _TRACKER_LINE_RE.match(lines[idx])
        if not old:
            # Строка не парсится — дописываем статус в начало хвоста.
            return False
        new_status = status if status is not None else old.group("status")
        new_priority = priority if priority is not None else old.group("priority")
        new_executor = executor if executor is not None else old.group("executor")
        new_description = description if description is not None else old.group("description")
        lines[idx] = _build_line(
            new_status, new_priority, new_executor.strip(), new_description.strip(), task_id
        )
        _write_lines_atomic(path, lines)
    return True
