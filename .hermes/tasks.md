# HERMES — трекер задач проекта

Формат: `- [статус] P<0..2> · <исполнитель> · <описание> (#id)`
статусы: `[ ]` ожидает · `[~]` в работе · `[x]` готово · `[!]` заблокировано

## Закрыто

Сессия 1 (f2e5adc) — аудит, универсальность, CLI, TUI, MCP-клиент, checkpoints,
security. Сессия 2 (8d978e0) — файловая память, адаптер Telegram. Сессия 3
(0015a1f) — адаптер MAX. Сессия 4 — публикация в git и развёртывание в AI Artel.

- [x] P1 · hermes · Полный аудит прокопия: Windows-следы, чистота, универсальность, паритет с Hermes (#1)
- [x] P0 · hermes · Вычистить личные абсолютные пути из reporter.py, openspec/orchestrator и MCP-моста (#2)
- [x] P1 · hermes · Свести два резолвера home (paths.py → home.py), убрать бренд AgentCore (#3)
- [x] P1 · hermes · Кроссплатформенность: GUI-бэкенды, kill-фолбэки, поиск opencode, маркеры extra gui (#4)
- [x] P1 · hermes · CI-матрица ubuntu+windows+macos; README/доки актуализированы; Dockerfile из контекста (#5)
- [x] P2 · hermes · Чистота репо: egg-info/pycache, agent_e2e → e2e_live, PowerShell-чек-лист → docs/PLATFORM_NOTES.md (#6)
- [x] P2 · hermes · Гэп-анализ паритета с Hermes → docs/PARITY.md (#7)
- [x] P2 · hermes · Синхронизировать openspec/specs с changes/* + архивировать завершённые изменения (#8)
- [x] P2 · hermes · Портабельный ~/.config/opencode/opencode.json через {env:...} (#9)
- [x] P1 · hermes · Изменение prokop-cli: команда prokop (#10)
- [x] P2 · hermes · Проверка Dockerfile: логика подтверждена локальной симуляцией (#11)
- [x] P1 · hermes · Изменение backends-utf8: UTF-8-вывод не зависит от локали (#12)
- [x] P1 · hermes · Изменение mcp-client: общий клиент MCP + подкоманда prokop mcp (#13)
- [x] P1 · hermes · computer/cua.py на общем MCP-клиенте + покрытие тестами (#14)
- [x] P1 · hermes · Изменение prokop-tui: терминальный интерфейс (#15)
- [x] P1 · hermes · Изменение prokop-checkpoints: снимки и откат (#16)
- [x] P1 · hermes · Изменение prokop-security: политики и аудит (#17)
- [x] P2 · hermes · Зафиксировать состояние в git (#21)
- [x] P1 · hermes · Изменение prokop-integrations: файловая память + Telegram (#23)
- [x] P1 · hermes · Фабрика провайдеров памяти: memory.provider подключён (#24)
- [x] P1 · hermes · Изменение max-adapter: полный адаптер мессенджера MAX (#25)
- [x] P0 · hermes · Пуш в git: 0015a1f, df34be0, e163cd8 (origin/main синхронизирован) (#28)
- [x] P0 · hermes · Развернуть репо в AI Artel: bare /srv/git/prokop.git + рабочая копия /srv/projects/prokop (#29)
- [x] P0 · hermes · Первый прогон на Linux: 14 падений → найдены и исправлены 2 настоящие причины (#30)

## Осталось

- [ ] P0 · hermes · Переключить Прокопия на наш prokop: подключить `ProkopEngine` за швом `AgentEngine` в copilot-v2 (ADR 0003) (#31)
- [ ] P0 · hermes · P0-1 спеки артели: structured output (`response_format`) в транспорте prokop (#32)
- [ ] P0 · hermes · P0-2 спеки артели: vision-хелпер `build_multimodal_message` (только user-сообщения) (#33)
- [ ] P0 · hermes · P0-3 спеки артели: резолвер role→model и передача в spawn_fn субагентов (#34)
- [ ] P2 · hermes · P0-4/P0-5: изоляция реестра (готово механизмом) и конфиг без глобалов (#35)
- [ ] P2 · hermes · Вебхуки MAX (#27), песочница (#18), остальные платформы (#19), orchestrator (#20)

## Заметки

### AI Artel: что найдено (VM AIRTEL, 192.168.0.60)

- **Стек OS3** — `/docker/artel3`: реестр `config/agents.json` (66 ролей),
  классы `config/agent-classes.json`, секреты `secrets/<role>.env`, vault по роли.
  В реестре есть роль **`prokopiy` — «Прокопий (Оркестрация)»**; в MAX-боте
  `id5118006623_bot` → prokopiy.
- **Мозг флота** — `/docker/artel3/scripts/os3-agent-runner.py`: собственный цикл
  на DeepSeek (`llm_call`), не Hermes. Рантайм-образ `artel3/agent-base:2`
  (`python3 /app/os3-agent-runner.py --agent … --role … --key …`).
- **Установленного Hermes Agent на сервере нет**: единственные упоминания —
  `vault/hermes` (там персонаж Марфы), `benchmark_hermes` (сравнение
  PROKOP/Hermes/OpenClaw), `.env.bak-prehermes` и старый контейнер
  `artel3-agent-hermes` в бэкапе миграции.
- **`copilot-v2`** (`/srv/projects/copilot-v2`, bare `/srv/git/copilot-v2.git`) —
  «Копилот Декларанта V.2». По ADR 0003 и спецификации (раздел 6) ассистент-движком
  должен стать **наш prokop** через шов `AgentEngine` → `ProkopEngine`; сейчас
  стоит `BuiltinEngine`. Причина отложения (HISTORY): «Прокопий несёт
  Windows-специфику (`backends/local.py`, `computer/windows.py`) и глобальные
  синглтоны».
- **Эта причина устранена** — кроссплатформенность вычищена и подтверждена зелёным
  прогоном на самой VM AIRTEL (Linux, Python 3.12).

### Что дал первый прогон на Linux (ценность)

537 тестов: локально (Windows) зелёные, на сервере **14 падений**. Причины:

1. 11 тестов запускали литерал `python` — на Linux есть только `python3`.
   Исправлено: `sys.executable` (`df34be0`).
2. 3 теста TUI: в `run_tui` проверка зависимости шла раньше проверки терминала —
   в pipe без `prompt_toolkit` пользователю предлагали поставить extra вместо
   сообщения об отсутствии терминала. Порядок исправлен (`df34be0`).
3. 1 тест ключа TUI зависел от установленного extra. Исправлено (`e163cd8`).

Итог: **537 passed на Windows и на Linux**. Развёрнутая копия:
`/srv/projects/prokop` (venv `.venv`, `pip install -e src`), CLI работает
(`prokop --version`, `prokop doctor`).

### Открытый вопрос

Что именно имелось в виду под «Прокопий, который в артели hermes agent»:
шов `ProkopEngine` в copilot-v2 (по ADR 0003 — да, это он) или замена харнесса
роли `prokopiy` в OS3-флоте. На сервере Hermes-рантайма не найдено.
