# Адаптер для AI Artel OS3 (роль `prokopiy`)

Здесь лежит интеграция ядра `prokop` с контуром AI Artel OS3: роль
**`prokopiy`** («Прокопий (Оркестрация)») обслуживается `AgentTurn` из ядра
вместо собственного цикла раннера.

## Что меняется

| Слой | Было | Стало |
|---|---|---|
| Мозг роли | `llm_call()` в `os3-agent-runner.py` — свой цикл на DeepSeek с инструментами | `AgentTurn` из `prokop` (`loop`, бюджеты, ретраи, диспетчер инструментов) |
| Персона, память | читаются раннером и склеиваются в промпт | те же данные передаются в `identity` ядра |
| Инструменты | MCP-шлюзы, `vault_read`/`vault_write`, правки сайтов | **не меняются**: схемы от раннера, вызовы уходят в его же `call_tool` |
| Доставка, история, MAX | раннер | **не меняются** |

Заменяется только «мозг»: всё остальное (приём задач из CRM, идемпотентность,
heartbeat, запись дневника и полного отчёта, канал MAX) остаётся в раннере.

## Развёртывание

```bash
# 1. Ядро для системного Python (раннер запускается /usr/bin/python3 вне Docker)
sudo pip3 install --break-system-packages --ignore-installed typing_extensions httpx PyYAML
sudo pip3 install --break-system-packages --no-deps -e /srv/projects/prokop/src

# 2. Адаптер рядом с раннером
sudo cp /srv/projects/prokop/integrations/artel3/prokop_engine.py /docker/artel3/scripts/

# 3. Патч ОБОИХ модулей раннера (см. предупреждение ниже)
sudo python3 patch_runner_prokop2.py \
    /docker/artel3/scripts/os3-agent-runner.py \
    /docker/artel3/scripts/os3_agent_runner_compat.py

# 4. Явный переключатель и перезапуск
sudo systemctl edit artel3-fleet.service     # Environment=ARTEL_PROKOP_ROLES=prokopiy
sudo systemctl daemon-reload && sudo systemctl restart artel3-fleet
```

> **Важно: раннеров два.** `os3-agent-fleet.py` импортирует
> `os3_agent_runner_compat.py`, а `os3-agent-runner.py` запускается внутри
> контейнеров (`artel3/agent-base:2`, `CMD … os3-agent-runner.py`). Патчить
> нужно **оба**: иначе флот продолжит работать прежним циклом (именно на этом
> легко обмануться — патч «применён», а в логе нет строки `prokop:`).
> Контейнерные роли (`adrian`, `analitik`, `kozma`, `pisar`) подхватят патч
> только после пересборки образа `artel3/agent-base`.

## Управление

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `ARTEL_PROKOP_ROLES` | `prokopiy` | роли на ядре prokop: `*` (все), список через запятую или пусто (выключено) |
| `ARTEL_PROKOP_MODEL` | `deepseek-chat` | модель роли (совпадает с моделью раннера) |
| `ARTEL_PROKOP_TIMEOUT` | `180` | таймаут HTTP до провайдера, секунд |
| `ARTEL_PROKOP_FAIL_NOTE` | `3` | после скольких повторов падающего вызова добавить модели указание |
| `ARTEL_PROKOP_FAIL_STOP` | `5` | после скольких повторов прервать ход |

Переменные задаются в юните флота:

```bash
sudo systemctl edit artel3-fleet.service
# [Service]
# Environment=ARTEL_PROKOP_ROLES=*
sudo systemctl restart artel3-fleet
```

## Контейнерные роли

Часть ролей (по `config/agents-containerized.json`) работает не во флоте, а
отдельными контейнерами на образе `artel3/agent-base`. У них **свой, минимальный
раннер** (`/app/os3-agent-runner.py`, ~227 строк, без инструментов), поэтому его
нужно патчить отдельно.

```bash
CTX=/docker/artel3/build/agent

# 1. Патч контейнерного раннера, адаптер и исходники ядра — в контекст сборки
sudo python3 patch_container_runner.py $CTX/os3-agent-runner.py
sudo cp /srv/projects/prokop/integrations/artel3/prokop_engine.py $CTX/
sudo cp -r /srv/projects/prokop/src $CTX/prokop-src   # без .venv, tests, .env

# 2. Образ поверх имеющегося (overlay — не зависит от egress к Docker Hub)
sudo docker build -f $CTX/Dockerfile.prokop -t artel3/agent-base:3 $CTX

# 3. Проверка образа до выката
sudo docker run --rm -e ARTEL_PROKOP_ROLES='*' artel3/agent-base:3 python3 /app/prokop_engine.py

# 4. Compose: новый образ + переменная в каждый сервис (генератором, не руками)
cd /docker/artel3/compose
sudo cp agents.generated.yml agents.generated.yml.bak-preprokop-$(date +%Y%m%d-%H%M%S)
sudo env ARTEL_AGENT_IMAGE=artel3/agent-base:3 ARTEL_PROKOP_ROLES='*' \
    python3 /docker/artel3/scripts/gen_agent_compose.py
sudo docker compose -p artel3-agents -f agents.generated.yml up -d
```

Логи контейнерных ролей — в `docker logs artel3-agent-<роль>` (их stdout), а не
в общий `/var/log/artel3-agents.log`.

Откат контейнеров: `ARTEL_AGENT_IMAGE=artel3/agent-base:2 ARTEL_PROKOP_ROLES=`
и повторный прогон генератора с `up -d`. Образ `:2` остаётся на месте.

## Отказобезопасность

`prokop_engine.run()` возвращает `None` при любой ошибке — недоступное ядро,
сбой импорта, ошибка хода. Раннер в этом случае **откатывается на прежний
`llm_call`**, поэтому роль не остаётся без ответа. Отключение — пустое значение
`ARTEL_PROKOP_ROLES`.

**Защита от зацикливания портирована.** Прежний харнесс останавливал агента,
который повторяет один и тот же падающий вызов (в артели был случай: 86 вызовов
инструментов и ни одной записи кода). В адаптере тот же учёт: после
`ARTEL_PROKOP_FAIL_NOTE` (3) повторов одного падающего вызова в его результат
добавляется указание не повторять вызов и собрать отчёт из имеющихся данных;
после `ARTEL_PROKOP_FAIL_STOP` (5) ход прерывается через `TurnControl`, и задача
завершается честным текстом «данные получить не удалось» с кодом ошибки — как
результат, а не как падение (статус не уходит в `blocked`).

## Диагностика

```bash
python3 /docker/artel3/scripts/prokop_engine.py   # установлено ли ядро, роли, base_url, модель
journalctl -u artel3-fleet -n 50 | grep -i prokop
grep -i 'prokop' /var/log/artel3-agents.log
```

Признак того, что роль действительно идёт через ядро — строка в логе агентов:

```
agt_agent:prokopiy: prokop: ход завершён api_calls=1 messages=2 failed=False символов=46
```

Если её нет, а задача выполнена — работает откат на прежний `llm_call`
(проверьте `ARTEL_PROKOP_ROLES`, наличие `prokop` для системного Python и
патч обоих модулей раннера).

## Откат

```bash
sudo systemctl edit artel3-fleet.service     # Environment=ARTEL_PROKOP_ROLES=
sudo systemctl restart artel3-fleet
```

Патч раннера минимален и обратим: бэкап рядом с файлом
(`os3-agent-runner.py-bak-prokop-<штамп>`).
