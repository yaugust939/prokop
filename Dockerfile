# Чистая установка prokop из опубликованного GitHub-репозитория.
# Сборка ставит пакет с нуля и прогоняет тесты как проверку установки.
FROM python:3.13-slim

# git нужен для клонирования источника
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/prokop

# Свежий клон публичного репозитория (неглубокий, ветка main)
RUN git clone --depth 1 https://github.com/yaugust939/prokop.git .

# Чистая установка: пакет + зависимости для тестов
RUN pip install --no-cache-dir -e src \
    && pip install --no-cache-dir pytest

# Проверка установки: полный прогон тестов
RUN python -m pytest src/tests -q

# По умолчанию — сообщить установленную версию
CMD ["python", "-c", "import prokop; print('prokop', prokop.__version__)"]
