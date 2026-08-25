"""Реестр инструментов и модель инструмента.

Инструмент — запись с именем, принадлежностью к набору, схемой
(OpenAI function-calling), обработчиком и метаданными. Модули с вызовом
регистрации на верхнем уровне обнаруживаются автоматически; ручной список
импортов не нужен. Обработчик обязан возвращать JSON-строку (единственное
структурное исключение — мультимодальная обёртка).
"""

from __future__ import annotations

import inspect
import json
import pkgutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from prokop.logging_setup import get_logger

log = get_logger("tools.registry")

#: Ключ в результате, означающий мультимодальную обёртку.
MULTIMODAL_FLAG = "_multimodal"

Handler = Callable[..., Any]
CheckFn = Callable[[], bool]


@dataclass
class Tool:
    """Запись инструмента в реестре."""

    name: str
    toolset: str
    schema: dict[str, Any]
    handler: Handler
    check_fn: Optional[CheckFn] = None
    requires_env: list[str] = field(default_factory=list)
    is_async: bool = False
    emoji: Optional[str] = None
    #: Лимит размера результата (символы).
    result_limit: int = 64000
    #: Динамический генератор переопределений схемы.
    schema_overrides: Optional[Callable[[], dict[str, Any]]] = None

    def is_available(self) -> bool:
        """Доступен ли инструмент: переменные окружения + ``check_fn``."""
        import os

        for var in self.requires_env:
            if not os.environ.get(var):
                return False
        if self.check_fn is not None:
            try:
                return bool(self.check_fn())
            except Exception:  # noqa: BLE001 — недоступность не должна ронять
                return False
        return True

    def openai_schema(self) -> dict[str, Any]:
        """Схема инструмента в формате OpenAI."""
        overrides = self.schema_overrides() if self.schema_overrides else {}
        function = {
            "name": self.name,
            "description": self.schema.get("description", ""),
            "parameters": self.schema.get("parameters", {"type": "object", "properties": {}}),
        }
        function.update({k: v for k, v in overrides.items() if k in function})
        return {"type": "function", "function": function}


class ToolRegistry:
    """Единый реестр инструментов."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._discovered_packages: set[str] = set()

    def register(self, tool: Tool, *, override: bool = False) -> None:
        """Зарегистрировать инструмент.

        Тенящая регистрация существующего имени без ``override`` отклоняется.
        """
        existing = self._tools.get(tool.name)
        if existing is not None and not override:
            log.warning(
                "Регистрация %s отклонена: имя уже занято набором %s",
                tool.name,
                existing.toolset,
            )
            return
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools)

    def by_toolset(self, toolset: str) -> list[Tool]:
        return [t for t in self._tools.values() if t.toolset == toolset]

    def discover_package(self, package: Any) -> None:
        """Автообнаружение: импорт модулей пакета, содержащих регистрацию.

        Импортируются все модули пакета; модули с вызовом регистрации на
        верхнем уровне саморегистрируются как побочный эффект импорта.
        """
        package_name = getattr(package, "__name__", str(package))
        if package_name in self._discovered_packages:
            return
        self._discovered_packages.add(package_name)
        package_path = getattr(package, "__path__", None)
        if package_path is None:
            return
        for module_info in pkgutil.iter_modules(list(package_path)):
            module_name = f"{package_name}.{module_info.name}"
            try:
                __import__(module_name)
            except Exception as exc:  # noqa: BLE001 — сбой модуля не роняет реестр
                log.warning("Модуль инструмента %s не импортирован: %s", module_name, exc)


_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Глобальный реестр инструментов."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry() -> None:
    """Сбросить глобальный реестр (для тестов)."""
    global _registry
    _registry = None


def register(
    name: str,
    toolset: str,
    schema: dict[str, Any],
    handler: Handler,
    *,
    check_fn: Optional[CheckFn] = None,
    requires_env: Optional[list[str]] = None,
    is_async: Optional[bool] = None,
    emoji: Optional[str] = None,
    result_limit: int = 64000,
    schema_overrides: Optional[Callable[[], dict[str, Any]]] = None,
    registry: Optional[ToolRegistry] = None,
) -> Tool:
    """Зарегистрировать инструмент на верхнем уровне модуля."""
    if is_async is None:
        is_async = inspect.iscoroutinefunction(handler)
    tool = Tool(
        name=name,
        toolset=toolset,
        schema=schema,
        handler=handler,
        check_fn=check_fn,
        requires_env=requires_env or [],
        is_async=is_async,
        emoji=emoji,
        result_limit=result_limit,
        schema_overrides=schema_overrides,
    )
    (registry or get_registry()).register(tool)
    return tool


def validate_result(result: Any) -> str:
    """Проверить контракт результата и вернуть его каноническую строку.

    Допустимы: JSON-строка либо мультимодальная обёртка (список
    контент-блоков с флагом). Любой другой тип — ошибка контракта.
    """
    if isinstance(result, str):
        try:
            json.loads(result)
            return result
        except json.JSONDecodeError as exc:
            raise TypeError(f"Результат инструмента — невалидный JSON: {exc}") from exc
    if isinstance(result, dict) and result.get(MULTIMODAL_FLAG):
        return json.dumps(result, ensure_ascii=False)
    raise TypeError("Результат инструмента должен быть JSON-строкой или мультимодальной обёрткой")
