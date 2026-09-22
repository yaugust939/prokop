"""Сбор и разбор результатов headless-сессии opencode (этап 1 — MVP).

Процесс ``opencode run --format json`` пишет в stdout NDJSON-поток событий.
``collect`` читает его построчно, копит последний текст ``message.updated``
и финальное событие ``result``. Таймаут по приоритету задачи; при таймауте
допускается одна повторная попытка с ``--fork`` (реализуется вызывающим
кодом через ``collect_once``), затем дерево процессов завершается
принудительно (``taskkill /T /F`` на Windows, ``killpg`` на POSIX).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional

from prokop.orchestrator.spawn import SpawnConfig, spawn


class OrchestratorError(Exception):
    """Ошибка оркестратора при выполнении headless-сессии."""


@dataclass
class SessionResult:
    """Итог headless-сессии opencode."""

    result: Optional[str] = None        # финальный текстовый итог
    session_id: Optional[str] = None
    cost: Optional[float] = None
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    duration_ms: Optional[int] = None
    last_text: Optional[str] = None     # последний текст message.updated
    timed_out: bool = False
    exit_code: Optional[int] = None
    events: list[dict] = field(default_factory=list)  # все разобранные события

    @property
    def ok(self) -> bool:
        return self.result is not None and not self.timed_out


def _kill_process_tree(pid: int) -> None:
    """Прибить процесс с деревом потомков.

    Windows — ``taskkill /T /F``; POSIX — сигнал группе процессов
    (``SIGKILL``, с откатом на ``SIGTERM`` там, где его нет).
    """
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
    else:
        import signal

        sig = getattr(signal, "SIGKILL", signal.SIGTERM)
        try:
            os.killpg(os.getpgid(pid), sig)
        except (OSError, ProcessLookupError):
            try:
                os.kill(pid, sig)
            except OSError:
                return


def parse_ndjson_line(line: str) -> Optional[dict]:
    """Разобрать одну строку NDJSON; не-JSON строки (логи) игнорируются."""
    line = line.strip()
    if not line:
        return None
    # Возможный BOM/мусор в начале потока от обёртки консоли.
    if line.startswith("\ufeff"):
        line = line[1:]
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def _is_result_event(event: dict) -> bool:
    return event.get("type") == "result"


def _is_message_updated(event: dict) -> bool:
    if event.get("type") != "message.updated":
        return False
    part = event.get("part") or {}
    return part.get("type") == "text" and isinstance(part.get("text"), str)


def collect_once(cfg: SpawnConfig) -> SessionResult:
    """Запустить headless-сессию и собрать результат (одна попытка).

    Читает stdout построчно до завершения процесса или таймаута. При
    таймауте завершает дерево процессов принудительно (``taskkill`` на
    Windows, ``killpg`` на POSIX) и помечает ``timed_out=True``.
    """
    proc, _binary = spawn(cfg)
    started = time.monotonic()
    timeout = cfg.timeout_seconds
    result = SessionResult(exit_code=None)

    # Финальный результат может прийти либо как событие "result",
    # либо последним текстовым сообщением; читаем до конца процесса.
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            event = parse_ndjson_line(raw)
            if event is None:
                continue
            result.events.append(event)
            if _is_result_event(event):
                data = event.get("result") or {}
                if isinstance(data, dict):
                    result.session_id = data.get("sessionId") or data.get("sessionID")
                    result.cost = data.get("cost")
                    result.tokens_input = data.get("tokens", {}).get("input") \
                        if isinstance(data.get("tokens"), dict) else None
                    result.tokens_output = data.get("tokens", {}).get("output") \
                        if isinstance(data.get("tokens"), dict) else None
                    result.duration_ms = data.get("durationMs")
                    text = data.get("result") or data.get("text")
                    if isinstance(text, str) and text.strip():
                        result.result = text
                elif isinstance(data, str) and data.strip():
                    result.result = data
                    result.session_id = event.get("sessionId") or event.get("sessionID")
            elif _is_message_updated(event):
                text = (event.get("part") or {}).get("text")
                if text:
                    result.last_text = text
            if time.monotonic() - started > timeout:
                raise TimeoutError("превышен таймаут headless-сессии")

        proc.wait(timeout=15)
        result.exit_code = proc.returncode
        if result.session_id is None:
            result.session_id = _extract_session_id(result.events)
    except TimeoutError:
        result.timed_out = True
        _kill_process_tree(proc.pid)
    except (OSError, subprocess.TimeoutExpired) as exc:
        result.timed_out = True
        result.exit_code = -1
        _kill_process_tree(proc.pid)
        result.last_text = f"error: {exc}"

    if result.result is None and result.last_text:
        # Финальное событие result могло не прийти — берём последний текст.
        result.result = result.last_text
    return result


def _extract_session_id(events: list[dict]) -> Optional[str]:
    for event in events:
        sid = event.get("sessionId") or event.get("sessionID")
        if sid:
            return sid
    return None


def run_with_retry(cfg: SpawnConfig, *, max_attempts: int = 2) -> SessionResult:
    """Запуск с одной повторной попыткой ``--fork`` при таймауте.

    Первый запуск — с исходным конфигом; при ``timed_out`` повторно с
    ``fork=True``. Ошибка запуска бросается как ``OrchestratorError``.
    """
    attempt = 0
    last: Optional[SessionResult] = None
    while attempt < max_attempts:
        attempt += 1
        retry_cfg = cfg
        if attempt > 1:
            retry_cfg = SpawnConfig(**{**cfg.__dict__, "fork": True})
        try:
            last = collect_once(retry_cfg)
        except FileNotFoundError as exc:
            raise OrchestratorError(str(exc)) from exc
        if not last.timed_out:
            return last
    # Обе попытки истекли по таймауту.
    assert last is not None
    return last
