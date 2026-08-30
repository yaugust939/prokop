"""OpenAI function-calling схема инструмента ``computer_use``.

Один инструмент с ``action``-дискриминатором объединяет все операции
GUI-автоматизации. Схема компактна: модель платит за неё один раз на каждый
вызов, а разрешения (allow/ask) настраиваются для одного имени.
"""

from __future__ import annotations

from typing import Any, Dict

ACTIONS: tuple[str, ...] = (
    "capture",
    "click",
    "double_click",
    "right_click",
    "middle_click",
    "drag",
    "scroll",
    "type",
    "key",
    "set_value",
    "wait",
    "list_apps",
    "list_windows",
    "focus_app",
)

#: Режимы захвата.
CAPTURE_MODES: tuple[str, ...] = ("som", "vision", "ax")

#: Кнопки мыши.
BUTTONS: tuple[str, ...] = ("left", "right", "middle")

#: Модификаторы клавиш.
MODIFIERS: tuple[str, ...] = (
    "ctrl", "shift", "alt", "win", "cmd", "option", "super", "meta", "fn",
)

#: Направления скролла.
DIRECTIONS: tuple[str, ...] = ("up", "down", "left", "right")

#: Режимы доставки ввода.
DELIVERY_MODES: tuple[str, ...] = ("background", "foreground")

COMPUTER_USE_SCHEMA: Dict[str, Any] = {
    "name": "computer_use",
    "description": (
        "Управление графическим интерфейсом компьютера: захват экрана/окна "
        "(som — скриншот с нумерованными элементами + AX-дерево, vision — "
        "чистый скриншот, ax — только дерево доступности), клики и ввод по "
        "индексу элемента или координатам, скролл/драг, горячие клавиши, "
        "установка значений, управление окнами и фокусом. Рекомендуемый цикл: "
        "capture(mode='som') → click(element=N). По умолчанию ввод доставляется "
        "в фоне, не перехватывая курсор пользователя. Захват безопасен; "
        "остальные действия требуют подтверждения."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": list(ACTIONS),
                "description": "Операция для выполнения.",
            },
            # ── capture ──────────────────────────────────────────
            "mode": {
                "type": "string",
                "enum": list(CAPTURE_MODES),
                "description": "Режим захвата (по умолчанию som).",
            },
            "app": {
                "type": "string",
                "description": "Имя приложения или 'screen'/'desktop' для всего экрана.",
            },
            "pid": {
                "type": "integer",
                "description": "Точный процесс для захвата.",
            },
            "window_id": {
                "type": "integer",
                "description": "Точный идентификатор окна для захвата.",
            },
            "max_elements": {
                "type": "integer",
                "description": "Максимум элементов AX-дерева (по умолчанию 100, максимум 1000).",
                "default": 100,
                "minimum": 1,
                "maximum": 1000,
            },
            # ── таргетинг ────────────────────────────────────────
            "element": {
                "type": "integer",
                "description": "1-индексный номер элемента из последнего capture(mode='som').",
            },
            "coordinate": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
                "description": "Координаты [x, y] относительно окна.",
            },
            "button": {
                "type": "string",
                "enum": list(BUTTONS),
                "description": "Кнопка мыши (по умолчанию left).",
            },
            "modifiers": {
                "type": "array",
                "items": {"type": "string", "enum": list(MODIFIERS)},
                "description": "Модификаторы, удерживаемые при действии.",
            },
            # ── drag ─────────────────────────────────────────────
            "from_element": {"type": "integer", "description": "Индекс источника (drag)."},
            "to_element": {"type": "integer", "description": "Индекс цели (drag)."},
            "from_coordinate": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
                "description": "Координаты источника [x, y] (drag).",
            },
            "to_coordinate": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
                "description": "Координаты цели [x, y] (drag).",
            },
            # ── scroll ───────────────────────────────────────────
            "direction": {
                "type": "string",
                "enum": list(DIRECTIONS),
                "description": "Направление скролла.",
            },
            "amount": {
                "type": "integer",
                "description": "Число «кликов» колеса (по умолчанию 3).",
                "default": 3,
            },
            # ── ввод ─────────────────────────────────────────────
            "text": {"type": "string", "description": "Текст для ввода."},
            "keys": {
                "type": "string",
                "description": "Комбинация клавиш, например 'ctrl+s', 'return', 'escape'.",
            },
            "value": {
                "type": "string",
                "description": "Значение для set_value (селект/слайдер).",
            },
            "seconds": {
                "type": "number",
                "description": "Пауза в секундах (до 30).",
            },
            # ── focus ────────────────────────────────────────────
            "raise_window": {
                "type": "boolean",
                "description": "Поднять окно на передний план (фокус).",
                "default": False,
            },
            "delivery_mode": {
                "type": "string",
                "enum": list(DELIVERY_MODES),
                "description": "Режим доставки ввода: background (по умолчанию) или foreground.",
                "default": "background",
            },
            "capture_after": {
                "type": "boolean",
                "description": "Сделать свежий захват после действия.",
                "default": False,
            },
        },
        "required": ["action"],
    },
}


def get_computer_use_schema() -> Dict[str, Any]:
    """Вернуть схему инструмента в формате OpenAI function-calling."""
    return COMPUTER_USE_SCHEMA
