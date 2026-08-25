# Протокол чистоты (clean room log)

> Назначение — доказательная база оригинальности. Фиксирует, какая роль имела
> доступ к каким файлам. Инвариант: в журнале НЕ существует строки
> `B → reference\`.

## Параметры барьера

- **Reference (оригинал):** https://github.com/nousresearch/hermes-agent
- **Закреплённый коммит:** `e5032945cbebb64b8a819b66ec831c1906297b81`
- **Зона A (только чтение оригинала):** `reference\`
- **Канал A → B:** только `openspec\changes\` (спецификация OpenSpec)
- **Зона B (реализация):** `src\`
- **Роли:** A = `explore` · B = `general` · Диспетчер = `hermes`

## Журнал доступа

| # | Дата | Роль | Агент | Действие | Объект | Результат |
|---|------|------|-------|----------|--------|-----------|
| 1 | 2026-08-25 | — | hermes | Клонировал оригинал (shallow) | reference\ | pinned `e503294…` |
| 2 | 2026-08-25 | A | explore | Изучил эталон (ядро), извлёк поведенческую спецификацию | reference\ | отчёт → openspec\changes\hermes-core |
| 3 | 2026-08-25 | A | hermes | Создал OpenSpec change hermes-core по отчёту explore | openspec\changes\hermes-core | 4/4 артефакта, valid |
| 4 | 2026-08-25 | B | hermes | Реализация ядра по спецификации (субагенты недоступны: Insufficient Balance) — диспетчер принял роль Team B | openspec\changes\hermes-core | reference\ не читается |
| 5 | 2026-08-25 | B | hermes | Реализовал ядро в src\ (пакет agent_core, 8 групп / 36 задач); 61 тест зелёный, импорт+компиляция OK | src\ | приёмка hermes-core: 36/36 |
| 6 | 2026-08-25 | A | explore | Изучил эталон (обвес), извлёк поведенческую спецификацию 5 подсистем (gateway, messaging, cron, subagents, backends) | reference\ | отчёт → openspec\changes\hermes-peripherals |
| 7 | 2026-08-25 | B | hermes | Создал OpenSpec change hermes-peripherals (proposal/design/specs×5/tasks, valid) и реализовал Фазу 1 (планировщик, модуль cron) по спецификации | openspec\changes\hermes-peripherals | 23 теста зелёные, reference\ не читается |
| 8 | 2026-08-25 | B | general | Реализовал подсистему субагентов/делегирования (пакет subagents: бюджет, роли, реестр, очередь, изоляция, инструмент) по спецификации | openspec\changes\hermes-peripherals\specs\subagents | 26 тестов зелёные, reference\ не читается |
| 9 | 2026-08-25 | B | hermes | Реализовал терминальные бэкенды (пакет backends: контракт, снимок сессии, локальный бэкенд, обрезка вывода, выбор из конфига) по спецификации | openspec\changes\hermes-peripherals\specs\backends | 13 тестов зелёные, reference\ не читается |
| 10 | 2026-08-25 | B | general | Реализовал ядро гейтвея и абстракцию платформ (пакет gateway: ключ сессии, событие, контракт адаптера, авторизация, guard, кэш агентов, подготовка ответа) по спецификации | openspec\changes\hermes-peripherals\specs\gateway + messaging | 48 тестов зелёные, reference\ не читается |
| 11 | 2026-08-25 | — | hermes | Зафиксировал Фазу 0: ГИБРИД — ядро остаётся чистой комнатой; обвес выносится во второй проект на AgentScope 2.0 + Spark Design | clean-room\REGLAMENT.md §9; D:\OBS_SparkDesign_AgentScope\KONCEPT.md | §9 добавлен, концепт записан |

## Правило

Запись `B (general) → reference\` — нарушение барьера. При обнаружении:
остановка работ, затронутый код перегенерируется с нуля строго по `openspec\changes\`,
запись помечается `[!]` как инцидент.
