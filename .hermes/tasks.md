# HERMES — трекер задач проекта

Формат: `- [статус] P<0..2> · <исполнитель> · <описание> (#id)`
статусы: `[ ]` ожидает · `[~]` в работе · `[x]` готово · `[!]` заблокировано

## Закрыто

Сессия 1 (коммит f2e5adc) — аудит, универсальность, CLI, TUI, MCP-клиент,
checkpoints, security. Сессия 2 (коммит ниже) — реализации контрактов.

- [x] P1 · hermes · Полный аудит прокопия: Windows-следы, чистота, универсальность, паритет с Hermes (#1)
- [x] P0 · hermes · Вычистить личные абсолютные пути из reporter.py, openspec/orchestrator и MCP-моста (#2)
- [x] P1 · hermes · Свести два резолвера home (paths.py → home.py), убрать бренд AgentCore (#3)
- [x] P1 · hermes · Кроссплатформенность: GUI-бэкенды, kill-фолбэки, поиск opencode, маркеры extra gui (#4)
- [x] P1 · hermes · CI-матрица ubuntu+windows+macos; README/доки актуализированы; Dockerfile из контекста (#5)
- [x] P2 · hermes · Чистота репо: egg-info/pycache, agent_e2e → e2e_live, PowerShell-чек-лист → docs/PLATFORM_NOTES.md (#6)
- [x] P2 · hermes · Гэп-анализ паритета с Hermes → docs/PARITY.md (#7)
- [x] P2 · hermes · Синхронизировать openspec/specs с changes/* + архивировать завершённые изменения (#8)
- [x] P2 · hermes · Портабельный ~/.config/opencode/opencode.json через {env:...} (#9)
- [x] P1 · hermes · Изменение prokop-cli: команда prokop (turn/chat/sessions/skills/providers/config/doctor/cron) (#10)
- [x] P2 · hermes · Проверка Dockerfile: логика подтверждена локальной симуляцией (docker build блокирован pull) (#11)
- [x] P1 · hermes · Изменение backends-utf8: вывод команд декодируется как UTF-8, не зависит от локали (#12)
- [x] P1 · hermes · Изменение mcp-client: общий клиент внешних MCP-серверов + подкоманда prokop mcp (#13)
- [x] P1 · hermes · computer/cua.py переведён на общий MCP-клиент + покрытие CuaBackend тестами (#14)
- [x] P1 · hermes · Изменение prokop-tui: терминальный интерфейс, слэш-команды, extra tui, деградация (#15)
- [x] P1 · hermes · Изменение prokop-checkpoints: снимки состояния и откат + инструмент агента (#16)
- [x] P1 · hermes · Изменение prokop-security: политики команд и путей, аудит, подкоманда security (#17)
- [x] P2 · hermes · Зафиксировать состояние в git: коммит f2e5adc (138 файлов) (#21)
- [x] P1 · hermes · Изменение prokop-integrations: файловый провайдер памяти + адаптер Telegram (#23)
- [x] P1 · hermes · Фабрика провайдеров памяти: memory.provider наконец подключён (#24)

## Осталось

- [ ] P2 · hermes · Изоляция процессов/ФС (настоящая песочница) — платформенно-специфична, отдельным изменением (#18)
- [ ] P2 · hermes · Остальные платформы обмена сообщениями (контракт проверен на Telegram) (#19)
- [ ] P2 · hermes · Синхронизировать и закрыть изменение orchestrator (0/29 задач: реестр/роутер/очередь/sweeper) (#20)
- [ ] P2 · hermes · Проверить `docker build` в среде с доступным реестром образов (#22)

## Заметки

- Коммит f2e5adc: portability + CLI/TUI/MCP/checkpoints/security.
- Коммит сессии 2: файловый провайдер памяти, адаптер Telegram, подкоманда
  `prokop memory`; 481 тест, `openspec validate --all`: 17 passed.
- Найдено и закрыто: `memory.provider` из конфигурации не влиял ни на что
  (`MemoryManager.set_external` не вызывался) — добавлена фабрика.
