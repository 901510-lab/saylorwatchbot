import asyncio
import datetime
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from telegram import Bot, BotCommand, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

BOT_VERSION = "2026-05-24.3"

# === Initialization ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))
MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", 15 * 60))
ENABLE_ALIVE_PING = os.environ.get("ENABLE_ALIVE_PING", "false").lower() in {"1", "true", "yes", "on"}
MIN_BTC_CHANGE = float(os.environ.get("MIN_BTC_CHANGE", "1"))
ENABLE_STRATEGY_SITE = os.environ.get("ENABLE_STRATEGY_SITE", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}

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
STRATEGY_SITE_BASE = "https://www.strategy.com"
STRATEGY_PURCHASES_PATH = "/purchases"
STRATEGY_PRESS_PATH = "/press"
STRATEGY_SITE_STATE_FILE = Path(os.environ.get("STRATEGY_SITE_STATE_FILE", "last_strategy_site.json"))
STRATEGY_SITE_USER_AGENT = "Mozilla/5.0 (compatible; SaylorWatchBot/1.0)"
BTC_PRESS_KEYWORDS = (
    "bitcoin",
    "btc",
    "acquire",
    "acquired",
    "purchase",
    "purchased",
    "holdings",
    "hodl",
    "sale",
    "sold",
    "dispose",
)

# English menu (reply keyboard + /commands)
BTN_STATUS = "📊 Status"
BTN_CHECK = "🔄 Check now"
BTN_BUY_CHECK = "💰 Purchase check"
BTN_SELL_CHECK = "📉 Sale check"
BTN_BASELINE = "📌 Reset baseline"
BTN_HELP = "❓ Help"
BTN_HIDE_MENU = "⌨️ Hide menu"

BOT_COMMANDS = [
    BotCommand("start", "Open menu and show status"),
    BotCommand("status", "Strategy BTC balance & baseline"),
    BotCommand("check", "Run treasury check now"),
    BotCommand("checkbuy", "Test purchase alert (admin)"),
    BotCommand("checksell", "Test sale alert (admin)"),
    BotCommand("baseline", "Reset baseline to live data"),
    BotCommand("testalert", "Test notification delivery"),
    BotCommand("chatid", "Show your Telegram ID"),
    BotCommand("help", "Help and menu"),
    BotCommand("site", "Latest data from strategy.com"),
]

MENU_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton(BTN_STATUS), KeyboardButton(BTN_CHECK)],
        [KeyboardButton(BTN_BUY_CHECK), KeyboardButton(BTN_SELL_CHECK)],
        [KeyboardButton(BTN_BASELINE), KeyboardButton(BTN_HELP)],
        [KeyboardButton(BTN_HIDE_MENU)],
    ],
    resize_keyboard=True,
)


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


def alert_chat_id() -> int:
    return int(str(X_CHAT_ID).strip())


def is_admin(user_id: int | None, chat_id: int | None = None) -> bool:
    target = str(X_CHAT_ID).strip()
    if user_id is not None and str(user_id) == target:
        return True
    if chat_id is not None and str(chat_id) == target:
        return True
    return False


async def deny_admin(update: Update) -> None:
    await update.message.reply_text(
        "⛔ Команда только для админа.\n"
        f"Ваш User ID: {update.effective_user.id}\n"
        f"X_CHAT_ID на сервере: {X_CHAT_ID}\n"
        "Они должны совпадать. Узнайте ID: /chatid"
    )


async def setup_bot_menu(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)


async def validate_alert_target(bot: Bot) -> None:
    target = alert_chat_id()
    me = await bot.get_me()
    if target == me.id:
        raise RuntimeError(
            "X_CHAT_ID совпадает с ID бота. Укажите ваш личный chat id: напишите боту /chatid "
            "и поставьте это число в X_CHAT_ID на хостинге."
        )


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


async def fetch_strategy_html(path: str) -> str | None:
    url = f"{STRATEGY_SITE_BASE}{path}"
    headers = {"User-Agent": STRATEGY_SITE_USER_AGENT}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
                if resp.status != 200:
                    write_log(f"⚠️ Strategy.com response {path}: {resp.status}")
                    return None
                return await resp.text()
    except Exception as exc:
        write_log(f"⚠️ Strategy.com network error {path}: {type(exc).__name__}: {exc}")
        return None


def parse_strategy_next_data(html: str) -> dict[str, Any] | None:
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html,
        re.S,
    )
    if not match:
        write_log("⚠️ Strategy.com: __NEXT_DATA__ not found")
        return None
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        write_log("⚠️ Strategy.com: invalid __NEXT_DATA__ JSON")
        return None


def is_btc_related_press(title: str) -> bool:
    normalized = title.lower()
    return any(keyword in normalized for keyword in BTC_PRESS_KEYWORDS)


def load_strategy_site_state() -> dict[str, Any]:
    if not STRATEGY_SITE_STATE_FILE.exists():
        return {}
    try:
        return json.loads(STRATEGY_SITE_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid strategy site state file: %s", STRATEGY_SITE_STATE_FILE)
        return {}


def save_strategy_site_state(state: dict[str, Any]) -> None:
    STRATEGY_SITE_STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def parse_strategy_purchases(next_data: dict[str, Any]) -> dict[str, Any] | None:
    rows = next_data.get("props", {}).get("pageProps", {}).get("bitcoinData")
    if not isinstance(rows, list) or not rows:
        return None

    latest_row = rows[-1]
    acquisitions = [row for row in rows if parse_number(row.get("count", 0)) > 0]
    latest_acquisition = acquisitions[-1] if acquisitions else None

    btc_nav = parse_number(latest_row.get("btc_nav", 0))
    usd_estimate = btc_nav * 1_000_000 if btc_nav else 0.0

    snapshot: dict[str, Any] = {
        "btc_holdings": parse_number(latest_row.get("btc_holdings", 0)),
        "usd_estimate": usd_estimate,
        "as_of_date": str(latest_row.get("date_of_purchase", "")),
        "latest_row_uid": str(latest_row.get("uid", "")),
    }
    if latest_acquisition:
        snapshot["latest_acquisition"] = {
            "uid": str(latest_acquisition.get("uid", "")),
            "date": str(latest_acquisition.get("date_of_purchase", "")),
            "count": parse_number(latest_acquisition.get("count", 0)),
            "price": parse_number(latest_acquisition.get("purchase_price", 0)),
            "btc_holdings": parse_number(latest_acquisition.get("btc_holdings", 0)),
            "title": str(latest_acquisition.get("title", "")),
        }
    return snapshot


def parse_strategy_press(next_data: dict[str, Any]) -> dict[str, str] | None:
    releases = next_data.get("props", {}).get("pageProps", {}).get("releaseList")
    if not isinstance(releases, list) or not releases:
        return None

    latest = releases[0]
    title = str(latest.get("display_title") or latest.get("title") or "").strip()
    url = str(latest.get("url") or "").strip()
    if url and not url.startswith("http"):
        url = f"{STRATEGY_SITE_BASE}{url}"

    return {
        "uid": str(latest.get("uid", "")),
        "title": title or "Strategy press release",
        "url": url,
        "date": str(latest.get("publication_date", "")),
    }


async def fetch_strategy_site_snapshot() -> dict[str, Any] | None:
    purchases_html = await fetch_strategy_html(STRATEGY_PURCHASES_PATH)
    if not purchases_html:
        return None

    purchases_data = parse_strategy_next_data(purchases_html)
    if not purchases_data:
        return None

    snapshot = parse_strategy_purchases(purchases_data)
    if not snapshot:
        return None

    press_html = await fetch_strategy_html(STRATEGY_PRESS_PATH)
    if press_html:
        press_data = parse_strategy_next_data(press_html)
        if press_data:
            press = parse_strategy_press(press_data)
            if press:
                snapshot["latest_press"] = press

    snapshot["source"] = f"{STRATEGY_SITE_BASE}{STRATEGY_PURCHASES_PATH}"
    return snapshot


async def fetch_strategy_site_holdings() -> dict[str, Any] | None:
    snapshot = await fetch_strategy_site_snapshot()
    if not snapshot:
        return None

    return {
        "name": "Strategy",
        "btc": snapshot["btc_holdings"],
        "usd": snapshot.get("usd_estimate", 0.0),
        "source": snapshot["source"],
        "site_snapshot": snapshot,
    }


def format_site_acquisition_alert(acquisition: dict[str, Any]) -> str:
    return (
        "🏢 Strategy.com — BTC purchase reported\n"
        f"Date: {acquisition.get('date', 'n/a')}\n"
        f"Acquired: {format_btc(parse_number(acquisition.get('count', 0)))} BTC\n"
        f"Price: {format_usd(parse_number(acquisition.get('price', 0)))}\n"
        f"Total holdings: {format_btc(parse_number(acquisition.get('btc_holdings', 0)))} BTC\n"
        f"Source: {STRATEGY_SITE_BASE}{STRATEGY_PURCHASES_PATH}"
    )


def format_site_press_alert(press: dict[str, str]) -> str:
    lines = [
        "📰 Strategy.com — new press release",
        press.get("title", "Press release"),
    ]
    if press.get("date"):
        lines.append(f"Date: {press['date']}")
    if press.get("url"):
        lines.append(press["url"])
    return "\n".join(lines)


async def run_strategy_site_check(bot: Bot, *, initialize_only: bool = False) -> str | None:
    if not ENABLE_STRATEGY_SITE:
        return None

    snapshot = await fetch_strategy_site_snapshot()
    if not snapshot:
        return "Strategy.com unavailable"

    state = load_strategy_site_state()
    if not state:
        save_strategy_site_state(
            {
                "last_press_uid": snapshot.get("latest_press", {}).get("uid"),
                "last_acquisition_uid": snapshot.get("latest_acquisition", {}).get("uid"),
                "last_site_btc": snapshot.get("btc_holdings"),
                "initialized_at": datetime.datetime.now(datetime.UTC).isoformat(),
            }
        )
        return "Strategy.com monitor initialized (no alerts on first run)"

    notes: list[str] = []

    press = snapshot.get("latest_press")
    if press:
        press_uid = press.get("uid")
        if press_uid and press_uid != state.get("last_press_uid") and is_btc_related_press(press.get("title", "")):
            if not initialize_only:
                await send_holdings_alert(bot, format_site_press_alert(press))
            notes.append("new BTC press release on strategy.com")
            state["last_press_uid"] = press_uid

    acquisition = snapshot.get("latest_acquisition")
    if acquisition:
        acq_uid = acquisition.get("uid")
        acq_count = parse_number(acquisition.get("count", 0))
        if acq_uid and acq_uid != state.get("last_acquisition_uid") and acq_count >= MIN_BTC_CHANGE:
            if not initialize_only:
                await send_holdings_alert(bot, format_site_acquisition_alert(acquisition))
                site_holdings = await fetch_strategy_site_holdings()
                if site_holdings:
                    save_holdings_state(site_holdings)
            notes.append(f"new purchase on strategy.com (+{format_btc(acq_count)} BTC)")
            state["last_acquisition_uid"] = acq_uid

    state["last_site_btc"] = snapshot.get("btc_holdings")
    if press and press.get("uid"):
        state.setdefault("last_press_uid", press["uid"])
    if acquisition and acquisition.get("uid"):
        state.setdefault("last_acquisition_uid", acquisition["uid"])
    save_strategy_site_state(state)

    return "; ".join(notes) if notes else None


async def fetch_strategy_holdings() -> dict[str, Any] | None:
    if ENABLE_STRATEGY_SITE:
        site_holdings = await fetch_strategy_site_holdings()
        if site_holdings:
            return site_holdings

    holdings = await fetch_coingecko_holdings()
    if holdings:
        return holdings

    return await fetch_strategy_holdings_from_legacy_json()


def format_holdings_alert(previous_btc: float, holdings: dict[str, Any], delta: float, increased: bool) -> str:
    action = "закупка" if increased else "продажа"
    sign = "+" if increased else "−"
    return (
        f"{'💰' if increased else '📉'} Strategy — {action} BTC\n"
        f"Было: {format_btc(previous_btc)} BTC\n"
        f"Сейчас: {format_btc(holdings['btc'])} BTC\n"
        f"Изменение: {sign}{format_btc(abs(delta))} BTC\n"
        f"Оценка: {format_usd(holdings.get('usd', 0.0))}"
    )


async def send_holdings_alert(bot: Bot, text: str) -> None:
    await bot.send_message(chat_id=alert_chat_id(), text=text)


async def run_holdings_check(bot: Bot) -> str:
    """One monitoring cycle. Returns a short status message for logs or /check."""
    global last_monitor_check, last_monitor_error

    last_monitor_check = datetime.datetime.now()
    holdings = await fetch_strategy_holdings()
    if not holdings:
        last_monitor_error = "Не удалось получить данные (strategy.com / CoinGecko)"
        return last_monitor_error

    previous = load_holdings_state()
    previous_btc = parse_number(previous.get("btc", 0)) if previous else None
    current_btc = holdings["btc"]
    last_monitor_error = None

    if previous_btc is None:
        save_holdings_state(holdings)
        write_log(f"📊 Baseline сохранён: {format_btc(current_btc)} BTC")
        return f"Сохранён baseline: {format_btc(current_btc)} BTC"

    delta = current_btc - previous_btc
    if abs(delta) < MIN_BTC_CHANGE:
        write_log("ℹ️ Проверка — без значимых изменений.")
        return (
            f"Изменений нет. Сейчас {format_btc(current_btc)} BTC, "
            f"baseline {format_btc(previous_btc)} BTC (порог {MIN_BTC_CHANGE} BTC)."
        )

    if delta > 0:
        await send_holdings_alert(bot, format_holdings_alert(previous_btc, holdings, delta, increased=True))
        save_holdings_state(holdings)
        write_log(f"🚨 Закупка: +{format_btc(delta)} BTC")
        return f"Алерт закупки отправлен: +{format_btc(delta)} BTC"

    await send_holdings_alert(bot, format_holdings_alert(previous_btc, holdings, delta, increased=False))
    save_holdings_state(holdings)
    write_log(f"🚨 Продажа: {format_btc(delta)} BTC")
    return f"Алерт продажи отправлен: {format_btc(delta)} BTC"


# === Commands ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "SaylorWatchBot monitors Strategy (MicroStrategy) BTC treasury.\n\n"
        "• Alerts when holdings increase (purchase) or decrease (sale)\n"
        "• Primary source: strategy.com purchases page\n"
        "• Fallback: CoinGecko public treasury API\n"
        "• Also: new BTC-related press releases on strategy.com\n\n"
        "Use the buttons below or type /help.\n"
        f"Build: {BOT_VERSION}",
        reply_markup=MENU_KEYBOARD,
    )
    await status(update, context, show_menu=False)


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    show_menu: bool = True,
):
    uptime = datetime.datetime.now() - start_time
    holdings = await fetch_strategy_holdings()

    if holdings:
        source_label = "strategy.com" if "strategy.com" in str(holdings.get("source", "")) else "CoinGecko"
        btc_balance_info = (
            f"🏢 {holdings['name']}\n"
            f"💰 {format_btc(holdings['btc'])} BTC (~{format_usd(holdings.get('usd', 0.0))})\n"
            f"📡 Source: {source_label}"
        )
        site_snap = holdings.get("site_snapshot") if isinstance(holdings.get("site_snapshot"), dict) else None
        if not site_snap and ENABLE_STRATEGY_SITE:
            site_snap = await fetch_strategy_site_snapshot()
        if site_snap:
            acq = site_snap.get("latest_acquisition")
            if acq:
                btc_balance_info += (
                    f"\n🛒 Last purchase (site): {format_btc(parse_number(acq.get('count', 0)))} BTC"
                    f" on {acq.get('date', 'n/a')}"
                )
    else:
        btc_balance_info = "⚠️ Failed to fetch Strategy balance"

    state = load_holdings_state()
    if state:
        baseline_btc = format_btc(parse_number(state.get("btc", 0)))
        baseline_line = f"📊 Alert baseline: {baseline_btc} BTC"
    else:
        baseline_line = "📊 Alert baseline: not set yet"

    msg = (
        f"✅ Bot online\n"
        f"⏱ Uptime: {uptime}\n\n"
        f"{btc_balance_info}\n"
        f"{baseline_line}"
    )

    if is_admin(update.effective_user.id, update.effective_chat.id) and last_monitor_error:
        msg += f"\n\n⚠️ Monitor error: {last_monitor_error}"

    await update.message.reply_text(
        msg,
        reply_markup=MENU_KEYBOARD if show_menu else None,
    )


async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    await update.message.reply_text(f"⏱ Uptime: {uptime}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "SaylorWatchBot — help\n\n"
        "Menu buttons:\n"
        f"• {BTN_STATUS} — current BTC & alert baseline\n"
        f"• {BTN_CHECK} — compare live data vs baseline now\n"
        f"• {BTN_BUY_CHECK} — simulate purchase alert (admin)\n"
        f"• {BTN_SELL_CHECK} — simulate sale alert (admin)\n"
        f"• {BTN_BASELINE} — set baseline = live balance (strategy.com first)\n"
        f"• {BTN_HIDE_MENU} — hide keyboard\n\n"
        "Also monitors strategy.com for new BTC purchases and press releases.\n\n"
        "Commands:\n"
        "/start /status /check /baseline /site\n"
        "/checkbuy /checksell /testalert /chatid\n"
        "/info /uptime (admin: /clear /restart)\n\n"
        f"Version: {BOT_VERSION}"
    )
    await update.message.reply_text(help_text, reply_markup=MENU_KEYBOARD)


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Для X_CHAT_ID на хостинге используйте:\n"
        f"Chat ID: {update.effective_chat.id}\n"
        f"User ID: {update.effective_user.id}\n\n"
        "Обычно в личке с ботом оба совпадают. "
        "Не подставляйте ID самого бота."
    )


async def testalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return
    try:
        await send_holdings_alert(
            context.bot,
            "✅ Тест: уведомления доходят. Мониторинг закупок и продаж включён.",
        )
        await update.message.reply_text(
            f"✅ Тестовый алерт отправлен в Chat ID {alert_chat_id()}."
        )
    except Exception as exc:
        await update.message.reply_text(
            f"❌ Ошибка отправки: {exc}\nПроверьте /chatid и переменную X_CHAT_ID на хостинге."
        )


async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return
    await update.message.reply_text("Проверяю strategy.com и CoinGecko…")
    result = await run_holdings_check(context.bot)
    site_result = await run_strategy_site_check(context.bot)
    lines = [f"Holdings: {result}"]
    if site_result:
        lines.append(f"Strategy.com: {site_result}")
    combined = "\n".join(lines)
    if "отправлен" in result or "Изменений нет" in result or "Сохранён" in result:
        await update.message.reply_text(f"✅ {combined}", reply_markup=MENU_KEYBOARD)
    else:
        await update.message.reply_text(f"❌ {combined}", reply_markup=MENU_KEYBOARD)


async def reset_baseline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set baseline to current live holdings (/baseline)."""
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    holdings = await fetch_strategy_holdings()
    if not holdings:
        await update.message.reply_text("Failed to fetch treasury data (strategy.com / CoinGecko).")
        return

    save_holdings_state(holdings)
    await update.message.reply_text(
        f"Baseline reset to live balance: {format_btc(holdings['btc'])} BTC",
        reply_markup=MENU_KEYBOARD,
    )


async def simulate_purchase_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    holdings = await fetch_strategy_holdings()
    if not holdings:
        await update.message.reply_text("Failed to fetch treasury data (strategy.com / CoinGecko).")
        return

    test_btc = holdings["btc"] - max(MIN_BTC_CHANGE * 10, 100)
    save_holdings_state(
        {"name": holdings["name"], "btc": test_btc, "usd": 0.0, "source": "purchase-check-test"}
    )
    await update.message.reply_text(
        f"Test baseline set lower ({format_btc(test_btc)} BTC). Running purchase check…",
        reply_markup=MENU_KEYBOARD,
    )
    result = await run_holdings_check(context.bot)
    await update.message.reply_text(
        f"{'✅' if 'отправлен' in result else 'ℹ️'} {result}",
        reply_markup=MENU_KEYBOARD,
    )


async def simulate_sale_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    holdings = await fetch_strategy_holdings()
    if not holdings:
        await update.message.reply_text("Failed to fetch treasury data (strategy.com / CoinGecko).")
        return

    test_btc = holdings["btc"] + max(MIN_BTC_CHANGE * 10, 100)
    save_holdings_state(
        {"name": holdings["name"], "btc": test_btc, "usd": 0.0, "source": "sale-check-test"}
    )
    await update.message.reply_text(
        f"Test baseline set higher ({format_btc(test_btc)} BTC). Running sale check…",
        reply_markup=MENU_KEYBOARD,
    )
    result = await run_holdings_check(context.bot)
    await update.message.reply_text(
        f"{'✅' if 'отправлен' in result else 'ℹ️'} {result}",
        reply_markup=MENU_KEYBOARD,
    )


async def setbaseline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    if not context.args:
        holdings = await fetch_strategy_holdings()
        if not holdings:
            await update.message.reply_text(
                "Использование:\n"
                "/setbaseline — baseline = текущий баланс (strategy.com / CoinGecko)\n"
                "/setbaseline 800000 — baseline = 800000 BTC (для теста)"
            )
            return
        save_holdings_state(holdings)
        await update.message.reply_text(
            f"Baseline = текущий баланс: {format_btc(holdings['btc'])} BTC"
        )
        return

    try:
        btc = parse_number(context.args[0])
    except ValueError:
        await update.message.reply_text("Укажите число BTC, например: /setbaseline 800000")
        return

    save_holdings_state({"name": "Strategy", "btc": btc, "usd": 0.0, "source": "manual"})
    await update.message.reply_text(
        f"Baseline задан: {format_btc(btc)} BTC.\n"
        f"Следующая /check сравнит с live-данными (порог {MIN_BTC_CHANGE} BTC)."
    )


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id, update.effective_chat.id):
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
        f"Strategy.com monitor: {ENABLE_STRATEGY_SITE}\n"
        f"Bot version: {BOT_VERSION}\n"
        f"Server Time: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def menu_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text == BTN_STATUS:
        await status(update, context)
    elif text == BTN_CHECK:
        await check_now(update, context)
    elif text == BTN_BUY_CHECK:
        await simulate_purchase_check(update, context)
    elif text == BTN_SELL_CHECK:
        await simulate_sale_check(update, context)
    elif text == BTN_BASELINE:
        await reset_baseline(update, context)
    elif text == BTN_HELP:
        await help_command(update, context)
    elif text == BTN_HIDE_MENU:
        await update.message.reply_text("Menu hidden. Send /start to show it again.", reply_markup=ReplyKeyboardRemove())


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text("⛔ Access denied.")
        return
    await update.message.reply_text("🔄 Restarting Render instance...")
    os._exit(0)


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes recent bot messages"""
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
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
    if not ENABLE_STRATEGY_SITE:
        await update.message.reply_text("Мониторинг strategy.com отключён (ENABLE_STRATEGY_SITE=false).")
        return

    snapshot = await fetch_strategy_site_snapshot()
    if not snapshot:
        await update.message.reply_text("Не удалось загрузить данные с strategy.com.")
        return

    lines = [
        f"🌐 strategy.com — {format_btc(snapshot['btc_holdings'])} BTC",
        f"As of: {snapshot.get('as_of_date', 'n/a')}",
        f"{STRATEGY_SITE_BASE}{STRATEGY_PURCHASES_PATH}",
    ]
    acq = snapshot.get("latest_acquisition")
    if acq:
        lines.append(
            f"Last purchase: {format_btc(parse_number(acq.get('count', 0)))} BTC "
            f"on {acq.get('date', 'n/a')} @ {format_usd(parse_number(acq.get('price', 0)))}"
        )
    press = snapshot.get("latest_press")
    if press:
        lines.append(f"Latest press: {press.get('title', 'n/a')}")
        if press.get("url"):
            lines.append(press["url"])
    await update.message.reply_text("\n".join(lines))


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
    write_log("🕵️ Мониторинг Strategy (strategy.com + CoinGecko)")
    while True:
        try:
            global last_monitor_error
            site_note = await run_strategy_site_check(bot)
            result = await run_holdings_check(bot)
            if site_note:
                write_log(f"Monitor: {result}; site: {site_note}")
            else:
                write_log(f"Monitor: {result}")
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
            await bot.send_message(chat_id=alert_chat_id(), text=f"✅ Still alive (uptime: {uptime_value})")
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

    await validate_alert_target(application.bot)
    await setup_bot_menu(application.bot)

    if ENABLE_STRATEGY_SITE:
        init_note = await run_strategy_site_check(application.bot)
        if init_note:
            write_log(f"Strategy.com: {init_note}")

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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("baseline", reset_baseline))
    app.add_handler(CommandHandler("checkbuy", simulate_purchase_check))
    app.add_handler(CommandHandler("checksell", simulate_sale_check))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("site", site))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("testalert", testalert))
    app.add_handler(CommandHandler("check", check_now))
    app.add_handler(CommandHandler("setbaseline", setbaseline))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message))
    app.run_polling()
