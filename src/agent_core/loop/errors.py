"""Обработка ошибок вызовов модели.

Транзиентные ошибки API (rate-limit, перегрузка, таймауты) ретраятся с
адаптивной задержкой и джиттером; детерминированные локальные ошибки не
ретраятся. Ошибки классифицируются в структурированный результат с флагом
retryable. Есть жёсткий лимит «выпадающих» исключений, чтобы постоянный
сбой не крутился бесконечно.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

#: Жёсткий лимит исключений, «выпадающих» из ретраев.
MAX_ESCAPED_EXCEPTIONS = 3


class ErrorKind(Enum):
    """Категория ошибки."""

    TRANSIENT = "transient"          # rate-limit, перегрузка, таймаут
    BILLING = "billing"              # квоты/биллинг
    INVALID_REQUEST = "invalid_request"
    LOCAL = "local"                  # детерминированная локальная ошибка
    UNKNOWN = "unknown"


@dataclass
class TurnError:
    """Структурированный результат ошибки хода."""

    kind: ErrorKind
    message: str
    retryable: bool = False

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "retryable": str(self.retryable).lower(),
        }


def classify_error(exc: Exception) -> TurnError:
    """Классифицировать исключение в ошибку хода."""
    text = str(exc).lower()
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return TurnError(ErrorKind.TRANSIENT, "таймаут", retryable=True)
    if "rate limit" in text or "429" in text or "too many requests" in text:
        return TurnError(ErrorKind.TRANSIENT, "ограничение частоты запросов", retryable=True)
    if "overloaded" in text or "503" in text or "502" in text or "500" in text:
        return TurnError(ErrorKind.TRANSIENT, "перегрузка сервера", retryable=True)
    if "quota" in text or "billing" in text or "insufficient" in text or "402" in text:
        return TurnError(ErrorKind.BILLING, "квота/биллинг исчерпаны", retryable=False)
    if "invalid" in text or "400" in text or "bad request" in text:
        return TurnError(ErrorKind.INVALID_REQUEST, "невалидный запрос", retryable=False)
    if isinstance(exc, (TypeError, ValueError, KeyError)):
        return TurnError(ErrorKind.LOCAL, f"локальная ошибка: {exc}", retryable=False)
    return TurnError(ErrorKind.UNKNOWN, str(exc), retryable=False)


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Адаптивная задержка с джиттером."""
    delay = min(cap, base * (2 ** attempt))
    return delay * (0.5 + random.random() / 2)


async def retry_transient(coro_factory, *, max_attempts: int = 3, sleep=asyncio.sleep):
    """Повторять транзиентные ошибки; локальные пробрасывать сразу.

    Возвращает результат первого успешного вызова. Если все попытки
    исчерпаны, возвращает последнюю ошибку.
    """
    last_error: Optional[TurnError] = None
    escaped = 0
    for attempt in range(max_attempts):
        try:
            return await coro_factory(), None
        except Exception as exc:  # noqa: BLE001 — классифицируем любое
            error = classify_error(exc)
            if error.kind is ErrorKind.LOCAL:
                raise
            last_error = error
            if not error.retryable or attempt == max_attempts - 1:
                return None, error
            await sleep(backoff_delay(attempt))
    return None, last_error
