"""Куратор навыков (жизненный цикл).

Следит только за навыками, созданными агентом (происхождение ``agent``):
встроенные и хаб-навыки неприкосновенны. Максимально деструктивное
действие — архив (в ``.archive/``), никогда не удаление. Закреплённые
(pinned) навыки освобождены от авто-переходов; удаление закреплённого
навыка отклоняется.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Optional

from prokop.logging_setup import get_logger
from prokop.skills.model import Skill

log = get_logger("skills.curator")

#: Возраст активности, после которого навык считается устаревшим (секунд).
STALE_AFTER_SECONDS = 30 * 24 * 3600

ARCHIVE_DIRNAME = ".archive"


class Curator:
    """Куратор навыков в корневом каталоге."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.archive_dir = self.root / ARCHIVE_DIRNAME

    # --- правила -------------------------------------------------------

    def _protected(self, skill: Skill) -> bool:
        """Неприкосновенен ли навык для куратора."""
        if skill.provenance != "agent":
            return True
        if skill.pinned:
            return True
        return False

    def is_stale(self, skill: Skill, now: Optional[float] = None) -> bool:
        """Устарел ли навык по метрикам активности."""
        now = now if now is not None else time.time()
        skill_file = skill.path / "SKILL.md"
        if not skill_file.exists():
            return False
        last_activity = skill_file.stat().st_mtime
        return (now - last_activity) > STALE_AFTER_SECONDS

    # --- действия ---------------------------------------------------------

    def archive(self, skill: Skill) -> bool:
        """Архивировать устаревший навык агента (не удалять)."""
        if self._protected(skill):
            log.info("Навык %s защищён от архивации", skill.name)
            return False
        if not self.is_stale(skill):
            return False
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        target = self.archive_dir / skill.path.name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(skill.path), str(target))
        log.info("Навык %s архивирован", skill.name)
        return True

    def delete(self, skill: Skill) -> bool:
        """Удаление навыка; для закреплённых — отклоняется."""
        if skill.pinned:
            log.warning("Удаление закреплённого навыка %s отклонено", skill.name)
            return False
        if skill.path.exists():
            shutil.rmtree(skill.path)
            return True
        return False

    def run(self, skills: list[Skill]) -> list[str]:
        """Прогнать куратора по списку навыков; возвращает архивированные имена."""
        archived: list[str] = []
        for skill in skills:
            if self._protected(skill):
                continue
            if self.archive(skill):
                archived.append(skill.name)
        return archived
