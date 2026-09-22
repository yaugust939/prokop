## ADDED Requirements

### Requirement: Ticker исполняет задания с target "opencode"

Планировщик prokop SHALL поддерживать delivery-target `"opencode"` для заданий: когда задание наступает по расписанию, Ticker ВМЕСТО вызова `AgentTurn` вызывает `orchestrator.spawn()` с промптом задания. Промпт задания MAY содержать тег `#project:<alias>` — тогда задание выполняется в конкретном проекте, иначе в проекте `global`.

#### Scenario: Задание с target opencode исполняется через spawn

- **WHEN** наступило время задания с `delivery_target: "opencode"` и промптом, содержащим `#project:kladez`
- **THEN** Ticker запускает headless-сессию opencode в проекте `kladez` с этим промптом

#### Scenario: Задание без проекта исполняется глобально

- **WHEN** наступило время задания с target `"opencode"` без тега `#project`
- **THEN** задание выполняется через spawn в проекте `global` с агентом `hermes`

### Requirement: Результаты заданий сохраняются и репортятся

Результат исполнения задания с target `"opencode"` SHALL сохраняться в `~/.prokop/cron/outputs/<job_id>/<stamp>.txt` (механизм `LocalDelivery`) И передаваться в отчётность трекера `tasks.md`.

#### Scenario: Результат задания записан и отмечен в трекере

- **WHEN** задание с target `"opencode"` успешно выполнено
- **THEN** в `~/.prokop/cron/outputs/<job_id>/` появляется файл результата, а в `tasks.md` обновляется строка с резюме результата

### Requirement: Ticker запускается без открытой сессии opencode

Планировщик SHALL иметь механизм запуска tick'а, независимый от активной сессии opencode: либо вызов `agent_run_ticker` из оркестратора (каждые 10–15 минут), либо триггер Windows Task Scheduler, вызывающий tick напрямую (например `python -c "from prokop.cron.ticker import ..."`).

#### Scenario: Задание исполняется при закрытой сессии opencode

- **WHEN** сессия opencode не открыта, но Windows Task Scheduler запускает tick
- **THEN** наступившие задания с target `"opencode"` исполняются через spawn без участия TUI
