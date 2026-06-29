# Загрузка SaylorWatchBot на сервер

Собрано: 2026-06-29T14:51:34Z UTC

## 1. Распаковка

### JustRunMy (`/app/SaylorWatchBot`)
```bash
cd /app/SaylorWatchBot
unzip -o ~/saylorwatch_deploy_*.zip
```

### Свой Ubuntu
```bash
cd ~/SaylorWatchBot
unzip -o ~/Загрузки/saylorwatch_deploy_*.zip
```

## 2. НЕ перезаписывать на сервере

- `.env`
- `scripts/email_support.env`
- `scripts/.email_*oauth*.json`
- `scripts/.email_support_state.json`
- `baselines/`, `subscribers.json`, `payments.json`, `transactions.json`
- `user_languages.json`, `free_alert_queue.json`, `free_tier_perks.json`
- `paper_wallet_state.json` (ежедневный пост @Paper_wallet_co)
- `free_alert_card_cache/` (кэш PNG для отложенных free-алертов)

Архив их не содержит — это нормально.

## 3. Telegram-бот

```bash
pip install -r requirements.txt
# перезапуск (панель хостинга или):
pkill -f 'python3 main.py' || true
nohup ./start.sh >> bot.log 2>&1 &
```

## 4. Почтовый агент (если на этом же сервере)

```bash
cp -n scripts/email_support.example.env scripts/email_support.env
bash scripts/install_email_systemd.sh
systemctl --user daemon-reload
systemctl --user restart saylorwatch-email-poll.timer
python3 scripts/email_support_agent.py --check
```

## 5. Проверка

```bash
python3 scripts/sanity_check.py
```

## 6. Paper Wallet — ручной пост в канал

```bash
python3 scripts/paper_wallet_post.py --force
```

Автопост каждый день 12:00 MSK — в `main.py` (нужен `PAPER_WALLET_ENABLED=true` в `.env`).
