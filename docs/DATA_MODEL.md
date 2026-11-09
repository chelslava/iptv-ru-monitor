# Модель данных

Канал хранится отдельно от конкретных потоков: один канал может иметь
несколько URL, зеркал и вариантов качества. JSON-схемы — в `data/schemas/`.

## Channel (`data/state/channels.json`, `dist/*/channels.json`)

| Поле | Назначение |
|------|------------|
| `channel_id` | Внутренний стабильный ID (`<страна>-<слаг>`, детерминирован) |
| `name` | Каноническое название |
| `alt_names` | Альтернативные названия (после дедупликации) |
| `country` | ISO 3166-1 alpha-2 |
| `languages` | Языки вещания |
| `category` | Категория (`general/news/kids/sports/...`) |
| `tvg_id` | Идентификатор EPG/XMLTV |
| `logo_url` | URL логотипа |
| `is_public` | Допуск к публичной сборке |
| `metadata_source` | Происхождение метаданных (source_id) |

## Stream (`data/state/streams.json`, `dist/*/streams.json`)

| Поле | Назначение |
|------|------------|
| `stream_id` | Внутренний ID (16 hex sha256 URL) |
| `channel_id` | Связанный канал |
| `url` | Адрес потока (http/https) |
| `protocol` | `hls` / `http` / `dash` / `unknown` |
| `source_id` | Источник URL (source-first) |
| `declared_quality` | Заявленное качество |
| `enabled` | Участвует ли в проверках |
| `publication_status` | `pending` / `allowed` / `rejected` |

**Секретные URL и адреса с временными токенами нельзя сохранять в публичном
каталоге или логах** — такие URL отклоняются политикой публикации
(`filtering/publication_policy.py`), а в логах маскируются
(`infrastructure/logging.py`).

## CheckResult (`data/state/checks.jsonl`, SQLite, артефакты CI)

Одна запись — одна проверка одного потока из одной точки наблюдения.

- `stream_id`, `checked_at` (UTC), `probe_location`, `country_code`;
- уровень 1: `http_status`, `dns_ok`, `tls_ok`, `startup_time_ms`;
- уровень 2: `playlist_ok`, `first_segment_ok`;
- уровень 3: `video_codec`, `audio_codec`, `width`, `height`, `fps`,
  `bitrate_bps`, `duration_checked_seconds`;
- DVR/catchup (issue #10, при `check.dvr_probe=true`): `dvr`,
  `dvr_hours` — подтверждённая глубина архива Flussonic;
- `error_code` / `error_message` (секреты отредактированы), `check_version`.

Успешной считается проверка без `error_code` (`is_success`). Один успешный
HTTP-ответ не доказывает стабильность — рейтинг строится по истории.

### Точки наблюдения (`probe_location`)

| Метка | Кто проверяет | Каденс | Транспорт результатов |
|-------|---------------|--------|----------------------|
| `github-runner` | CI (check-global) | каждые 6 ч | артефакт `checks-global` (30 дней) |
| `ru-vds` | VDS по SSH (check-ru) | ежедневно | артефакт `checks-ru` (30 дней); без секретов — пропуск |
| `home-ru` | домашний ПК (ночной прогон) | ежедневно ночью | файлы `checks-home-ru-<штамп>.jsonl` в ветке `probe/ru` (последние 30) |

`probe/ru` — транспортная ветка-шина: домашний ПК публикует JSONL-файлы
коммитами (`scripts/ru_probe_push.sh`, guard 8 ч + `IPTV_FORCE=1`),
CI забирает их при сборке (`scripts/merge_history.sh`). Ветка не влияет
на main и служит только переносом данных.

Кандидаты на подтверждение требуют успеха минимум из **двух** точек
(`config/quality_profiles.yaml -> approval.min_probe_locations`), поэтому
`home-ru` — обязательный участник воронки публикаций.

## EPG-сопоставление (`data/state/epg_matches.json`)

Сохраняются исходный ID/название, выбранный `tvg_id`, способ сопоставления,
уверенность, источник и признак ручного подтверждения. Нечёткое совпадение
не перезаписывает ручное. Способы (в порядке приоритета):

| Метод | Как работает |
|-------|--------------|
| `tvg_id` | точное совпадение id канала с id EPG-источника |
| `alias` | ручной алиас из `config/countries/*.yaml` (только если его tvg_id есть в активном EPG) |
| `normalized_name` | нормализованное имя канала = display-name EPG |
| `bridge` | id формата iptv-org раскрыт через iptv-org/database (Unlicense) в каноническое имя + `alt_names` (вкл. русские), затем как имя (issue #5) |

## Жизненный цикл потока (issue #8)

По истории проверок от самой свежей до первого успеха считается счётчик
провалов подряд (`history/lifecycle.py`):

| Провалов подряд | Состояние | Эффект |
|---|---|---|
| < `stale_consecutive_failures` (4) | живой | публикуется |
| ≥ 4 | `stale` | публикуется, помечается в `report.json` |
| ≥ `deny_consecutive_failures` (8) | `auto-denied` | исключается из плейлиста (approved-запись не удаляется) |

Пороги считаются в сутках: с ротацией каталога (issue #16) каждый поток
проверяется ~раз в сутки (раньше — 4 раза в сутки, пороги были 6/12 ≈
1.5/3 суток).

Один успех сбрасывает счётчик — поток реанимируется автоматически.

## Файлы состояния (`data/state/`)

| Файл | Содержимое |
|------|-----------|
| `channels.json` / `streams.json` | Нормализованный каталог после discovery |
| `checks.jsonl` / `history.sqlite` | История проверок (окно = `retention.history_days`, 30 дней) |
| `scores.json` | Рейтинги потоков |
| `epg_matches.json`, `epg_programmes.json` | Результаты enrichment |
| `candidates.json` | Кандидаты на подтверждение последнего прогона (`iptv-monitor candidates`) |
| `approved_streams.yaml` | Подтверждённые stream_id для источников с `public_policy: review`. **Единственный state-файл, который трекается в git**: он переносит решения человека из PR кандидатов в CI-сборку |

### candidates.json

Результат `iptv-monitor candidates --country RU` (workflow approve-candidates,
ежедневно в 09:30 UTC): список потоков, заблокированных ТОЛЬКО причиной
review, с score ≥ 75, ≥ 6 проверками, успехом из ≥ 2 точек и полученным
HLS-сегментом. `--apply` дописывает `stream_ids` в `approved_streams.yaml`;
изменение коммитится в ветку `chore/approval-candidates` и открывается
автоматическим PR — **merge PR = подтверждение** (техническое состояние +
чек-лист прав источника из docs/SOURCE_POLICY.md).

## Классификация ошибок

`ssrf_blocked`, `unsupported_scheme`, `redirect_limit`, `dns_error`,
`tls_error`, `http_4xx`, `http_5xx`, `transport_error`, `timeout`,
`hls_invalid`, `hls_variant_unavailable`, `segment_error`,
`ffprobe_unavailable`, `ffprobe_timeout`, `ffprobe_error`,
`playback_error`, `unknown`.
