# Шрифты лендинга prokop — лицензии и происхождение

Все четыре гарнитуры — SIL OFL 1.1, кириллица у всех. Файлы локальные, внешних CDN
на странице нет. Тексты лицензий лежат рядом с шрифтами и попадают в `dist/fonts/`.

Имена файлов заданы `design/tokens.css` и не переименовываются.

## Акциденция

### Fedorovsk — `fedorovsk-cyrillic.woff2`, `fedorovsk-latin.woff2`

| | |
|---|---|
| Гарнитура | Fedorovsk / Fedorovsk Unicode |
| Авторы | Nikita Simmons (2007); редакция Aleksandr Andreev и Nikita Simmons |
| Проект | github.com/slavonic/Fedorovsk (проект гарнитуры), github.com/slavonic/node-church-slavonic-fonts (пакет `church-slavonic-fonts`) |
| Лицензия | SIL OFL 1.1 — файл `OFL-Fedorovsk.txt` |
| Исходник | `fonts/otf/Fedorovsk-Regular.otf` (123 848 байт) из проекта гарнитуры |
| Преобразование | `pyftsubset` (fontTools 4.66 + brotli) по `unicode-range` из `tokens.css` → woff2 |

**Двойная лицензия.** У пакета Slavonic Computing Initiative (`church-slavonic-fonts`,
npm-имя; в ТЗ он назван `fonts-churchslavonic`) гарнитуры двойные: **GPLv3 или SIL OFL 1.1**.
Взят **OFL**. У самого проекта гарнитуры лицензия одиночная — OFL 1.1, без GPL-ветки;
текст оттуда и приложен. Проверка покрытия: акциденция покрывает все символы заголовков
`h1`–`h3` страницы (53 различных символа) — см. `01_ОТЧЁТ.md`, раздел о шрифтах.

## Модульный слой

### Handjet — `handjet-cyrillic.woff2`, `handjet-cyrillic-ext.woff2`, `handjet-latin.woff2`

| | |
|---|---|
| Гарнитура | Handjet Regular, вариативная (ось `wght` 100–900) |
| Автор | The Handjet Project Authors, Rosetta Type |
| Проект | github.com/rosettatype/Handjet |
| Лицензия | SIL OFL 1.1 — файл `OFL-Handjet.txt` |
| Источник | jsDelivr Fontsource: `handjet:vf@latest` (подмножества cyrillic, cyrillic-ext, latin) |

Оси `ELGR`/`ELSH` из описания дизайн-системы в отдаваемом файле отсутствуют — в нём
только `wght`. Расхождение зафиксировано в отчёте.

## Текст

### Golos Text — `golos-text-cyrillic-400.woff2`, `golos-text-cyrillic-600.woff2`, `golos-text-latin-400.woff2`, `golos-text-latin-600.woff2`

| | |
|---|---|
| Гарнитура | Golos Text Regular (400), SemiBold (600) |
| Автор | The Golos Text Project Authors |
| Проект | github.com/googlefonts/golos-text |
| Лицензия | SIL OFL 1.1 — файл `OFL-GolosText.txt` |
| Источник | jsDelivr Fontsource: `golos-text@latest` (подмножества cyrillic, latin) |

## Код

### JetBrains Mono — `jetbrains-mono-cyrillic-400.woff2`, `jetbrains-mono-cyrillic-700.woff2`, `jetbrains-mono-latin-400.woff2`, `jetbrains-mono-latin-700.woff2`

| | |
|---|---|
| Гарнитура | JetBrains Mono Regular (400), Bold (700) |
| Автор | The JetBrains Mono Project Authors |
| Проект | github.com/JetBrains/JetBrainsMono |
| Лицензия | SIL OFL 1.1 — файл `OFL-JetBrainsMono.txt` |
| Источник | jsDelivr Fontsource: `jetbrains-mono@latest` (подмножества cyrillic, latin) |

## Проверка загрузок

Все 11 файлов с jsDelivr отданы с HTTP 200 и ненулевым размером, сигнатура — `wOF2`
(hex `77 4F 46 32`). Акциденция получена конвертацией OTF → woff2 локально.
Подробности и размеры — в `01_ОТЧЁТ.md`.
