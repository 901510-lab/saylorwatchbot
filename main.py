import os
import asyncio
from telegram.error import Conflict
import logging
import datetime
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from aiohttp import web
from bs4 import BeautifulSoup
from telegram.request import HTTPXRequest

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
start_time = datetime.datetime.now()

def write_log(msg: str):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
    logger.info(msg)

async def main():
    logger.info("🚀 Инициализация SaylorWatchBot...")

    # Создаём объект запроса с увеличенным пулом соединений и таймаутами
    from telegram.request import HTTPXRequest
    request = HTTPXRequest(connection_pool_size=50, read_timeout=30, write_timeout=30)

    # Строим приложение с кастомным HTTP-пулом
    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Бот активен и работает 24/7 🚀")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    await update.message.reply_text(f"✅ Бот онлайн\n⏱ Аптайм: {uptime}")

async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    await update.message.reply_text(f"⏱ Аптайм: {uptime}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Команды:*\n"
        "/start — проверить статус бота\n"
        "/status — аптайм и состояние\n"
        "/uptime — время работы\n"
        "/info — информация о системе\n"
        "/site — какой сайт мониторится\n"
        "/clear — удалить сообщения бота\n"
        "/restart — перезапуск Render-инстанса (админ)\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    commit = os.getenv("RENDER_GIT_COMMIT", "N/A")
    instance = os.getenv("RENDER_INSTANCE_ID", "N/A")
    uptime = datetime.datetime.now() - start_time
    msg = (
        f"🧠 *Информация о боте:*\n"
        f"Commit: `{commit}`\n"
        f"Instance: `{instance}`\n"
        f"Uptime: {uptime}\n"
        f"Server Time: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return
    await update.message.reply_text("🔄 Перезапуск Render-инстанса...")
    os._exit(0)

# === Очистка сообщений ===
async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    chat_id = update.message.chat_id
    bot = context.bot
    deleted = 0

    try:
        # получаем последние 100 апдейтов и удаляем только сообщения бота
        updates = await bot.get_updates(limit=100)
        for upd in updates:
            if upd.message and upd.message.from_user and upd.message.from_user.is_bot:
                try:
                    await bot.delete_message(chat_id, upd.message.message_id)
                    deleted += 1
                    await asyncio.sleep(0.15)
                except Exception:
                    pass
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при удалении: {e}")
        return

    await update.message.reply_text(
        f"🧹 Удалено сообщений бота: {deleted}\n"
        "❗ Telegram не позволяет удалять ваши собственные сообщения.\n"
        "Чтобы полностью очистить — используйте 'Удалить чат' вручную."
    )

# === Очистка апдейтов ===
async def clear_pending_updates(token):
    bot = Bot(token)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        write_log("🧹 Очередь обновлений очищена")
    except Exception as e:
        write_log(f"⚠️ Ошибка при очистке webhook: {e}")

   # === Команда /status ===
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    msg = (
        f"✅ *Бот онлайн*\n"
        f"⏱ Аптайм: {uptime}\n"
        f"📅 Время сервера: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


# === Команда /clear ===
async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет последние сообщения бота"""
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    bot = context.bot
    chat_id = update.effective_chat.id
    deleted = 0

    # Получаем последние 50 сообщений и удаляем только свои
    try:
        async for message in bot.get_chat_history(chat_id, limit=50):
            if message.from_user and message.from_user.is_bot:
                try:
                    await bot.delete_message(chat_id, message.message_id)
                    deleted += 1
                    await asyncio.sleep(0.3)
                except Exception:
                    pass
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка при очистке: {e}")
        return

    await update.message.reply_text(f"🧹 Удалено сообщений бота: {deleted}")


# === Основной запуск ===
if __name__ == "__main__":
    write_log("🚀 Инициализация SaylorWatchBot...")

    # Настраиваем HTTP-клиент с увеличенным пулом
    request = HTTPXRequest(connection_pool_size=50, read_timeout=30, write_timeout=30)

    # Создаём приложение и регистрируем post_init
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(_post_init)
        .build()
    )

    # Регистрируем все хендлеры
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("site", site))
    app.add_handler(CommandHandler("monitor", monitor))

    # Очистка старого webhook перед запуском polling
    try:
        Bot(BOT_TOKEN).delete_webhook(drop_pending_updates=True)
        write_log("🧹 Webhook очищен перед запуском polling")
    except Exception as e:
        write_log(f"⚠️ Ошибка при очистке webhook перед запуском: {e}")

    write_log("✅ Бот успешно запущен и работает в режиме polling")
    app.run_polling(close_loop=False)
