"""Локальный Windows-бэкенд GUI-автоматизации.

Стек: ``mss`` (скриншоты), ``pyautogui`` (ввод), ``pywinauto`` (UIA-дерево
элементов), ``Pillow`` (SOM-оверлеи). Зависимости подключаются лениво, чтобы
отсутствие стека не ломало импорт пакета: ``available()`` решает, виден ли
инструмент.

Координаты: ``rect`` элементов и ``coordinate`` задаются в системе координат
захваченного изображения (0,0 — левый верхний угол скриншота).
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from prokop.computer.backend import (
    ActionResult,
    CaptureResult,
    ComputerUseBackend,
    ComputerUseError,
    UIElement,
)
from prokop.computer.capture import draw_som_overlay, make_capture_result
from prokop.logging_setup import get_logger

log = get_logger("computer.windows")

#: Максимум узлов UIA-дерева за один обход (защита от циклов и раздувания).
MAX_TREE_NODES = 800

_IMPORT_ERROR: Optional[str] = None
try:
    import mss  # type: ignore
    import pyautogui  # type: ignore

    pyautogui.FAILSAFE = True
    import pywinauto  # type: ignore
    from pywinauto import Desktop  # type: ignore
except Exception as exc:  # noqa: BLE001 — ловим любую ошибку стека
    _IMPORT_ERROR = str(exc)


def _is_windows() -> bool:
    import sys

    return sys.platform == "win32"


class WindowsBackend(ComputerUseBackend):
    """Реализация десктоп-автоматизации для Windows через mss/pyautogui/pywinauto."""

    name = "windows"

    def __init__(self) -> None:
        #: Смещение последнего захваченного окна (screen-left, screen-top).
        #: rect элементов в capture хранятся в координатах изображения
        #: (относительно окна), клики требуют screen-координат.
        self._last_offset: Optional[tuple[int, int]] = None

    @classmethod
    def available(cls) -> bool:
        if not _is_windows():
            return False
        return _IMPORT_ERROR is None

    # ── внутренние помощники ──────────────────────────────────────

    def _require(self) -> None:
        if _IMPORT_ERROR is not None:
            raise ComputerUseError(
                f"Стек локального бэкенда недоступен: {_IMPORT_ERROR}. "
                "Установите extra gui (mss, pyautogui, pywinauto, Pillow)."
            )

    @staticmethod
    def _normalize_modifiers(modifiers: Optional[list[str]]) -> list[str]:
        return [m.lower().replace("cmd", "win").replace("meta", "win")
                for m in (modifiers or [])]

    @staticmethod
    def _resolve_target(app: Optional[str]) -> Optional[tuple[int, int, int, int]]:
        """Найти прямоугольник окна (screen-координаты) по имени приложения."""
        if not app or app in ("screen", "desktop"):
            return None
        try:
            desktop = Desktop(backend="uia")
            windows = desktop.windows()
            for win in windows:
                title = (win.window_text() or "").lower()
                if app.lower() in title:
                    rect = win.rectangle()
                    return (rect.left, rect.top,
                            rect.right - rect.left, rect.bottom - rect.top)
        except Exception as exc:  # noqa: BLE001
            log.warning("Не удалось найти окно %r: %s", app, exc)
        return None

    @staticmethod
    def _collect_nodes(roots: list[Any], limit: int) -> list[tuple[UIElement, Any]]:
        """Обойти список корней (окон) и собрать (элемент, обёртка).

        Координаты элементов — относительно своего корневого окна. Индексы
        назначаются успешно добавленным элементам (с геометрией), с 1.
        """
        result: list[tuple[UIElement, Any]] = []
        visited = 0
        index = 1

        def visit(node: Any, root_rect: Any) -> int:
            nonlocal visited, index, result
            if visited >= limit:
                return index
            visited += 1
            try:
                ctrl_type = node.element_info.control_type or ""
                name = node.window_text() or ""
                if not name:
                    name = node.element_info.name or ""
                rect = node.rectangle()
                rx = max(0, rect.left - root_rect.left)
                ry = max(0, rect.top - root_rect.top)
                el = UIElement(
                    index=index,
                    name=str(name)[:120],
                    control_type=str(ctrl_type),
                    role=str(ctrl_type),
                    rect=(rx, ry, rect.width(), rect.height()),
                )
                result.append((el, node))
                index += 1
            except Exception:  # noqa: BLE001 — узел без геометрии пропускаем
                pass
            try:
                for child in node.children():
                    index = visit(child, root_rect)
                    if index >= limit:
                        break
            except Exception:  # noqa: BLE001
                pass
            return index

        for win in roots:
            try:
                wr = win.rectangle()
            except Exception:  # noqa: BLE001
                continue
            index = visit(win, wr)
            if index >= limit:
                break
        return result

    @staticmethod
    def _collect_pairs(desktop: Any, limit: int) -> list[tuple[UIElement, Any]]:
        """Собрать элементы всех окон desktop (pywinauto 0.6.x: дерево от окон)."""
        try:
            windows = desktop.windows()
        except Exception:  # noqa: BLE001
            windows = []
        return WindowsBackend._collect_nodes(windows, limit)

    @staticmethod
    def _walk_tree(wrapper: Any, limit: int) -> list[UIElement]:
        return [el for el, _ in WindowsBackend._collect_pairs(wrapper, limit)]

    # ── реализация контракта ──────────────────────────────────────

    async def capture(
        self,
        *,
        mode: str = "som",
        app: Optional[str] = None,
        pid: Optional[int] = None,
        window_id: Optional[int] = None,
        max_elements: int = 100,
    ) -> CaptureResult:
        self._require()
        target_rect = self._resolve_target(app)
        self._last_offset = (target_rect[0], target_rect[1]) if target_rect else None

        with mss.mss() as sct:
            if target_rect is not None:
                x, y, w, h = target_rect
                monitor = {"left": x, "top": y, "width": w, "height": h}
            else:
                monitor = sct.monitors[1]
            shot = sct.grab(monitor)
            from PIL import Image  # type: ignore

            import io

            img = Image.frombytes("RGB", shot.size, shot.rgb)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            image = buf.getvalue()

        elements: list[UIElement] = []
        if mode != "vision":
            try:
                desktop = Desktop(backend="uia")
                if window_id is not None:
                    win = desktop.window(handle=window_id)
                    elements = [
                        el for el, _ in self._collect_nodes([win], min(MAX_TREE_NODES, max_elements * 4))
                    ]
                else:
                    elements = self._walk_tree(desktop, min(MAX_TREE_NODES, max_elements * 4))
            except Exception as exc:  # noqa: BLE001
                log.warning("UIA-дерево недоступно: %s", exc)

        result = CaptureResult(
            image=image,
            mode=mode,
            elements=elements,
            target=app or "",
        )
        result = make_capture_result(result, max_elements=max_elements,
                                     som_overlay=(mode == "som"))
        return result

    async def click(
        self,
        *,
        element: Optional[int] = None,
        coordinate: Optional[list[int]] = None,
        button: str = "left",
        modifiers: Optional[list[str]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        self._require()
        x, y = self._coordinate_of(element, coordinate)
        mods = self._normalize_modifiers(modifiers)
        try:
            for m in mods:
                pyautogui.keyDown(m)
            pyautogui.click(x, y, button=_btn(button))
            for m in mods:
                pyautogui.keyUp(m)
            return ActionResult(description=f"click {button} at ({x},{y})")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    async def drag(
        self,
        *,
        from_element: Optional[int] = None,
        to_element: Optional[int] = None,
        from_coordinate: Optional[list[int]] = None,
        to_coordinate: Optional[list[int]] = None,
        delivery_mode: str = "background",
    ) -> ActionResult:
        self._require()
        x1, y1 = self._coordinate_of(from_element, from_coordinate)
        x2, y2 = self._coordinate_of(to_element, to_coordinate)
        try:
            pyautogui.moveTo(x1, y1)
            pyautogui.dragTo(x2, y2, duration=0.3, button="left")
            return ActionResult(description=f"drag ({x1},{y1}) → ({x2},{y2})")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    async def scroll(
        self,
        *,
        direction: str = "down",
        amount: int = 3,
        delivery_mode: str = "background",
    ) -> ActionResult:
        self._require()
        clicks = amount if direction in ("down", "right") else -amount
        try:
            pyautogui.scroll(clicks)
            return ActionResult(description=f"scroll {direction} ×{amount}")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    async def type_text(
        self,
        *,
        text: str,
        delivery_mode: str = "background",
    ) -> ActionResult:
        self._require()
        try:
            pyautogui.write(text, interval=0.01)
            return ActionResult(description=f"typed {len(text)} chars")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    async def key(
        self,
        *,
        keys: str,
        delivery_mode: str = "background",
    ) -> ActionResult:
        self._require()
        try:
            pyautogui.hotkey(*[k.strip() for k in keys.replace("+", " ").split()])
            return ActionResult(description=f"key {keys}")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    async def set_value(
        self,
        *,
        element: int,
        value: str,
    ) -> ActionResult:
        self._require()
        try:
            wrapper = self._element_wrapper(element)
            if wrapper is None:
                return ActionResult(ok=False, error=f"элемент {element} не найден")
            editable = wrapper.children().find_control(
                best_match=value,
                control_type="ListItem",
            ) or wrapper
            editable.set_edit_text(value)
            return ActionResult(description=f"set_value #{element} = {value}")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    async def wait(self, *, seconds: float) -> ActionResult:
        await asyncio.sleep(min(max(seconds, 0.0), 30.0))
        return ActionResult(description=f"waited {seconds}s")

    async def list_apps(self) -> list[dict[str, Any]]:
        self._require()
        out: list[dict[str, Any]] = []
        try:
            for win in Desktop(backend="uia").windows():
                title = win.window_text() or ""
                if not title:
                    continue
                try:
                    pid = win.process_id()
                except Exception:  # noqa: BLE001
                    pid = None
                out.append({"title": title, "pid": pid})
        except Exception as exc:  # noqa: BLE001
            log.warning("list_apps: %s", exc)
        return out

    async def list_windows(self) -> list[dict[str, Any]]:
        self._require()
        return await self.list_apps()

    async def focus_app(
        self,
        *,
        app: str,
        raise_window: bool = False,
    ) -> ActionResult:
        self._require()
        try:
            desktop = Desktop(backend="uia")
            win = desktop.window(best_match=app)
            if raise_window:
                win.set_focus()
            return ActionResult(description=f"focus {app}")
        except Exception as exc:  # noqa: BLE001
            return ActionResult(ok=False, error=str(exc))

    # ── координаты и элементы ─────────────────────────────────────

    def _coordinate_of(
        self,
        element: Optional[int],
        coordinate: Optional[list[int]],
    ) -> tuple[int, int]:
        if coordinate and len(coordinate) == 2:
            x, y = int(coordinate[0]), int(coordinate[1])
            if self._last_offset is not None:
                x += self._last_offset[0]
                y += self._last_offset[1]
            return x, y
        if element is not None:
            wrapper = self._element_wrapper(element)
            if wrapper is not None:
                try:
                    r = wrapper.rectangle()
                    cx = r.left + r.width() // 2
                    cy = r.top + r.height() // 2
                    return cx, cy
                except Exception:  # noqa: BLE001
                    pass
        raise ComputerUseError("Нужен element или coordinate для позиционирования")

    def _element_wrapper(self, index: int) -> Optional[Any]:
        """Найти UIA-обёртку по 1-индексному номеру элемента."""
        try:
            desktop = Desktop(backend="uia")
            for el, wrapper in self._collect_pairs(desktop, MAX_TREE_NODES):
                if el.index == index:
                    return wrapper
        except Exception:  # noqa: BLE001
            pass
        return None


def _btn(button: str) -> str:
    return {"left": "left", "right": "right", "middle": "middle"}.get(button, "left")
