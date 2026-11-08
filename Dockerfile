# Образ для проверок (GitHub Actions runner, российский VDS, локальный запуск).
# Версия FFmpeg зафиксирована базовым образом python:3.12-slim-bookworm
# (пакет ffmpeg из Debian bookworm). При обновлении базового образа
# проверяйте совместимость через `iptv-monitor check --levels ffprobe`.

FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 iptv

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN pip install --no-cache-dir .

USER iptv

ENV IPTV_PROBE_LOCATION=ru-vds \
    IPTV_DATA_DIR=/app/data \
    IPTV_DIST_DIR=/app/dist

ENTRYPOINT ["iptv-monitor"]
