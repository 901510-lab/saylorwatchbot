import asyncio
import logging
import os
import aiohttp
import hashlib
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest
from telegram.error import Conflict

# ----------------------------------------------------
# 🔧 Логирование
# ----------------------------------------------------
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------------------------------------------
# 🔑 Переменные окружения
# ----------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
CHECK_URL = os.getenv("CHECK_URL", "https://microstrategy.com/en/bitcoin")
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", 15))

# ----------------------------------------------------
# 🧠 Команды
# ----------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Бот следит за сайтом и сообщит, если появятся изменения.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🔍 Проверяю: {CHECK_URL}\nИнтервал: {CHECK_INTERVAL_MIN} минут")

async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧹 Очистка очереди...")
    await context.bot.delete_webhook(drop_pending_updates=True)
    await update.message.reply_text("✅ Очередь Telegram обновлений очищена.")

# ----------------------------------------------------
# 🌐 Мониторинг сайта
# ----------------------------------------------------
async def monitor_site(bot):
    """Отслеживает изменения контента страницы и уведомляет в Telegram"""
    previous_hash = None

    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(CHECK_URL, timeout=20) as response:
                    if response.status == 200:
                        html = await response.text()
                        current_hash = hashlib.sha256(html.encode()).hexdigest()

                        if previous_hash is None:
                            previous_hash = current_hash
                            logger.info("📡 Первичная загрузка страницы выполнена.")
                        elif current_hash != previous_hash:
                            previous_hash = current_hash
                            msg = f"⚡ Изменения на сайте!\n🔗 {CHECK_URL}"
                            await bot.send_message(chat_id=X_CHAT_ID, text=msg)
                            logger.info("🚨 Изменения обнаружены, уведомление отправлено.")
                        else:
                            logger.info("✅ Проверка прошла, изменений нет.")
                    else:
                        logger.warning(f"⚠️ Сайт ответил статусом {response.status}")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при проверке сайта: {e}")

        await asyncio.sleep(CHECK_INTERVAL_MIN * 60)

# ----------------------------------------------------
# 🏓 Поддержка Render (health-ping)
# ----------------------------------------------------
async def ping_alive():
    while True:
        logger.info("💓 Render ping — бот активен")
        await asyncio.sleep(300)

# ----------------------------------------------------
# 🚀 Основной запуск
# ----------------------------------------------------
async def main():
    request = HTTPXRequest(connection_pool_size=50, read_timeout=30, write_timeout=30)

    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .request(request)
        .build()
    )

    # Очистка webhook
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("🧹 Webhook очищен перед запуском polling")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось очистить webhook: {e}")

    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("clear", clear))

    # Фоновые задачи
    app.create_task(monitor_site(app.bot))
    app.create_task(ping_alive())

    logger.info("✅ Бот успешно запущен и работает в режиме polling")
    await app.run_polling(close_loop=False)

# ----------------------------------------------------
# 🧩 Безопасный запуск
# ----------------------------------------------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Conflict:
        logger.warning("⚠️ Другой экземпляр бота уже запущен — останавливаем этот процесс.")
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
