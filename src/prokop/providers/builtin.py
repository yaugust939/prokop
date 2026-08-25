"""Встроенные профили провайдеров (декларативные).

Набор покрывает типичные режимы API. Профили декларативны и не содержат
клиентского кода. Любой провайдер может быть перекрыт пользовательским
плагином того же имени.
"""

from __future__ import annotations

from prokop.providers.profile import ProviderProfile
from prokop.providers.registry import ProviderRegistry


def register_builtin(registry: ProviderRegistry) -> None:
    """Зарегистрировать встроенные профили."""
    for profile in BUILTIN_PROFILES:
        registry.register(profile, ProviderRegistry.PRIORITY_BUILTIN)


#: Встроенные профили. Имена хостов — для разрешения провайдера по URL.
BUILTIN_PROFILES: list[ProviderProfile] = [
    ProviderProfile(
        name="openai-compatible",
        api_mode="chat_completions",
        aliases=["openai", "custom"],
        display_name="OpenAI-совместимый",
        env_vars=["OPENAI_API_KEY"],
        base_url="https://api.openai.com/v1",
        hostname="api.openai.com",
        supports_health_check=True,
        supports_vision=True,
        supports_vision_tool_messages=True,
        default_max_tokens=4096,
    ),
    ProviderProfile(
        name="anthropic-messages",
        api_mode="anthropic_messages",
        aliases=["anthropic"],
        display_name="Anthropic Messages",
        env_vars=["ANTHROPIC_API_KEY"],
        base_url="https://api.anthropic.com",
        hostname="api.anthropic.com",
        supports_health_check=True,
        supports_vision=True,
        supports_prompt_cache_key=True,
        default_max_tokens=8192,
    ),
    ProviderProfile(
        name="openrouter",
        api_mode="chat_completions",
        display_name="OpenRouter",
        env_vars=["OPENROUTER_API_KEY"],
        base_url="https://openrouter.ai/api/v1",
        hostname="openrouter.ai",
        supports_health_check=True,
        supports_vision=True,
        default_max_tokens=4096,
    ),
    ProviderProfile(
        name="deepseek",
        api_mode="chat_completions",
        display_name="DeepSeek",
        env_vars=["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com/v1",
        hostname="api.deepseek.com",
        supports_health_check=True,
        default_max_tokens=4096,
    ),
    ProviderProfile(
        name="ollama",
        api_mode="chat_completions",
        display_name="Ollama (локальный)",
        env_vars=[],
        base_url="http://localhost:11434/v1",
        hostname="localhost",
        supports_health_check=True,
        auth_type="api_key",
    ),
]
