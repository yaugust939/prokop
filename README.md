# prokop — универсальное ядро агента

[![tests](https://github.com/yaugust939/prokop/actions/workflows/tests.yml/badge.svg)](https://github.com/yaugust939/prokop/actions/workflows/tests.yml)
[![license](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

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
docker build -t prokop:clean .      # клонирует репо, ставит пакет, гоняет тесты
docker run --rm prokop:clean        # сообщает установленную версию
```

Сборка сама прогоняет весь набор тестов — если установка битая, билд падает.

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

На момент публикации — **173 теста**, все зелёные.

## Спецификация

- [`openspec/`](openspec) — поведенческие спецификации, по которым написан код.

Эталонный репозиторий в комплект **не входит** и не требуется для сборки.

## Лицензия

[MIT](LICENSE).
