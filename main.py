import os
import asyncio
import logging
import datetime
import threading
import atexit
from aiohttp import web
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === Инициализация ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

def write_log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
    logger.info(msg)

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Бот активен и работает 24/7 🚀")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот онлайн и готов к работе.")

# === Очистка старых апдейтов ===
async def clear_pending_updates(token):
    try:
        bot = Bot(token)
        updates = await bot.get_updates()
        if updates:
            await bot.delete_webhook(drop_pending_updates=True)
            write_log(f"🧹 Очередь сообщений очищена ({len(updates)})")
        else:
            write_log("🧹 Очередь сообщений пуста")
    except Exception as e:
        write_log(f"⚠️ Ошибка очистки апдейтов: {e}")

# === Уведомление о запуске ===
async def notify_start(token, chat_id):
    try:
        bot = Bot(token)
        await asyncio.sleep(3)
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Бот запущен и готов к работе / Bot is live (Render)\n⏰ {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
        )
        write_log("📩 Уведомление о запуске отправлено")
    except Exception as e:
        write_log(f"⚠️ Ошибка уведомления о запуске: {e}")

# === Уведомление о завершении ===
def notify_shutdown():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = Bot(BOT_TOKEN)
        loop.run_until_complete(
            bot.send_message(
                chat_id=X_CHAT_ID,
                text=f"🛑 Бот завершает работу / Bot is shutting down (Render)\n⏰ {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
            )
        )
        write_log("📩 Уведомление о завершении отправлено")
    except Exception as e:
        write_log(f"⚠️ Ошибка уведомления о завершении: {e}")

atexit.register(notify_shutdown)

# === Веб-сервер для Render ===
async def handle(request):
    return web.Response(text="✅ SaylorWatchBot is running")

def start_web_server():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    web.run_app(app, host="0.0.0.0", port=PORT)

# === Основной запуск бота ===
async def run_bot():
    write_log("🚀 SaylorWatchBot запущен / started (24/7 mode)")

    await clear_pending_updates(BOT_TOKEN)
    write_log("✅ Webhook очищен при старте (cleared successfully)")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))

    await notify_start(BOT_TOKEN, X_CHAT_ID)

    try:
        await application.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)
    except RuntimeError as e:
        if "event loop is already running" in str(e):
            write_log("⚙️ Event loop уже активен — используем fallback режим")
            await application.initialize()
            await application.start()
            await application.updater.start_polling()
        else:
            raise e

# === Точка входа ===
def main():
    threading.Thread(target=start_web_server, daemon=True).start()
    try:
        asyncio.run(run_bot())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())

if __name__ == "__main__":
    main()
