# Markdown Bot

Telegram-бот для конвертации файлов в формат Markdown.

## Поддерживаемые форматы

| Категория | Форматы |
|-----------|---------|
| Документы | PDF, DOCX, DOC, ODT, RTF |
| Презентации | PPTX, PPT, ODP |
| Таблицы | XLSX, XLS, ODS, CSV |
| Веб / разметка | HTML, HTM, XML, JSON |
| Текст | TXT |
| Архивы | ZIP |

## Запуск локально

### Требования

- Python 3.12+
- pandoc (`apt install pandoc` / `brew install pandoc`)
- libmagic (`apt install libmagic1` / `brew install libmagic`)
- poppler-utils (`apt install poppler-utils` / `brew install poppler`)

### Установка

```bash
git clone https://github.com/your-username/markdown-bot.git
cd markdown-bot

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Отредактируй .env и вставь свой BOT_TOKEN
```

### Запуск

```bash
python bot.py
```

## Запуск через Docker

```bash
cp .env.example .env
# Отредактируй .env

docker compose up -d
```

Просмотр логов:

```bash
docker compose logs -f
```

## Деплой

### Railway

1. Создай новый проект на [railway.app](https://railway.app).
2. Подключи репозиторий.
3. Добавь переменную окружения `BOT_TOKEN` в настройках сервиса.
4. Railway автоматически соберёт Docker-образ и запустит бота.

### Render

1. Создай новый **Web Service** (или **Background Worker**) на [render.com](https://render.com).
2. Укажи репозиторий, выбери тип **Docker**.
3. Добавь переменную `BOT_TOKEN` в разделе Environment.
4. Деплой запустится автоматически.

### VPS (Ubuntu / Debian)

```bash
# Установи Docker
curl -fsSL https://get.docker.com | sh

# Склонируй репозиторий
git clone https://github.com/your-username/markdown-bot.git
cd markdown-bot

cp .env.example .env
nano .env   # вставь BOT_TOKEN

docker compose up -d
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|----------|
| `BOT_TOKEN` | — | Токен бота от @BotFather (обязательно) |
| `MAX_FILE_SIZE_MB` | `50` | Максимальный размер файла в МБ |
| `TEMP_DIR` | `/tmp/markdown_bot` | Папка для временных файлов |
| `RATE_LIMIT_SECONDS` | `10` | Минимальный интервал между запросами одного пользователя |
| `OWNER_ID` | `0` | Telegram user ID владельца (для команды /stats) |
| `STATS_DB_PATH` | `/tmp/markdown_bot/stats.db` | Путь к SQLite базе статистики |
| `WEBHOOK_URL` | — | URL вебхука (если задан — запуск через webhook, иначе polling) |
| `PORT` | `8080` | Порт для webhook-режима |
