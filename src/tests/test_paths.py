"""Тесты единого резолвера путей и платформенной нейтральности ядра.

Инварианты (см. ``docs/PLATFORM_NOTES.md``):

- домашний каталог резолвится ровно одним способом — через ``prokop.home``;
- раскладка каталогов не зависит от ОС;
- в исходниках ядра нет личных абсолютных путей.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from prokop import home as home_mod
from prokop import paths


def test_paths_follow_home_root(home):
    """paths.* строятся от корня home и не изобретают свой корень."""
    root = home.resolve()
    assert paths.resolve_base().resolve() == root
    assert paths.resolve_home().resolve() == root / "test"
    assert paths.resolve_logs_path().resolve() == root / "test" / "logs"
    assert paths.resolve_database_path().resolve() == root / "test" / "sessions.db"
    assert paths.resolve_config_path().resolve() == root / "test" / "config.yaml"
    assert paths.ENV_HOME == home_mod.ENV_HOME == "PROKOP_HOME"


def test_paths_explicit_profile(home):
    assert paths.resolve_home("other").resolve() == home.resolve() / "other"


def test_paths_track_active_profile(home, monkeypatch):
    monkeypatch.setenv(home_mod.ENV_PROFILE, "second")
    home_mod.reset_cache()
    assert paths.resolve_home().resolve() == home.resolve() / "second"


def test_paths_module_is_platform_neutral():
    """paths.py не должен ветвиться по платформе (иначе раскладка разъедется)."""
    source = Path(paths.__file__).read_text(encoding="utf-8")
    for marker in ('sys.platform ==', 'platform.system(', 'LOCALAPPDATA', 'AgentCore'):
        assert marker not in source, f"в paths.py остался платформенный след: {marker}"


def test_reporter_global_tracker_is_portable(monkeypatch, tmp_path):
    """Трекер HERMES: HERMES_TRACKER → ~/.hermes/tasks.md, без личных путей."""
    from prokop.orchestrator import reporter

    monkeypatch.delenv(reporter.ENV_TRACKER, raising=False)
    assert reporter.global_tracker() == Path.home() / ".hermes" / "tasks.md"

    override = tmp_path / "t.md"
    monkeypatch.setenv(reporter.ENV_TRACKER, str(override))
    assert reporter.global_tracker() == override


def test_resolve_tracker_prefers_project(monkeypatch, tmp_path):
    from prokop.orchestrator import reporter

    monkeypatch.setenv(reporter.ENV_TRACKER, str(tmp_path / "global.md"))
    project = tmp_path / "proj"
    (project / ".hermes").mkdir(parents=True)
    local = project / ".hermes" / "tasks.md"
    local.write_text("# локальный трекер\n", encoding="utf-8")

    assert reporter.resolve_tracker(str(project)) == local
    assert reporter.resolve_tracker(str(tmp_path / "empty")) == tmp_path / "global.md"


@pytest.mark.parametrize(
    "pattern",
    [r"C:\\Users\\", r"C:/Users/", r"/home/[A-Za-z0-9._-]+/"],
)
def test_no_personal_absolute_paths_in_package(pattern):
    """В исходниках ядра не должно быть личных абсолютных путей."""
    package = Path(paths.__file__).resolve().parent
    rx = re.compile(pattern)
    offenders = []
    for file in package.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(package)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"
