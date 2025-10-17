import os
import asyncio
import logging
import datetime
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from aiohttp import web
from bs4 import BeautifulSoup

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
    await update.message.reply_text("🧹 Начинаю очистку сообщений...")
    bot = context.bot
    deleted = 0
    try:
        async for msg in bot.get_chat(chat_id).iter_history(limit=200):
            if msg.from_user and msg.from_user.is_bot:
                try:
                    await bot.delete_message(chat_id, msg.message_id)
                    deleted += 1
                    await asyncio.sleep(0.2)
                except Exception:
                    pass
        await bot.send_message(chat_id, f"✅ Очистка завершена. Удалено сообщений: {deleted}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Ошибка очистки: {e}")

# === Очистка апдейтов ===
async def clear_pending_updates(token):
    bot = Bot(token)
    await bot.delete_webhook(drop_pending_updates=True)
    write_log("🧹 Очередь обновлений очищена")

# === Уведомления ===
async def notify_start(token, chat_id):
    try:
        bot = Bot(token)
        commit = os.getenv("RENDER_GIT_COMMIT", "N/A")
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Бот запущен / Bot is live\n🧩 Commit: `{commit}`\n⏰ {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
            parse_mode="Markdown"
        )
    except Exception as e:
        write_log(f"⚠️ Ошибка уведомления о запуске: {e}")

# === Авто-пинг ===
async def ping_alive(bot: Bot):
    while True:
        await asyncio.sleep(6 * 60 * 60)
        uptime = datetime.datetime.now() - start_time
        try:
            await bot.send_message(chat_id=X_CHAT_ID, text=f"✅ Still alive (uptime: {uptime})")
        except Exception as e:
            write_log(f"⚠️ Ошибка авто-пинга: {e}")

# === Health-check сервер ===
async def handle(request):
    return web.Response(text="✅ SaylorWatchBot is alive")

async def start_healthcheck_server():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    write_log(f"🌐 Health-check сервер запущен на порту {PORT}")

# === Мониторинг SaylorTracker ===
LAST_PRICE_FILE = "last_price.txt"

async def fetch_saylor_price():
    """Получает текущую цену MicroStrategy с сайта saylortracker.com"""
    import aiohttp
    url = "https://saylortracker.com/"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()
    soup = BeautifulSoup(html, "html.parser")
    elem = soup.find(string=lambda t: "Average BTC Price" in t)
    if not elem:
        return None
    price_tag = elem.find_parent("div").find_next_sibling("div")
    if not price_tag:
        return None
    return price_tag.text.strip()

async def monitor_saylor_price(bot: Bot):
    """Отслеживает изменение средней цены MicroStrategy"""
    last_price = None
    if os.path.exists(LAST_PRICE_FILE):
        with open(LAST_PRICE_FILE, "r") as f:
            last_price = f.read().strip()

    while True:
        try:
            current_price = await fetch_saylor_price()
            if current_price and current_price != last_price:
                direction = ""
                try:
                    c_val = float(current_price.replace("$", "").replace(",", ""))
                    l_val = float(last_price.replace("$", "").replace(",", "")) if last_price else c_val
                    direction = "🔺" if c_val > l_val else "🔻" if c_val < l_val else "➖"
                except Exception:
                    direction = "💰"
                message = f"{direction} Цена MicroStrategy изменилась:\nБыла: {last_price or 'N/A'} → Стала: {current_price}"
                await bot.send_message(chat_id=X_CHAT_ID, text=message)
                write_log(message)
                last_price = current_price
                with open(LAST_PRICE_FILE, "w") as f:
                    f.write(current_price)
            else:
                write_log(f"ℹ️ Проверка SaylorTracker — без изменений ({current_price})")
        except Exception as e:
            write_log(f"⚠️ Ошибка мониторинга SaylorTracker: {e}")

        await asyncio.sleep(15 * 60)  # каждые 15 минут

# === Основной запуск ===
async def main():
    write_log("🚀 Инициализация SaylorWatchBot...")
    await clear_pending_updates(BOT_TOKEN)
    await notify_start(BOT_TOKEN, X_CHAT_ID)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))

    # фоновые задачи
    bot = Bot(BOT_TOKEN)
    asyncio.create_task(ping_alive(bot))
    asyncio.create_task(start_healthcheck_server())
    asyncio.create_task(monitor_saylor_price(bot))

    write_log("✅ Бот успешно запущен и работает в режиме polling")
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    await app.updater.idle()

if __name__ == "__main__":
    asyncio.run(main())
