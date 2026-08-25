"""Декларативный профиль модельного провайдера.

Профиль описывает всё про провайдера: имя, режим API, псевдонимы,
endpoints, тип аутентификации и переопределяемые хуки. Профиль декларативен:
он НЕ владеет построением клиента, ротацией ключей или стримингом — это
остаётся на цикле агента и транспорте.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

#: Режимы API, которые умеет ядро.
API_MODES = (
    "chat_completions",
    "codex_responses",
    "anthropic_messages",
    "bedrock_converse",
    "codex_app_server",
)

#: Типы аутентификации.
AUTH_TYPES = (
    "api_key",
    "oauth_device_code",
    "oauth_external",
    "copilot",
    "aws_sdk",
)

# Типы хуков (по умолчанию no-op / pass-through).
MessagesHook = Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
ExtraBodyHook = Callable[[dict[str, Any]], dict[str, Any]]
ApiKwargsHook = Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]
FetchModelsHook = Callable[[], Optional[list[str]]]


@dataclass
class ProviderProfile:
    """Декларативное описание провайдера."""

    name: str
    api_mode: str = "chat_completions"
    aliases: list[str] = field(default_factory=list)
    display_name: Optional[str] = None
    description: Optional[str] = None
    signup_url: Optional[str] = None
    #: Имена переменных окружения для ключей.
    env_vars: list[str] = field(default_factory=list)
    base_url: Optional[str] = None
    models_url: Optional[str] = None
    auth_type: str = "api_key"
    supports_health_check: bool = False
    supports_vision: bool = False
    supports_vision_tool_messages: bool = False
    supports_prompt_cache_key: bool = False
    fallback_models: list[str] = field(default_factory=list)
    hostname: Optional[str] = None
    default_headers: dict[str, str] = field(default_factory=dict)
    #: None = использовать дефолт вызывающего;
    #: спец-значение ``NO_TEMPERATURE`` = не слать параметр вовсе.
    fixed_temperature: Optional[float] = None
    default_max_tokens: Optional[int] = None
    default_aux_model: Optional[str] = None

    #: Хуки (по умолчанию no-op/pass-through).
    prepare_messages: Optional[MessagesHook] = None
    build_extra_body: Optional[ExtraBodyHook] = None
    build_api_kwargs_extras: Optional[ApiKwargsHook] = None
    fetch_models: Optional[FetchModelsHook] = None

    def __post_init__(self) -> None:
        if self.api_mode not in API_MODES:
            raise ValueError(f"Неизвестный режим API: {self.api_mode!r}")
        if self.auth_type not in AUTH_TYPES:
            raise ValueError(f"Неизвестный тип аутентификации: {self.auth_type!r}")
        if self.display_name is None:
            self.display_name = self.name

    def matches(self, name_or_alias: str) -> bool:
        """Совпадение по имени или псевдониму."""
        return name_or_alias == self.name or name_or_alias in self.aliases


#: Специальное значение: не отправлять параметр температуры вовсе.
NO_TEMPERATURE = "__no_temperature__"
