"""Чистая логика терминального интерфейса.

Модуль не импортирует `prompt_toolkit` и не знает о терминале: состояние
сессии и разбор слэш-команд — обычные функции, пригодные для тестов в среде
без TTY (например в CI).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

#: Действия, которые может вернуть разбор строки.
ACTION_PROMPT = "prompt"
ACTION_HANDLED = "handled"
ACTION_QUIT = "quit"

#: Команды выхода.
QUIT_COMMANDS = frozenset({"/quit", "/exit", "/q"})

HELP_TEXT = """\
Доступные команды:
  /help              эта справка
  /status            состояние сессии
  /model [имя]       показать или сменить модель
  /provider [имя]    показать или сменить провайдера
  /new               начать новую сессию
  /sessions          список сохранённых сессий
  /clear             очистить историю текущего процесса
  /quit              выйти

Строка без «/» отправляется модели."""


@dataclass
class TuiState:
    """Состояние интерактивной сессии."""

    provider: str
    model: str
    session_id: Optional[str] = None
    turns: int = 0
    history: list[Any] = field(default_factory=list)

    def status_line(self) -> str:
        """Строка состояния для нижней панели."""
        session = (self.session_id or "—")[:8]
        return f" {self.provider}/{self.model} · сессия {session} · ходов {self.turns} "

    def reset_session(self) -> None:
        """Начать новую сессию: сбросить идентификатор, историю и счётчик."""
        self.session_id = None
        self.history = []
        self.turns = 0


@dataclass
class CommandOutcome:
    """Результат разбора введённой строки."""

    action: str = ACTION_PROMPT
    text: str = ""
    error: bool = False


def _require_known(value: str, known: list[str], what: str) -> Optional[str]:
    """Проверить значение по списку известных; вернуть текст ошибки."""
    if not known or value in known:
        return None
    return f"неизвестный {what}: {value!r}. Доступны: {', '.join(known)}"


def handle_command(
    line: str,
    state: TuiState,
    *,
    providers: Optional[list[str]] = None,
    sessions: Optional[list[dict[str, Any]]] = None,
) -> CommandOutcome:
    """Разобрать введённую строку.

    Строка без ведущего ``/`` считается запросом к модели. Слэш-команды
    меняют состояние и возвращают текст для печати; неизвестная команда
    возвращает ошибку, но не завершает интерфейс.
    """
    text = (line or "").strip()
    if not text:
        return CommandOutcome(action=ACTION_HANDLED)
    if not text.startswith("/"):
        return CommandOutcome(action=ACTION_PROMPT, text=text)

    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command in QUIT_COMMANDS:
        return CommandOutcome(action=ACTION_QUIT)

    if command == "/help":
        return CommandOutcome(action=ACTION_HANDLED, text=HELP_TEXT)

    if command == "/status":
        return CommandOutcome(action=ACTION_HANDLED, text=state.status_line().strip())

    if command == "/model":
        if not argument:
            return CommandOutcome(
                action=ACTION_HANDLED, text=f"модель: {state.model}"
            )
        state.model = argument
        return CommandOutcome(
            action=ACTION_HANDLED, text=f"модель переключена: {argument}"
        )

    if command == "/provider":
        if not argument:
            return CommandOutcome(
                action=ACTION_HANDLED, text=f"провайдер: {state.provider}"
            )
        error = _require_known(argument, providers or [], "провайдер")
        if error:
            return CommandOutcome(action=ACTION_HANDLED, text=error, error=True)
        state.provider = argument
        return CommandOutcome(
            action=ACTION_HANDLED, text=f"провайдер переключён: {argument}"
        )

    if command == "/new":
        state.reset_session()
        return CommandOutcome(action=ACTION_HANDLED, text="новая сессия")

    if command == "/clear":
        state.history = []
        return CommandOutcome(action=ACTION_HANDLED, text="история очищена")

    if command == "/sessions":
        rows = sessions or []
        if not rows:
            return CommandOutcome(action=ACTION_HANDLED, text="Сохранённых сессий нет.")
        listing = "\n".join(
            f"{str(row.get('id'))[:8]}  {row.get('last_activity') or '—'}  "
            f"{row.get('message_count') or 0} сообщ."
            for row in rows
        )
        return CommandOutcome(action=ACTION_HANDLED, text=listing)

    return CommandOutcome(
        action=ACTION_HANDLED,
        text=f"неизвестная команда: {command}. Введите /help.",
        error=True,
    )
