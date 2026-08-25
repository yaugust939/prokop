"""Тесты навыков."""

from __future__ import annotations

import json
import time

import pytest

from prokop.skills.model import parse_skill_file, SkillError, validate_related_path
from prokop.skills.access import SkillsAccess
from prokop.skills.discovery import discover_skills, SkillStore
from prokop.skills.index import SkillsIndex
from prokop.skills.curator import Curator
from prokop.skills.model import Skill, SkillMeta

SKILL_TEXT = """---
name: demo-skill
description: Демонстрационный навык для тестов.
platforms: []
metadata:
  hermes:
    tags: [тест]
---
# Демо
Делает что-то полезное.
"""


def test_parse_skill_file_valid():
    meta, body = parse_skill_file(SKILL_TEXT)
    assert meta.name == "demo-skill"
    assert "Делает" in body
    assert meta.index_description().endswith(".")


def test_parse_skill_file_rejects_missing_name():
    with pytest.raises(SkillError):
        parse_skill_file("---\ndescription: без имени\n---\nтекст")


def test_parse_skill_file_name_limit():
    with pytest.raises(SkillError):
        parse_skill_file(f"---\nname: {'x' * 65}\ndescription: ок\n---\n")


def test_related_path_traversal_blocked(tmp_path):
    with pytest.raises(SkillError):
        validate_related_path(tmp_path, "../etc/passwd")
    with pytest.raises(SkillError):
        validate_related_path(tmp_path, "scripts/../../secret")


@pytest.fixture()
def access(tmp_path):
    return SkillsAccess(tmp_path / "skills")


def test_create_list_view_patch_delete(access):
    created = json.loads(access.manage("create", "demo-skill", content=SKILL_TEXT))
    assert created["ok"] is True

    listing = json.loads(access.list_skills())
    assert listing[0]["name"] == "demo-skill"

    text = access.view("demo-skill")
    assert "Демо" in text

    patched = json.loads(access.manage(
        "patch", "demo-skill",
        old_string="что-то полезное", new_string="ещё больше пользы",
    ))
    assert patched["ok"] is True
    assert "ещё больше пользы" in access.view("demo-skill")

    deleted = json.loads(access.manage("delete", "demo-skill"))
    assert deleted["ok"] is True
    assert json.loads(access.list_skills()) == []


def test_patch_requires_unique_match(access):
    access.manage("create", "dup", content="---\nname: dup\ndescription: d\n---\nодна и та же строка, одна и та же строка")
    with pytest.raises(SkillError):
        access.manage("patch", "dup", old_string="одна и та же строка", new_string="другое")
    ok = json.loads(access.manage("patch", "dup", old_string="одна и та же строка",
                                  new_string="другое", replace_all=True))
    assert ok["ok"] is True


def test_write_and_remove_related_file(access):
    access.manage("create", "demo-skill", content=SKILL_TEXT)
    access.manage("write_file", "demo-skill", file_path="scripts/run.sh", file_content="#!/bin/sh")
    text = access.view("demo-skill", file_path="scripts/run.sh")
    assert text.startswith("#!/bin/sh")
    access.manage("remove_file", "demo-skill", file_path="scripts/run.sh")
    with pytest.raises(SkillError):
        access.view("demo-skill", file_path="scripts/run.sh")


def test_discovery_filters_disabled_and_platform(tmp_path):
    access = SkillsAccess(tmp_path / "skills")
    access.manage("create", "demo-skill", content=SKILL_TEXT)
    store = SkillStore(tmp_path / "skills", provenance="user")
    found = discover_skills([store])
    assert {s.name for s in found} == {"demo-skill"}
    found = discover_skills([store], disabled=["demo-skill"])
    assert found == []


def test_index_invalidation(tmp_path):
    index = SkillsIndex(home=tmp_path)
    meta, _ = parse_skill_file(SKILL_TEXT)
    skill = Skill(meta=meta, path=tmp_path)
    first = index.build([skill])
    assert "demo-skill" in first
    index.invalidate()
    generation = index.generation
    index.build([skill])
    assert index.generation == generation


def test_curator_protects_builtin_and_pinned(tmp_path):
    curator = Curator(tmp_path / "skills")
    builtin = Skill(
        meta=SkillMeta(name="builtin-skill", description="d"),
        path=tmp_path / "skills" / "builtin-skill",
        provenance="builtin",
    )
    pinned = Skill(
        meta=SkillMeta(name="pinned-skill", description="d"),
        path=tmp_path / "skills" / "pinned-skill",
        provenance="agent",
        pinned=True,
    )
    assert curator._protected(builtin)
    assert curator._protected(pinned)
    assert curator.delete(pinned) is False
