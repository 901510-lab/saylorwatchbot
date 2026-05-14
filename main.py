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

# === Initialization ===
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


# === Commands ===
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import aiohttp

    uptime = datetime.datetime.now() - start_time
    status_msg = f"✅ Bot online\n⏱ Uptime: {uptime}\n"

    last_info = "📊 No recent purchase detected yet (waiting for update)."
    btc_balance_info = "⚠️ Failed to fetch MicroStrategy BTC balance"

    # === Primary source: CoinGecko ===
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status == 200:
                    data = await r.json()
                    for c in data.get("companies", []):
                        if "MicroStrategy" in c.get("name", ""):
                            btc = float(c.get("total_holdings", 0))
                            usd = c.get("total_current_value_usd", "0")
                            avg_price = c.get("total_entry_value_usd", "0")
                            btc_balance_info = (
                                f"🏢 MicroStrategy — Bitcoin Holdings\n"
                                f"💰 {btc} BTC (~${usd})\n"
                                f"📈 Entry value: ${avg_price}\n"
                                f"🟢 Data via CoinGecko"
                            )
                            last_info = "📅 Latest data fetched from CoinGecko"
                            with open("last_purchase.txt", "w") as f:
                                f.write(str(btc))
                            break
                else:
                    raise Exception(f"CoinGecko API response: {r.status}")
    except Exception as e:
        write_log(f"⚠️ CoinGecko error: {e}")
        # === Fallback source: GitHub (Bitcointreasuries) ===
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    "https://raw.githubusercontent.com/bitcointreasuries/bitcointreasuries.github.io/master/_data/companies.json",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r2:
                    if r2.status == 200:
                        data2 = await r2.json()
                        for c in data2:
                            if "MicroStrategy" in c.get("name", ""):
                                btc = c.get("bitcoin", "0")
                                usd = c.get("usd_value", "0")
                                price = c.get("btc_price", "0")
                                btc_balance_info = (
                                    f"🏢 MicroStrategy — Bitcoin Holdings\n"
                                    f"💰 {btc} BTC (~${usd})\n"
                                    f"📈 Avg buy price: ${price}\n"
                                    f"🟡 Data via GitHub/Bitcointreasuries"
                                )
                                last_info = "📅 Fallback data used (CoinGecko unavailable)"
                                break
                    else:
                        btc_balance_info = f"⚠️ Fallback API response: {r2.status}"
        except Exception as e2:
            btc_balance_info = f"⚠️ Fallback fetch error: {type(e2).__name__}"

    msg = (
        f"{status_msg}\n"
        f"{last_info}\n"
        f"{btc_balance_info}\n"
        f"🌐 Monitoring: {CHECK_URL}"
    )

    await update.message.reply_text(msg)


async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    await update.message.reply_text(f"⏱ Uptime: {uptime}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 *Commands:*\n"
        "/start — check bot status\n"
        "/status — show uptime and system info\n"
        "/uptime — show uptime\n"
        "/info — system details\n"
        "/site — show monitored site\n"
        "/clear — delete recent bot messages\n"
        "/restart — restart Render instance (admin only)\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Access denied.")
        return
    commit = os.getenv("RENDER_GIT_COMMIT", "N/A")
    instance = os.getenv("RENDER_INSTANCE_ID", "N/A")
    uptime = datetime.datetime.now() - start_time
    msg = (
        f"🧠 *Bot Information:*\n"
        f"Commit: `{commit}`\n"
        f"Instance: `{instance}`\n"
        f"Uptime: {uptime}\n"
        f"Server Time: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Access denied.")
        return
    await update.message.reply_text("🔄 Restarting Render instance...")
    os._exit(0)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes recent bot messages"""
    if str(update.effective_user.id) != str(X_CHAT_ID):
        await update.message.reply_text("⛔ Access denied.")
        return

    chat_id = update.effective_chat.id
    bot = context.bot
    deleted = 0

    try:
        current_msg_id = update.message.message_id
        for msg_id in range(current_msg_id - 50, current_msg_id):
            try:
                await bot.delete_message(chat_id, msg_id)
                deleted += 1
                await asyncio.sleep(0.1)
            except Exception:
                pass
        await update.message.reply_text(f"🧹 Deleted messages: {deleted}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error clearing messages: {e}")


# === Health check ===
async def handle(request):
    return web.Response(text="✅ SaylorWatchBot is alive")


async def start_healthcheck_server():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    write_log(f"🌐 Health-check server started on port {PORT}")


# === Monitoring ===
LAST_PURCHASE_FILE = "last_purchase.txt"
CHECK_URL = "https://raw.githubusercontent.com/bitcointreasuries/bitcointreasuries.github.io/master/_data/companies.json"


async def fetch_latest_purchase():
    import aiohttp

    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(CHECK_URL, timeout=20) as resp:
                if resp.status != 200:
                    write_log(f"⚠️ API response: {resp.status}")
                    return None

                data = await resp.json()

    except Exception as e:
        write_log(f"⚠️ Network error: {e}")
        return None

    # ищем MicroStrategy / Strategy
    for company in data:
        name = company.get("name", "")

        if "MicroStrategy" in name or "Strategy" in name:
            btc = float(company.get("bitcoin", 0))
            usd = company.get("usd_value", 0)

            return {
                "name": name,
                "btc": btc,
                "usd": usd
            }

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
    write_log(f"🕵️ Monitoring {CHECK_URL}")
    while True:
        try:
            purchase = await fetch_latest_purchase()
            if purchase and purchase["date"] != last_date:
                msg = (
                    f"💰 *MicroStrategy bought Bitcoin!*\n"
                    f"📅 Date: {purchase['date']}\n"
                    f"₿ Amount: {purchase['amount']}\n"
                    f"💵 Total: {purchase['total']}\n"
                    f"🌐 Source: {CHECK_URL}"
                )
                await bot.send_message(chat_id=X_CHAT_ID, text=msg, parse_mode="Markdown")
                last_date = purchase["date"]
                with open(LAST_PURCHASE_FILE, "w") as f:
                    f.write(last_date)
            else:
                write_log("ℹ️ Checked — no updates.")
        except Exception as e:
            write_log(f"⚠️ Monitoring error: {e}")
        await asyncio.sleep(15 * 60)


async def ping_alive(bot: Bot):
    while True:
        await asyncio.sleep(6 * 60 * 60)
        uptime = datetime.datetime.now() - start_time
        try:
            await bot.send_message(chat_id=X_CHAT_ID, text=f"✅ Still alive (uptime: {uptime})")
        except Exception as e:
            write_log(f"⚠️ Auto-ping error: {e}")


async def _post_init(application: Application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        write_log("🧹 Telegram webhook and polling sessions cleared (post_init)")
    except Exception as e:
        write_log(f"⚠️ Polling clear error: {e}")

    application.create_task(start_healthcheck_server())
    application.create_task(monitor_saylor_purchases(application.bot))
    application.create_task(ping_alive(application.bot))

    write_log("🧩 post_init complete")


async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🌐 Monitored website:\n{CHECK_URL}")


if __name__ == "__main__":
    request = HTTPXRequest(connection_pool_size=50, read_timeout=30, write_timeout=30)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(_post_init)
        .build()
    )

    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("site", site))

    asyncio.run(app.run_polling())
