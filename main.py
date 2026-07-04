import asyncio
import datetime
import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from dotenv import load_dotenv
from telegram import (
    Bot,
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, PreCheckoutQueryHandler, filters
from telegram.request import HTTPXRequest

from baseline import load_baseline, migrate_legacy_baseline, save_baseline_from_holdings
from json_store import atomic_write_json, json_rw_lock, read_json_file
from user_lang_prefs import get_user_lang as _get_user_lang_pref, set_user_lang as _set_user_lang_pref
from alert_delivery import dispatch_alert, gating_enabled
from bot_analytics import get_analytics, record_start
from entities import find_entity_by_name
from founding_promo import (
    FOUNDING_PROMO_CALLBACK,
    FOUNDING_PROMO_CANCEL_CALLBACK,
    FOUNDING_PROMO_CONFIRM_CALLBACK,
    FOUNDING_PROMO_DAYS,
    eligible_for_founding,
    promo_active,
    promo_status,
    try_claim_founding_premium,
    user_claim_slot,
    user_claimed_founding,
)
try:
    from social_growth import (
        bot_link,
        configured_social_links,
        format_share_message,
        list_share_options,
        social_links_configured,
    )
except ImportError:
    def bot_link() -> str:
        return "https://t.me/Saylor_w_bot"

    def configured_social_links() -> list:
        return []

    def social_links_configured() -> bool:
        return False

    def list_share_options() -> str:
        return "Upload social_growth.py to enable /share"

    def format_share_message(platform: str, kind: str) -> str:
        raise ValueError("social_growth.py not deployed on server")
from partners import configured_partners, partners_configured
from monitor_entities import run_companies_check
from monitor_etf import run_etf_check
from subscription_plans import (
    PLANS,
    FREE_ALERT_DELAY_MINUTES,
    PREMIUM_PRICE_USD_DEFAULT,
    PlanId,
    whales_top_n_for_plan,
)
from subscription_reminders import (
    REMINDER_HOUR,
    REMINDER_MINUTE,
    REMINDER_TIMEZONE,
    reminders_enabled,
    subscription_reminder_scheduler,
)
from subscription_payments import (
    PREMIUM_BILLING_DAYS,
    PREMIUM_STARS_PRICE,
    SUBSCRIBE_PAY_CALLBACK,
    fulfill_premium_payment,
    payment_already_processed,
    pre_checkout_handler,
    send_premium_invoice,
    stars_payments_enabled,
)
from subscribers import (
    days_remaining,
    effective_plan,
    get_subscriber,
    grant_premium_days,
    revoke_subscription,
)
from weekly_digest import (
    WEEKLY_DIGEST_HOUR,
    WEEKLY_DIGEST_MINUTE,
    WEEKLY_DIGEST_TIMEZONE,
    deliver_weekly_digest,
    digest_enabled,
    weekly_digest_scheduler,
)
from weekly_report_export import (
    build_weekly_export,
    cache_weekly_digest,
    get_cached_weekly_digest,
)
from paper_wallet import (
    PAPER_WALLET_POST_HOUR,
    PAPER_WALLET_POST_MINUTE,
    PAPER_WALLET_TIMEZONE,
    paper_wallet_enabled,
    paper_wallet_scheduler,
)
from whales import collect_whale_rankings, format_whales_message
from models import EntityType
from cards import CardData, generate_card
from bot_help_wiki import format_help_wiki
from i18n import (
    DEFAULT_LANG,
    LANG_NATIVE_NAMES,
    LANG_OPTIONS,
    SUPPORTED_LANGS,
    lang_from_button,
    resolve_menu_action,
    t,
)

BOT_VERSION = "2026-06-24.1"

# === Initialization ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
X_CHAT_ID = os.getenv("X_CHAT_ID")
PORT = int(os.environ.get("PORT", 10000))
MONITOR_INTERVAL_SECONDS = int(os.environ.get("MONITOR_INTERVAL_SECONDS", 15 * 60))
ENABLE_ALIVE_PING = os.environ.get("ENABLE_ALIVE_PING", "false").lower() in {"1", "true", "yes", "on"}
MIN_BTC_CHANGE = float(os.environ.get("MIN_BTC_CHANGE", "1"))
LEGAL_URL = os.environ.get("LEGAL_URL", "").strip()
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "SaylorWatch@outlook.com").strip()
SITE_URL = os.environ.get("SITE_URL", "").strip().rstrip("/")
# Адреса для донатов (на оплату сервера). По умолчанию зашиты ниже,
# при необходимости можно переопределить переменными окружения.
DONATE_BTC = os.environ.get("DONATE_BTC", "").strip()
DONATE_ETH = os.environ.get("DONATE_ETH", "").strip()
DONATE_TON = os.environ.get("DONATE_TON", "").strip()
# EVM chain id для deep-link (1 = Ethereum mainnet).
DONATE_ETH_CHAIN = os.environ.get("DONATE_ETH_CHAIN", "1").strip() or "1"


def metamask_send_url(address: str) -> str:
    # Открывает экран отправки в MetaMask mobile (работает и как ссылка в Telegram).
    return f"https://link.metamask.io/send/{address}@{DONATE_ETH_CHAIN}"


def btc_explorer_url(address: str) -> str:
    # bitcoin: URI Telegram не делает кликабельным, поэтому ведём на mempool.space
    # (там виден адрес и QR-код для сканирования кошельком).
    return f"https://mempool.space/address/{address}"


def ton_transfer_url(address: str) -> str:
    return f"https://app.tonkeeper.com/transfer/{address}"


def donate_configured() -> bool:
    return bool(DONATE_BTC or DONATE_ETH or DONATE_TON)


def donate_footer(lang: str) -> str:
    # Ненавязчивая строка-футер с иконками кошельков для тела сообщений.
    if not donate_configured():
        return ""
    return "\n\n" + t(lang, "donate_footer")


def social_footer(lang: str) -> str:
    return "\n" + t(lang, "social_footer")


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

# Dedupe: site acquisition + holdings delta в одном monitor tick
_site_acquisition_skip_btc: float | None = None


def reset_monitor_dedupe() -> None:
    global _site_acquisition_skip_btc
    _site_acquisition_skip_btc = None


def mark_site_acquisition_for_dedupe(btc: float) -> None:
    global _site_acquisition_skip_btc
    _site_acquisition_skip_btc = abs(float(btc))


def holdings_matches_site_acquisition(delta_btc: float) -> bool:
    global _site_acquisition_skip_btc
    if _site_acquisition_skip_btc is None:
        return False
    return abs(abs(float(delta_btc)) - _site_acquisition_skip_btc) < MIN_BTC_CHANGE

# === Monitoring configuration ===
HOLDINGS_STATE_FILE = Path(os.environ.get("HOLDINGS_STATE_FILE", "last_holdings.json"))
# Per-entity baseline id для текущего MVP-мониторинга Strategy (см. baseline.py).
STRATEGY_ENTITY_ID = "strategy"
COINGECKO_TREASURY_URL = "https://api.coingecko.com/api/v3/companies/public_treasury/bitcoin"
COINGECKO_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
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

BOT_COMMANDS = [
    BotCommand("start", "Open menu and show status"),
    BotCommand("holdings", "Strategy BTC treasury overview"),
    BotCommand("stats", "Detailed treasury stats & PnL"),
    BotCommand("buy", "Latest Bitcoin purchase"),
    BotCommand("status", "Strategy BTC balance & baseline"),
    BotCommand("chatid", "Show your Telegram ID"),
    BotCommand("help", "Command mini wiki & glossary"),
    BotCommand("site", "Latest data from strategy.com"),
    BotCommand("whales", "Top BTC holders ranking"),
    BotCommand("plans", "Free vs Premium features"),
    BotCommand("mysub", "Your subscription status"),
    BotCommand("subscribe", "Get Premium (Telegram Stars)"),
    BotCommand("weekly", "Premium weekly digest (PNG)"),
    BotCommand("donate", "Support the server (BTC / ETH / TON)"),
    BotCommand("partners", "Partner links (exchanges & wallets)"),
    BotCommand("social", "Follow on X, Reddit & Discord"),
    BotCommand("disclaimer", "Legal disclaimer (not investment advice)"),
    BotCommand("language", "Choose interface language"),
]


def set_user_lang(telegram_id: int, lang: str) -> None:
    _set_user_lang_pref(telegram_id, lang)


def get_user_lang(telegram_id: int | None) -> str:
    return _get_user_lang_pref(telegram_id)


def user_lang(update: Update) -> str:
    return get_user_lang(update.effective_user.id)


def alert_lang() -> str:
    return get_user_lang(alert_chat_id())


def menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t(lang, "btn_holdings")), KeyboardButton(t(lang, "btn_stats"))],
            [KeyboardButton(t(lang, "btn_status")), KeyboardButton(t(lang, "btn_check"))],
            [KeyboardButton(t(lang, "btn_baseline")), KeyboardButton(t(lang, "btn_help"))],
            [
                KeyboardButton(t(lang, "btn_plans")),
                KeyboardButton(t(lang, "btn_subscribe")),
            ],
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
    del chat_id  # только user_id — не авторизуем всех в группе алертов
    target = str(X_CHAT_ID).strip()
    return user_id is not None and str(user_id) == target


async def deny_admin(update: Update) -> None:
    lang = user_lang(update)
    await update.message.reply_text(
        t(
            lang,
            "deny_admin",
            user_id=update.effective_user.id,
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


def card_title_for_entity(entity: str, *, increased: bool) -> str:
    """Заголовок карточки на английском. Strategy — шаблон i18n, ETF — INFLOW/OUTFLOW."""
    if is_strategy_company(entity):
        raw = t(DEFAULT_LANG, "alert_buy_title" if increased else "alert_sell_title")
        return re.sub(r"^[^\x00-\x7f]+\s*", "", raw)
    cfg = find_entity_by_name(entity)
    if cfg and cfg.type == EntityType.ETF:
        action = "ETF INFLOW" if increased else "ETF OUTFLOW"
        return f"{entity.upper()} · {action}"
    action = "BITCOIN BUY" if increased else "BITCOIN SELL"
    return f"{entity.upper()} · {action}"


def entity_type_line(entity: str, lang: str) -> str:
    """Подпись типа сущности для текстового алерта (локализованная)."""
    cfg = find_entity_by_name(entity)
    if is_strategy_company(entity):
        return t(lang, "entity_kind_treasury")
    if cfg and cfg.type == EntityType.ETF:
        line = t(lang, "entity_kind_etf")
    else:
        line = t(lang, "entity_kind_company")
    if cfg and cfg.ticker:
        return f"{line} · {cfg.ticker}"
    return line


def card_kind_label(entity: str) -> str:
    """Подпись типа на карточке (англ., с тикером)."""
    cfg = find_entity_by_name(entity)
    if is_strategy_company(entity):
        return t(DEFAULT_LANG, "card_kind_treasury")
    if cfg and cfg.type == EntityType.ETF:
        kind = t(DEFAULT_LANG, "card_kind_etf")
    else:
        kind = t(DEFAULT_LANG, "card_kind_company")
    if cfg and cfg.ticker:
        return f"{kind} · {cfg.ticker}"
    return kind


def card_panel_label(entity: str, *, is_etf: bool) -> str:
    if is_etf:
        return t(DEFAULT_LANG, "card_panel_flow")
    return t(DEFAULT_LANG, "card_panel_holdings")


def load_holdings_state() -> dict[str, Any] | None:
    # Миграция старого last_holdings.json -> baselines/strategy.json (один раз).
    migrate_legacy_baseline(STRATEGY_ENTITY_ID, HOLDINGS_STATE_FILE)
    bl = load_baseline(STRATEGY_ENTITY_ID)
    if bl:
        return bl.to_dict()
    return None


def save_holdings_state(holdings: dict[str, Any]) -> None:
    save_baseline_from_holdings(STRATEGY_ENTITY_ID, holdings)


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


async def fetch_btc_spot_price() -> float | None:
    """Текущая спотовая цена BTC в USD с CoinGecko (или None при ошибке)."""
    try:
        data = await fetch_json(COINGECKO_PRICE_URL, timeout_seconds=10)
    except Exception as exc:
        write_log(f"⚠️ CoinGecko price error: {type(exc).__name__}: {exc}")
        return None
    try:
        price = float(data["bitcoin"]["usd"])
        return price if price > 0 else None
    except (KeyError, TypeError, ValueError):
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
        with json_rw_lock(STRATEGY_SITE_STATE_FILE, default={}) as data:
            return dict(data) if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        logger.warning("Invalid strategy site state file: %s", STRATEGY_SITE_STATE_FILE)
        return {}


def save_strategy_site_state(state: dict[str, Any]) -> None:
    with json_rw_lock(STRATEGY_SITE_STATE_FILE, default={}) as data:
        data.clear()
        data.update(state)


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
        lines.append(t(lang, "lbl_date", date=press["date"]))
    if press.get("url"):
        lines.append(press["url"])
    return "\n".join(lines)


async def run_strategy_site_check(
    bot: Bot,
    *,
    initialize_only: bool = False,
    lang: str | None = None,
    send_alerts: bool = True,
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
            if not initialize_only and send_alerts:
                press_instant, _press_queued = await send_holdings_alert(
                    bot,
                    format_site_press_alert(press, alert_lang()),
                    entity_id=STRATEGY_ENTITY_ID,
                    site_monitor=True,
                    text_for_lang=lambda lang: format_site_press_alert(press, lang),
                )
                if press_instant + _press_queued > 0:
                    state["last_press_uid"] = press_uid
            notes.append(t(msg_lang, "site_note_press"))

    acquisition = snapshot.get("latest_acquisition")
    if acquisition:
        acq_uid = acquisition.get("uid")
        acq_count = parse_number(acquisition.get("count", 0))
        if acq_uid and acq_uid != state.get("last_acquisition_uid") and acq_count >= MIN_BTC_CHANGE:
            if not initialize_only and send_alerts:
                acq_price = parse_number(acquisition.get("price", 0))
                total_btc = parse_number(snapshot.get("btc_holdings", 0))
                acq_date = acquisition.get("date", datetime.date.today().isoformat())
                stats = await build_treasury_stats()
                alert_text = format_premium_alert(
                    delta_btc=acq_count,
                    delta_usd=acq_count * acq_price,
                    total_btc=total_btc,
                    buy_price=acq_price,
                    date=acq_date,
                    stats=stats,
                    increased=True,
                    lang=alert_lang(),
                )
                acq_instant, _acq_queued = await send_alert_with_card(
                    bot,
                    text=alert_text,
                    delta_btc=acq_count,
                    delta_usd=acq_count * acq_price,
                    total_btc=total_btc,
                    date=acq_date,
                    increased=True,
                    entity_id=STRATEGY_ENTITY_ID,
                    site_monitor=False,
                    stats=stats,
                    buy_price=acq_price,
                )
                if acq_instant + _acq_queued > 0:
                    mark_site_acquisition_for_dedupe(acq_count)
                    if total_btc:
                        save_holdings_state(
                            {
                                "name": "Strategy",
                                "btc": total_btc,
                                "usd": parse_number(snapshot.get("usd_estimate", 0)),
                                "source": str(snapshot.get("source", "strategy.com")),
                            }
                        )
                    else:
                        site_holdings = await fetch_strategy_site_holdings()
                        if site_holdings:
                            save_holdings_state(site_holdings)
                    state["last_acquisition_uid"] = acq_uid
                    notes.append(t(msg_lang, "site_note_purchase", btc=format_btc(acq_count)))
                else:
                    write_log("⚠️ Strategy site acquisition alert not delivered — UID kept")
            elif not initialize_only and not send_alerts:
                notes.append(
                    t(msg_lang, "site_note_purchase", btc=format_btc(acq_count)) + " (dry-run)"
                )

    state["last_site_btc"] = snapshot.get("btc_holdings")
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


def alert_title_for_entity(entity: str, *, increased: bool, lang: str) -> str:
    """Заголовок текстового алерта с учётом сущности."""
    if is_strategy_company(entity):
        return t(lang, "alert_buy_title" if increased else "alert_sell_title")
    cfg = find_entity_by_name(entity)
    if cfg and cfg.type == EntityType.ETF:
        key = "alert_etf_inflow_title" if increased else "alert_etf_outflow_title"
        return t(lang, key, entity=entity.upper())
    key = "alert_entity_buy_title" if increased else "alert_entity_sell_title"
    return t(lang, key, entity=entity.upper())


def format_etf_flow_alert(
    *,
    entity: str,
    flow_btc: float,
    flow_usd: float,
    flow_date: str,
    inflow: bool,
    lang: str,
) -> str:
    """Короткий алерт по дневному ETF-потоку (Farside / SoSoValue)."""
    sign = "+" if inflow else "−"
    lines = [
        alert_title_for_entity(entity, increased=inflow, lang=lang),
        entity_type_line(entity, lang),
        "",
        f"{t(lang, 'lbl_etf_flow')}: {sign}{format_btc(abs(flow_btc))} BTC",
    ]
    if flow_usd:
        lines.append(f"\u2248 {format_usd_compact(abs(flow_usd))}")
    if flow_date:
        lines.append(f"📅 {flow_date}")
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
    entity: str = "Strategy",
) -> str:
    """Короткий «premium crypto terminal» alert."""
    sign = "+" if increased else "−"
    lines = [
        alert_title_for_entity(entity, increased=increased, lang=lang),
        entity_type_line(entity, lang),
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


async def send_holdings_alert(
    bot: Bot,
    text: str,
    *,
    entity_id: str = "strategy",
    site_monitor: bool = False,
    text_for_lang=None,
) -> tuple[int, int]:
    """Текстовый алерт (без карточки). Возвращает (instant, queued)."""
    builder = text_for_lang or (lambda lang: text)
    return await dispatch_alert(
        bot,
        alert_chat_id(),
        entity_id=entity_id,
        site_monitor=site_monitor,
        text_for_lang=builder,
        photo=None,
        admin_lang=alert_lang(),
        donate_footer_for_lang=donate_footer,
    )


async def send_alert_with_card(
    bot: Bot,
    *,
    text: str,
    delta_btc: float,
    delta_usd: float,
    total_btc: float,
    date: str,
    increased: bool,
    entity: str = "Strategy",
    entity_id: str = "strategy",
    is_etf: bool = False,
    site_monitor: bool = False,
    stats: dict[str, Any] | None = None,
    buy_price: float = 0.0,
) -> tuple[int, int]:
    """Шлёт alert с image-карточкой. Возвращает (instant, queued)."""
    card_title = card_title_for_entity(entity, increased=increased)
    delta_str = f"{'+' if increased else '−'}{format_btc(abs(delta_btc))} BTC"
    if is_etf:
        panel_value = delta_str
    else:
        panel_value = f"{format_btc(total_btc)} BTC"
    card = generate_card(
        CardData(
            title=card_title,
            delta_btc=delta_str,
            delta_usd=f"\u2248 {format_usd_compact(abs(delta_usd))}" if delta_usd else "",
            total_btc=panel_value,
            date=date or "—",
            is_sale=not increased,
            compact=not is_strategy_company(entity),
            kind_label=card_kind_label(entity),
            panel_label=card_panel_label(entity, is_etf=is_etf),
            strategy_style=is_strategy_company(entity),
        )
    )

    def text_for_lang(lang: str) -> str:
        if is_etf:
            return format_etf_flow_alert(
                entity=entity,
                flow_btc=delta_btc,
                flow_usd=delta_usd,
                flow_date=date,
                inflow=increased,
                lang=lang,
            )
        return format_premium_alert(
            delta_btc=delta_btc,
            delta_usd=delta_usd,
            total_btc=total_btc,
            buy_price=buy_price if increased else 0.0,
            date=date,
            stats=stats,
            increased=increased,
            lang=lang,
            entity=entity,
        )

    trade_journal = None
    if not is_etf and abs(delta_btc) >= 0.01:
        if not increased:
            estimated = True
        elif entity_id == STRATEGY_ENTITY_ID and buy_price > 0:
            estimated = False
        else:
            estimated = True
        trade_journal = {
            "entity_id": entity_id,
            "entity_name": entity,
            "increased": increased,
            "delta_btc": delta_btc,
            "delta_usd": delta_usd,
            "date": date or datetime.date.today().isoformat(),
            "buy_price": buy_price,
            "source": "strategy.com" if entity_id == STRATEGY_ENTITY_ID else "coingecko_treasury",
            "price_estimated": estimated,
        }

    instant, queued = await dispatch_alert(
        bot,
        alert_chat_id(),
        entity_id=entity_id,
        site_monitor=site_monitor,
        text_for_lang=text_for_lang,
        photo=card,
        admin_lang=alert_lang(),
        donate_footer_for_lang=donate_footer,
        abs_delta_btc=abs(delta_btc),
        trade_journal=trade_journal,
    )
    n = instant + queued
    if trade_journal and instant > 0:
        try:
            from transactions import record_trade_alert

            record_trade_alert(
                entity_id=trade_journal["entity_id"],
                entity_name=trade_journal["entity_name"],
                increased=trade_journal["increased"],
                delta_btc=trade_journal["delta_btc"],
                delta_usd=trade_journal["delta_usd"],
                date=trade_journal["date"],
                buy_price=trade_journal["buy_price"],
                source=trade_journal["source"],
                price_estimated=trade_journal["price_estimated"],
            )
        except Exception as exc:
            logger.warning("trade journal record failed: %s", exc)
    if card is None and n:
        write_log("⚠️ Card unavailable; text alert dispatched")
    elif card is not None and n == 0:
        write_log("⚠️ No alert recipients for entity " + entity_id)
    return instant, queued


async def run_holdings_check(
    bot: Bot,
    lang: str | None = None,
    *,
    send_alerts: bool = True,
) -> tuple[str, str, str]:
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

    if holdings_matches_site_acquisition(delta):
        save_holdings_state(holdings)
        write_log(f"ℹ️ Holdings +{format_btc(delta)} BTC matches site acquisition — duplicate skipped")
        return (
            "ok",
            "deduped",
            t(msg_lang, "check_no_change", current=format_btc(current_btc), baseline=format_btc(previous_btc), threshold=MIN_BTC_CHANGE),
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
    if increased:
        date = last_acq.get("date", "") if last_acq else datetime.date.today().isoformat()
    else:
        date = datetime.date.today().isoformat()

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
    if not send_alerts:
        sign = "+" if increased else ""
        return (
            "ok",
            "would_alert",
            t(
                msg_lang,
                "check_would_alert",
                delta=f"{sign}{format_btc(delta)}",
                current=format_btc(current_btc),
            ),
        )

    alert_instant, _alert_queued = await send_alert_with_card(
        bot,
        text=alert_text,
        delta_btc=delta,
        delta_usd=delta_usd,
        total_btc=current_btc,
        date=date,
        increased=increased,
        entity_id=STRATEGY_ENTITY_ID,
        stats=stats,
        buy_price=buy_price if increased else 0.0,
    )
    if alert_instant + _alert_queued > 0:
        save_holdings_state(holdings)
        if increased:
            write_log(f"🚨 Purchase: +{format_btc(delta)} BTC")
            return "ok", "purchase_sent", t(msg_lang, "check_purchase_sent", delta=format_btc(delta))
        write_log(f"🚨 Sale: {format_btc(delta)} BTC")
        return "ok", "sale_sent", t(msg_lang, "check_sale_sent", delta=format_btc(delta))
    write_log(f"⚠️ Alert not delivered (0 instant, 0 queued) — baseline kept")
    return "error", "delivery_failed", t(msg_lang, "check_delivery_failed")


# === Commands ===
def site_link_line(lang: str) -> str:
    """Строка со ссылкой на сайт, если SITE_URL задан."""
    if not SITE_URL:
        return ""
    return t(lang, "site_link_line", url=SITE_URL)


async def build_start_text(lang: str) -> str:
    return build_start_intro_fast(lang)


def build_start_intro_fast(lang: str) -> str:
    """Приветствие /start без сетевых запросов — мгновенно."""
    intro = t(
        lang,
        "start_intro",
        version=BOT_VERSION,
        stars=PREMIUM_STARS_PRICE,
        days=PREMIUM_BILLING_DAYS,
    )
    if donate_configured():
        intro += "\n" + t(lang, "donate_footer")
    intro += social_footer(lang)
    if promo_active():
        st = promo_status()
        intro += "\n" + t(
            lang,
            "founding_promo_start_line",
            remaining=st.remaining,
            days=FOUNDING_PROMO_DAYS,
        )
    site_line = site_link_line(lang)
    if site_line:
        intro += "\n" + site_line
    return intro


async def build_start_btc_line(lang: str) -> str:
    btc_price = await fetch_btc_spot_price()
    if btc_price:
        return t(lang, "start_btc_price", price=format_usd(btc_price))
    return ""


async def send_start_followup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lang: str,
) -> None:
    """BTC spot и status — после карточек, не блокирует витрину."""
    chat_id = update.effective_chat.id
    try:
        btc_line = await build_start_btc_line(lang)
        if btc_line:
            await context.bot.send_message(chat_id=chat_id, text=btc_line)
    except Exception:
        logger.exception("start btc line failed")
    try:
        await status(update, context, show_menu=False)
    except Exception:
        logger.exception("start status followup failed")


async def send_plan_showcase(bot: Bot, chat_id: int, lang: str) -> None:
    """Мини-карточки Free и Premium — из кэша (мгновенно после прогрева)."""
    from plan_showcase import (
        get_cached_start_showcase,
        showcase_enabled,
        start_showcase_cache_ready,
    )

    if not showcase_enabled():
        return

    wiki_lang = lang if lang in {"ru", "en"} else "en"
    if not start_showcase_cache_ready(wiki_lang):
        try:
            await bot.send_chat_action(chat_id=chat_id, action="upload_photo")
        except Exception:
            pass
    free_col, prem_col = await asyncio.to_thread(get_cached_start_showcase, wiki_lang)

    async def _send_photo(img: io.BytesIO | None, caption: str) -> bool:
        if img is None:
            return False
        img.seek(0)
        try:
            await bot.send_photo(chat_id=chat_id, photo=img, caption=caption)
            return True
        except Exception:
            logger.exception("start showcase photo failed")
            try:
                img.seek(0)
                await bot.send_photo(chat_id=chat_id, photo=img)
                await bot.send_message(chat_id=chat_id, text=caption)
                return True
            except Exception:
                logger.exception("start showcase photo fallback failed")
                return False

    if free_col or prem_col:
        await bot.send_message(chat_id=chat_id, text=t(wiki_lang, "start_free_header"))
        free_cap = t(
            wiki_lang,
            "start_free_showcase",
            delay=FREE_ALERT_DELAY_MINUTES,
        )
        if free_col and not await _send_photo(free_col, free_cap):
            await bot.send_message(chat_id=chat_id, text=t(wiki_lang, "start_showcase_skip"))

    if prem_col:
        await bot.send_message(chat_id=chat_id, text=t(wiki_lang, "start_premium_header"))
        prem_cap = t(
            wiki_lang,
            "start_premium_showcase",
            stars=PREMIUM_STARS_PRICE,
            days=PREMIUM_BILLING_DAYS,
        )
        if not await _send_photo(prem_col, prem_cap):
            await bot.send_message(chat_id=chat_id, text=t(wiki_lang, "start_showcase_skip"))

    if not free_col and not prem_col:
        await bot.send_message(chat_id=chat_id, text=t(wiki_lang, "start_showcase_skip"))

    await bot.send_message(
        chat_id=chat_id,
        text=t(wiki_lang, "start_showcase_footer") + "\n\n" + t(wiki_lang, "disclaimer_short"),
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if update.effective_user:
        record_start(update.effective_user.id)
    if context.args:
        param = context.args[0].strip().lower()
        if param in {"social", "social_x", "social_reddit", "social_discord"}:
            await social_command(update, context)
            return
    wiki_lang = lang if lang in {"ru", "en"} else "en"
    intro = build_start_intro_fast(wiki_lang)
    await update.message.reply_text(intro, reply_markup=menu_keyboard(lang))
    await send_plan_showcase(context.bot, update.effective_chat.id, wiki_lang)
    track_background_task(
        context.application,
        send_start_followup(update, context, lang),
        "start-followup",
    )


async def disclaimer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    text = t(lang, "disclaimer_full")
    if LEGAL_URL:
        text += "\n\n" + t(lang, "disclaimer_terms", url=LEGAL_URL)
    if SUPPORT_EMAIL:
        text += "\n\n" + t(lang, "disclaimer_contact", email=SUPPORT_EMAIL)
    await update.message.reply_text(text, reply_markup=menu_keyboard(lang))


async def donate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not donate_configured():
        await update.message.reply_text(t(lang, "donate_unset"), reply_markup=menu_keyboard(lang))
        return

    blocks: list[str] = []
    if DONATE_ETH:
        blocks.append(f"{t(lang, 'donate_eth')}\n`{DONATE_ETH}`")
    if DONATE_BTC:
        blocks.append(f"{t(lang, 'donate_btc')}\n`{DONATE_BTC}`")
    if DONATE_TON:
        blocks.append(f"{t(lang, 'donate_ton')}\n`{DONATE_TON}`")

    text = t(lang, "donate_title") + "\n\n" + t(lang, "donate_body", addresses="\n\n".join(blocks))

    # Кликабельные кнопки-кошельки. MetaMask открывает экран отправки;
    # Rabby не поддерживает deep-link отправки, поэтому ведём на приложение
    # (адрес EVM тот же). Bitcoin — на mempool.space (адрес + QR).
    buttons: list[list[InlineKeyboardButton]] = []
    if DONATE_ETH:
        buttons.append(
            [
                InlineKeyboardButton(
                    t(lang, "donate_btn_metamask"), url=metamask_send_url(DONATE_ETH)
                ),
                InlineKeyboardButton(t(lang, "donate_btn_rabby"), url="https://rabby.io"),
            ]
        )
    if DONATE_BTC:
        buttons.append(
            [InlineKeyboardButton(t(lang, "donate_btn_btc"), url=btc_explorer_url(DONATE_BTC))]
        )
    if DONATE_TON:
        buttons.append(
            [InlineKeyboardButton(t(lang, "donate_btn_ton"), url=ton_transfer_url(DONATE_TON))]
        )

    # Markdown — чтобы адреса в `обратных кавычках` копировались по тапу.
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else menu_keyboard(lang),
    )


async def social_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    link = bot_link()
    links = configured_social_links()
    buttons: list[list[InlineKeyboardButton]] = [[InlineKeyboardButton(t(lang, "social_btn_bot"), url=link)]]
    for item in links:
        buttons.append([InlineKeyboardButton(t(lang, item.btn_key), url=item.url)])

    if links:
        text = t(lang, "social_title") + "\n\n" + t(lang, "social_body", bot_link=link)
    else:
        text = t(lang, "social_unset", bot_link=link)

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def partners_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    partners = configured_partners()
    if not partners:
        await update.message.reply_text(
            t(lang, "partners_unset"),
            reply_markup=menu_keyboard(lang),
        )
        return
    lines = [t(lang, "partners_title"), "", t(lang, "partners_body")]
    buttons: list[list[InlineKeyboardButton]] = []
    for partner in partners:
        lines.append(f"• {t(lang, partner.desc_key)}")
        buttons.append([InlineKeyboardButton(t(lang, partner.btn_key), url=partner.url)])
    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(buttons),
        disable_web_page_preview=True,
    )


async def share_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await update.message.reply_text(t(lang, "share_forbidden"), reply_markup=menu_keyboard(lang))
        return

    args = [a.lower() for a in (context.args or [])]
    if len(args) == 1 and args[0] == "schedule":
        try:
            from social_schedule import format_schedule_text

            body = format_schedule_text()
        except ImportError:
            body = "Upload social_schedule.py to enable /share schedule"
        await update.message.reply_text(body, reply_markup=menu_keyboard(lang))
        return

    if len(args) >= 2 and args[0] == "collage" and args[1] == "tiers":
        from plan_showcase import (
            build_start_showcase_images,
            format_social_tiers_summary,
            get_showcase_sets,
        )

        lang = user_lang(update)
        wiki_lang = lang if lang in {"ru", "en"} else "en"
        free_sigs, prem_sigs = get_showcase_sets()
        free_col, prem_col = build_start_showcase_images(free_sigs, prem_sigs, wiki_lang)
        summary = format_social_tiers_summary(wiki_lang)
        await update.message.reply_text(f"📋 Social tiers summary:\n\n{summary}")
        chat_id = update.effective_chat.id
        if free_col:
            free_col.seek(0)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=free_col,
                caption="🆓 Free · 2× Strategy BUY cards (/start preview)",
            )
        if prem_col:
            prem_col.seek(0)
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=prem_col,
                caption="⭐ Premium · 5 whale signal cards (/start preview)",
            )
        if not free_col and not prem_col:
            await update.message.reply_text(t(lang, "start_showcase_skip"))
        await update.message.reply_text(
            "Tip: run `python3 scripts/export_social_tiers.py --lang "
            f"{wiki_lang}` to save PNG + text to assets/social/"
        )
        return

    if len(args) < 2:
        await update.message.reply_text(
            t(lang, "share_usage", help=list_share_options()),
            reply_markup=menu_keyboard(lang),
        )
        return

    variant = args[2] if len(args) > 2 else None
    try:
        body = format_share_message(args[0], args[1], variant=variant)
    except ValueError as exc:
        await update.message.reply_text(
            f"{exc}\n\n{list_share_options()}",
            reply_markup=menu_keyboard(lang),
        )
        return

    label = f"{args[0]} / {args[1]}"
    if variant:
        label += f" / {variant}"
    await update.message.reply_text(f"📋 Copy for {label}:\n\n{body}")


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
        format_treasury_block(stats, lang, "holdings_title") + donate_footer(lang),
        reply_markup=menu_keyboard(lang),
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    stats = await build_treasury_stats()
    if not stats:
        await update.message.reply_text(t(lang, "status_fetch_fail"), reply_markup=menu_keyboard(lang))
        return
    await update.message.reply_text(
        format_stats_block(stats, lang) + donate_footer(lang),
        reply_markup=menu_keyboard(lang),
    )


def user_plan_for_update(update: Update) -> PlanId:
    """Тариф пользователя; admin (X_CHAT_ID) всегда premium для полного доступа."""
    uid = update.effective_user.id if update.effective_user else None
    chat_id = update.effective_chat.id if update.effective_chat else None
    if is_admin(uid, chat_id):
        return PlanId.PREMIUM
    return effective_plan(uid)


async def whales_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    plan = user_plan_for_update(update)
    top_n = whales_top_n_for_plan(plan)
    await update.message.reply_text(t(lang, "whales_fetching"), reply_markup=menu_keyboard(lang))
    entries, notes = await collect_whale_rankings()
    text = format_whales_message(
        entries, lang, format_btc=format_btc, notes=notes, top_n=top_n
    )
    await update.message.reply_text(text + donate_footer(lang), reply_markup=menu_keyboard(lang))


async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    free = PLANS[PlanId.FREE]
    premium = PLANS[PlanId.PREMIUM]
    text = t(
        lang,
        "plans_body",
        delay=free.strategy_alert_delay_minutes,
        free_top=free.whales_top_n,
        premium_top=premium.whales_top_n,
        price=PREMIUM_PRICE_USD_DEFAULT,
        stars=PREMIUM_STARS_PRICE,
    )
    if promo_active():
        st = promo_status()
        text += "\n\n" + t(
            lang,
            "founding_promo_plans_line",
            remaining=st.remaining,
            max_slots=st.max_slots,
            days=st.promo_days,
        )
    markup = subscribe_action_keyboard(
        lang,
        update.effective_user.id if update.effective_user else 0,
        update.effective_chat.id if update.effective_chat else 0,
    )
    await update.message.reply_text(
        t(lang, "plans_title") + "\n\n" + text + donate_footer(lang),
        reply_markup=markup,
    )


def subscribe_action_keyboard(lang: str, user_id: int, chat_id: int) -> InlineKeyboardMarkup | ReplyKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    show_founding = eligible_for_founding(user_id) and not is_admin(user_id, chat_id)
    if show_founding:
        st = promo_status()
        rows.append(
            [
                InlineKeyboardButton(
                    t(
                        lang,
                        "subscribe_btn_founding",
                        days=FOUNDING_PROMO_DAYS,
                        remaining=st.remaining,
                        max_slots=st.max_slots,
                    ),
                    callback_data=FOUNDING_PROMO_CALLBACK,
                )
            ]
        )
    if stars_payments_enabled() and not show_founding:
        rows.append(
            [
                InlineKeyboardButton(
                    t(
                        lang,
                        "subscribe_btn_pay",
                        stars=PREMIUM_STARS_PRICE,
                        days=PREMIUM_BILLING_DAYS,
                    ),
                    callback_data=SUBSCRIBE_PAY_CALLBACK,
                )
            ]
        )
    if rows:
        return InlineKeyboardMarkup(rows)
    return menu_keyboard(lang)


def founding_promo_confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t(
                        lang,
                        "subscribe_btn_founding_confirm",
                        days=FOUNDING_PROMO_DAYS,
                    ),
                    callback_data=FOUNDING_PROMO_CONFIRM_CALLBACK,
                )
            ],
            [
                InlineKeyboardButton(
                    t(lang, "subscribe_btn_founding_cancel"),
                    callback_data=FOUNDING_PROMO_CANCEL_CALLBACK,
                )
            ],
        ]
    )


def append_subscribe_payment_hint(lang: str, offer: str) -> str:
    if not stars_payments_enabled():
        return offer
    return offer + "\n\n" + t(
        lang,
        "subscribe_offer_pay_hint",
        price=PREMIUM_PRICE_USD_DEFAULT,
        stars=PREMIUM_STARS_PRICE,
        days=PREMIUM_BILLING_DAYS,
    )


def subscribe_action_keyboard(
    lang: str,
    *,
    extend: bool = False,
    extend_date: str = "",
    extend_days: int = 0,
) -> str:
    premium = PLANS[PlanId.PREMIUM]
    body = t(
        lang,
        "subscribe_offer_body",
        premium_top=premium.whales_top_n,
        price=PREMIUM_PRICE_USD_DEFAULT,
        stars=PREMIUM_STARS_PRICE,
        days=PREMIUM_BILLING_DAYS,
    )
    parts = [t(lang, "subscribe_offer_title"), body]
    if extend:
        parts.insert(
            1,
            t(
                lang,
                "subscribe_offer_extend",
                date=extend_date,
                days=extend_days,
                billing_days=PREMIUM_BILLING_DAYS,
                stars=PREMIUM_STARS_PRICE,
            ),
        )
    return "\n\n".join(parts)


async def issue_premium_invoice(
    bot: Bot,
    chat_id: int,
    user_id: int,
    lang: str,
) -> tuple[bool, str | None]:
    """Отправить Stars-инвойс. (ok, error_key_or_message)."""
    try:
        await asyncio.wait_for(
            send_premium_invoice(
                bot,
                chat_id,
                user_id,
                title=t(lang, "subscribe_invoice_title"),
                description=t(
                    lang,
                    "subscribe_invoice_description",
                    days=PREMIUM_BILLING_DAYS,
                ),
                price_label=t(lang, "subscribe_price_label", days=PREMIUM_BILLING_DAYS),
            ),
            timeout=25.0,
        )
        logger.info(
            "premium invoice sent user=%s chat=%s stars=%s days=%s",
            user_id,
            chat_id,
            PREMIUM_STARS_PRICE,
            PREMIUM_BILLING_DAYS,
        )
        return True, None
    except asyncio.TimeoutError:
        logger.error("send_invoice timeout user=%s chat=%s", user_id, chat_id)
        return False, "subscribe_timeout"
    except Exception as exc:
        logger.exception("send_invoice failed user=%s", user_id)
        return False, str(exc)


async def subscribe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if message is None or user is None or chat is None:
        logger.warning("subscribe: update without message/user/chat")
        return

    lang = user_lang(update)
    uid = user.id
    chat_id = chat.id
    logger.info("subscribe_command start user=%s chat=%s type=%s", uid, chat_id, chat.type)

    if chat.type != "private":
        await message.reply_text(t(lang, "subscribe_private_only"), reply_markup=menu_keyboard(lang))
        return

    if not stars_payments_enabled() and not promo_active():
        await message.reply_text(t(lang, "payments_disabled"), reply_markup=menu_keyboard(lang))
        return

    sub = get_subscriber(uid)
    extend = sub is not None and sub.is_active_premium() and bool(sub.expires_at)
    remaining = days_remaining(sub) if extend else None
    offer = build_subscribe_offer_text(
        lang,
        extend=extend,
        extend_date=sub.expires_at[:10] if extend and sub and sub.expires_at else "",
        extend_days=remaining if remaining is not None else 0,
    )
    admin = is_admin(uid, chat_id)
    show_founding = promo_active() and eligible_for_founding(uid) and not admin
    if show_founding:
        st = promo_status()
        offer += "\n\n" + t(
            lang,
            "founding_promo_offer",
            remaining=st.remaining,
            max_slots=st.max_slots,
            days=FOUNDING_PROMO_DAYS,
        )
    elif promo_active() and admin:
        st = promo_status()
        offer += "\n\n" + t(
            lang,
            "founding_promo_admin_info",
            claimed=st.claimed,
            max_slots=st.max_slots,
            remaining=st.remaining,
        )
    elif user_claimed_founding(uid):
        slot = user_claim_slot(uid)
        offer += "\n\n" + t(lang, "founding_promo_already", slot=slot or 0)
    if not show_founding:
        offer = append_subscribe_payment_hint(lang, offer)
    if admin:
        offer = t(lang, "subscribe_admin_banner") + "\n\n" + offer
    await message.reply_text(
        offer,
        reply_markup=subscribe_action_keyboard(lang, uid, chat_id),
    )


async def subscribe_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or query.data != SUBSCRIBE_PAY_CALLBACK:
        return

    user = query.from_user
    message = query.message
    if user is None or message is None:
        return

    lang = user_lang(update)
    uid = user.id
    chat_id = message.chat_id

    if message.chat.type != "private":
        await query.answer(t(lang, "subscribe_private_only"), show_alert=True)
        return

    if not stars_payments_enabled():
        await query.answer(t(lang, "payments_disabled"), show_alert=True)
        return

    if is_admin(uid, chat_id):
        sub = get_subscriber(uid)
        if sub and sub.is_active_premium():
            await query.answer()
            await message.reply_text(
                t(lang, "subscribe_admin_skip"),
                reply_markup=menu_keyboard(lang),
            )
            return

    await query.answer()
    await message.reply_text(t(lang, "subscribe_pay_opening"))

    ok, err = await issue_premium_invoice(context.bot, chat_id, uid, lang)
    if ok:
        await message.reply_text(
            t(lang, "subscribe_invoice_sent"),
            reply_markup=menu_keyboard(lang),
        )
    elif err == "subscribe_timeout":
        await message.reply_text(t(lang, "subscribe_timeout"), reply_markup=menu_keyboard(lang))
    else:
        logger.warning("subscribe invoice failed user=%s: %s", uid, err)
        await message.reply_text(
            t(lang, "subscribe_invoice_error"),
            reply_markup=menu_keyboard(lang),
        )


async def founding_promo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: показать экран подтверждения акции."""
    query = update.callback_query
    if query is None or query.data != FOUNDING_PROMO_CALLBACK:
        return

    user = query.from_user
    message = query.message
    if user is None or message is None:
        return

    lang = user_lang(update)
    uid = user.id
    chat_id = message.chat_id

    if message.chat.type != "private":
        await query.answer(t(lang, "subscribe_private_only"), show_alert=True)
        return

    if is_admin(uid, chat_id):
        await query.answer(t(lang, "founding_promo_admin_skip"), show_alert=True)
        return

    if not eligible_for_founding(uid):
        await query.answer()
        if not promo_active():
            await message.reply_text(t(lang, "founding_promo_exhausted"), reply_markup=menu_keyboard(lang))
        elif user_claimed_founding(uid):
            await message.reply_text(
                t(lang, "founding_promo_already", slot=user_claim_slot(uid) or 0),
                reply_markup=menu_keyboard(lang),
            )
        elif effective_plan(uid) == PlanId.PREMIUM:
            await message.reply_text(t(lang, "founding_promo_has_premium"), reply_markup=menu_keyboard(lang))
        else:
            await message.reply_text(t(lang, "founding_promo_disabled"), reply_markup=menu_keyboard(lang))
        return

    st = promo_status()
    await query.answer()
    await message.reply_text(
        t(
            lang,
            "founding_promo_confirm",
            days=FOUNDING_PROMO_DAYS,
            next_slot=st.claimed + 1,
            max_slots=st.max_slots,
        ),
        reply_markup=founding_promo_confirm_keyboard(lang),
        parse_mode="Markdown",
    )


async def founding_promo_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: активация акции после явного подтверждения."""
    query = update.callback_query
    if query is None or query.data != FOUNDING_PROMO_CONFIRM_CALLBACK:
        return

    user = query.from_user
    message = query.message
    if user is None or message is None:
        return

    lang = user_lang(update)
    uid = user.id
    chat_id = message.chat_id

    if message.chat.type != "private":
        await query.answer(t(lang, "subscribe_private_only"), show_alert=True)
        return

    if is_admin(uid, chat_id):
        await query.answer(t(lang, "founding_promo_admin_skip"), show_alert=True)
        return

    await query.answer()
    result = try_claim_founding_premium(uid)

    if result.status == "ok" and result.sub:
        expires = result.sub.expires_at[:10] if result.sub.expires_at else "—"
        remaining = days_remaining(result.sub)
        await message.edit_reply_markup(reply_markup=None)
        await message.reply_text(
            t(
                lang,
                "founding_promo_success",
                slot=result.slot or 0,
                max_slots=promo_status().max_slots,
                days=FOUNDING_PROMO_DAYS,
                expires=expires,
                remaining=remaining if remaining is not None else 0,
            ),
            reply_markup=menu_keyboard(lang),
        )
        return

    if result.status == "already_claimed":
        await message.reply_text(
            t(lang, "founding_promo_already", slot=result.slot or user_claim_slot(uid) or 0),
            reply_markup=menu_keyboard(lang),
        )
        return

    if result.status == "already_premium":
        await message.reply_text(t(lang, "founding_promo_has_premium"), reply_markup=menu_keyboard(lang))
        return

    if result.status == "exhausted":
        await message.reply_text(t(lang, "founding_promo_exhausted"), reply_markup=menu_keyboard(lang))
        return

    await message.reply_text(t(lang, "founding_promo_disabled"), reply_markup=menu_keyboard(lang))


async def founding_promo_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or query.data != FOUNDING_PROMO_CANCEL_CALLBACK:
        return

    lang = user_lang(update)
    await query.answer()
    message = query.message
    if message is not None:
        try:
            await message.delete()
        except Exception:
            await message.edit_reply_markup(reply_markup=None)


async def mysub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    uid = update.effective_user.id
    plan = user_plan_for_update(update)
    sub = get_subscriber(uid)

    if plan == PlanId.PREMIUM:
        if is_admin(uid, update.effective_chat.id):
            body = t(lang, "mysub_admin_premium")
        elif sub and sub.expires_at:
            remaining = days_remaining(sub)
            body = t(
                lang,
                "mysub_premium_until",
                date=sub.expires_at[:10],
                days=remaining if remaining is not None else 0,
            )
        else:
            body = t(lang, "mysub_premium")
    else:
        if sub and sub.plan == PlanId.PREMIUM and sub.expires_at:
            body = t(lang, "mysub_expired", date=sub.expires_at[:10])
        else:
            free_plan = PLANS[PlanId.FREE]
            body = t(
                lang,
                "mysub_free",
                delay=free_plan.strategy_alert_delay_minutes,
                free_top=free_plan.whales_top_n,
            )

    if user_claimed_founding(uid):
        slot = user_claim_slot(uid)
        body += "\n\n" + t(lang, "mysub_founding_badge", slot=slot or 0)

    await update.message.reply_text(
        t(lang, "mysub_title") + "\n\n" + body + "\n\n" + (
            t(lang, "mysub_admin_hint")
            if is_admin(uid, update.effective_chat.id)
            else t(lang, "mysub_hint")
        ),
        reply_markup=menu_keyboard(lang),
    )


async def setsub_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: выдать или отозвать premium вручную."""
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return

    args = [a.strip().lower() for a in (context.args or []) if a.strip()]
    if not args:
        await update.message.reply_text(t(lang, "setsub_usage"), reply_markup=menu_keyboard(lang))
        return

    target_uid = update.effective_user.id
    idx = 0
    if args[0].isdigit():
        target_uid = int(args[0])
        idx = 1

    if idx >= len(args):
        await update.message.reply_text(t(lang, "setsub_usage"), reply_markup=menu_keyboard(lang))
        return

    action = args[idx]
    if action == "free":
        revoke_subscription(target_uid)
        await update.message.reply_text(
            t(lang, "setsub_revoked", user_id=target_uid),
            reply_markup=menu_keyboard(lang),
        )
        return

    if action != "premium":
        await update.message.reply_text(t(lang, "setsub_usage"), reply_markup=menu_keyboard(lang))
        return

    days = 30
    if idx + 1 < len(args):
        try:
            days = max(1, int(args[idx + 1]))
        except ValueError:
            await update.message.reply_text(t(lang, "setsub_invalid_days"), reply_markup=menu_keyboard(lang))
            return

    sub = grant_premium_days(target_uid, days)
    await update.message.reply_text(
        t(
            lang,
            "setsub_granted",
            user_id=target_uid,
            days=days,
            expires=sub.expires_at[:10] if sub.expires_at else "—",
        ),
        reply_markup=menu_keyboard(lang),
    )


async def successful_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    payment = update.message.successful_payment if update.message else None
    if payment is None or update.effective_user is None:
        return

    charge_id = payment.telegram_payment_charge_id
    if payment_already_processed(charge_id):
        sub = get_subscriber(update.effective_user.id)
        expires = sub.expires_at[:10] if sub and sub.expires_at else "—"
        remaining = days_remaining(sub) if sub else 0
        await update.message.reply_text(
            t(
                lang,
                "payment_already_processed",
                expires=expires,
                remaining=remaining if remaining is not None else 0,
            ),
            reply_markup=menu_keyboard(lang),
        )
        return

    sub = fulfill_premium_payment(payment, update.effective_user.id)
    if sub is None:
        await update.message.reply_text(
            t(lang, "payment_failed", email=SUPPORT_EMAIL or "support"),
            reply_markup=menu_keyboard(lang),
        )
        return

    expires = sub.expires_at[:10] if sub.expires_at else "—"
    remaining = days_remaining(sub)
    await update.message.reply_text(
        t(
            lang,
            "payment_success",
            days=PREMIUM_BILLING_DAYS,
            expires=expires,
            remaining=remaining if remaining is not None else 0,
        ),
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
    header = t(
        lang,
        "help_body",
        version=BOT_VERSION,
        free_top=PLANS[PlanId.FREE].whales_top_n,
        premium_top=PLANS[PlanId.PREMIUM].whales_top_n,
        btn_status=t(lang, "btn_status"),
        btn_check=t(lang, "btn_check"),
        btn_baseline=t(lang, "btn_baseline"),
        btn_language=t(lang, "btn_language"),
        btn_hide_menu=t(lang, "btn_hide_menu"),
    )
    wiki = format_help_wiki(lang if lang in {"ru", "en"} else "en")
    help_text = f"{header}\n\n{wiki}"
    if donate_configured():
        help_text += "\n\n" + t(lang, "donate_footer")
    if social_links_configured():
        help_text += "\n" + t(lang, "social_footer")
    site_line = site_link_line(lang)
    if site_line:
        help_text += "\n" + site_line
    help_text += "\n\n" + t(lang, "disclaimer_short")
    help_text += "\n" + t(lang, "help_wiki_note")

    chat_id = update.effective_chat.id
    if len(help_text) <= 4096:
        await update.message.reply_text(help_text, reply_markup=menu_keyboard(lang))
    else:
        await update.message.reply_text(header, reply_markup=menu_keyboard(lang))
        await context.bot.send_message(chat_id=chat_id, text=wiki)
        footer = t(lang, "disclaimer_short") + "\n" + t(lang, "help_wiki_note")
        await context.bot.send_message(chat_id=chat_id, text=footer, reply_markup=menu_keyboard(lang))


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
        await context.bot.send_message(
            chat_id=alert_chat_id(),
            text=t(alert_lang(), "testalert_message") + donate_footer(alert_lang()),
        )
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
    site_result = await run_strategy_site_check(context.bot, lang=lang, send_alerts=False)
    severity, _kind, result = await run_holdings_check(context.bot, lang=lang, send_alerts=False)
    company_lines = await run_companies_check(context.bot, lang=lang, send_alerts=False)
    etf_lines = await run_etf_check(context.bot, lang=lang, send_alerts=False)
    lines = [t(lang, "check_holdings_line", result=result)]
    if site_result:
        lines.append(t(lang, "check_site_line", result=site_result))
    if company_lines:
        lines.append(t(lang, "check_companies_line", result="; ".join(company_lines)))
    if etf_lines:
        lines.append(t(lang, "check_etf_line", result="; ".join(etf_lines)))
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

    previous_state = load_holdings_state()
    test_btc = holdings["btc"] - max(MIN_BTC_CHANGE * 10, 100)
    save_holdings_state(
        {"name": holdings["name"], "btc": test_btc, "usd": 0.0, "source": "purchase-check-test"}
    )
    await update.message.reply_text(
        t(lang, "simulate_purchase_setup", btc=format_btc(test_btc)),
        reply_markup=menu_keyboard(lang),
    )
    try:
        severity, kind, result = await run_holdings_check(context.bot, lang=lang, send_alerts=False)
    finally:
        if previous_state:
            save_holdings_state(previous_state)
        else:
            save_holdings_state(holdings)
    emoji = "✅" if severity == "ok" and kind in ("purchase_sent", "sale_sent", "would_alert") else "ℹ️"
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

    previous_state = load_holdings_state()
    test_btc = holdings["btc"] + max(MIN_BTC_CHANGE * 10, 100)
    save_holdings_state(
        {"name": holdings["name"], "btc": test_btc, "usd": 0.0, "source": "sale-check-test"}
    )
    await update.message.reply_text(
        t(lang, "simulate_sale_setup", btc=format_btc(test_btc)),
        reply_markup=menu_keyboard(lang),
    )
    try:
        severity, kind, result = await run_holdings_check(context.bot, lang=lang, send_alerts=False)
    finally:
        if previous_state:
            save_holdings_state(previous_state)
        else:
            save_holdings_state(holdings)
    emoji = "✅" if severity == "ok" and kind in ("purchase_sent", "sale_sent", "would_alert") else "ℹ️"
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
    message = update.effective_message
    if message is None:
        return
    try:
        from transactions import list_transactions

        commit = os.getenv("RENDER_GIT_COMMIT", "N/A")
        instance = os.getenv("RENDER_INSTANCE_ID", "N/A")
        uptime_value = datetime.datetime.now() - start_time
        stats = get_analytics()
        last_visit = stats.last_visit[:19].replace("T", " ") if stats.last_visit else "—"
        msg = (
            f"🧠 Bot Information\n"
            f"Commit: {commit}\n"
            f"Instance: {instance}\n"
            f"Uptime: {uptime_value}\n"
            f"Monitor interval: {MONITOR_INTERVAL_SECONDS}s\n"
            f"Alive ping enabled: {ENABLE_ALIVE_PING}\n"
            f"Strategy.com monitor: {ENABLE_STRATEGY_SITE}\n"
            f"Stars payments: {stars_payments_enabled()} ({PREMIUM_STARS_PRICE} ⭐ / {PREMIUM_BILLING_DAYS}d)\n"
            f"Alert gating: {gating_enabled()} (free delay {FREE_ALERT_DELAY_MINUTES}m)\n"
            f"Weekly digest: {digest_enabled()} (Sun {WEEKLY_DIGEST_HOUR}:{WEEKLY_DIGEST_MINUTE:02d} {WEEKLY_DIGEST_TIMEZONE})\n"
            f"Site URL: {SITE_URL or '—'}\n"
            f"Trade journal: {len(list_transactions())} entries\n"
            f"Bot version: {BOT_VERSION}\n"
            f"Server Time: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}\n\n"
            f"📊 Analytics\n"
            f"Unique users (/start): {stats.unique_users}\n"
            f"Total /start presses: {stats.total_starts}\n"
            f"Premium active: {stats.active_premium}\n"
            f"Paid via Stars: {stats.paid_subscriptions} ({stats.stars_earned} ⭐)\n"
            f"Founding promo: {promo_status().claimed}/{promo_status().max_slots} "
            f"({promo_status().remaining} left)\n"
            f"Last visit: {last_visit} UTC"
        )
        await message.reply_text(msg, reply_markup=menu_keyboard(lang))
    except Exception as exc:
        logger.exception("info failed")
        await message.reply_text(
            t(lang, "botstats_error", error=str(exc)),
            reply_markup=menu_keyboard(lang),
        )


WEEKLY_EXPORT_PREFIX = "weekly_exp:"


def weekly_export_keyboard(lang: str) -> InlineKeyboardMarkup:
    prefix = WEEKLY_EXPORT_PREFIX
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(t(lang, "weekly_export_pdf"), callback_data=f"{prefix}pdf"),
                InlineKeyboardButton(t(lang, "weekly_export_html"), callback_data=f"{prefix}html"),
            ],
            [
                InlineKeyboardButton(t(lang, "weekly_export_csv"), callback_data=f"{prefix}csv"),
                InlineKeyboardButton(t(lang, "weekly_export_table"), callback_data=f"{prefix}table"),
            ],
        ]
    )


def _weekly_export_label(lang: str, fmt: str) -> str:
    key = {
        "pdf": "weekly_export_pdf",
        "html": "weekly_export_html",
        "csv": "weekly_export_csv",
        "table": "weekly_export_table",
    }.get(fmt, "weekly_export_pdf")
    return t(lang, key)


async def weekly_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = user_lang(update)
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_admin(uid, chat_id) and effective_plan(uid) != PlanId.PREMIUM:
        await update.message.reply_text(
            t(lang, "weekly_premium_only"),
            reply_markup=menu_keyboard(lang),
        )
        return
    await update.message.reply_text(
        t(lang, "weekly_fetching"),
        reply_markup=menu_keyboard(lang),
    )
    try:
        sent, data = await deliver_weekly_digest(
            context.bot,
            [uid],
            update_snapshot=False,
        )
        if sent and data:
            cache_weekly_digest(uid, data)
            await update.message.reply_text(
                t(lang, "weekly_sent", period=data.period_label),
                reply_markup=menu_keyboard(lang),
            )
            await update.message.reply_text(
                t(lang, "weekly_export_prompt"),
                reply_markup=weekly_export_keyboard(lang),
            )
        else:
            await update.message.reply_text(
                t(lang, "weekly_fail"),
                reply_markup=menu_keyboard(lang),
            )
    except Exception as exc:
        logger.exception("weekly command failed")
        await update.message.reply_text(
            t(lang, "weekly_fail"),
            reply_markup=menu_keyboard(lang),
        )


async def weekly_export_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query is None or not query.data or not query.data.startswith(WEEKLY_EXPORT_PREFIX):
        return
    await query.answer()
    lang = user_lang(update)
    uid = query.from_user.id
    chat_id = query.message.chat.id if query.message else uid
    if not is_admin(uid, chat_id) and effective_plan(uid) != PlanId.PREMIUM:
        await query.message.reply_text(
            t(lang, "weekly_premium_only"),
            reply_markup=menu_keyboard(lang),
        )
        return

    fmt = query.data[len(WEEKLY_EXPORT_PREFIX) :]
    if fmt not in {"pdf", "html", "csv", "table"}:
        return
    label = _weekly_export_label(lang, fmt)
    data = get_cached_weekly_digest(uid)
    if data is None:
        await query.message.reply_text(
            t(lang, "weekly_export_expired"),
            reply_markup=menu_keyboard(lang),
        )
        return

    await query.message.reply_text(
        t(lang, "weekly_export_building", label=label),
        reply_markup=menu_keyboard(lang),
    )
    try:
        export = build_weekly_export(data, fmt, lang)
        bio = io.BytesIO(export.content)
        bio.name = export.filename
        await context.bot.send_document(
            chat_id=chat_id,
            document=bio,
            caption=t(lang, "weekly_export_sent", label=label, period=data.period_label),
        )
    except Exception:
        logger.exception("weekly export failed fmt=%s user=%s", fmt, uid)
        await query.message.reply_text(
            t(lang, "weekly_export_fail"),
            reply_markup=menu_keyboard(lang),
        )


async def botstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: счётчики посещений и подписок."""
    lang = user_lang(update)
    if not is_admin(update.effective_user.id, update.effective_chat.id):
        await deny_admin(update)
        return
    message = update.effective_message
    if message is None:
        return
    try:
        stats = get_analytics()
        last_visit = stats.last_visit[:19].replace("T", " ") if stats.last_visit else "—"
        text = t(
            lang,
            "botstats_body",
            unique=stats.unique_users,
            starts=stats.total_starts,
            premium_active=stats.active_premium,
            premium_total=stats.total_premium_ever,
            paid=stats.paid_subscriptions,
            stars=stats.stars_earned,
            last_visit=last_visit,
            founding_claimed=promo_status().claimed,
            founding_max=promo_status().max_slots,
            founding_remaining=promo_status().remaining,
        )
        await message.reply_text(text, reply_markup=menu_keyboard(lang))
    except Exception as exc:
        logger.exception("botstats failed")
        await message.reply_text(
            t(lang, "botstats_error", error=str(exc)),
            reply_markup=menu_keyboard(lang),
        )


async def on_bot_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled bot error: %s", context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            lang = user_lang(update)
            await update.effective_message.reply_text(
                t(lang, "bot_error"),
                reply_markup=menu_keyboard(lang),
            )
        except Exception:
            pass


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
    elif action == "baseline":
        await reset_baseline(update, context)
    elif action == "plans":
        await plans_command(update, context)
    elif action == "subscribe":
        await subscribe_command(update, context)
    elif action == "help":
        await help_command(update, context)
    elif action == "language":
        await show_language_menu(update, lang)
    elif action == "hide_menu":
        await update.message.reply_text(t(lang, "hide_menu"), reply_markup=ReplyKeyboardRemove())
    elif action == "back":
        lang = user_lang(update)
        intro = await build_start_text(lang)
        await update.message.reply_text(intro, reply_markup=menu_keyboard(lang))


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
    token = os.environ.get("HEALTHCHECK_TOKEN", "").strip()
    if token and request.query.get("token") != token:
        return web.Response(text="Forbidden", status=403)
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
    write_log("🕵️ Мониторинг Strategy + компании + ETF")
    while True:
        try:
            reset_monitor_dedupe()
            global last_monitor_error
            site_note = await run_strategy_site_check(bot, lang=alert_lang())
            _severity, _kind, result = await run_holdings_check(bot, lang=alert_lang())
            company_notes = await run_companies_check(bot, lang=alert_lang())
            etf_notes = await run_etf_check(bot, lang=alert_lang())
            parts = [f"Strategy: {result}"]
            if site_note:
                parts.append(f"site: {site_note}")
            if company_notes:
                parts.append(f"companies: {'; '.join(company_notes)}")
            if etf_notes:
                parts.append(f"etf: {'; '.join(etf_notes)}")
            write_log(f"Monitor: {' | '.join(parts)}")
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

    write_log(f"🚀 SaylorWatchBot {BOT_VERSION}")
    write_log(
        f"⭐ Stars payments: enabled={stars_payments_enabled()} "
        f"price={PREMIUM_STARS_PRICE} days={PREMIUM_BILLING_DAYS}"
    )
    write_log(
        f"🔐 Subscription gating: {gating_enabled()} "
        f"(free delay {FREE_ALERT_DELAY_MINUTES} min)"
    )
    try:
        from free_tier_perks import perks_summary_for_admin

        write_log(f"🎁 Free tier perks: {perks_summary_for_admin()}")
    except Exception as exc:
        logger.warning("Free tier perks summary failed: %s", exc)
    if digest_enabled():
        write_log(
            f"📊 Weekly digest: Sun {WEEKLY_DIGEST_HOUR}:{WEEKLY_DIGEST_MINUTE:02d} "
            f"{WEEKLY_DIGEST_TIMEZONE}"
        )
        track_background_task(
            application,
            weekly_digest_scheduler(application.bot, log_fn=write_log),
            "weekly-digest",
        )
    if reminders_enabled():
        write_log(
            f"⏳ Premium expiry reminders: daily {REMINDER_HOUR}:{REMINDER_MINUTE:02d} "
            f"{REMINDER_TIMEZONE} (3/2/1 days before)"
        )
        track_background_task(
            application,
            subscription_reminder_scheduler(application.bot, log_fn=write_log),
            "premium-expiry-reminders",
        )

    from free_alert_queue import flush_due_alerts, free_alert_queue_scheduler

    n_queued = await flush_due_alerts(application.bot)
    if n_queued:
        write_log(f"📬 Free alert queue flushed on startup: {n_queued}")
    track_background_task(
        application,
        free_alert_queue_scheduler(application.bot, log_fn=write_log),
        "free-alert-queue",
    )

    if paper_wallet_enabled():
        write_log(
            f"📰 Paper Wallet channel: daily {PAPER_WALLET_POST_HOUR}:"
            f"{PAPER_WALLET_POST_MINUTE:02d} {PAPER_WALLET_TIMEZONE} → "
            f"{os.environ.get('PAPER_WALLET_CHANNEL', '@Paper_wallet_co')}"
        )
        track_background_task(
            application,
            paper_wallet_scheduler(application.bot, log_fn=write_log),
            "paper-wallet",
        )

    try:
        from social_schedule import reminder_enabled, social_x_reminder_scheduler

        if reminder_enabled():
            write_log("📅 X @paper_wallet_co post reminders: daily (see SOCIAL_X_REMINDER_*)")
            track_background_task(
                application,
                social_x_reminder_scheduler(application.bot, log_fn=write_log),
                "social-x-reminders",
            )
    except ImportError:
        pass

    track_background_task(application, start_healthcheck_server(), "healthcheck-server")
    track_background_task(application, monitor_saylor_purchases(application.bot), "holdings-monitor")
    if ENABLE_ALIVE_PING:
        track_background_task(application, ping_alive(application.bot), "alive-ping")

    write_log("🧩 post_init complete")

    try:
        from plan_showcase import showcase_enabled, warm_start_showcase_cache

        if showcase_enabled():

            async def _warm_showcase_cache() -> None:
                try:
                    write_log("🖼 Warming start showcase cache (background)…")
                    n = await asyncio.to_thread(warm_start_showcase_cache)
                    write_log(f"🖼 Start showcase cache ready ({n} collages)")
                except Exception as exc:
                    logger.exception("Showcase cache warm failed")
                    write_log(f"⚠️ Showcase cache warm failed: {exc}")

            track_background_task(application, _warm_showcase_cache(), "start-showcase-warm")
    except ImportError:
        pass


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
    app.add_handler(CommandHandler("whales", whales_command))
    app.add_handler(CommandHandler("plans", plans_command))
    app.add_handler(CommandHandler("mysub", mysub_command))
    app.add_handler(CommandHandler("subscribe", subscribe_command))
    app.add_handler(CallbackQueryHandler(subscribe_pay_callback, pattern=f"^{SUBSCRIBE_PAY_CALLBACK}$"))
    app.add_handler(CallbackQueryHandler(founding_promo_callback, pattern=f"^{FOUNDING_PROMO_CALLBACK}$"))
    app.add_handler(
        CallbackQueryHandler(founding_promo_confirm_callback, pattern=f"^{FOUNDING_PROMO_CONFIRM_CALLBACK}$")
    )
    app.add_handler(
        CallbackQueryHandler(founding_promo_cancel_callback, pattern=f"^{FOUNDING_PROMO_CANCEL_CALLBACK}$")
    )
    app.add_handler(CommandHandler("weekly", weekly_command))
    app.add_handler(
        CallbackQueryHandler(weekly_export_callback, pattern=f"^{WEEKLY_EXPORT_PREFIX}")
    )
    app.add_handler(CommandHandler("setsub", setsub_command))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_command))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("baseline", reset_baseline))
    app.add_handler(CommandHandler("checkbuy", simulate_purchase_check))
    app.add_handler(CommandHandler("checksell", simulate_sale_check))
    app.add_handler(CommandHandler("uptime", uptime))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("info", info))
    app.add_handler(CommandHandler("botstats", botstats_command))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("site", site))
    app.add_handler(CommandHandler("donate", donate_command))
    app.add_handler(CommandHandler("social", social_command))
    app.add_handler(CommandHandler("partners", partners_command))
    app.add_handler(CommandHandler("share", share_command))
    app.add_handler(CommandHandler("disclaimer", disclaimer_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("lang", language_command))
    app.add_handler(CommandHandler("chatid", chatid))
    app.add_handler(CommandHandler("testalert", testalert))
    app.add_handler(CommandHandler("check", check_now))
    app.add_handler(CommandHandler("setbaseline", setbaseline))
    app.add_error_handler(on_bot_error)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_message))
    app.run_polling()
