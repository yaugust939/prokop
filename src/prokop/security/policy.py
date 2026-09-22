"""Политики безопасности: решения по командам и путям.

Слой политик управляет решениями ядра и его инструментов. Он **не** изолирует
процессы и файловую систему: команда, которую политика разрешила, действует в
пределах прав процесса. Границы слоя печатаются в инспекции (`security show`),
чтобы не создавать ложного чувства защищённости.

Приоритет правил для команд (первое совпадение выигрывает):

1. жёсткий блок-лист — запрет, не переопределяется настройками;
2. запрещающие шаблоны конфигурации — запрет;
3. разрешающие шаблоны конфигурации — разрешение (снимает подтверждение);
4. детектор опасных команд — подтверждение;
5. иначе — разрешение.

Для путей: запрещающие шаблоны дают запрет, разрешающие перекрывают запрет,
иначе путь разрешён.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from prokop.tools.safety import ApprovalDecision, classify_command, danger_label

#: Указание границ слоя (печатается в инспекции политики).
SCOPE_NOTICE = (
    "Слой политик управляет решениями ядра и инструментов. Он не изолирует "
    "процессы и файловую систему: разрешённая команда действует в пределах "
    "прав процесса."
)


class Decision(Enum):
    """Итоговое решение политики."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass
class PolicyDecision:
    """Решение по конкретному предмету (команде или пути)."""

    decision: Decision
    kind: str
    subject: str
    reason: str = ""
    label: Optional[str] = None

    @property
    def allowed(self) -> bool:
        return self.decision is Decision.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision.value,
            "kind": self.kind,
            "subject": self.subject,
            "reason": self.reason,
            "label": self.label,
        }


def _as_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    return ()


def _matches(value: str, patterns: Iterable[str]) -> bool:
    """Совпадение значения с шаблонами (без учёта регистра)."""
    text = str(value).strip().lower()
    for pattern in patterns:
        pat = str(pattern).strip().lower()
        if pat and fnmatch(text, pat):
            return True
    return False


def path_forms(path: str | os.PathLike[str]) -> list[str]:
    """Формы пути для сравнения: исходная, приведённая и разрешённая.

    Покрывает оба вида разделителей и относительные пути, чтобы запрет
    срабатывал независимо от того, как путь записан.
    """
    raw = str(path)
    forms = {raw, raw.replace("\\", "/"), raw.replace("/", os.sep)}
    try:
        resolved = str(Path(raw).expanduser().resolve())
    except (OSError, RuntimeError, ValueError):
        resolved = raw
    forms.update({resolved, resolved.replace("\\", "/")})
    return [form for form in forms if form]


def _path_matches(path: str | os.PathLike[str], patterns: Iterable[str]) -> bool:
    """Совпадение пути с шаблонами (нормализация разделителей и регистра)."""
    candidates = [form.replace("\\", "/").lower() for form in path_forms(path)]
    for pattern in patterns:
        pat = str(pattern).strip().replace("\\", "/").lower()
        if not pat:
            continue
        if any(fnmatch(candidate, pat) for candidate in candidates):
            return True
    return False


@dataclass
class SecurityPolicy:
    """Правила безопасности профиля."""

    command_deny: tuple[str, ...] = ()
    command_allow: tuple[str, ...] = ()
    path_deny: tuple[str, ...] = ()
    path_allow: tuple[str, ...] = ()
    audit_enabled: bool = True

    @classmethod
    def from_config(cls, section: Any) -> "SecurityPolicy":
        """Собрать политику из секции ``security`` конфигурации профиля."""
        data = section if isinstance(section, Mapping) else {}
        commands = data.get("commands")
        paths = data.get("paths")
        audit = data.get("audit")
        return cls(
            command_deny=_as_tuple((commands or {}).get("deny") if isinstance(commands, Mapping) else None),
            command_allow=_as_tuple((commands or {}).get("allow") if isinstance(commands, Mapping) else None),
            path_deny=_as_tuple((paths or {}).get("deny") if isinstance(paths, Mapping) else None),
            path_allow=_as_tuple((paths or {}).get("allow") if isinstance(paths, Mapping) else None),
            audit_enabled=bool((audit or {}).get("enabled", True)) if isinstance(audit, Mapping) else True,
        )

    # ── решения ───────────────────────────────────────────────────

    def check_command(self, command: str) -> PolicyDecision:
        """Решение по команде терминала."""
        text = (command or "").strip()
        if not text:
            return PolicyDecision(Decision.ALLOW, "command", text, "пустая команда")

        base = classify_command(text)
        if base is ApprovalDecision.BLOCKED:
            return PolicyDecision(
                Decision.DENY, "command", text, "жёсткий блок-лист (не переопределяется)"
            )
        if _matches(text, self.command_deny):
            return PolicyDecision(Decision.DENY, "command", text, "запрещено политикой профиля")
        if _matches(text, self.command_allow):
            return PolicyDecision(Decision.ALLOW, "command", text, "разрешено политикой профиля")
        if base is ApprovalDecision.NEEDS_APPROVAL:
            return PolicyDecision(
                Decision.ASK, "command", text, "опасная команда", danger_label(text)
            )
        return PolicyDecision(Decision.ALLOW, "command", text, "разрешено")

    def check_path(self, path: str | os.PathLike[str], *, mode: str = "write") -> PolicyDecision:
        """Решение по пути для операций самого ядра."""
        subject = str(path)
        if not subject:
            return PolicyDecision(Decision.ALLOW, "path", subject, "пустой путь")
        if _path_matches(subject, self.path_deny):
            if _path_matches(subject, self.path_allow):
                return PolicyDecision(Decision.ALLOW, "path", subject, "разрешено политикой профиля")
            return PolicyDecision(
                Decision.DENY, "path", subject, f"запрещено политикой профиля ({mode})"
            )
        return PolicyDecision(Decision.ALLOW, "path", subject, "разрешено")

    def describe(self) -> dict[str, Any]:
        """Представление правил для инспекции."""
        return {
            "commands": {"deny": list(self.command_deny), "allow": list(self.command_allow)},
            "paths": {"deny": list(self.path_deny), "allow": list(self.path_allow)},
            "audit": {"enabled": self.audit_enabled},
            "scope": SCOPE_NOTICE,
        }


_policy: Optional[SecurityPolicy] = None


def load_policy() -> SecurityPolicy:
    """Построить политику из конфигурации активного профиля."""
    try:
        from prokop.config import load_config
        from prokop.home import home_dir

        return SecurityPolicy.from_config(load_config(home_dir()).security)
    except Exception:  # noqa: BLE001 — отсутствие конфигурации не ошибка
        return SecurityPolicy()


def get_policy() -> SecurityPolicy:
    """Политика активного профиля (кэшируется)."""
    global _policy
    if _policy is None:
        _policy = load_policy()
    return _policy


def reset_policy() -> None:
    """Сбросить кэш политики (для тестов и смены конфигурации)."""
    global _policy
    _policy = None
