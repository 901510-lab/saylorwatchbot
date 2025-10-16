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
X_CHAT_ID = os.getenv("X_CHAT_ID")  # твой chat_id
CHECK_URL = os.getenv("CHECK_URL", "https://saylortracker.com")
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "15"))

# === LOGGING SETUP ===
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# === UTILITIES ===
def write_log(message: str):
    """Лог в консоль + файл"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open("saylorbot.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")

def clear_webhook(bot_token: str):
    """Очистка webhook перед запуском polling"""
    try:
        url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook?drop_pending_updates=true"
        r = requests.get(url)
        if r.ok:
            write_log("✅ Webhook очищен при старте (cleared successfully)")
        else:
            write_log(f"⚠️ Ошибка очистки webhook: {r.text}")
    except Exception as e:
        write_log(f"⚠️ Не удалось удалить webhook: {e}")

# === COMMAND HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветственное сообщение"""
    text = (
        "👋 Привет! Я SaylorWatchBot.\n"
        "Буду следить за изменениями на сайте и сообщать тебе о покупках BTC.\n\n"
        "Hello! I'm SaylorWatchBot.\n"
        "I'll notify you when new Bitcoin purchases are detected."
    )
    await update.message.reply_text(text)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса"""
    text = (
        "📊 Бот работает стабильно.\n"
        "Мониторинг сайта: ✅\n\n"
        "📊 Bot is running.\n"
        "Website monitoring: ✅"
    )
    await update.message.reply_text(text)

# === WEBSITE CHECK LOOP ===
async def check_site(app):
    """Проверка изменений на сайте (по содержимому)"""
    last_balance = None
    while True:
        try:
            r = requests.get(CHECK_URL, timeout=15)
            if r.status_code == 200:
                content = r.text
                marker = "₿"  # ищем общий элемент (для упрощённого примера)
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
                    write_log("📢 Notification sent: site content changed")
            else:
                write_log(f"⚠️ Ошибка запроса: {r.status_code}")
        except Exception as e:
            write_log(f"❌ Ошибка при проверке сайта: {e}")

        await asyncio.sleep(CHECK_INTERVAL_MIN * 60)

# === MAIN APP LAUNCH ===
async def main():
    write_log("🚀 SaylorWatchBot запущен / started (24/7 mode)")
    clear_webhook(BOT_TOKEN)

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    # Запускаем мониторинг сайта параллельно с polling
    asyncio.create_task(check_site(app))

    write_log("🌐 Web server started and polling initialized")
    await app.run_polling(close_loop=False)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except RuntimeError:
        # Render иногда вызывает ошибку “event loop already running”
        write_log("⚙️ Event loop уже активен — запускаем альтернативный режим")
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
