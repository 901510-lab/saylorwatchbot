FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# fonts-dejavu-core — шрифты для генерации image-карточек (Pillow)
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY start.sh entities.json ./
COPY main.py i18n.py cards.py json_store.py user_lang_prefs.py alert_delivery.py \
    baseline.py bot_analytics.py bot_help_wiki.py entities.py models.py monitor_entities.py monitor_etf.py \
    subscribers.py subscription_plans.py subscription_payments.py subscription_reminders.py \
    founding_promo.py free_alert_queue.py free_tier_perks.py partners.py paper_wallet.py \
    plan_showcase.py transactions.py weekly_digest.py weekly_report_export.py whales.py \
    social_growth.py social_schedule.py post_announcement.py post_social.py ./
COPY sources/ ./sources/
COPY assets/plan_showcase_signals.json assets/
RUN chmod +x start.sh

EXPOSE 10000

CMD ["./start.sh"]
