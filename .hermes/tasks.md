# HERMES — трекер задач проекта

Формат: `- [статус] P<0..2> · <исполнитель> · <описание> (#id)`
статусы: `[ ]` ожидает · `[~]` в работе · `[x]` готово · `[!]` заблокировано

## Ожидает уточнения

- [ ] P2 · hermes · Версионировать `prokop_max_engine.py` в репозитории (сейчас только на сервере) (#40)

## Выполнено: Прокопий в MAX — наша модель + ядро prokop

- [x] P0 · hermes · **Прокопий в MAX (личный ассистент): модель `deepseek-v4-flash` и движок на ядре prokop** (#38)

### Что сделано

Канал `artel3-max@prokopiy` → `/docker/artel3/scripts/max-channel.py`:

1. **Модель** — `deepseek-chat` → **`deepseek-v4-flash`**
   (`MODEL = os.environ.get('ARTEL_MAX_MODEL', 'deepseek-v4-flash')`, строка 26;
   подставляется в `_deepseek`, строка 283). Прежний `deepseek-chat` — по
   собственной записи артели (`copilot-v2/docs/HISTORY.md`) в реестре DeepSeek
   отсутствует. Проверено ключом роли: оба id отвечают `HTTP 200`.
2. **Движок** — ответы Прокопия собирает `AgentTurn` из prokop
   (`/docker/artel3/scripts/prokop_max_engine.py`): та же персона, тот же
   контекст диалога, те же инструменты; цикл хода и бюджеты — из ядра.
   Включается `ARTEL_MAX_PROKOP_AGENTS` (по умолчанию **только `prokopiy`**).
3. **Отказобезопасность** — при любой ошибке ядра возвращается `None` и канал
   идёт прежним путём `_deepseek`. Выключение: пустой `ARTEL_MAX_PROKOP_AGENTS`.

### Проверено

| Проверка | Результат |
|---|---|
| Прокопий через ядро | `prokop: ход завершён api_calls=1 messages=2 failed=False модель=deepseek-v4-flash` → «Проверка движка прошла — я на связи, друже.» |
| Персона | загружена из vault, 8277 символов — стиль Прокопия сохранён |
| Контроль (другая роль) | `marfa` → `'ок'` старым путём, строки `prokop:` нет |
| Живой канал | `systemctl restart artel3-max@prokopiy` → `active`, `polling, marker=1790102638313` |
| Прочие каналы | `marfa`, `yurist`, `mayor-m`, `kozma` — `active`, не тронуты |
| Ошибки | 0 |

Бэкап: `/docker/artel3/scripts/max-channel.py-bak-prokop-20260922-220517`.
Ядро для системного Python установлено (`pip -e /srv/projects/prokop/src`) —
теперь это законная зависимость канала.

### Важно про охват

Смена модели затрагивает **все** MAX-каналы (это один файл и общая функция
`_deepseek`), смена движка — **только Прокопия** (`ARTEL_MAX_PROKOP_AGENTS`).
Расширить движок на другие каналы: `ARTEL_MAX_PROKOP_AGENTS='*'` в юните.

## Откат (выполнен)

- [x] P0 · hermes · **Полный откат правок в контуре AI Artel** — флот, контейнеры, образ, пакеты, артефакты (#39)

Проверено: флот `active` без `ARTEL_PROKOP_ROLES`; оба раннера возвращены из
бэкапов (0 следов); `prokop_engine.py` удалён; drop-in снят; контейнеры на
`artel3/agent-base:2` healthy; образ `:3` удалён; `PROKOP_ROLES` в compose нет;
генератор compose восстановлен; контекст сборки очищен; `prokop`/`httpx`/
`typing_extensions` сняты с системного Python (`yaml` системный на месте);
отчёты проверок из vault удалены; временные скрипты удалены.
`integrations/artel3/` из репозитория удалён.

## Закрыто ранее

Сессия 1 (f2e5adc) — аудит, универсальность, CLI, TUI, MCP-клиент, checkpoints,
security. Сессия 2 (8d978e0) — файловая память, адаптер Telegram. Сессия 3
(0015a1f) — адаптер MAX. Сессия 4 — публикация в git, развёртывание в AI Artel,
первый прогон на Linux.

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
- [x] P0 · hermes · Пуш в git: origin/main синхронизирован (#28)
- [x] P0 · hermes · Развернуть репо в AI Artel: bare /srv/git/prokop.git + рабочая копия /srv/projects/prokop (#29)
- [x] P0 · hermes · Первый прогон на Linux: 14 падений → найдены и исправлены 2 настоящие причины (#30)

## Разведка: где живёт Прокопий в MAX (важно)

### Прокопий в MAX — работает, на AIRTEL, на DeepSeek

- Канал: `artel3-max@prokopiy.service` (AIRTEL) → `/docker/artel3/scripts/max-channel.py`.
- Личный чат админа: `private:279303071`, пользователь `7165150`.
- Последний диалог: `2026-09-22T21:44 «Ты тут?» → «Тут, друже. Никуда не делся.»`
- Модель в `max-channel.py` (строка 271): **`deepseek-chat`** — тот самый id,
  которого, по собственной записи артели (`copilot-v2/docs/HISTORY.md`), **нет
  в реестре DeepSeek**: доступны `deepseek-flash`, `deepseek-v4-flash`,
  `deepseek-v4-flash-vision-exp`. Там же было указание «убрать `deepseek-chat`
  из harness-контуров».
- Персона: `vault/prokopiy/soul/IDENTITY.md` — «Прокопий, персональный
  ИИ-помощник с русской душой».

### Hermes — остаток июня, не работает

- **Hermes Agent** установлен на **хосте Proxmox** (`192.168.0.2`): `/root/.hermes`
  (config.yaml, auth.json, logs, kanban.db, плагин `plugins/platforms/max/`).
- Шлюз **мёртв с 29.06.2026**: `gateway_state.json` ссылается на несуществующий
  PID, `MAX_TOKEN` в `.env` нет, логи обрываются 29.06.
- Модель в его конфиге: `deepseek-v4-flash` / провайдер `deepseek`; в
  `auth.json` — пул GigaChat.
- Память Прокопия: «Создан с нуля платформенный адаптер MAX Messenger для
  Hermes Agent (v0.17.0)» — это июньская работа.
- На Proxmox также остался OS3-агент роли `hermes` («Hermes (рантайм/личный
  контур)», контейнер `artel3-agent-hermes`, ключ `MASTER_DEEPSEEK_API_KEY`) —
  артефакт прежнего контура; MAX-канала у него нет.

### Что это значит

Живой Прокопий в MAX уже на нашей инфраструктуре (AIRTEL OS3 + DeepSeek), но
на **устаревшем id модели `deepseek-chat`**. Hermes как рантайм не работает.
Нужно подтверждение, что именно имеется в виду под «поменять на нашу модель».

## Осталось

- [ ] P2 · hermes · Вебхуки MAX (#27), песочница (#18), остальные платформы (#19), orchestrator (#20)
- [ ] P2 · hermes · copilot-v2: `ProkopEngine` за швом `AgentEngine` (ADR 0003) (#31)
