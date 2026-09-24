# Сборка лендинга prokop из ветки site: dist/ не лежит в git и не переносится руками.
# Разворачивает локальная сторона. Запуск:
#   docker build --build-arg SITE_REF=site -t prokopii-site:latest .
#   docker build --build-arg SITE_REF=<тег-или-ветка> -t prokopii-site:latest .

FROM node:24-alpine AS build
RUN apk add --no-cache git

# Ревизия выкатки: ветка или тег. По умолчанию — ветка site.
# git clone --branch принимает ветку или тег; для точного коммита нужен тег на его ревизии.
ARG SITE_REF=site
RUN git clone --depth 1 --branch "$SITE_REF" https://github.com/yaugust939/prokop /src

WORKDIR /src/site
# Сборщик берёт число тестов из tools/test-count.json: в образе node нет python,
# живой прогон pytest остаётся локальному запуску.
RUN node tools/build-dist.mjs

FROM nginx:1.27-alpine
RUN apk add --no-cache tzdata && cp /usr/share/zoneinfo/Europe/Moscow /etc/localtime
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/site/dist/ /usr/share/nginx/html/
EXPOSE 80
HEALTHCHECK CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
