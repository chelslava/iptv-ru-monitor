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

## Домашний ПК как RU-точка (home-ru)

Постоянная точка наблюдения без VDS — ночной прогон с домашнего компьютера
(резидентный RU IP, метка `home-ru`):

- `scripts/ru_probe_push.sh` — обновляет каталог, проверяет потоки
  (`IPTV_LIMIT`, по умолчанию 300; `IPTV_LEVELS`, по умолчанию `http,hls`)
  и публикует результаты в ветку `probe/ru` (хранятся последние 30 файлов).
- `scripts/ru_probe_task.cmd` — обёртка для планировщика Windows;
  задача «iptv-ru-monitor home-ru probe» ежедневно в 03:40 по местному времени.
- `build-playlists.yml` забирает файлы из `probe/ru` и сливает их в общую
  историю вместе с артефактами `checks-global`/`checks-ru`.

Регистрация задачи (однократно, из Git Bash):

```bash
MSYS_NO_PATHCONV=1 schtasks /Create /F /SC DAILY /ST 03:40 \
  /TN "iptv-ru-monitor home-ru probe" \
  /TR "D:\Repo\iptv-ru-monitor\scripts\ru_probe_task.cmd"
```

Лог: `data/state/home-ru-task.log`. Особенности запуска (проверено
2026-11-09 на ноутбуке):

- задача пересоздана с `AllowStartIfOnBatteries` — флаг «не запускать от
  батареи» навсегда ставил её в очередь (ноутбук на батарее = всегда
  «от батареи»);
- `StartWhenAvailable` — пропущенный по выключению ПК прогон стартует
  при включении;
- докат при входе в систему: ярлык в автозагрузке пользователя
  (`shell:startup\iptv-ru-monitor home-ru.lnk`) — без прав администратора;
- защита от дублей: скрипт пропускает прогон, если предыдущий был менее
  8 часов назад (обход — `IPTV_FORCE=1`);
- опционально (нужен админ, один раз): перевести задачу в S4U-режим,
  чтобы работала без активного входа:

  ```powershell
  $t = Get-ScheduledTask -TaskName 'iptv-ru-monitor home-ru probe'
  $t.Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
  $t.Settings.WakeToRun = $true
  Set-ScheduledTask -InputObject $t
  ```

Ручной прогон:

```bash
bash scripts/ru_probe_push.sh                 # 50 потоков, http,hls
IPTV_LIMIT=500 IPTV_LEVELS=http,hls,ffprobe bash scripts/ru_probe_push.sh
```

## Ретенция истории

`config/app.yaml → retention`: 90 дней, максимум 200 записей на поток.
Применяется командой `iptv-monitor retention` (запускайте периодически
на VDS или в CI).

## Автоматические PR кандидатов

Workflow `approve-candidates` создаёт PR автоматически. Разрешение включено
через API (2026-11-09; эквивалент галочки Settings → Actions → General →
Workflow permissions → «Allow GitHub Actions to create and approve pull
requests»):

```bash
gh api -X PUT repos/<owner>/<repo>/actions/permissions/workflow   -F default_workflow_permissions=read -F can_approve_pull_request_reviews=true
```

Если разрешение снова отключено, workflow сам откатывается на issue с
compare-ссылкой (см. approve-candidates.yml). Ограничение GitHub: PR,
созданные GITHUB_TOKEN, не запускают CI на самих себя — для data-only PR
(approved_streams.yaml) это не мешает merge и последующей сборке.

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
