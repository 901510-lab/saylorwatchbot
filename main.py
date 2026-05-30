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

from cards import CardData, generate_card
from i18n import (
    DEFAULT_LANG,
    LANG_NATIVE_NAMES,
    LANG_OPTIONS,
    SUPPORTED_LANGS,
    lang_from_button,
    resolve_menu_action,
    t,
)

BOT_VERSION = "2026-05-30.1"

# === Initialization ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))
MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", 15 * 60))
ENABLE_ALIVE_PING = os.environ.get("ENABLE_ALIVE_PING", "false").lower() in {"1", "true", "yes", "on"}
MIN_BTC_CHANGE = float(os.environ.get("MIN_BTC_CHANGE", "1"))
LEGAL_URL = os.environ.get("LEGAL_URL", "").strip()
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
# strategy.com (Akamai) blocks bot-like User-Agents with HTTP 403.
STRATEGY_SITE_USER_AGENT = os.environ.get(
    "STRATEGY_SITE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)
STRATEGY_SITE_HTTP_HEADERS = {
    "User-Agent": STRATEGY_SITE_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
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

USER_LANG_FILE = Path(os.environ.get("USER_LANG_FILE", "user_languages.json"))

BOT_COMMANDS = [
    BotCommand("start", "Open menu and show status"),
    BotCommand("holdings", "Strategy BTC treasury overview"),
    BotCommand("stats", "Detailed treasury stats & PnL"),
    BotCommand("buy", "Latest Bitcoin purchase"),
    BotCommand("status", "Strategy BTC balance & baseline"),
    BotCommand("check", "Run treasury check now"),
    BotCommand("checkbuy", "Test purchase alert (admin)"),
    BotCommand("checksell", "Test sale alert (admin)"),
    BotCommand("baseline", "Reset baseline to live data"),
    BotCommand("testalert", "Test notification delivery"),
    BotCommand("chatid", "Show your Telegram ID"),
    BotCommand("help", "Help and menu"),
    BotCommand("site", "Latest data from strategy.com"),
    BotCommand("disclaimer", "Legal disclaimer (not investment advice)"),
    BotCommand("language", "Choose interface language"),
]


def load_user_languages() -> dict[str, str]:
    if not USER_LANG_FILE.exists():
        return {}
    try:
        return json.loads(USER_LANG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_user_languages(data: dict[str, str]) -> None:
    USER_LANG_FILE.write_text(json.dumps(data, indent=2, sort_keys=True))


def get_user_lang(telegram_id: int | None) -> str:
    if telegram_id is None:
        return DEFAULT_LANG
    code = load_user_languages().get(str(telegram_id), DEFAULT_LANG)
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def set_user_lang(telegram_id: int, lang: str) -> None:
    data = load_user_languages()
    data[str(telegram_id)] = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    save_user_languages(data)


def user_lang(update: Update) -> str:
    return get_user_lang(update.effective_user.id)


def alert_lang() -> str:
    return get_user_lang(alert_chat_id())


def menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t(lang, "btn_holdings")), KeyboardButton(t(lang, "btn_stats"))],
            [KeyboardButton(t(lang, "btn_status")), KeyboardButton(t(lang, "btn_check"))],
            [
                KeyboardButton(t(lang, "btn_buy_check")),
                KeyboardButton(t(lang, "btn_sell_check")),
            ],
            [KeyboardButton(t(lang, "btn_baseline")), KeyboardButton(t(lang, "btn_help"))],
            [
                KeyboardButton(t(lang, "btn_language")),
                KeyboardButton(t(lang, "btn_hide_menu")),
            ],
        ],
        resize_keyboard=True,
    )


def language_keyboard(lang: str = DEFAULT_LANG) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    row: list[KeyboardButton] = []
    for _code, label in LANG_OPTIONS:
        row.append(KeyboardButton(label))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([KeyboardButton(t(lang, "btn_back"))])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


async def show_language_menu(update: Update, lang: str) -> None:
    await update.message.reply_text(t(lang, "lang_menu_title"), reply_markup=language_keyboard(lang))


async def apply_language(update: Update, code: str) -> None:
    set_user_lang(update.effective_user.id, code)
    name = LANG_NATIVE_NAMES.get(code, code)
    await update.message.reply_text(
        t(code, "lang_set", name=name),
        reply_markup=menu_keyboard(code),
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
    lang = user_lang(update)
    await update.message.reply_text(
        t(
            lang,
            "deny_admin",
            user_id=update.effective_user.id,
            chat_id=X_CHAT_ID,
        )
    )


async def setup_bot_menu(bot: Bot) -> None:
    await bot.set_my_commands(BOT_COMMANDS)


async def validate_alert_target(bot: Bot) -> None:
    target = alert_chat_id()
    me = await bot.get_me()
    if target == me.id:
        raise RuntimeError(
            "X_CHAT_ID matches the bot ID. Use your personal chat id from /chatid "
            "and set it as X_CHAT_ID on hosting."
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


def format_usd_compact(value: float) -> str:
    """$66.7B / $2.4B / $980M / $12.3K — для "мощного" главного блока."""
    abs_v = abs(value)
    sign = "-" if value < 0 else ""
    if abs_v >= 1e9:
        return f"{sign}${abs_v / 1e9:.1f}B"
    if abs_v >= 1e6:
        return f"{sign}${abs_v / 1e6:.1f}M"
    if abs_v >= 1e3:
        return f"{sign}${abs_v / 1e3:.1f}K"
    return f"{sign}${abs_v:,.0f}"


def format_signed_usd_compact(value: float) -> str:
    prefix = "+" if value >= 0 else ""
    return f"{prefix}{format_usd_compact(value)}"


def _short_uptime(delta: datetime.timedelta) -> str:
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


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
    try:
        async with aiohttp.ClientSession(headers=STRATEGY_SITE_HTTP_HEADERS) as session:
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


def format_site_press_alert(press: dict[str, str], lang: str) -> str:
    lines = [t(lang, "alert_site_press"), press.get("title", "Press release")]
    if press.get("date"):
        lines.append(f"Date: {press['date']}")
    if press.get("url"):
        lines.append(press["url"])
    return "\n".join(lines)


async def run_strategy_site_check(
    bot: Bot, *, initialize_only: bool = False, lang: str | None = None
) -> str | None:
    if not ENABLE_STRATEGY_SITE:
        return None

    msg_lang = lang or alert_lang()
    snapshot = await fetch_strategy_site_snapshot()
    if not snapshot:
        return t(msg_lang, "site_note_unavailable")

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
        return t(msg_lang, "site_note_init")

    notes: list[str] = []

    press = snapshot.get("latest_press")
    if press:
        press_uid = press.get("uid")
        if press_uid and press_uid != state.get("last_press_uid") and is_btc_related_press(press.get("title", "")):
            if not initialize_only:
                await send_holdings_alert(bot, format_site_press_alert(press, alert_lang()))
            notes.append(t(msg_lang, "site_note_press"))
            state["last_press_uid"] = press_uid

    acquisition = snapshot.get("latest_acquisition")
    if acquisition:
        acq_uid = acquisition.get("uid")
        acq_count = parse_number(acquisition.get("count", 0))
        if acq_uid and acq_uid != state.get("last_acquisition_uid") and acq_count >= MIN_BTC_CHANGE:
            if not initialize_only:
                acq_price = parse_number(acquisition.get("price", 0))
                acq_total = parse_number(acquisition.get("btc_holdings", 0))
                acq_date = acquisition.get("date", datetime.date.today().isoformat())
                stats = await build_treasury_stats()
                alert_text = format_premium_alert(
                    delta_btc=acq_count,
                    delta_usd=acq_count * acq_price,
                    total_btc=acq_total,
                    buy_price=acq_price,
                    date=acq_date,
                    stats=stats,
                    increased=True,
                    lang=alert_lang(),
                )
                await send_alert_with_card(
                    bot,
                    text=alert_text,
                    delta_btc=acq_count,
                    delta_usd=acq_count * acq_price,
                    total_btc=acq_total,
                    date=acq_date,
                    increased=True,
                )
                site_holdings = await fetch_strategy_site_holdings()
                if site_holdings:
                    save_holdings_state(site_holdings)
            notes.append(t(msg_lang, "site_note_purchase", btc=format_btc(acq_count)))
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


async def build_treasury_stats() -> dict[str, Any] | None:
    """Единая картина казны: баланс, рыночная стоимость, ср. цена, PnL, последняя покупка."""
    holdings = await fetch_strategy_holdings()
    if not holdings:
        return None

    btc = parse_number(holdings.get("btc", 0))
    market_value = parse_number(holdings.get("usd", 0))
    cost_basis = parse_number(holdings.get("entry_value_usd", 0))

    # Стоимость покупки и рыночная стоимость есть только в CoinGecko —
    # подтягиваем оттуда, если основной источник (strategy.com) их не дал.
    if (not cost_basis or not market_value) and "coingecko" not in str(holdings.get("source", "")):
        cg = await fetch_coingecko_holdings()
        if cg:
            cost_basis = cost_basis or parse_number(cg.get("entry_value_usd", 0))
            market_value = market_value or parse_number(cg.get("usd", 0))

    btc_price = market_value / btc if btc and market_value else 0.0
    avg_price = cost_basis / btc if btc and cost_basis else 0.0
    pnl = market_value - cost_basis if cost_basis and market_value else 0.0

    site_snap = holdings.get("site_snapshot") if isinstance(holdings.get("site_snapshot"), dict) else None
    if not site_snap and ENABLE_STRATEGY_SITE:
        site_snap = await fetch_strategy_site_snapshot()
    last_acq = site_snap.get("latest_acquisition") if site_snap else None

    source = str(holdings.get("source", ""))
    source_label_key = "source_strategy_short" if "strategy.com" in source else "source_coingecko_short"

    return {
        "name": holdings.get("name", "Strategy"),
        "btc": btc,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "btc_price": btc_price,
        "avg_price": avg_price,
        "pnl": pnl,
        "last_acquisition": last_acq,
        "source_label_key": source_label_key,
    }


def _last_buy_line(last_acq: dict[str, Any] | None, lang: str) -> str | None:
    if not last_acq:
        return None
    count = format_btc(parse_number(last_acq.get("count", 0)))
    date = last_acq.get("date", "n/a")
    return f"{t(lang, 'lbl_last_buy')}: +{count} BTC ({date})"


def format_treasury_block(stats: dict[str, Any], lang: str, title_key: str) -> str:
    """«Мощный» главный блок: крупный ₿ + иерархия emoji."""
    lines = [
        t(lang, title_key),
        "",
        f"\u20bf {format_btc(stats['btc'])} BTC",
        f"\u2248 {format_usd_compact(stats['market_value'])}",
        "",
    ]
    if stats.get("avg_price"):
        lines.append(f"{t(lang, 'lbl_avg_price')}: {format_usd(stats['avg_price'])}")
    if stats.get("pnl"):
        lines.append(f"{t(lang, 'lbl_pnl')}: {format_signed_usd_compact(stats['pnl'])}")
    last_line = _last_buy_line(stats.get("last_acquisition"), lang)
    if last_line:
        lines.append(last_line)
    lines.append(f"{t(lang, 'lbl_source')}: {t(lang, stats['source_label_key'])}")
    return "\n".join(lines)


def format_stats_block(stats: dict[str, Any], lang: str) -> str:
    lines = [
        t(lang, "stats_title"),
        "",
        f"{t(lang, 'lbl_holdings')}: {format_btc(stats['btc'])} BTC",
        f"{t(lang, 'stats_market_value')}: {format_usd_compact(stats['market_value'])}",
    ]
    if stats.get("btc_price"):
        lines.append(f"{t(lang, 'stats_btc_price')}: {format_usd(stats['btc_price'])}")
    if stats.get("cost_basis"):
        lines.append(f"{t(lang, 'stats_cost_basis')}: {format_usd_compact(stats['cost_basis'])}")
    if stats.get("avg_price"):
        lines.append(f"{t(lang, 'lbl_avg_price')}: {format_usd(stats['avg_price'])}")
    if stats.get("pnl"):
        lines.append(f"{t(lang, 'lbl_pnl')}: {format_signed_usd_compact(stats['pnl'])}")
    last_line = _last_buy_line(stats.get("last_acquisition"), lang)
    if last_line:
        lines.append(last_line)
    lines.append(f"{t(lang, 'lbl_source')}: {t(lang, stats['source_label_key'])}")
    return "\n".join(lines)


def format_premium_alert(
    *,
    delta_btc: float,
    delta_usd: float,
    total_btc: float,
    buy_price: float,
    date: str,
    stats: dict[str, Any] | None,
    increased: bool,
    lang: str,
) -> str:
    """Короткий «premium crypto terminal» alert."""
    sign = "+" if increased else "−"
    title_key = "alert_buy_title" if increased else "alert_sell_title"
    lines = [
        t(lang, title_key),
        "",
        f"\u20bf {sign}{format_btc(abs(delta_btc))} BTC",
    ]
    if delta_usd:
        lines.append(f"\u2248 {format_usd_compact(abs(delta_usd))}")
    lines.append("")
    lines.append(f"{t(lang, 'lbl_holdings')}: {format_btc(total_btc)} BTC")
    if stats and stats.get("avg_price"):
        lines.append(f"{t(lang, 'lbl_avg_price')}: {format_usd(stats['avg_price'])}")
    if stats and stats.get("pnl"):
        lines.append(f"{t(lang, 'lbl_pnl')}: {format_signed_usd_compact(stats['pnl'])}")
    if buy_price:
        lines.append(f"{t(lang, 'lbl_buy_price')}: {format_usd(buy_price)}")
    if date:
        lines.append(f"📅 {date}")
    return "\n".join(lines)


async def send_holdings_alert(bot: Bot, text: str) -> None:
    await bot.send_message(chat_id=alert_chat_id(), text=text)


async def send_alert_with_card(
    bot: Bot,
    *,
    text: str,
    delta_btc: float,
    delta_usd: float,
    total_btc: float,
    date: str,
    increased: bool,
) -> None:
    """Шлёт alert: с image-карточкой, либо текстом если картинка недоступна."""
    card = generate_card(
        CardData(
            title=t(alert_lang(), "alert_buy_title" if increased else "alert_sell_title"),
            delta_btc=f"{'+' if increased else '−'}{format_btc(abs(delta_btc))} BTC",
            delta_usd=f"\u2248 {format_usd_compact(abs(delta_usd))}" if delta_usd else "",
            total_btc=f"{format_btc(total_btc)} BTC",
            date=date or "—",
            is_sale=not increased,
        )
    )
    if card is not None:
        try:
            await bot.send_photo(chat_id=alert_chat_id(), photo=card, caption=text)
            return
        except Exception as exc:
            write_log(f"⚠️ Card send failed, falling back to text: {type(exc).__name__}: {exc}")
    await send_holdings_alert(bot, text)


async def run_holdings_check(bot: Bot, lang: str | None = None) -> tuple[str, str, str]:
    """One monitoring cycle. Returns (severity, kind, message). severity: ok | error."""
    global last_monitor_check, last_monitor_error

    msg_lang = lang or alert_lang()
    last_monitor_check = datetime.datetime.now()
    holdings = await fetch_strategy_holdings()
    if not holdings:
        last_monitor_error = t(msg_lang, "check_fetch_error")
        return "error", "fetch_error", last_monitor_error

    previous = load_holdings_state()
    previous_btc = parse_number(previous.get("btc", 0)) if previous else None
    current_btc = holdings["btc"]
    last_monitor_error = None

    if previous_btc is None:
        save_holdings_state(holdings)
        write_log(f"📊 Baseline saved: {format_btc(current_btc)} BTC")
        return "ok", "baseline_saved", t(msg_lang, "check_baseline_saved", btc=format_btc(current_btc))

    delta = current_btc - previous_btc
    if abs(delta) < MIN_BTC_CHANGE:
        write_log("ℹ️ Check — no significant change.")
        return (
            "ok",
            "no_change",
            t(
                msg_lang,
                "check_no_change",
                current=format_btc(current_btc),
                baseline=format_btc(previous_btc),
                threshold=MIN_BTC_CHANGE,
            ),
        )

    alert_message_lang = alert_lang()
    increased = delta > 0
    stats = await build_treasury_stats()
    btc_price = stats["btc_price"] if stats and stats.get("btc_price") else (
        parse_number(holdings.get("usd", 0)) / current_btc if current_btc else 0.0
    )
    delta_usd = abs(delta) * btc_price
    last_acq = stats.get("last_acquisition") if stats else None
    buy_price = parse_number(last_acq.get("price", 0)) if last_acq else btc_price
    date = last_acq.get("date", "") if last_acq else datetime.date.today().isoformat()

    alert_text = format_premium_alert(
        delta_btc=delta,
        delta_usd=delta_usd,
        total_btc=current_btc,
        buy_price=buy_price if increased else 0.0,
        date=date,
        stats=stats,
        increased=increased,
        lang=alert_message_lang,
    )
    await send_alert_with_card(
        bot,
        text=alert_text,
        delta_btc=delta,
        delta_usd=delta_usd,
        total_btc=current_btc,
        date=date,
        increased=increased,
    )
    save_holdings_state(holdings)
    if increased:
        write_log(f"🚨 Purchase: +{format_btc(delta)} BTC")
        return "ok", "purchase_sent", t(msg_lang, "check_purchase_sent", delta=format_btc(delta))
    write_log(f"🚨 Sale: {format_btc(delta)} BTC")
    return "ok", "sale_sent", t(msg_lang, "check_sale_sent", delta=format_btc(delta))


# === Commands ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    await update.message.reply_text(
        t(lang, "start_intro", version=BOT_VERSION) + "\n\n" + t(lang, "disclaimer_short"),
        reply_markup=menu_keyboard(lang),
    )
    await status(update, context, show_menu=False)


async def disclaimer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    text = t(lang, "disclaimer_full")
    if LEGAL_URL:
        text += "\n\n" + t(lang, "disclaimer_terms", url=LEGAL_URL)
    await update.message.reply_text(text, reply_markup=menu_keyboard(lang))


async def status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    show_menu: bool = True,
):
    lang = user_lang(update)
    uptime = datetime.datetime.now() - start_time
    stats = await build_treasury_stats()

    if stats:
        btc_balance_info = format_treasury_block(stats, lang, "holdings_title")
    else:
        btc_balance_info = t(lang, "status_fetch_fail")

    state = load_holdings_state()
    if state:
        baseline_line = t(lang, "status_baseline", btc=format_btc(parse_number(state.get("btc", 0))))
    else:
        baseline_line = t(lang, "status_baseline_unset")

    msg = (
        f"{t(lang, 'status_online')} · {t(lang, 'status_uptime', uptime=_short_uptime(uptime))}\n\n"
        f"{btc_balance_info}\n"
        f"{baseline_line}"
    )

    if is_admin(update.effective_user.id, update.effective_chat.id) and last_monitor_error:
        msg += f"\n\n{t(lang, 'status_monitor_error', error=last_monitor_error)}"

    await update.message.reply_text(
        msg,
        reply_markup=menu_keyboard(lang) if show_menu else None,
    )


async def uptime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uptime = datetime.datetime.now() - start_time
    await update.message.reply_text(f"⏱ Uptime: {uptime}")


async def holdings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    stats = await build_treasury_stats()
    if not stats:
        await update.message.reply_text(t(lang, "status_fetch_fail"), reply_markup=menu_keyboard(lang))
        return
    await update.message.reply_text(
        format_treasury_block(stats, lang, "holdings_title"),
        reply_markup=menu_keyboard(lang),
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    stats = await build_treasury_stats()
    if not stats:
        await update.message.reply_text(t(lang, "status_fetch_fail"), reply_markup=menu_keyboard(lang))
        return
    await update.message.reply_text(
        format_stats_block(stats, lang),
        reply_markup=menu_keyboard(lang),
    )


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    stats = await build_treasury_stats()
    last_acq = stats.get("last_acquisition") if stats else None
    if not last_acq:
        await update.message.reply_text(t(lang, "buy_none"), reply_markup=menu_keyboard(lang))
        return

    count = parse_number(last_acq.get("count", 0))
    price = parse_number(last_acq.get("price", 0))
    total = parse_number(last_acq.get("btc_holdings", 0)) or (stats["btc"] if stats else 0.0)
    date = last_acq.get("date", "")
    text = format_premium_alert(
        delta_btc=count,
        delta_usd=count * price,
        total_btc=total,
        buy_price=price,
        date=date,
        stats=stats,
        increased=True,
        lang=lang,
    )
    text = text.replace(t(lang, "alert_buy_title"), t(lang, "buy_title"), 1)
    await update.message.reply_text(text, reply_markup=menu_keyboard(lang))


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    help_text = t(
        lang,
        "help_body",
        btn_status=t(lang, "btn_status"),
        btn_check=t(lang, "btn_check"),
        btn_buy_check=t(lang, "btn_buy_check"),
        btn_sell_check=t(lang, "btn_sell_check"),
        btn_baseline=t(lang, "btn_baseline"),
        btn_language=t(lang, "btn_language"),
        btn_hide_menu=t(lang, "btn_hide_menu"),
        version=BOT_VERSION,
    )
    help_text += "\n\n" + t(lang, "disclaimer_short")
    await update.message.reply_text(help_text, reply_markup=menu_keyboard(lang))


async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    await update.message.reply_text(
        t(
            lang,
            "chatid_help",
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
        )
    )


async def testalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return
    try:
        await send_holdings_alert(context.bot, t(alert_lang(), "testalert_message"))
        await update.message.reply_text(
            t(lang, "testalert_sent", chat_id=alert_chat_id()),
            reply_markup=menu_keyboard(lang),
        )
    except Exception as exc:
        await update.message.reply_text(
            t(lang, "testalert_fail", error=exc),
            reply_markup=menu_keyboard(lang),
        )


async def check_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return
    await update.message.reply_text(t(lang, "check_checking"), reply_markup=menu_keyboard(lang))
    severity, _kind, result = await run_holdings_check(context.bot, lang=lang)
    site_result = await run_strategy_site_check(context.bot, lang=lang)
    lines = [t(lang, "check_holdings_line", result=result)]
    if site_result:
        lines.append(t(lang, "check_site_line", result=site_result))
    combined = "\n".join(lines)
    emoji = "✅" if severity == "ok" else "❌"
    await update.message.reply_text(f"{emoji} {combined}", reply_markup=menu_keyboard(lang))


async def reset_baseline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set baseline to current live holdings (/baseline)."""
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    holdings = await fetch_strategy_holdings()
    if not holdings:
        await update.message.reply_text(t(lang, "fetch_treasury_fail"), reply_markup=menu_keyboard(lang))
        return

    save_holdings_state(holdings)
    await update.message.reply_text(
        t(lang, "baseline_reset", btc=format_btc(holdings["btc"])),
        reply_markup=menu_keyboard(lang),
    )


async def simulate_purchase_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    holdings = await fetch_strategy_holdings()
    if not holdings:
        await update.message.reply_text(t(lang, "fetch_treasury_fail"), reply_markup=menu_keyboard(lang))
        return

    test_btc = holdings["btc"] - max(MIN_BTC_CHANGE * 10, 100)
    save_holdings_state(
        {"name": holdings["name"], "btc": test_btc, "usd": 0.0, "source": "purchase-check-test"}
    )
    await update.message.reply_text(
        t(lang, "simulate_purchase_setup", btc=format_btc(test_btc)),
        reply_markup=menu_keyboard(lang),
    )
    severity, kind, result = await run_holdings_check(context.bot, lang=lang)
    emoji = "✅" if severity == "ok" and kind == "purchase_sent" else "ℹ️"
    await update.message.reply_text(f"{emoji} {result}", reply_markup=menu_keyboard(lang))


async def simulate_sale_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    holdings = await fetch_strategy_holdings()
    if not holdings:
        await update.message.reply_text(t(lang, "fetch_treasury_fail"), reply_markup=menu_keyboard(lang))
        return

    test_btc = holdings["btc"] + max(MIN_BTC_CHANGE * 10, 100)
    save_holdings_state(
        {"name": holdings["name"], "btc": test_btc, "usd": 0.0, "source": "sale-check-test"}
    )
    await update.message.reply_text(
        t(lang, "simulate_sale_setup", btc=format_btc(test_btc)),
        reply_markup=menu_keyboard(lang),
    )
    severity, kind, result = await run_holdings_check(context.bot, lang=lang)
    emoji = "✅" if severity == "ok" and kind == "sale_sent" else "ℹ️"
    await update.message.reply_text(f"{emoji} {result}", reply_markup=menu_keyboard(lang))


async def setbaseline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    if not context.args:
        holdings = await fetch_strategy_holdings()
        if not holdings:
            await update.message.reply_text(t(lang, "setbaseline_usage"), reply_markup=menu_keyboard(lang))
            return
        save_holdings_state(holdings)
        await update.message.reply_text(
            t(lang, "setbaseline_live", btc=format_btc(holdings["btc"])),
            reply_markup=menu_keyboard(lang),
        )
        return

    try:
        btc = parse_number(context.args[0])
    except ValueError:
        await update.message.reply_text(t(lang, "setbaseline_invalid"), reply_markup=menu_keyboard(lang))
        return

    save_holdings_state({"name": "Strategy", "btc": btc, "usd": 0.0, "source": "manual"})
    await update.message.reply_text(
        t(lang, "setbaseline_manual", btc=format_btc(btc), threshold=MIN_BTC_CHANGE),
        reply_markup=menu_keyboard(lang),
    )


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_language_menu(update, user_lang(update))


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text(t(lang, "access_denied"))
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
    lang = user_lang(update)

    picked_lang = lang_from_button(text)
    if picked_lang:
        await apply_language(update, picked_lang)
        return

    action = resolve_menu_action(text)
    if action == "status":
        await status(update, context)
    elif action == "holdings":
        await holdings_command(update, context)
    elif action == "stats":
        await stats_command(update, context)
    elif action == "check":
        await check_now(update, context)
    elif action == "buy_check":
        await simulate_purchase_check(update, context)
    elif action == "sell_check":
        await simulate_sale_check(update, context)
    elif action == "baseline":
        await reset_baseline(update, context)
    elif action == "help":
        await help_command(update, context)
    elif action == "language":
        await show_language_menu(update, lang)
    elif action == "hide_menu":
        await update.message.reply_text(t(lang, "hide_menu"), reply_markup=ReplyKeyboardRemove())
    elif action == "back":
        await update.message.reply_text(
            t(lang, "start_intro", version=BOT_VERSION),
            reply_markup=menu_keyboard(lang),
        )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text(t(lang, "access_denied"))
        return
    await update.message.reply_text(t(lang, "restart"))
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
        lang = user_lang(update)
        await update.message.reply_text(t(lang, "clear_done", count=deleted))
    except Exception as exc:
        logger.exception("Failed to clear messages")
        lang = user_lang(update)
        await update.message.reply_text(t(lang, "clear_error", error=exc))


async def site(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not ENABLE_STRATEGY_SITE:
        await update.message.reply_text(t(lang, "site_disabled"), reply_markup=menu_keyboard(lang))
        return

    snapshot = await fetch_strategy_site_snapshot()
    if not snapshot:
        await update.message.reply_text(t(lang, "site_fetch_fail"), reply_markup=menu_keyboard(lang))
        return

    lines = [
        t(lang, "site_header", btc=format_btc(snapshot["btc_holdings"])),
        t(lang, "site_as_of", date=snapshot.get("as_of_date", "n/a")),
        f"{STRATEGY_SITE_BASE}{STRATEGY_PURCHASES_PATH}",
    ]
    acq = snapshot.get("latest_acquisition")
    if acq:
        lines.append(
            t(
                lang,
                "site_last_purchase",
                btc=format_btc(parse_number(acq.get("count", 0))),
                date=acq.get("date", "n/a"),
                price=format_usd(parse_number(acq.get("price", 0))),
            )
        )
    press = snapshot.get("latest_press")
    if press:
        lines.append(t(lang, "site_latest_press", title=press.get("title", "n/a")))
        if press.get("url"):
            lines.append(press["url"])
    await update.message.reply_text("\n".join(lines), reply_markup=menu_keyboard(lang))


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
            site_note = await run_strategy_site_check(bot, lang=alert_lang())
            _severity, _kind, result = await run_holdings_check(bot, lang=alert_lang())
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
            await bot.send_message(
                chat_id=alert_chat_id(),
                text=t(alert_lang(), "alive_ping", uptime=uptime_value),
            )
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
        init_note = await run_strategy_site_check(application.bot, lang=alert_lang())
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
    app.add_handler(CommandHandler("holdings", holdings_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("baseline", reset_baseline))
    app.add_handler(CommandHandler("checkbuy", simulate_purchase_check))
    app.add_handler(CommandHandler("checksell", simulate_sale_check))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("site", site))
    app.add_handler(CommandHandler("disclaimer", disclaimer_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("lang", language_command))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("testalert", testalert))
    app.add_handler(CommandHandler("check", check_now))
    app.add_handler(CommandHandler("setbaseline", setbaseline))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message))
    app.run_polling()
