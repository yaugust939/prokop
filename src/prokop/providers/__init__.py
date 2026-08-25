"""Слой модельных провайдеров."""

from prokop.providers.profile import ProviderProfile
from prokop.providers.registry import (
    ProviderRegistry,
    get_registry,
    resolve_provider_by_url,
)

__all__ = ["ProviderProfile", "ProviderRegistry", "get_registry", "resolve_provider_by_url"]
