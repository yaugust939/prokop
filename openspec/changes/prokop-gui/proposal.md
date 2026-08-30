## Why

Прокопий — headless-агент: умеет текст (turn), планировщик и shell-команды, но не видит и не трогает графический интерфейс. Для реальной работы (окна, приложения, десктоп-сценарии, чтение UI) ему нужны «глаза и руки»: скриншоты экрана/окон, клики, ввод, управление окнами. В эталоне `reference/tools/computer_use/` уже есть проверенная модель такой автоматизации (SOM/vision/ax-захваты, клики по индексам элементов, ввод, окна, фокус) — переносим её в ядро прокопия оригинальной реализацией.

## What Changes

- Новый пакет ядра `src/prokop/computer/` — десктопная GUI-автоматизация:
  - `capture` в трёх режимах: `som` (скриншот с нумерованными оверлеями элементов + AX-дерево), `vision` (чистый скриншот), `ax` (только accessibility-дерево);
  - действия: `click` (по индексу элемента или координатам), `double_click`, `right_click`, `drag`, `scroll`, `type`, `key`, `set_value`, `wait`, `list_apps`, `list_windows`, `focus_app`, `capture_after`;
  - бэкенды: локальный (Windows UIA/pyautogui/mss) и подключаемый через MCP (cua-driver) — абстракция `ComputerUseBackend`.
- Регистрация инструмента `computer_use` в реестре инструментов (`tools/registry.py`) и новом наборе `gui` в `tools/toolsets.py`.
- Мультимодальный контракт результата: захваты возвращаются через существующую обёртку `_multimodal` (текст-сводка + base64-изображение), чтобы vision-модели видели скриншот, а текстовые — только сводку.
- Проброс инструмента через MCP-сервер `prokop_mcp.py` (вне репозитория, `~/.config/opencode/mcp-servers/`).
- Скил `gui-automation` (SKILL.md) в каталоге скилов прокопия + сценарии (сделай скриншот, кликни, заполни форму, прочитай окно).

## Capabilities

### New Capabilities

- `computer-use`: десктопная GUI-автоматизация — захват экрана/окон (som/vision/ax), клики и ввод по индексам элементов или координатам, скролл/драг, горячие клавиши, управление окнами и фокусом, работа в фоне без захвата курсора пользователя, мультимодальная доставка скриншотов модели.

### Modified Capabilities

<!-- Нет: существующие спеки ядра (tools, skills, loop) не меняют поведение. -->

## Impact

- `src/prokop/computer/` — новый пакет ядра (backend, capture, actions, schema, tool).
- `src/prokop/tools/toolsets.py` — новый набор `gui`.
- `src/prokop/tools/registry.py` — регистрация инструмента `computer_use`.
- Зависимости: `mss`, `pyautogui`, `pywinauto` (Windows UIA) или MCP-клиент cua-driver; всё опционально, инструмент доступен только при наличии бэкенда (`check_fn`).
- MCP-обёртка `prokop_mcp.py` (вне репо) — проброс `computer_use`.
- Документация: `docs/GUIDE.md`, `docs/PRODUCT_SPEC.md`.
