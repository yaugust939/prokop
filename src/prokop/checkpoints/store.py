"""Снимки состояния и откат.

Снимок — каталог в домашнем каталоге профиля: манифест (что снято) и блобы
(содержимое файлов). Никаких теней ФС и симлинков: только копирование, поэтому
поведение одинаково на Windows, macOS и Linux.

Восстановление безопасно по умолчанию: содержимое записанных файлов
возвращается, отсутствующие файлы и каталоги воссоздаются, а файлы, появившиеся
после снимка, **не удаляются** — для этого нужен явный запрос. Перед
восстановлением создаётся страховочный снимок текущего состояния, поэтому
откат обратим.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from prokop.logging_setup import get_logger

log = get_logger("checkpoints.store")

#: Каталог снимков внутри профиля.
CHECKPOINTS_DIR = "checkpoints"
INDEX_NAME = "index.json"
MANIFEST_NAME = "manifest.json"
BLOBS_DIR = "files"

#: Служебные имена, не попадающие в снимок по умолчанию.
DEFAULT_IGNORES: tuple[str, ...] = (
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "*.pyc",
    "*.pyo",
    "*.egg-info",
    ".prokop_dumps",
    ".prokop_session.json",
)

#: Потолок размера одного копируемого файла по умолчанию (5 МБ).
DEFAULT_MAX_FILE_BYTES = 5 * 1024 * 1024

#: Потолок числа хранимых снимков по умолчанию.
DEFAULT_MAX_ENTRIES = 20


class CheckpointError(Exception):
    """Ошибка работы со снимками."""


def _positive_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return int(value) if value > 0 else default


@dataclass
class SnapshotEntry:
    """Одна запись снимка: файл или каталог."""

    path: str
    kind: str = "file"
    blob: Optional[str] = None
    size: int = 0
    #: Причина, по которой содержимое не сохранено (если так).
    skipped: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "blob": self.blob,
            "size": self.size,
            "skipped": self.skipped,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SnapshotEntry":
        return cls(
            path=str(data.get("path", "")),
            kind=str(data.get("kind", "file")),
            blob=data.get("blob"),
            size=int(data.get("size") or 0),
            skipped=data.get("skipped"),
        )


@dataclass
class Snapshot:
    """Снимок набора путей."""

    id: str
    label: str = ""
    created_at: str = ""
    roots: list[str] = field(default_factory=list)
    entries: list[SnapshotEntry] = field(default_factory=list)

    @property
    def files(self) -> int:
        """Число записанных файлов."""
        return sum(1 for e in self.entries if e.kind == "file" and e.blob)

    @property
    def total_bytes(self) -> int:
        """Суммарный размер записанных файлов."""
        return sum(e.size for e in self.entries if e.kind == "file" and e.blob)

    @property
    def skipped(self) -> list[SnapshotEntry]:
        """Записи, содержимое которых не сохранено."""
        return [e for e in self.entries if e.skipped]

    def summary(self) -> dict[str, Any]:
        """Краткое описание для списка (без содержимого)."""
        return {
            "id": self.id,
            "label": self.label,
            "created_at": self.created_at,
            "roots": list(self.roots),
            "files": self.files,
            "bytes": self.total_bytes,
            "skipped": len(self.skipped),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "entries": [e.to_dict() for e in self.entries]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Snapshot":
        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label", "")),
            created_at=str(data.get("created_at", "")),
            roots=[str(r) for r in (data.get("roots") or [])],
            entries=[SnapshotEntry.from_dict(e) for e in (data.get("entries") or [])],
        )


@dataclass
class RestoreReport:
    """Итог восстановления из снимка."""

    checkpoint_id: str
    safety_id: Optional[str] = None
    restored: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    #: Пути, запрещённые политикой безопасности.
    denied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "safety_id": self.safety_id,
            "restored": list(self.restored),
            "removed": list(self.removed),
            "errors": list(self.errors),
            "denied": list(self.denied),
        }


class CheckpointStore:
    """Хранилище снимков профиля."""

    def __init__(
        self,
        home: Path,
        *,
        ignores: Optional[Iterable[str]] = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        enabled: bool = True,
        path_guard: Optional[Callable[[str], Optional[str]]] = None,
    ) -> None:
        self.home = Path(home)
        self.dir = self.home / CHECKPOINTS_DIR
        self.ignores = tuple(ignores) if ignores is not None else DEFAULT_IGNORES
        self.max_file_bytes = int(max_file_bytes)
        self.max_entries = int(max_entries)
        self.enabled = bool(enabled)
        #: Проверка политики путей: возвращает причину запрета или ``None``.
        self.path_guard = path_guard

    def _denied_reason(self, path: str | Path) -> Optional[str]:
        if self.path_guard is None:
            return None
        try:
            return self.path_guard(str(path))
        except Exception as exc:  # noqa: BLE001 — сбой проверки трактуем как запрет
            return f"проверка политики не удалась: {exc}"

    @classmethod
    def from_config(
        cls,
        home: Path,
        section: Any,
        *,
        path_guard: Optional[Callable[[str], Optional[str]]] = None,
    ) -> "CheckpointStore":
        """Собрать хранилище из секции ``checkpoints`` конфигурации профиля."""
        data = section if isinstance(section, Mapping) else {}
        ignores = list(DEFAULT_IGNORES)
        extra = data.get("ignore")
        if isinstance(extra, (list, tuple)):
            ignores += [str(item) for item in extra if str(item).strip()]
        return cls(
            home,
            ignores=ignores,
            max_file_bytes=_positive_int(data.get("max_file_bytes"), DEFAULT_MAX_FILE_BYTES),
            max_entries=_positive_int(data.get("max_entries"), DEFAULT_MAX_ENTRIES),
            enabled=bool(data.get("enabled", True)),
            path_guard=path_guard,
        )

    # ── служебное ─────────────────────────────────────────────────

    def _ignored(self, name: str) -> bool:
        return any(name == pattern or fnmatch(name, pattern) for pattern in self.ignores)

    def _new_id(self) -> str:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{stamp}-{secrets.token_hex(3)}"

    def _read_index(self) -> list[dict[str, Any]]:
        path = self.dir / INDEX_NAME
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        rows = data.get("snapshots") if isinstance(data, dict) else None
        return [r for r in (rows or []) if isinstance(r, dict)]

    def _write_json(self, path: Path, payload: Mapping[str, Any]) -> None:
        """Атомарная запись JSON (временный файл + переименование)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # ── снимок ────────────────────────────────────────────────────

    def _add_file(
        self,
        path: Path,
        out: list[SnapshotEntry],
        blobs_dir: Path,
        counter: list[int],
    ) -> None:
        try:
            size = path.stat().st_size
        except OSError as exc:
            out.append(SnapshotEntry(path=str(path), skipped=f"нет доступа: {exc}"))
            return
        if size > self.max_file_bytes:
            out.append(
                SnapshotEntry(path=str(path), size=size, skipped="превышен потолок размера")
            )
            return
        counter[0] += 1
        blob = f"{counter[0]:05d}"
        try:
            shutil.copyfile(path, blobs_dir / blob)
        except OSError as exc:
            out.append(
                SnapshotEntry(path=str(path), size=size, skipped=f"ошибка копирования: {exc}")
            )
            return
        out.append(SnapshotEntry(path=str(path), blob=blob, size=size))

    def _walk(
        self,
        root: Path,
        out: list[SnapshotEntry],
        blobs_dir: Path,
        counter: list[int],
    ) -> None:
        if root.is_dir():
            out.append(SnapshotEntry(path=str(root), kind="dir"))
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(d for d in dirnames if not self._ignored(d))
                current = Path(dirpath)
                for name in dirnames:
                    out.append(SnapshotEntry(path=str(current / name), kind="dir"))
                for name in sorted(filenames):
                    if self._ignored(name):
                        continue
                    self._add_file(current / name, out, blobs_dir, counter)
        elif root.is_file():
            if not self._ignored(root.name):
                self._add_file(root, out, blobs_dir, counter)

    def create(self, paths: Sequence[str | Path], label: str = "") -> Snapshot:
        """Создать снимок указанных путей."""
        roots = [Path(p).expanduser() for p in paths]
        existing = [r for r in roots if r.exists()]
        if not existing:
            raise CheckpointError("нет существующих путей для снимка")

        checkpoint_id = self._new_id()
        target = self.dir / checkpoint_id
        blobs_dir = target / BLOBS_DIR
        blobs_dir.mkdir(parents=True, exist_ok=True)

        entries: list[SnapshotEntry] = []
        counter = [0]
        allowed_roots = 0
        for root in existing:
            denied = self._denied_reason(root)
            if denied is not None:
                entries.append(
                    SnapshotEntry(
                        path=str(root),
                        kind="dir" if root.is_dir() else "file",
                        skipped=f"запрещено политикой: {denied}",
                    )
                )
                continue
            allowed_roots += 1
            try:
                resolved = root.resolve()
            except OSError:
                resolved = root
            self._walk(resolved, entries, blobs_dir, counter)

        if allowed_roots == 0:
            raise CheckpointError("все указанные пути запрещены политикой безопасности")

        snapshot = Snapshot(
            id=checkpoint_id,
            label=label,
            created_at=datetime.now().isoformat(timespec="seconds"),
            roots=[str(r) for r in existing],
            entries=entries,
        )
        self._write_json(target / MANIFEST_NAME, snapshot.to_dict())

        rows = self._read_index()
        rows.insert(0, snapshot.summary())
        self._write_json(self.dir / INDEX_NAME, {"snapshots": rows})

        self.prune()
        log.info("Снимок %s: %d записей, %d файлов", snapshot.id, len(entries), snapshot.files)
        return snapshot

    def list(self) -> list[dict[str, Any]]:
        """Список снимков от новых к старым."""
        return self._read_index()

    def get(self, checkpoint_id: str) -> Optional[Snapshot]:
        """Полный снимок по идентификатору (или ``None``)."""
        if not checkpoint_id or "/" in checkpoint_id or "\\" in checkpoint_id:
            return None
        path = self.dir / checkpoint_id / MANIFEST_NAME
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return Snapshot.from_dict(data)

    # ── восстановление ────────────────────────────────────────────

    def restore(self, checkpoint_id: str, *, remove_extra: bool = False) -> RestoreReport:
        """Восстановить состояние из снимка."""
        snapshot = self.get(checkpoint_id)
        if snapshot is None:
            raise CheckpointError(f"снимок {checkpoint_id!r} не найден")

        report = RestoreReport(checkpoint_id=snapshot.id)

        # Страховочный снимок: откат должен быть обратим. Если снять его не
        # удалось (например, все пути запрещены политикой), это не повод
        # прерывать восстановление — причина попадает в отчёт.
        existing_roots = [r for r in snapshot.roots if Path(r).exists()]
        if existing_roots:
            try:
                safety = self.create(existing_roots, label=f"перед откатом {snapshot.id}")
                report.safety_id = safety.id
            except CheckpointError as exc:
                report.errors.append(f"страховочный снимок не создан: {exc}")

        blobs_dir = self.dir / snapshot.id / BLOBS_DIR
        for entry in snapshot.entries:
            path = Path(entry.path)
            denied = self._denied_reason(path)
            if denied is not None:
                report.denied.append(f"{path}: {denied}")
                continue
            try:
                if entry.kind == "dir":
                    path.mkdir(parents=True, exist_ok=True)
                    report.restored.append(str(path))
                elif entry.blob:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(blobs_dir / entry.blob, path)
                    report.restored.append(str(path))
            except OSError as exc:
                report.errors.append(f"{path}: {exc}")

        if remove_extra:
            report.removed = self._remove_extra(snapshot, report.errors)

        return report

    def _remove_extra(self, snapshot: Snapshot, errors: list[str]) -> list[str]:
        """Удалить файлы, появившиеся после снимка, внутри снятых каталогов."""
        known = {entry.path for entry in snapshot.entries}
        removed: list[str] = []
        seen: set[str] = set()
        for entry in snapshot.entries:
            if entry.kind != "dir":
                continue
            base = Path(entry.path)
            if not base.is_dir():
                continue
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if not self._ignored(d))
                current = Path(dirpath)
                for name in sorted(filenames):
                    if self._ignored(name):
                        continue
                    candidate = current / name
                    key = str(candidate)
                    if key in known or key in seen:
                        continue
                    seen.add(key)
                    denied = self._denied_reason(candidate)
                    if denied is not None:
                        continue
                    try:
                        candidate.unlink()
                        removed.append(key)
                    except OSError as exc:
                        errors.append(f"{key}: {exc}")
        return removed

    # ── удаление ──────────────────────────────────────────────────

    def prune(self, keep: Optional[int] = None) -> list[str]:
        """Удалить старые снимки, оставив ``keep`` последних (идемпотентно)."""
        limit = self.max_entries if keep is None else max(0, int(keep))
        rows = self._read_index()
        if len(rows) <= limit:
            return []
        survivors, dropped = rows[:limit], rows[limit:]
        for row in dropped:
            shutil.rmtree(self.dir / str(row.get("id")), ignore_errors=True)
        self._write_json(self.dir / INDEX_NAME, {"snapshots": survivors})
        return [str(row.get("id")) for row in dropped]
