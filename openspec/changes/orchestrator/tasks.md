## 1. MVP: spawn + collect + отчёт

- [ ] 1.1 Создать пакет `src/prokop/orchestrator/` с `__init__.py`
- [ ] 1.2 Реализовать `spawn.py`: запуск `opencode run --dir <проект> --agent <имя> --format json --title <title>` через `subprocess.Popen` со списком аргументов, `encoding="utf-8"`, `errors="replace"`; платформенные флаги точечно (`CREATE_NO_WINDOW` на Windows, `start_new_session` на POSIX); поиск бинаря кроссплатформенный (`OPENCODE_BIN` → `which` → npm-каталоги ОС); опциональный флаг `--auto` по конфигу задачи; поддержка `--session X --continue` и `--fork`
- [ ] 1.3 Реализовать `collect.py`: построчный парсинг NDJSON-событий, накопление последнего `message.updated` и финального `result` (sessionId/cost/tokens/durationMs); таймауты по приоритету (P0-60м/P1-30м/P2-15м, конфиг); 1 retry с `--fork` при таймауте, затем завершение дерева процессов (`taskkill /T /F` на Windows, `killpg(SIGKILL)` с откатом на `SIGTERM` на POSIX)
- [ ] 1.4 Реализовать `reporter.py`: атомарная запись/обновление строк в `tasks.md` (глобальном и проектных) с файловой блокировкой `_FileLock` (паттерн из `prokop/cron/store.py`); `[~]` на старте, `[x]`/`[!]` по завершении с резюме и стоимостью в скобках; `#id = max+1` для новых задач
- [ ] 1.5 Добавить в `prokop_mcp.py` инструмент `prokop_orchestrate` (промпт + необязательные project/agent/model/приоритет) с вызовом конвейера spawn → collect → report
- [ ] 1.6 Создать агент `~/.config/opencode/agent/orchestrator.md` (mode: primary, permission `prokop_*: allow`): инструкция «маршрутизируй, делегируй, докладывай в трекер»
- [ ] 1.7 Создать команду `~/.config/opencode/command/dispatch.md`
- [ ] 1.8 Smoke-тест этапа 1: `prokop_orchestrate("перечисли файлы проекта")` → процесс `opencode run` с `--dir D:/OBS_API_Kladez`, строка в `tasks.md`, в ответе `result`+`cost`+`sessionId`

## 2. Реестр и маршрутизация

- [ ] 2.1 Реализовать `registry.py`: чтение `opencode.db` (таблицы `project`, `project_directory`, `session`, `session_input`) только на чтение с graceful degrade; снимок `~/.hermes/registry.json` (projects/sessions/tasks); атомарная перезапись (tmp + `os.replace`)
- [ ] 2.2 Реализовать `registry.refresh()`: SELECT → diff → merge; сканирование `D:\OBS_*` и `D:\opencode` на `.hermes\tasks.md` для добавления инициализированных проектов; версия реестра и `updated_at`
- [ ] 2.3 Реализовать `router.py`: правила маршрутизации в порядке (явное имя/путь/session_id → routing_keywords → `#project:<alias>` → системное/global → cwd/1 уточняющий вопрос); выбор агента (browser/explore/hermes/general) и передача скилов упоминанием в промпте
- [ ] 2.4 Добавить в `prokop_mcp.py` инструменты `prokop_orchestrate_list` и `prokop_registry_refresh`
- [ ] 2.5 Доработать `prokop_orchestrate` и `/dispatch` для выбора проекта и продолжения сессий (`--session X --continue`)
- [ ] 2.6 Smoke-тест этапа 2: refresh показывает 30+ проектов; «ВАК статья про...» → RANXIGS; «продолжи сессию X» → `--session X --continue`

## 3. Планировщик, параллельность, устойчивость

- [ ] 3.1 Расширить `prokop/cron/executor.py`: delivery-target `"opencode"` — при наступлении задания Ticker вызывает `orchestrator.spawn()` вместо `AgentTurn`; учёт тега `#project:<alias>` (иначе `global`)
- [ ] 3.2 Сохранять результат заданий в `~/.prokop/cron/outputs/<job_id>/<stamp>.txt` (механизм `LocalDelivery`) и передавать в отчётность трекера
- [ ] 3.3 Реализовать `queue.py`: файловая очередь `~/.prokop/orchestrator/queue.json`, семафор 2–3 одновременных spawn, сериализация задач по одному проекту
- [ ] 3.4 Реализовать `sweeper.py`: поиск процессов `opencode run` старше порога и их завершение (кроссплатформенно: `psutil` либо нативные средства ОС — `wmic`/`Get-Process` на Windows, `ps` на POSIX); PIDs задач в `registry.tasks`
- [ ] 3.5 Настроить триггер tick'а вне сессии opencode: планировщик ОС (Windows Task Scheduler / `cron` на POSIX, например каждые 10 минут: `python -c "from prokop.cron.ticker import ..."`)
- [ ] 3.6 Smoke-тест этапа 3: `agent_schedule_job("каждые 2ч проверь git status... #project:kladez", "*/2 * * * *")` → `agent_run_ticker` → результат в `~/.prokop/cron/outputs/` и отметка в `tasks.md`

## 4. Полный цикл

- [ ] 4.1 Реализовать `budget.py`: суточный лимит токенов (сумма tokens_input/output за день из реестра), при превышении — задачи в очередь с предупреждением в трекере
- [ ] 4.2 Принудительный `--model` в spawn (по умолчанию дешёвая модель как у prokop), переопределяемый в задаче
- [ ] 4.3 Опциональный режим runner-сессии: `--port` + `--attach` для длинных сессий
- [ ] 4.4 Отчёт `/report` по всем проектам (агрегация реестра: статусы задач, стоимость, последние сессии)
- [ ] 4.5 Smoke-тест этапа 4: продолжение прежней сессии, срабатывание лимита бюджета с предупреждением в трекере

## 5. Стабилизация

- [ ] 5.1 E2E-прогон по всем инициализированным проектам (выполнение типовых задач через оркестратор)
- [ ] 5.2 Рег-тест на кириллицу/пробелы в путях проектов и промптов
- [ ] 5.3 Профилирование времени холодного старта headless-сессии
- [ ] 5.4 Документация: шаблон проекта и README в `D:\opencode`
