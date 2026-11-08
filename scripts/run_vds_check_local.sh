#!/usr/bin/env bash
# Локальная эмуляция проверки с российского VDS — без Docker и сервера.
#
# Воспроизводит сценарий scripts/run_vds_check.sh: те же метки точки
# наблюдения (probe_location=ru-vds) и тот же файл результатов, но этапы
# выполняются через uv на этой машине. Используется для отладки пайплайна
# до развёртывания реального VDS.
#
# Переменные окружения:
#   IPTV_LEVELS — уровни проверки (по умолчанию http,hls)
#   IPTV_LIMIT  — сколько потоков проверять (по умолчанию 5)
#   IPTV_SKIP_DISCOVER=1 — не обновлять каталог (быстрый повторный прогон)

set -euo pipefail
cd "$(dirname "$0")/.."

LEVELS="${IPTV_LEVELS:-http,hls}"
LIMIT="${IPTV_LIMIT:-5}"
RESULT="deploy/vds/data/state/checks-ru.jsonl"

export IPTV_PROBE_LOCATION=ru-vds
export IPTV_JSONL_PATH="$RESULT"

mkdir -p "$(dirname "$RESULT")"
rm -f "$RESULT"

echo "==> [ru-vds] Обновление каталога"
if [[ "${IPTV_SKIP_DISCOVER:-0}" != "1" ]]; then
    # probe_location берётся из IPTV_PROBE_LOCATION (экспортирована выше)
    uv run iptv-monitor discover
fi

echo "==> [ru-vds] Проверка потоков (уровни: $LEVELS, лимит: $LIMIT)"
uv run iptv-monitor check \
    --levels "$LEVELS" \
    --limit "$LIMIT" \
    --probe-location ru-vds \
    --country RU

echo "==> Результаты: $RESULT"
echo
echo "Подключение к сборке (эмуляция артефакта check-ru):"
echo "  cat $RESULT >> data/state/checks.jsonl"
echo "  uv run iptv-monitor score && uv run iptv-monitor build --country RU"
