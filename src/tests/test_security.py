"""Тесты слоя политик безопасности: правила, решения, аудит, интеграции."""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path
from typing import Any, Optional

import pytest
import yaml

from prokop.checkpoints.store import CheckpointStore
from prokop.cli.commands import Context
from prokop.cli.main import EXIT_OK, EXIT_USAGE, main
from prokop.config import Config
from prokop.security.audit import AuditLog
from prokop.security.policy import (
    SCOPE_NOTICE,
    Decision,
    SecurityPolicy,
    path_forms,
)
from prokop.tools.dispatcher import handle_function_call
from prokop.tools.registry import Tool, ToolRegistry

RUN_COMMAND_SCHEMA = {
    "description": "Выполнить команду",
    "parameters": {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
}


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_config(profile_home: Path, data: dict[str, Any]) -> None:
    profile_home.mkdir(parents=True, exist_ok=True)
    (profile_home / "config.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )


@pytest.fixture()
def policy_env(home):
    """Сбросить кэши политики и журнала до и после теста."""
    from prokop.security import audit as audit_mod
    from prokop.security import policy as policy_mod

    policy_mod.reset_policy()
    audit_mod.reset_audit()
    yield home
    policy_mod.reset_policy()
    audit_mod.reset_audit()


# --- правила команд -------------------------------------------------------


def test_no_section_behaves_as_before():
    policy = SecurityPolicy.from_config(None)
    assert policy.check_command("ls -la").decision is Decision.ALLOW
    assert policy.check_command("rm -rf ./build").decision is Decision.ASK
    assert policy.check_command("rm -rf /").decision is Decision.DENY
    assert policy.audit_enabled is True


def test_config_deny_blocks():
    policy = SecurityPolicy.from_config({"commands": {"deny": ["curl *"]}})
    decision = policy.check_command("curl https://example.com")
    assert decision.decision is Decision.DENY
    assert "запрещено политикой" in decision.reason


def test_config_allow_removes_approval():
    policy = SecurityPolicy.from_config({"commands": {"allow": ["rm -rf ./build*"]}})
    decision = policy.check_command("rm -rf ./build")
    assert decision.decision is Decision.ALLOW
    assert "разрешено политикой" in decision.reason


def test_deny_beats_allow():
    policy = SecurityPolicy.from_config(
        {"commands": {"deny": ["rm *"], "allow": ["rm -rf ./build"]}}
    )
    assert policy.check_command("rm -rf ./build").decision is Decision.DENY


def test_hardline_is_not_overridable():
    policy = SecurityPolicy.from_config(
        {"commands": {"allow": ["rm -rf /", "mkfs*", "shutdown*"]}}
    )
    assert policy.check_command("rm -rf /").decision is Decision.DENY
    assert policy.check_command("mkfs.ext4 /dev/sda1").decision is Decision.DENY
    assert policy.check_command("shutdown -h now").decision is Decision.DENY


def test_dangerous_command_needs_approval_with_label():
    policy = SecurityPolicy.from_config({})
    decision = policy.check_command("rm -rf ./build")
    assert decision.decision is Decision.ASK
    assert decision.label


def test_empty_command_allowed():
    assert SecurityPolicy.from_config({}).check_command("   ").decision is Decision.ALLOW


# --- правила путей --------------------------------------------------------


def test_path_allowed_without_rules(tmp_path):
    policy = SecurityPolicy.from_config({})
    assert policy.check_path(tmp_path / "a.txt").decision is Decision.ALLOW


def test_path_denied(tmp_path):
    target = tmp_path / "secrets" / "key.txt"
    policy = SecurityPolicy.from_config({"paths": {"deny": [f"{tmp_path.as_posix()}/secrets/*"]}})
    decision = policy.check_path(target)
    assert decision.decision is Decision.DENY
    assert "запрещено политикой" in decision.reason


def test_path_allow_overrides_deny(tmp_path):
    policy = SecurityPolicy.from_config(
        {
            "paths": {
                "deny": [f"{tmp_path.as_posix()}/secrets/*"],
                "allow": [f"{tmp_path.as_posix()}/secrets/readme.txt"],
            }
        }
    )
    assert policy.check_path(tmp_path / "secrets" / "key.txt").decision is Decision.DENY
    assert policy.check_path(tmp_path / "secrets" / "readme.txt").decision is Decision.ALLOW


def test_path_matching_is_normalized(tmp_path):
    policy = SecurityPolicy.from_config({"paths": {"deny": [f"{tmp_path.as_posix()}/секрет/*"]}})
    # Обратные слэши и относительная форма указывают на тот же путь.
    assert policy.check_path(str(tmp_path / "секрет" / "файл.txt")).decision is Decision.DENY
    assert policy.check_path(str(tmp_path / "секрет" / "файл.txt").replace("/", "\\")).decision is Decision.DENY


def test_path_forms_include_resolved(tmp_path):
    forms = path_forms(tmp_path / "a" / "b.txt")
    assert any(form.replace("\\", "/").endswith("a/b.txt") for form in forms)


# --- аудит ----------------------------------------------------------------


def test_audit_records_and_tails(tmp_path):
    audit = AuditLog(tmp_path, enabled=True)
    policy = SecurityPolicy.from_config({})

    audit.record(policy.check_command("ls"), source="test")
    audit.record(policy.check_command("rm -rf ./build"), source="test")

    rows = audit.tail(10)
    assert len(rows) == 2
    assert rows[0]["decision"] == "ask"  # хвост в обратном порядке
    assert rows[1]["decision"] == "allow"
    assert all("at" in row and "subject" in row for row in rows)


def test_audit_limit(tmp_path):
    audit = AuditLog(tmp_path, enabled=True)
    policy = SecurityPolicy.from_config({})
    for _ in range(5):
        audit.record(policy.check_command("ls"))

    assert len(audit.tail(2)) == 2
    assert audit.tail(0) == []


def test_audit_disabled_writes_nothing(tmp_path):
    audit = AuditLog(tmp_path, enabled=False)
    audit.record(SecurityPolicy.from_config({}).check_command("ls"))
    assert audit.tail(10) == []
    assert not audit.path().exists()


def test_audit_write_failure_does_not_raise(tmp_path):
    # Каталог журнала занят файлом — запись обязана провалиться тихо.
    audit = AuditLog(tmp_path, enabled=True)
    audit.path().parent.mkdir(parents=True, exist_ok=True)
    audit.path().parent.joinpath("logs").write_text("не каталог", encoding="utf-8")
    audit.record(SecurityPolicy.from_config({}).check_command("ls"))  # не бросает


def test_audit_tail_skips_broken_lines(tmp_path):
    audit = AuditLog(tmp_path, enabled=True)
    audit.path().parent.mkdir(parents=True, exist_ok=True)
    audit.path().write_text('{"decision": "allow"}\nне json\n\n', encoding="utf-8")
    rows = audit.tail(10)
    assert rows == [{"decision": "allow"}]


# --- диспетчер инструментов -----------------------------------------------


def make_registry(handler: Any = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="run_command",
            toolset="core",
            schema=RUN_COMMAND_SCHEMA,
            handler=handler or (lambda **kwargs: json.dumps({"ok": True})),
        )
    )
    return registry


def call_run_command(registry: ToolRegistry, command: str, approval: Any = None) -> dict[str, Any]:
    raw = asyncio.run(
        handle_function_call(
            "run_command", {"command": command}, registry=registry, approval=approval
        )
    )
    return json.loads(raw)


def test_dispatcher_denies_command_from_config(policy_env):
    write_config(policy_env / "test", {"security": {"commands": {"deny": ["curl *"]}}})
    registry = make_registry()
    payload = call_run_command(registry, "curl https://example.com")
    assert "запрещена политикой" in payload["error"]

    rows = AuditLog(policy_env / "test").tail(5)
    assert rows and rows[0]["decision"] == "deny"
    assert rows[0]["source"] == "tool:run_command"


def test_dispatcher_allows_whitelisted_dangerous_command(policy_env):
    write_config(policy_env / "test", {"security": {"commands": {"allow": ["rm -rf ./build"]}}})
    registry = make_registry()
    payload = call_run_command(registry, "rm -rf ./build")
    assert payload == {"ok": True}  # обработчик выполнен без подтверждения


def test_dispatcher_asks_for_dangerous_command(policy_env):
    write_config(policy_env / "test", {})
    registry = make_registry()
    payload = call_run_command(registry, "rm -rf ./build")
    assert "не одобрена" in payload["error"]


def test_dispatcher_respects_approval_callback(policy_env):
    write_config(policy_env / "test", {})
    registry = make_registry()

    async def approve(name: str, command: str) -> bool:
        return True

    payload = call_run_command(registry, "rm -rf ./build", approval=approve)
    assert payload == {"ok": True}


def test_dispatcher_blocks_hardline_even_with_allow(policy_env):
    write_config(policy_env / "test", {"security": {"commands": {"allow": ["rm -rf /"]}}})
    registry = make_registry()
    payload = call_run_command(registry, "rm -rf /")
    assert "запрещена политикой" in payload["error"]


# --- снимки и политика путей ---------------------------------------------


def test_checkpoint_store_denies_path_on_restore(tmp_path):
    workspace = tmp_path / "work"
    target = write(workspace / "a.txt", "до")

    store = CheckpointStore(tmp_path / "home")
    snapshot = store.create([workspace])

    denied_dir = tmp_path / "work"
    guarded = CheckpointStore(
        tmp_path / "home",
        path_guard=lambda path: "запрещено тестом" if str(path).startswith(str(denied_dir)) else None,
    )
    target.write_text("после", encoding="utf-8")
    report = guarded.restore(snapshot.id)

    assert target.read_text(encoding="utf-8") == "после"  # не изменён
    assert report.denied
    assert any("запрещено тестом" in item for item in report.denied)


def test_checkpoint_store_denies_path_on_create(tmp_path):
    allowed = write(tmp_path / "allowed" / "a.txt", "a")
    denied = write(tmp_path / "denied" / "b.txt", "b")

    store = CheckpointStore(
        tmp_path / "home",
        path_guard=lambda path: "нельзя" if str(path).startswith(str(tmp_path / "denied")) else None,
    )
    snapshot = store.create([tmp_path / "allowed", tmp_path / "denied"])

    paths = [entry.path for entry in snapshot.entries]
    assert any(p.endswith("a.txt") for p in paths)
    assert not any("b.txt" in p for p in paths)
    assert any("запрещено политикой" in (entry.skipped or "") for entry in snapshot.entries)
    assert denied.exists()  # сам файл не тронут


def test_checkpoint_store_raises_when_all_paths_denied(tmp_path):
    from prokop.checkpoints.store import CheckpointError

    write(tmp_path / "work" / "a.txt", "a")
    store = CheckpointStore(tmp_path / "home", path_guard=lambda path: "нельзя")
    with pytest.raises(CheckpointError):
        store.create([tmp_path / "work"])


# --- CLI ------------------------------------------------------------------


def make_ctx(tmp_path: Path, section: Optional[dict[str, Any]] = None) -> Context:
    def loader(home: Path) -> Config:
        config = Config()
        config.security = section or {}
        return config

    return Context(
        home=tmp_path / "home",
        profile="test",
        env={},
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        config_loader=loader,
    )


def out(ctx: Context) -> str:
    return ctx.stdout.getvalue()


def test_cli_security_show_lists_rules_and_scope(tmp_path):
    ctx = make_ctx(
        tmp_path,
        {"commands": {"deny": ["curl *"]}, "paths": {"deny": ["/etc/*"]}},
    )
    assert main(["security", "show"], context=ctx) == EXIT_OK
    text = out(ctx)
    assert "curl *" in text
    assert "/etc/*" in text
    assert SCOPE_NOTICE in text


def test_cli_security_check_dangerous(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["security", "check", "rm -rf ./build"], context=ctx) == EXIT_OK
    assert "ask" in out(ctx)


def test_cli_security_check_hardline(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["--json", "security", "check", "mkfs.ext4 /dev/sda1"], context=ctx) == EXIT_OK
    payload = json.loads(out(ctx))
    assert payload["decision"] == "deny"


def test_cli_security_check_does_not_execute(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["security", "check", "rm -rf /"], context=ctx) == EXIT_OK
    assert "deny" in out(ctx)


def test_cli_security_audit_records_check(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["security", "check", "ls"], context=ctx) == EXIT_OK

    ctx2 = make_ctx(tmp_path)
    assert main(["--json", "security", "audit", "--limit", "5"], context=ctx2) == EXIT_OK
    payload = json.loads(out(ctx2))
    assert payload["count"] == 1
    assert payload["records"][0]["subject"] == "ls"


def test_cli_security_audit_empty(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["security", "audit"], context=ctx) == EXIT_OK
    assert "Записей нет" in out(ctx)


def test_cli_security_requires_subcommand(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["security"], context=ctx) == EXIT_USAGE


def test_cli_security_works_without_key(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["security", "show"], context=ctx) == EXIT_OK


def test_config_roundtrip_keeps_security_section():
    config = Config.from_dict({"security": {"commands": {"deny": ["x"]}}})
    assert config.security["commands"]["deny"] == ["x"]
    assert Config().security == {}


# --- гигиена --------------------------------------------------------------


def test_security_sources_have_no_personal_paths():
    import prokop.security as package

    root = Path(package.__file__).resolve().parent
    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    offenders = []
    for file in root.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(root)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"
