# SaylorWatchBot

Telegram-бот для мониторинга BTC-холдингов Strategy/MicroStrategy и отправки уведомления, когда баланс BTC увеличился относительно сохранённого baseline.

## Требования

- Python `3.12.x` — Render runtime задан в `runtime.txt`.
- Telegram bot token из `@BotFather`.
- Telegram `chat_id`/user id для админ-команд и уведомлений.

## Настройка окружения

1. Скопируйте пример переменных:

   ```bash
   cp .env.example .env
   ```

2. Заполните минимум:

   ```env
   BOT_TOKEN=...
   X_CHAT_ID=...
   ```

`BOT_TOKEN` и `X_CHAT_ID` обязательны: приложение валидирует их при запуске и завершится с понятной ошибкой, если они не заданы.

## Установка зависимостей локально

```bash
python -m pip install -r requirements.txt
```

Если команда падает с `Tunnel connection failed: 403 Forbidden`, это не ошибка проекта: текущая среда не имеет доступа к PyPI через proxy/tunnel. Лучшие варианты исправления:

- запустить установку на машине/CI с доступом к `https://pypi.org`;
- настроить корпоративный proxy для `pip` через `HTTPS_PROXY`/`HTTP_PROXY`;
- использовать внутреннее PyPI-зеркало:

  ```bash
  python -m pip install -r requirements.txt --index-url https://your-pypi-mirror/simple
  ```

### Почему pip ставит `apscheduler`, `beautifulsoup4` и другие старые зависимости

Актуальный `requirements.txt` содержит только runtime-зависимости, которые нужны текущему коду:

```text
python-telegram-bot==20.6
python-dotenv==1.0.1
aiohttp==3.9.5
```

Если `pip install -r requirements.txt` устанавливает `apscheduler`, `requests`, `beautifulsoup4`, `certifi` или `nest_asyncio`, значит локально используется старый `requirements.txt`. Обновите файл из вашей рабочей ветки или удалите лишние строки вручную.

## Локальный запуск

```bash
python main.py
```

Или через helper-скрипт:

```bash
./start.sh
```

## Деплой и push в GitHub

Ошибка вида:

```text
fatal: 'origin' does not appear to be a git repository
```

означает, что в локальном репозитории не настроен remote `origin`. Это исправляется один раз:

```bash
git remote add origin https://github.com/YOUR_USERNAME/SaylorWatchBot.git
git push -u origin $(git branch --show-current)
```

Если remote уже есть, но URL неправильный:

```bash
git remote set-url origin https://github.com/YOUR_USERNAME/SaylorWatchBot.git
```

Также можно передать remote URL прямо в deploy-скрипт:

```bash
GITHUB_REMOTE_URL=https://github.com/YOUR_USERNAME/SaylorWatchBot.git ./deploy.sh
```

`deploy.sh` пушит текущую ветку, а не жёстко заданную `main`. При необходимости ветку можно указать явно:

```bash
DEPLOY_BRANCH=main ./deploy.sh
```



### Почему deploy.sh пишет про `.env`

Актуальный `deploy.sh` намеренно не добавляет `.env` в git, потому что там хранятся секреты. Если при запуске вы видите сообщение:

```text
Следующие пути игнорируются одним из ваших файлов .gitignore:
.env
```

значит локально запущена старая версия скрипта или в рабочей копии осталась старая строка `git add ... .env`. В актуальной версии при запуске должна быть строка вида:

```text
🚀 deploy.sh version: 2026-05-14.2
🧩 Добавляем изменения проекта (без .env)...
```

Проверьте локальный файл:

```bash
grep -n "DEPLOY_SCRIPT_VERSION\|git add" deploy.sh
```

В актуальной версии в списке должен быть `.env.example`, но не `.env`.

Если команда `git checkout origin/main -- README.md .env.example` пишет `pathspec ... did not match`, значит эти новые файлы ещё не попали в ваш `origin/main`. В таком случае сначала сделайте минимальный безопасный ремонт старого `deploy.sh`, чтобы запушить изменения без `.env`:

```bash
cp deploy.sh deploy.sh.bak
sed -i 's/git add main.py requirements.txt .env/git add main.py requirements.txt Procfile runtime.txt start.sh deploy.sh .gitignore/g' deploy.sh
chmod +x deploy.sh
grep -n "git add" deploy.sh
```

После `grep` в строке `git add` не должно быть `.env`. Затем можно выполнить деплой:

```bash
UPDATE_REMOTE_URL=true GITHUB_REMOTE_URL=https://github.com/YOUR_USERNAME/SaylorWatchBot.git ./deploy.sh
```

Если хотите подтянуть актуальный `deploy.sh` из remote, сначала убедитесь, что он там действительно есть:

```bash
git fetch origin
git ls-tree -r --name-only origin/main | grep -E '^(deploy.sh|README.md|.env.example|.gitignore)$'
```

Если `.env` уже когда-то был добавлен в git index, уберите его из отслеживания без удаления локального файла:

```bash
git ls-files --error-unmatch .env && git rm --cached .env || echo ".env не отслеживается git — это нормально"
```

### Если `origin` уже настроен

`GITHUB_REMOTE_URL=... ./deploy.sh` добавляет remote только если `origin` ещё не существует. Если `origin` уже есть, скрипт не меняет его без явного разрешения. Чтобы заменить URL существующего remote:

```bash
UPDATE_REMOTE_URL=true GITHUB_REMOTE_URL=https://github.com/YOUR_USERNAME/SaylorWatchBot.git ./deploy.sh
```

Не используйте буквальный `USERNAME` из примера — замените его на ваш GitHub username или organization.

## Security: leaked Telegram tokens

If a Telegram bot token appears in terminal output, screenshots, logs, GitHub issues, chat messages, or deployment logs, treat it as compromised immediately.

1. Open `@BotFather` in Telegram.
2. Run `/mybots` and select the affected bot.
3. Choose **API Token** → **Revoke current token**.
4. Put the new token only in `.env` locally or in your hosting provider's environment variables.
5. Do not commit `.env` and avoid pasting logs that contain `https://api.telegram.org/bot...` URLs.

The app lowers `httpx` logging noise to reduce accidental Telegram API URL logging, but token rotation is still required after a token was exposed.

## Render

`Procfile` запускает `start.sh`, а `start.sh` запускает `python main.py`. Зависимости должны устанавливаться на build-этапе платформы из `requirements.txt`, а не при каждом старте worker-процесса.
