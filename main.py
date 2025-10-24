import os
import asyncio
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

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
start_time = datetime.datetime.now()

def write_log(msg: str):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
    logger.info(msg)

# === Команды ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Привет! Бот активен и работает 24/7 🚀")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import aiohttp
    import datetime

    uptime = datetime.datetime.now() - start_time
    status_msg = f"✅ Бот онлайн\n⏱ Аптайм: {uptime}\n"

    # Проверяем последний зафиксированный результат
    last_info = "📊 Данных о последних покупках пока нет (бот ждёт обновления сайта)."
    if os.path.exists(LAST_PURCHASE_FILE):
        with open(LAST_PURCHASE_FILE, "r") as f:
            last_date = f.read().strip()
            if last_date:
                last_info = f"📅 Последняя покупка: {last_date}"

    # Проверяем сайт доступности
site_status = "❌ Ошибка подключения"
try:
    async with aiohttp.ClientSession() as session:
        async with session.get(CHECK_URL, timeout=10) as resp:
            if resp.status == 200:
                site_status = "✅ Сайт доступен и работает"
            else:
                site_status = f"⚠️ Ответ сайта: {resp.status}"
except Exception as e:
    site_status = f"⚠️ Ошибка: {type(e).__name__}"

        # === Общее количество купленных BTC с SaylorTracker ===
    total_btc_info = "⚠️ Не удалось получить данные о покупках"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get("https://saylortracker.com/", timeout=15) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, "html.parser")
                    total_elem = soup.find("strong", string=lambda s: s and "Total" in s)
                    if total_elem:
                        total_text = total_elem.find_next("td").get_text(strip=True)
                        total_btc_info = f"📊 Всего куплено BTC: {total_text}"
                    else:
                        total_btc_info = "⚠️ Не удалось найти итоговую строку на сайте"
                else:
                    total_btc_info = f"⚠️ Ошибка загрузки сайта ({resp.status})"
    except Exception as e:
        total_btc_info = f"⚠️ Ошибка при обработке данных: {type(e).__name__}"

    # Получаем баланс MicroStrategy через bitcointreasuries.net
    btc_balance_info = "⚠️ Не удалось получить баланс BTC"
    try:
        api_url = "https://bitcointreasuries.net/api/v2/companies"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for c in data:
                        if "MicroStrategy" in c.get("name", ""):
                            btc = c.get("bitcoin", "0")
                            usd = c.get("usd_value", "0")
                            price = c.get("btc_price", "0")
                            btc_balance_info = (
                                f"💰 Баланс MicroStrategy: {btc} BTC (~${usd})\n"
                                f"📈 Средняя цена покупки: ${price}"
                            )
                            break
                else:
                    btc_balance_info = f"⚠️ API ответ: {resp.status}"
    except Exception as e:
        btc_balance_info = f"⚠️ Ошибка при получении баланса: {type(e).__name__}"

    # Итоговое сообщение
    msg = (
        f"{status_msg}\n"
        f"{last_info}\n"
        f"{btc_balance_info}\n"
        f"{total_btc_info}\n"
        f"{site_status}\n"
        f"🌐 Мониторинг: {CHECK_URL}"
    )

    await update.message.reply_text(msg)

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

# === Команда /clear (работает в polling и Render) ===
async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет последние сообщения, отправленные ботом"""
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    chat_id = update.effective_chat.id
    bot = context.bot
    deleted = 0

    try:
        # Определим диапазон последних message_id (до 50 назад)
        current_msg_id = update.message.message_id
        for msg_id in range(current_msg_id - 50, current_msg_id):
            try:
                await bot.delete_message(chat_id, msg_id)
                deleted += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass  # пропускаем, если сообщение уже удалено или не принадлежит боту

        await update.message.reply_text(f"🧹 Удалено сообщений: {deleted}")
    except Exception as e:
        await update.message.reply_text(
            f"⚠️ Ошибка при очистке: {e}\n"
            "Совет: попробуй ещё раз через 10–15 секунд."
        )

# === Health-check ===
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
LAST_PURCHASE_FILE = "last_purchase.txt"
CHECK_URL = os.getenv("CHECK_URL", "https://saylortracker.com/")

async def fetch_latest_purchase():
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHECK_URL, timeout=20) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
    except Exception as e:
        write_log(f"⚠️ Ошибка сети: {e}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if not table:
        return None
    rows = table.find_all("tr")
    if len(rows) < 2:
        return None
    cells = [c.get_text(strip=True) for c in rows[1].find_all("td")]
    if len(cells) < 4:
        return None
    date, amount, price, total = cells[0], cells[1], cells[2], cells[3]
    return {"date": date, "amount": amount, "price": price, "total": total}

async def monitor_saylor_purchases(bot: Bot):
    last_date = None
    if os.path.exists(LAST_PURCHASE_FILE):
        with open(LAST_PURCHASE_FILE, "r") as f:
            last_date = f.read().strip()
    write_log(f"🕵️ Мониторинг {CHECK_URL}")
    while True:
        try:
            purchase = await fetch_latest_purchase()
            if purchase and purchase["date"] != last_date:
                msg = (
                    f"💰 *MicroStrategy купила Bitcoin!*\n"
                    f"📅 Дата: {purchase['date']}\n"
                    f"₿ Количество: {purchase['amount']}\n"
                    f"💵 Сумма: {purchase['total']}\n"
                    f"🌐 Источник: {CHECK_URL}"
                )
                await bot.send_message(chat_id=X_CHAT_ID, text=msg, parse_mode="Markdown")
                last_date = purchase["date"]
                with open(LAST_PURCHASE_FILE, "w") as f:
                    f.write(last_date)
            else:
                write_log("ℹ️ Проверка — без изменений")
        except Exception as e:
            write_log(f"⚠️ Ошибка мониторинга: {e}")
        await asyncio.sleep(15 * 60)

# === Автопинг ===
async def ping_alive(bot: Bot):
    while True:
        await asyncio.sleep(6 * 60 * 60)
        uptime = datetime.datetime.now() - start_time
        try:
            await bot.send_message(chat_id=X_CHAT_ID, text=f"✅ Still alive (uptime: {uptime})")
        except Exception as e:
            write_log(f"⚠️ Ошибка авто-пинга: {e}")

# === Post-init ===
async def _post_init(application: Application):
    try:
        # 🔧 Принудительная очистка webhook и любых polling-сессий
        await application.bot.delete_webhook(drop_pending_updates=True)
        write_log("🧹 Telegram webhook и polling-сессии очищены (post_init)")
    except Exception as e:
        write_log(f"⚠️ Ошибка при очистке polling-сессий: {e}")

    # 🔁 Запуск фоновых задач
    application.create_task(start_healthcheck_server())
    application.create_task(monitor_saylor_purchases(application.bot))
    application.create_task(ping_alive(application.bot))

    write_log("🧩 post_init завершён")

# === Команда /site ===
async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🌐 Мониторится сайт:\n{CHECK_URL}")

# === Запуск ===
if __name__ == "__main__":
    request = HTTPXRequest(connection_pool_size=50, read_timeout=30, write_timeout=30)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("site", site))

if __name__ == "__main__":
    asyncio.run(app.run_polling())
