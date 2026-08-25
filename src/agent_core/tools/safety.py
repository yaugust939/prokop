"""Разрешения для команд терминала.

Три уровня: жёсткий блок-лист (команды, не выполняемые никогда, даже в
режиме полного доверия), детектор опасных команд (требуется одобрение
пользователя) и пользовательский deny-лист по глоб-паттернам.
"""

from __future__ import annotations

import fnmatch
import re
from enum import Enum
from typing import Iterable

#: Решение по команде.
class ApprovalDecision(Enum):
    ALLOWED = "allowed"
    NEEDS_APPROVAL = "needs_approval"
    BLOCKED = "blocked"


#: Жёсткий блок-лист: никогда не выполняются.
HARDLINE_PATTERNS: tuple[str, ...] = (
    r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)+/(\s|$)",        # рекурсивное удаление корня
    r"\brm\s+-[a-zA-Z]*[rR][a-zA-Z]*\s+/(etc|usr|bin|sbin|boot|home)\b",
    r"\bmkfs\b",
    r"\bdd\s+.*\bof=/dev/",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",            # fork-bomb
    r"\bkill\s+-1\b",
    r"\bkillall\s+-1\b",
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r">\s*/dev/sda\b",
)

#: Опасные команды: требуется одобрение.
DANGEROUS_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)+", "рекурсивное удаление"),
    (r"\bchmod\s+(-R\s+)?777\b", "chmod 777"),
    (r"\|\s*(ba)?sh\b", "передача вывода в оболочку"),
    (r"\bcurl\b.*\|\s*(ba)?sh\b", "загрузка и исполнение скрипта"),
    (r"\bwget\b.*\|\s*(ba)?sh\b", "загрузка и исполнение скрипта"),
    (r"\beval\b", "eval"),
    (r"(rmv|sudo)\s+rm\s+-rf", "sudo rm -rf"),
    (r">\s*/etc/", "перезапись системного файла"),
    (r"\bbase64\s+-d\b", "обфускация через base64"),
    (r"\bgit\s+push\s+.*(--force|-f)\b", "принудительный push"),
    (r"\bDROP\s+DATABASE\b", "удаление базы данных"),
)

_compiled_hardline = tuple(re.compile(p, re.IGNORECASE) for p in HARDLINE_PATTERNS)
_compiled_dangerous = tuple((re.compile(p, re.IGNORECASE), label) for p, label in DANGEROUS_PATTERNS)


def classify_command(command: str, deny_patterns: Iterable[str] = ()) -> ApprovalDecision:
    """Классифицировать команду терминала.

    Порядок: жёсткий блок-лист → пользовательский deny-лист → детектор
    опасных команд → разрешено.
    """
    command = (command or "").strip()
    if not command:
        return ApprovalDecision.ALLOWED

    for pattern in _compiled_hardline:
        if pattern.search(command):
            return ApprovalDecision.BLOCKED

    lowered = command.lower()
    for glob in deny_patterns:
        if glob and fnmatch.fnmatch(lowered, glob.lower()):
            return ApprovalDecision.BLOCKED

    for pattern, _label in _compiled_dangerous:
        if pattern.search(command):
            return ApprovalDecision.NEEDS_APPROVAL

    return ApprovalDecision.ALLOWED


def danger_label(command: str) -> str | None:
    """Метка опасности для отображения пользователю."""
    for pattern, label in _compiled_dangerous:
        if pattern.search(command or ""):
            return label
    return None
