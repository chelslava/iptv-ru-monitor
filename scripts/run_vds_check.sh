#!/usr/bin/env bash
# Проверка потоков из российского сегмента сети.
# Запускается НА VDS (по SSH из GitHub Actions, см. .github/workflows/check-ru.yml,
# и инструкции в deploy/vds/README.md).
#
# Переменные окружения:
#   IPTV_REPO_DIR  — путь к репозиторию на VDS (по умолчанию /opt/iptv-ru-monitor)
#   IPTV_LEVELS    — уровни проверки (по умолчанию http,hls)

set -euo pipefail

REPO_DIR="${IPTV_REPO_DIR:-/opt/iptv-ru-monitor}"
LEVELS="${IPTV_LEVELS:-http,hls}"
RESULT_FILE="$REPO_DIR/deploy/vds/data/state/checks-ru.jsonl"

cd "$REPO_DIR"

echo "==> Обновление репозитория"
git pull --ff-only

echo "==> Проверка из РФ (уровни: $LEVELS)"
# Результат пишется в отдельный файл (IPTV_JSONL_PATH), чтобы каждая
# итерация передавала в сборку только свежие результаты.
rm -f "$RESULT_FILE"
docker compose -f deploy/vds/docker-compose.yml run --rm checker \
  discover
docker compose -f deploy/vds/docker-compose.yml run --rm checker \
  check --levels "$LEVELS" --country RU

echo "==> Результаты: $RESULT_FILE"
