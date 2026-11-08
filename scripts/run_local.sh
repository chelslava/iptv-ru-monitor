#!/usr/bin/env bash
# Локальный прогон полного цикла мониторинга.
# Использование: scripts/run_local.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Установка зависимостей"
uv sync --extra dev

echo "==> Полный цикл: discover -> check -> enrich -> score -> build"
uv run iptv-monitor pipeline --country RU

echo "==> Готово. Артефакты: dist/"
