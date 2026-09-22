"""Слой политик безопасности.

- :mod:`prokop.security.policy` — правила для команд и путей, единое решение
  `allow` / `ask` / `deny`, приоритет правил;
- :mod:`prokop.security.audit` — журнал решений (JSONL, только добавление).

Границы слоя: политики управляют решениями ядра и его инструментов, но **не**
изолируют процессы и файловую систему (см. `SCOPE_NOTICE`).
"""

from __future__ import annotations

from prokop.security.audit import (
    AUDIT_FILENAME,
    DEFAULT_TAIL,
    AuditLog,
    get_audit,
    reset_audit,
)
from prokop.security.policy import (
    SCOPE_NOTICE,
    Decision,
    PolicyDecision,
    SecurityPolicy,
    get_policy,
    load_policy,
    path_forms,
    reset_policy,
)

__all__ = [
    "AUDIT_FILENAME",
    "DEFAULT_TAIL",
    "SCOPE_NOTICE",
    "AuditLog",
    "Decision",
    "PolicyDecision",
    "SecurityPolicy",
    "get_audit",
    "get_policy",
    "load_policy",
    "path_forms",
    "reset_audit",
    "reset_policy",
]
