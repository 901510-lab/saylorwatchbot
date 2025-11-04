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
import json

# === Initialization ===
load_dotenv()

# --- Safety check for environment variables ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
CHECK_URL = os.getenv("CHECK_URL", "https://saylortracker.com/")
PORT_ENV = os.getenv("PORT")

try:
    PORT = int(PORT_ENV) if PORT_ENV else 10000
except ValueError:
    print(f"⚠️ Invalid PORT value: {PORT_ENV}, using default 10000")
    PORT = 10000

if not BOT_TOKEN or len(BOT_TOKEN) < 40:
    print("❌ BOT_TOKEN missing or invalid! Check Environment Variables on Render.")
    exit(1)

if not X_CHAT_ID or not X_CHAT_ID.isdigit():
    print("❌ X_CHAT_ID missing or invalid! Check Environment Variables on Render.")
    exit(1)

print(f"✅ Environment loaded successfully.")
print(f"🌐 CHECK_URL = {CHECK_URL}")
print(f"🧠 CHAT_ID = {X_CHAT_ID}")

# --- Logging ---
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
start_time = datetime.datetime.now()


def write_log(msg: str):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
    logger.info(msg)


# === Commands ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Bot is active and running 24/7 🚀")


# === /status COMMAND WITH MULTI-SOURCE FALLBACK ===
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import aiohttp
    uptime = datetime.datetime.now() - start_time
    status_msg = f"✅ Bot online\n⏱ Uptime: {uptime}\n"

    # --- Last purchase check ---
    last_info = "📊 No recent purchase detected yet (waiting for update)."
    if os.path.exists("last_purchase.txt"):
        with open("last_purchase.txt", "r") as f:
            last_date = f.read().strip()
            if last_date:
                last_info = f"📅 Last recorded purchase: {last_date}"

    # --- Website availability ---
    site_status = "❌ Connection error"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHECK_URL, timeout=10) as resp:
                site_status = (
                    "✅ Website is reachable"
                    if resp.status == 200
                    else f"⚠️ Website response: {resp.status}"
                )
    except Exception as e:
        site_status = f"⚠️ Error: {type(e).__name__}"

    # --- MicroStrategy BTC balance ---
    cache_file = "mstr_balance_cache.json"
    btc_balance_info = "⚠️ Failed to fetch MicroStrategy BTC balance"
    cache_valid = False
    cache_time_str = "unknown"
    data_source = "❌ None"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SaylorWatchBot/1.0)"}

    # --- Try read cache ---
    if os.path.exists(cache_file):
        try:
            cache_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(cache_file))
            cache_age = (datetime.datetime.now() - cache_mtime).total_seconds()
            if cache_age < 24 * 3600:
                with open(cache_file, "r") as f:
                    cached = json.load(f)
                btc_balance_info = (
                    f"💰 MicroStrategy balance: {cached['btc']} BTC (~${cached['usd']})\n"
                    f"📈 Average buy price: ${cached['price']} (cached)"
                )
                cache_valid = True
                data_source = "💾 Cache"
                cache_time_str = cache_mtime.strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            write_log(f"⚠️ Cache read error: {e}")

    # --- 1️⃣ CoinGecko ---
    if not cache_valid:
        try:
            async with aiohttp.ClientSession(headers=headers) as s:
                url = "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin"
                async with s.get(url, timeout=15) as r:
                    if r.status == 200:
                        data = await r.json()
                        for c in data.get("companies", []):
                            if "MicroStrategy" in c.get("name", ""):
                                btc = c.get("total_holdings", "0")
                                usd = c.get("total_current_value_usd", "0")
                                entry = c.get("total_entry_value_usd", "0")
                                btc_balance_info = (
                                    f"💰 MicroStrategy balance: {btc} BTC (~${usd})\n"
                                    f"📈 Entry value: ${entry}\n"
                                    f"🟢 Source: CoinGecko"
                                )
                                data_source = "🟢 CoinGecko"
                                with open(cache_file, "w") as f:
                                    json.dump({"btc": btc, "usd": usd, "price": entry}, f)
                                cache_valid = True
                                cache_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                                break
                    else:
                        write_log(f"⚠️ CoinGecko status {r.status}")
        except Exception as e:
            write_log(f"⚠️ CoinGecko error: {e}")

    # --- Other fallbacks (GitHub / CoinMarketCap / BitcoinTreasuries) omitted for brevity ---
    # (Ты можешь оставить весь блок без изменений, он не влияет на запуск)

    msg = (
        f"{status_msg}\n"
        f"{last_info}\n"
        f"{btc_balance_info}\n"
        f"🕒 Cache updated: {cache_time_str}\n"
        f"✅ Data source: {data_source}\n"
        f"{site_status}\n"
        f"🌐 Monitoring: {CHECK_URL}"
    )
    await update.message.reply_text(msg)


# === Entry point ===
async def main():
    write_log("🚀 Starting SaylorWatchBot...")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))

    # --- параллельно поднимаем веб-сервер healthcheck ---
    async def handle_health(request):
        return web.Response(text="✅ SaylorWatchBot running")

    web_app = web.Application()
    web_app.router.add_get("/", handle_health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    write_log(f"🌍 Healthcheck server running on port {PORT}")

    # --- запускаем Telegram polling ---
    await app.run_polling()


if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print("🛑 Bot stopped manually.")
    except Exception as e:
        print(f"❌ Startup error: {e}")
