# Вендоренные статики статус-страницы

Публикуются в `dist/assets/` на этапе `build` (см. `_publish_static_assets`
в `cli.py`); страницы стран подключают их как `../assets/<file>`.

| Файл | Что это | Версия | Лицензия |
|---|---|---|---|
| `hls.light.min.js` | [hls.js](https://github.com/video-dev/hls.js), light-сборка (без EME/DRM, субтитров и альтернативных аудиодорожек) | 1.7.4 | Apache-2.0 |
| `player.js` | Наш минимальный плеер-слой: модалка, выбор лучшего потока по score, авто-failover | — | MIT (как проект) |

## Почему вендорим, а не CDN

Аудитория проекта — Россия; jsdelivr периодически недоступен у части
российских провайдеров. Статус-страница должна играть без внешних
зависимостей в момент воспроизведения. hls.js лениво загружается с первого
клика ▶, поэтому вес страницы не меняется.

## Обновление hls.js

```bash
curl -sL -o src/iptv_monitor/generators/static/hls.light.min.js \
  "https://cdn.jsdelivr.net/npm/hls.js@<версия>/dist/hls.light.min.js"
```

После обновления: поправить версию в таблице выше, прогнать
`uv run pytest tests/unit/test_generators.py` и smoke-тест плеера.
