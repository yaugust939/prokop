"""Инструменты доступа к навыкам (прогрессивное раскрытие).

Перечисление — только метаданные (экономно по токенам); просмотр — полный
текст ``SKILL.md`` или связанного файла; управление — создание,
редактирование, патч, удаление и запись/удаление связанных файлов.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Optional

from prokop.logging_setup import get_logger
from prokop.skills.discovery import SkillStore, discover_skills
from prokop.skills.model import (
    SKILL_FILENAME,
    SkillError,
    parse_skill_file,
    validate_related_path,
)

log = get_logger("skills.access")

MANAGE_ACTIONS = ("create", "edit", "patch", "delete", "write_file", "remove_file")


class SkillsAccess:
    """Доступ к навыкам внутри корневого каталога."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # --- перечисление ---------------------------------------------------

    def list_skills(self, category: Optional[str] = None) -> str:
        """Метаданные всех навыков (tier-1, без полного текста)."""
        skills = discover_skills([SkillStore(self.root, provenance="user")])
        if category:
            skills = [s for s in skills if s.category == category]
        payload = [
            {
                "name": s.name,
                "description": s.meta.description,
                "category": s.category,
                "tags": (s.meta.metadata.get("hermes", {}) or {}).get("tags", [])
                if isinstance(s.meta.metadata.get("hermes"), dict)
                else [],
                "has_files": any(p.name in ("references", "templates", "scripts", "assets") and p.is_dir() for p in s.path.iterdir()),
            }
            for s in skills
        ]
        return json.dumps(payload, ensure_ascii=False)

    # --- просмотр ---------------------------------------------------------

    def view(self, name: str, file_path: Optional[str] = None) -> str:
        """Полный текст навыка или конкретного связанного файла."""
        skill_dir = self._find_dir(name)
        if file_path:
            target = validate_related_path(skill_dir, file_path)
            if not target.exists():
                raise SkillError(f"Файл не найден: {file_path}")
            return target.read_text(encoding="utf-8")
        return (skill_dir / SKILL_FILENAME).read_text(encoding="utf-8")

    # --- управление --------------------------------------------------------

    def manage(
        self,
        action: str,
        name: str,
        *,
        content: Optional[str] = None,
        category: Optional[str] = None,
        file_path: Optional[str] = None,
        file_content: Optional[str] = None,
        old_string: Optional[str] = None,
        new_string: Optional[str] = None,
        replace_all: bool = False,
    ) -> str:
        """Выполнить операцию управления навыком."""
        if action not in MANAGE_ACTIONS:
            raise SkillError(f"Неизвестное действие: {action}")
        if action == "create":
            return self._create(name, content or "", category)
        if action == "edit":
            return self._edit(name, content or "")
        if action == "patch":
            return self._patch(name, old_string or "", new_string or "", replace_all)
        if action == "delete":
            return self._delete(name)
        if action == "write_file":
            return self._write_file(name, file_path or "", file_content or "")
        if action == "remove_file":
            return self._remove_file(name, file_path or "")

    # --- реализация операций ------------------------------------------------

    def _dir_for(self, name: str, category: Optional[str]) -> Path:
        base = self.root / category if category else self.root
        return base / name

    def _find_dir(self, name: str) -> Path:
        for candidate in self.root.glob(f"**/{name}/{SKILL_FILENAME}"):
            return candidate.parent
        raise SkillError(f"Навык не найден: {name}")

    def _create(self, name: str, content: str, category: Optional[str]) -> str:
        parse_skill_file(content)  # валидация метаданных
        target = self._dir_for(name, category)
        if target.exists():
            raise SkillError(f"Навык уже существует: {name}")
        target.mkdir(parents=True, exist_ok=True)
        (target / SKILL_FILENAME).write_text(content, encoding="utf-8")
        return json.dumps({"ok": True, "created": name}, ensure_ascii=False)

    def _edit(self, name: str, content: str) -> str:
        parse_skill_file(content)
        target = self._find_dir(name)
        (target / SKILL_FILENAME).write_text(content, encoding="utf-8")
        return json.dumps({"ok": True, "edited": name}, ensure_ascii=False)

    def _patch(self, name: str, old_string: str, new_string: str, replace_all: bool) -> str:
        if not old_string:
            raise SkillError("Патч требует old_string")
        target = self._find_dir(name) / SKILL_FILENAME
        text = target.read_text(encoding="utf-8")
        if old_string not in text:
            raise SkillError("old_string не найден в навыке")
        if not replace_all and text.count(old_string) > 1:
            raise SkillError("old_string встречается более одного раза; уточните контекст или включите replace_all")
        patched = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
        target.write_text(patched, encoding="utf-8")
        return json.dumps({"ok": True, "patched": name}, ensure_ascii=False)

    def _delete(self, name: str) -> str:
        target = self._find_dir(name)
        shutil.rmtree(target)
        return json.dumps({"ok": True, "deleted": name}, ensure_ascii=False)

    def _write_file(self, name: str, file_path: str, file_content: str) -> str:
        skill_dir = self._find_dir(name)
        target = validate_related_path(skill_dir, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file_content, encoding="utf-8")
        return json.dumps({"ok": True, "wrote": file_path}, ensure_ascii=False)

    def _remove_file(self, name: str, file_path: str) -> str:
        skill_dir = self._find_dir(name)
        target = validate_related_path(skill_dir, file_path)
        if not target.exists():
            raise SkillError(f"Файл не найден: {file_path}")
        target.unlink()
        return json.dumps({"ok": True, "removed": file_path}, ensure_ascii=False)
