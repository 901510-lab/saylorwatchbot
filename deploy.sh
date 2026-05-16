#!/usr/bin/env bash
# =========================================
# 🚀 SaylorWatchBot — автоматический деплой
# =========================================

set -euo pipefail

DEPLOY_SCRIPT_VERSION="2026-05-14.2"
PROJECT_FILES=(
  main.py
  requirements.txt
  Procfile
  runtime.txt
  start.sh
  deploy.sh
  .gitignore
  .env.example
  README.md
)

REMOTE_NAME="${REMOTE_NAME:-origin}"
REMOTE_URL="${GITHUB_REMOTE_URL:-}"
UPDATE_REMOTE_URL="${UPDATE_REMOTE_URL:-false}"
COMMIT_MESSAGE_VALUE="${COMMIT_MESSAGE:-}"

unstage_env_if_needed() {
  if git diff --cached --name-only | grep -qx '.env'; then
    echo "⚠️ .env уже был staged до запуска deploy.sh; убираю из staged changes."
    git restore --staged .env
  fi
}

assert_env_is_not_tracked() {
  if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    echo "❌ .env уже отслеживается git. Это риск утечки секретов."
    echo "   Выполните: git rm --cached .env"
    echo "   Затем закоммитьте удаление .env из индекса и храните секреты в Render Environment Variables."
    exit 1
  fi
}

if [[ "$REMOTE_URL" == *"USERNAME"* ]]; then
  echo "❌ Замените USERNAME в GITHUB_REMOTE_URL на ваш GitHub username или organization."
  echo "   Пример: GITHUB_REMOTE_URL=https://github.com/alex7706/SaylorWatchBot.git ./deploy.sh"
  exit 1
fi

echo "🚀 deploy.sh version: $DEPLOY_SCRIPT_VERSION"
echo "🔄 Проверяем git-репозиторий..."
if [ ! -d .git ]; then
  echo "⚙️  Инициализация нового репозитория..."
  git init
fi

CURRENT_BRANCH="${DEPLOY_BRANCH:-$(git branch --show-current 2>/dev/null || true)}"
if [ -z "$CURRENT_BRANCH" ]; then
  CURRENT_BRANCH="main"
  git branch -M "$CURRENT_BRANCH"
fi

assert_env_is_not_tracked
unstage_env_if_needed

echo "🧩 Добавляем изменения проекта (без .env)..."
# Важно: .env намеренно НЕ добавляется. Секреты должны оставаться только локально/в Render env vars.
git add -- "${PROJECT_FILES[@]}"
unstage_env_if_needed

if git diff --cached --name-only | grep -qx '.env'; then
  echo "❌ .env попал в staged changes. Это секретный файл; отменяю staging."
  git restore --staged .env
  exit 1
fi

if git diff --cached --quiet; then
  echo "ℹ️ Нет изменений для коммита."
else
  if [ -z "$COMMIT_MESSAGE_VALUE" ]; then
    echo "💬 Введите комментарий к коммиту:"
    read -r COMMIT_MESSAGE_VALUE
  fi

  if [ -z "$COMMIT_MESSAGE_VALUE" ]; then
    COMMIT_MESSAGE_VALUE="Update SaylorWatchBot"
  fi

  git commit -m "$COMMIT_MESSAGE_VALUE"
fi

if git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  current_remote_url="$(git remote get-url "$REMOTE_NAME")"
  if [ -n "$REMOTE_URL" ] && [ "$REMOTE_URL" != "$current_remote_url" ]; then
    if [ "$UPDATE_REMOTE_URL" = "true" ]; then
      echo "🌐 Обновляем remote $REMOTE_NAME: $REMOTE_URL"
      git remote set-url "$REMOTE_NAME" "$REMOTE_URL"
    else
      echo "ℹ️ Remote '$REMOTE_NAME' уже настроен: $current_remote_url"
      echo "   GITHUB_REMOTE_URL не меняет существующий remote автоматически."
      echo "   Если нужно заменить URL, запустите:"
      echo "   UPDATE_REMOTE_URL=true GITHUB_REMOTE_URL=$REMOTE_URL ./deploy.sh"
    fi
  fi
else
  if [ -n "$REMOTE_URL" ]; then
    echo "🌐 Добавляем remote $REMOTE_NAME: $REMOTE_URL"
    git remote add "$REMOTE_NAME" "$REMOTE_URL"
  else
    echo "❌ Remote '$REMOTE_NAME' не настроен."
    echo "   Исправление: git remote add $REMOTE_NAME https://github.com/YOUR_USERNAME/SaylorWatchBot.git"
    echo "   Или запустите: GITHUB_REMOTE_URL=https://github.com/YOUR_USERNAME/SaylorWatchBot.git ./deploy.sh"
    exit 1
  fi
fi

echo "⬆️ Отправляем ветку '$CURRENT_BRANCH' в GitHub remote '$REMOTE_NAME'..."
git push -u "$REMOTE_NAME" "$CURRENT_BRANCH"

echo "☁️  Ожидаем автоматический деплой на Render..."
sleep 3

echo "📜 Последние логи Render можно посмотреть здесь:"
echo "👉 https://dashboard.render.com/"
echo "✅ Готово! Бот будет запущен автоматически."
