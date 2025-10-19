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

        # === Команда /clear ===
async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет последние сообщения бота"""
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    chat_id = update.message.chat_id
    bot = context.bot
    deleted = 0

    try:
        # Ограничим число апдейтов до 30 (вместо 100)
        updates = await bot.get_updates(limit=30)

        # Удаляем сообщения постепенно (1–2/сек)
        for upd in updates:
            if upd.message and upd.message.from_user and upd.message.from_user.is_bot:
                try:
                    await bot.delete_message(chat_id, upd.message.message_id)
                    deleted += 1
                    await asyncio.sleep(0.5)  # 👈 замедление — ключевой момент
                except Exception as e:
                    logger.warning(f"Не удалось удалить сообщение: {e}")

    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Ошибка при удалении: {e}\n"
            "Совет: подожди 10–15 секунд и попробуй ещё раз."
        )
        return

    await update.message.reply_text(f"🧹 Удалено сообщений бота: {deleted}")

# === Уведомление о старте ===
async def notify_start(token, chat_id):
    try:
        bot = Bot(token)
        commit = os.getenv("RENDER_GIT_COMMIT", "N/A")
        await bot.send_message(
            chat_id=chat_id,
            text=f"✅ Бот запущен / Bot is live\n🧩 Commit: `{commit}`\n⏰ {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
            parse_mode="Markdown",
        )
    except Exception as e:
        write_log(f"⚠️ Ошибка уведомления о запуске: {e}")

# === Автопинг ===
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

# === Мониторинг покупок MicroStrategy (исправленный и устойчивый) ===
LAST_PURCHASE_FILE = "last_purchase.txt"
CHECK_URL = os.getenv("CHECK_URL", "https://saylortracker.com/")

async def fetch_latest_purchase():
    """Парсит таблицу с сайта SaylorTracker и возвращает первую запись"""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHECK_URL, timeout=20) as resp:
                if resp.status != 200:
                    write_log(f"⚠️ Ошибка загрузки ({resp.status}) с {CHECK_URL}")
                    return None
                html = await resp.text()
    except Exception as e:
        write_log(f"⚠️ Ошибка сети при загрузке сайта: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        write_log("⚠️ Таблица с покупками не найдена.")
        return None

    rows = table.find_all("tr")
    if len(rows) < 2:
        return None

    # первая строка с данными (пропускаем заголовок)
    first_row = rows[1]
    cells = [c.get_text(strip=True) for c in first_row.find_all("td")]
    if len(cells) < 4:
        write_log("⚠️ Недостаточно ячеек в таблице.")
        return None

    date, amount, price, total = cells[0], cells[1], cells[2], cells[3]
    return {"date": date, "amount": amount, "price": price, "total": total}


async def monitor_saylor_purchases(bot: Bot):
    """Проверяет покупки MicroStrategy каждые 15 минут"""
    last_date = None
    if os.path.exists(LAST_PURCHASE_FILE):
        with open(LAST_PURCHASE_FILE, "r") as f:
            last_date = f.read().strip()

    write_log(f"🕵️ Запущен мониторинг {CHECK_URL}")

    while True:
        try:
            purchase = await fetch_latest_purchase()
            if not purchase:
                write_log("⚠️ Не удалось получить данные о покупках MicroStrategy.")
            else:
                if purchase["date"] != last_date:
                    msg = (
                        f"💰 *MicroStrategy купила Bitcoin!*\n"
                        f"📅 Дата: {purchase['date']}\n"
                        f"₿ Количество: {purchase['amount']}\n"
                        f"💵 Сумма: {purchase['total']}\n"
                        f"🌐 Источник: {CHECK_URL}"
                    )
                    await bot.send_message(chat_id=X_CHAT_ID, text=msg, parse_mode="Markdown")
                    write_log(f"🚨 Новая покупка: {purchase}")
                    last_date = purchase["date"]
                    with open(LAST_PURCHASE_FILE, "w") as f:
                        f.write(last_date)
                else:
                    write_log(f"ℹ️ Проверка — без изменений ({purchase['date']})")
        except Exception as e:
            write_log(f"⚠️ Ошибка мониторинга: {e}")

        await asyncio.sleep(15 * 60)

        # === Post-init: единая точка старта фоновых задач и очистки webhook ===
async def _post_init(application: Application):
    # 1) Очистка возможного старого webhook, чтобы избежать Conflict
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        write_log("🧹 Очередь обновлений очищена (drop_pending_updates=True)")
    except Exception as e:
        write_log(f"⚠️ Ошибка при очистке webhook: {e}")

    # 2) Уведомление о запуске
    await notify_start(BOT_TOKEN, X_CHAT_ID)

    # 3) Фоновые задачи (используем application.create_task — корректно в рамках PTB)
    application.create_task(start_healthcheck_server())
    application.create_task(monitor_saylor_purchases(application.bot))
    application.create_task(ping_alive(application.bot))

    write_log("🧩 post_init завершён: фоновые задачи запущены")

# === Команда /site ===
async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = os.getenv("CHECK_URL", "https://saylortracker.com/")
    await update.message.reply_text(f"🌐 Текущий сайт для мониторинга:\n{url}")

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

    write_log("✅ Бот успешно запущен и работает в режиме polling")

    # 🚀 Запуск только одного event loop
    app.run_polling(close_loop=False)
