# Сборка лендинга prokop из ветки site: dist/ не лежит в git и не переносится руками.
# Разворачивает локальная сторона. Запуск:
#   SITE_REV=$(git ls-remote https://github.com/yaugust939/prokop refs/heads/site | cut -f1) \
#     docker compose up -d --build
#   docker build --build-arg SITE_REV=<коммит> -t prokopii-site:latest .

FROM node:24-alpine AS build
RUN apk add --no-cache git

# Ревизия выкатки. SITE_REV обязателен, и вот почему.
# Docker кэширует слой по тексту инструкции, а результат сетевой операции в ключ
# кэша не входит: без меняющегося аргумента пересборка молча берёт клон из кэша и
# везёт в образ старый код. На это уже наступили — вторая сборка «прошла» со старым
# сборщиком. Плюс пиннит выкатку на конкретный коммит, а не на движущуюся ветку.
ARG SITE_REF=site
ARG SITE_REV

RUN test -n "$SITE_REV" || { echo "SITE_REV не задан: укажите коммит, иначе слой клона возьмётся из кэша" >&2; exit 1; }

# Клон полный, а не --depth 1: так выкатка возможна на любой коммит, не только на вершину ветки.
RUN git clone --branch "$SITE_REF" https://github.com/yaugust939/prokop /src \
 && git -C /src checkout --detach "$SITE_REV" \
 && test "$(git -C /src rev-parse HEAD)" = "$SITE_REV" \
 || { echo "SITE_REV=$SITE_REV не совпал с выкачанным коммитом" >&2; exit 1; }

WORKDIR /src/site
# Сборщик берёт число тестов из tools/test-count.json: в образе node нет python,
# живой прогон pytest остаётся локальному запуску. Эта ветка обязана работать —
# см. пункт 8 приёмки в 00_ТЗ.md.
RUN node tools/build-dist.mjs

FROM nginx:1.27-alpine
RUN apk add --no-cache tzdata && cp /usr/share/zoneinfo/Europe/Moscow /etc/localtime
# Сниппет заголовков безопасности: подключается в каждом location со своим Cache-Control.
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/site/dist/ /usr/share/nginx/html/
EXPOSE 80
LABEL org.opencontainers.image.title="prokop — лендинг prokopii.ru" \
      org.opencontainers.image.description="Статический лендинг ядра агента prokop (Python, MIT)" \
      org.opencontainers.image.source="https://github.com/yaugust939/prokop" \
      org.opencontainers.image.licenses="MIT"
HEALTHCHECK CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
