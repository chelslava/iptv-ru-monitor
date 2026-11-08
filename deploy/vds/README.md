# Российский VDS: подготовка и безопасность

Проверяющий контейнер запускается на VDS и помечает результаты
`probe_location=ru-vds`. Запуск выполняется из GitHub Actions по SSH
(workflow `check-ru.yml`) — self-hosted runner не обязателен.

## 0. Локальная проверка без VDS

Отладить сценарий РФ-проверки можно на своей машине — с Docker или без него.

**Без Docker** (нативно через uv, те же метки и файл результатов):

```bash
bash scripts/run_vds_check_local.sh                    # http,hls, 5 потоков
IPTV_LIMIT=20 IPTV_LEVELS=http,hls,ffprobe \
    bash scripts/run_vds_check_local.sh                # шире и глубже
```

**С Docker** (полный контур как на сервере, из корня репозитория):

```bash
mkdir -p deploy/vds/data/state
docker compose -f deploy/vds/docker-compose.yml build
docker compose -f deploy/vds/docker-compose.yml run --rm checker \
    discover --probe-location ru-vds
docker compose -f deploy/vds/docker-compose.yml run --rm checker \
    check --levels http,hls --limit 5 --probe-location ru-vds --country RU
```

Результат обоих вариантов: `deploy/vds/data/state/checks-ru.jsonl`.
Подключение к сборке (эмуляция артефакта workflow `check-ru`):

```bash
cat deploy/vds/data/state/checks-ru.jsonl >> data/state/checks.jsonl
uv run iptv-monitor score && uv run iptv-monitor build --country RU
# report.json -> summary.probe_locations должно показать обе точки
```

> [!NOTE]
> Локальная эмуляция помечает результаты `ru-vds`, но выполняется с вашего
> компьютера: если вы не в РФ, география проверок не соответствует метке.
> Для боевых данных используйте реальный VDS.


## 1. Подготовка сервера

```bash
# ОС: любой актуальный Debian/Ubuntu.
adduser --disabled-password --gecos "" iptv-ci
apt-get update && apt-get install -y docker.io docker-compose-plugin git ufw

# Репозиторий (deploy key с правом чтения):
mkdir -p /opt/iptv-ru-monitor
chown iptv-ci:iptv-ci /opt/iptv-ru-monitor
sudo -u iptv-ci git clone git@github.com:<owner>/iptv-ru-monitor.git /opt/iptv-ru-monitor
```

## 2. Firewall

```bash
ufw default deny incoming
ufw allow OpenSSH
ufw enable
```

## 3. SSH-ключ для CI

На локальной машине (ключ используется ТОЛЬКО для этого сервера):

```bash
ssh-keygen -t ed25519 -f vds_ci_key -C "iptv-ci-github-actions"
ssh-copy-id -i vds_ci_key.pub iptv-ci@<VDS_HOST>
```

Ограничьте ключ на сервере (в `~iptv-ci/.ssh/authorized_keys`):

```
restrict,command="bash /opt/iptv-ru-monitor/scripts/run_vds_check.sh" ssh-ed25519 AAAA... iptv-ci-github-actions
```

Так CI не сможет выполнять произвольные команды. Секреты положите в GitHub
Actions Secrets: `VDS_HOST`, `VDS_USER` (`iptv-ci`), `VDS_SSH_KEY`
(закрытый ключ).

## 4. Регламент безопасности

- Отдельный пользователь без root; Docker через членство в группе `docker`
  или запуск `docker compose` через sudo с whitelist.
- Ротация ключей — не реже раза в квартал (`ssh-keygen -R` + новые секреты).
- Ограничения контейнера: `cpus: 1.0`, `mem_limit: 512m`, `pids_limit`,
  `cap_drop: ALL`, `read_only` ФС (см. docker-compose.yml).
- Запрет выполнения команд, полученных из данных источников: скрипт
  запускает фиксированный набор команд, переменные не проходят в shell.
- SSRF-защита в коде: обращения к localhost/приватным диапазонам запрещены
  (src/iptv_monitor/infrastructure/http_client.py).
- Токены и приватные URL редактируются в логах (infrastructure/logging.py).

## 5. Запуск вручную

```bash
cd /opt/iptv-ru-monitor
bash scripts/run_vds_check.sh
# результаты: deploy/vds/data/state/checks-ru.jsonl
```
