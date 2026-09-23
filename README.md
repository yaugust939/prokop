# prokop — универсальное ядро агента

[![tests](https://github.com/yaugust939/prokop/actions/workflows/tests.yml/badge.svg)](https://github.com/yaugust939/prokop/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

![prokop — универсальное ядро агента](docs/assets/prokop.png)

**prokop** — ядро универсального агента: цикл хода, инструменты, навыки, память,
хранилище сессий, слой модельных провайдеров и обвес (планировщик, субагенты,
терминальные бэкенды, гейтвей). Реализовано по поведенческой спецификации
(OpenSpec) — интерфейс и контракты зафиксированы в [`openspec/`](openspec).

## Возможности

**Ядро (`prokop`):**
- `loop` — цикл хода агента: пролог → «модель → инструменты → модель» → финализация;
  прерывание/steer/redirect, стриминг, байт-стабильный системный промпт,
  бюджеты итераций и настенных часов, ретраи, аренда сессии;
- `tools` — декларативный реестр инструментов и наборы (toolsets), коэрция
  аргументов, разрешения и блок-листы, прогрессивное раскрытие;
- `skills` — навыки (процедурная память): структура, доступ, самоулучшение,
  куратор жизненного цикла;
- `memory` — постоянная память: контракт провайдеров, менеджер, впрыск контекста;
- `store` — хранилище сессий (SQLite + FTS5) и полнотекстовый поиск;
- `providers` — слой модельных провайдеров (профили, реестр, смена модели без правки кода);
- `transport` — транспорт вызовов модели (режим `chat_completions`).

**Обвес (`prokop`):**
- `cron` — планировщик отложенных/периодических заданий (разбор расписаний,
  тикер, исполнение «без агента», доставка, переживание перезапуска);
- `subagents` — делегирование: изоляция ребёнка, роли лист/оркестратор,
  бюджеты, асинхронный возврат сводки;
- `backends` — терминальные бэкенды (локальный: спавн на команду, снимок
  окружения, обрезка вывода);
- `gateway` — ядро гейтвея и абстракция платформ обмена сообщениями (ключ
  сессии, нормализованное событие, контракт адаптера, авторизация, защита от
  параллельных ходов, кэш агентов, подготовка ответа).

## Установка

Требуется Python 3.11+.

```bash
git clone https://github.com/yaugust939/prokop.git
cd prokop
pip install -e src
```

Зависимости: `httpx`, `PyYAML` (плюс `pytest` для тестов).

## Контейнер (чистая установка)

Проверить установку с нуля и получить готовый образ:

```bash
docker build -t prokop:clean .      # ставит пакет из рабочего дерева, гоняет тесты
docker run --rm prokop:clean        # сообщает установленную версию
```

Сборка сама прогоняет весь набор тестов — если установка битая, билд падает.

## Платформы

Ядро платформенно-нейтрально: раскладка состояния одинакова на Windows,
macOS и Linux (``~/.prokop/<профиль>``, переопределяется ``PROKOP_HOME``).
Ни один модуль ядра не ветвится по ОС ради путей и не хранит личных
абсолютных путей. Отличия окружения собраны в
[`docs/PLATFORM_NOTES.md`](docs/PLATFORM_NOTES.md); CI гоняет тесты на
ubuntu / windows / macos.

## Командная строка

После установки доступна команда `prokop` — ядро самодостаточно, без opencode:

```bash
prokop doctor                        # проверить окружение (профиль, конфиг, ключ, бинари)
prokop config show                   # действующая конфигурация профиля
prokop turn "Сколько будет 17*23?"   # один ход агента
prokop chat                          # интерактивный цикл ходов
prokop tui                           # терминальный интерфейс (extra tui)
prokop sessions list|show|search     # сессии профиля
prokop skills list                   # навыки
prokop providers list                # провайдеры моделей
prokop cron list|add|tick            # планировщик
prokop mcp list|tools|call           # внешние MCP-серверы
prokop checkpoints list|create|restore|prune   # снимки состояния и откат
prokop security show|check|audit     # политики безопасности и журнал решений
prokop memory list|search|forget     # постоянная память профиля
```

Локальные команды (`doctor`, `config`, `sessions`, `skills`, `providers`,
`cron`, `mcp`, `checkpoints`, `security`, `memory`) работают без ключа модели и
без сети. Флаг `--json` даёт машиночитаемый вывод, коды возврата пригодны для
скриптов: `0` — успех, `1` — ошибка пользователя/конфигурации, `2` — ошибка
исполнения.

## Внешние MCP-серверы

Ядро — MCP-**клиент**: инструменты любого внешнего MCP-сервера попадают в
реестр ядра под именами `mcp__<сервер>__<инструмент>` и вызываются моделью
тем же диспетчером, что и встроенные. Серверы описываются в профиле и по
умолчанию выключены:

```yaml
# ~/.prokop/<профиль>/config.yaml
mcp:
  servers:
    files:
      command: ["python", "-m", "my_mcp_server"]   # список аргументов
      enabled: true
      timeout: 30
```

```bash
prokop mcp list                      # настроенные серверы
prokop mcp tools files               # инструменты сервера
prokop mcp call files read --args '{"path": "."}'
```

MCP SDK не требуется: клиент реализован на стандартной библиотеке
(JSON-RPC 2.0 поверх stdio).

## Память

Постоянная память профиля, переживающая перезапуск, — провайдер `file`:

```yaml
# ~/.prokop/<профиль>/config.yaml
memory:
  provider: file
  options:
    max_records: 2000      # предел записей (старые уплотняются)
    prefetch_limit: 5      # сколько записей подгружать в контекст
```

Агент получает инструменты `memory_save`, `memory_search`, `memory_forget`;
перед ходом релевантные записи подгружаются в контекст по совпадению слов.
Хранилище — `~/.prokop/<профиль>/memory/memory.jsonl` (в профиле, не в
проекте). Наблюдение: `prokop memory list|search|forget`. Неизвестное имя
провайдера даёт предупреждение и оставляет встроенную память.

## Адаптеры платформ

Реализованы два адаптера поверх HTTP-API платформ (`httpx`, без новых
зависимостей): **Telegram** (`gateway/telegram.py`) и **MAX**
(`gateway/max.py`) — российский мессенджер, для которого у ядра есть
полноценная реализация контракта.

Общее: подключение с проверкой токена, отправка с разбиением по лимиту
платформы, индикатор набора, информация о чате, отправка файлов, длинный опрос
и нормализация входящих в событие гейтвея; ошибки платформы отображаются в
категории контракта (`auth`, `rate_limit`, `transient`, `network`, `invalid`).

```python
from prokop.gateway.max import MaxAdapter          # или gateway.telegram
from prokop.gateway.engine import Gateway

adapter = MaxAdapter(token="<access_token>")
await adapter.connect()                            # GET /me
updates = await adapter.get_updates(timeout=25)    # указатель marker — внутри
event = adapter.normalize(updates[0])              # → InboundEvent
if event is not None:
    result = await Gateway(run_turn).handle(event)
    await adapter.send_text(event.source.chat_id, result.text or "")
```

Особенности MAX, учтённые в адаптере: база `platform-api2.max.ru`, авторизация
заголовком `Authorization`; указатель длинного опроса `marker`; идентификатор
сообщения — строка; адресация получателя `chat_id` (чат/канал) или `user:<id>`
(диалог); действие «набор текста» доступно только в групповых чатах; медиа
загружается в два шага (`POST /uploads` → загрузка → токен вложения).

## Политики безопасности

Правила задаются в профиле, решения принимаются в одной точке, каждое решение
попадает в журнал:

```yaml
# ~/.prokop/<профиль>/config.yaml
security:
  commands:
    deny:  ["curl *", "npm publish*"]   # запрещено всегда
    allow: ["rm -rf ./build"]           # снимает подтверждение
  paths:
    deny:  ["*/секреты/*"]              # ядро не тронет эти пути
  audit:
    enabled: true
```

```bash
prokop security show                 # действующие правила
prokop security check "rm -rf ./build"   # решение без выполнения
prokop security audit --limit 20     # журнал решений
```

Приоритет: жёсткий блок-лист → запрет из конфигурации → разрешение из
конфигурации → подтверждение для опасных команд → разрешение. Жёсткий
блок-лист не переопределяется настройками.

**Границы:** это слой **политик**, а не песочница. Он управляет решениями ядра
и инструментов, но не изолирует процессы и файловую систему — разрешённая
команда действует в пределах прав процесса. `security show` печатает это
указание явно.

## Снимки состояния и откат

Перед рискованной работой снимите состояние — вернуться можно в любой момент:

```bash
prokop checkpoints create ./project --label "до правок"
prokop checkpoints list
prokop checkpoints restore 20260922-201500-ab12cd
prokop checkpoints restore <id> --remove-extra   # + удалить лишние файлы
```

Безопасность по умолчанию: содержимое файлов возвращается, удалённые файлы
воссоздаются, а **лишние файлы не удаляются** — только по явному флагу. Перед
откатом автоматически создаётся страховочный снимок, поэтому откат обратим.
Служебные каталоги (`.git`, `node_modules`, `__pycache__`, кэши, артефакты
сборки) в снимок не попадают; потолки по размеру файла и числу снимков
настраиваются секцией `checkpoints` профиля. Агенту доступен инструмент
`checkpoint` (набор `checkpoints`).

## Терминальный интерфейс

```bash
pip install prokop[tui]              # опциональная зависимость
prokop tui                           # редактирование, история, статусная строка
```

Слэш-команды: `/help`, `/status`, `/model`, `/provider`, `/new`, `/sessions`,
`/clear`, `/quit`; строка без `/` уходит модели. Ход пишется в хранилище
сессий профиля — его видно в `prokop sessions list`. Без `prompt_toolkit`
команда не падает, а подсказывает установку extra и линейный режим
`prokop chat`.

## Использование

Минимальный живой ход через модель (нужен ключ провайдера):

```bash
export DEEPSEEK_API_KEY=sk-...      # или положить в src/.env (в git не попадает)
python src/smoke_live.py
```

Программный ход:

```python
import asyncio
from prokop.providers.registry import ProviderRegistry
from prokop.transport.http_transport import ChatCompletionsTransport
from prokop.loop.turn import AgentTurn

async def main():
    reg = ProviderRegistry(); reg.discover()
    transport = ChatCompletionsTransport(reg.get("deepseek"), api_key="sk-...")
    turn = AgentTurn(transport=transport, model="deepseek-chat",
                     provider="deepseek", identity="Полезный ассистент.")
    print((await turn.run("Привет!")).final_response)

asyncio.run(main())
```

## Интеграция с opencode

Ядро подключается к [opencode](https://opencode.ai) как MCP-сервер `prokop` и
даёт инструменты `prokop_agent_turn`, `prokop_agent_schedule_job`,
`prokop_agent_list_jobs`, `prokop_agent_run_ticker`, `prokop_agent_run_command`.
В переключателе агентов opencode доступен агент **prokop** (универсальный
помощник), использующий эти инструменты.

## Тесты

```bash
cd src
python -m pytest tests -q
```

На момент публикации — **537 тестов**, все зелёные.

## Спецификация

- [`openspec/`](openspec) — поведенческие спецификации, по которым написан код.

Эталонный репозиторий в комплект **не входит** и не требуется для сборки.

## Документация

- [`SOUL.md`](SOUL.md) — личность агента (характер, ценности, стиль, границы).
- [`docs/PLATFORM_NOTES.md`](docs/PLATFORM_NOTES.md) — инварианты путей и точки, где платформа различается.
- [`docs/PARITY.md`](docs/PARITY.md) — паритет с аналогами: где не уступаем, где гэпы.
- [`docs/PRODUCT_SPEC.md`](docs/PRODUCT_SPEC.md) — продуктовая спецификация и роадмап.
- [`docs/GUIDE.md`](docs/GUIDE.md) — руководство: установка, быстрый старт, примеры.
- [`docs/FAQ.md`](docs/FAQ.md) — частые вопросы.
- [`docs/MARKETING.md`](docs/MARKETING.md) — позиционирование и ключевые сообщения.

## Лицензия

[MIT](LICENSE).
