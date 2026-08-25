"""Реестр модельных провайдеров.

Ленивое обнаружение из трёх мест (встроенные, пользовательские плагины,
плагины-точки входа) и приоритет «последний побеждает»: пользовательский
плагин того же имени заменяет встроенный, плагины-точки входа — низший
приоритет. Разрешение провайдера по URL использует точное сравнение
имени хоста (не подстроку) — против атак подмены хоста.
"""

from __future__ import annotations

import importlib
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from agent_core.logging_setup import get_logger
from agent_core.providers.profile import ProviderProfile

log = get_logger("providers.registry")


class ProviderRegistry:
    """Реестр профилей провайдеров с приоритетами."""

    #: Уровни приоритета (большее число = выше приоритет).
    #: Пользовательский плагин перекрывает встроенный; плагины-точки входа —
    #: низший приоритет и не могут захватить имя первопартийного провайдера.
    PRIORITY_ENTRYPOINT = 0
    PRIORITY_BUILTIN = 1
    PRIORITY_USER = 2

    def __init__(self) -> None:
        self._profiles: dict[str, ProviderProfile] = {}
        self._priorities: dict[str, int] = {}
        self._discovered = False

    # --- регистрация -------------------------------------------------

    def register(self, profile: ProviderProfile, priority: int = PRIORITY_BUILTIN) -> None:
        """Зарегистрировать профиль.

        При совпадении имени побеждает профиль с бо́льшим приоритетом:
        пользовательский (2) перекрывает встроенный (1), а плагины-точки
        входа (0) — низший приоритет и встроенное имя не захватывают.
        """
        name = profile.name
        existing = self._priorities.get(name)
        if existing is None or priority >= existing:
            self._profiles[name] = profile
            self._priorities[name] = priority

    def unregister(self, name: str) -> None:
        self._profiles.pop(name, None)
        self._priorities.pop(name, None)

    # --- обнаружение -------------------------------------------------

    def discover(self, user_modules: Iterable[Callable[[ProviderRegistry], None]] = ()) -> None:
        """Ленивое обнаружение: встроенные → пользовательские → точки входа.

        Пользовательские модули и плагины-точки входа саморегистрируются
        через вызов :meth:`register`. Обнаружение выполняется один раз.
        """
        if self._discovered:
            return
        from agent_core.providers import builtin

        builtin.register_builtin(self)

        for module in user_modules:
            try:
                module(self)
            except Exception as exc:  # noqa: BLE001 — сбой плагина не должен ронять ядро
                log.warning("Пользовательский модуль провайдеров не загрузился: %s", exc)

        for entry in _entry_points():
            try:
                plugin = entry.load()
                plugin(self)
            except Exception as exc:  # noqa: BLE001
                log.warning("Плагин-точка входа провайдеров не загрузился: %s", exc)

        self._discovered = True

    # --- запросы -----------------------------------------------------

    def get(self, name_or_alias: Optional[str]) -> Optional[ProviderProfile]:
        """Профиль по имени или псевдониму."""
        if not name_or_alias:
            return None
        direct = self._profiles.get(name_or_alias)
        if direct is not None:
            return direct
        for profile in self._profiles.values():
            if profile.matches(name_or_alias):
                return profile
        return None

    def list(self) -> list[ProviderProfile]:
        return list(self._profiles.values())

    def names(self) -> list[str]:
        return sorted(self._profiles)


def _entry_points() -> Iterable:
    """Точки входа ``agent_core.providers`` (если среда их предоставляет)."""
    try:
        from importlib.metadata import entry_points

        eps = entry_points()
        if hasattr(eps, "select"):
            return list(eps.select(group="agent_core.providers"))
        return list(eps.get("agent_core.providers", ()))  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 — среда без метаданных
        return ()


def resolve_provider_by_url(registry: ProviderRegistry, base_url: str) -> Optional[ProviderProfile]:
    """Определить провайдера по имени хоста из ``base_url``.

    Используется точное сравнение имени хоста (не вхождение подстроки),
    чтобы подмена хоста не перенаправляла на чужой провайдер.
    """
    if not base_url:
        return None
    host = (urlparse(base_url).hostname or "").lower()
    if not host:
        return None
    for profile in registry.list():
        if profile.hostname and profile.hostname.lower() == host:
            return profile
    return None


_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    """Глобальный реестр (создаётся лениво)."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
        _registry.discover()
    return _registry


def reset_registry() -> None:
    """Сбросить глобальный реестр (для тестов)."""
    global _registry
    _registry = None
