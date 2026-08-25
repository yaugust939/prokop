"""Коэрция аргументов по схеме.

Перед вызовом инструмента аргументы приводятся к схеме: строки — к
``integer``/``number``/``boolean``, скаляры — к массивам, если схема ждёт
массив, JSON-строки — к объектам/массивам (в том числе рекурсивно внутри
элементов). Это защита от моделей, возвращающих числа строками.
"""

from __future__ import annotations

import json
from typing import Any

_TRUTHY = {"true", "1", "yes", "on"}
_FALSY = {"false", "0", "no", "off"}


def _coerce_scalar(value: Any, type_name: str) -> Any:
    """Привести скаляр к типу схемы."""
    if type_name == "integer":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            try:
                return int(text)
            except ValueError:
                try:
                    return int(float(text))
                except ValueError:
                    return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    if type_name == "number":
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return value
        return value
    if type_name == "boolean":
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in _TRUTHY:
                return True
            if lowered in _FALSY:
                return False
        return value
    if type_name == "string" and not isinstance(value, str):
        return value
    return value


def _try_parse_json(value: str, expected_type: str) -> Any:
    """Распарсить JSON-строку в объект/массив ожидаемого типа."""
    stripped = value.strip()
    if not stripped:
        return value
    if expected_type == "object" and not stripped.startswith("{"):
        return value
    if expected_type == "array" and not stripped.startswith("["):
        return value
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return value
    if expected_type == "object":
        return parsed if isinstance(parsed, dict) else value
    if expected_type == "array":
        return parsed if isinstance(parsed, list) else value
    return parsed


def coerce_arguments(args: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    """Привести аргументы к схеме ``parameters``.

    Неизвестные свойства передаются как есть; ошибки коэрции не
    выбрасываются — значение остаётся прежним.
    """
    if not isinstance(args, dict):
        return args
    properties = (parameters or {}).get("properties", {}) or {}
    result: dict[str, Any] = {}
    for key, value in args.items():
        prop = properties.get(key)
        if not prop:
            result[key] = value
            continue
        result[key] = _coerce_value(value, prop)
    return result


def _coerce_value(value: Any, prop: dict[str, Any]) -> Any:
    """Коэрция одного значения по его схеме (рекурсивно для массивов)."""
    type_name = prop.get("type")
    if type_name == "array":
        items_schema = prop.get("items") or {}
        if not isinstance(value, list):
            if isinstance(value, str):
                parsed = _try_parse_json(value, "array")
                if isinstance(parsed, list):
                    value = parsed
                else:
                    value = [value]
            else:
                value = [value]
        return [_coerce_value(item, items_schema) for item in value]
    if type_name == "object":
        if isinstance(value, str):
            return _try_parse_json(value, "object")
        return value
    if type_name in ("integer", "number", "boolean") and isinstance(value, str):
        parsed = _try_parse_json(value, type_name)
        if parsed is not value and not isinstance(parsed, str):
            return parsed
    return _coerce_scalar(value, type_name or "")
