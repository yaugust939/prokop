"""Тесты командной строки `prokop`.

Сеть и ключи модели не используются: транспорт и цикл хода подменяются
фейками через поля-фабрики :class:`prokop.cli.commands.Context`.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest

from prokop.cli import commands
from prokop.cli.commands import EXIT_RUNTIME, EXIT_USAGE, CliError, Context
from prokop.cli.main import EXIT_OK, main
from prokop.config import Config


# --- вспомогательное ------------------------------------------------------


@dataclass
class FakeTurnResult:
    """Минимальный результат хода для фейкового цикла."""

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
    """Транспорт-заглушка (закрывается без сети)."""

    def __init__(self, profile: Any, api_key: Optional[str] = None, timeout: float = 0.0) -> None:
        self.profile = profile
        self.api_key = api_key
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeTurn:
    """Цикл хода-заглушка: эхо запроса."""

    last_history: Any = None
    fail_with: Optional[str] = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def run(self, prompt: str) -> FakeTurnResult:
        FakeTurn.last_history = self.kwargs.get("history")
        if FakeTurn.fail_with:
            return FakeTurnResult(failed=True, error=FakeTurn.fail_with, completed=False)
        return FakeTurnResult(
            final_response=f"эхо: {prompt}",
            messages=[{"role": "user", "content": prompt}],
        )


def fake_config_loader(home: Path) -> Config:
    config = Config()
    config.model.provider = "deepseek"
    config.model.model = "deepseek-chat"
    return config


def make_ctx(
    tmp_path: Path,
    *,
    stdin_text: str = "",
    env: Optional[dict[str, str]] = None,
    **overrides: Any,
) -> Context:
    """Контекст с временным профилем, подменёнными потоками и фабриками."""
    ctx = Context(
        home=tmp_path / "home",
        profile="test",
        env=env if env is not None else {},
        stdin=io.StringIO(stdin_text),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        config_loader=fake_config_loader,
        transport_factory=FakeTransport,
        turn_factory=FakeTurn,
    )
    for name, value in overrides.items():
        setattr(ctx, name, value)
    return ctx


def out(ctx: Context) -> str:
    return ctx.stdout.getvalue()


def err(ctx: Context) -> str:
    return ctx.stderr.getvalue()


@pytest.fixture(autouse=True)
def _reset_fakes():
    FakeTurn.fail_with = None
    FakeTurn.last_history = None
    yield
    FakeTurn.fail_with = None
    FakeTurn.last_history = None


# --- каркас: версия, справка, разбор аргументов ---------------------------


def test_version_returns_zero(tmp_path):
    assert main(["--version"]) == EXIT_OK


def test_help_without_arguments(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main([], context=ctx) == EXIT_OK
    assert "usage: prokop" in out(ctx)
    assert "sessions" in out(ctx)


def test_unknown_command_is_usage_error(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["nope"], context=ctx) == EXIT_USAGE
    assert "ошибка" in err(ctx)


def test_missing_required_argument_is_usage_error(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["sessions", "show"], context=ctx) == EXIT_USAGE
    assert "session_id" in err(ctx)


def test_missing_subcommand_is_usage_error(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["sessions"], context=ctx) == EXIT_USAGE
    assert "укажите подкоманду" in err(ctx)


def test_console_script_is_declared():
    pyproject = Path(commands.__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "[project.scripts]" in text
    assert 'prokop = "prokop.cli.main:main"' in text


# --- форматы вывода -------------------------------------------------------


def test_json_output_is_valid_and_keeps_cyrillic(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["cron", "add", "--name", "проверка", "--schedule", "каждые 2ч",
                 "--prompt", "скажи привет"], context=ctx) == EXIT_OK

    ctx2 = make_ctx(tmp_path, env={})
    assert main(["--json", "cron", "list"], context=ctx2) == EXIT_OK
    payload = json.loads(out(ctx2))
    assert payload["count"] == 1
    assert payload["jobs"][0]["name"] == "проверка"
    assert "проверка" in out(ctx2), "кириллица не должна экранироваться"
    assert "\\u" not in out(ctx2)


def test_json_flag_works_after_subcommand(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["providers", "list", "--json"], context=ctx) == EXIT_OK
    payload = json.loads(out(ctx))
    assert any(p["name"] == "deepseek" for p in payload["providers"])


def test_text_mode_is_default(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["providers", "list"], context=ctx) == EXIT_OK
    assert "deepseek" in out(ctx)
    with pytest.raises(json.JSONDecodeError):
        json.loads(out(ctx))


# --- локальные команды (без сети и ключа) ---------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["doctor"],
        ["config", "show"],
        ["sessions", "list"],
        ["skills", "list"],
        ["providers", "list"],
        ["cron", "list"],
        ["cron", "tick"],
    ],
)
def test_local_commands_work_without_key(tmp_path, argv):
    ctx = make_ctx(tmp_path, env={})
    assert main(argv, context=ctx) == EXIT_OK, err(ctx)


def test_config_show_reports_profile(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["config", "show"], context=ctx) == EXIT_OK
    assert str(tmp_path / "home") in out(ctx)
    assert "test" in out(ctx)


def test_doctor_reports_checks(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["doctor"], context=ctx) == EXIT_OK
    assert "python" in out(ctx)
    assert "профиль" in out(ctx)


def test_sessions_show_unknown_is_usage_error(tmp_path):
    ctx = make_ctx(tmp_path)
    assert main(["sessions", "show", "нет-такой"], context=ctx) == EXIT_USAGE
    assert "не найдена" in err(ctx)


def test_cron_add_rejects_bad_schedule(tmp_path):
    ctx = make_ctx(tmp_path)
    code = main(["cron", "add", "--name", "x", "--schedule", "!!!", "--prompt", "p"],
                context=ctx)
    assert code == EXIT_USAGE
    assert "расписание" in err(ctx)


def test_cron_add_requires_payload(tmp_path):
    ctx = make_ctx(tmp_path)
    code = main(["cron", "add", "--name", "x", "--schedule", "каждые 2ч"], context=ctx)
    assert code == EXIT_USAGE


# --- ход агента -----------------------------------------------------------


def test_turn_success(tmp_path):
    ctx = make_ctx(tmp_path, env={"DEEPSEEK_API_KEY": "k"})
    assert main(["turn", "привет"], context=ctx) == EXIT_OK
    assert "эхо: привет" in out(ctx)


def test_turn_json_payload(tmp_path):
    ctx = make_ctx(tmp_path, env={"DEEPSEEK_API_KEY": "k"})
    assert main(["--json", "turn", "привет"], context=ctx) == EXIT_OK
    payload = json.loads(out(ctx))
    assert payload["response"] == "эхо: привет"
    assert payload["model"] == "deepseek-chat"
    assert payload["provider"] == "deepseek"


def test_turn_without_key_is_usage_error(tmp_path):
    ctx = make_ctx(tmp_path, env={})
    assert main(["turn", "привет"], context=ctx) == EXIT_USAGE
    assert "ключ" in err(ctx)


def test_turn_failure_is_runtime_error(tmp_path):
    FakeTurn.fail_with = "модель недоступна"
    ctx = make_ctx(tmp_path, env={"DEEPSEEK_API_KEY": "k"})
    assert main(["turn", "привет"], context=ctx) == EXIT_RUNTIME
    assert "модель недоступна" in err(ctx)


def test_turn_unknown_provider_is_usage_error(tmp_path):
    ctx = make_ctx(tmp_path, env={"DEEPSEEK_API_KEY": "k"})
    assert main(["turn", "привет", "--provider", "нет-такого"], context=ctx) == EXIT_USAGE


def test_resolve_credentials_requires_model(tmp_path):
    def loader(home: Path) -> Config:
        return Config()  # ни провайдера, ни модели

    ctx = make_ctx(tmp_path, env={"DEEPSEEK_API_KEY": "k"}, config_loader=loader)
    with pytest.raises(CliError) as exc:
        commands.resolve_credentials(ctx)
    assert exc.value.code == EXIT_USAGE
    assert "модель не задана" in str(exc.value)


# --- интерактивный режим --------------------------------------------------


def test_chat_processes_stream_without_tty(tmp_path):
    ctx = make_ctx(tmp_path, stdin_text="привет\nexit\n", env={"DEEPSEEK_API_KEY": "k"})
    assert main(["chat"], context=ctx) == EXIT_OK
    assert "эхо: привет" in out(ctx)


def test_chat_ends_at_eof(tmp_path):
    ctx = make_ctx(tmp_path, stdin_text="один\nдва\n", env={"DEEPSEEK_API_KEY": "k"})
    assert main(["chat"], context=ctx) == EXIT_OK
    assert "эхо: один" in out(ctx)
    assert "эхо: два" in out(ctx)


def test_chat_keeps_history_between_turns(tmp_path):
    ctx = make_ctx(tmp_path, stdin_text="один\nдва\nexit\n", env={"DEEPSEEK_API_KEY": "k"})
    assert main(["chat"], context=ctx) == EXIT_OK
    assert FakeTurn.last_history is not None


# --- гигиена --------------------------------------------------------------


def test_cli_sources_have_no_personal_paths():
    package = Path(commands.__file__).resolve().parent
    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    offenders = []
    for file in package.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(package)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"


def test_cli_sources_resolve_state_through_kernel():
    """CLI не изобретает свои пути: импортирует home/paths."""
    package = Path(commands.__file__).resolve().parent
    source = (package / "commands.py").read_text(encoding="utf-8")
    assert "from prokop.home import" in source
    assert "from prokop.paths import" in source
