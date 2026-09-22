"""Инструмент агента для снимков и отката.

Регистрируется в наборе `checkpoints` при импорте модуля (пакетный шаблон
ядра: инструменты саморегистрируются на импорте). Набор включается явно в
конфигурации профиля, поэтому возможность не навязывается модели.
"""

from __future__ import annotations

import json
from typing import Any

from prokop.checkpoints.store import CheckpointError, CheckpointStore
from prokop.config import load_config
from prokop.home import home_dir
from prokop.security.audit import get_audit
from prokop.security.policy import Decision, get_policy
from prokop.tools.registry import register

#: Имя набора инструментов.
TOOLSET = "checkpoints"

#: Имя инструмента.
TOOL_NAME = "checkpoint"

SCHEMA: dict[str, Any] = {
    "description": (
        "Снимки состояния и откат: создать снимок путей, показать список "
        "снимков, восстановить состояние из снимка, удалить старые снимки. "
        "Восстановление по умолчанию не удаляет файлы, появившиеся после снимка."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "restore", "prune"],
                "description": "Действие",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Пути для снимка (для create)",
            },
            "label": {"type": "string", "description": "Метка снимка"},
            "checkpoint_id": {
                "type": "string",
                "description": "Идентификатор снимка (для restore)",
            },
            "remove_extra": {
                "type": "boolean",
                "description": "Удалить файлы, появившиеся после снимка",
            },
            "keep": {
                "type": "integer",
                "description": "Сколько последних снимков оставить (для prune)",
            },
        },
        "required": ["action"],
    },
}


def _path_guard(path: str) -> str | None:
    """Проверка политики путей: причина запрета или ``None``."""
    decision = get_policy().check_path(path)
    get_audit().record(decision, source="tool:checkpoint")
    return None if decision.decision is Decision.ALLOW else decision.reason


def _store() -> CheckpointStore:
    home = home_dir()
    return CheckpointStore.from_config(
        home, load_config(home).checkpoints, path_guard=_path_guard
    )


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


def handle_checkpoint(**kwargs: Any) -> str:
    """Обработчик инструмента `checkpoint`."""
    action = str(kwargs.get("action") or "").strip().lower()
    store = _store()

    if action == "create":
        paths = kwargs.get("paths") or []
        if isinstance(paths, str):
            paths = [paths]
        if not paths:
            return _error("для действия create нужен непустой список путей")
        try:
            snapshot = store.create(paths, label=str(kwargs.get("label") or ""))
        except CheckpointError as exc:
            return _error(str(exc))
        return json.dumps(
            {"ok": True, "snapshot": snapshot.summary()}, ensure_ascii=False
        )

    if action == "list":
        return json.dumps({"ok": True, "snapshots": store.list()}, ensure_ascii=False)

    if action == "restore":
        checkpoint_id = kwargs.get("checkpoint_id")
        if not checkpoint_id:
            return _error("для действия restore нужен checkpoint_id")
        try:
            report = store.restore(
                str(checkpoint_id), remove_extra=bool(kwargs.get("remove_extra"))
            )
        except CheckpointError as exc:
            return _error(str(exc))
        return json.dumps({"ok": True, "report": report.to_dict()}, ensure_ascii=False)

    if action == "prune":
        removed = store.prune(kwargs.get("keep"))
        return json.dumps({"ok": True, "removed": removed}, ensure_ascii=False)

    return _error(f"неизвестное действие: {action!r}")


def _enabled() -> bool:
    """Доступность инструмента: секция ``checkpoints`` не выключена."""
    try:
        return _store().enabled
    except Exception:  # noqa: BLE001 — недоступность не должна ронять реестр
        return False


register(TOOL_NAME, TOOLSET, SCHEMA, handle_checkpoint, check_fn=_enabled)
