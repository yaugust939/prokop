"""Модель навыка и разбор метаданных.

Навык — каталог с обязательным ``SKILL.md`` и опциональными
подкаталогами ``references/``, ``templates/``, ``scripts/``, ``assets/``.
Метаданные читаются из YAML-frontmatter. Связанные файлы допускаются
только внутри разрешённых подкаталогов (без path traversal).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

SKILL_FILENAME = "SKILL.md"

#: Разрешённые подкаталоги для связанных файлов.
ALLOWED_SUBDIRS = ("references", "templates", "scripts", "assets")

#: Ограничения метаданных.
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
#: Длина описания в системном индексе.
INDEX_DESCRIPTION_LENGTH = 57


class SkillError(Exception):
    """Ошибка работы с навыком."""


@dataclass
class SkillMeta:
    """Метаданные навыка из frontmatter."""

    name: str
    description: str
    version: Optional[str] = None
    author: Optional[str] = None
    license: Optional[str] = None
    platforms: list[str] = field(default_factory=list)
    compatibility: Optional[str] = None
    prerequisites: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def index_description(self) -> str:
        """Описание, обрезанное для системного индекса."""
        text = (self.description or "").strip()
        if len(text) > INDEX_DESCRIPTION_LENGTH:
            return text[:INDEX_DESCRIPTION_LENGTH] + "…"
        return text


@dataclass
class Skill:
    """Навык: метаданные + путь к каталогу."""

    meta: SkillMeta
    path: Path
    category: str = ""
    provenance: str = "user"  # builtin | hub | agent | plugin
    pinned: bool = False
    use_count: int = 0
    view_count: int = 0
    patch_count: int = 0
    state: str = "active"  # active | stale | archived

    @property
    def name(self) -> str:
        return self.meta.name


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Отделить YAML-frontmatter от тела документа."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise SkillError(f"Неверный frontmatter: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillError("frontmatter должен быть словарём")
    return data, parts[2]


def parse_skill_file(text: str) -> tuple[SkillMeta, str]:
    """Разобрать содержимое ``SKILL.md`` на метаданные и тело.

    Имя обязательно и не длиннее 64 символов; описание обязательно и не
    длиннее 1024 символов.
    """
    data, body = _split_frontmatter(text)
    name = str(data.get("name") or "").strip()
    description = str(data.get("description") or "").strip()
    if not name:
        raise SkillError("frontmatter: отсутствует поле name")
    if len(name) > MAX_NAME_LENGTH:
        raise SkillError(f"name длиннее {MAX_NAME_LENGTH} символов")
    if not description:
        raise SkillError("frontmatter: отсутствует поле description")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise SkillError(f"description длиннее {MAX_DESCRIPTION_LENGTH} символов")
    meta = SkillMeta(
        name=name,
        description=description,
        version=data.get("version"),
        author=data.get("author"),
        license=data.get("license"),
        platforms=list(data.get("platforms") or []),
        compatibility=data.get("compatibility"),
        prerequisites=dict(data.get("prerequisites") or {}),
        metadata=dict(data.get("metadata") or {}),
    )
    return meta, body.strip()


def validate_related_path(skill_dir: Path, relative: str) -> Path:
    """Проверить путь связанного файла: только разрешённые подкаталоги."""
    parts = Path(relative).parts
    if not parts or parts[0] not in ALLOWED_SUBDIRS:
        raise SkillError(
            f"Файл должен быть внутри {'/'.join(ALLOWED_SUBDIRS)}"
        )
    target = (skill_dir / relative).resolve()
    if skill_dir.resolve() not in target.parents:
        raise SkillError("path traversal вне каталога навыка")
    return target
