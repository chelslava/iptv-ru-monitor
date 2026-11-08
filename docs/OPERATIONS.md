# Эксплуатация

## Локальный запуск

```bash
uv sync --extra dev
uv run iptv-monitor pipeline --country RU    # полный цикл
uv run iptv-monitor discover                 # отдельные этапы
uv run iptv-monitor check --levels http,hls
uv run iptv-monitor build --country RU
```

Через Docker: `docker compose up --build monitor`.

## CI/CD (GitHub Actions)

| Workflow | Назначение | Запуск |
|----------|-----------|--------|
| `ci.yml` | Ruff, mypy, pytest | Push / Pull Request |
| `discover.yml` | Обновление каталога источников | Ежедневно + вручную |
| `check-global.yml` | Базовая проверка (HTTP+HLS) с GitHub-раннера | Каждые 6 часов + вручную |
| `check-ru.yml` | Проверка из российского VDS по SSH | Ежедневно + вручную |
| `build-playlists.yml` | Слияние результатов, скоринг, сборка dist/ | После проверок (по расписанию) |
| `publish-pages.yml` | Публикация dist/ на GitHub Pages | Ежедневно + вручную |

Scheduled workflow может запускаться с задержкой — точное время не
гарантируется. Все workflow самодостаточны (объновляют каталог перед
проверкой), артефакты: `checks-global`, `checks-ru`, `dist`.

Слияние истории: `build-playlists.yml` скачивает последние артефакты
обеих точек проверки и объединяет их в `data/state/checks.jsonl`;
`stream_id` детерминированы (sha256 URL), поэтому история совпадает
с актуальным каталогом.

## Российский VDS

Подготовка сервера, SSH-ключ CI с минимальными правами, firewall и
ограничения контейнера — [deploy/vds/README.md](../deploy/vds/README.md).

Секреты GitHub Actions: `VDS_HOST`, `VDS_USER`, `VDS_SSH_KEY`.
Без `VDS_HOST` workflow `check-ru.yml` завершается успешно с пометкой о
пропуске (не блокирует сборку).

## Ретенция истории

`config/app.yaml → retention`: 90 дней, максимум 200 записей на поток.
Применяется командой `iptv-monitor retention` (запускайте периодически
на VDS или в CI).

## Публикация

GitHub Pages публикует содержимое артефакта `dist` (workflow
`publish-pages.yml`). В настройках репозитория: Pages → Source →
GitHub Actions. Ручная альтернатива — `scripts/publish_artifacts.sh`
(ветка `gh-pages`).

## Мониторинг и диагностика

- `dist/ru/report.json` — причины включения/исключения каждого потока,
  топ ошибок, распределение точек наблюдения;
- логи проверок проходят редакцию секретов (`infrastructure/logging.py`);
- при смене формата источника адаптеры падают изолированно (`fetch_all`
  ловит исключения по источнику и пишет в лог).

## Известные ограничения MVP

- Free-TV и EPG/лого-источники выключены до проверки лицензий
  (`enabled: false`);
- слияние истории точек наблюдения — конкатенация артефактов без
  дедупликации прогонов;
- `ffprobe`/`playback` уровни не запускаются по расписанию (включайте
  вручную: `--levels http,hls,ffprobe`) — они медленные и нагружают VDS.
