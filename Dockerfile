# Чистая установка prokop из текущего рабочего дерева.
# Сборка ставит пакет с нуля и прогоняет тесты как проверку установки.
FROM python:3.13-slim

WORKDIR /opt/prokop

# Только исходники пакета. Лишнее отсекает .dockerignore
# (reference/, .git/, .github/, src/.env, кэши).
COPY src ./src

# Чистая установка: пакет + зависимости для тестов
RUN pip install --no-cache-dir -e src \
    && pip install --no-cache-dir pytest

# Проверка установки: полный прогон тестов
RUN python -m pytest src/tests -q

# По умолчанию — сообщить установленную версию
CMD ["python", "-c", "import prokop; print('prokop', prokop.__version__)"]
