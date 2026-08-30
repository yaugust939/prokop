"""Обработка результатов захвата: сводка, SOM-оверлеи, мультимодальность.

Ядро возвращает инструментам либо JSON-строку, либо мультимодальную
обёртку ``_multimodal`` (список content-блоков). Захваты упаковываются в
обёртку: текстовый блок (сводка + индексы) и изображение base64 — так
vision-модели видят скриншот, а текстовые модели получают сводку.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from prokop.computer.backend import CaptureResult, UIElement
from prokop.logging_setup import get_logger

log = get_logger("computer.capture")

#: Максимальное число элементов AX-дерева по умолчанию.
DEFAULT_MAX_ELEMENTS = 100
#: Жёсткий потолок.
HARD_MAX_ELEMENTS = 1000
#: Целевой размер изображения по длинной стороне.
MAX_IMAGE_SIDE = 1280

MULTIMODAL_FLAG = "_multimodal"


def clamp_max_elements(value: Optional[int]) -> int:
    """Ограничить значение max_elements допустимым диапазоном."""
    if value is None:
        return DEFAULT_MAX_ELEMENTS
    return max(1, min(int(value), HARD_MAX_ELEMENTS))


def trim_elements(elements: list[UIElement], limit: int) -> tuple[list[UIElement], int]:
    """Обрезать дерево элементов до limit; вернуть (элементы, отброшено)."""
    total = len(elements)
    if total <= limit:
        return elements, 0
    return elements[:limit], total - limit


def scale_png(data: bytes, max_side: int = MAX_IMAGE_SIDE) -> bytes:
    """Уменьшить PNG, если длинная сторона больше max_side."""
    try:
        from PIL import Image  # type: ignore
    except Exception:  # noqa: BLE001 — без Pillow возвращаем как есть
        return data
    try:
        import io

        img = Image.open(io.BytesIO(data))
        w, h = img.size
        longest = max(w, h)
        if longest <= max_side:
            return data
        ratio = max_side / longest
        img = img.resize((max(1, round(w * ratio)), max(1, round(h * ratio))))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось уменьшить скриншот: %s", exc)
        return data


def _summary_text(capture: CaptureResult, max_elements: int) -> str:
    """Текстовая сводка захвата: описание + элементы с индексами."""
    lines: list[str] = []
    target = f" (цель: {capture.target})" if capture.target else ""
    lines.append(f"Захват mode={capture.mode}{target}: {len(capture.elements)} элементов.")
    if capture.truncated_elements:
        lines.append(
            f"Внимание: дерево усечено, всего {capture.total_elements}, показано {max_elements}."
        )
    for el in capture.elements:
        desc = f"[{el.index}] {el.control_type or el.role}".strip()
        if el.name:
            desc += f" {el.name}"
        if el.value not in (None, ""):
            desc += f" = {el.value}"
        if el.rect:
            x, y, w, h = el.rect
            desc += f" @({x},{y},{w},{h})"
        lines.append(desc)
    return "\n".join(lines)


def draw_som_overlay(data: bytes, elements: list[UIElement]) -> bytes:
    """Нарисовать нумерованные рамки поверх скриншота (SOM-разметка)."""
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:  # noqa: BLE001 — без Pillow оверлеи не рисуем
        return data
    try:
        import io

        img = Image.open(io.BytesIO(data)).convert("RGB")
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default(16)
        except Exception:  # noqa: BLE001
            font = None
        for el in elements:
            if not el.rect:
                continue
            x, y, w, h = el.rect
            draw.rectangle([x, y, x + w, y + h], outline=(255, 80, 80), width=2)
            label = str(el.index)
            if font is None:
                draw.text((x + 2, y + 2), label, fill=(255, 80, 80))
            else:
                draw.text((x + 2, y + 2), label, font=font, fill=(255, 80, 80))
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.warning("Не удалось нарисовать SOM-оверлеи: %s", exc)
        return data


def make_capture_result(
    capture: CaptureResult,
    *,
    max_elements: int = DEFAULT_MAX_ELEMENTS,
    scale: bool = True,
    som_overlay: bool = False,
) -> CaptureResult:
    """Подготовить результат: ограничить элементы, сформировать сводку."""
    limit = clamp_max_elements(max_elements)
    elements, dropped = trim_elements(capture.elements, limit)
    capture.elements = elements
    capture.total_elements = len(capture.elements) + dropped
    capture.truncated_elements = dropped
    if capture.image and som_overlay and capture.mode == "som" and elements:
        capture.image = draw_som_overlay(capture.image, elements)
    if capture.image and scale:
        capture.image = scale_png(capture.image)
    capture.text = _summary_text(capture, limit)
    return capture


def make_multimodal(capture: CaptureResult) -> dict[str, Any]:
    """Упаковать захват в мультимодальную обёртку ``_multimodal``."""
    content: list[dict[str, Any]] = [
        {"type": "text", "text": capture.text or "Захват без сводки."},
    ]
    if capture.image:
        b64 = base64.b64encode(capture.image).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        )
    return {
        MULTIMODAL_FLAG: True,
        "content": content,
        "text_summary": capture.text or "",
    }
