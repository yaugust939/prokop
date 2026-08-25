"""Гейтвей и абстракция платформ (обвес).

Подсистемы: ключ сессии, нормализованное событие, контракт адаптера,
авторизация отправителя, защита от параллельных ходов, кэш агентов по
сессиям, подготовка ответа, оркестратор гейтвея. Реализовано по
``specs/gateway`` и ``specs/messaging`` без обращения к эталону.
"""

from prokop.gateway.adapters import (
    ChatInfo,
    ErrorCategory,
    PlatformAdapter,
    SendError,
    SendResult,
    is_retryable,
)
from prokop.gateway.auth import AuthDecision, SenderGate, UnauthorizedPolicy
from prokop.gateway.cache import AgentCache
from prokop.gateway.engine import Gateway, HandleOutcome, HandleResult
from prokop.gateway.events import (
    CONTROL_NEW,
    CONTROL_RESET,
    CONTROL_STOP,
    Author,
    InboundEvent,
    MessageType,
    Source,
    parse_control_command,
)
from prokop.gateway.guard import Admit, SessionGuard, TurnMode
from prokop.gateway.keys import CHANNEL, DM, GROUP, session_key
from prokop.gateway.response import (
    mask_secrets,
    prepare_response,
    replace_provider_errors,
    sanitize_surrogates,
    truncate,
)

__all__ = [
    # keys
    "DM",
    "GROUP",
    "CHANNEL",
    "session_key",
    # events
    "Author",
    "Source",
    "MessageType",
    "InboundEvent",
    "parse_control_command",
    "CONTROL_STOP",
    "CONTROL_NEW",
    "CONTROL_RESET",
    # adapters
    "PlatformAdapter",
    "SendResult",
    "SendError",
    "ErrorCategory",
    "ChatInfo",
    "is_retryable",
    # auth
    "SenderGate",
    "AuthDecision",
    "UnauthorizedPolicy",
    # guard
    "SessionGuard",
    "TurnMode",
    "Admit",
    # cache
    "AgentCache",
    # response
    "sanitize_surrogates",
    "mask_secrets",
    "replace_provider_errors",
    "truncate",
    "prepare_response",
    # engine
    "Gateway",
    "HandleResult",
    "HandleOutcome",
]
