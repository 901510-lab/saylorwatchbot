import asyncio
import datetime
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest

# === Initialization ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))
MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", 15 * 60))
ENABLE_ALIVE_PING = os.environ.get("ENABLE_ALIVE_PING", "false").lower() in {"1", "true", "yes", "on"}

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
start_time = datetime.datetime.now()
last_monitor_check: datetime.datetime | None = None
last_monitor_error: str | None = None

# === Monitoring configuration ===
HOLDINGS_STATE_FILE = Path(os.environ.get("HOLDINGS_STATE_FILE", "last_holdings.json"))
COINGECKO_TREASURY_URL = "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin"
LEGACY_BITCOIN_TREASURIES_URL = "https://raw.githubusercontent.com/bitcointreasuries/bitcointreasuries.github.io/master/_data/companies.json"
CHECK_URL = COINGECKO_TREASURY_URL


def write_log(msg: str):
    print(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}")
    logger.info(msg)


def validate_required_env() -> None:
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not X_CHAT_ID:
        missing.append("X_CHAT_ID")

    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")


def parse_number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value)
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    if not cleaned:
        return 0.0
    return float(cleaned)


def format_btc(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def format_usd(value: float) -> str:
    return f"${value:,.0f}"


def is_strategy_company(name: str) -> bool:
    normalized = name.lower()
    return "microstrategy" in normalized or normalized == "strategy" or "strategy inc" in normalized


def load_holdings_state() -> dict[str, Any] | None:
    if not HOLDINGS_STATE_FILE.exists():
        return None

    try:
        return json.loads(HOLDINGS_STATE_FILE.read_text())
    except json.JSONDecodeError:
        logger.warning("Invalid holdings state file: %s", HOLDINGS_STATE_FILE)
        return None
    except OSError:
        logger.exception("Failed to read holdings state file: %s", HOLDINGS_STATE_FILE)
        return None


def save_holdings_state(holdings: dict[str, Any]) -> None:
    state = {
        "name": holdings["name"],
        "btc": holdings["btc"],
        "usd": holdings.get("usd", 0.0),
        "source": holdings.get("source", CHECK_URL),
        "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    HOLDINGS_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def track_background_task(application: Application, coro, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    application.bot_data.setdefault("background_tasks", set()).add(task)
    task.add_done_callback(application.bot_data["background_tasks"].discard)


async def fetch_json(url: str, timeout_seconds: int = 20) -> Any | None:
    headers = {"User-Agent": "SaylorWatchBot/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as resp:
            if resp.status != 200:
                write_log(f"⚠️ API response from {url}: {resp.status}")
                return None
            return await resp.json()


async def fetch_strategy_holdings_from_legacy_json() -> dict[str, Any] | None:
    try:
        data = await fetch_json(LEGACY_BITCOIN_TREASURIES_URL)
    except Exception as exc:
        logger.exception("Failed to fetch legacy Bitcointreasuries holdings")
        write_log(f"⚠️ Legacy Bitcointreasuries network error: {type(exc).__name__}: {exc}")
        return None

    if data is None:
        return None

    if not isinstance(data, list):
        write_log("⚠️ Unexpected legacy holdings payload: expected a list")
        return None

    for company in data:
        if not isinstance(company, dict):
            continue

        name = str(company.get("name", ""))
        if is_strategy_company(name):
            try:
                return {
                    "name": name,
                    "btc": parse_number(company.get("bitcoin", 0)),
                    "usd": parse_number(company.get("usd_value", 0)),
                    "source": LEGACY_BITCOIN_TREASURIES_URL,
                }
            except ValueError as exc:
                write_log(f"⚠️ Invalid numeric legacy holdings data for {name}: {exc}")
                return None

    write_log("⚠️ Strategy/MicroStrategy record not found in legacy holdings payload")
    return None


async def fetch_coingecko_holdings() -> dict[str, Any] | None:
    try:
        data = await fetch_json(COINGECKO_TREASURY_URL, timeout_seconds=10)
    except Exception as exc:
        write_log(f"⚠️ CoinGecko error: {type(exc).__name__}: {exc}")
        return None

    if not isinstance(data, dict):
        return None

    for company in data.get("companies", []):
        if not isinstance(company, dict):
            continue
        name = str(company.get("name", ""))
        if is_strategy_company(name):
            try:
                return {
                    "name": name,
                    "btc": parse_number(company.get("total_holdings", 0)),
                    "usd": parse_number(company.get("total_current_value_usd", 0)),
                    "entry_value_usd": parse_number(company.get("total_entry_value_usd", 0)),
                    "source": COINGECKO_TREASURY_URL,
                }
            except ValueError as exc:
                write_log(f"⚠️ Invalid CoinGecko data for {name}: {exc}")
                return None

    write_log("⚠️ Strategy/MicroStrategy record not found in CoinGecko payload")
    return None


async def fetch_strategy_holdings() -> dict[str, Any] | None:
    holdings = await fetch_coingecko_holdings()
    if holdings:
        return holdings

    return await fetch_strategy_holdings_from_legacy_json()


# === Commands ===
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    holdings = await fetch_strategy_holdings()

    if holdings:
        source_label = "CoinGecko" if holdings.get("source") == COINGECKO_TREASURY_URL else "GitHub/Bitcointreasuries"
        entry_value = holdings.get("entry_value_usd")
        entry_line = f"\n📈 Entry value: {format_usd(entry_value)}" if entry_value else ""
        btc_balance_info = (
            f"🏢 {holdings['name']} — Bitcoin Holdings\n"
            f"💰 {format_btc(holdings['btc'])} BTC (~{format_usd(holdings.get('usd', 0.0))})"
            f"{entry_line}\n"
            f"🟢 Data via {source_label}"
        )
    else:
        btc_balance_info = "⚠️ Failed to fetch Strategy/MicroStrategy BTC balance"

    state = load_holdings_state()
    state_info = "📊 Monitoring baseline: not recorded yet"
    if state:
        state_info = (
            f"📊 Monitoring baseline: {format_btc(parse_number(state.get('btc', 0)))} BTC "
            f"at {state.get('updated_at', 'unknown time')}"
        )

    monitor_lines = [state_info]
    if last_monitor_check:
        monitor_lines.append(f"🕵️ Last monitor check: {last_monitor_check:%Y-%m-%d %H:%M:%S}")
    if last_monitor_error:
        monitor_lines.append(f"⚠️ Last monitor error: {last_monitor_error}")

    msg = (
        f"✅ Bot online\n"
        f"⏱ Uptime: {uptime}\n\n"
        f"{btc_balance_info}\n"
        f"{'\n'.join(monitor_lines)}\n"
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
        "/status — show uptime, holdings, and monitor info\n"
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
    uptime_value = datetime.datetime.now() - start_time
    msg = (
        f"🧠 *Bot Information:*\n"
        f"Commit: `{commit}`\n"
        f"Instance: `{instance}`\n"
        f"Uptime: {uptime_value}\n"
        f"Monitor interval: {MONITOR_INTERVAL_SECONDS}s\n"
        f"Alive ping enabled: {ENABLE_ALIVE_PING}\n"
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
            except Exception as exc:
                logger.debug("Failed to delete message %s: %s", msg_id, exc)
        await update.message.reply_text(f"🧹 Deleted messages: {deleted}")
    except Exception as exc:
        logger.exception("Failed to clear messages")
        await update.message.reply_text(f"⚠️ Error clearing messages: {exc}")


async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌐 Monitored sources:\n"
        f"Primary: {COINGECKO_TREASURY_URL}\n"
        f"Fallback: {LEGACY_BITCOIN_TREASURIES_URL}"
    )


# === Health check ===
async def handle(request):
    return web.Response(text="✅ SaylorWatchBot is alive")


async def start_healthcheck_server():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    runner = web.AppRunner(app)
    await runner.setup()

    try:
        site = web.TCPSite(runner, "0.0.0.0", PORT)
        await site.start()
        write_log(f"🌐 Health-check server started on port {PORT}")
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
        write_log("🧹 Health-check server stopped")


async def monitor_saylor_purchases(bot: Bot):
    global last_monitor_check, last_monitor_error

    write_log(f"🕵️ Monitoring {COINGECKO_TREASURY_URL} with legacy fallback")
    while True:
        try:
            last_monitor_check = datetime.datetime.now()
            holdings = await fetch_strategy_holdings()
            if not holdings:
                last_monitor_error = "Unable to fetch holdings"
            else:
                previous = load_holdings_state()
                previous_btc = parse_number(previous.get("btc", 0)) if previous else None
                current_btc = holdings["btc"]
                last_monitor_error = None

                if previous_btc is None:
                    save_holdings_state(holdings)
                    write_log(f"📊 Initial holdings baseline saved: {format_btc(current_btc)} BTC")
                elif current_btc > previous_btc:
                    delta = current_btc - previous_btc
                    msg = (
                        "💰 Strategy/MicroStrategy BTC holdings increased!\n"
                        f"₿ Previous: {format_btc(previous_btc)} BTC\n"
                        f"₿ Current: {format_btc(current_btc)} BTC\n"
                        f"➕ Change: {format_btc(delta)} BTC\n"
                        f"💵 Current value: {format_usd(holdings.get('usd', 0.0))}\n"
                        f"🌐 Source: {holdings.get('source', CHECK_URL)}"
                    )
                    await bot.send_message(chat_id=X_CHAT_ID, text=msg)
                    save_holdings_state(holdings)
                    write_log(f"🚨 Holdings increase detected: +{format_btc(delta)} BTC")
                elif current_btc != previous_btc:
                    save_holdings_state(holdings)
                    write_log(
                        f"📉 Holdings changed without increase: {format_btc(previous_btc)} -> "
                        f"{format_btc(current_btc)} BTC"
                    )
                else:
                    write_log("ℹ️ Checked — no updates.")
        except Exception as exc:
            last_monitor_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Monitoring error")
            write_log(f"⚠️ Monitoring error: {last_monitor_error}")

        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)


async def ping_alive(bot: Bot):
    while True:
        await asyncio.sleep(6 * 60 * 60)
        uptime_value = datetime.datetime.now() - start_time
        try:
            await bot.send_message(chat_id=X_CHAT_ID, text=f"✅ Still alive (uptime: {uptime_value})")
        except Exception as exc:
            logger.exception("Auto-ping error")
            write_log(f"⚠️ Auto-ping error: {exc}")


async def _post_init(application: Application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        write_log("🧹 Telegram webhook and polling sessions cleared (post_init)")
    except Exception as exc:
        logger.exception("Polling clear error")
        write_log(f"⚠️ Polling clear error: {exc}")

    track_background_task(application, start_healthcheck_server(), "healthcheck-server")
    track_background_task(application, monitor_saylor_purchases(application.bot), "holdings-monitor")
    if ENABLE_ALIVE_PING:
        track_background_task(application, ping_alive(application.bot), "alive-ping")

    write_log("🧩 post_init complete")


async def _post_shutdown(application: Application):
    tasks = application.bot_data.get("background_tasks", set())
    for task in tasks:
        task.cancel()

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
        write_log("🧹 Background tasks stopped")


if __name__ == "__main__":
    validate_required_env()

    request = HTTPXRequest(connection_pool_size=50, read_timeout=30, write_timeout=30)
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .request(request)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", status))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("site", site))

    app.run_polling()
