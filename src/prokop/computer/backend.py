"""Контракты GUI-автоматизации: модели результата и абстрактный бэкенд.

Бэкенд — подключаемая реализация доступа к десктопу. Ядро работает только
с абстракцией ``ComputerUseBackend``; конкретные реализации живут в
``windows.py`` (локальный Windows) и ``cua.py`` (cua-driver через MCP).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class UIElement:
    """Элемент интерфейса из accessibility-дерева."""

    index: int
    name: str = ""
    control_type: str = ""
    role: str = ""
    value: Optional[str] = None
    #: Прямоугольник в координатах окна: (x, y, width, height).
    rect: Optional[tuple[int, int, int, int]] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "control_type": self.control_type,
            "role": self.role,
            "value": self.value,
            "rect": list(self.rect) if self.rect else None,
        }


@dataclass
class CaptureResult:
    """Результат захвата окна/экрана."""

    #: PNG-байты изображения (могут отсутствовать в режиме ax).
    image: Optional[bytes] = None
    mode: str = "som"
    elements: list[UIElement] = field(default_factory=list)
    total_elements: int = 0
    truncated_elements: int = 0
    text: str = ""
    #: Целевое окно (имя приложения или идентификатор), если задано.
    target: str = ""


@dataclass
class ActionResult:
    """Результат действия (клик, ввод, фокус и т.д.)."""

    ok: bool = True
    description: str = ""
    error: Optional[str] = None


class ComputerUseError(Exception):
    """Ошибка GUI-автоматизации (бэкенд, целевое окно, действие)."""


class ComputerUseBackend(abc.ABC):
    """Абстрактный бэкенд десктоп-автоматизации."""

    name: str = "abstract"

    @classmethod
    @abc.abstractmethod
    def available(cls) -> bool:
        """Доступен ли бэкенд в текущем окружении (без установки в ошибку)."""

    @abc.abstractmethod
    async def capture(
        self,
        *,
        mode: str = "som",
        app: Optional[str] = None,
        pid: Optional[int] = None,
        window_id: Optional[int] = None,
        max_elements: int = 100,
    ) -> CaptureResult:
        """Захватить экран/окно в режиме som/vision/ax."""

    @abc.abstractmethod
    async def click(
        self,
        *,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        button: str = "left",
        modifiers: Optional[list[str]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Клик по индексу элемента или координатам."""

    async def double_click(
        self,
        *,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        modifiers: Optional[list[str]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Двойной клик."""
        return await self.click(element=element, coordinate=coordinate, button="left",
                                modifiers=modifiers, delivery_mode=delivery_mode)

    async def right_click(
        self,
        *,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        modifiers: Optional[list[str]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Клик правой кнопкой."""
        return await self.click(element=element, coordinate=coordinate, button="right",
                                modifiers=modifiers, delivery_mode=delivery_mode)

    async def middle_click(
        self,
        *,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        modifiers: Optional[list[str]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Клик средней кнопкой."""
        return await self.click(element=element, coordinate=coordinate, button="middle",
                                modifiers=modifiers, delivery_mode=delivery_mode)

    @abc.abstractmethod
    async def drag(
        self,
        *,
        from_element: Optional[int] = None,
        to_element: Optional[int] = None,
        from_coordinate: Optional[list[int]] = None,
        to_coordinate: Optional[list[int]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Перетаскивание."""

    @abc.abstractmethod
    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 3,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Прокрутка."""

    @abc.abstractmethod
    async def type_text(
        self,
        *,
        text: str,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Ввод текста."""

    @abc.abstractmethod
    async def key(
        self,
        *,
        keys: str,
        delivery_mode: str = "background",
    ) -> ActionResult:
        """Отправка комбинации клавиш."""

    @abc.abstractmethod
    async def set_value(
        self,
        *,
        element: int,
        value: str,
    ) -> ActionResult:
        """Установка значения в селекте/слайдере без нативного меню."""

    @abc.abstractmethod
    async def wait(self, *, seconds: float) -> ActionResult:
        """Пауза (до 30 секунд)."""

    @abc.abstractmethod
    async def list_apps(self) -> list[dict[str, Any]]:
        """Список запущенных приложений."""

    @abc.abstractmethod
    async def list_windows(self) -> list[dict[str, Any]]:
        """Список окон."""

    @abc.abstractmethod
    async def focus_app(
        self,
        *,
        app: str,
        raise_window: bool = False,
    ) -> ActionResult:
        """Направить ввод в приложение (без поднятия окна по умолчанию)."""

    async def close(self) -> None:
        """Освободить ресурсы бэкенда (переопределяется при необходимости)."""
