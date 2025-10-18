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

# === Очистка сообщений ===
async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    chat_id = update.message.chat_id
    bot = context.bot
    deleted = 0

    try:
        # Правильное получение истории сообщений
        messages = await bot.get_chat_history(chat_id, limit=200)
        for msg in messages:
            if msg.from_user and msg.from_user.is_bot:
                try:
                    await bot.delete_message(chat_id, msg.message_id)
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
        "Чтобы очистить весь чат — используйте 'Удалить чат' вручную."
    )

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
        async for msg in bot.get_chat(chat_id).iter_history(limit=200):
            if msg.from_user and msg.from_user.is_bot:
                try:
                    await bot.delete_message(chat_id, msg.message_id)
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
        "Чтобы очистить весь чат — используйте 'Удалить чат' вручную."
    )

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

# === Мониторинг покупок MicroStrategy ===
LAST_PURCHASE_FILE = "last_purchase.txt"

async def fetch_latest_purchase():
    """Извлекает последнюю запись из таблицы покупок MicroStrategy на saylortracker.com"""
    import aiohttp
    url = "https://saylortracker.com/"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "html.parser")

    table_title = soup.find(string=lambda t: "Purchase History" in t or "Purchases" in t)
    if not table_title:
        return None

    table = table_title.find_parent("div").find_next("table")
    if not table:
        return None

    first_row = table.find("tbody").find("tr")
    if not first_row:
        return None

    cells = [c.get_text(strip=True) for c in first_row.find_all("td")]
    if len(cells) < 4:
        return None

    # Пример: ['Oct 12, 2025', '3,000', '$59,900', '$180M']
    return {
        "date": cells[0],
        "amount": cells[1],
        "total": cells[3]
    }

async def monitor_saylor_purchases(bot: Bot):
    """Отслеживает новые покупки биткойна Майклом Сэйлором"""
    last_date = None
    if os.path.exists(LAST_PURCHASE_FILE):
        with open(LAST_PURCHASE_FILE, "r") as f:
            last_date = f.read().strip()

    while True:
        try:
            purchase = await fetch_latest_purchase()
            if not purchase:
                write_log("⚠️ Не удалось получить данные о покупках MicroStrategy.")
            else:
                if purchase["date"] != last_date:
                    message = (
                        f"💰 Новая покупка Bitcoin!\n"
                        f"📅 Дата: {purchase['date']}\n"
                        f"₿ Количество: {purchase['amount']}\n"
                        f"🏦 Сумма: {purchase['total']}"
                    )
                    await bot.send_message(chat_id=X_CHAT_ID, text=message)
                    write_log(message)
                    last_date = purchase["date"]
                    with open(LAST_PURCHASE_FILE, "w") as f:
                        f.write(last_date)
                else:
                    write_log(f"ℹ️ Проверка покупок MicroStrategy — без изменений ({purchase['date']})")
        except Exception as e:
            write_log(f"⚠️ Ошибка мониторинга покупок: {e}")

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

    bot = Bot(BOT_TOKEN)
    asyncio.create_task(ping_alive(bot))
    asyncio.create_task(start_healthcheck_server())
    asyncio.create_task(monitor_saylor_purchases(bot))

    write_log("✅ Бот успешно запущен и работает в режиме polling")
    asyncio.create_task(ping_alive(bot))
    asyncio.create_task(start_healthcheck_server())
    asyncio.create_task(monitor_saylor_purchases(bot))
    await app.run_polling()

if __name__ == "__main__":
    import asyncio

    write_log("🚀 Инициализация SaylorWatchBot...")

    # Выполняем асинхронные функции отдельно
    asyncio.run(clear_pending_updates(BOT_TOKEN))
    asyncio.run(notify_start(BOT_TOKEN, X_CHAT_ID))

    # Создаём приложение Telegram
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))

    bot = Bot(BOT_TOKEN)

    # 🔧 В Python 3.12 нужно вручную создать event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Фоновые задачи
    loop.create_task(ping_alive(bot))
    loop.create_task(start_healthcheck_server())
    loop.create_task(monitor_saylor_purchases(bot))

    write_log("✅ Бот успешно запущен и работает в режиме polling")

    # Запуск polling
    app.run_polling()
