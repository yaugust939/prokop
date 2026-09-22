"""Оркестратор: кросс-проектное управление opencode (OpenSpec change `orchestrator`).

Слой поверх headless-режима opencode CLI: запуск задач в произвольном
проекте, сбор JSON-результатов, отчётность в трекеры ``tasks.md``.

Подсистемы (этап 1 — MVP):
- ``spawn``   — запуск ``opencode run --format json`` в подпроцессе;
- ``collect`` — построчный парсинг NDJSON-событий и извлечение итога;
- ``reporter`` — атомарная запись строк в трекеры ``tasks.md``.
"""
