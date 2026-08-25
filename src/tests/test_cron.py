"""Тесты планировщика (обвес, Фаза 1)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta

import pytest

from prokop.cron.model import Job, JobError, validate_job, new_job_id
from prokop.cron.schedule import (
    ScheduleKind,
    ScheduleError,
    parse_schedule,
    next_run,
)
from prokop.cron.store import JobStore
from prokop.cron.ticker import Ticker, add_job, GRACE_SECONDS
from prokop.cron.delivery import resolve_delivery, LocalDelivery, DeliveryError


# --- модель и валидация ---------------------------------------------------


def test_validate_job_empty_payload():
    job = Job(id="1", name="x")
    with pytest.raises(JobError):
        validate_job(job)


def test_validate_job_no_agent_requires_script():
    job = Job(id="1", name="x", no_agent=True, prompt="текст",
              schedule=parse_schedule("5м"))
    with pytest.raises(JobError):
        validate_job(job)


def test_validate_job_requires_schedule():
    job = Job(id="1", name="x", prompt="текст")
    with pytest.raises(JobError):
        validate_job(job)


def test_job_dict_roundtrip():
    job = Job(id="abc", name="ночной отчёт", prompt="собери отчёт",
              schedule=parse_schedule("каждые 2ч"),
              delivery_target="локально")
    restored = Job.from_dict(job.to_dict())
    assert restored.name == "ночной отчёт"
    assert restored.schedule.kind is ScheduleKind.INTERVAL
    assert restored.schedule.minutes == 120


# --- разбор расписаний ----------------------------------------------------


def test_parse_duration():
    spec = parse_schedule("30м")
    assert spec.kind is ScheduleKind.ONCE
    assert spec.minutes == 30
    assert parse_schedule("2h").minutes == 120
    assert parse_schedule("1д").minutes == 1440


def test_parse_every():
    spec = parse_schedule("каждые 2ч")
    assert spec.kind is ScheduleKind.INTERVAL
    assert spec.minutes == 120


def test_parse_cron():
    spec = parse_schedule("*/5 * * * *")
    assert spec.kind is ScheduleKind.CRON
    assert spec.cron_expr == "*/5 * * * *"


def test_parse_iso():
    spec = parse_schedule("2030-01-01T09:00:00")
    assert spec.kind is ScheduleKind.AT
    assert spec.at == "2030-01-01T09:00:00"


def test_parse_rejects_arbitrary_phrase():
    with pytest.raises(ScheduleError):
        parse_schedule("каждый понедельник 9 утра")


def test_parse_rejects_bad_cron():
    with pytest.raises(ScheduleError):
        parse_schedule("99 * * * *")


# --- вычисление следующего запуска ----------------------------------------


def test_next_run_once_and_interval():
    now = datetime(2026, 1, 1, 12, 0, 0)
    once = parse_schedule("30м")
    assert next_run(once, now) == now + timedelta(minutes=30)
    interval = parse_schedule("каждые 1ч")
    assert next_run(interval, now) == now + timedelta(hours=1)


def test_next_run_at():
    spec = parse_schedule("2030-01-01T09:00:00")
    assert next_run(spec, datetime.now()) == datetime(2030, 1, 1, 9, 0, 0)


def test_next_run_cron():
    # «Каждые 15 минут» → следующий кратный 15 момент.
    spec = parse_schedule("*/15 * * * *")
    nxt = next_run(spec, datetime(2026, 1, 1, 12, 3, 0))
    assert nxt == datetime(2026, 1, 1, 12, 15, 0)


# --- магазин --------------------------------------------------------------


def test_store_atomic_roundtrip(home):
    store = JobStore(home)
    job = Job(id=new_job_id(), name="тест", prompt="текст",
              schedule=parse_schedule("5м"))
    store.upsert(job)
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].name == "тест"
    # Обновление не плодит дубли.
    job.name = "обновлено"
    store.upsert(job)
    assert len(store.load()) == 1
    assert store.get(job.id).name == "обновлено"
    assert store.remove(job.id) is True
    assert store.load() == []


# --- тикер ----------------------------------------------------------------


def _script_job(home, script, *, delivery_target="локально", **kwargs):
    store = JobStore(home)
    job = Job(id=new_job_id(), name="w", no_agent=True, script=script,
              schedule=parse_schedule("1м"), delivery_target=delivery_target,
              **kwargs)
    return store, add_job(store, job)


def test_ticker_executes_script_and_delivers(home):
    store, job = _script_job(home, 'python -c "print(\'result\')"')
    future = datetime.now() + timedelta(minutes=2)
    ticker = Ticker(store, home, now_fn=lambda: future)
    result = ticker.tick()
    assert job.id in result.executed
    outputs = list((home / "cron" / "outputs" / job.id).glob("*.txt"))
    assert len(outputs) == 1
    assert "result" in outputs[0].read_text(encoding="utf-8")


def test_ticker_silent_run_no_delivery(home):
    store, job = _script_job(home, 'python -c "pass"')
    future = datetime.now() + timedelta(minutes=2)
    result = Ticker(store, home, now_fn=lambda: future).tick()
    assert job.id in result.quiet
    assert not list((home / "cron" / "outputs" / job.id).glob("*"))


def test_ticker_error_delivers_watchdog_message(home):
    store, job = _script_job(home, 'python -c "import sys; sys.exit(3)"')
    future = datetime.now() + timedelta(minutes=2)
    result = Ticker(store, home, now_fn=lambda: future).tick()
    assert job.id in result.errors
    outputs = list((home / "cron" / "outputs" / job.id).glob("*.txt"))
    assert len(outputs) == 1
    assert "вотчдог" in outputs[0].read_text(encoding="utf-8")


def test_ticker_interval_catchup_consolidates(home):
    store = JobStore(home)
    job = Job(id=new_job_id(), name="w", no_agent=True, script='python -c "pass"',
              schedule=parse_schedule("каждые 1м"), delivery_target="локально")
    job = add_job(store, job)
    # Пропущено много периодов — догон один, следующий запуск от «сейчас».
    far_future = datetime.now() + timedelta(hours=5)
    Ticker(store, home, now_fn=lambda: far_future).tick()
    refreshed = store.get(job.id)
    expected_next = far_future + timedelta(minutes=1)
    assert datetime.fromisoformat(refreshed.next_run) == expected_next


def test_ticker_one_shot_grace_window(home):
    # Разовое пропущено дальше льготного окна — истекает, не исполняется.
    store, job = _script_job(home, 'python -c "print(\'x\')"')
    job.schedule = parse_schedule("1м")
    job.next_run = (datetime.now() - timedelta(seconds=GRACE_SECONDS + 60)).isoformat()
    store.upsert(job)
    result = Ticker(store, home, now_fn=datetime.now).tick()
    assert job.id in result.expired
    assert job.id not in result.executed


def test_ticker_paused_skipped(home):
    store, job = _script_job(home, 'python -c "print(\'x\')"', paused=True)
    future = datetime.now() + timedelta(minutes=2)
    result = Ticker(store, home, now_fn=lambda: future).tick()
    assert job.id in result.skipped_paused
    assert job.id not in result.executed


def test_ticker_one_shot_completes(home):
    store, job = _script_job(home, 'python -c "print(\'x\')"')
    job.schedule = parse_schedule("1м")
    job.next_run = (datetime.now() - timedelta(seconds=1)).isoformat()
    store.upsert(job)
    Ticker(store, home, now_fn=datetime.now).tick()
    assert store.get(job.id).next_run is None


# --- доставка -------------------------------------------------------------


def test_resolve_delivery_local():
    assert isinstance(resolve_delivery("локально"), LocalDelivery)
    assert isinstance(resolve_delivery("local"), LocalDelivery)


def test_resolve_delivery_future_strategies_stub():
    strategy = resolve_delivery("источник")
    with pytest.raises(DeliveryError):
        strategy.deliver(Job(id="x", name="y"), "payload", home=None)
