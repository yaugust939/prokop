"""Тесты файлового провайдера памяти и его подключения по конфигурации."""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path
from typing import Any, Optional

import pytest

from prokop.cli.commands import Context
from prokop.cli.main import EXIT_OK, main
from prokop.config import Config
from prokop.memory.factory import (
    BUILTIN,
    available_providers,
    build_manager,
    build_provider,
)
from prokop.memory.file_provider import FileMemoryProvider
from prokop.memory.provider import BuiltinMemoryProvider


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def make_provider(tmp_path: Path, **kwargs: Any) -> FileMemoryProvider:
    return FileMemoryProvider(tmp_path / "profile", **kwargs)


def save(provider: FileMemoryProvider, key: str, value: str) -> dict[str, Any]:
    return json.loads(
        run(provider.handle_tool_call("memory_save", {"key": key, "value": value}))
    )


# --- фабрика --------------------------------------------------------------


def test_factory_no_provider(tmp_path):
    config = Config()
    assert build_provider(config, tmp_path) is None


def test_factory_builtin(tmp_path):
    config = Config()
    config.memory.provider = BUILTIN
    assert build_provider(config, tmp_path) is None


def test_factory_file_provider(tmp_path):
    config = Config()
    config.memory.provider = "file"
    provider = build_provider(config, tmp_path)
    assert isinstance(provider, FileMemoryProvider)


def test_factory_unknown_provider_warns(tmp_path, caplog):
    config = Config()
    config.memory.provider = "нет-такого"
    with caplog.at_level("WARNING"):
        assert build_provider(config, tmp_path) is None
    assert "неизвестен" in caplog.text


def test_factory_case_insensitive(tmp_path):
    config = Config()
    config.memory.provider = "FILE"
    assert isinstance(build_provider(config, tmp_path), FileMemoryProvider)


def test_factory_options(tmp_path):
    config = Config()
    config.memory.provider = "file"
    config.memory.options = {"max_records": 7, "prefetch_limit": 2, "filename": "m.jsonl"}
    provider = build_provider(config, tmp_path)
    assert provider.max_records == 7
    assert provider.prefetch_limit == 2
    assert provider.path.name == "m.jsonl"


def test_build_manager_without_provider(tmp_path):
    manager = build_manager(Config(), tmp_path)
    assert manager.external is None
    assert len(manager.providers()) == 1
    assert isinstance(manager.providers()[0], BuiltinMemoryProvider)


def test_build_manager_with_file_provider(tmp_path):
    config = Config()
    config.memory.provider = "file"
    manager = build_manager(config, tmp_path)

    providers = manager.providers()
    assert len(providers) == 2
    assert isinstance(providers[0], BuiltinMemoryProvider)  # встроенный всегда первый
    assert isinstance(providers[1], FileMemoryProvider)


def test_available_providers_lists_builtin():
    names = available_providers()
    assert BUILTIN in names
    assert "file" in names


# --- хранилище ------------------------------------------------------------


def test_save_and_read_fact(tmp_path):
    provider = make_provider(tmp_path)
    assert save(provider, "стек", "Python 3.11")["ok"] is True

    facts = provider.facts()
    assert [f["key"] for f in facts] == ["стек"]
    assert facts[0]["value"] == "Python 3.11"


def test_fact_survives_restart(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "ключ", "значение")

    again = make_provider(tmp_path)
    assert [f["key"] for f in again.facts()] == ["ключ"]


def test_latest_fact_wins(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "ключ", "первое")
    save(provider, "ключ", "второе")

    facts = provider.facts()
    assert len(facts) == 1
    assert facts[0]["value"] == "второе"


def test_sync_turn_saves_digest(tmp_path):
    provider = make_provider(tmp_path)
    provider.session_id = "s1"
    run(provider.sync_turn("вопрос про сборку", "ответ про сборку", []))

    records = provider.search("сборку")
    assert records
    assert records[0]["kind"] == "turn"
    assert "вопрос про сборку" in records[0]["value"]


def test_broken_line_is_skipped(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "ключ", "значение")
    with open(provider.path, "a", encoding="utf-8") as handle:
        handle.write("это не json\n\n")

    assert [f["key"] for f in provider.facts()] == ["ключ"]


def test_missing_storage_is_empty(tmp_path):
    provider = make_provider(tmp_path)
    assert provider.facts() == []
    assert run(provider.prefetch("что угодно")) == ""


def test_backup_paths(tmp_path):
    provider = make_provider(tmp_path)
    assert provider.backup_paths() == [str(provider.path)]


def test_is_available_and_system_prompt(tmp_path):
    provider = make_provider(tmp_path)
    assert provider.is_available() is True
    assert "память" in provider.system_prompt_block().lower()


def test_init_sets_session(tmp_path):
    provider = make_provider(tmp_path)
    provider.init(session_id="session-1")
    assert provider.session_id == "session-1"


# --- релевантность --------------------------------------------------------


def test_prefetch_matches_query(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "стек", "Python и httpx")
    save(provider, "город", "Москва")

    text = run(provider.prefetch("какой стек используется"))
    assert "Python и httpx" in text
    assert "Москва" not in text


def test_prefetch_without_match_is_empty(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "стек", "Python")
    assert run(provider.prefetch("погода на завтра")) == ""


def test_prefetch_cyrillic(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "проект", "ядро агента")
    assert "ядро агента" in run(provider.prefetch("расскажи про проект"))


def test_prefetch_limit(tmp_path):
    provider = make_provider(tmp_path, prefetch_limit=2)
    for index in range(5):
        save(provider, f"ключ{index}", "общее слово")
    assert len(provider.search("общее слово")) == 2


def test_prefetch_empty_query_returns_latest_facts(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "первый", "a")
    save(provider, "второй", "b")

    records = provider.search("")
    assert len(records) == 2


def test_search_dedups_facts_by_key(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "ключ", "старое значение")
    save(provider, "ключ", "новое значение")

    records = provider.search("значение")
    assert len(records) == 1
    assert records[0]["value"] == "новое значение"


# --- инструменты ----------------------------------------------------------


def test_tool_schemas_cover_three_tools(tmp_path):
    names = {
        schema["function"]["name"] for schema in make_provider(tmp_path).get_tool_schemas()
    }
    assert names == {"memory_save", "memory_search", "memory_forget"}


def test_tool_save_requires_key(tmp_path):
    provider = make_provider(tmp_path)
    payload = json.loads(run(provider.handle_tool_call("memory_save", {"value": "x"})))
    assert "error" in payload


def test_tool_search(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "ключ", "значение")
    payload = json.loads(
        run(provider.handle_tool_call("memory_search", {"query": "значение"}))
    )
    assert payload["count"] == 1
    assert payload["records"][0]["key"] == "ключ"


def test_tool_forget(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "ключ", "значение")

    first = json.loads(run(provider.handle_tool_call("memory_forget", {"key": "ключ"})))
    assert first["ok"] is True
    second = json.loads(run(provider.handle_tool_call("memory_forget", {"key": "ключ"})))
    assert second["ok"] is False


def test_tool_forget_requires_key(tmp_path):
    provider = make_provider(tmp_path)
    payload = json.loads(run(provider.handle_tool_call("memory_forget", {})))
    assert "error" in payload


def test_unknown_tool_returns_error(tmp_path):
    provider = make_provider(tmp_path)
    payload = json.loads(run(provider.handle_tool_call("нет-такого", {})))
    assert "error" in payload


# --- пределы --------------------------------------------------------------


def test_max_records_compaction(tmp_path):
    provider = make_provider(tmp_path, max_records=5)
    for index in range(12):
        save(provider, f"ключ{index}", f"значение{index}")

    lines = [
        line for line in provider.path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert len(lines) <= 5
    # Остались самые свежие записи.
    keys = {fact["key"] for fact in provider.facts()}
    assert "ключ11" in keys
    assert "ключ0" not in keys


def test_compaction_keeps_file_valid(tmp_path):
    provider = make_provider(tmp_path, max_records=3)
    for index in range(8):
        save(provider, f"к{index}", "v")
    for line in provider.path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            assert isinstance(json.loads(line), dict)


def test_forget_keeps_other_records(tmp_path):
    provider = make_provider(tmp_path)
    save(provider, "a", "1")
    save(provider, "b", "2")
    provider.forget("a")
    assert [f["key"] for f in provider.facts()] == ["b"]


# --- CLI ------------------------------------------------------------------


def make_ctx(tmp_path: Path, provider: Optional[str] = None) -> Context:
    def loader(home: Path) -> Config:
        config = Config()
        config.memory.provider = provider
        return config

    return Context(
        home=tmp_path / "profile",
        profile="test",
        env={},
        stdin=io.StringIO(""),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
        config_loader=loader,
    )


def out(ctx: Context) -> str:
    return ctx.stdout.getvalue()


def test_cli_memory_list_empty(tmp_path):
    ctx = make_ctx(tmp_path, "file")
    assert main(["memory", "list"], context=ctx) == EXIT_OK
    assert "нет" in out(ctx).lower()


def test_cli_memory_flow(tmp_path):
    provider = FileMemoryProvider(tmp_path / "profile")
    save(provider, "стек", "Python и httpx")

    ctx = make_ctx(tmp_path, "file")
    assert main(["memory", "list"], context=ctx) == EXIT_OK
    assert "Python и httpx" in out(ctx)

    ctx2 = make_ctx(tmp_path, "file")
    assert main(["--json", "memory", "search", "httpx"], context=ctx2) == EXIT_OK
    payload = json.loads(out(ctx2))
    assert payload["count"] == 1

    ctx3 = make_ctx(tmp_path, "file")
    assert main(["memory", "forget", "стек"], context=ctx3) == EXIT_OK
    assert "удалён" in out(ctx3)


def test_cli_memory_forget_missing_key(tmp_path):
    ctx = make_ctx(tmp_path, "file")
    assert main(["memory", "forget", "нет-такого"], context=ctx) == EXIT_OK
    assert "не найден" in out(ctx)


def test_cli_memory_non_file_provider(tmp_path):
    ctx = make_ctx(tmp_path, None)
    assert main(["memory", "list"], context=ctx) == EXIT_OK
    assert "не поддерживает" in out(ctx)


def test_cli_memory_requires_subcommand(tmp_path):
    from prokop.cli.main import EXIT_USAGE

    ctx = make_ctx(tmp_path, "file")
    assert main(["memory"], context=ctx) == EXIT_USAGE


def test_cli_memory_works_without_key(tmp_path):
    ctx = make_ctx(tmp_path, "file")
    assert main(["memory", "list"], context=ctx) == EXIT_OK


# --- гигиена --------------------------------------------------------------


def test_memory_sources_have_no_personal_paths():
    import prokop.memory as package

    root = Path(package.__file__).resolve().parent
    rx = re.compile(r"C:\\Users\\|C:/Users/|/home/[A-Za-z0-9._-]+/")
    offenders = []
    for file in root.rglob("*.py"):
        for num, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
            if rx.search(line):
                offenders.append(f"{file.relative_to(root)}:{num}")
    assert not offenders, f"личные абсолютные пути: {offenders}"
