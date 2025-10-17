import os
import asyncio
import logging
import datetime
import atexit
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
start_time = datetime.datetime.now()


def write_log(msg):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
    logger.info(msg)


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
        "/clear — очистить все сообщения (админ)\n"
        "/restart — перезапуск бота (админ)\n"
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


# === Очистка апдейтов ===
async def clear_pending_updates(token):
    bot = Bot(token)
    await bot.delete_webhook(drop_pending_updates=True)
    write_log("🧹 Очередь обновлений очищена")


# === Уведомления ===
async def notify_start(token, chat_id):
    try:
        bot = Bot(token)
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Бот запущен / Bot is live\n⏰ {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
        )
    except Exception as e:
        write_log(f"⚠️ Ошибка уведомления о запуске: {e}")


def notify_shutdown():
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        bot = Bot(BOT_TOKEN)
        loop.run_until_complete(
            bot.send_message(
                chat_id=X_CHAT_ID,
                text=f"🛑 Бот завершает работу / Bot is shutting down\n⏰ {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
            )
        )
    except Exception as e:
        write_log(f"⚠️ Ошибка при завершении: {e}")
    finally:
        try:
            loop.close()
        except Exception:
            pass


atexit.register(notify_shutdown)


# === Авто-пинг ===
async def ping_alive(bot: Bot):
    while True:
        await asyncio.sleep(6 * 60 * 60)
        uptime = datetime.datetime.now() - start_time
        try:
            await bot.send_message(
                chat_id=X_CHAT_ID,
                text=f"✅ Still alive (uptime: {uptime})"
            )
        except Exception as e:
            write_log(f"⚠️ Ошибка авто-пинга: {e}")


# === Основной запуск ===
async def main():
    await clear_pending_updates(BOT_TOKEN)
    await notify_start(BOT_TOKEN, X_CHAT_ID)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))

    bot = Bot(BOT_TOKEN)
    asyncio.create_task(ping_alive(bot))

    write_log("🚀 SaylorWatchBot запущен / polling mode активен")
    await app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    asyncio.run(main())
