"""Схема конфигурации профиля.

Ключи соответствуют спецификации ``specs/memory`` и ``specs/providers``:
``model.*`` — основная модель, ``memory.provider`` — постоянная память,
``toolsets.*`` — наборы инструментов, ``auxiliary.*`` — вспомогательные модели
(компрессия, зрение, заголовки, поиск по сессиям, переписывание запросов памяти).

Запись на диск — атомарная (временный файл + ``os.replace``).
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG_FILENAME = "config.yaml"

#: Задачи вспомогательных моделей.
AUXILIARY_TASKS = (
    "compression",
    "vision",
    "titles",
    "session_search",
    "memory_query_rewrite",
    "embeddings",
)


@dataclass
class ModelConfig:
    """Конфигурация основной модели."""

    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    #: Имя переменной окружения, в которой лежит ключ (ключ в файле не храним).
    api_key_env: Optional[str] = None
    max_tokens: Optional[int] = None
    context_length: Optional[int] = None
    reasoning_effort: Optional[str] = None
    ollama_num_ctx: Optional[int] = None

    def api_key(self) -> Optional[str]:
        """Разрешить ключ из переменной окружения."""
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None


@dataclass
class MemoryConfig:
    """Конфигурация постоянной памяти."""

    provider: Optional[str] = None


@dataclass
class ToolsetsConfig:
    """Включённые/отключённые наборы инструментов."""

    enabled: list[str] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)


@dataclass
class AuxiliaryModelConfig:
    """Конфигурация одной вспомогательной модели."""

    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    timeout: Optional[float] = None
    reasoning_effort: Optional[str] = None


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class Config:
    """Полная конфигурация профиля."""

    model: ModelConfig = field(default_factory=ModelConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    toolsets: ToolsetsConfig = field(default_factory=ToolsetsConfig)
    auxiliary: dict[str, AuxiliaryModelConfig] = field(default_factory=dict)
    timezone: Optional[str] = None
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    def aux(self, task: str) -> AuxiliaryModelConfig:
        """Вспомогательная модель для задачи; пустая, если не задана."""
        return self.auxiliary.get(task) or AuxiliaryModelConfig()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        if not isinstance(data, dict):
            return cls()
        model = ModelConfig(**(data.get("model") or {}))
        memory = MemoryConfig(**(data.get("memory") or {}))
        toolsets = ToolsetsConfig(**(data.get("toolsets") or {}))
        auxiliary = {
            name: AuxiliaryModelConfig(**(spec or {}))
            for name, spec in (data.get("auxiliary") or {}).items()
        }
        logging_cfg = LoggingConfig(**(data.get("logging") or {}))
        return cls(
            model=model,
            memory=memory,
            toolsets=toolsets,
            auxiliary=auxiliary,
            timezone=data.get("timezone"),
            logging=logging_cfg,
        )


def config_path(home: Path) -> Path:
    """Путь к файлу конфигурации в домашнем каталоге профиля."""
    return home / CONFIG_FILENAME


def load_config(home: Path) -> Config:
    """Загрузить конфигурацию; при отсутствии файла — значения по умолчанию."""
    path = config_path(home)
    if not path.exists():
        return Config()
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return Config.from_dict(data)


def save_config(config: Config, home: Path) -> None:
    """Атомарно сохранить конфигурацию."""
    path = config_path(home)
    home.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(home), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(config.to_dict(), fh, allow_unicode=True, sort_keys=True)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
