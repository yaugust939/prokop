"""Тесты снимков состояния и отката."""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path
from typing import Any, Optional

import pytest

from prokop.checkpoints.store import (
    DEFAULT_IGNORES,
    CheckpointError,
    CheckpointStore,
)
from prokop.cli.commands import Context
from prokop.cli.main import EXIT_OK, EXIT_USAGE, main
from prokop.config import Config


def make_store(tmp_path: Path, **kwargs: Any) -> CheckpointStore:
    return CheckpointStore(tmp_path / "home", **kwargs)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# --- снимок ---------------------------------------------------------------


def test_snapshot_of_directory(tmp_path):
    workspace = tmp_path / "work"
    write(workspace / "a.txt", "первый")
    write(workspace / "sub" / "b.txt", "второй")

    store = make_store(tmp_path)
    snapshot = store.create([workspace], label="начало")

    assert snapshot.files == 2
    assert snapshot.label == "начало"
    assert snapshot.total_bytes > 0
    assert (store.dir / snapshot.id / "manifest.json").exists()
    assert len(store.list()) == 1
    assert store.list()[0]["files"] == 2


def test_snapshot_of_single_file(tmp_path):
    target = write(tmp_path / "one.txt", "содержимое")
    store = make_store(tmp_path)

    snapshot = store.create([target])
    target.write_text("изменено", encoding="utf-8")
    store.restore(snapshot.id)

    assert target.read_text(encoding="utf-8") == "содержимое"


def test_snapshot_with_cyrillic_and_spaces(tmp_path):
    target = write(tmp_path / "рабочая папка" / "файл с пробелом.txt", "привет")
    store = make_store(tmp_path)

    snapshot = store.create([target])
    target.unlink()
    store.restore(snapshot.id)

    assert target.read_text(encoding="utf-8") == "привет"


def test_snapshot_ids_are_unique(tmp_path):
    target = write(tmp_path / "f.txt", "x")
    store = make_store(tmp_path)

    first = store.create([target]).id
    second = store.create([target]).id
    assert first != second
    assert len(store.list()) == 2


def test_missing_path_is_skipped(tmp_path):
    target = write(tmp_path / "f.txt", "x")
    store = make_store(tmp_path)

    snapshot = store.create([tmp_path / "нет-такого", target])
    assert snapshot.files == 1


def test_snapshot_without_existing_paths_raises(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(CheckpointError):
        store.create([tmp_path / "нет-такого"])


# --- восстановление -------------------------------------------------------


def test_restore_returns_changed_file(tmp_path):
    workspace = tmp_path / "work"
    target = write(workspace / "a.txt", "до")
    store = make_store(tmp_path)
    snapshot = store.create([workspace])

    target.write_text("после", encoding="utf-8")
    report = store.restore(snapshot.id)

    assert target.read_text(encoding="utf-8") == "до"
    assert str(target) in report.restored


def test_restore_recreates_deleted_file(tmp_path):
    workspace = tmp_path / "work"
    target = write(workspace / "a.txt", "важно")
    store = make_store(tmp_path)
    snapshot = store.create([workspace])

    target.unlink()
    store.restore(snapshot.id)

    assert target.read_text(encoding="utf-8") == "важно"


def test_restore_keeps_extra_files_by_default(tmp_path):
    workspace = tmp_path / "work"
    write(workspace / "a.txt", "a")
    store = make_store(tmp_path)
    snapshot = store.create([workspace])

    extra = write(workspace / "new.txt", "новый")
    report = store.restore(snapshot.id)

    assert extra.exists()
    assert report.removed == []


def test_restore_removes_extra_files_on_request(tmp_path):
    workspace = tmp_path / "work"
    write(workspace / "a.txt", "a")
    write(workspace / "sub" / "b.txt", "b")
    store = make_store(tmp_path)
    snapshot = store.create([workspace])

    extra = write(workspace / "new.txt", "новый")
    extra_nested = write(workspace / "sub" / "new2.txt", "новый2")
    report = store.restore(snapshot.id, remove_extra=True)

    assert not extra.exists()
    assert not extra_nested.exists()
    assert str(extra) in report.removed
    assert (workspace / "a.txt").exists()


def test_restore_creates_safety_snapshot(tmp_path):
    workspace = tmp_path / "work"
    target = write(workspace / "a.txt", "до")
    store = make_store(tmp_path)
    snapshot = store.create([workspace])

    target.write_text("после", encoding="utf-8")
    report = store.restore(snapshot.id)

    assert report.safety_id is not None
    ids = [row["id"] for row in store.list()]
    assert report.safety_id in ids

    # Откат отката: восстановление из страховочного снимка возвращает «после».
    store.restore(report.safety_id)
    assert target.read_text(encoding="utf-8") == "после"


def test_restore_unknown_snapshot_raises_and_changes_nothing(tmp_path):
    workspace = tmp_path / "work"
    target = write(workspace / "a.txt", "до")
    store = make_store(tmp_path)

    with pytest.raises(CheckpointError):
        store.restore("нет-такого")
    assert target.read_text(encoding="utf-8") == "до"


def test_restore_report_has_errors_list(tmp_path):
    workspace = tmp_path / "work"
    write(workspace / "a.txt", "a")
    store = make_store(tmp_path)
    snapshot = store.create([workspace])
    report = store.restore(snapshot.id)
    assert report.errors == []
    assert report.to_dict()["checkpoint_id"] == snapshot.id


# --- пределы и игнорирование ---------------------------------------------


def test_service_directories_are_ignored(tmp_path):
    workspace = tmp_path / "work"
    write(workspace / "a.txt", "a")
    write(workspace / ".git" / "config", "git")
    write(workspace / "node_modules" / "pkg" / "index.js", "js")
    write(workspace / "__pycache__" / "x.pyc", "bin")

    store = make_store(tmp_path)
    snapshot = store.create([workspace])

    paths = [e.path for e in snapshot.entries]
    assert any(p.endswith("a.txt") for p in paths)
    assert not any(".git" in p for p in paths)
    assert not any("node_modules" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)


def test_extra_ignore_patterns_from_config(tmp_path):
    workspace = tmp_path / "work"
    write(workspace / "a.txt", "a")
    write(workspace / "secret.env", "секрет")

    store = CheckpointStore.from_config(tmp_path / "home", {"ignore": ["*.env"]})
    snapshot = store.create([workspace])

    paths = [e.path for e in snapshot.entries]
    assert any(p.endswith("a.txt") for p in paths)
    assert not any(p.endswith("secret.env") for p in paths)


def test_large_file_is_skipped_and_reported(tmp_path):
    workspace = tmp_path / "work"
    write(workspace / "small.txt", "ok")
    write(workspace / "big.bin", "x" * 500)

    store = make_store(tmp_path, max_file_bytes=100)
    snapshot = store.create([workspace])

    skipped = [e.path for e in snapshot.skipped]
    assert any(p.endswith("big.bin") for p in skipped)
    assert snapshot.summary()["skipped"] == 1
    assert snapshot.files == 1


def test_max_entries_prunes_oldest(tmp_path):
    target = write(tmp_path / "f.txt", "x")
    store = make_store(tmp_path, max_entries=2)

    ids = [store.create([target]).id for _ in range(4)]
    rows = store.list()

    assert len(rows) == 2
    assert [r["id"] for r in rows] == [ids[3], ids[2]]
    assert not (store.dir / ids[0]).exists()


def test_prune_is_idempotent(tmp_path):
    target = write(tmp_path / "f.txt", "x")
    store = make_store(tmp_path, max_entries=10)
    store.create([target])

    assert store.prune(5) == []
    assert store.prune(5) == []
    assert len(store.list()) == 1


def test_prune_removes_oldest(tmp_path):
    target = write(tmp_path / "f.txt", "x")
    store = make_store(tmp_path, max_entries=10)
    ids = [store.create([target]).id for _ in range(3)]

    removed = store.prune(1)
    assert removed == [ids[1], ids[0]]
    assert [r["id"] for r in store.list()] == [ids[2]]


def test_config_defaults():
    store = CheckpointStore.from_config(Path("/tmp/x"), None)
    assert store.enabled is True
    assert list(store.ignores) == list(DEFAULT_IGNORES)

    store = CheckpointStore.from_config(
        Path("/tmp/x"),
        {"enabled": False, "max_entries": 3, "max_file_bytes": 10},
    )
    assert store.enabled is False
    assert store.max_entries == 3
    assert store.max_file_bytes == 10


def test_config_roundtrip_keeps_checkpoints_section():
    config = Config.from_dict({"checkpoints": {"max_entries": 5}})
    assert config.checkpoints["max_entries"] == 5
    assert Config().checkpoints == {}


# --- инструмент агента ----------------------------------------------------


@pytest.fixture()
def registry(home):
    """Реестр с зарегистрированным инструментом `checkpoint`."""
    import prokop.checkpoints  # noqa: F401 — саморегистрация инструмента
    from prokop.checkpoints.tool import SCHEMA, TOOLSET, TOOL_NAME, handle_checkpoint
    from prokop.tools.registry import Tool, ToolRegistry

    reg = ToolRegistry()
    reg.register(
        Tool(
            name=TOOL_NAME,
            toolset=TOOLSET,
            schema=SCHEMA,
            handler=handle_checkpoint,
        )
    )
    return reg


def call_tool(registry, arguments: dict[str, Any]) -> dict[str, Any]:
    """Вызвать инструмент через диспетчер ядра (синхронно, для теста)."""
    from prokop.tools.dispatcher import handle_function_call

    raw = asyncio.run(
        handle_function_call("checkpoint", arguments, registry=registry)
    )
    return json.loads(raw)


def test_tool_create_list_restore_prune(home, registry):
    target = write(home / "work" / "a.txt", "до")

    created = call_tool(
        registry,
        {"action": "create", "paths": [str(home / "work")], "label": "тест"},
    )
    assert created["ok"] is True
    checkpoint_id = created["snapshot"]["id"]

    listed = call_tool(registry, {"action": "list"})
    assert listed["ok"] is True
    assert listed["snapshots"][0]["id"] == checkpoint_id

    target.write_text("после", encoding="utf-8")
    restored = call_tool(registry, {"action": "restore", "checkpoint_id": checkpoint_id})
    assert restored["ok"] is True
    assert target.read_text(encoding="utf-8") == "до"

    pruned = call_tool(registry, {"action": "prune", "keep": 1})
    assert pruned["ok"] is True


def test_tool_unknown_action(home, registry):
    payload = call_tool(registry, {"action": "wat"})
    assert payload["ok"] is False
    assert "неизвестное действие" in payload["error"]


def test_tool_create_without_paths(home, registry):
    assert call_tool(registry, {"action": "create"})["ok"] is False


def test_tool_restore_without_id(home, registry):
    assert call_tool(registry, {"action": "restore"})["ok"] is False


def test_toolset_is_registered():
    from prokop.tools.toolsets import resolve_toolset

    assert resolve_toolset("checkpoints") == ["checkpoint"]


# --- CLI ------------------------------------------------------------------


def make_ctx(tmp_path: Path, section: Optional[dict[str, Any]] = None) -> Context:
    def loader(home: Path) -> Config:
        config = Config()
        config.checkpoints = section or {}
        return config

    return Context(
        home=tmp_path / "home",
        profile="test",
        env={},
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        config_loader=loader,
    )


def out(ctx: Context) -> str:
    return ctx.stdout.getvalue()


def test_cli_checkpoints_flow(tmp_path):
    workspace = tmp_path / "work"
    target = write(workspace / "a.txt", "до")

    ctx = make_ctx(tmp_path)
    assert main(["checkpoints", "create", str(workspace), "--label", "тест"], context=ctx) == EXIT_OK
    assert "Снимок создан" in out(ctx)

    ctx2 = make_ctx(tmp_path)
    assert main(["--json", "checkpoints", "list"], context=ctx2) == EXIT_OK
    payload = json.loads(out(ctx2))
    assert payload["count"] == 1
    checkpoint_id = payload["snapshots"][0]["id"]

    target.write_text("после", encoding="utf-8")
    ctx3 = make_ctx(tmp_path)
    assert main(["checkpoints", "restore", checkpoint_id], context=ctx3) == EXIT_OK
    assert target.read_text(encoding="utf-8") == "до"
    assert "страховочный снимок" in out(ctx3)

    ctx4 = make_ctx(tmp_path)
    assert main(["checkpoints", "prune", "--keep", "1"], context=ctx4) == EXIT_OK


def test_cli_checkpoints_list_empty(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["checkpoints", "list"], context=ctx) == EXIT_OK
    assert "Снимков нет" in out(ctx)


def test_cli_checkpoints_unknown_snapshot(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["checkpoints", "restore", "нет-такого"], context=ctx) == EXIT_USAGE
    assert "не найден" in ctx.stderr.getvalue()


def test_cli_checkpoints_missing_path(tmp_path):
    ctx = make_ctx(tmp_path)
    code = main(["checkpoints", "create", str(tmp_path / "нет-такого")], context=ctx)
    assert code == EXIT_USAGE
    assert "путей" in ctx.stderr.getvalue()


def test_cli_checkpoints_requires_subcommand(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["checkpoints"], context=ctx) == EXIT_USAGE


def test_cli_checkpoints_works_without_key(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["checkpoints", "list"], context=ctx) == EXIT_OK


# --- гигиена --------------------------------------------------------------


def test_checkpoints_sources_have_no_personal_paths():
    import prokop.checkpoints as package

    root = Path(package.__file__).resolve().parent
    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    offenders = []
    for file in root.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(root)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"
