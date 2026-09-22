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
См. `src/e2e_live.py` — регистрирует инструмент `multiply` и проверяет,
что агент сам его вызывает (полный цикл «модель → тул → модель»).

## 3. Конфигурация

- **Провайдер/модель** — через слой провайдеров (`prokop.providers`). Профиль
  задаёт имя, режим API, базовый URL, переменные ключа. Смена модели — без правки кода.
- **Домашний каталог** — по умолчанию `~/.prokop`; переопределяется `PROKOP_HOME`.
- **Секреты** — только через переменные окружения / `.env`.

## 4. Использование

### Командная строка
После `pip install -e src` доступна команда `prokop` (точка входа
`prokop.cli.main:main`). Команды делятся на локальные — работают без ключа
модели и без сети — и сетевые.

| Команда | Что делает |
|---|---|
| `prokop doctor` | проверка окружения: профиль, запись, конфигурация, ключ модели, провайдеры, python, бинари `opencode` и `cua-driver` |
| `prokop config show` | действующая конфигурация профиля и путь к домашнему каталогу (файлы не изменяются) |
| `prokop sessions list` | сессии профиля (id, активность, число сообщений, модель) |
| `prokop sessions show <id>` | сообщения одной сессии |
| `prokop sessions search <запрос>` | полнотекстовый поиск по сообщениям |
| `prokop skills list` | навыки профиля из `<профиль>/skills` |
| `prokop providers list` | провайдеры моделей из реестра (режим API, переменная ключа) |
| `prokop cron list` | задания планировщика |
| `prokop cron add --name N --schedule S [--prompt P \| --script X] [--no-agent]` | создать задание |
| `prokop cron tick` | исполнить наступившие задания (один тик) |
| `prokop mcp list` | настроенные MCP-серверы с признаком включённости |
| `prokop mcp tools <сервер>` | инструменты сервера (исходное имя → имя в реестре) |
| `prokop mcp call <сервер> <инструмент> --args '<json>'` | вызвать инструмент сервера |
| `prokop checkpoints list` | снимки состояния профиля |
| `prokop checkpoints create <путь>... [--label L]` | создать снимок |
| `prokop checkpoints restore <id> [--remove-extra]` | откатить состояние из снимка |
| `prokop checkpoints prune [--keep N]` | удалить старые снимки |
| `prokop security show` | действующие правила безопасности и границы слоя |
| `prokop security check "<команда>"` | решение по команде без выполнения |
| `prokop security audit [--limit N]` | журнал решений |
| `prokop turn "<запрос>" [--model M] [--provider P]` | один ход агента |
| `prokop chat [--model M] [--provider P]` | линейный цикл ходов; выход по `exit`/`quit`/EOF |
| `prokop tui [--model M] [--provider P]` | терминальный интерфейс (нужен extra `tui`) |

Форматы и коды возврата:

- по умолчанию — краткий текст; флаг `--json` (до или после подкоманды) даёт
  валидный JSON в UTF-8 без экранирования кириллицы;
- `0` — успех, `1` — ошибка пользователя или конфигурации (в том числе
  неверные аргументы и отсутствие ключа), `2` — ошибка исполнения.

Модель берётся из `model.model` конфигурации профиля; при отсутствии —
ошибка с подсказкой (можно задать флагом `--model`). Ключ — из переменной,
указанной в `model.api_key_env`, иначе из `env_vars` профиля провайдера
(например `DEEPSEEK_API_KEY`).

### Внешние MCP-серверы
Ядро умеет быть MCP-клиентом: поднимает внешние MCP-серверы по stdio и
отдаёт их инструменты модели. Секция конфигурации профиля:

```yaml
mcp:
  servers:
    files:
      command: ["python", "-m", "my_mcp_server"]   # только список аргументов
      enabled: true                                # по умолчанию false
      env: {TOKEN: "..."}                          # опционально
      cwd: "/path/to/workdir"                      # опционально
      timeout: 30                                  # опционально, секунды
```

Правила:

- `command` — список аргументов; строковая форма не принимается (никакой
  склейки в командную строку);
- сервер выключен, если `enabled` не задан явно;
- инструменты доступны модели только если включён набор `mcp`
  (`toolsets.enabled: [core, mcp]`); имена в реестре — `mcp__<сервер>__<инструмент>`,
  вызов уходит серверу под исходным именем;
- недоступный сервер пропускается с предупреждением и не ломает остальные;
- MCP SDK не нужен: клиент реализован на стандартной библиотеке
  (JSON-RPC 2.0 поверх stdio, `src/prokop/mcp/`).

Проверка вручную — `prokop mcp list|tools|call` (см. таблицу команд).

### Снимки состояния и откат
```bash
prokop checkpoints create ./project --label "до правок"
prokop checkpoints list
prokop checkpoints restore <id>
```

Что снимается: файлы и каталоги (содержимое копируется, никаких теней ФС и
симлинков — одинаково на всех платформах). Служебные каталоги и файлы
(`.git`, `node_modules`, `__pycache__`, кэши, `*.pyc`, `*.egg-info`)
игнорируются. Снимки лежат в `<профиль>/checkpoints/`.

Безопасность отката:

- содержимое записанных файлов возвращается, отсутствующие файлы и каталоги
  воссоздаются;
- **лишние файлы не удаляются** — для этого нужен явный флаг `--remove-extra`
  (он затрагивает только файлы внутри снятых каталогов);
- перед восстановлением автоматически создаётся страховочный снимок текущего
  состояния, поэтому откат обратим (в отчёте возвращается его идентификатор);
- неизвестный идентификатор и несуществующий путь — ошибка с кодом `1`, файлы
  не изменяются.

Настройки в конфигурации профиля:

```yaml
checkpoints:
  enabled: true            # доступность инструмента агенту (по умолчанию true)
  max_entries: 20          # сколько снимков хранить (старые удаляются)
  max_file_bytes: 5242880  # потолок размера одного файла (5 МБ)
  ignore: ["*.log"]        # дополнительные шаблоны игнорирования
```

Агенту доступен инструмент `checkpoint` (`create`, `list`, `restore`,
`prune`) в наборе `checkpoints` — включается через
`toolsets.enabled: [core, checkpoints]`.

### Политики безопасности
```yaml
security:
  commands:
    deny:  ["curl *", "npm publish*"]   # запрет (сильнее разрешения)
    allow: ["rm -rf ./build"]           # снимает подтверждение
  paths:
    deny:  ["*/секреты/*"]              # ядро не тронет эти пути
    allow: ["*/секреты/readme.txt"]     # перекрывает запрет
  audit:
    enabled: true
```

Приоритет решений по команде: жёсткий блок-лист (запрет, не переопределяется)
→ `commands.deny` → `commands.allow` → детектор опасных команд (подтверждение)
→ разрешение. По пути: `paths.deny` → `paths.allow` → разрешение.

Политика путей применяется к операциям **самого ядра** — созданию снимков и
восстановлению из них; содержимое shell-команд статически не анализируется
(для команд работает политика команд).

Проверка и наблюдение:

```bash
prokop security show                    # правила + границы слоя
prokop security check "rm -rf ./build"  # ask: опасная команда (рекурсивное удаление)
prokop security audit --limit 20        # журнал решений
```

Журнал — `<профиль>/logs/security.jsonl` (JSONL, только добавление). Запись
best-effort: сбой журнала не прерывает операцию. Ротация пока не делается —
чтение идёт по хвосту.

**Границы:** это слой политик, а не песочница. Он не изолирует процессы и
файловую систему: разрешённая команда действует в пределах прав процесса.
Изоляция (Job Objects / namespaces / sandbox-exec) платформенно-специфична и
в это изменение не входит.

### Терминальный интерфейс (TUI)
```bash
pip install prokop[tui]      # опциональная зависимость (prompt_toolkit)
prokop tui                   # интерактивная сессия
```

Что даёт: редактирование ввода, история введённых строк, статусная строка
(провайдер, модель, сессия, число ходов), потоковый вывод ответа.

Слэш-команды:

| Команда | Действие |
|---|---|
| `/help` | справка |
| `/status` | состояние сессии |
| `/model [имя]` | показать или сменить модель |
| `/provider [имя]` | показать или сменить провайдера (имя проверяется по реестру) |
| `/new` | начать новую сессию |
| `/sessions` | последние сохранённые сессии |
| `/clear` | очистить историю текущего процесса (записи не удаляются) |
| `/quit` | выход |

Строка без `/` отправляется модели. Ход сохраняется в хранилище сессий
профиля (источник `tui`), поэтому сессию видно в `prokop sessions list|show`.
Ошибка хода печатается и не завершает интерфейс.

Деградация: без `prompt_toolkit` команда сообщает, как установить extra, и
предлагает `prokop chat`; без терминала (ввод подан потоком) — отказывается с
кодом `1`, не пытаясь рисовать интерфейс.

### Как библиотека
Импортируйте подсистемы:
```python
from prokop.loop.turn import AgentTurn            # цикл агента
from prokop.tools.registry import ToolRegistry, register   # инструменты
from prokop.cron.store import JobStore            # планировщик
from prokop.backends.local import LocalBackend    # команды
```

### Через opencode (MCP)
MCP-сервер `prokop` даёт инструменты:
| Инструмент | Назначение |
|---|---|
| `prokop_agent_turn` | независимый агентный ход |
| `prokop_agent_schedule_job` | создать задание планировщика |
| `prokop_agent_list_jobs` | список заданий |
| `prokop_agent_run_ticker` | исполнить наступившие задания |
| `prokop_agent_run_command` | команда через терминальный бэкенд |
| `prokop_computer_use` | GUI-автоматизация: захват экрана/окон, клики, ввод |

В переключателе агентов opencode доступен агент **prokop** (личность — `SOUL.md`).

> После правки конфигурации opencode **перезапустите**, чтобы подхватить изменения.

### GUI-автоматизация (`computer_use`)

Инструмент управляет десктопом: скриншоты окна/экрана (`som` — с номерами
элементов, `vision` — чистый снимок, `ax` — дерево доступности), клики и ввод
по индексу элемента или координатам, скролл/драг, клавиши, окна и фокус.
Захват безопасен; действия требуют подтверждения (permission
`prokop_computer_use: ask` в opencode.json).

Бэкенды (по приоритету):
1. **cua-driver** — фоновый ввод без кражи курсора (если в PATH); работает
   на Windows, macOS и Linux;
2. **локальный Windows** — `pip install prokop[gui]` (mss, pyautogui,
   pywinauto, Pillow). Единственный локальный десктоп-бэкенд; на macOS и
   Linux используйте cua-driver.

Выбор переопределяется `PROKOP_GUI_BACKEND=auto|cua|windows`. Если ни один
бэкенд недоступен, инструмент скрыт из схемы. Сценарии — в скиле
`gui-automation`.

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
python -m pytest tests -q        # 403 тестов
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
