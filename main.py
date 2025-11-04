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
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hello! Bot is active and running 24/7 🚀")

# === /status COMMAND WITH MULTI-SOURCE FALLBACK ===
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import aiohttp

    uptime = datetime.datetime.now() - start_time
    status_msg = f"✅ Bot online\n⏱ Uptime: {uptime}\n"

    # === 1️⃣ Last purchase check ===
    last_info = "📊 No recent purchase detected yet (waiting for update)."
    if os.path.exists("last_purchase.txt"):
        with open("last_purchase.txt", "r") as f:
            last_date = f.read().strip()
            if last_date:
                last_info = f"📅 Last recorded purchase: {last_date}"

    # === 2️⃣ Site availability ===
    site_status = "❌ Connection error"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHECK_URL, timeout=10) as resp:
                if resp.status == 200:
                    site_status = "✅ Website is reachable"
                else:
                    site_status = f"⚠️ Website response: {resp.status}"
    except Exception as e:
        site_status = f"⚠️ Error: {type(e).__name__}"

    # === 3️⃣ MicroStrategy BTC balance (4-level fallback chain) ===
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

    # --- 2️⃣ GitHub fallback ---
    if not cache_valid:
        try:
            url = "https://raw.githubusercontent.com/coinforensics/bitcointreasuries/master/docs/companies.json"
            async with aiohttp.ClientSession(headers=headers) as s:
                async with s.get(url, timeout=15) as r:
                    if r.status == 200:
                        data = await r.json()
                        items = data if isinstance(data, list) else data.get("companies", [])
                        for c in items:
                            if "MicroStrategy" in c.get("name", ""):
                                btc = c.get("bitcoin", "0")
                                usd = c.get("usd_value", "0")
                                price = c.get("btc_price", "0")
                                btc_balance_info = (
                                    f"💰 MicroStrategy balance: {btc} BTC (~${usd})\n"
                                    f"📈 Avg buy price: ${price}\n"
                                    f"🟡 Source: GitHub"
                                )
                                data_source = "🟡 GitHub"
                                with open(cache_file, "w") as f:
                                    json.dump({"btc": btc, "usd": usd, "price": price}, f)
                                cache_valid = True
                                cache_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                                break
                    else:
                        write_log(f"⚠️ GitHub status {r.status}")
        except Exception as e:
            write_log(f"⚠️ GitHub error: {e}")

    # --- 3️⃣ CoinMarketCap ---
    if not cache_valid:
        try:
            url = "https://api.coinmarketcap.com/data-api/v3/company/all?convert=USD"
            async with aiohttp.ClientSession(headers=headers) as s:
                async with s.get(url, timeout=15) as r:
                    if r.status == 200:
                        data = await r.json()
                        for c in data.get("data", {}).get("companyHoldings", []):
                            if "MicroStrategy" in c.get("name", ""):
                                btc = c.get("total_holdings", "0")
                                usd = c.get("total_value_usd", "0")
                                avg = c.get("average_buy_price", "0")
                                btc_balance_info = (
                                    f"💰 MicroStrategy balance: {btc} BTC (~${usd})\n"
                                    f"📈 Avg buy price: ${avg}\n"
                                    f"🔵 Source: CoinMarketCap"
                                )
                                data_source = "🔵 CoinMarketCap"
                                with open(cache_file, "w") as f:
                                    json.dump({"btc": btc, "usd": usd, "price": avg}, f)
                                cache_valid = True
                                cache_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                                break
                    else:
                        write_log(f"⚠️ CMC status {r.status}")
        except Exception as e:
            write_log(f"⚠️ CoinMarketCap error: {e}")

    # --- 4️⃣ BitcoinTreasuries.net ---
    if not cache_valid:
        for attempt in range(2):
            try:
                url = "https://bitcointreasuries.net/api/data"
                async with aiohttp.ClientSession(headers=headers) as s:
                    async with s.get(url, timeout=20) as r:
                        if r.status == 200:
                            data = await r.json()
                            rows = data.get("data", [])
                            for c in rows:
                                if "MicroStrategy" in c.get("Company", ""):
                                    btc = c.get("BTC", "0")
                                    usd = c.get("USDValue", "0")
                                    avg = c.get("BTCPrice", "0")
                                    btc_balance_info = (
                                        f"💰 MicroStrategy balance: {btc} BTC (~${usd})\n"
                                        f"📈 Avg buy price: ${avg}\n"
                                        f"🟣 Source: BitcoinTreasuries.net"
                                    )
                                    data_source = "🟣 BitcoinTreasuries"
                                    with open(cache_file, "w") as f:
                                        json.dump({"btc": btc, "usd": usd, "price": avg}, f)
                                    cache_valid = True
                                    cache_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                                    break
                        else:
                            write_log(f"⚠️ BitcoinTreasuries status {r.status}")
                if cache_valid:
                    break
                await asyncio.sleep(3)
            except Exception as e:
                write_log(f"⚠️ BitcoinTreasuries attempt {attempt+1} error: {e}")

    # === Combine & send ===
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

# === Other Commands, Healthcheck, Monitor, etc. (без изменений) ===
# (оставлены те же функции uptime, help_command, info, restart, clear, handle, start_healthcheck_server,
#  fetch_latest_purchase, monitor_saylor_purchases, ping_alive, _post_init, site, main block)
