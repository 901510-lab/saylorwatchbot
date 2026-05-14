#!/bin/bash
# =========================================
# 🚀 SaylorWatchBot — автоматический деплой
# =========================================

echo "🔄 Проверяем git-репозиторий..."
if [ ! -d .git ]; then
  echo "⚙️  Инициализация нового репозитория..."
  git init
  git branch -M main
fi

echo "🧩 Добавляем изменения..."
git add main.py requirements.txt Procfile runtime.txt start.sh deploy.sh .gitignore

echo "💬 Введите комментарий к коммиту:"
read commit_message

if [ -z "$commit_message" ]; then
  commit_message="Update SaylorWatchBot"
fi

git commit -m "$commit_message"

# Проверяем наличие удалённого репозитория
if ! git remote | grep -q origin; then
  echo "🌐 Укажите ссылку на GitHub (например https://github.com/USERNAME/SaylorWatchBot.git):"
  read repo_url
  git remote add origin "$repo_url"
fi

echo "⬆️ Отправляем код на GitHub..."
git push -u origin main

echo "☁️  Ожидаем автоматический деплой на Render..."
sleep 3

echo "📜 Последние логи Render можно посмотреть здесь:"
echo "👉 https://dashboard.render.com/"
echo "✅ Готово! Бот будет запущен автоматически."
