## Why

Сейчас задачи выполняются вручную из той папки, где открыт opencode: HERMES ведёт трекеры по проектам, но нет единой точки «дал задачу — получил результат» поверх всех проектов и сессий. Чтобы автономно управлять opencode, нужен кросс-проектный слой: он сам решает что/где/кем выполнять, поднимает headless-сессии в нужном проекте, собирает результаты и докладывает в трекер, а также исполняет периодические задачи даже без открытой сессии.

## What Changes

- Новый Python-модуль `src/prokop/orchestrator/` (ядро оркестратора):
  - `registry.py` — реестр проектов и сессий: источник истины `opencode.db` (только чтение), обогащённый снимок `~/.hermes/registry.json` (атомарная перезапись).
  - `router.py` — правила маршрутизации запроса на проект и агента (явное имя/путь/session_id → ключевые слова проекта → `#project:<alias>` → global).
  - `spawn.py` — запуск headless-сессии `opencode run --dir <проект> --agent <имя> --format json [--session X --continue|--fork]` через subprocess (список аргументов, CREATE_NO_WINDOW).
  - `collect.py` — построчный парсинг NDJSON-событий, извлечение финального `result`/`cost`/`tokens`/`sessionId`, таймауты по приоритету, retry с `--fork`.
  - `reporter.py` — запись/обновление строк в `tasks.md` (глобальном и проектных) с файловой блокировкой (паттерн `_FileLock` из `prokop/cron/store.py`).
  - `sweeper.py` — поиск и kill зависших/orphan процессов `opencode run`.
  - `queue.py` — файловая очередь задач с семафором 2–3 параллельных spawn (этап 3).
- Расширение `prokop_mcp.py` новыми MCP-инструментами: `prokop_orchestrate`, `prokop_orchestrate_status`, `prokop_orchestrate_list`, `prokop_registry_refresh`.
- Новый агент `~/.config/opencode/agent/orchestrator.md` (mode: primary, permission `prokop_*: allow`) и команда `/dispatch`.
- Расширение планировщика prokop: новый delivery-target `"opencode"` в `prokop/cron/executor.py` — Ticker вместо `AgentTurn` вызывает `orchestrator.spawn()` с промптом задания.
- Опционально (этап 4): суточный лимит токенов `budget.py`, флоу `--fork`/`--continue`, runner-сессии через `--port`/`--attach`, отчёт `/report` по всем проектам.

## Capabilities

### New Capabilities

- `registry`: реестр проектов и сессий — синхронизация из `opencode.db`, обогащённый снимок `registry.json`, сканирование проектов-кандидатов, атомарная перезапись.
- `dispatch`: диспетчеризация задач — роутинг запроса на проект/агента, spawn headless-сессии, сбор JSON-результатов, таймауты/retry, очередь и семафор параллелизма, kill зависших процессов.
- `scheduler-orchestration`: расширение планировщика prokop — delivery-target `"opencode"` для заданий Ticker, запуск headless-сессий по расписанию, доставка результатов в `cron/outputs` и трекер.
- `tracker-reporting`: отчётность в трекеры `tasks.md` — строки `[~]` на старте и `[x]`/`[!]` по завершении с резюме результата, атомарная запись с блокировкой.

### Modified Capabilities

<!-- Greenfield: существующие спеки отсутствуют, изменений требований нет. -->

## Impact

- Новые файлы в `src/prokop/orchestrator/` и в `src/prokop/cron/` (executor.py), доработка `prokop_mcp.py`.
- Конфиг opencode: новый агент и команда в `~/.config/opencode/` (вне git), перезапуск opencode для применения.
- Реестр `~/.hermes/registry.json` — новое состояние на диске пользователя.
- Зависимости: используется существующий Python 3.11 + opencode CLI (npm). Новых внешних пакетов не требуется.
- Риски: кодировка/quoting путей на Windows, зависшие процессы, конкуренция с интерактивным TUI (общий `opencode.db`), расход токенов — обработаны в design.md и tasks.md.
