# Контролируемый переход на PostParser production

Этот документ описывает только будущую процедуру. Команды не выполняются
автоматически. Новое приложение работает как strangler: интерфейс, VK и новые
`runs/results` обслуживает `postparser-prod`, а подтверждённые legacy-маршруты
проксируются на неизменённый `telegram-parser.service`.

## Границы и владение данными

- Код: `/opt/postparser-prod`.
- Пользователь и сервис: `postparser-prod`.
- Bind: `127.0.0.1:5052`; порт не публикуется наружу.
- Данные: `/var/lib/postparser-prod`.
- Настройки: `/var/lib/postparser-prod/settings.sqlite3`.
- Результаты: `/var/lib/postparser-prod/parse_results.sqlite3`.
- Логи: `/var/log/postparser-prod`.
- Конфигурация: `/etc/postparser-prod.env`.
- Legacy upstream: `http://127.0.0.1:5050`.

Нельзя копировать shadow-базы или `settings.groups`. Production начинает с
пустых SQLite-баз. Старые Telegram session, Instagram token и media остаются
доступны только старому процессу; новый процесс получает их результаты через
HTTP proxy и не имеет файлового доступа к ним.

## Подготовка файлов без запуска

Все команды ниже выполняются только после отдельного разрешения и после
фиксации одобренного commit hash.

```bash
TARGET_COMMIT='<approved-commit-hash>'

id postparser-prod >/dev/null 2>&1 || \
  useradd --system --home /nonexistent --shell /usr/sbin/nologin postparser-prod

install -d -o postparser-prod -g postparser-prod -m 0750 \
  /opt/postparser-prod /var/lib/postparser-prod
install -d -o postparser-prod -g postparser-prod -m 0750 \
  /var/log/postparser-prod

git clone --branch feature/production-migration-adapter --single-branch \
  https://github.com/romanyusupov/PostParserApp.git \
  /opt/postparser-prod
git -C /opt/postparser-prod checkout --detach "$TARGET_COMMIT"
test "$(git -C /opt/postparser-prod rev-parse HEAD)" = "$TARGET_COMMIT"

python3 -m venv /opt/postparser-prod/venv
/opt/postparser-prod/venv/bin/python -m pip install \
  -r /opt/postparser-prod/server/requirements.txt
/opt/postparser-prod/venv/bin/python -m pip check
chown -R postparser-prod:postparser-prod /opt/postparser-prod
```

## EnvironmentFile

Скопировать `deploy/postparser-prod.env.example` в
`/etc/postparser-prod.env`, заполнить только отдельно разрешённые интеграции и
не помещать файл в Git:

```bash
install -o root -g postparser-prod -m 0640 \
  /opt/postparser-prod/deploy/postparser-prod.env.example \
  /etc/postparser-prod.env
```

Обязательные несекретные значения:

```text
POSTPARSER_SERVICE_NAME=postparser-prod
POSTPARSER_DATA_DIR=/var/lib/postparser-prod
POSTPARSER_LEGACY_BASE_URL=http://127.0.0.1:5050
POSTPARSER_LEGACY_TIMEOUT_SECONDS=310
POSTPARSER_LEGACY_OWNED_NETWORKS=telegram,instagram
```

Секреты добавляются вручную только после отдельного решения. Не извлекать
hardcoded-значения из старого `telegram_api.py`. Не добавлять Telegram session
или Instagram token: эти интеграции остаются legacy-owned.

## Установка unit и предварительные проверки

Перед копированием unit согласовать `WorkingDirectory`, затем:

```bash
install -o root -g root -m 0644 \
  /opt/postparser-prod/deploy/postparser-prod.service \
  /etc/systemd/system/postparser-prod.service
systemctl daemon-reload
systemctl enable --now postparser-prod.service
```

Проверки нового контура не должны обращаться к внешним API:

```bash
systemctl is-active postparser-prod.service
curl -fsS http://127.0.0.1:5052/api/v1/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5052/shadow/settings
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5052/results
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5052/api/v1/runs
ss -ltnp | grep ':5052'
journalctl -u postparser-prod.service -n 100 --no-pager
```

Ожидаемый новый health:

```json
{"service":"postparser-prod","status":"ok"}
```

Legacy `/health` намеренно проверяет старый сервис через proxy. Если upstream
недоступен, legacy-маршруты возвращают безопасный `502/503`, но новый UI и
`/api/v1/health` продолжают работать. Автоматического доступа к общей session
или token нет.

## Проверка через SSH forwarding

До появления любого публичного Nginx-маршрута открыть туннель с Windows:

```powershell
ssh -i "C:\Users\rnyus\.ssh\postparser_vps_ed25519" `
  -o IdentitiesOnly=yes `
  -o BatchMode=yes `
  -N -L 5052:127.0.0.1:5052 root@222.167.211.198
```

После этого UI доступен локально по `http://127.0.0.1:5052`. Сначала создать
production-настройки групп вручную, затем проверить UI и каждый proxy-route.
Тесты сетей проводить по одному. Telegram/Instagram через новый
`/api/v1/parse` должны оставаться заблокированными; их legacy-маршруты должны
проходить через старый сервис. VK можно включить отдельно после установки
только его токена.

## Временный Nginx и основное переключение

Файл `deploy/nginx/postparser-prod.conf.example` предназначен для временного
проверочного URL. Он требует отдельно согласованных DNS и сертификата. До этого
использовать только SSH forwarding.

После полного контролируемого теста:

1. Сохранить копию действующего Nginx-конфига с датой и SHA-256.
2. Убедиться, что live `5050` и production `5052` отвечают.
3. Установить проверенный вариант
   `deploy/nginx/postparser-prod-main-switch.conf.example`.
4. Выполнить `nginx -t`.
5. Перезагрузить только Nginx configuration.
6. Проверить публичные `/health`, OAuth redirect, media и основные UI/API.
7. Не останавливать `telegram-parser.service`: proxy зависит от него.

Пример команд переключения после отдельного разрешения:

```bash
install -o root -g root -m 0644 \
  /etc/nginx/sites-enabled/tg-parser.conf \
  /root/tg-parser.conf.before-postparser-prod
sha256sum /root/tg-parser.conf.before-postparser-prod
install -o root -g root -m 0644 \
  /opt/postparser-prod/deploy/nginx/postparser-prod-main-switch.conf.example \
  /etc/nginx/sites-enabled/tg-parser.conf
nginx -t
systemctl reload nginx
```

## Немедленный rollback

Rollback Nginx не затрагивает данные нового сервиса и возвращает весь публичный
трафик на прежний `5050`:

```bash
install -o root -g root -m 0644 \
  /root/tg-parser.conf.before-postparser-prod \
  /etc/nginx/sites-enabled/tg-parser.conf
nginx -t
systemctl reload nginx
curl -fsS http://127.0.0.1:5050/health
systemctl is-active telegram-parser.service nginx
```

После восстановления трафика production можно остановить отдельно:

```bash
systemctl disable --now postparser-prod.service
```

Полное удаление выполняется только по отдельному разрешению и только после
архивации нужных production SQLite. Не удалять `/opt/telegram-parser`, его
session/token/media, shadow-каталог, live unit или Nginx backup.

## Основные риски

- `postparser-prod` зависит от доступности legacy `5050` для совместимых
  маршрутов; это намеренная зависимость до завершения миграции.
- Одновременное открытие Telegram session исключено отсутствием файлового
  доступа нового пользователя.
- SSRF ограничен server-side allowlist и loopback; клиент не выбирает upstream.
- Media проходит только через проверенный относительный proxy-путь с защитой
  от traversal, без ACL к старому каталогу.
- Синхронный legacy parse может работать долго; proxy и Gunicorn используют
  согласованный timeout 310/320 секунд.
- Порт `5052` должен оставаться привязанным только к loopback.
- Production и shadow SQLite нельзя объединять или копировать без отдельного
  плана миграции.
