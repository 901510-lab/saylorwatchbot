import os
import asyncio
import logging
import datetime
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from aiohttp import web
from telegram.request import HTTPXRequest
import json
import aiohttp

# === Initialization ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
CHECK_URL = os.getenv("CHECK_URL", "https://saylortracker.com/")
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN or ":" not in BOT_TOKEN:
    print("❌ BOT_TOKEN missing or invalid!"); raise SystemExit(1)
if not X_CHAT_ID or not X_CHAT_ID.isdigit():
    print("❌ X_CHAT_ID missing or invalid!"); raise SystemExit(1)

print("✅ Environment loaded successfully.")
print(f"🌐 CHECK_URL = {CHECK_URL}")
print(f"🧠 CHAT_ID = {X_CHAT_ID}")

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("SaylorWatchBot")
start_time = datetime.datetime.now()

def log(msg: str):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
    logger.info(msg)

# === Safe reply helper ===
async def safe_reply(update: Update, text: str):
    # Работаем даже если update.message отсутствует (канал/форум)
    chat = update.effective_chat
    if chat:
        try:
            await update.get_bot().send_message(chat_id=chat.id, text=text)
        except Exception as e:
            log(f"⚠️ Failed to reply: {e}")
    else:
        log("⚠️ No effective_chat to reply into.")

# === Debug middlewares ===
async def log_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Подцепим как самый первый хендлер (type-agnostic)
    uid = update.effective_user.id if update.effective_user else "unknown"
    chat_id = update.effective_chat.id if update.effective_chat else "nochat"
    kind = update.effective_update_type
    logger.info(f"📨 Update: type={kind}, from={uid}, chat={chat_id}")

# === Commands ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await safe_reply(update, "👋 Hello! Bot is active and running 24/7 🚀")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    await safe_reply(update, f"🏓 Pong! Uptime: {uptime}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log("🧩 /status command received")
    uptime = datetime.datetime.now() - start_time
    status_msg = f"✅ Bot online\n⏱ Uptime: {uptime}\n"

    # Last purchase
    last_info = "📊 No recent purchase detected yet (waiting for update)."
    try:
        if os.path.exists("last_purchase.txt"):
            with open("last_purchase.txt", "r") as f:
                last_date = f.read().strip()
                if last_date:
                    last_info = f"📅 Last recorded purchase: {last_date}"
    except Exception as e:
        log(f"⚠️ last_purchase read error: {e}")

    # Site availability
    site_status = "❌ Connection error"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(CHECK_URL, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                site_status = "✅ Website is reachable" if resp.status == 200 else f"⚠️ Website response: {resp.status}"
    except asyncio.TimeoutError:
        site_status = "⚠️ Website timeout"
    except Exception as e:
        site_status = f"⚠️ Error: {type(e).__name__}"

    # MicroStrategy balance (multi-source)
    cache_file = "mstr_balance_cache.json"
    btc_balance_info = "⚠️ Failed to fetch MicroStrategy BTC balance"
    cache_valid = False
    cache_time_str = "unknown"
    data_source = "❌ None"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; SaylorWatchBot/1.0)"}

    # cache
    try:
        if os.path.exists(cache_file):
            cache_mtime = datetime.datetime.fromtimestamp(os.path.getmtime(cache_file))
            if (datetime.datetime.now() - cache_mtime).total_seconds() < 24 * 3600:
                with open(cache_file, "r") as f:
                    cached = json.load(f)
                btc_balance_info = (
                    f"💰 MicroStrategy balance: {cached.get('btc','?')} BTC (~${cached.get('usd','?')})\n"
                    f"📈 Average buy price: ${cached.get('price','?')} (cached)"
                )
                cache_valid = True
                data_source = "💾 Cache"
                cache_time_str = cache_mtime.strftime("%Y-%m-%d %H:%M")
    except Exception as e:
        log(f"⚠️ Cache read error: {e}")

    async def try_fetch(url, pick_fn, source_tag):
        nonlocal btc_balance_info, cache_valid, cache_time_str, data_source
        try:
            async with aiohttp.ClientSession(headers=headers) as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                    if r.status == 200:
                        data = await r.json()
                        picked = pick_fn(data)
                        if picked:
                            btc, usd, price = picked
                            btc_balance_info = (
                                f"💰 MicroStrategy balance: {btc} BTC (~${usd})\n"
                                f"📈 Avg/Entry price: ${price}\n"
                                f"{source_tag}"
                            )
                            try:
                                with open(cache_file, "w") as f:
                                    json.dump({"btc": btc, "usd": usd, "price": price}, f)
                            except Exception as ee:
                                log(f"⚠️ Cache write error: {ee}")
                            cache_valid = True
                            cache_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                            data_source = source_tag
                            return True
                    else:
                        log(f"⚠️ {source_tag} status {r.status}")
        except asyncio.TimeoutError:
            log(f"⚠️ {source_tag} timeout")
        except Exception as e:
            log(f"⚠️ {source_tag} error: {e}")
        return False

    if not cache_valid:
        # 1) CoinGecko
        await try_fetch(
            "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin",
            lambda data: next(
                (
                    (c.get("total_holdings","0"), c.get("total_current_value_usd","0"), c.get("total_entry_value_usd","0"))
                    for c in data.get("companies", [])
                    if "MicroStrategy" in c.get("name","")
                ),
                None,
            ),
            "🟢 Source: CoinGecko"
        )

    if not cache_valid:
        # 2) GitHub
        await try_fetch(
            "https://raw.githubusercontent.com/coinforensics/bitcointreasuries/master/docs/companies.json",
            lambda data: next(
                (
                    (c.get("bitcoin","0"), c.get("usd_value","0"), c.get("btc_price","0"))
                    for c in (data if isinstance(data, list) else data.get("companies", []))
                    if "MicroStrategy" in c.get("name","")
                ),
                None,
            ),
            "🟡 Source: GitHub"
        )

    if not cache_valid:
        # 3) CoinMarketCap
        await try_fetch(
            "https://api.coinmarketcap.com/data-api/v3/company/all?convert=USD",
            lambda data: next(
                (
                    (c.get("total_holdings","0"), c.get("total_value_usd","0"), c.get("average_buy_price","0"))
                    for c in data.get("data", {}).get("companyHoldings", [])
                    if "MicroStrategy" in c.get("name","")
                ),
                None,
            ),
            "🔵 Source: CoinMarketCap"
        )

    if not cache_valid:
        # 4) BitcoinTreasuries x2
        for attempt in range(2):
            ok = await try_fetch(
                "https://bitcointreasuries.net/api/data",
                lambda data: next(
                    (
                        (c.get("BTC","0"), c.get("USDValue","0"), c.get("BTCPrice","0"))
                        for c in data.get("data", [])
                        if "MicroStrategy" in c.get("Company","")
                    ),
                    None,
                ),
                "🟣 Source: BitcoinTreasuries.net"
            )
            if ok:
                break
            await asyncio.sleep(2)

    msg = (
        f"{status_msg}\n"
        f"{last_info}\n"
        f"{btc_balance_info}\n"
        f"🕒 Cache updated: {cache_time_str}\n"
        f"✅ Data source: {data_source}\n"
        f"{site_status}\n"
        f"🌐 Monitoring: {CHECK_URL}"
    )
    await safe_reply(update, msg)

async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ловим неизвестные команды, чтобы видеть, что апдейты доходят
    txt = update.message.text if update.message else "<no message>"
    await safe_reply(update, f"🤔 Unknown command: {txt}\nTry /ping or /status")

# === Entry point ===
async def main():
    log("🚀 Starting SaylorWatchBot...")

    app = Application.builder().token(BOT_TOKEN).build()

    # Принудительно убираем webhook (важно для polling!)
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        log("🧹 Webhook deleted, pending updates dropped.")
    except Exception as e:
        log(f"⚠️ delete_webhook error: {e}")

    # Handlers: сначала логгер апдейтов, затем команды
    app.add_handler(MessageHandler(filters.ALL, log_update), group=-1000)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))  # неизвестные команды

    # Healthcheck server for Render
    async def handle_root(request): return web.Response(text="✅ SaylorWatchBot running")
    web_app = web.Application()
    web_app.router.add_get("/", handle_root)
    web_app.router.add_get("/health", handle_root)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log(f"🌍 Healthcheck server running on port {PORT}")

    # Уведомление о старте
    try:
        bot = Bot(token=BOT_TOKEN, request=HTTPXRequest())
        await bot.send_message(chat_id=int(X_CHAT_ID), text="✅ SaylorWatchBot restarted and is now running.")
    except Exception as e:
        log(f"⚠️ Startup notify failed: {e}")

    # Polling
    await app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)

# ==== Render-safe launcher ====
if __name__ == "__main__":
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(main())
        loop.run_forever()
    except KeyboardInterrupt:
        print("🛑 Bot stopped manually.")
    except Exception as e:
        print(f"❌ Startup error: {e}")
