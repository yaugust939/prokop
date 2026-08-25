"""Движок делегирования: связывает роли, реестр, очередь и параллельность.

Реальное порождение ребёнка зависит от транспорта модели и инжектируется как
колбэк ``spawn_fn(goal, context, role) -> SubagentResult`` (асинхронный).
Логика глубины, ролей, потолка детей, реестра, очереди завершений и
параллельного исполнения пакета реализована автономно.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Awaitable, Callable, Optional

from prokop.subagents.config import SubagentsConfig
from prokop.subagents.model import (
    SubagentRecord,
    SubagentResult,
    SubagentStatus,
    new_subagent_id,
)
from prokop.subagents.queue import CompletionQueue
from prokop.subagents.registry import RegistrySaturatedError, SubagentRegistry
from prokop.subagents.roles import Role, RoleError, resolve_role, validate_depth

#: Колбэк порождения ребёнка: (цель, контекст, роль) -> результат.
SpawnFn = Callable[[str, str, str], Awaitable[SubagentResult]]


class DelegationEngine:
    """Оркестрация порождения и управления субагентами."""

    def __init__(
        self,
        *,
        spawn_fn: SpawnFn,
        config: Optional[SubagentsConfig] = None,
        depth: int = 0,
        owner: Optional[str] = None,
    ) -> None:
        self.spawn_fn = spawn_fn
        self.config = config or SubagentsConfig()
        #: Глубина вложенности текущего агента (у корня — 0).
        self.depth = depth
        self.owner = owner
        self.registry = SubagentRegistry(self.config.max_children)
        self.completions = CompletionQueue()
        self._tasks: dict[str, asyncio.Task] = {}
        self._tasks_lock = threading.Lock()

    # --- публичное API ------------------------------------------------------

    async def delegate(
        self,
        *,
        goal: Optional[str] = None,
        context: str = "",
        role: str | Role = Role.LEAF.value,
        tasks: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Породить одиночную цель или пакет задач; вернуть квитанцию."""
        if tasks:
            return await self._spawn_batch(tasks)
        if not goal or not goal.strip():
            return {"ok": False, "error": "пустая цель делегирования"}
        subagent_id = await self._spawn_single(goal, context, role)
        return {
            "ok": True,
            "delegation_id": subagent_id,
            "subagent_ids": [subagent_id],
        }

    async def handle_action(self, action: str, **kwargs: Any) -> dict[str, Any]:
        """Единая точка входа инструмента делегирования."""
        if action == "spawn":
            try:
                return await self.delegate(
                    goal=kwargs.get("goal"),
                    context=kwargs.get("context") or "",
                    role=kwargs.get("role") or Role.LEAF.value,
                    tasks=kwargs.get("tasks"),
                )
            except (RegistrySaturatedError, RoleError) as exc:
                return {"ok": False, "error": str(exc)}
        if action == "list":
            return {"ok": True, "subagents": self.list()}
        if action == "steer":
            ok = self.steer(kwargs.get("subagent_id"), kwargs.get("steer") or "")
            return {"ok": ok}
        if action == "stop":
            ok = self.stop(kwargs.get("subagent_id"))
            return {"ok": ok}
        return {"ok": False, "error": f"неизвестное действие: {action}"}

    # --- управление -----------------------------------------------------------

    def list(self) -> list[dict[str, Any]]:
        """Список активных субагентов."""
        return self.registry.list()

    def stop(self, subagent_id: Optional[str]) -> bool:
        """Остановить субагента: пометить и отменить его задачу."""
        if not subagent_id or not self.registry.stop(subagent_id):
            return False
        task = self._tasks.get(subagent_id)
        if task is not None and not task.done():
            task.cancel()
        return True

    def steer(self, subagent_id: Optional[str], text: str) -> bool:
        """Подрулить субагента текстом."""
        if not subagent_id:
            return False
        return self.registry.steer(subagent_id, text)

    # --- порождение ------------------------------------------------------------

    async def _spawn_single(self, goal: str, context: str, role: str | Role) -> str:
        self._validate_spawn(role)
        resolved = resolve_role(role, orchestration_enabled=self.config.orchestration_enabled)
        record = SubagentRecord(
            id=new_subagent_id(),
            goal=goal,
            role=resolved.value,
            owner=self.owner,
        )
        self.registry.register(record)
        child = self._launch_child(record, goal, context, resolved.value)
        asyncio.create_task(self._deliver(child))
        return record.id

    async def _spawn_batch(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"ok": False, "error": "пустой пакет задач"}
        specs: list[tuple[SubagentRecord, str, str, str]] = []
        registered: list[SubagentRecord] = []
        try:
            for item in items:
                goal = (item.get("goal") or "").strip()
                if not goal:
                    raise RoleError("в пакете есть задача с пустой целью")
                role = item.get("role") or Role.LEAF.value
                self._validate_spawn(role)
                resolved = resolve_role(
                    role, orchestration_enabled=self.config.orchestration_enabled
                )
                record = SubagentRecord(
                    id=new_subagent_id(),
                    goal=goal,
                    role=resolved.value,
                    owner=self.owner,
                )
                self.registry.register(record)
                registered.append(record)
                specs.append((record, goal, item.get("context") or "", resolved.value))
        except (RegistrySaturatedError, RoleError):
            for record in registered:
                self.registry.remove(record.id)
            raise

        delegation_id = new_subagent_id()
        child_tasks = [
            self._launch_child(record, goal, context, role)
            for record, goal, context, role in specs
        ]
        asyncio.create_task(self._deliver_batch(delegation_id, child_tasks))
        return {
            "ok": True,
            "delegation_id": delegation_id,
            "subagent_ids": [record.id for record, *_ in specs],
            "parallel": True,
        }

    def _validate_spawn(self, role: str | Role) -> None:
        validate_depth(self.depth + 1, self.config.max_depth)

    # --- исполнение ребёнка -------------------------------------------------------

    def _launch_child(
        self, record: SubagentRecord, goal: str, context: str, role: str
    ) -> asyncio.Task:
        task = asyncio.create_task(self._run_child(record, goal, context, role))
        with self._tasks_lock:
            self._tasks[record.id] = task
        task.add_done_callback(lambda _t, rid=record.id: self._forget(rid))
        return task

    def _forget(self, subagent_id: str) -> None:
        with self._tasks_lock:
            self._tasks.pop(subagent_id, None)

    async def _run_child(
        self, record: SubagentRecord, goal: str, context: str, role: str
    ) -> SubagentResult:
        try:
            result = await self.spawn_fn(goal, context, role)
        except asyncio.CancelledError:
            result = SubagentResult(
                goal=goal,
                context=context,
                role=role,
                status=SubagentStatus.STOPPED.value,
                summary="остановлен владельцем",
                subagent_id=record.id,
            )
        except Exception as exc:  # noqa: BLE001 — сбой ребёнка не роняет движок
            result = SubagentResult(
                goal=goal,
                context=context,
                role=role,
                status=SubagentStatus.FAILED.value,
                error=str(exc),
                subagent_id=record.id,
            )
        self.registry.remove(record.id)
        return result

    async def _deliver(self, child: asyncio.Task) -> None:
        result = await child
        await self.completions.put(result)

    async def _deliver_batch(self, delegation_id: str, children: list[asyncio.Task]) -> None:
        results = [await child for child in children]
        await self.completions.put(consolidate_batch_results(delegation_id, results))


def consolidate_batch_results(
    delegation_id: str, results: list[SubagentResult]
) -> SubagentResult:
    """Свернуть результаты пакета в одно консолидированное сообщение."""
    if not results:
        return SubagentResult(
            goal=delegation_id, status=SubagentStatus.DONE.value, summary="пустой пакет"
        )
    statuses = {r.status for r in results}
    if SubagentStatus.FAILED.value in statuses:
        status = SubagentStatus.FAILED.value
    elif SubagentStatus.TRUNCATED.value in statuses:
        status = SubagentStatus.TRUNCATED.value
    elif SubagentStatus.STOPPED.value in statuses:
        status = SubagentStatus.STOPPED.value
    else:
        status = SubagentStatus.DONE.value
    summary = "\n".join(
        f"[{r.subagent_id or '?'}] {r.summary}" for r in results if r.summary
    )
    models = {r.model for r in results if r.model}
    errors = [r.error for r in results if r.error]
    return SubagentResult(
        goal=f"пакет из {len(results)} задач ({delegation_id})",
        status=status,
        summary=summary,
        api_calls=sum(r.api_calls for r in results),
        model=", ".join(sorted(models)),
        error="; ".join(errors) or None,
    )
