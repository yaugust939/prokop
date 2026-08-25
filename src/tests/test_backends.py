"""Тесты терминальных бэкендов (локальный)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from prokop.backends.base import TerminalBackend
from prokop.backends.config import BackendConfig, resolve_backend, backend_config_from_dict
from prokop.backends.errors import InfrastructureError
from prokop.backends.local import LocalBackend
from prokop.backends.result import CommandResult, truncate_output
from prokop.backends.snapshot import SessionSnapshot, DEFAULT_EXCLUDED_VARS


# --- обрезка вывода -------------------------------------------------------


def test_truncate_output_short_unchanged():
    text, truncated = truncate_output("короткий вывод", max_chars=100)
    assert truncated is False
    assert text == "короткий вывод"


def test_truncate_output_head_tail_window():
    long_text = "".join(f"строка {i}\n" for i in range(1000))
    max_chars = 500
    text, truncated = truncate_output(long_text, max_chars=max_chars)
    assert truncated is True
    assert len(text) <= max_chars + 100  # маркер + небольшой запас
    assert text.startswith("строка 0")
    assert "строка 999" in text


# --- снимок сессии --------------------------------------------------------


def test_snapshot_roundtrip_and_atomic(tmp_path):
    snap = SessionSnapshot(tmp_path / "session.json")
    snap.set("FOO", "bar")
    snap.set("BAZ", "qux")
    loaded = snap.load()
    assert loaded == {"FOO": "bar", "BAZ": "qux"}
    # Файл приватный и читается повторно.
    snap2 = SessionSnapshot(tmp_path / "session.json")
    assert snap2.get("FOO") == "bar"


def test_snapshot_excludes_service_vars(tmp_path):
    snap = SessionSnapshot(tmp_path / "session.json")
    env = {"USER_VAR": "keep", "PROKOP_SESSION_ID": "secret", "_": "noise"}
    snap.save(env)
    loaded = snap.load()
    assert "USER_VAR" in loaded
    assert "PROKOP_SESSION_ID" not in loaded
    assert "_" not in loaded


# --- выбор бэкенда --------------------------------------------------------


def test_resolve_backend_local():
    backend = resolve_backend(BackendConfig(type="local"), snapshot_path="/tmp/x.json")
    assert isinstance(backend, TerminalBackend)
    assert backend.name == "local"


def test_resolve_backend_unknown_is_infra_error():
    with pytest.raises(InfrastructureError):
        resolve_backend(BackendConfig(type="ssh"))


def test_backend_config_from_dict():
    cfg = backend_config_from_dict({"type": "local", "workdir": "/tmp", "timeout": 5})
    assert cfg.type == "local"
    assert cfg.timeout == 5


# --- локальный бэкенд ------------------------------------------------------


@pytest.fixture()
def backend(tmp_path):
    return LocalBackend(
        workdir=str(tmp_path / "work"),
        snapshot_path=str(tmp_path / "session.json"),
        dump_dir=str(tmp_path / "dumps"),
    )


def test_run_prints_output(backend):
    result = backend.run('python -c "print(\'hello\')"')
    assert result.ok
    assert "hello" in result.output


def test_run_nonzero_exit_code(backend):
    result = backend.run('python -c "import sys; sys.exit(7)"')
    assert result.exit_code == 7
    assert not result.ok


def test_run_timeout_marks_timed_out(backend):
    result = backend.run('python -c "import time; time.sleep(30)"', timeout=0.5)
    assert result.timed_out
    assert not result.ok


def test_export_var_survives_spawns(backend):
    backend.export_var("MY_FLAG", "преодолено")
    result = backend.run('python -c "import os; print(os.environ.get(\'MY_FLAG\'))"')
    assert "преодолено" in result.output


def test_cwd_tracking(backend, tmp_path):
    subdir = tmp_path / "work" / "sub"
    subdir.mkdir(parents=True, exist_ok=True)
    backend.run(f"cd {subdir}")
    assert Path(backend.cwd).name == "sub"


def test_output_truncation_writes_dump(backend):
    script = 'python -c "import sys; [print(\'x\' * 80) for _ in range(10000)]"'
    backend.max_output_chars = 500
    result = backend.run(script)
    assert result.truncated
    assert result.dump_path is not None
    dump = Path(result.dump_path)
    assert dump.exists()
    # Полный вывод доступен в свалке.
    assert dump.read_text(encoding="utf-8").count("\n") > 100
