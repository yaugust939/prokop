# prokop — универсальное ядро агента (clean room)

Оригинальная реализация ядра универсального агента, написанная **с нуля по
поведенческой спецификации** в процессе *чистой комнаты* (clean room design).
Код не копировался ни из одного существующего проекта — только поведение,
интерфейсы и контракты, зафиксированные в спецификациях OpenSpec.

> Поведенческим ориентиром служил открытый агент [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
> (MIT). Реализация в этом репозитории независима и оригинальна; процесс
> задокументирован в [`clean-room/`](clean-room/REGLAMENT.md) и
> [`openspec/`](openspec).

## Возможности

**Ядро (`agent_core`):**
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

**Обвес (`agent_core`):**
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

## Использование

Минимальный живой ход через модель (нужен ключ провайдера):

```bash
export DEEPSEEK_API_KEY=sk-...      # или положить в src/.env (в git не попадает)
python src/smoke_live.py
```

Программный ход:

```python
import asyncio
from agent_core.providers.registry import ProviderRegistry
from agent_core.transport.http_transport import ChatCompletionsTransport
from agent_core.loop.turn import AgentTurn

async def main():
    reg = ProviderRegistry(); reg.discover()
    transport = ChatCompletionsTransport(reg.get("deepseek"), api_key="sk-...")
    turn = AgentTurn(transport=transport, model="deepseek-chat",
                     provider="deepseek", identity="Полезный ассистент.")
    print((await turn.run("Привет!")).final_response)

asyncio.run(main())
```

## Интеграция с opencode

Ядро подключается к [opencode](https://opencode.ai) как MCP-сервер и даёт
инструменты `agent_turn`, `agent_schedule_job`, `agent_list_jobs`,
`agent_run_ticker`, `agent_run_command` (см. `src/`, раздел про провайдеров и
планировщик).

## Тесты

```bash
cd src
python -m pytest tests -q
```

На момент публикации — **171 тест**, все зелёные.

## Чистая комната

- [`clean-room/REGLAMENT.md`](clean-room/REGLAMENT.md) — регламент барьера
  (роли «читает эталон» / «пишет код только по спецификации»).
- [`clean-room/log.md`](clean-room/log.md) — журнал доступа; инвариант:
  реализация никогда не читала эталон.
- [`openspec/`](openspec) — поведенческие спецификации, по которым написан код.

Эталонный репозиторий в комплект **не входит** и не требуется для сборки.

## Лицензия

[MIT](LICENSE).
