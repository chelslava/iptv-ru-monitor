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

- `stream_id`, `checked_at` (UTC), `probe_location` (`github-runner`,
  `ru-vds`, `local`, ...), `country_code`;
- уровень 1: `http_status`, `dns_ok`, `tls_ok`, `startup_time_ms`;
- уровень 2: `playlist_ok`, `first_segment_ok`;
- уровень 3: `video_codec`, `audio_codec`, `width`, `height`, `fps`,
  `bitrate_bps`, `duration_checked_seconds`;
- `error_code` / `error_message` (секреты отредактированы), `check_version`.

Успешной считается проверка без `error_code` (`is_success`). Один успешный
HTTP-ответ не доказывает стабильность — рейтинг строится по истории.

## EPG-сопоставление (`data/state/epg_matches.json`)

Сохраняются исходный ID/название, выбранный `tvg_id`, способ сопоставления
(`tvg_id` / `alias` / `normalized_name` / `manual`), уверенность, источник и
признак ручного подтверждения. Нечёткое совпадение не перезаписывает ручное.

## Файлы состояния (`data/state/`)

| Файл | Содержимое |
|------|-----------|
| `channels.json` / `streams.json` | Нормализованный каталог после discovery |
| `checks.jsonl` / `history.sqlite` | История проверок |
| `scores.json` | Рейтинги потоков |
| `epg_matches.json`, `epg_programmes.json` | Результаты enrichment |
| `approved_streams.yaml` | Подтверждённые к публикации stream_id (для источников с `public_policy: review`) |

## Классификация ошибок

`ssrf_blocked`, `unsupported_scheme`, `redirect_limit`, `dns_error`,
`tls_error`, `http_4xx`, `http_5xx`, `transport_error`, `timeout`,
`hls_invalid`, `hls_variant_unavailable`, `segment_error`,
`ffprobe_unavailable`, `ffprobe_timeout`, `ffprobe_error`,
`playback_error`, `unknown`.
