"""Точка входа командной строки `prokop`.

Разбор аргументов, диспетчеризация команд, форматы вывода и коды возврата.
Логика команд живёт в :mod:`prokop.cli.commands`; здесь только каркас.

Коды возврата: ``0`` — успех, ``1`` — ошибка пользователя или конфигурации,
``2`` — ошибка исполнения.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional, Sequence

from prokop import __version__
from prokop.cli import commands
from prokop.cli.commands import EXIT_RUNTIME, EXIT_USAGE, CliError, Context, Result
from prokop.cli.stdio import configure_stdio

#: Код возврата при успехе.
EXIT_OK = 0


class _ArgumentParser(argparse.ArgumentParser):
    """Парсер, не завершающий процесс: ошибка ввода → код ``1``."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise CliError(f"{self.prog}: {message}", EXIT_USAGE)


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    """Флаг `--json` доступен и после подкоманды (глобальное значение важнее)."""
    parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="машиночитаемый вывод (JSON)",
    )


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер команд."""
    parser = _ArgumentParser(
        prog="prokop",
        description="prokop — универсальное ядро агента: ход, сессии, планировщик, навыки.",
    )
    parser.add_argument(
        "--version", action="version", version=f"prokop {__version__}"
    )
    parser.add_argument(
        "--json", action="store_true", default=False,
        help="машиночитаемый вывод (JSON)",
    )
    sub = parser.add_subparsers(dest="command", metavar="<команда>")

    # doctor
    doctor_p = sub.add_parser("doctor", help="проверить окружение профиля")
    _add_json_flag(doctor_p)

    # config show
    config_p = sub.add_parser("config", help="конфигурация профиля")
    config_sub = config_p.add_subparsers(dest="config_command", metavar="<подкоманда>")
    config_show_p = config_sub.add_parser("show", help="показать конфигурацию")
    _add_json_flag(config_show_p)

    # sessions
    sessions_p = sub.add_parser("sessions", help="сессии профиля")
    sessions_sub = sessions_p.add_subparsers(dest="sessions_command", metavar="<подкоманда>")
    sessions_list_p = sessions_sub.add_parser("list", help="перечислить сессии")
    _add_json_flag(sessions_list_p)
    sessions_show_p = sessions_sub.add_parser("show", help="показать сессию")
    sessions_show_p.add_argument("session_id", help="идентификатор сессии")
    _add_json_flag(sessions_show_p)
    sessions_search_p = sessions_sub.add_parser("search", help="поиск по сообщениям")
    sessions_search_p.add_argument("query", help="поисковая строка")
    sessions_search_p.add_argument("--limit", type=int, default=20)
    _add_json_flag(sessions_search_p)

    # skills list
    skills_p = sub.add_parser("skills", help="навыки профиля")
    skills_sub = skills_p.add_subparsers(dest="skills_command", metavar="<подкоманда>")
    skills_list_p = skills_sub.add_parser("list", help="перечислить навыки")
    _add_json_flag(skills_list_p)

    # providers list
    providers_p = sub.add_parser("providers", help="провайдеры моделей")
    providers_sub = providers_p.add_subparsers(dest="providers_command", metavar="<подкоманда>")
    providers_list_p = providers_sub.add_parser("list", help="перечислить провайдеры")
    _add_json_flag(providers_list_p)

    # cron
    cron_p = sub.add_parser("cron", help="планировщик")
    cron_sub = cron_p.add_subparsers(dest="cron_command", metavar="<подкоманда>")
    cron_list_p = cron_sub.add_parser("list", help="перечислить задания")
    _add_json_flag(cron_list_p)
    cron_add_p = cron_sub.add_parser("add", help="создать задание")
    cron_add_p.add_argument("--name", required=True, help="имя задания")
    cron_add_p.add_argument("--schedule", required=True, help="расписание")
    cron_add_p.add_argument("--prompt", help="промпт (задание с агентом)")
    cron_add_p.add_argument("--script", help="скрипт (задание без агента)")
    cron_add_p.add_argument("--no-agent", action="store_true", help="исполнять без агента")
    _add_json_flag(cron_add_p)
    cron_tick_p = cron_sub.add_parser("tick", help="исполнить наступившие задания")
    _add_json_flag(cron_tick_p)

    # mcp
    mcp_p = sub.add_parser("mcp", help="внешние MCP-серверы")
    mcp_sub = mcp_p.add_subparsers(dest="mcp_command", metavar="<подкоманда>")
    mcp_list_p = mcp_sub.add_parser("list", help="перечислить настроенные серверы")
    _add_json_flag(mcp_list_p)
    mcp_tools_p = mcp_sub.add_parser("tools", help="инструменты сервера")
    mcp_tools_p.add_argument("server", help="имя сервера")
    _add_json_flag(mcp_tools_p)
    mcp_call_p = mcp_sub.add_parser("call", help="вызвать инструмент сервера")
    mcp_call_p.add_argument("server", help="имя сервера")
    mcp_call_p.add_argument("tool", help="имя инструмента на сервере")
    mcp_call_p.add_argument("--args", help="аргументы вызова как JSON-объект")
    _add_json_flag(mcp_call_p)

    # security
    sec_p = sub.add_parser("security", help="политики безопасности")
    sec_sub = sec_p.add_subparsers(dest="security_command", metavar="<подкоманда>")
    sec_show_p = sec_sub.add_parser("show", help="показать действующие правила")
    _add_json_flag(sec_show_p)
    sec_check_p = sec_sub.add_parser("check", help="проверить команду без выполнения")
    # Имя dest отличается от ``command``: иначе позиционный аргумент перетирает
    # dest верхнего парсера подкоманд.
    sec_check_p.add_argument("command_text", metavar="<команда>", help="команда для проверки")
    _add_json_flag(sec_check_p)
    sec_audit_p = sec_sub.add_parser("audit", help="журнал решений")
    sec_audit_p.add_argument("--limit", type=int, default=50, help="сколько записей")
    _add_json_flag(sec_audit_p)

    # checkpoints
    cp_p = sub.add_parser("checkpoints", help="снимки состояния и откат")
    cp_sub = cp_p.add_subparsers(dest="checkpoints_command", metavar="<подкоманда>")
    cp_list_p = cp_sub.add_parser("list", help="перечислить снимки")
    _add_json_flag(cp_list_p)
    cp_create_p = cp_sub.add_parser("create", help="создать снимок")
    cp_create_p.add_argument("paths", nargs="+", help="пути для снимка")
    cp_create_p.add_argument("--label", help="метка снимка")
    _add_json_flag(cp_create_p)
    cp_restore_p = cp_sub.add_parser("restore", help="восстановить из снимка")
    cp_restore_p.add_argument("checkpoint_id", help="идентификатор снимка")
    cp_restore_p.add_argument(
        "--remove-extra",
        action="store_true",
        help="удалить файлы, появившиеся после снимка",
    )
    _add_json_flag(cp_restore_p)
    cp_prune_p = cp_sub.add_parser("prune", help="удалить старые снимки")
    cp_prune_p.add_argument("--keep", type=int, help="сколько последних оставить")
    _add_json_flag(cp_prune_p)

    # turn
    turn_p = sub.add_parser("turn", help="один ход агента")
    turn_p.add_argument("prompt", help="запрос к агенту")
    turn_p.add_argument("--model", help="модель (иначе из конфигурации)")
    turn_p.add_argument("--provider", help="провайдер (иначе из конфигурации)")
    _add_json_flag(turn_p)

    # chat
    chat_p = sub.add_parser("chat", help="интерактивный цикл ходов")
    chat_p.add_argument("--model", help="модель (иначе из конфигурации)")
    chat_p.add_argument("--provider", help="провайдер (иначе из конфигурации)")
    _add_json_flag(chat_p)

    # tui
    tui_p = sub.add_parser("tui", help="терминальный интерфейс (extra tui)")
    tui_p.add_argument("--model", help="модель (иначе из конфигурации)")
    tui_p.add_argument("--provider", help="провайдер (иначе из конфигурации)")
    _add_json_flag(tui_p)

    return parser


def _require_subcommand(value: Optional[str], command: str, options: str) -> str:
    if value:
        return value
    raise CliError(f"укажите подкоманду: {command} {options}", EXIT_USAGE)


def dispatch(args: argparse.Namespace, ctx: Context) -> Result:
    """Вызвать реализацию выбранной команды."""
    command = args.command

    if command == "doctor":
        return commands.doctor(ctx)

    if command == "config":
        sub = _require_subcommand(args.config_command, "config", "show")
        if sub == "show":
            return commands.config_show(ctx)
        raise CliError(f"неизвестная подкоманда config {sub!r}", EXIT_USAGE)

    if command == "sessions":
        sub = _require_subcommand(
            args.sessions_command, "sessions", "list|show <id>|search <запрос>"
        )
        if sub == "list":
            return commands.sessions_list(ctx)
        if sub == "show":
            return commands.sessions_show(ctx, args.session_id)
        if sub == "search":
            return commands.sessions_search(ctx, args.query, limit=args.limit)
        raise CliError(f"неизвестная подкоманда sessions {sub!r}", EXIT_USAGE)

    if command == "skills":
        sub = _require_subcommand(args.skills_command, "skills", "list")
        if sub == "list":
            return commands.skills_list(ctx)
        raise CliError(f"неизвестная подкоманда skills {sub!r}", EXIT_USAGE)

    if command == "providers":
        sub = _require_subcommand(args.providers_command, "providers", "list")
        if sub == "list":
            return commands.providers_list(ctx)
        raise CliError(f"неизвестная подкоманда providers {sub!r}", EXIT_USAGE)

    if command == "cron":
        sub = _require_subcommand(args.cron_command, "cron", "list|add|tick")
        if sub == "list":
            return commands.cron_list(ctx)
        if sub == "add":
            return commands.cron_add(
                ctx,
                name=args.name,
                schedule=args.schedule,
                prompt=args.prompt,
                script=args.script,
                no_agent=bool(args.no_agent),
            )
        if sub == "tick":
            return commands.cron_tick(ctx)
        raise CliError(f"неизвестная подкоманда cron {sub!r}", EXIT_USAGE)

    if command == "security":
        sub = _require_subcommand(args.security_command, "security", "show|check <команда>|audit")
        if sub == "show":
            return commands.security_show(ctx)
        if sub == "check":
            return commands.security_check(ctx, args.command_text)
        if sub == "audit":
            return commands.security_audit(ctx, limit=args.limit)
        raise CliError(f"неизвестная подкоманда security {sub!r}", EXIT_USAGE)

    if command == "checkpoints":
        sub = _require_subcommand(
            args.checkpoints_command,
            "checkpoints",
            "list|create <пути>|restore <id>|prune",
        )
        if sub == "list":
            return commands.checkpoints_list(ctx)
        if sub == "create":
            return commands.checkpoints_create(ctx, args.paths, label=args.label)
        if sub == "restore":
            return commands.checkpoints_restore(
                ctx, args.checkpoint_id, remove_extra=bool(args.remove_extra)
            )
        if sub == "prune":
            return commands.checkpoints_prune(ctx, keep=args.keep)
        raise CliError(f"неизвестная подкоманда checkpoints {sub!r}", EXIT_USAGE)

    if command == "mcp":
        sub = _require_subcommand(args.mcp_command, "mcp", "list|tools <сервер>|call <сервер> <инструмент>")
        if sub == "list":
            return commands.mcp_list(ctx)
        if sub == "tools":
            return commands.mcp_tools(ctx, args.server)
        if sub == "call":
            return commands.mcp_call(ctx, args.server, args.tool, args.args)
        raise CliError(f"неизвестная подкоманда mcp {sub!r}", EXIT_USAGE)

    if command == "turn":
        return commands.turn(
            ctx, args.prompt, provider=args.provider, model=args.model
        )

    if command == "chat":
        return commands.chat(ctx, provider=args.provider, model=args.model)

    if command == "tui":
        return commands.tui_command(ctx, provider=args.provider, model=args.model)

    raise CliError(f"неизвестная команда: {command!r}", EXIT_USAGE)


def _emit(result: Result, *, as_json: bool, ctx: Context) -> None:
    """Напечатать результат в выбранном формате."""
    if as_json:
        payload: Any = result.data if result.data is not None else {}
        print(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            file=ctx.stdout,
        )
    elif result.text:
        print(result.text, file=ctx.stdout)


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    context: Optional[Context] = None,
) -> int:
    """Точка входа CLI. Возвращает код возврата процесса."""
    configure_stdio()
    parser = build_parser()

    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:  # --help/--version
        return int(exc.code or EXIT_OK)
    except CliError as exc:
        # Контекст создаётся только на ошибке разбора: `--version` и `--help`
        # не должны трогать профиль на диске.
        error_ctx = context if context is not None else commands.make_context()
        print(f"ошибка: {exc}", file=error_ctx.stderr)
        return exc.code

    ctx = context if context is not None else commands.make_context()

    if args.command is None:
        parser.print_help(file=ctx.stdout)
        return EXIT_OK

    try:
        result = dispatch(args, ctx)
    except CliError as exc:
        print(f"ошибка: {exc}", file=ctx.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("прервано", file=ctx.stderr)
        return EXIT_RUNTIME
    except Exception as exc:  # noqa: BLE001 — ошибка исполнения не должна ронять CLI
        print(f"ошибка исполнения: {exc}", file=ctx.stderr)
        return EXIT_RUNTIME

    _emit(result, as_json=bool(getattr(args, "json", False)), ctx=ctx)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
