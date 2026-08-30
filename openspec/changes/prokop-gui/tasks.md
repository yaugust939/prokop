## 1. Скаффолд пакета computer/

- [x] 1.1 Создать пакет `src/prokop/computer/` с модулями: `schema.py`, `backend.py`, `windows.py`, `cua.py`, `capture.py`, `tool.py`, `__init__.py`
- [x] 1.2 Добавить опциональные зависимости в `src/pyproject.toml`: `mss`, `pyautogui`, `pywinauto` (extra `gui`, без верхнего порога для pre-1.0 или с порогом `<next_major` для >=1.0)

## 2. Схема и контракты

- [x] 2.1 Реализовать `schema.py`: OpenAI function-calling схема `computer_use` с `action`-дискриминатором (capture/click/double_click/right_click/middle_click/drag/scroll/type/key/set_value/wait/list_apps/list_windows/focus_app) и параметрами (mode, app, pid, window_id, max_elements, element, coordinate, button, modifiers, text, keys, value, direction, amount, seconds, delivery_mode, raise_window, capture_after)
- [x] 2.2 Реализовать модели результата в `backend.py`: `ActionResult`, `CaptureResult`, `UIElement`, абстрактный `ComputerUseBackend` с методами capture/click/type/key/set_value/scroll/list_apps/list_windows/focus_app/wait
- [x] 2.3 Реализовать `capture.py`: обработка захвата (PNG, масштабирование, SOM-оверлеи, AX-дерево с max_elements, total_elements/truncated_elements, текстовая сводка + base64 для `_multimodal`)

## 3. Бэкенды

- [x] 3.1 Реализовать локальный Windows-бэкенд `windows.py`: mss-скриншоты, pyautogui (move/click/type/key/scroll), pywinauto UIA (дерево элементов, сом-разметка, set_value для select/slider, list_windows/focus_app)
- [x] 3.2 Реализовать бэкенд `cua.py`: MCP-клиент over stdio к `cua-driver` (health-проверка, capture/actions в фоновом режиме без кражи курсора, foreground как явный режим)
- [x] 3.3 Реализовать выбор бэкенда через `check_fn` и конфиг (приоритет: cua-driver при наличии, иначе локальный Windows при наличии зависимостей)

## 4. Инструмент и регистрация

- [x] 4.1 Реализовать `tool.py`: регистрация `computer_use` в реестре (schema, handler, check_fn, result_limit, мультимодальная обёртка `_multimodal` для захватов)
- [x] 4.2 Добавить набор `gui` в `tools/toolsets.py` (includes core, tools=[computer_use])
- [x] 4.3 Реализовать диспетчеризацию действий и обработку ошибок бэкенда (неизвестное действие, недоступный бэкенд, timeout)

## 5. Тесты

- [x] 5.1 Написать unit-тесты `src/tests/test_computer_schema.py`: схема, валидация action, required, enum
- [x] 5.2 Написать unit-тесты `src/tests/test_computer_tool.py` на мок-бэкенде: dispatcher (все действия), мультимодальная обёртка для capture, JSON-результат для list_apps/list_windows, ошибки
- [x] 5.3 Написать тест `src/tests/test_computer_toolsets.py`: набор `gui` разрешается, `check_fn` скрывает инструмент при отсутствии бэкенда
- [x] 5.4 Написать тест сценариев спеки (WHEN/THEN): захват som/vision/ax, таргетинг по элементу/координатам, max_elements, capture_after, delivery_mode background/foreground

## 6. MCP-проброс и интеграция

- [x] 6.1 Добавить инструмент `computer_use` в MCP-обёртку `~/.config/opencode/mcp-servers/prokop_mcp.py` (schema + dispatch, exec в фоновом потоке)
- [x] 6.2 Согласовать разрешения в `~/.config/opencode/opencode.json`: `computer_use` (capture — allow, действия — ask), проверка в переключателе агентов

## 7. Скилы и документация

- [x] 7.1 Создать скил `gui-automation` (SKILL.md: когда использовать, процедуры — скриншот → клик → ввод → проверка, pitfalls, verification) в каталоге скилов прокопия
- [x] 7.2 Обновить `docs/GUIDE.md` (раздел computer_use), `docs/PRODUCT_SPEC.md` (новая возможность), `CHANGELOG.md`
- [x] 7.3 Живая проверка на Windows: запуск прокопия, захват экрана, клик по элементу, ввод текста (смоук-чеклист)

## 8. DoD

- [x] 8.1 Полный прогон тестов прокопия (`python -m pytest tests -q` в src) — зелёный, без регрессий
- [x] 8.2 Проверка `openspec validate change prokop-gui` — валидно
- [x] 8.3 Сводка в трекер hermes: что сделано, как включать инструмент
