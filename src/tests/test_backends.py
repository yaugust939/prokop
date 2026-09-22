"""Тесты терминальных бэкендов (локальный)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

#: Интерпретатор текущего окружения: команды `python` на Linux нет.
PYTHON = f'"{sys.executable}"'

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
    result = backend.run(f'{PYTHON} -c "print(\'hello\')"')
    assert result.ok
    assert "hello" in result.output


def test_run_nonzero_exit_code(backend):
    result = backend.run(f'{PYTHON} -c "import sys; sys.exit(7)"')
    assert result.exit_code == 7
    assert not result.ok


def test_run_timeout_marks_timed_out(backend):
    result = backend.run(f'{PYTHON} -c "import time; time.sleep(30)"', timeout=0.5)
    assert result.timed_out
    assert not result.ok


def test_export_var_survives_spawns(backend):
    backend.export_var("MY_FLAG", "преодолено")
    result = backend.run(f'{PYTHON} -c "import os; print(os.environ.get(\'MY_FLAG\'))"')
    assert "преодолено" in result.output


def test_cwd_tracking(backend, tmp_path):
    subdir = tmp_path / "work" / "sub"
    subdir.mkdir(parents=True, exist_ok=True)
    backend.run(f"cd {subdir}")
    assert Path(backend.cwd).name == "sub"


def test_output_truncation_writes_dump(backend):
    script = f'{PYTHON} -c "import sys; [print(\'x\' * 80) for _ in range(10000)]"'
    backend.max_output_chars = 500
    result = backend.run(script)
    assert result.truncated
    assert result.dump_path is not None
    dump = Path(result.dump_path)
    assert dump.exists()
    # Полный вывод доступен в свалке.
    assert dump.read_text(encoding="utf-8").count("\n") > 100


# --- кодировка вывода (не зависит от локали) -------------------------------


def test_output_encoding_is_utf8_regardless_of_locale(backend):
    """Кириллица из дочернего процесса не искажается локале-зависимым декодером."""
    result = backend.run(f'{PYTHON} -c "print(\'преодолено\')"')
    assert result.output.strip() == "преодолено"


def test_output_encoding_survives_foreign_pythonioencoding(backend, monkeypatch):
    """Результат не зависит от кодировки, заданной вызывающей стороной."""
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    result = backend.run(f'{PYTHON} -c "print(\'преодолено\')"')
    assert result.output.strip() == "преодолено"

    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    result = backend.run(f'{PYTHON} -c "print(\'преодолено\')"')
    assert result.output.strip() == "преодолено"


def test_child_env_keeps_caller_priority():
    """Окружение процесса перекрывается, явные слои вызывающего кода — нет."""
    from prokop.backends.local import _child_env

    merged = _child_env(
        {"A": "1", "PYTHONIOENCODING": "cp866"},
        {"A": "2", "PYTHONUTF8": "0"},
        {"A": "3"},
    )
    assert merged["A"] == "3"                      # приоритет снимка сессии
    assert merged["PYTHONUTF8"] == "0"             # явное значение сохранено
    assert merged["PYTHONIOENCODING"] == "utf-8"   # ambient перекрыт UTF-8-режимом


def test_snapshot_value_overrides_utf8_default(backend):
    backend.export_var("PYTHONIOENCODING", "utf-8")
    result = backend.run(f'{PYTHON} -c "import os; print(os.environ.get(\'PYTHONIOENCODING\'))"')
    assert result.output.strip() == "utf-8"


def test_undecodable_bytes_do_not_break_command(backend):
    """Нераскодируемые байты заменяются, команда не падает."""
    script = (
        f'{PYTHON} -c "import sys; sys.stdout.buffer.write(b\'\\xff\\xfe broken\\n\')"'
    )
    result = backend.run(script)
    assert result.exit_code == 0
    assert "broken" in result.output
