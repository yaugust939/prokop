"""Навыки (процедурная память)."""

from agent_core.skills.model import Skill, SkillMeta, parse_skill_file, SkillError
from agent_core.skills.access import SkillsAccess
from agent_core.skills.discovery import discover_skills, SkillStore
from agent_core.skills.index import SkillsIndex
from agent_core.skills.curator import Curator

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
