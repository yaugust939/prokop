"""Тесты терминального интерфейса.

Рендеринг не проверяется (в CI нет терминала): покрыты чистая логика
(состояние, слэш-команды), деградация, запись хода в хранилище сессий и
поведение цикла при ошибке хода. Цикл проверяется с подменённым читателем
строк — без `prompt_toolkit` и без TTY.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from prokop.cli.commands import Context
from prokop.config import Config
from prokop.providers.registry import ProviderRegistry
from prokop.store.sessions import SessionStore
from prokop.tui import app as tui_app
from prokop.tui.state import (
    ACTION_HANDLED,
    ACTION_PROMPT,
    ACTION_QUIT,
    TuiState,
    handle_command,
)


# --- чистая логика: состояние и команды -----------------------------------


def make_state(**kwargs: Any) -> TuiState:
    defaults: dict[str, Any] = {"provider": "deepseek", "model": "deepseek-chat"}
    defaults.update(kwargs)
    return TuiState(**defaults)


def test_plain_text_goes_to_model():
    outcome = handle_command("  привет мир  ", make_state())
    assert outcome.action == ACTION_PROMPT
    assert outcome.text == "привет мир"


def test_empty_line_is_handled_without_output():
    outcome = handle_command("   ", make_state())
    assert outcome.action == ACTION_HANDLED
    assert outcome.text == ""


@pytest.mark.parametrize("command", ["/quit", "/exit", "/q", "/QUIT"])
def test_quit_commands(command):
    assert handle_command(command, make_state()).action == ACTION_QUIT


def test_help_lists_commands():
    outcome = handle_command("/help", make_state())
    assert outcome.action == ACTION_HANDLED
    for command in ("/model", "/provider", "/new", "/sessions", "/clear", "/quit"):
        assert command in outcome.text


def test_status_line_contains_context():
    state = make_state(session_id="abcdef123456", turns=3)
    line = state.status_line()
    assert "deepseek/deepseek-chat" in line
    assert "abcdef12" in line
    assert "3" in line

    outcome = handle_command("/status", state)
    assert "deepseek/deepseek-chat" in outcome.text


def test_model_show_and_set():
    state = make_state()
    assert "deepseek-chat" in handle_command("/model", state).text

    outcome = handle_command("/model gpt-4o", state)
    assert state.model == "gpt-4o"
    assert "gpt-4o" in outcome.text


def test_provider_show_set_and_unknown():
    state = make_state()
    assert "deepseek" in handle_command("/provider", state).text

    outcome = handle_command("/provider openrouter", state, providers=["deepseek", "openrouter"])
    assert outcome.error is False
    assert state.provider == "openrouter"

    outcome = handle_command("/provider нет-такого", state, providers=["deepseek"])
    assert outcome.error is True
    assert "неизвестный провайдер" in outcome.text
    assert state.provider == "openrouter"  # не изменился


def test_new_resets_session():
    state = make_state(session_id="sid", turns=5, history=[{"a": 1}])
    outcome = handle_command("/new", state)
    assert outcome.action == ACTION_HANDLED
    assert state.session_id is None
    assert state.turns == 0
    assert state.history == []


def test_clear_keeps_session_and_turns():
    state = make_state(session_id="sid", turns=5, history=[{"a": 1}])
    handle_command("/clear", state)
    assert state.history == []
    assert state.session_id == "sid"
    assert state.turns == 5


def test_sessions_listing():
    state = make_state()
    empty = handle_command("/sessions", state, sessions=[])
    assert "нет" in empty.text.lower()

    rows = [{"id": "abcdef123456", "last_activity": "2026-09-22", "message_count": 4}]
    filled = handle_command("/sessions", state, sessions=rows)
    assert "abcdef12" in filled.text
    assert "4" in filled.text


def test_unknown_command_is_reported_without_quitting():
    outcome = handle_command("/wat", make_state())
    assert outcome.action == ACTION_HANDLED
    assert outcome.error is True
    assert "/help" in outcome.text


def test_state_module_does_not_import_prompt_toolkit():
    """Чистая логика обязана быть тестируемой без терминальной зависимости."""
    import prokop.tui.state as state_module

    source = Path(state_module.__file__).read_text(encoding="utf-8")
    assert "import prompt_toolkit" not in source
    assert "from prompt_toolkit" not in source


def test_tui_package_import_does_not_require_prompt_toolkit():
    import prokop.tui as tui_package

    source = Path(tui_package.__file__).read_text(encoding="utf-8")
    assert "from prokop.tui.app" not in source


# --- деградация -----------------------------------------------------------


def make_ctx(tmp_path: Path, *, tty: bool = False, env: Optional[dict[str, str]] = None) -> Context:
    def loader(home: Path) -> Config:
        config = Config()
        config.model.provider = "deepseek"
        config.model.model = "deepseek-chat"
        return config

    stdin = io.StringIO("")
    if tty:
        stdin.isatty = lambda: True  # type: ignore[method-assign]

    return Context(
        home=tmp_path / "home",
        profile="test",
        env=env if env is not None else {"DEEPSEEK_API_KEY": "k"},
        stdin=stdin,  # type: ignore[arg-type]
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        config_loader=loader,
    )


def test_missing_dependency_degrades(tmp_path, monkeypatch):
    from prokop.cli.commands import CliError

    monkeypatch.setattr(tui_app, "prompt_toolkit_available", lambda: False)
    ctx = make_ctx(tmp_path, tty=True)
    with pytest.raises(CliError) as exc:
        tui_app.run_tui(ctx)
    assert "prompt_toolkit" in str(exc.value)
    assert "prokop[tui]" in str(exc.value)
    assert "prokop chat" in str(exc.value)


def test_without_tty_refuses(tmp_path):
    from prokop.cli.commands import CliError

    ctx = make_ctx(tmp_path, tty=False)
    with pytest.raises(CliError) as exc:
        tui_app.run_tui(ctx)
    assert "терминал" in str(exc.value)


def test_without_key_refuses(tmp_path, monkeypatch):
    from prokop.cli.commands import CliError

    # Тест про ключ, а не про окружение: зависимость считаем доступной, иначе
    # на машине без extra `tui` проверка ключа просто не достигается.
    monkeypatch.setattr(tui_app, "prompt_toolkit_available", lambda: True)
    ctx = make_ctx(tmp_path, tty=True, env={})
    with pytest.raises(CliError) as exc:
        tui_app.run_tui(ctx)
    assert "ключ" in str(exc.value)


# --- цикл -----------------------------------------------------------------


@dataclass
class FakeTurnResult:
    final_response: Optional[str] = None
    messages: list[Any] = None  # type: ignore[assignment]
    api_calls: int = 1
    completed: bool = True
    failed: bool = False
    error: Optional[str] = None

    def __post_init__(self) -> None:
        if self.messages is None:
            self.messages = []


class FakeTransport:
    def __init__(self, profile: Any, api_key: Optional[str] = None, timeout: float = 0.0) -> None:
        pass

    async def close(self) -> None:
        pass


class FakeTurn:
    """Цикл хода-заглушка; поведение задаётся классом."""

    fail_with: Optional[str] = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def run(self, prompt: str) -> FakeTurnResult:
        if FakeTurn.fail_with:
            return FakeTurnResult(failed=True, error=FakeTurn.fail_with, completed=False)
        return FakeTurnResult(
            final_response=f"эхо: {prompt}",
            messages=[{"role": "user", "content": prompt}],
        )


@pytest.fixture(autouse=True)
def _reset_fakes():
    FakeTurn.fail_with = None
    yield
    FakeTurn.fail_with = None


def make_loop_ctx(tmp_path: Path) -> Context:
    ctx = make_ctx(tmp_path)
    ctx.transport_factory = FakeTransport  # type: ignore[assignment]
    ctx.turn_factory = FakeTurn  # type: ignore[assignment]
    return ctx


def scripted_reader(lines: list[str]):
    """Читатель строк: отдаёт строки по очереди, затем конец ввода."""
    pending = list(lines)

    def read_line(state: TuiState) -> str:
        if not pending:
            raise EOFError
        return pending.pop(0)

    return read_line


def test_loop_records_session_and_turns(tmp_path):
    ctx = make_loop_ctx(tmp_path)
    registry = ProviderRegistry()
    registry.discover()
    profile = registry.get("deepseek")

    tui_app._loop(
        ctx,
        profile,
        "k",
        "deepseek-chat",
        read_line=scripted_reader(["привет", "/quit"]),
    )

    assert "эхо: привет" in ctx.stdout.getvalue()

    store = SessionStore(ctx.home)
    try:
        sessions = store.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["source"] == "tui"

        messages = store.get_messages(sessions[0]["id"])
        roles = [m["role"] for m in messages]
        assert roles == ["user", "assistant"]
        assert messages[0]["content"] == "привет"
        assert messages[1]["content"] == "эхо: привет"
    finally:
        store.close()


def test_loop_handles_commands_without_turns(tmp_path):
    ctx = make_loop_ctx(tmp_path)
    registry = ProviderRegistry()
    registry.discover()

    tui_app._loop(
        ctx,
        registry.get("deepseek"),
        "k",
        "deepseek-chat",
        read_line=scripted_reader(["/help", "/status", "/model gpt", "/quit"]),
    )

    output = ctx.stdout.getvalue()
    assert "/help" in output
    assert "модель переключена: gpt" in output

    store = SessionStore(ctx.home)
    try:
        # Ни одного хода — сессия не создавалась.
        assert store.list_sessions() == []
    finally:
        store.close()


def test_loop_new_starts_fresh_session(tmp_path):
    ctx = make_loop_ctx(tmp_path)
    registry = ProviderRegistry()
    registry.discover()

    tui_app._loop(
        ctx,
        registry.get("deepseek"),
        "k",
        "deepseek-chat",
        read_line=scripted_reader(["первый", "/new", "второй", "/quit"]),
    )

    store = SessionStore(ctx.home)
    try:
        sessions = store.list_sessions()
        assert len(sessions) == 2
    finally:
        store.close()


def test_loop_survives_turn_error(tmp_path):
    FakeTurn.fail_with = "модель недоступна"
    ctx = make_loop_ctx(tmp_path)
    registry = ProviderRegistry()
    registry.discover()

    tui_app._loop(
        ctx,
        registry.get("deepseek"),
        "k",
        "deepseek-chat",
        read_line=scripted_reader(["привет", "ещё раз", "/quit"]),
    )

    output = ctx.stdout.getvalue()
    assert output.count("модель недоступна") == 2  # ошибка не выбила из цикла


def test_loop_ends_at_eof(tmp_path):
    ctx = make_loop_ctx(tmp_path)
    registry = ProviderRegistry()
    registry.discover()

    tui_app._loop(
        ctx,
        registry.get("deepseek"),
        "k",
        "deepseek-chat",
        read_line=scripted_reader(["привет"]),
    )
    assert "эхо: привет" in ctx.stdout.getvalue()


# --- CLI ------------------------------------------------------------------


def test_cli_tui_help():
    from prokop.cli.main import EXIT_OK, main

    assert main(["tui", "--help"]) == EXIT_OK


def test_cli_tui_without_tty(tmp_path):
    from prokop.cli.main import EXIT_USAGE, main

    ctx = make_ctx(tmp_path, tty=False)
    assert main(["tui"], context=ctx) == EXIT_USAGE
    assert "терминал" in ctx.stderr.getvalue()


def test_tui_sources_have_no_personal_paths():
    package = Path(tui_app.__file__).resolve().parent
    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    offenders = []
    for file in package.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(package)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"
