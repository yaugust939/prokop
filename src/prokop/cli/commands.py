"""Реализация команд CLI — тонкий слой над модулями ядра.

Здесь нет логики хода, хранения, расписаний или навыков: команды собирают
зависимости из ядра (`AgentTurn`, `SessionStore`, `JobStore`/`Ticker`,
`discover_skills`, `ProviderRegistry`, `load_config`) и форматируют результат.

Зависимости вынесены в :class:`Context` полями-фабриками, чтобы тесты
подменяли их без сети, без ключей и без реального профиля.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, TextIO

from prokop.checkpoints.store import CheckpointError, CheckpointStore
from prokop.config import Config, config_path, load_config
from prokop.cron.model import Job, new_job_id, validate_job
from prokop.cron.schedule import parse_schedule
from prokop.cron.store import JobStore
from prokop.cron.ticker import Ticker, add_job
from prokop.home import home_dir, profile_name
from prokop.loop.turn import AgentTurn
from prokop.mcp.client import McpClient
from prokop.mcp.config import McpServerConfig, parse_servers
from prokop.mcp.runtime import tool_name
from prokop.paths import DATABASE_NAME
from prokop.providers.registry import ProviderRegistry
from prokop.security.audit import DEFAULT_TAIL, AuditLog
from prokop.security.policy import SCOPE_NOTICE, Decision, SecurityPolicy
from prokop.skills.discovery import SkillStore, discover_skills
from prokop.store.search import ensure_fts, search_sessions
from prokop.store.sessions import SessionStore
from prokop.transport.http_transport import ChatCompletionsTransport

#: Код возврата: ошибка пользователя или конфигурации.
EXIT_USAGE = 1
#: Код возврата: ошибка исполнения (модель, инфраструктура).
EXIT_RUNTIME = 2

#: Идентичность агента для CLI-ходов.
DEFAULT_IDENTITY = "Ты — PROKOP, универсальный помощник. Отвечай кратко и по делу."

#: Имя каталога пользовательских навыков внутри профиля.
SKILLS_DIR = "skills"

#: Команды выхода в интерактивном режиме.
_EXIT_WORDS = frozenset({"exit", "quit", ":q", ":quit"})


class CliError(Exception):
    """Ошибка CLI, несущая код возврата."""

    def __init__(self, message: str, code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Result:
    """Итог команды: данные для `--json` и текст для человека."""

    data: Any = None
    text: str = ""


def default_skill_discovery(home: Path, config: Config) -> list[Any]:
    """Навыки профиля из каталога ``<профиль>/skills``."""
    return discover_skills([SkillStore(home / SKILLS_DIR, provenance="user")])


@dataclass
class Context:
    """Окружение команды: пути, потоки, переменные и фабрики ядра."""

    home: Path
    profile: str
    env: Mapping[str, str]
    stdin: TextIO
    stdout: TextIO
    stderr: TextIO
    config_loader: Callable[[Path], Config] = load_config
    registry_factory: Callable[[], ProviderRegistry] = ProviderRegistry
    session_store_factory: Callable[[Path], SessionStore] = SessionStore
    job_store_factory: Callable[[Path], JobStore] = JobStore
    ticker_factory: Callable[[JobStore, Path], Ticker] = Ticker
    skill_discovery: Callable[[Path, Config], list[Any]] = default_skill_discovery
    transport_factory: Callable[..., Any] = ChatCompletionsTransport
    turn_factory: Callable[..., Any] = AgentTurn


def make_context(
    *,
    env: Optional[Mapping[str, str]] = None,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> Context:
    """Собрать контекст по умолчанию (реальные пути ядра и потоки процесса)."""
    return Context(
        home=home_dir(),
        profile=profile_name(),
        env=os.environ if env is None else env,
        stdin=stdin if stdin is not None else sys.stdin,
        stdout=stdout if stdout is not None else sys.stdout,
        stderr=stderr if stderr is not None else sys.stderr,
    )


# --- модель и ключ -------------------------------------------------------


def _key_vars(config: Config, profile: Any) -> list[str]:
    """Переменные окружения, в которых может лежать ключ (в порядке поиска)."""
    candidates = [config.model.api_key_env, *profile.env_vars]
    out: list[str] = []
    for name in candidates:
        if name and name not in out:
            out.append(name)
    return out


def resolve_credentials(
    ctx: Context,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> tuple[Any, str, str]:
    """Определить профиль провайдера, ключ и имя модели.

    Бросает :class:`CliError` с кодом ``1``, если провайдер не найден, режим
    API не поддержан, ключ отсутствует или модель не задана.
    """
    config = ctx.config_loader(ctx.home)
    registry = ctx.registry_factory()
    registry.discover()

    name = provider or config.model.provider or "deepseek"
    profile = registry.get(name)
    if profile is None:
        known = ", ".join(registry.names()) or "—"
        raise CliError(f"провайдер {name!r} не найден в реестре. Доступны: {known}")
    if profile.api_mode != "chat_completions":
        raise CliError(
            f"режим API {profile.api_mode!r} пока не поддержан транспортом; "
            "доступен chat_completions"
        )

    key_vars = _key_vars(config, profile)
    api_key = ""
    for var in key_vars:
        value = ctx.env.get(var)
        if value:
            api_key = value
            break
    if not api_key:
        where = " или ".join(key_vars) if key_vars else "переменную окружения с ключом"
        raise CliError(f"нет ключа модели: задайте {where}")

    model_name = model or config.model.model or (
        profile.fallback_models[0] if profile.fallback_models else None
    )
    if not model_name:
        raise CliError(
            "модель не задана: укажите --model или ключ model.model в конфигурации профиля"
        )
    return profile, api_key, model_name


async def run_turn_once(
    ctx: Context,
    profile: Any,
    api_key: str,
    model_name: str,
    prompt: str,
    *,
    history: Optional[list[Any]] = None,
    callbacks: Any = None,
) -> Any:
    """Один ход через транспорт ядра."""
    transport = ctx.transport_factory(profile, api_key=api_key, timeout=180.0)
    turn = ctx.turn_factory(
        transport=transport,
        model=model_name,
        provider=profile.name,
        identity=DEFAULT_IDENTITY,
        history=history,
        callbacks=callbacks,
    )
    try:
        return await turn.run(prompt)
    finally:
        close = getattr(transport, "close", None)
        if close is not None:
            await close()


# --- команды -------------------------------------------------------------


def config_show(ctx: Context) -> Result:
    """Показать действующую конфигурацию профиля."""
    config = ctx.config_loader(ctx.home)
    path = config_path(ctx.home)
    exists = path.exists()
    data = {
        "profile": ctx.profile,
        "home": str(ctx.home),
        "config_path": str(path),
        "config_exists": exists,
        "config": config.to_dict(),
    }
    text = "\n".join(
        [
            f"Профиль: {ctx.profile}",
            f"Домашний каталог: {ctx.home}",
            f"Конфигурация: {path} "
            f"({'есть' if exists else 'нет — значения по умолчанию'})",
            f"Модель: {config.model.provider or '—'} / {config.model.model or '—'}",
        ]
    )
    return Result(data=data, text=text)


def doctor(ctx: Context) -> Result:
    """Проверить окружение профиля, не обращаясь к модели."""
    config = ctx.config_loader(ctx.home)
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    add("профиль", ctx.home.exists(), str(ctx.home))
    add("запись в профиль", os.access(ctx.home, os.W_OK), str(ctx.home))
    path = config_path(ctx.home)
    add(
        "конфигурация",
        True,
        str(path) if path.exists() else f"{path} (нет — значения по умолчанию)",
    )
    add("модель", True, f"{config.model.provider or '—'} / {config.model.model or '—'}")

    registry = ctx.registry_factory()
    registry.discover()
    add("провайдеры", bool(registry.names()), ", ".join(registry.names()) or "не найдены")

    key_vars: list[str] = []
    for profile in registry.list():
        for var in _key_vars(config, profile):
            if var not in key_vars:
                key_vars.append(var)
    found = [var for var in key_vars if ctx.env.get(var)]
    add(
        "ключ модели",
        bool(found),
        ", ".join(found) if found else f"не задан (ожидается {', '.join(key_vars)})",
    )

    add("python", True, sys.version.split()[0])

    for binary, hint in (("opencode", "оркестратор"), ("cua-driver", "GUI-автоматизация")):
        path_bin = _which(ctx, binary)
        add(f"бинарь {binary}", path_bin is not None, path_bin or f"нет ({hint})")

    text_lines = []
    for check in checks:
        mark = "OK " if check["ok"] else "-- "
        text_lines.append(f"{mark}{check['check']}: {check['detail']}")
    return Result(data={"checks": checks}, text="\n".join(text_lines))


def _which(ctx: Context, name: str) -> Optional[str]:
    """Путь к бинарю: сначала специализированный поиск, затем PATH."""
    if name == "opencode":
        try:
            from prokop.orchestrator.spawn import find_opencode

            return find_opencode()
        except Exception:  # noqa: BLE001 — оркестратор опционален
            pass
    import shutil

    return shutil.which(name)


def sessions_list(ctx: Context, *, limit: int = 50) -> Result:
    """Перечислить сессии профиля."""
    store = ctx.session_store_factory(ctx.home)
    try:
        sessions = store.list_sessions()[:limit]
    finally:
        store.close()

    rows = [
        {
            "id": s.get("id"),
            "source": s.get("source"),
            "model": s.get("model"),
            "started_at": s.get("started_at"),
            "last_activity": s.get("last_activity"),
            "message_count": s.get("message_count"),
        }
        for s in sessions
    ]
    if rows:
        text = "\n".join(
            f"{r['id']}  {r['last_activity'] or '—'}  "
            f"{r['message_count'] or 0} сообщ.  {r['model'] or '—'}"
            for r in rows
        )
    else:
        text = "Сессий нет."
    return Result(data={"sessions": rows, "count": len(rows)}, text=text)


def sessions_show(ctx: Context, session_id: str) -> Result:
    """Показать одну сессию с сообщениями."""
    store = ctx.session_store_factory(ctx.home)
    try:
        session = store.get_session(session_id)
        if session is None:
            raise CliError(f"сессия {session_id!r} не найдена")
        messages = store.get_messages(session_id)
    finally:
        store.close()

    rows = [
        {
            "position": m.get("position"),
            "role": m.get("role"),
            "content": m.get("content"),
        }
        for m in messages
    ]
    data = {"session": session, "messages": rows, "count": len(rows)}
    if rows:
        text = "\n".join(
            f"[{r['position']}] {r['role']}: {r['content'] or ''}" for r in rows
        )
    else:
        text = f"Сессия {session_id}: сообщений нет."
    return Result(data=data, text=text)


def sessions_search(ctx: Context, query: str, *, limit: int = 20) -> Result:
    """Полнотекстовый поиск по сообщениям профиля."""
    db_path = ctx.home / DATABASE_NAME
    if not db_path.exists():
        return Result(data={"results": [], "count": 0}, text="Совпадений нет.")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        ensure_fts(conn)
        hits = search_sessions(conn, query, limit=limit)
    finally:
        conn.close()

    if hits:
        text = "\n\n".join(
            f"{hit['session_id']} [{hit['position']}] {hit['role']}: {hit['snippet']}"
            for hit in hits
        )
    else:
        text = "Совпадений нет."
    return Result(data={"results": hits, "count": len(hits)}, text=text)


def skills_list(ctx: Context) -> Result:
    """Перечислить доступные навыки профиля."""
    config = ctx.config_loader(ctx.home)
    skills = ctx.skill_discovery(ctx.home, config)
    rows = [
        {
            "name": skill.name,
            "description": getattr(skill.meta, "description", None),
            "category": getattr(skill, "category", ""),
            "provenance": getattr(skill, "provenance", "user"),
            "path": str(getattr(skill, "path", "")),
        }
        for skill in skills
    ]
    if rows:
        text = "\n".join(f"{r['name']}  [{r['provenance']}]  {r['description'] or ''}" for r in rows)
    else:
        text = "Навыков нет."
    return Result(data={"skills": rows, "count": len(rows)}, text=text)


def providers_list(ctx: Context) -> Result:
    """Перечислить провайдеры моделей из реестра."""
    registry = ctx.registry_factory()
    registry.discover()
    profiles = sorted(registry.list(), key=lambda p: p.name)
    rows = [
        {
            "name": p.name,
            "display_name": p.display_name,
            "api_mode": p.api_mode,
            "aliases": list(p.aliases),
            "env_vars": list(p.env_vars),
            "base_url": p.base_url,
        }
        for p in profiles
    ]
    if rows:
        text = "\n".join(
            f"{r['name']}  [{r['api_mode']}]  ключ: {', '.join(r['env_vars']) or '—'}"
            for r in rows
        )
    else:
        text = "Провайдеров не найдено."
    return Result(data={"providers": rows, "count": len(rows)}, text=text)


def cron_list(ctx: Context) -> Result:
    """Перечислить задания планировщика."""
    store = ctx.job_store_factory(ctx.home)
    jobs = store.load()
    rows = [
        {
            "id": job.id,
            "name": job.name,
            "schedule": job.schedule.display if job.schedule else None,
            "next_run": job.next_run,
            "paused": job.paused,
            "target": job.delivery_target,
        }
        for job in jobs
    ]
    if rows:
        text = "\n".join(
            f"{r['id']}  {r['schedule'] or '—'}  следующий: {r['next_run'] or '—'}  {r['name']}"
            for r in rows
        )
    else:
        text = "Заданий нет."
    return Result(data={"jobs": rows, "count": len(rows)}, text=text)


def cron_add(
    ctx: Context,
    *,
    name: str,
    schedule: str,
    prompt: Optional[str] = None,
    script: Optional[str] = None,
    no_agent: bool = False,
) -> Result:
    """Создать задание планировщика."""
    try:
        spec = parse_schedule(schedule)
    except Exception as exc:  # noqa: BLE001 — текст разбора расписания
        raise CliError(f"не удалось разобрать расписание: {exc}") from exc

    job = Job(
        id=new_job_id(),
        name=name,
        prompt=prompt,
        script=script,
        no_agent=no_agent,
        schedule=spec,
    )
    try:
        validate_job(job)
    except Exception as exc:  # noqa: BLE001 — текст валидации задания
        raise CliError(str(exc)) from exc

    store = ctx.job_store_factory(ctx.home)
    add_job(store, job)

    data = {
        "id": job.id,
        "name": job.name,
        "schedule": spec.display,
        "next_run": job.next_run,
    }
    text = f"Задание создано: {job.id} ({spec.display}), следующий запуск {job.next_run}"
    return Result(data=data, text=text)


def cron_tick(ctx: Context) -> Result:
    """Исполнить наступившие задания (один тик)."""
    store = ctx.job_store_factory(ctx.home)
    ticker = ctx.ticker_factory(store, ctx.home)
    result = ticker.tick()
    data = {
        "executed": list(result.executed),
        "quiet": list(result.quiet),
        "errors": list(result.errors),
        "expired": list(result.expired),
        "deferred_agent": list(result.deferred_agent),
    }
    text = (
        f"исполнено: {len(data['executed'])}, тихо: {len(data['quiet'])}, "
        f"ошибок: {len(data['errors'])}, просрочено: {len(data['expired'])}, "
        f"отложено агенту: {len(data['deferred_agent'])}"
    )
    return Result(data=data, text=text)


# --- политики безопасности -----------------------------------------------


def security_policy(ctx: Context) -> SecurityPolicy:
    """Политика безопасности профиля по его конфигурации."""
    return SecurityPolicy.from_config(ctx.config_loader(ctx.home).security)


def audit_for(ctx: Context, policy: Optional[SecurityPolicy] = None) -> AuditLog:
    """Журнал решений профиля (в каталоге логов профиля)."""
    active = policy or security_policy(ctx)
    return AuditLog(home=ctx.home, enabled=active.audit_enabled)


def security_show(ctx: Context) -> Result:
    """Показать действующие правила и границы слоя."""
    policy = security_policy(ctx)
    lines = [
        "Команды:",
        f"  запрет:   {', '.join(policy.command_deny) or '—'}",
        f"  разрешено: {', '.join(policy.command_allow) or '—'}",
        "Пути:",
        f"  запрет:   {', '.join(policy.path_deny) or '—'}",
        f"  разрешено: {', '.join(policy.path_allow) or '—'}",
        f"Аудит: {'включён' if policy.audit_enabled else 'выключен'}",
        "",
        SCOPE_NOTICE,
    ]
    return Result(data=policy.describe(), text="\n".join(lines))


def security_check(ctx: Context, command: str) -> Result:
    """Проверить решение по команде, не выполняя её."""
    policy = security_policy(ctx)
    decision = policy.check_command(command)
    audit_for(ctx, policy).record(decision, source="cli:security-check")
    text = f"{decision.decision.value}: {decision.reason}"
    if decision.label:
        text += f" ({decision.label})"
    return Result(data=decision.to_dict(), text=text)


def security_audit(ctx: Context, *, limit: int = DEFAULT_TAIL) -> Result:
    """Показать последние решения из журнала."""
    rows = audit_for(ctx).tail(limit)
    if rows:
        text = "\n".join(
            f"{r.get('at')}  {r.get('decision')}  {r.get('kind')}: "
            f"{r.get('subject')} — {r.get('reason')}"
            for r in rows
        )
    else:
        text = "Записей нет."
    return Result(data={"records": rows, "count": len(rows)}, text=text)


# --- снимки состояния ----------------------------------------------------


def checkpoint_store(ctx: Context) -> CheckpointStore:
    """Хранилище снимков профиля: конфигурация + политика путей."""
    config = ctx.config_loader(ctx.home)
    policy = SecurityPolicy.from_config(config.security)
    audit = audit_for(ctx, policy)

    def guard(path: str) -> Optional[str]:
        decision = policy.check_path(path)
        audit.record(decision, source="checkpoints")
        return None if decision.decision is Decision.ALLOW else decision.reason

    return CheckpointStore.from_config(ctx.home, config.checkpoints, path_guard=guard)


def checkpoints_list(ctx: Context) -> Result:
    """Перечислить снимки профиля."""
    rows = checkpoint_store(ctx).list()
    if rows:
        text = "\n".join(
            f"{r.get('id')}  {r.get('created_at') or '—'}  "
            f"{r.get('files') or 0} файл(ов)  {r.get('bytes') or 0} Б  "
            f"{r.get('label') or ''}".rstrip()
            for r in rows
        )
    else:
        text = "Снимков нет."
    return Result(data={"snapshots": rows, "count": len(rows)}, text=text)


def checkpoints_create(
    ctx: Context,
    paths: list[str],
    *,
    label: Optional[str] = None,
) -> Result:
    """Создать снимок указанных путей."""
    store = checkpoint_store(ctx)
    try:
        snapshot = store.create(paths, label=label or "")
    except CheckpointError as exc:
        raise CliError(str(exc)) from exc

    data = {"snapshot": snapshot.summary()}
    text = (
        f"Снимок создан: {snapshot.id} — записей {len(snapshot.entries)}, "
        f"файлов {snapshot.files}"
    )
    if snapshot.skipped:
        text += f", пропущено {len(snapshot.skipped)}"
    return Result(data=data, text=text)


def checkpoints_restore(
    ctx: Context,
    checkpoint_id: str,
    *,
    remove_extra: bool = False,
) -> Result:
    """Восстановить состояние из снимка."""
    store = checkpoint_store(ctx)
    try:
        report = store.restore(checkpoint_id, remove_extra=remove_extra)
    except CheckpointError as exc:
        raise CliError(str(exc)) from exc

    text = (
        f"Восстановлено: {len(report.restored)}, удалено: {len(report.removed)}, "
        f"ошибок: {len(report.errors)}"
    )
    if report.safety_id:
        text += f"\nстраховочный снимок: {report.safety_id}"
    return Result(data=report.to_dict(), text=text)


def checkpoints_prune(ctx: Context, *, keep: Optional[int] = None) -> Result:
    """Удалить старые снимки, оставив последние."""
    removed = checkpoint_store(ctx).prune(keep)
    return Result(data={"removed": removed}, text=f"Удалено снимков: {len(removed)}")


# --- внешние MCP-серверы -------------------------------------------------


def mcp_servers(ctx: Context) -> dict[str, McpServerConfig]:
    """Настроенные MCP-серверы профиля."""
    return parse_servers(ctx.config_loader(ctx.home).mcp)


def _require_server(ctx: Context, name: str) -> McpServerConfig:
    servers = mcp_servers(ctx)
    server = servers.get(name)
    if server is None:
        known = ", ".join(sorted(servers)) or "—"
        raise CliError(f"MCP-сервер {name!r} не найден в конфигурации. Настроены: {known}")
    return server


async def _with_client(server: McpServerConfig, action: Callable[[McpClient], Any]) -> Any:
    """Поднять сервер, выполнить действие, закрыть процесс."""
    client = McpClient(
        server.name,
        server.command,
        env=server.env,
        cwd=server.cwd,
        timeout=server.timeout,
    )
    try:
        await client.start()
        await client.initialize()
        return await action(client)
    finally:
        await client.close()


def mcp_list(ctx: Context) -> Result:
    """Перечислить настроенные MCP-серверы."""
    servers = mcp_servers(ctx)
    rows = [
        {
            "name": s.name,
            "command": list(s.command),
            "enabled": s.enabled,
            "timeout": s.timeout,
        }
        for s in sorted(servers.values(), key=lambda s: s.name)
    ]
    if rows:
        text = "\n".join(
            f"{'вкл ' if r['enabled'] else 'выкл'}  {r['name']}  {' '.join(r['command'])}"
            for r in rows
        )
    else:
        text = "MCP-серверы не настроены."
    return Result(data={"servers": rows, "count": len(rows)}, text=text)


def mcp_tools(ctx: Context, server_name: str) -> Result:
    """Перечислить инструменты MCP-сервера."""
    server = _require_server(ctx, server_name)
    tools = asyncio.run(_with_client(server, lambda client: client.list_tools()))
    rows = [
        {
            "name": tool.name,
            "registry_name": tool_name(server.name, tool.name),
            "description": tool.description,
        }
        for tool in tools
    ]
    if rows:
        text = "\n".join(
            f"{r['name']}  →  {r['registry_name']}  {r['description']}" for r in rows
        )
    else:
        text = f"Сервер {server.name}: инструментов нет."
    return Result(data={"server": server.name, "tools": rows, "count": len(rows)}, text=text)


def _parse_call_args(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CliError(f"--args не является валидным JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CliError("--args должен быть JSON-объектом")
    return data


def mcp_call(
    ctx: Context,
    server_name: str,
    tool: str,
    raw_args: Optional[str] = None,
) -> Result:
    """Вызвать инструмент MCP-сервера."""
    server = _require_server(ctx, server_name)
    arguments = _parse_call_args(raw_args)
    raw = asyncio.run(_with_client(server, lambda client: client.call_tool(tool, arguments)))
    payload: Any
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = raw

    if isinstance(payload, dict) and payload.get("isError"):
        raise CliError(
            str(payload.get("error") or f"инструмент {tool} вернул ошибку"),
            EXIT_RUNTIME,
        )

    if isinstance(payload, dict) and isinstance(payload.get("content"), list):
        text = "\n".join(str(part) for part in payload["content"])
    elif isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(payload, ensure_ascii=False, default=str)

    data = {"server": server.name, "tool": tool, "result": payload}
    return Result(data=data, text=text)


def tui_command(
    ctx: Context,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Result:
    """Запустить интерактивный терминальный интерфейс.

    Импорт `prokop.tui.app` ленивый: `prompt_toolkit` — опциональная
    зависимость (extra ``tui``), и её отсутствие не должно ломать импорт CLI.
    """
    from prokop.tui.app import run_tui

    run_tui(ctx, provider=provider, model=model)
    return Result(data={"tui": True}, text="")


def turn(
    ctx: Context,
    prompt: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Result:
    """Один ход агента через модель из конфигурации профиля."""
    profile, api_key, model_name = resolve_credentials(ctx, provider=provider, model=model)
    result = asyncio.run(run_turn_once(ctx, profile, api_key, model_name, prompt))
    if result.failed:
        raise CliError(result.error or "ход не завершён", EXIT_RUNTIME)

    text = result.final_response or ""
    data = {
        "response": text,
        "model": model_name,
        "provider": profile.name,
        "api_calls": result.api_calls,
    }
    return Result(data=data, text=text)


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):
        return False


def _read_line(ctx: Context) -> Optional[str]:
    """Прочитать строку; ``None`` — конец потока ввода."""
    if _is_tty(ctx.stdin):
        print("> ", end="", file=ctx.stdout, flush=True)
    line = ctx.stdin.readline()
    if line == "":
        return None
    return line


def chat(
    ctx: Context,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Result:
    """Линейный цикл «запрос → ход → ответ» в рамках одной сессии."""
    profile, api_key, model_name = resolve_credentials(ctx, provider=provider, model=model)

    history: Optional[list[Any]] = None
    turns = 0
    while True:
        line = _read_line(ctx)
        if line is None:
            break
        text = line.strip()
        if not text:
            continue
        if text.lower() in _EXIT_WORDS:
            break
        result = asyncio.run(
            run_turn_once(ctx, profile, api_key, model_name, text, history=history)
        )
        if result.failed:
            raise CliError(result.error or "ход не завершён", EXIT_RUNTIME)
        history = result.messages
        turns += 1
        print(result.final_response or "", file=ctx.stdout, flush=True)

    return Result(data={"turns": turns, "model": model_name}, text="")
