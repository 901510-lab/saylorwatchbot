import os
import asyncio
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# === CONFIGURATION ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
CHECK_URL = os.getenv("CHECK_URL", "https://saylortracker.com")
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "15"))

# === LOGGING ===
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

def write_log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open("saylorbot.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")

# === RESET WEBHOOK ===
def clear_webhook(bot_token: str):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook?drop_pending_updates=true"
        r = requests.get(url, timeout=10)
        if r.ok:
            write_log("✅ Webhook очищен при старте (cleared successfully)")
        else:
            write_log(f"⚠️ Ошибка очистки webhook: {r.text}")
    except Exception as e:
        write_log(f"⚠️ Не удалось удалить webhook: {e}")

# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "👋 Привет! Я SaylorWatchBot.\n"
        "Буду следить за сайтом SaylorTracker и уведомлять о покупках BTC.\n\n"
        "👋 Hello! I'm SaylorWatchBot.\n"
        "I'll notify you when Bitcoin balance changes on SaylorTracker."
    )
    await update.message.reply_text(msg)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "✅ Бот активен и работает 24/7.\n"
        f"URL мониторинга: {CHECK_URL}\n\n"
        "✅ Bot is active and running 24/7.\n"
        f"Monitoring URL: {CHECK_URL}"
    )
    await update.message.reply_text(msg)

# === MONITOR SITE ===
async def check_site(app):
    last_balance = None
    while True:
        try:
            r = requests.get(CHECK_URL, timeout=15)
            if r.status_code == 200:
                content = r.text
                marker = "₿"
                current_balance = content.count(marker)

                if last_balance is None:
                    last_balance = current_balance
                elif current_balance != last_balance:
                    last_balance = current_balance
                    msg = (
                        "⚡ Обнаружено изменение на сайте SaylorTracker!\n"
                        "⚡ Bitcoin balance has changed on SaylorTracker!"
                    )
                    await app.bot.send_message(chat_id=X_CHAT_ID, text=msg)
                    write_log("📢 Notification sent — BTC balance changed")
            else:
                write_log(f"⚠️ Ошибка запроса: {r.status_code}")
        except Exception as e:
            write_log(f"❌ Ошибка проверки сайта: {e}")

        await asyncio.sleep(CHECK_INTERVAL_MIN * 60)

# === LAUNCHER ===
async def run_bot():
    write_log("🚀 SaylorWatchBot запущен / started (24/7 mode)")
    clear_webhook(BOT_TOKEN)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    # запускаем мониторинг сайта
    asyncio.create_task(check_site(app))

    write_log("🌐 Web server started and polling initialized")

    # вечный цикл polling с защитой от ошибок
    while True:
        try:
            await app.run_polling()
        except Exception as e:
            write_log(f"💥 Ошибка polling: {e}")
            write_log("♻️ Перезапуск через 10 секунд...")
            await asyncio.sleep(10)

# === ENTRY POINT (совместимо с Python 3.12) ===
if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except RuntimeError:
        # если Render запускает уже активный event loop — создаём новый вручную
        write_log("⚙️ Перехват активного event loop — создаётся новый цикл")
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        new_loop.run_until_complete(run_bot())
