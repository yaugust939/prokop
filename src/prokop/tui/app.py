"""Интерактивный терминальный интерфейс на `prompt_toolkit`.

Тонкий слой поверх ядра: цикл ввода, потоковый вывод ответа и запись хода в
хранилище сессий. Логика состояния и разбор команд — в
:mod:`prokop.tui.state`; здесь только рендеринг и ввод-вывод.

`prompt_toolkit` — опциональная зависимость (extra ``tui``): импорт ленивый,
при отсутствии пакета команда сообщает, как его установить, и предлагает
линейный режим.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, TextIO

from prokop.cli.commands import (
    EXIT_USAGE,
    CliError,
    Context,
    resolve_credentials,
    run_turn_once,
)
from prokop.loop.streaming import StreamCallbacks
from prokop.store.sessions import SessionStore
from prokop.tui.state import (
    ACTION_HANDLED,
    ACTION_PROMPT,
    ACTION_QUIT,
    TuiState,
    handle_command,
)

#: Подсказка по установке опциональной зависимости.
INSTALL_HINT = "pip install prokop[tui]"

#: Сколько последних сессий показывать по `/sessions`.
SESSIONS_LIMIT = 20


def prompt_toolkit_available() -> bool:
    """Установлен ли `prompt_toolkit` (без исключений наружу)."""
    try:
        import prompt_toolkit  # noqa: F401
    except Exception:  # noqa: BLE001 — отсутствие пакета не ошибка импорта
        return False
    return True


def _is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if isatty is None:
        return False
    try:
        return bool(isatty())
    except (ValueError, OSError):
        return False


def _print(ctx: Context, text: str) -> None:
    print(text, file=ctx.stdout, flush=True)


def _session_rows(store: SessionStore) -> list[dict[str, Any]]:
    try:
        return store.list_sessions()[:SESSIONS_LIMIT]
    except Exception:  # noqa: BLE001 — список сессий не критичен для цикла
        return []


def _ensure_session(store: SessionStore, state: TuiState) -> None:
    """Создать сессию, если её ещё нет (старт или после `/new`)."""
    if state.session_id:
        return
    state.session_id = store.create_session(
        source="tui",
        model=state.model,
        model_config={"provider": state.provider},
    )


def run_tui(
    ctx: Context,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """Запустить интерактивный интерфейс.

    Бросает :class:`CliError`, если недоступна зависимость, нет терминала или
    не разрешаются провайдер и ключ модели.
    """
    # Порядок проверок: сначала терминал, потом зависимость. Без терминала
    # TUI невозможен независимо от того, установлен ли prompt_toolkit, и
    # подсказка про extra в этом случае вводила бы в заблуждение.
    if not _is_tty(ctx.stdin):
        raise CliError(
            "TUI требует интерактивный терминал. "
            "Для потокового ввода используйте `prokop chat`.",
            EXIT_USAGE,
        )
    if not prompt_toolkit_available():
        raise CliError(
            "TUI недоступен: не установлен prompt_toolkit. "
            f"Установите extra: {INSTALL_HINT}. "
            "Либо используйте линейный режим: prokop chat",
            EXIT_USAGE,
        )

    profile, api_key, model_name = resolve_credentials(
        ctx, provider=provider, model=model
    )
    _loop(ctx, profile, api_key, model_name)


def _prompt_toolkit_reader():
    """Читатель строк на `prompt_toolkit` (импорт ленивый)."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import InMemoryHistory

    session = PromptSession(history=InMemoryHistory())

    def read_line(state: TuiState) -> str:
        return session.prompt("prokop> ", bottom_toolbar=lambda: state.status_line())

    return read_line


def _loop(
    ctx: Context,
    profile: Any,
    api_key: str,
    model_name: str,
    *,
    read_line: Any = None,
) -> None:
    """Цикл интерфейса: ввод → разбор → ход → вывод.

    ``read_line`` принимает состояние и возвращает строку; конец ввода —
    исключение ``EOFError``. Параметр нужен тестам: цикл проверяется без
    терминала и без `prompt_toolkit`.
    """
    reader = read_line if read_line is not None else _prompt_toolkit_reader()

    registry = ctx.registry_factory()
    registry.discover()
    provider_names = registry.names()

    store = ctx.session_store_factory(ctx.home)
    state = TuiState(provider=profile.name, model=model_name)

    current_profile = profile
    current_key = api_key
    current_model = model_name

    try:
        while True:
            try:
                line = reader(state)
            except (EOFError, KeyboardInterrupt):
                break

            outcome = handle_command(
                line,
                state,
                providers=provider_names,
                sessions=_session_rows(store),
            )

            if outcome.action == ACTION_QUIT:
                break

            if outcome.action == ACTION_HANDLED:
                if outcome.text:
                    _print(ctx, outcome.text)
                if state.provider != current_profile.name or state.model != current_model:
                    try:
                        current_profile, current_key, current_model = resolve_credentials(
                            ctx, provider=state.provider, model=state.model
                        )
                    except CliError as exc:
                        _print(ctx, f"ошибка: {exc}")
                        state.provider = current_profile.name
                        state.model = current_model
                continue

            if outcome.action != ACTION_PROMPT:
                continue

            _ensure_session(store, state)
            if state.session_id:
                store.add_message(state.session_id, "user", outcome.text)

            streamed: list[str] = []

            def on_text(delta: str) -> None:
                streamed.append(delta)
                _stream(ctx, delta)

            result = asyncio.run(
                run_turn_once(
                    ctx,
                    current_profile,
                    current_key,
                    current_model,
                    outcome.text,
                    history=state.history,
                    callbacks=StreamCallbacks(on_text=on_text),
                )
            )

            if result.failed:
                _print(ctx, f"\nошибка: {result.error or 'ход не завершён'}")
            else:
                text = result.final_response or ""
                if streamed:
                    _print(ctx, "")
                elif text:
                    # Провайдер без стриминга: печатаем готовый ответ.
                    _print(ctx, text)
                if state.session_id:
                    store.add_message(state.session_id, "assistant", text)
                state.turns += 1

            state.history = list(result.messages or [])
    finally:
        store.close()


def _stream(ctx: Context, delta: str) -> None:
    """Напечатать дельту ответа без перевода строки."""
    print(delta, end="", file=ctx.stdout, flush=True)
