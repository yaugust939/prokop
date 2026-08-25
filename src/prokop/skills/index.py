"""Индекс навыков в системном промпте.

Индекс строится из имени и обрезанного описания каждого навыка. После
любой мутации навыка индекс инвалидируется и пересобирается
(двухуровневый кэш: in-process + дисковый снапшот).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from prokop.skills.model import Skill

INDEX_SNAPSHOT_NAME = "skills_index.json"


class SkillsIndex:
    """Кэш индекса навыков."""

    def __init__(self, home: Optional[Path] = None) -> None:
        self._cached: Optional[str] = None
        self._generation = 0
        self.home = home

    def build(self, skills: list[Skill]) -> str:
        """Построить индекс (кэшируется до инвалидации)."""
        if self._cached is not None:
            return self._cached
        lines = []
        for skill in skills:
            lines.append(f"- {skill.name}: {skill.meta.index_description()}")
        text = "\n".join(lines)
        self._cached = text
        self._persist(text)
        return text

    def invalidate(self) -> None:
        """Инвалидировать кэш (после мутации навыка)."""
        self._cached = None
        self._generation += 1

    @property
    def generation(self) -> int:
        return self._generation

    def _persist(self, text: str) -> None:
        """Дисковый снапшот индекса (если задан домашний каталог)."""
        if self.home is None:
            return
        try:
            self.home.mkdir(parents=True, exist_ok=True)
            (self.home / INDEX_SNAPSHOT_NAME).write_text(
                json.dumps({"generation": self._generation, "index": text}, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass

    def load_snapshot(self) -> Optional[str]:
        """Загрузить дисковый снапшот, если он есть."""
        if self.home is None:
            return None
        path = self.home / INDEX_SNAPSHOT_NAME
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._cached = data.get("index")
            self._generation = int(data.get("generation", 0))
            return self._cached
        except (OSError, json.JSONDecodeError):
            return None
