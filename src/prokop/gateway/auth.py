"""Авторизация отправителя.

Гейтвей проверяет отправителя до модельного хода: по белому списку ид
(разбитому по платформам) либо по явному глобальному «разрешить всех».
Несанкционированный отправитель отклоняется — применяется политика
спаривания (код подтверждения) либо игнорирования.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class UnauthorizedPolicy(str, Enum):
    """Политика для неавторизованного отправителя."""

    IGNORE = "ignore"
    PAIR = "pair"


@dataclass(frozen=True)
class AuthDecision:
    """Результат проверки отправителя."""

    allowed: bool
    policy: UnauthorizedPolicy = UnauthorizedPolicy.IGNORE
    reason: Optional[str] = None


class SenderGate:
    """Белый список отправителей с глобальным «разрешить всех»."""

    def __init__(
        self,
        *,
        allow_all: bool = False,
        policy: UnauthorizedPolicy = UnauthorizedPolicy.IGNORE,
    ) -> None:
        #: Глобальное явное «разрешить всех».
        self.allow_all = allow_all
        #: Политика для неавторизованных.
        self.policy = policy
        #: platform -> set(user_id).
        self._allowed: dict[str, set[str]] = {}

    def grant(self, platform: str, user_id: str) -> None:
        """Добавить отправителя в белый список платформы."""
        self._allowed.setdefault(platform, set()).add(user_id)

    def revoke(self, platform: str, user_id: str) -> bool:
        """Убрать отправителя из белого списка; True, если он там был."""
        ids = self._allowed.get(platform)
        if ids is None or user_id not in ids:
            return False
        ids.discard(user_id)
        if not ids:
            self._allowed.pop(platform, None)
        return True

    def is_whitelisted(self, platform: str, user_id: str) -> bool:
        """True, если отправитель в белом списке (без учёта allow_all)."""
        return user_id in self._allowed.get(platform, set())

    def authorize(self, platform: str, user_id: str) -> AuthDecision:
        """Проверить отправителя.

        Глобальное «разрешить всех» имеет приоритет над белым списком.
        Неавторизованный отправитель получает решение с политикой
        спаривания/игнорирования.
        """
        if self.allow_all:
            return AuthDecision(allowed=True)
        if self.is_whitelisted(platform, user_id):
            return AuthDecision(allowed=True)
        return AuthDecision(
            allowed=False,
            policy=self.policy,
            reason="отправитель вне белого списка",
        )
