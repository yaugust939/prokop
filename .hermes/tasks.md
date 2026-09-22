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

- [ ] P2 · hermes · Пересобрать образ `artel3/agent-base`, чтобы патч получили контейнерные роли (adrian, analitik, kozma, pisar) (#36)
- [ ] P2 · hermes · Вебхуки MAX (#27), песочница (#18), остальные платформы (#19), orchestrator (#20)
- [ ] P2 · hermes · copilot-v2: `ProkopEngine` за швом `AgentEngine` (ADR 0003) — отдельная задача, если понадобится (#31)

## Заметки

### ✅ Переключение роли `prokopiy` на ядро prokop — выполнено

Проверено **в бою** через продовую шину (задача `task.assigned` → SSE-инбокс →
`execute()` → prokop → CRM + отчёт):

```
agt_agent:prokopiy: EXECUTE task smoke-prokop2-…: Проверка роли Прокопий на ядре prokop
agt_agent:prokopiy: prokop: ход завершён api_calls=1 messages=2 failed=False символов=46
agt_agent:prokopiy: LLM result: Ядро prokop на связи, друже — Прокопий у руля.
agt_agent:prokopiy: report: полный текст сохранён (…/vault/prokopiy/reports/…)
agt_agent:prokopiy: COMPLETED task smoke-prokop2-…
```

Ответ с характером Прокопия («друже») — персона передана в `identity` ядра.
Откат не потребовался (строка `prokop:` есть — значит ядро, а не прежний цикл).

**Что сделано:**
- prokop установлен для системного Python (`pip --break-system-packages -e
  /srv/projects/prokop/src`), CLI доступен как `/usr/local/bin/prokop`;
- адаптер `integrations/artel3/prokop_engine.py` (в нашем репо) — мозг роли на
  `AgentTurn`: тот же персонаж, память и инструменты, но цикл и бюджеты из ядра;
- инструменты не менялись: схемы от раннера, вызовы в его же `call_tool`;
- пропатчены **оба** модуля раннера (`os3-agent-runner.py` и
  `os3_agent_runner_compat.py`) — флот импортирует второй; бэкапы рядом;
- переключатель `ARTEL_PROKOP_ROLES=prokopiy` в drop-in юнита
  `artel3-fleet.service.d/prokop.conf`; пустое значение = полный откат;
- отказобезопасность проверена: при неверном ключе prokop вернул None, раннер
  автоматически откатился на прежний `llm_call`.

**Контроль:** `marfa`, `webmaster`, `yadro`, `seo` — по-прежнему на `llm_call`;
флот активен, ошибок за сессию нет.

### ⚠️ Найдено при развёртывании

Раннеров **два**: флот импортирует `os3_agent_runner_compat.py`, а
`os3-agent-runner.py` запускается внутри образа `artel3/agent-base:2`. Патч
только второго выглядит успешным, но флот продолжает работать прежним циклом
(задача выполняется, строки `prokop:` в логе нет). Зафиксировано в README.

### AI Artel: разведка (VM AIRTEL, 192.168.0.60)

- **Стек OS3** — `/docker/artel3`: реестр `config/agents.json` (66 ролей),
  классы `config/agent-classes.json`, секреты `secrets/<role>.env`, vault по роли.
  Роль **`prokopiy` — «Прокопий (Оркестрация)»**; в MAX-боте `id5118006623_bot`.
- **Мозг флота** — свой раннер на DeepSeek (`llm_call`), образ
  `artel3/agent-base:2`. **Установленного Hermes Agent на сервере нет**:
  следы — `vault/hermes` (персонаж Марфы), `benchmark_hermes`, `.env.bak-prehermes`.
- **`copilot-v2`** — «Копилот Декларанта V.2»; по ADR 0003 ассистент-движком
  должен стать наш prokop через шов `AgentEngine` → `ProkopEngine`. Причина
  отложения — «Windows-специфика и глобальные синглтоны» — **устранена** нашим
  аудитом и подтверждена зелёным прогоном на этой же VM.

### Что дал первый прогон на Linux

537 тестов: локально (Windows) зелёные, на сервере **14 падений**. Причины и
исправления (коммиты `df34be0`, `e163cd8`): тесты запускали литерал `python`
(на Linux только `python3`) → `sys.executable`; в `run_tui` проверка зависимости
шла раньше проверки терминала → порядок исправлен; один тест TUI зависел от
установленного extra. Итог: **537 passed и на Windows, и на Linux**.
