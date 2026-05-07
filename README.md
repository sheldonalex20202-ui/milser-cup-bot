# Telegram Community Logger MVP

MVP-сервис принимает Telegram webhook updates, выбирает только входящие пользовательские сообщения из comments к постам канала и direct messages, сохраняет их в SQLite как pending-события и досылает строки в Google Sheets.

## Стек и архитектура

- FastAPI: быстрый webhook endpoint и healthcheck.
- Pydantic Settings: конфигурация только через env.
- SQLite: дедупликация `update_id`, `chat_id + message_id`, локальная очередь pending writes и маппинг discussion thread -> channel post.
- Google Sheets API: append строк через service account.
- Tenacity: retry/backoff для append в Sheets.

Pipeline:

1. `POST /telegram/webhook` получает Update.
2. Проверяется `X-Telegram-Bot-Api-Secret-Token`.
3. Parser извлекает `message`, игнорирует service/edited/bot/admin/sender_chat events.
4. Parser определяет `comment` или `direct`.
5. Сообщение нормализуется в общую модель.
6. Событие сохраняется в SQLite как `pending`.
7. Background task пытается append в Google Sheets.
8. При успехе событие помечается `synced`; при ошибке остается `failed` и будет повторено.

## Структура проекта

```text
app/
  api/
    dependencies.py
    routes.py
  core/
    config.py
    logging.py
  models/
    domain.py
  services/
    ingest.py
  sheets/
    client.py
    rows.py
  storage/
    sqlite.py
  telegram/
    content.py
    parser.py
  main.py
migrations/
  001_init.sql
tests/
Dockerfile
docker-compose.yml
requirements.txt
.env.example
```

## Google Sheets schema

Сервис создает вкладку `Messages`, если ее нет, и выставляет заголовки:

| Column | Name |
| --- | --- |
| A | ingested_at_utc |
| B | source_type |
| C | telegram_update_id |
| D | telegram_chat_id |
| E | telegram_message_id |
| F | telegram_message_thread_id |
| G | telegram_direct_messages_topic_id |
| H | channel_chat_id |
| I | discussion_group_chat_id |
| J | channel_post_id |
| K | user_id |
| L | username |
| M | first_name |
| N | last_name |
| O | message_date_utc |
| P | content_type |
| Q | text |
| R | caption |
| S | media_json |
| T | raw_message_json |
| U | raw_update_json |
| V | dedup_key |
| W | schema_version |

## Telegram setup

### 1. Создать бота и получить token

1. Откройте `@BotFather`.
2. Выполните `/newbot`.
3. Сохраните token в `TELEGRAM_BOT_TOKEN`.
4. Узнайте id бота через `getMe` и укажите в `TELEGRAM_BOT_USER_ID`, чтобы явно отфильтровать сообщения самого бота.

### 2. Настроить канал и discussion group

1. Создайте Telegram channel.
2. Создайте group/supergroup для обсуждений.
3. В настройках канала привяжите discussion group.
4. Добавьте бота в discussion group.
5. Выдайте боту право читать сообщения. В privacy mode у BotFather лучше выполнить `/setprivacy` -> `Disable`, иначе бот может не видеть все group messages.
6. Получите id канала и группы, например временно отправив тестовый webhook/update в сервис или через `getUpdates` до установки webhook.
7. Заполните `TELEGRAM_CHANNEL_CHAT_ID` и `TELEGRAM_DISCUSSION_GROUP_CHAT_ID`.

### 3. Проверить comments

1. Опубликуйте пост в канале.
2. Откройте комментарии к посту и отправьте сообщение от обычного пользователя.
3. В логах должен появиться `normalized message created` с `source_type=comment`.
4. В Google Sheets должна появиться строка.

Практическая эвристика comments:

- chat id сообщения должен совпадать с `TELEGRAM_DISCUSSION_GROUP_CHAT_ID`;
- sender должен быть реальным пользователем, без `sender_chat`;
- сообщение должно иметь text/caption/media;
- если в update есть `forward_origin` channel, `is_automatic_forward`, `reply_to_message` с channel origin или `external_reply.chat.type=channel`, сервис записывает маппинг `message_thread_id -> channel_post_id`;
- пользовательский comment принимается, если его `message_thread_id` найден в локальном маппинге;
- опционально `TELEGRAM_ACCEPT_UNMAPPED_DISCUSSION_THREADS=true` разрешает принимать любой thread в discussion group как comment, но это менее строго и может логировать обычный флуд в группе.

Ограничение: если бот не видел root automatic-forward сообщения обсуждения и Telegram не прислал `external_reply`/`reply_to_message` с каналом, строгий режим не сможет надежно связать thread с постом.

### 4. Проверить direct messages

Bot API поддерживает `Message.direct_messages_topic` для direct messages chats. Сервис считает direct message, если:

- у `message` есть `direct_messages_topic.topic_id`; или
- `message.chat.type == "private"`.

Чтобы проверить:

1. Включите доступные direct messages для канала/сообщества в текущем интерфейсе Telegram, если эта функция доступна вашему аккаунту/каналу.
2. Добавьте/настройте бота так, чтобы он получал эти сообщения.
3. Отправьте DM от обычного пользователя.
4. Проверьте `source_type=direct` и `telegram_direct_messages_topic_id` в Sheets.

Ограничение: Telegram постепенно меняет режимы channel direct messages. Если Bot API не доставляет такие updates вашему боту, сервис не сможет их получить без изменения конфигурации Telegram.

## Google service account

1. В Google Cloud Console создайте project.
2. Включите Google Sheets API.
3. Создайте Service Account.
4. Создайте JSON key.
5. Положите файл, например, в `secrets/google-service-account.json`.
6. Создайте Google Spreadsheet.
7. Нажмите Share и добавьте email service account с правами Editor.
8. Скопируйте spreadsheet id из URL и укажите в `GOOGLE_SPREADSHEET_ID`.

## Локальный запуск

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Для публичного webhook локально используйте tunnel, например ngrok/cloudflared.

Установить webhook:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://your-public-host.example.com/telegram/webhook" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET_TOKEN}" \
  -d "allowed_updates=[\"message\"]"
```

Проверить webhook:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Healthcheck:

```bash
curl http://localhost:8000/health
```

Ручной retry pending rows:

```bash
curl -X POST http://localhost:8000/internal/sync-pending \
  -H "X-Telegram-Bot-Api-Secret-Token: $TELEGRAM_WEBHOOK_SECRET_TOKEN"
```

## Direct broadcast

Internal UI for direct-message broadcasts from the community:

```text
/internal/broadcast/direct/ui
```

The UI resolves usernames through the Google Sheets `Messages*` tabs, using
`telegram_chat_id` and `telegram_direct_messages_topic_id`, then sends through
Telegram Bot API direct message topics. Run `Preview` first, review successful
and unsuccessful recipients, then start the broadcast.

In production the webhook secret is not embedded into the HTML page. Enter
`TELEGRAM_WEBHOOK_SECRET_TOKEN` manually.

## Docker

```bash
cp .env.example .env
mkdir -p data secrets
docker compose up --build -d
```

На сервере поставьте reverse proxy с HTTPS. Telegram webhook требует публичный HTTPS URL.

## Deploy на Render Web Service

Проект готов к Render через `render.yaml` и Docker runtime.

Важные Render-нюансы:

- Web service должен слушать порт из env `PORT`; Dockerfile уже запускает `uvicorn` с `${PORT:-8000}`.
- Render filesystem по умолчанию ephemeral, поэтому SQLite должен лежать на persistent disk.
- `render.yaml` монтирует disk в `/app/data` и задает `SQLITE_PATH=/app/data/app.db`.
- Persistent disk доступен только на paid web service. В `render.yaml` указан `plan: starter`.
- Сервис с persistent disk нельзя масштабировать на несколько instances; для MVP это нормально, потому что SQLite локальный.

### 1. Создать GitHub repo

```bash
git init
git add .
git commit -m "Initial Telegram community logger MVP"
git branch -M main
git remote add origin https://github.com/<owner>/<repo>.git
git push -u origin main
```

Не коммитьте `.env`, `data/` и `secrets/`; они уже добавлены в `.gitignore` и `.dockerignore`.

### 2. Создать Render Blueprint

1. Откройте Render Dashboard.
2. New -> Blueprint.
3. Подключите GitHub repository.
4. Render найдет `render.yaml`.
5. Во время создания заполните env vars с `sync: false`.

Нужно заполнить:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_BOT_USER_ID
TELEGRAM_CHANNEL_CHAT_ID
TELEGRAM_DISCUSSION_GROUP_CHAT_ID
TELEGRAM_SUPPORT_ADMIN_USER_IDS
GOOGLE_SPREADSHEET_ID
GOOGLE_CREDENTIALS_JSON
```

`TELEGRAM_WEBHOOK_SECRET_TOKEN` Render сгенерирует сам через `generateValue: true`. После первого deploy откройте Environment в Render и скопируйте значение, оно понадобится для `setWebhook`.

### 3. Google credentials на Render

Для Render удобнее использовать `GOOGLE_CREDENTIALS_JSON`:

1. Откройте JSON key service account.
2. Скопируйте весь JSON в одну env var `GOOGLE_CREDENTIALS_JSON`.
3. Убедитесь, что Google Sheet расшарен на `client_email` из JSON с ролью Editor.

Локальный режим через `GOOGLE_CREDENTIALS_PATH` тоже поддерживается.

### 4. Установить Telegram webhook на Render URL

После успешного deploy Render даст URL вида:

```text
https://telegram-community-logger.onrender.com
```

Установите webhook:

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://telegram-community-logger.onrender.com/telegram/webhook" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET_TOKEN}" \
  -d "allowed_updates=[\"message\"]"
```

Проверьте:

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
curl "https://telegram-community-logger.onrender.com/health"
```

### 5. Проверить pending retry на Render

```bash
curl -X POST "https://telegram-community-logger.onrender.com/internal/sync-pending" \
  -H "X-Telegram-Bot-Api-Secret-Token: ${TELEGRAM_WEBHOOK_SECRET_TOKEN}"
```

### 6. Если deploy не стартует

Чаще всего причина одна из этих:

- `GOOGLE_CREDENTIALS_JSON` пустой или вставлен невалидный JSON.
- Google Sheet не расшарен на service account.
- Не заполнен `GOOGLE_SPREADSHEET_ID`.
- Persistent disk не создан, или `SQLITE_PATH` не указывает на `/app/data/app.db`.
- Telegram webhook secret в `setWebhook` не совпадает с Render env var.

## Тесты

```bash
pytest
```

Покрыты:

- direct message detection;
- comment detection via stored thread mapping;
- ignore обычного сообщения в discussion group без thread mapping;
- content type/media extraction;
- SQLite дедупликация по update/message.

## Edge cases и решения MVP

- Empty `text`, но есть `caption`: логируется.
- Media без текста: логируется, `media_json` содержит file ids/metadata.
- Несколько photo sizes в одном message: сохраняются все элементы массива `photo`.
- Forwarded/automatic forwarded root messages: используются для thread mapping, но не пишутся как user inbound, если sender не пользователь.
- Service messages: игнорируются, если нет text/caption/media.
- Edited messages: явно игнорируются в MVP.
- Duplicate updates: не пишутся повторно из-за unique `update_id` и `chat_id + message_id`.
- Temporary Google Sheets outage: событие остается `failed`, retry через startup, background sync или `/internal/sync-pending`.
- Discussion group флуд вне post thread: игнорируется в строгом режиме.
- Anonymous admins / messages on behalf of chat: игнорируются через `sender_chat`.
- Bot/self messages: игнорируются через `from.is_bot` и `TELEGRAM_BOT_USER_ID`.

## Ограничения MVP

- Сервис не отвечает пользователям.
- SLA, first response, second response и support metrics не считаются.
- Исторические сообщения не импортируются.
- Album/media group не агрегируется в одну сущность; каждый Telegram message логируется отдельной строкой.
- Google Sheets append сам по себе не транзакционный. Защита от дублей реализована локально до append; если append прошел, а процесс умер до `mark_synced`, retry может добавить повторную строку. Для следующего этапа стоит добавить внешний idempotency layer в Sheets или отдельную durable outbox с reconciliation.
- Строгая comment detection зависит от того, видит ли бот root/thread updates в discussion group.

## TODO next

- Reconciliation job для проверки `dedup_key` в Sheets перед retry.
- Поддержка edited messages отдельным `event_type`.
- Импорт/repair thread mappings для уже существующих discussion threads.
- Метрики ingest/sync и Prometheus endpoint.
- SLA и реакция админов.
