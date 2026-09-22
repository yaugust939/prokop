"""Тесты оркестратора: платформенно-нейтральный запуск и сбор результата."""

from __future__ import annotations

import os
import re
from pathlib import Path

from prokop.orchestrator import collect as collect_mod
from prokop.orchestrator.collect import (
    _is_message_updated,
    _is_result_event,
    parse_ndjson_line,
)
from prokop.orchestrator.spawn import (
    SpawnConfig,
    _npm_candidates,
    build_command,
    find_opencode,
)


def test_find_opencode_honors_env_override(monkeypatch):
    monkeypatch.setenv("OPENCODE_BIN", "/custom/opencode")
    assert find_opencode() == "/custom/opencode"


def test_npm_candidates_prefer_package_binary():
    """Прямой бинарь пакета идёт раньше .CMD-обёртки из каталога npm."""
    candidates = _npm_candidates()
    assert candidates, "список кандидатов не должен быть пустым"

    names = ("opencode.exe", "opencode.cmd", "opencode") if os.name == "nt" \
        else ("opencode",)
    first_match = next(c for c in candidates if c.name in names)
    assert "node_modules" in first_match.parts, (
        "первым должен идти бинарь пакета, а не .CMD-обёртка"
    )


def test_npm_candidates_are_absolute():
    assert all(c.is_absolute() for c in _npm_candidates())


def test_build_command_passes_arguments_as_list():
    cfg = SpawnConfig(prompt="привет мир", project="C:/tmp/proj", auto=True)
    cmd = build_command(cfg, "opencode")
    assert isinstance(cmd, list)
    assert cmd[:3] == ["opencode", "run", "привет мир"]
    assert "--dir" in cmd and "--format" in cmd and "json" in cmd


def test_timeout_by_priority():
    assert SpawnConfig(prompt="x", project="p", priority="P0").timeout_seconds == 3600.0
    assert SpawnConfig(prompt="x", project="p", priority="P1").timeout_seconds == 1800.0
    assert SpawnConfig(prompt="x", project="p", priority="P2").timeout_seconds == 900.0


def test_parse_ndjson_tolerates_noise():
    assert parse_ndjson_line("") is None
    assert parse_ndjson_line("не json") is None
    assert parse_ndjson_line('\ufeff{"type": "result"}') == {"type": "result"}


def test_event_classification():
    assert _is_result_event({"type": "result"})
    assert not _is_result_event({"type": "message.updated"})
    assert _is_message_updated(
        {"type": "message.updated", "part": {"type": "text", "text": "a"}}
    )
    assert not _is_message_updated({"type": "message.updated", "part": {"type": "tool"}})


def test_orchestrator_module_has_no_personal_paths():
    """В модуле оркестратора не должно быть личных абсолютных путей."""
    package = Path(collect_mod.__file__).resolve().parent
    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    offenders = []
    for file in package.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(package)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"
