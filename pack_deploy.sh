#!/usr/bin/env bash
# Собрать архив для загрузки на сервер (JustRunMy / свой VPS / Ubuntu).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
STAMP="$(date -u +%Y%m%d-%H%M)"
OUT="${1:-$ROOT/saylorwatch_deploy_${STAMP}.zip}"

BOT_FILES=(
  json_store.py
  user_lang_prefs.py
  free_alert_queue.py
  free_tier_perks.py
  partners.py
  main.py
  i18n.py
  alert_delivery.py
  baseline.py
  bot_analytics.py
  cards.py
  entities.py
  entities.json
  models.py
  monitor_entities.py
  monitor_etf.py
  subscribers.py
  subscription_plans.py
  subscription_payments.py
  subscription_reminders.py
  founding_promo.py
  paper_wallet.py
  transactions.py
  weekly_digest.py
  bot_help_wiki.py
  plan_showcase.py
  weekly_report_export.py
  whales.py
  assets/plan_showcase_signals.json
  social_growth.py
  social_schedule.py
  requirements.txt
  start.sh
  sources/__init__.py
  sources/base.py
  sources/http.py
  sources/strategy.py
  sources/coingecko_treasury.py
  sources/farside_etf.py
  sources/sosovalue_etf.py
)

SCRIPT_FILES=(
  scripts/email_support_agent.py
  scripts/bot_knowledge.py
  scripts/faq_normalize.py
  scripts/graph_mail_oauth.py
  scripts/outlook_oauth.py
  scripts/email_support.example.env
  scripts/generate_modelfile.py
  scripts/Modelfile.saylorwatch-support
  scripts/setup_ollama_support_model.sh
  scripts/install_email_systemd.sh
  scripts/export_social_tiers.py
  scripts/sanity_check.py
  scripts/paper_wallet_post.py
  scripts/social_calendar_sync.py
  scripts/social_calendar.example.env
  scripts/setup_social_calendar.sh
  scripts/requirements-social.txt
  scripts/systemd/saylorwatch-email-poll.service
  scripts/systemd/saylorwatch-email-poll.timer
  scripts/systemd/saylorwatch-email-startup.service
)

cd "$ROOT"
for f in "${BOT_FILES[@]}" "${SCRIPT_FILES[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "ERROR: missing $f" >&2
    exit 1
  fi
done

cat >"$ROOT/SERVER_UPLOAD.md" <<EOF
# Загрузка SaylorWatchBot на сервер

Собрано: $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC

## 1. Распаковка

### JustRunMy (\`/app/SaylorWatchBot\`)
\`\`\`bash
cd /app/SaylorWatchBot
unzip -o ~/saylorwatch_deploy_*.zip
\`\`\`

### Свой Ubuntu
\`\`\`bash
cd ~/SaylorWatchBot
unzip -o ~/Загрузки/saylorwatch_deploy_*.zip
\`\`\`

## 2. НЕ перезаписывать на сервере

- \`.env\`
- \`scripts/email_support.env\`
- \`scripts/.email_*oauth*.json\`
- \`scripts/.email_support_state.json\`
- \`baselines/\`, \`subscribers.json\`, \`payments.json\`, \`transactions.json\`
- \`user_languages.json\`, \`free_alert_queue.json\`, \`free_tier_perks.json\`
- \`paper_wallet_state.json\` (ежедневный пост @Paper_wallet_co)
- \`free_alert_card_cache/\` (кэш PNG для отложенных free-алертов)

Архив их не содержит — это нормально.

## 3. Telegram-бот

\`\`\`bash
pip install -r requirements.txt
# перезапуск (панель хостинга или):
pkill -f 'python3 main.py' || true
nohup ./start.sh >> bot.log 2>&1 &
\`\`\`

## 4. Почтовый агент (если на этом же сервере)

\`\`\`bash
cp -n scripts/email_support.example.env scripts/email_support.env
bash scripts/install_email_systemd.sh
systemctl --user daemon-reload
systemctl --user restart saylorwatch-email-poll.timer
python3 scripts/email_support_agent.py --check
\`\`\`

## 5. Проверка

\`\`\`bash
python3 scripts/sanity_check.py
\`\`\`

## 6. Paper Wallet — ручной пост в канал

\`\`\`bash
python3 scripts/paper_wallet_post.py --force
\`\`\`

Автопост каждый день 12:00 MSK — в \`main.py\` (нужен \`PAPER_WALLET_ENABLED=true\` в \`.env\`).
EOF

rm -f "$OUT"
zip -q "$OUT" "${BOT_FILES[@]}" "${SCRIPT_FILES[@]}" SERVER_UPLOAD.md

echo "✅ $OUT"
echo "   Размер: $(du -h "$OUT" | cut -f1)"
unzip -l "$OUT" | tail -1
echo ""
echo "Загрузите на сервер → распакуйте в каталог бота."
echo "Инструкция: SERVER_UPLOAD.md (внутри архива и в корне проекта)"
