"""Инструмент ``computer_use``: регистрация и диспетчеризация.

Инструмент доступен только при рабочем бэкенде (``check_fn``): cua-driver
приоритетнее, иначе локальный Windows-бэкенд. Выбор переопределяется
переменной окружения ``PROKOP_GUI_BACKEND`` (``auto`` | ``cua`` | ``windows``).

Возврат: JSON-строка для текстовых результатов; мультимодальная обёртка
``_multimodal`` для захватов (текст + base64-изображение).
"""

from __future__ import annotations

import os
from typing import Any, Optional

from prokop.computer.backend import (
    ActionResult,
    CaptureResult,
    ComputerUseBackend,
    ComputerUseError,
)
from prokop.computer.capture import make_capture_result, make_multimodal
from prokop.computer.schema import ACTIONS, get_computer_use_schema
from prokop.logging_setup import get_logger
from prokop.tools.registry import register

log = get_logger("computer.tool")

#: Лимит результата инструмента (base64-изображения большие).
RESULT_LIMIT = 2_000_000

_BACKEND: Optional[ComputerUseBackend] = None


def _load_backend_class(name: str):
    if name == "cua":
        from prokop.computer.cua import CuaBackend

        return CuaBackend
    if name == "windows":
        from prokop.computer.windows import WindowsBackend

        return WindowsBackend
    raise ValueError(f"Неизвестный бэкенд GUI: {name}")


def get_backend() -> Optional[ComputerUseBackend]:
    """Вернуть активный бэкенд (singleton) или None, если ни один недоступен."""
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    mode = os.environ.get("PROKOP_GUI_BACKEND", "auto").strip().lower()
    candidates: list[str]
    if mode in ("cua", "windows"):
        candidates = [mode]
    else:
        candidates = ["cua", "windows"]
    for name in candidates:
        try:
            cls = _load_backend_class(name)
        except (ImportError, ValueError):
            continue
        try:
            if not cls.available():
                continue
            _BACKEND = cls()
            log.info("Активный GUI-бэкенд: %s", name)
            return _BACKEND
        except Exception:  # noqa: BLE001 — недоступный бэкенд пропускаем
            continue
    return None


def check_computer_use_requirements() -> bool:
    """Доступен ли инструмент: хотя бы один бэкенд готов."""
    from prokop.computer.cua import CuaBackend
    from prokop.computer.windows import WindowsBackend

    return CuaBackend.available() or WindowsBackend.available()


def _action_result(result: ActionResult, action: str) -> dict[str, Any]:
    """Упаковать результат действия в dict."""
    if result.ok:
        return {"ok": True, "action": action, "description": result.description}
    return {"ok": False, "action": action, "error": result.error or "неизвестная ошибка"}


async def _capture_after(backend: ComputerUseBackend, args: dict[str, Any], text: str):
    """Действие + свежий захват → мультимодальная обёртка."""
    capture = await _run_capture(backend, args)
    capture.text = (text + "\n\n" + capture.text).strip()
    return make_multimodal(capture)


async def _run_capture(backend: ComputerUseBackend, args: dict[str, Any]) -> CaptureResult:
    result = await backend.capture(
        mode=args.get("mode") or "som",
        app=args.get("app"),
        pid=args.get("pid"),
        window_id=args.get("window_id"),
        max_elements=args.get("max_elements") or 100,
    )
    if not isinstance(result, CaptureResult):
        raise ComputerUseError("Бэкенд вернул некорректный результат захвата")
    return make_capture_result(result, max_elements=args.get("max_elements") or 100,
                               som_overlay=(args.get("mode") or "som") == "som")


async def handle_computer_use(action: str, **kwargs: Any) -> str:
    """Диспетчер инструмента. Возвращает JSON-строку или ``_multimodal`` dict."""
    backend = get_backend()
    if backend is None:
        return '{"ok": false, "error": "GUI-бэкенд недоступен (нет cua-driver и стека windows)"}'

    if action not in ACTIONS:
        raise ValueError(f"Неизвестное действие: {action}. Допустимые: {', '.join(ACTIONS)}")

    capture_after = bool(kwargs.get("capture_after"))
    args = {k: v for k, v in kwargs.items() if k != "capture_after"}

    try:
        if action == "capture":
            return make_multimodal(await _run_capture(backend, args))

        if action == "click":
            result = await backend.click(
                element=kwargs.get("element"),
                coordinate=kwargs.get("coordinate"),
                button=kwargs.get("button") or "left",
                modifiers=kwargs.get("modifiers"),
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "double_click":
            result = await backend.double_click(
                element=kwargs.get("element"),
                coordinate=kwargs.get("coordinate"),
                modifiers=kwargs.get("modifiers"),
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "right_click":
            result = await backend.right_click(
                element=kwargs.get("element"),
                coordinate=kwargs.get("coordinate"),
                modifiers=kwargs.get("modifiers"),
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "middle_click":
            result = await backend.middle_click(
                element=kwargs.get("element"),
                coordinate=kwargs.get("coordinate"),
                modifiers=kwargs.get("modifiers"),
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "drag":
            result = await backend.drag(
                from_element=kwargs.get("from_element"),
                to_element=kwargs.get("to_element"),
                from_coordinate=kwargs.get("from_coordinate"),
                to_coordinate=kwargs.get("to_coordinate"),
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "scroll":
            result = await backend.scroll(
                direction=kwargs.get("direction") or "down",
                amount=int(kwargs.get("amount") or 3),
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "type":
            result = await backend.type_text(
                text=kwargs.get("text") or "",
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "key":
            result = await backend.key(
                keys=kwargs.get("keys") or "",
                delivery_mode=kwargs.get("delivery_mode") or "background",
            )
        elif action == "set_value":
            result = await backend.set_value(
                element=int(kwargs.get("element") or 0),
                value=kwargs.get("value") or "",
            )
        elif action == "wait":
            result = await backend.wait(seconds=float(kwargs.get("seconds") or 1))
        elif action == "list_apps":
            items = await backend.list_apps()
            return _json({"ok": True, "apps": items})
        elif action == "list_windows":
            items = await backend.list_windows()
            return _json({"ok": True, "windows": items})
        elif action == "focus_app":
            result = await backend.focus_app(
                app=kwargs.get("app") or "",
                raise_window=bool(kwargs.get("raise_window")),
            )
        else:  # pragma: no cover — action проверен выше
            raise ValueError(f"Неизвестное действие: {action}")

        payload = _action_result(result, action)
        if capture_after and result.ok:
            return await _capture_after(backend, args, payload["description"])
        return _json(payload)

    except ComputerUseError as exc:
        return _json({"ok": False, "action": action, "error": str(exc)})


def _json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


#: Регистрация инструмента при импорте модуля.
register(
    name="computer_use",
    toolset="gui",
    schema=get_computer_use_schema(),
    handler=handle_computer_use,
    check_fn=check_computer_use_requirements,
    result_limit=RESULT_LIMIT,
)
