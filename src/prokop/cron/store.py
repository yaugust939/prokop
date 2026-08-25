"""Файловый магазин заданий планировщика.

Плоский JSON-файл в домашнем каталоге профиля. Запись атомарная
(временный файл + переименование); критические секции защищены
межпроцессной файловой блокировкой с таймаутом ожидания.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from prokop.cron.model import Job

JOBS_FILENAME = "jobs.json"
LOCK_FILENAME = "jobs.lock"

#: Таймаут ожидания блокировки, секунд.
LOCK_TIMEOUT_SECONDS = 10.0


class JobStore:
    """Магазин заданий в каталоге планировщика профиля."""

    def __init__(self, home: Path) -> None:
        self.dir = Path(home) / "cron"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / JOBS_FILENAME
        self.lock_path = self.dir / LOCK_FILENAME

    # --- блокировка -----------------------------------------------------

    @contextmanager
    def locked(self, timeout: float = LOCK_TIMEOUT_SECONDS) -> Iterator[None]:
        """Межпроцессная блокировка с таймаутом ожидания.

        При недоступности блокировки в пределах таймаута — тихо отпускаем
        (тик пропускается), чтобы не замораживать планировщик.
        """
        lock = _FileLock(self.lock_path, timeout=timeout)
        acquired = lock.acquire()
        try:
            yield
        finally:
            if acquired:
                lock.release()

    # --- чтение/запись ----------------------------------------------------

    def load(self) -> list[Job]:
        """Загрузить все задания."""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return [Job.from_dict(item) for item in data.get("jobs", [])]

    def save(self, jobs: list[Job]) -> None:
        """Атомарно сохранить все задания."""
        payload = {"jobs": [job.to_dict() for job in jobs]}
        fd, tmp_name = tempfile.mkstemp(dir=str(self.dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self.path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # --- операции -----------------------------------------------------------

    def get(self, job_id: str) -> Optional[Job]:
        for job in self.load():
            if job.id == job_id:
                return job
        return None

    def upsert(self, job: Job) -> None:
        """Добавить или обновить задание (под блокировкой)."""
        with self.locked():
            jobs = self.load()
            for i, existing in enumerate(jobs):
                if existing.id == job.id:
                    jobs[i] = job
                    break
            else:
                jobs.append(job)
            self.save(jobs)

    def remove(self, job_id: str) -> bool:
        """Удалить задание; возвращает, было ли оно."""
        with self.locked():
            jobs = self.load()
            remaining = [j for j in jobs if j.id != job_id]
            if len(remaining) == len(jobs):
                return False
            self.save(remaining)
            return True


class _FileLock:
    """Простая межпроцессная файловая блокировка."""

    def __init__(self, path: Path, timeout: float = LOCK_TIMEOUT_SECONDS) -> None:
        self.path = path
        self.timeout = timeout
        self._fd: Optional[int] = None

    def acquire(self) -> bool:
        try:
            import fcntl  # POSIX

            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    fd = os.open(self.path, os.O_CREAT | os.O_RDWR)
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fd = fd
                    return True
                except OSError:
                    if time.monotonic() >= deadline:
                        return False
                    time.sleep(0.05)
        except ImportError:
            return self._acquire_windows()

    def _acquire_windows(self) -> bool:
        """Фолбэк для Windows: атомарное создание маркера."""
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                self._fd = fd
                return True
            except FileExistsError:
                # Устаревший маркер (старше таймаута) перехватываем.
                try:
                    if time.time() - self.path.stat().st_mtime > self.timeout:
                        self.path.unlink()
                        continue
                except OSError:
                    return False
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)
            except OSError:
                return False

    def release(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
        try:
            self.path.unlink()
        except OSError:
            pass
