"""Доставка результата прогона планировщика.

Цель доставки — строка, разбираемая в стратегию. Фаза 1 реализует
«локально» (файл в каталоге выхода задания); остальные стратегии
(канал, адрес, веер) — интерфейс с заглушками для последующих фаз.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Optional

from agent_core.cron.model import Job


class DeliveryError(Exception):
    """Ошибка доставки."""


class DeliveryStrategy(ABC):
    """Стратегия доставки результата."""

    name: str = "abstract"

    @abstractmethod
    def deliver(self, job: Job, payload: str, *, home: Path) -> Optional[str]:
        """Доставить результат; вернуть путь/идентификатор или ``None``."""


class LocalDelivery(DeliveryStrategy):
    """Локальная доставка: только файл выхода задания, без чата."""

    name = "локально"

    def deliver(self, job: Job, payload: str, *, home: Path) -> Optional[str]:
        output_dir = home / "cron" / "outputs" / job.id
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = output_dir / f"{stamp}.txt"
        path.write_text(payload, encoding="utf-8")
        return str(path)


class _NotImplementedDelivery(DeliveryStrategy):
    """Заглушка для стратегий последующих фаз."""

    def __init__(self, name: str) -> None:
        self.name = name

    def deliver(self, job: Job, payload: str, *, home: Path) -> Optional[str]:
        raise DeliveryError(
            f"Стратегия доставки «{self.name}» доступна с фазы гейтвея/платформ"
        )


#: Реестр стратегий по имени.
_STRATEGIES: dict[str, DeliveryStrategy] = {
    "локально": LocalDelivery(),
    "local": LocalDelivery(),
    "source": _NotImplementedDelivery("источник"),
    "источник": _NotImplementedDelivery("источник"),
    "all": _NotImplementedDelivery("все"),
    "все": _NotImplementedDelivery("все"),
}


def resolve_delivery(target: str) -> DeliveryStrategy:
    """Разобрать цель доставки в стратегию.

    Неизвестная цель трактуется как адрес «платформа:чат» — заглушка до
    появления платформ.
    """
    target = (target or "").strip().lower()
    strategy = _STRATEGIES.get(target)
    if strategy is not None:
        return strategy
    return _NotImplementedDelivery(target or "адрес")


def deliver_result(job: Job, payload: str, *, home: Path) -> Optional[str]:
    """Доставить результат согласно цели задания."""
    strategy = resolve_delivery(job.delivery_target)
    return strategy.deliver(job, payload, home=home)
