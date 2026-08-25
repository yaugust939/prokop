"""Подсистема субагентов и делегирования (обвес).

Реализовано по ``specs/subagents`` без обращения к эталону. Состав: бюджет
итераций субагента, роли и глубина вложенности, инструмент делегирования,
реестр активных субагентов, очередь завершений, изоляция ребёнка, потолок
одновременных детей.
"""

from prokop.subagents.budget import IterationBudget
from prokop.subagents.config import SubagentsConfig
from prokop.subagents.engine import DelegationEngine, consolidate_batch_results
from prokop.subagents.isolation import (
    BLOCKED_TOOL_NAMES,
    build_child_system_prompt,
    filter_child_tools,
)
from prokop.subagents.model import (
    SubagentRecord,
    SubagentResult,
    SubagentStatus,
    new_subagent_id,
)
from prokop.subagents.queue import CompletionQueue
from prokop.subagents.registry import RegistrySaturatedError, SubagentRegistry
from prokop.subagents.roles import (
    DepthError,
    Role,
    RoleError,
    normalize_max_depth,
    resolve_role,
    validate_depth,
)
from prokop.subagents.tool import (
    DELEGATION_TOOL_NAME,
    build_delegation_handler,
    delegation_tool_schema,
    make_delegation_tool,
)

__all__ = [
    "IterationBudget",
    "SubagentsConfig",
    "DelegationEngine",
    "consolidate_batch_results",
    "BLOCKED_TOOL_NAMES",
    "build_child_system_prompt",
    "filter_child_tools",
    "SubagentRecord",
    "SubagentResult",
    "SubagentStatus",
    "new_subagent_id",
    "CompletionQueue",
    "RegistrySaturatedError",
    "SubagentRegistry",
    "DepthError",
    "Role",
    "RoleError",
    "normalize_max_depth",
    "resolve_role",
    "validate_depth",
    "DELEGATION_TOOL_NAME",
    "build_delegation_handler",
    "delegation_tool_schema",
    "make_delegation_tool",
]
