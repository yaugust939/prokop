"""Обнаружение навыков.

Локальное обнаружение — сканирование каталогов (встроенные,
пользовательские, проектные) с кэшем по сигнатуре mtime. Навыки
фильтруются по платформе и списку отключённых.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from prokop.logging_setup import get_logger
from prokop.skills.model import SKILL_FILENAME, Skill, parse_skill_file

log = get_logger("skills.discovery")

#: Время жизни кэша обнаружения, секунд.
CACHE_TTL_SECONDS = 30.0

#: Соответствие имён платформ навыка текущей ОС.
_PLATFORM_ALIASES = {
    "windows": ("windows",),
    "macos": ("darwin",),
    "linux": ("linux",),
}


@dataclass
class SkillStore:
    """Один каталог навыков с меткой происхождения."""

    path: Path
    provenance: str = "user"
    #: Навыки считаются проектными.
    is_project: bool = False


class _CacheEntry:
    def __init__(self, signature: float, skills: list[Skill]) -> None:
        self.signature = signature
        self.skills = skills
        self.created_at = time.monotonic()


def _dir_signature(path: Path) -> float:
    """Сигнатура каталога: максимум mtime файлов навыков."""
    latest = 0.0
    for skill_file in path.glob(f"**/{SKILL_FILENAME}"):
        latest = max(latest, skill_file.stat().st_mtime)
    return latest


def _platform_ok(platforms: list[str]) -> bool:
    """Проходит ли навык фильтр платформы."""
    if not platforms:
        return True
    current = platform.system().lower()
    for entry in platforms:
        aliases = _PLATFORM_ALIASES.get(entry.lower(), (entry.lower(),))
        if current in aliases:
            return True
    return False


def discover_skills(
    stores: list[SkillStore],
    *,
    disabled: Optional[list[str]] = None,
    trusted_projects: Optional[set[str]] = None,
    cache: Optional[dict[str, _CacheEntry]] = None,
) -> list[Skill]:
    """Найти навыки во всех каталогах.

    Ненадёжные проектные навыки (каталог не в ``trusted_projects``)
    пропускаются. Результат кэшируется по сигнатуре каталога.
    """
    disabled_set = set(disabled or [])
    trusted = trusted_projects or set()
    results: list[Skill] = []
    local_cache = cache if cache is not None else {}

    for store in stores:
        if not store.path.exists():
            continue
        if store.is_project and str(store.path) not in trusted:
            log.warning("Проектные навыки %s в карантине: каталог не доверен", store.path)
            continue
        signature = _dir_signature(store.path)
        entry = local_cache.get(str(store.path))
        if entry and entry.signature == signature and (time.monotonic() - entry.created_at) < CACHE_TTL_SECONDS:
            candidates = entry.skills
        else:
            candidates = _scan(store)
            local_cache[str(store.path)] = _CacheEntry(signature, candidates)
        for skill in candidates:
            if skill.name in disabled_set:
                continue
            if not _platform_ok(skill.meta.platforms):
                continue
            results.append(skill)
    return results


def _scan(store: SkillStore) -> list[Skill]:
    """Просканировать один каталог навыков."""
    skills: list[Skill] = []
    for skill_file in sorted(store.path.glob(f"**/{SKILL_FILENAME}")):
        try:
            text = skill_file.read_text(encoding="utf-8")
            meta, _body = parse_skill_file(text)
        except Exception as exc:  # noqa: BLE001 — битый навык пропускается
            log.warning("Навык %s пропущен: %s", skill_file, exc)
            continue
        category = skill_file.parent.parent.name if skill_file.parent != store.path else ""
        skills.append(
            Skill(
                meta=meta,
                path=skill_file.parent,
                category=category,
                provenance=store.provenance,
            )
        )
    return skills
