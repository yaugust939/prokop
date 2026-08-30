"""Десктопная GUI-автоматизация прокопия.

Пакет даёт ядру инструмент ``computer_use``: захват экрана/окон в режимах
``som``/``vision``/``ax``, клики и ввод по индексам элементов или координатам,
скролл/драг, горячие клавиши, управление окнами и фокусом. Бэкенды —
локальный Windows (mss + pyautogui + pywinauto UIA) и cua-driver через MCP.
"""

from __future__ import annotations

from prokop.computer.schema import get_computer_use_schema

__all__ = ["get_computer_use_schema"]
