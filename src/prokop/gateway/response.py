"""Подготовка ответа перед чат-поверхностями.

Финальный текст хода проходит: санитизацию суррогатов (непарные суррогатные
кодовые точки заменяются), маскировку секретов (API-ключи и токены известных
форматов), замену сырых ошибок провайдера на короткие безопасные формулировки
и обрезку до лимита платформы.
"""

from __future__ import annotations

import re
from typing import Optional

#: Маска, заменяющая обнаруженный секрет.
SECRET_MASK = "[REDACTED]"

#: Непарный высокий суррогат, за которым нет низкого, ИЛИ низкий без высокого.
_SURROGATE_RE = re.compile(
    r"[\ud800-\udbff](?![\udc00-\udfff])"  # высокий без низкого
    r"|(?<![\ud800-\udbff])[\udc00-\udfff]"  # низкий без высокого
)

#: Форматы секретов (порядок важен: специфичные — раньше общих).
_SECRET_PATTERNS = [
    r"sk-ant-[A-Za-z0-9_\-]{16,}",                 # Anthropic
    r"sk-proj-[A-Za-z0-9_\-]{16,}",                # OpenAI project key
    r"sk_live_[0-9A-Za-z]{16,}",                   # Stripe live
    r"ghp_[A-Za-z0-9]{36}",                        # GitHub personal token
    r"gho_[A-Za-z0-9]{36}",                        # GitHub OAuth token
    r"github_pat_[A-Za-z0-9_]{22,}",               # GitHub fine-grained
    r"AKIA[0-9A-Z]{16}",                           # AWS access key id
    r"xox[baprs]-[0-9A-Za-z\-]{10,}",              # Slack tokens
    r"sk-[A-Za-z0-9_\-]{16,}",                     # OpenAI / generic sk-
    r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b",            # Telegram bot token
    r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",  # JWT
    r"Bearer\s+[A-Za-z0-9._\-]{16,}",              # Bearer-токен
]

_SECRET_RE = re.compile("|".join(_SECRET_PATTERNS))

#: Сырые признаки ошибок провайдера → короткая безопасная формулировка.
_PROVIDER_ERRORS: list[tuple[str, str]] = [
    (r"rate.?limit|429|too many requests", "Превышен лимит запросов, попробуйте позже."),
    (r"overloaded|503|502|500", "Сервис временно перегружен, попробуйте позже."),
    (r"timeout|timed ?out", "Запрос превысил время ожидания."),
    (r"authentication|unauthorized|invalid api key|401|403", "Ошибка доступа к модели."),
    (r"quota|billing|insufficient|402", "Квота исчерпана."),
    (r"connection error|connection refused|dns|name resolution", "Не удалось связаться с сервисом модели."),
]


def sanitize_surrogates(text: str) -> str:
    """Заменить непарные суррогатные кодовые точки на U+FFFD.

    Корректные астральные символы (суррогатные пары) не затрагиваются.
    """
    if not text:
        return text
    return _SURROGATE_RE.sub("\ufffd", text)


def mask_secrets(text: str) -> str:
    """Заменить API-ключи и токены известных форматов маской."""
    if not text:
        return text
    return _SECRET_RE.sub(SECRET_MASK, text)


def replace_provider_errors(text: str) -> str:
    """Заменить сырые признаки ошибок провайдера короткими формулировками."""
    result = text
    for pattern, phrase in _PROVIDER_ERRORS:
        result = re.sub(pattern, phrase, result, flags=re.IGNORECASE)
    return result


def truncate(text: str, limit: int) -> str:
    """Обрезать текст до лимита (не разрывая корректных астральных пар)."""
    if limit is None or len(text) <= limit:
        return text
    return sanitize_surrogates(text[:limit])


def prepare_response(text: str, *, max_length: Optional[int] = None) -> str:
    """Подготовить финальный текст ответа к отправке в чат."""
    result = mask_secrets(text)
    result = replace_provider_errors(result)
    result = sanitize_surrogates(result)
    if max_length is not None:
        result = truncate(result, max_length)
    return result
