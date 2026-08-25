"""Навыки (процедурная память)."""

from prokop.skills.model import Skill, SkillMeta, parse_skill_file, SkillError
from prokop.skills.access import SkillsAccess
from prokop.skills.discovery import discover_skills, SkillStore
from prokop.skills.index import SkillsIndex
from prokop.skills.curator import Curator

__all__ = [
    "Skill",
    "SkillMeta",
    "parse_skill_file",
    "SkillError",
    "SkillsAccess",
    "discover_skills",
    "SkillStore",
    "SkillsIndex",
    "Curator",
]
