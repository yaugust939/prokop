## Context

Оркестратор — кросс-проектный слой поверх opencode для автономного выполнения задач в любом проекте и сессии. Существующее состояние:

- **opencode CLI 1.18.18** (npm, глобально) поддерживает headless-режим: `opencode run "<промпт>" --dir <путь> --agent <имя> --format json [--session X --continue|--fork] [--auto]`. Все сессии хранятся в одном SQLite `~/.local/share/opencode/opencode.db` (WAL).
- **PROKOP MCP** (`~/.config/opencode/mcp-servers\prokop_mcp.py`) уже предоставляет `agent_turn`, `agent_schedule_job`, `agent_list_jobs`, `agent_run_ticker`, `agent_run_command`, `computer_use`. Ядро — пакет `src/prokop` (Python 3.11, asyncio) в `D:\OBS_Prokopii_1`.
- **Планировщик prokop** уже существует: `JobStore` (`~/.prokop/cron/jobs.json`, файловая блокировка), `Ticker.tick()` различает agent-задания и `no_agent`-скрипты.
- **HERMES** — проектный диспетчер, ведёт трекеры `tasks.md` (глобальный `~/.hermes/tasks.md`, локальные по проектам). Формат строк: `- [статус] P<0..2> · <исполнитель> · <описание> (#id)`. проекты на дисках пользователя уже инициализированы.

Ограничение среды: Windows (quoting, кириллица в путях, кодировка JSON-вывода opencode — UTF-16 при редиректе PowerShell), интерактивный TUI может быть открыт одновременно с headless-вызовами.

## Goals / Non-Goals

**Goals:**
- Единая точка входа «дал задачу — получил результат» поверх всех проектов и сессий: из TUI (любая папка) и из headless-вызова.
- Автономная маршрутизация: запрос → проект → агент → headless-сессия → результат → трекер.
- Периодические задачи исполняются без открытой сессии opencode (через планировщик prokop + Windows Task Scheduler).
- Реестр проектов и сессий как единая картина состояния (источник истины `opencode.db`).
- Надёжность на Windows: таймауты, retry, kill зависших процессов, атомарная запись реестра и трекеров.

**Non-Goals:**
- Не заменяет HERMES (проектный диспетчер остаётся как есть).
- Не управляет десктоп-приложением opencode (desktop-app) — это отдельная система.
- Не плодит второй планировщик — расширяется существующий Ticker prokop.
- Не вводит новых внешних зависимостей/Python-пакетов.
- Полный GUI-контроль и постоянный демон-раннер — вне скоупа (опционально на этапе 4).

## Decisions

### D1: Основной канал — headless-spawn, а не постоянный serve+attach
`opencode run --format json` запускается отдельным процессом под каждую задачу.

- *Рационально*: изоляция (зависший процесс убивается `taskkill /T /F`, не задевая остальное), параллельность (N задач = N процессов), сбор результата через финальное событие `result` (sessionId/cost/tokens/durationMs), минимальная интерференция с TUI. Континуитет сессий уже обеспечивает общий `opencode.db` (WAL) — холодный старт ~1–2 с.
- *Альтернатива (serve+attach)*: отвергнута как основной канал — нужен постоянный демон, один раннер = узкое место, падение сервера роняет attach-сессии, общий console со всеми сессиями. Остаётся опцией для редких длинных runner-сессий (этап 4).

### D2: Ядро — детерминированный Python-модуль + тонкий LLM-агент
Оркестратор = `src/prokop/orchestrator/` (registry, router, spawn, collect, reporter, sweeper, queue) — вся механика детерминированная. LLM (агент `orchestrator`) отвечает только за неоднозначную маршрутизацию (1 уточняющий вопрос) и резюме результатов.

- *Рационально*: тестируемость, предсказуемость, дешёвая работа по расписанию (без LLM в цикле для тривиального).

### D3: Реестр — двухслойная модель (opencode.db + registry.json)
Источник истины — `opencode.db` (только чтение): таблицы `project`, `project_directory`, `session`, `session_input`. Обогащённый снимок — `~/.hermes/registry.json` (алиасы проектов, routing_keywords, статусы задач, PIDs). Синхронизация `registry.refresh()`: SELECT → diff → merge, перезапись atomic (tmp + `os.replace`).

- *Рационально*: не дублируем владение данными opencode; registry.json — аугментация для маршрутизации и оперативного состояния.
- *Риск*: структура `opencode.db` может меняться между версиями → запросы к БД через `SELECT` с защитой от ошибок (graceful degrade: пустой реестр, не падение).

### D4: Маршрутизация — порядочные правила в router.py
1. Явное (имя проекта/путь/`session_id` → `--session X --continue`) → 2. `routing_keywords` проекта (substring, регистронезависимо) → 3. `#project:<alias>` из крона/автозадач → 4. системное/кросс-проектное → `global` → 5. по умолчанию `cwd` вызова или 1 уточняющий вопрос LLM-агента.

- *Рационально*: детерминизм для крона, гибкость для неоднозначных запросов из TUI.

### D5: Запуск через subprocess списком аргументов
`subprocess.Popen(["opencode","run","<промпт>","--dir",project,"--agent",a,"--format","json","--auto","--title",title], stdout=PIPE, stderr=STDOUT, encoding="utf-8", errors="replace")`. Платформенные флаги добавляются точечно: `creationflags=CREATE_NO_WINDOW` только при `os.name == "nt"`, `start_new_session=True` на POSIX (ребёнок — лидер своей группы процессов). `--auto` отключается для задач с деструктивными действиями (флаг в задаче).

- *Рационально*: передача аргументами, а не строкой консоли, надёжно сохраняет кириллицу и пробелы в путях на любой платформе. Кодировка stdout — `utf-8` + `errors="replace"` (JSON NDJSON).

### D6: Сбор результатов — построчный парсинг NDJSON
Читаем stdout построчно, копим последний `message.updated` (текст) и финальное `result`. Timeout по приоритету: P0–60 мин, P1–30 мин, P2–15 мин (конфиг). При таймауте — 1 retry с `--fork`, затем принудительное завершение дерева процессов: `taskkill /PID <pid> /T /F` на Windows, `killpg(SIGKILL)` с откатом на `SIGTERM` на POSIX.

- *Рационально*: `--format json` даёт машиночитаемый поток; retry с fork сохраняет контекст сессии.

### D7: Отчётность в трекеры с файловой блокировкой
Переиспользуем паттерн `_FileLock` из `prokop/cron/store.py`: lock-файл рядом с `tasks.md`, чтение → правка → запись атомарно. На старте строка `[~]`, по завершении `[x]`/`[!]` с резюме (1–2 строки) и стоимостью/токенами в скобках.

### D8: Планировщик — расширение Ticker (delivery-target "opencode")
В `prokop/cron/executor.py` добавляется target `"opencode"`: когда задание наступило, Ticker вместо `AgentTurn` вызывает `orchestrator.spawn()`. Промпт может содержать `#project:<alias>`. Результат — в `~/.prokop/cron/outputs/<job_id>/<stamp>.txt` и в `tasks.md`. Триггеры tick'а: `agent_run_ticker` (каждые 10–15 мин) либо Windows Task Scheduler (устойчиво к закрытым сессиям).

### D9: Параллелизм — семафор 2–3 + файловая очередь
`queue.py`: максимум 2–3 одновременных spawn (Windows + лимит модели), очередь `~/.prokop/orchestrator/queue.json`. Задачи по разным проектам не конкурируют; по одному проекту — сериализация.

## Risks / Trade-offs

- [Windows/quoting и кодировка] → subprocess со списком аргументов, `encoding="utf-8", errors="replace"`, JSON с `ensure_ascii=False`; рег-тест на кириллицу/пробелы (этап 5).
- [Зависшие/orphan-процессы opencode run] → таймауты + `taskkill /T /F`; `sweeper.py` при старте ищет процессы старше порога и убивает; PIDs в `registry.tasks`.
- [Конкуренция с интерактивным TUI (общий opencode.db)] → WAL не блокирует чтения; для активной папки пользователя — `--fork`; эвристика: сессия по проекту обновлялась <5 мин назад → отложить/предупредить.
- [Расход токенов/стоимость] → принудительный `--model` в spawn (по умолчанию дешёвая); суточный лимит токенов `budget.py` (этап 4) — при превышении задачи в очередь с предупреждением.
- [Структура opencode.db меняется между версиями] → защищённые SELECT (graceful degrade), версия реестра в registry.json.
- [Отказ планировщика (нет активной сессии)] → Windows Task Scheduler вызывает tick напрямую; `grace_seconds` уже есть в Ticker.
- [JSON-вывод opencode в редиректе PowerShell — UTF-16] → парсинг учитывает BOM/кодировку; предпочтителен запуск через `subprocess` из Python (не PowerShell-редирект).

## Migration Plan

1. Этап 1 (MVP): модуль `orchestrator/{spawn,collect,reporter}.py`, инструмент `prokop_orchestrate`, агент `orchestrator.md`, команда `/dispatch`. Smoke: задача → headless-сессия в проекте → строка в `tasks.md` → `result`/`cost`/`sessionId`.
2. Этап 2: `registry.py` + `router.py` + `prokop_orchestrate_list`/`prokop_registry_refresh`; маршрутизация по ключевым словам и `--continue`.
3. Этап 3: executor target `opencode`, `queue.py`, `sweeper.py`, Task Scheduler (tick каждые 10 мин).
4. Этап 4: `budget.py`, `--fork`/`--continue`-флоу, опциональный `--port`+`--attach`, `/report`.
5. Этап 5: E2E по всем проектам, рег-тесты, документация.

Откат: модуль добавляется параллельно существующему коду (не меняет поведение `agent_turn`/Ticker по умолчанию — target `"opencode"` только для новых заданий); удаление оркестратора не ломает существующие потоки HERMES/PROKOP.

## Open Questions

- Нужен ли оркестратору доступ к `opencode.db` напрямую (SQLite) или лучше API/`opencode list` команды? — Пока: прямое чтение только, с graceful degrade.
- Допустимо ли автоматически ставить `--auto` для задач из TUI (риск деструктивных действий) или только для крона/автозадач? — Пока: флаг в задаче, по умолчанию off для интерактива.
