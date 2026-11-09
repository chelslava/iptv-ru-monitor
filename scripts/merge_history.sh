#!/usr/bin/env bash
# Слияние истории проверок в data/state/checks.jsonl.
# Источники: ветка history/global (постоянная история github-runner, issue #16),
# артефакт check-ru (последний прогон VDS) и файлы ветки probe/ru
# (домашняя RU-точка). Пока ветка history/global не создана, используется
# fallback на артефакты check-global последних 5 прогонов (старое поведение,
# ~30 часов глубины).
# Используется build-playlists.yml и approve-candidates.yml.
# Требует: выполненный checkout, GITHUB_REPOSITORY, GH_TOKEN.

set -euo pipefail

: "${GITHUB_REPOSITORY:?нужен GITHUB_REPOSITORY}"
: "${GH_TOKEN:?нужен GH_TOKEN}"

mkdir -p data/state artifacts/global artifacts/ru probe/ru history/global

echo "==> Ветка history/global (постоянная история github-runner, issue #16)"
BRANCH_RUN_IDS=""
if git fetch origin "+refs/heads/history/global:refs/remotes/origin/history/global" 2>/dev/null; then
  git ls-tree --name-only refs/remotes/origin/history/global \
    | grep -E '^checks-global-[0-9]{8}-[0-9]{4}(-r[0-9]+)?\.jsonl\.gz$' \
    | while read -r f; do
        git show "refs/remotes/origin/history/global:$f" | gzip -d > "history/global/${f%.gz}"
      done
  echo "    файлов: $(ls -1 history/global | wc -l)"
  # Прогоны, уже живущие в ветке (суффикс -r<run_id>): их артефакты ниже
  # пропускаются, чтобы не задваивать одни и те же проверки.
  BRANCH_RUN_IDS=$(git ls-tree --name-only refs/remotes/origin/history/global \
    | grep -oE '\-r[0-9]+\.jsonl\.gz$' | grep -oE '[0-9]+' | sort -u || true)
else
  echo "    ветка не найдена — только артефакты check-global (последние 5 прогонов)"
fi

echo "==> Артефакты check-global (последние 5 прогонов, кроме уже слитых из ветки)"
for run_id in $(gh run list -R "$GITHUB_REPOSITORY" --workflow check-global.yml \
    --status success --limit 5 --json databaseId -q '.[].databaseId'); do
  if echo "$BRANCH_RUN_IDS" | grep -qx "$run_id"; then
    echo "    run $run_id уже в ветке — пропуск"
    continue
  fi
  art_id=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$run_id/artifacts" \
    --jq '.artifacts[] | select(.name=="checks-global") | .id' | head -1)
  [[ -z "$art_id" ]] && continue
  curl -sL -H "Authorization: Bearer $GH_TOKEN" \
    "https://api.github.com/repos/$GITHUB_REPOSITORY/actions/artifacts/$art_id/zip" \
    -o /tmp/global.zip
  # Файл в каждом артефакте один и тот же — свой подкаталог на прогон.
  unzip -o -j /tmp/global.zip -d "artifacts/global/$run_id"
done
echo "    файлов: $(find artifacts/global -name '*.jsonl' | wc -l)"

echo "==> Артефакт check-ru (последний успешный прогон)"
ru_id=$(gh run list -R "$GITHUB_REPOSITORY" --workflow check-ru.yml \
  --status success --limit 1 --json databaseId -q '.[0].databaseId' || echo "")
if [[ -n "$ru_id" ]]; then
  art_id=$(gh api "repos/$GITHUB_REPOSITORY/actions/runs/$ru_id/artifacts" \
    --jq '.artifacts[] | select(.name=="checks-ru") | .id' | head -1)
  if [[ -n "$art_id" ]]; then
    curl -sL -H "Authorization: Bearer $GH_TOKEN" \
      "https://api.github.com/repos/$GITHUB_REPOSITORY/actions/artifacts/$art_id/zip" \
      -o /tmp/ru.zip
    unzip -o -j /tmp/ru.zip -d artifacts/ru || true
  fi
fi

echo "==> Ветка probe/ru (домашняя RU-точка)"
if git fetch origin "+refs/heads/probe/ru:refs/remotes/origin/probe/ru" 2>/dev/null; then
  git ls-tree --name-only refs/remotes/origin/probe/ru \
    | grep -E '^checks-home-ru-[0-9T:-]+\.jsonl$' \
    | while read -r f; do git show "refs/remotes/origin/probe/ru:$f" >> "probe/ru/$f"; done
  echo "    файлов: $(ls -1 probe/ru | wc -l)"
else
  echo "    ветка не найдена — пропущено"
fi

echo "==> Слияние"
: > data/state/checks.jsonl
if compgen -G 'history/global/*.jsonl' > /dev/null; then
  cat history/global/*.jsonl >> data/state/checks.jsonl
fi
if compgen -G 'artifacts/global/*/*.jsonl' > /dev/null; then
  cat artifacts/global/*/*.jsonl >> data/state/checks.jsonl
fi
if compgen -G 'artifacts/ru/*.jsonl' > /dev/null; then
  cat artifacts/ru/*.jsonl >> data/state/checks.jsonl
fi
if compgen -G 'probe/ru/*.jsonl' > /dev/null; then
  cat probe/ru/*.jsonl >> data/state/checks.jsonl
fi
echo "    записей: $(wc -l < data/state/checks.jsonl)"
