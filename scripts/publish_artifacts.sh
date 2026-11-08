#!/usr/bin/env bash
# Публикация собранных артефактов (dist/) на GitHub Pages.
# Основной путь — workflow .github/workflows/publish-pages.yml; этот скрипт
# используется для ручной публикации из локальной сборки.
# Использование: GH_TOKEN=... scripts/publish_artifacts.sh

set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d dist ]]; then
  echo "dist/ не найден: сначала выполните 'iptv-monitor build'" >&2
  exit 1
fi

if [[ -z "${GH_TOKEN:-}" ]]; then
  echo "Установите GH_TOKEN с правом записи в репозиторий" >&2
  exit 1
fi

BRANCH="${PAGES_BRANCH:-gh-pages}"
echo "==> Публикация dist/ в ветку $BRANCH"

WORKTREE="$(mktemp -d)"
git worktree add "$WORKTREE" --orphan "$BRANCH" 2>/dev/null || git worktree add "$WORKTREE" "$BRANCH"
rsync -a --delete --exclude '.git' dist/ "$WORKTREE/"
(
  cd "$WORKTREE"
  git add -A
  git -c user.name="iptv-ru-monitor bot" -c user.email="bot@users.noreply.github.com" \
    commit -m "publish: $(date -u +%Y-%m-%dT%H:%M:%SZ)" || echo "нет изменений"
  git push origin "$BRANCH" --force-with-lease
)
git worktree remove --force "$WORKTREE"

echo "==> Готово. Настройте GitHub Pages на ветку $BRANCH (root), если ещё не настроено."
