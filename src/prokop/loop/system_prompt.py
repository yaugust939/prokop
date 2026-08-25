"""Системный промпт: построение, кэш, персистентность.

Системный промпт строится один раз на сессию, кэшируется и сохраняется в
хранилище; на следующих ходах восстанавливается дословно — это основа кэша
префикса. Промпт состоит из стабильной части (идентичность, правила,
контекстные файлы) и «волатильной» хвостовой части (модель/провайдер/
платформа), по которой проверяется устаревание.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Optional


def prompt_hash(content: str) -> str:
    """Content-адресованный хэш промпта."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class SystemPromptState:
    """Состояние системного промпта сессии."""

    content: Optional[str] = None
    #: Хэш хвостовой (волатильной) части — для проверки устаревания.
    tail_hash: Optional[str] = None

    @property
    def hash(self) -> Optional[str]:
        return prompt_hash(self.content) if self.content is not None else None


def build_stable_part(
    *,
    identity: str,
    platform_rules: str = "",
    context_files: Optional[list[str]] = None,
    skills_index: str = "",
    memory_block: str = "",
) -> str:
    """Стабильная часть системного промпта."""
    sections = [identity.strip()]
    if platform_rules:
        sections.append(platform_rules.strip())
    for context_file in context_files or []:
        if context_file.strip():
            sections.append(context_file.strip())
    if skills_index:
        sections.append(f"## Доступные навыки\n{skills_index}")
    if memory_block:
        sections.append(memory_block.strip())
    return "\n\n".join(s for s in sections if s)


def build_tail_part(*, model: str, provider: str, platform: str) -> str:
    """Волатильная хвостовая часть (модель/провайдер/платформа)."""
    return f"Модель: {model}; провайдер: {provider}; платформа: {platform}."


def build_system_prompt(
    *,
    identity: str,
    model: str,
    provider: str,
    platform: str = "cli",
    platform_rules: str = "",
    context_files: Optional[list[str]] = None,
    skills_index: str = "",
    memory_block: str = "",
) -> SystemPromptState:
    """Построить системный промпт целиком (стабильная часть + хвост)."""
    stable = build_stable_part(
        identity=identity,
        platform_rules=platform_rules,
        context_files=context_files,
        skills_index=skills_index,
        memory_block=memory_block,
    )
    tail = build_tail_part(model=model, provider=provider, platform=platform)
    content = f"{stable}\n\n{tail}"
    return SystemPromptState(content=content, tail_hash=hashlib.sha256(tail.encode("utf-8")).hexdigest())


def is_stale(state: SystemPromptState, *, model: str, provider: str, platform: str) -> bool:
    """Устарел ли промпт: сравнение хвоста с текущей моделью/провайдером."""
    if state.content is None:
        return True
    tail = build_tail_part(model=model, provider=provider, platform=platform)
    return hashlib.sha256(tail.encode("utf-8")).hexdigest() != state.tail_hash
