"""Тикер планировщика: проверка наступивших заданий и их запуск.

Тик сериализуется блокировкой «один тик на машину». Пропущенные во время
простоя повторяющиеся задания догоняются одним объединением (следующий
запуск пересчитывается от текущего момента, а не веером от прошлого).
Разовые задания исполняются в пределах льготного окна после пропуска.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from agent_core.cron import delivery
from agent_core.cron.executor import execute_script
from agent_core.cron.model import Job
from agent_core.cron.schedule import ScheduleKind, next_run
from agent_core.cron.store import JobStore

#: Льготное окно для разовых заданий после пропуска, секунд.
GRACE_SECONDS = 120.0


@dataclass
class TickResult:
    """Итог одного тика."""

    executed: list[str] = field(default_factory=list)
    quiet: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    skipped_paused: list[str] = field(default_factory=list)
    deferred_agent: list[str] = field(default_factory=list)


class Ticker:
    """Тикер планировщика над магазином заданий."""

    def __init__(
        self,
        store: JobStore,
        home: Path,
        *,
        now_fn: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.store = store
        self.home = Path(home)
        self.now_fn = now_fn or datetime.now

    # --- тик ------------------------------------------------------------

    def tick(self) -> TickResult:
        """Один проход: исполнить наступившие задания и пересчитать времена."""
        result = TickResult()
        with self.store.locked():
            jobs = self.store.load()
            now = self.now_fn()
            updated: list[Job] = []
            for job in jobs:
                if job.paused:
                    result.skipped_paused.append(job.id)
                    updated.append(job)
                    continue
                if not job.next_run or job.schedule is None:
                    updated.append(job)
                    continue
                due = datetime.fromisoformat(job.next_run)
                if due > now:
                    updated.append(job)
                    continue
                self._fire(job, due, now, result)
                self._advance(job, due, now)
                updated.append(job)
            self.store.save(updated)
        return result

    # --- исполнение ---------------------------------------------------------

    def _fire(self, job: Job, due: datetime, now: datetime, result: TickResult) -> None:
        is_one_shot = job.schedule.kind in (ScheduleKind.ONCE, ScheduleKind.AT)
        if is_one_shot and (now - due).total_seconds() > GRACE_SECONDS:
            result.expired.append(job.id)
            return

        if job.script:
            execution = execute_script(job.script)
            if execution.silent:
                result.quiet.append(job.id)
            elif execution.ok:
                self._deliver(job, execution.stdout)
                result.executed.append(job.id)
            else:
                self._deliver(job, f"⚠️ вотчдог: задание «{job.name}» завершилось ошибкой (код {execution.exit_code}).")
                job.error_count += 1
                result.errors.append(job.id)
            return

        # Задание с промптом, но без скрипта — агентный ход (Фаза 2).
        result.deferred_agent.append(job.id)

    def _deliver(self, job: Job, payload: str) -> None:
        try:
            delivery.deliver_result(job, payload, home=self.home)
        except delivery.DeliveryError:
            pass

    # --- пересчёт времени ---------------------------------------------------

    def _advance(self, job: Job, due: datetime, now: datetime) -> None:
        job.last_run_at = now.isoformat()
        if job.schedule.kind in (ScheduleKind.ONCE, ScheduleKind.AT):
            job.next_run = None  # разовое выполнено
            return
        if job.schedule.kind is ScheduleKind.INTERVAL:
            # Догон одним объединением: от текущего момента, не веером.
            job.next_run = (now + timedelta(minutes=job.schedule.minutes or 0)).isoformat()
            return
        if job.schedule.kind is ScheduleKind.CRON:
            nxt = next_run(job.schedule, now)
            job.next_run = nxt.isoformat() if nxt else None


def add_job(
    store: JobStore,
    job: Job,
    *,
    now: Optional[datetime] = None,
) -> Job:
    """Добавить задание с вычисленным следующим запуском."""
    now = now or datetime.now()
    job.created_at = job.created_at or now.isoformat()
    job.next_run = (next_run(job.schedule, now) or now).isoformat()
    store.upsert(job)
    return job
