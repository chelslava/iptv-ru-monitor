<div align="center">

# 📺 iptv-ru-monitor

**Автоматизированный мониторинг публичных IPTV-потоков и каталог каналов для Android TV / TiviMate**

🇷🇺 Первая страна — Россия · Другие страны добавляются конфигурацией, без правки кода

[![CI](https://github.com/chelslava/iptv-ru-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/chelslava/iptv-ru-monitor/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)
![mypy](https://img.shields.io/badge/mypy-checked-2a6db2.svg)
![pytest](https://img.shields.io/badge/pytest-passing-0a9edc.svg)
![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)

</div>

---

> [!WARNING]
> **Что это НЕ.** Проект — инструмент мониторинга и каталогизации, а не поставщик
> телевизионных услуг. Он не обходит DRM, авторизацию, платные подписки или
> геоблокировки и не предназначен для поиска и распространения нелегальных копий
> платных каналов. Успешный HTTP-ответ не считается доказательством
> воспроизводимости. Источники с неясными правами не включаются в публичные
> сборки до проверки — см. [docs/SOURCE_POLICY.md](docs/SOURCE_POLICY.md);
> merge PR с кандидатами фиксирует выполнение правового чек-листа.

> [!NOTE]
> Количество каналов — не показатель качества. Приоритет у проверяемости,
> стабильности, корректного EPG и допустимости источника.

## 🌐 Мониторинг онлайн

Мониторинг публикуется на GitHub Pages и доступен из браузера без авторизации:

| Что | Ссылка |
|---|---|
| 🏠 **Главная (все страны)** | [chelslava.github.io/iptv-ru-monitor](https://chelslava.github.io/iptv-ru-monitor/) |
| 🇷🇺 **Статус-страница России** — поиск и фильтр по каталогу | [/ru/index.html](https://chelslava.github.io/iptv-ru-monitor/ru/index.html) |
| 🇺🇿 Узбекистан | [/uz/index.html](https://chelslava.github.io/iptv-ru-monitor/uz/index.html) |

На статус-странице: **поиск канала по имени**, фильтр по категории, статус
потока (`excellent`/`good`/`unstable`/`failed`), score и uptime за 30 дней —
можно проверить, работает ли канал, ещё до добавления плейлиста. Рядом —
счётчики каталога, покрытие EPG, точки наблюдения и их свежесть.

Страница обновляется автоматически: каждая успешная проверка (4 раза в
сутки) запускает сборку и публикацию — сцепка workflow-ов, не крон.

Плейлисты и машиночитаемые данные (см. [Данные/API](#-данныеapi)) лежат рядом,
например основной плейлист:
[ru/russia.m3u](https://chelslava.github.io/iptv-ru-monitor/ru/russia.m3u).

## ✨ Возможности

| | |
|---|---|
| 🔎 **Discovery** | Сбор каналов из открытых источников: IPTV-org, Free-TV/IPTV, ngrch, IPTVMIR и любые M3U-списки (адаптер `remote_m3u`) |
| 🧹 **Normalization** | Канонические названия, категории; страна по `tvg-id`/названию (UK→GB и др. алиасы), а не наследуется от источника; канал отделён от потока; URL-дедуп нормализует регистр/порт/порядок query |
| 🔬 **Многоуровневые проверки** | HTTP/DNS/TLS → HLS (master/media playlist, выбор варианта по bandwidth, sniffing первого сегмента) → FFprobe → ограниченное декодирование; транзиентные ошибки повторяются |
| 🌍 **Географический контекст** | Результаты маркируются точкой наблюдения: `github-runner`, `home-ru`, `ru-vds` — доступность из РФ не смешивается с зарубежной |
| 🔄 **Ротация каталога** | github-runner проверяет ¼ каталога за 6ч-слот (весь каталог раз в сутки); история накапливается постоянно в ветке `history/global` — настоящие uptime 7д/30д вместо rolling-окна 30ч |
| 📈 **Скоринг по истории** | Взвешенное среднее по компонентам с данными; уровням `excellent`/`good`/`unstable`/`failed`; новым потокам — `insufficient_data` |
| 📺 **EPG и логотипы** | Сопоставление XMLTV: `tvg-id` → алиасы (скоупятся страной) → нормализованное имя → мост iptv-org/database → нечёткое совпадение (rapidfuzz, неоднозначные не применяются); ручные подтверждения не перезаписываются |
| 🕹 **UA-fallback** | Потоки, отвечающие 401/403/444 плеерному User-Agent, перепроверяются с браузерным (~15% «мёртвых» так оживают); в M3U добавляются `#EXTVLCOPT`/`#KODIPROP` |
| 🤖 **Автокандидаты** | Приоритетная очередь проверок (`--order approval`): второй точкой наблюдения первыми проверяются потоки, готовые стать кандидатами; PR с кандидатами группируется по источникам с чек-листом прав |
| 🛡 **Безопасная публикация** | Секретные URL и токены (включая `username` Xtream) не попадают в артефакты и логи; SSRF-защита с pin-IP (DNS-rebinding закрыт); записи атомарны; публикация — через подтверждение (PR с кандидатами) |
| 🌐 **Статус-страница** | Поиск и фильтр по каталогу каналов, статус/score/uptime каждого потока — [см. Мониторинг онлайн](#-мониторинг-онлайн) |
| 📦 **Артефакты** | M3U для TiviMate, XMLTV, JSON-каталоги, per-profile отчёты с причинами включения/исключения |

## 🚀 Быстрый старт

Требуется [uv](https://docs.astral.sh/uv/) (или Python 3.12+):

```bash
uv sync --extra dev          # окружение и зависимости
uv run iptv-monitor --help   # список команд
uv run iptv-monitor pipeline --country RU   # полный цикл
```

Отдельные этапы:

```bash
uv run iptv-monitor discover                    # сбор и нормализация источников
uv run iptv-monitor check --levels http,hls     # проверка потоков
uv run iptv-monitor check --rotate-offset 1 --rotate-parts 4   # срез каталога (CI-режим)
uv run iptv-monitor check --order approval      # готовые к кандидату — первыми
uv run iptv-monitor enrich                      # EPG и логотипы
uv run iptv-monitor score                       # рейтинг по истории
uv run iptv-monitor build --country RU          # генерация dist/
```

<details>
<summary>🐳 Через Docker</summary>

```bash
docker compose up --build monitor        # полный цикл
docker compose run --rm monitor check    # отдельный этап
```
</details>

<details>
<summary>🖥 Российская точка наблюдения с домашнего ПК (без VDS)</summary>

Разовый прогон сценария VDS (метка `ru-vds`, отдельный файл результатов):

```bash
bash scripts/run_vds_check_local.sh     # уровни http,hls, 5 потоков
IPTV_LIMIT=20 IPTV_LEVELS=http,hls,ffprobe bash scripts/run_vds_check_local.sh
```

Постоянная RU-точка — ночной прогон с резидентного IP (метка `home-ru`,
~300 потоков с ротацией по каталогу — полный круг за ~30 ночей, публикация
результатов в ветку `probe/ru`):

```bash
bash scripts/ru_probe_push.sh           # вручную; либо по расписанию
IPTV_LIMIT=500 IPTV_ROTATE_PARTS=15 bash scripts/ru_probe_push.sh
```

Результаты подключаются к сборке так же, как артефакт реального VDS.
Подробнее: [deploy/vds/README.md](deploy/vds/README.md).
</details>

## 📊 Как это работает

```mermaid
flowchart TD
    SRC["🔎 Источники IPTV<br/>iptv-org · Free-TV · ngrch · IPTVMIR · custom"] --> DISC["Discovery<br/>разбор M3U"]
    DISC --> NORM["🧹 Normalization<br/>каналы · потоки · страны · категории · дедупликация"]
    NORM --> GH["🐙 GitHub Actions<br/>github-runner: ¼ каталога за 6ч-слот"]
    NORM --> VDS["🇷🇺 Российская точка<br/>домашний ПК: home-ru, ротация + priority-очередь"]
    GH --> HIST["🗂 history/global<br/>постоянная история 30 дней"]
    GH --> RES["🔬 Check Results"]
    VDS --> PRB["🗂 probe/ru"]
    HIST --> RES
    PRB --> RES
    RES --> ENR["📺 Enrichment<br/>EPG (fuzzy) · логотипы · алиасы"]
    ENR --> SCORE["📈 Quality Scoring<br/>рейтинг по истории"]
    SCORE --> GEN["📦 Generators<br/>M3U · XMLTV · JSON · HTML"]
    GEN --> PAGES["🚀 GitHub Pages<br/>плейлисты · статус-страница · API"]
    GEN --> APPR["🤖 approve-candidates<br/>PR с кандидатами по источникам"]
```

История проверок хранится в двух git-ветках — `history/global` (постоянная
история github-runner, файл за прогон, ретенция 30 дней) и `probe/ru`
(ночные прогоны домашней RU-точки). Сборка сливает обе + артефакт `check-ru`
через `scripts/merge_history.sh` и обрезает по `retention` — поэтому
`uptime_30d` в отчёте настоящие 30 дней, а не последние часы.

<details>
<summary>Уровни проверки потоков</summary>

| Уровень | Что проверяется | Зачем |
|---|---|---|
| **1. HTTP** | DNS, TCP, TLS, коды ответа, редиректы, размер | Быстро отсеять мёртвые URL |
| **2. HLS** | Master/media playlist, варианты качества, первый сегмент | URL отвечает ≠ поток играет |
| **3. Медиа** | FFprobe: кодеки, разрешение, FPS, битрейт | Параметры качества и профили отбора |
| **4. Повторяемость** | Повторные проверки с интервалом, точка наблюдения | Один успех не доказывает стабильность |

</details>

<details>
<summary>Рейтинг качества (стартовая гипотеза)</summary>

| Компонент | Вес |
|---|---|
| Доступность при повторных проверках | 35 % |
| Устойчивость получения сегментов | 30 % |
| Время запуска | 15 % |
| Медиапараметры | 15 % |
| Корректность HLS | 5 % |

Уровни: `90–100 excellent` · `75–89 good` · `50–74 unstable` · `0–49 failed`.
Меньше `min_checks` проверок → `insufficient_data` (в плейлисты не попадает).
Балл — взвешенное среднее по компонентам с данными (ffprobe выключен не
занижает балл); без контентных доказательств (только HTTP) — максимум
`unstable` (issue #21).
Калибровка — [docs/QUALITY_SCORING.md](docs/QUALITY_SCORING.md).
</details>

## ⚙️ Конфигурация

| Файл | Назначение |
|---|---|
| [`config/app.yaml`](config/app.yaml) | Тайм-ауты, параллелизм, хранилище, ретенция, жизненный цикл, UA-fallback, порог EPG-fuzzy |
| [`config/sources.yaml`](config/sources.yaml) | Источники и политика публикации (`allow` / `review` / `deny`) |
| [`config/countries/ru.yaml`](config/countries/ru.yaml) | Профиль страны: плейлисты, EPG-алиасы, номера каналов |
| [`config/quality_profiles.yaml`](config/quality_profiles.yaml) | Веса рейтинга, профили отбора и критерии автокандидатов (`approval`) |
| [`config/epg_sources.yaml`](config/epg_sources.yaml) | Источники XMLTV |
| [`config/logo_sources.yaml`](config/logo_sources.yaml) | Источники логотипов |
| [`.env.example`](.env.example) | Переопределения окружением (`IPTV_*`) |

Новая страна = новый файл `config/countries/<код>.yaml` — логика стран не
зашита в код.

## 📦 Артефакты

```
dist/
├── index.html            # hub: ссылки на каталоги всех стран
└── ru/                   # аналогично uz/ и другие страны
    ├── index.html        # статус-страница: поиск и фильтр по каталогу
    ├── russia.m3u        # основной плейлист (TiviMate и др.)
    ├── russia-hd.m3u     # ≥ 720p
    ├── russia-kids.m3u   # детские
    ├── russia-sport.m3u  # спортивные
    ├── russia.xml        # XMLTV EPG (согласованные tvg-id)
    ├── channels.json     # нормализованный каталог каналов
    ├── streams.json      # публичные сведения о потоках (без секретов)
    ├── stats.json        # сводные счётчики и время последней проверки точек
    ├── report.json       # отчёт основного профиля: причины вкл/искл + uptime
    └── report-ru_hd.json # per-profile отчёты (ru_kids, ru_sport — аналогично)
```

`dist/` генерируется автоматически и вручную не редактируется.

## 🔌 Данные/API

Все артефакты — машиночитаемый JSON, доступен без авторизации:

| Файл | Содержимое |
|---|---|
| [`stats.json`](https://chelslava.github.io/iptv-ru-monitor/ru/stats.json) | счётчики каталога/плейлиста, покрытие EPG, автодeny, последнее время проверки каждой точки наблюдения |
| [`report.json`](https://chelslava.github.io/iptv-ru-monitor/ru/report.json) | по каждому потоку: score, уровень, причины исключения, uptime 7д/30д, провалы подряд (per-profile: `report-ru_hd.json` и др.) |
| [`channels.json`](https://chelslava.github.io/iptv-ru-monitor/ru/channels.json) | каталог каналов (имена, tvg-id, логотипы, категории, страна) |
| [`streams.json`](https://chelslava.github.io/iptv-ru-monitor/ru/streams.json) | потоки и решения публикации (URL — только без секретов, флаг `ua_required`) |

## 📺 Подключение в TiviMate (Android TV)

1. Дождитесь публикации артефактов (workflow `publish-pages.yml`).
2. TiviMate → *Настройки → Плейлисты → Добавить плейлист → URL*:
   `https://<аккаунт>.github.io/iptv-ru-monitor/ru/russia.m3u`
3. Источник EPG: `.../ru/russia.xml` (генерируется из epg.pw и iptvx.one, см.
   `config/epg_sources.yaml`).
4. Тематические подборки: `russia-hd.m3u`, `russia-kids.m3u`, `russia-sport.m3u`.

Локально: соберите плейлист командой `uv run iptv-monitor build` и укажите
в TiviMate файл `dist/ru/russia.m3u`.

<details>
<summary>Потоки, требующие браузерный User-Agent</summary>

Часть источников отдаёт контент только браузерному UA — такие потоки
перепроверяются автоматически (`ua_fallback`) и помечаются в `streams.json`
(`ua_required: true`); в M3U для VLC/Kodi добавляются `#EXTVLCOPT`/`#KODIPROP`.
TiviMate задаёт User-Agent **на весь плейлист** (по-канальному не умеет):

*Настройки → Плейлисты → (плейлист) → User-Agent* — укажите браузерный UA,
например `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,
like Gecko) Chrome/126.0.0.0 Safari/537.36`.

Проверить статус конкретного канала — через
[поиск по каталогу](https://chelslava.github.io/iptv-ru-monitor/ru/index.html).
</details>

## 🧪 Тестирование и качество

```bash
uv run pytest            # unit + integration, без обращения к сети
uv run ruff check .      # линтер
uv run mypy              # типизация
```

Интеграционный тест прогоняет весь конвейер на мок-транспорте: discovery →
проверки → скоринг → сборка, включая проверку исключения секретных URL.

## 🗺️ Roadmap

Базовые этапы (0–6) выполнены: конвейер, проверки, RU-точка, EPG, рейтинг,
публикация, вторая страна. Дальше — волны улучшений
(подробный учёт — [issue #4](https://github.com/chelslava/iptv-ru-monitor/issues/4)):

- [x] **Волна 1** (#5–#15) — EPG-мост, дедуп плейлиста, `tvg-chno`, жизненный
  цикл, статус-страница v2, DVR-детекция, уведомления, второй профиль страны
- [x] **Волна 2** (#16–#26) — постоянная история + ротация каталога,
  priority-очередь home-ru, UA-fallback, атомарные записи, нормализация
  скоринга, EPG-fuzzy, SSRF pin-IP, redaction, техдолг
- [ ] **Волна 3** — приоритетная очередь approval (`--order approval`) и поиск
  по каталогу на статус-странице — сделано; контроль качества `max_per_run`
  17.11; backlog: catchup не-Flussonic, per-stream history API

## 📚 Документация

| Документ | Содержание |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Полная архитектура проекта |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Модель данных и файлы состояния |
| [docs/QUALITY_SCORING.md](docs/QUALITY_SCORING.md) | Формулы рейтинга и калибровка |
| [docs/SOURCE_POLICY.md](docs/SOURCE_POLICY.md) | Реестр источников и правила публикации |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Локальный запуск, CI/CD, VDS, ретенция |

## 🤝 Участие и безопасность

- [CONTRIBUTING.md](CONTRIBUTING.md) — как предложить изменения.
- [SECURITY.md](SECURITY.md) — модель угроз и как сообщить об уязвимости.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — правила поведения.

## 📄 Лицензия

Код распространяется по лицензии [MIT](LICENSE). Лицензия проекта **не
распространяется** автоматически на потоки, EPG, логотипы и сторонние каталоги.

**Благодарности:** [iptv-org/iptv](https://github.com/iptv-org/iptv) и
[Free-TV/IPTV](https://github.com/free-tv/iptv) — открытые каталоги, используемые
как источники данных (в рамках их условий).

---

<div align="center">
<sub>Сделано для сообщества · Мониторинг вместо обещаний: каждый поток в плейлисте проверен</sub>
</div>
