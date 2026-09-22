"""Настройка стандартных потоков CLI.

Консоль Windows по умолчанию не UTF-8, из-за чего кириллица в выводе
превращается в `UnicodeEncodeError`. Здесь потоки приводятся к UTF-8; там,
где перенастройка не поддерживается (или поток подменён), настройка
безоперационна и не приводит к падению.
"""

from __future__ import annotations

import sys
from typing import Any

#: Кодировка, к которой приводятся потоки.
ENCODING = "utf-8"


def _reconfigure(stream: Any) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding=ENCODING, errors="replace")
    except (ValueError, OSError, LookupError, AttributeError):
        # Поток уже закрыт, обёрнут или не поддерживает смену кодировки.
        return


def configure_stdio() -> None:
    """Привести stdin/stdout/stderr к UTF-8 (best-effort, без падений)."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if stream is None:
            continue
        _reconfigure(stream)
