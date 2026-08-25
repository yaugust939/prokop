"""Тесты слоя провайдеров."""

from __future__ import annotations

from agent_core.providers.profile import ProviderProfile, API_MODES
from agent_core.providers.registry import (
    ProviderRegistry,
    resolve_provider_by_url,
)


def _profile(name: str, **kwargs) -> ProviderProfile:
    return ProviderProfile(name=name, **kwargs)


def test_profile_rejects_unknown_api_mode():
    try:
        _profile("x", api_mode="nonexistent")
    except ValueError:
        pass
    else:
        raise AssertionError("ожидался ValueError")


def test_registry_last_wins_user_over_builtin():
    reg = ProviderRegistry()
    reg.register(_profile("p1", display_name="builtin"), ProviderRegistry.PRIORITY_BUILTIN)
    reg.register(_profile("p1", display_name="user"), ProviderRegistry.PRIORITY_USER)
    assert reg.get("p1").display_name == "user"


def test_registry_entrypoint_loses_to_builtin():
    reg = ProviderRegistry()
    reg.register(_profile("p1", display_name="builtin"), ProviderRegistry.PRIORITY_BUILTIN)
    reg.register(_profile("p1", display_name="pip"), ProviderRegistry.PRIORITY_ENTRYPOINT)
    assert reg.get("p1").display_name == "builtin"


def test_registry_lookup_by_alias():
    reg = ProviderRegistry()
    reg.register(_profile("main", aliases=["alias1", "alias2"]))
    assert reg.get("alias2").name == "main"
    assert reg.get("missing") is None


def test_resolve_provider_by_url_exact_hostname():
    reg = ProviderRegistry()
    reg.register(_profile("exact", hostname="api.example.com"))
    found = resolve_provider_by_url(reg, "https://api.example.com/v1")
    assert found is not None and found.name == "exact"
    # Подмена хоста подстрокой не проходит (точное сравнение).
    spoof = resolve_provider_by_url(reg, "https://api.example.com.evil.com/v1")
    assert spoof is None


def test_builtin_discovery_and_aux_config():
    reg = ProviderRegistry()
    reg.discover()
    assert reg.get("openai-compatible") is not None
    assert "openai" in [a for p in reg.list() for a in p.aliases]
