# prokop — руководство

Практическое руководство: установка, быстрый старт, конфигурация, использование
(как библиотека и через opencode), примеры и устранение неполадок.

---

## 1. Установка

Требуется **Python 3.11+**.

### Из репозитория (для разработки)
```bash
git clone https://github.com/yaugust939/prokop.git
cd prokop
pip install -e src
```

### Проверка установки
```bash
python -c "import prokop; print(prokop.__version__)"   # 0.1.0
```

### Контейнер (чистая установка)
```bash
docker build -t prokop:clean .     # клонирует репо, ставит пакет, гоняет тесты
docker run --rm prokop:clean       # сообщает установленную версию
```

## 2. Быстрый старт

### Ключ модели
Для живых ходов нужен ключ провайдера (по умолчанию — DeepSeek):
```bash
export DEEPSEEK_API_KEY=sk-...
```
или положите его в `src/.env` (файл в `.gitignore`, в git не попадает):
```
DEEPSEEK_API_KEY=sk-...
```

### Первый ход
```bash
python src/smoke_live.py
```

Программно:
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

### Ход с инструментом
См. `src/agent_e2e.py` — регистрирует инструмент `multiply` и проверяет,
что агент сам его вызывает (полный цикл «модель → тул → модель»).

## 3. Конфигурация

- **Провайдер/модель** — через слой провайдеров (`prokop.providers`). Профиль
  задаёт имя, режим API, базовый URL, переменные ключа. Смена модели — без правки кода.
- **Домашний каталог** — по умолчанию `~/.prokop`; переопределяется `PROKOP_HOME`.
- **Секреты** — только через переменные окружения / `.env`.

## 4. Использование

### Как библиотека
Импортируйте подсистемы:
```python
from prokop.loop.turn import AgentTurn            # цикл агента
from prokop.tools.registry import ToolRegistry, register   # инструменты
from prokop.cron.store import JobStore            # планировщик
from prokop.backends.local import LocalBackend    # команды
```

### Через opencode (MCP)
MCP-сервер `prokop` даёт 5 инструментов:
| Инструмент | Назначение |
|---|---|
| `prokop_agent_turn` | независимый агентный ход |
| `prokop_agent_schedule_job` | создать задание планировщика |
| `prokop_agent_list_jobs` | список заданий |
| `prokop_agent_run_ticker` | исполнить наступившие задания |
| `prokop_agent_run_command` | команда через терминальный бэкенд |

В переключателе агентов opencode доступен агент **prokop** (личность — `SOUL.md`).

> После правки конфигурации opencode **перезапустите**, чтобы подхватить изменения.

## 5. Примеры

### Планировщик: задание «без агента»
```python
from pathlib import Path
from prokop.cron.model import Job, new_job_id
from prokop.cron.schedule import parse_schedule
from prokop.cron.store import JobStore
from prokop.cron.ticker import Ticker, add_job

home = Path.home() / ".prokop"
store = JobStore(home)
job = Job(id=new_job_id(), name="проверка", no_agent=True,
          script="echo ok", schedule=parse_schedule("каждые 5м"))
add_job(store, job)
print(Ticker(store, home).tick())
```

### Терминальный бэкенд
```python
from prokop.backends.local import LocalBackend
b = LocalBackend(workdir="/tmp/prokop-work")
print(b.run("echo hello && pwd").output)
```

## 6. Тесты
```bash
cd src
python -m pytest tests -q        # 173 теста
```

## 7. Устранение неполадок

| Симптом | Причина / решение |
|---|---|
| `НЕТ КЛЮЧА` в `smoke_live.py` | Задайте `DEEPSEEK_API_KEY` или положите в `src/.env` |
| `ModuleNotFoundError: prokop` | Выполните `pip install -e src` из корня |
| Модель не отвечает / таймаут | Проверьте ключ, сеть, `base_url` провайдера |
| Второй вызов модели падал на тул-коллах | Исправлено в 0.1.0 (сериализация `tool_calls`); обновитесь |
| Инструменты `prokop_*` не видны в opencode | Перезапустите opencode после правки конфига |

## 8. Куда дальше

- `docs/PRODUCT_SPEC.md` — полная спецификация и роадмап.
- `docs/FAQ.md` — частые вопросы.
- `SOUL.md` — личность агента.
