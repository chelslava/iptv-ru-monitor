#!/usr/bin/env bash
# Ночная проверка с домашнего ПК — постоянная RU-точка наблюдения (home-ru).
#
# Что делает:
#   1) обновляет репозиторий и каталог источников;
#   2) проверяет потоки (по умолчанию http,hls, первые IPTV_LIMIT штук)
#      с честной меткой probe_location=home-ru;
#   3) публикует результаты отдельным файлом в ветку probe/ru
#      (build-playlists.yml забирает их оттуда и сливает в общую историю).
#
# Запуск вручную:
#   bash scripts/ru_probe_push.sh
#   IPTV_LIMIT=30 IPTV_LEVELS=http,hls,ffprobe bash scripts/ru_probe_push.sh
#
# Расписание (Windows Task Scheduler): scripts/ru_probe_task.cmd, ежедневно 03:40.

set -euo pipefail
cd "$(dirname "$0")/.."

# uv может стоять в пользовательском каталоге
export PATH="$HOME/.local/bin:$PATH"

LEVELS="${IPTV_LEVELS:-http,hls}"
LIMIT="${IPTV_LIMIT:-50}"
BRANCH="${PROBE_BRANCH:-probe/ru}"
LABEL="${IPTV_PROBE_LABEL:-home-ru}"
STAMP="$(date -u +%Y%m%d-%H%M)"
RESULT="deploy/vds/data/state/checks-${LABEL}.jsonl"

export IPTV_PROBE_LOCATION="$LABEL"
export IPTV_JSONL_PATH="$RESULT"

echo "==> [$LABEL] Обновление репозитория и каталога"
git pull --ff-only
mkdir -p "$(dirname "$RESULT")"
rm -f "$RESULT"

uv run iptv-monitor discover
echo "==> [$LABEL] Проверка потоков (уровни: $LEVELS, лимит: $LIMIT)"
uv run iptv-monitor check \
    --levels "$LEVELS" \
    --limit "$LIMIT" \
    --probe-location "$LABEL" \
    --country RU

if [[ ! -s "$RESULT" ]]; then
    echo "Пустой результат проверки — пуш пропущен" >&2
    exit 1
fi
COUNT=$(wc -l < "$RESULT")

echo "==> [$LABEL] Публикация $COUNT результатов в ветку $BRANCH"
WORKTREE="$(mktemp -d)"
cleanup() {
    git worktree remove --force "$WORKTREE" 2>/dev/null || true
    git worktree prune
}
trap cleanup EXIT

git fetch origin
if git show-ref --verify --quiet "refs/remotes/origin/$BRANCH"; then
    git worktree add -B "$BRANCH" "$WORKTREE" "origin/$BRANCH" 1>&2
else
    git worktree add --orphan -b "$BRANCH" "$WORKTREE" 1>&2
fi

cp "$RESULT" "$WORKTREE/checks-${LABEL}-${STAMP}.jsonl"
# Ретенция ветки: храним последние 30 файлов результатов.
(
    cd "$WORKTREE"
    ls -1t "checks-${LABEL}-"*.jsonl 2>/dev/null | tail -n +31 | xargs -r rm -f
    git add -A
    git -c user.name="$(git config user.name)" \
        -c user.email="$(git config user.email)" \
        commit -m "probe(${LABEL}): $(date -u +%Y-%m-%d\ %H:%M) — ${COUNT} results" 1>&2
    git push origin "$BRANCH" 1>&2
)

echo "==> Готово: $BRANCH/checks-${LABEL}-${STAMP}.jsonl"
