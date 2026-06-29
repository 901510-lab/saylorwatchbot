"""Справочник команд и возможностей @Saylor_w_bot — источник истины для email FAQ."""

from __future__ import annotations

import re
from typing import Callable, TypedDict

from faq_normalize import looks_like_question

# Пользовательские команды (main.py BOT_COMMANDS, без admin-only)
VALID_BOT_COMMANDS: frozenset[str] = frozenset({
    "start", "holdings", "stats", "buy", "status", "site", "whales", "plans",
    "mysub", "subscribe", "weekly", "donate", "social", "disclaimer", "language",
    "lang", "help", "chatid",
})

ADMIN_ONLY_COMMANDS: frozenset[str] = frozenset({
    "check", "baseline", "testalert", "checkbuy", "checksell", "botstats", "setsub",
    "share", "restart", "clear", "uptime", "info", "setbaseline",
})

FORBIDDEN_COMMAND_PHRASES: tuple[str, ...] = (
    "/all alerts",
    "all alerts",
    "/companies",
    "/company",
    "/companies command",
    "/price",
    "/alert",
    "/notifications",
    "/etf",
)

# Команды, которых нет — отдельные ответы при вопросе «что значит /…»
NONEXISTENT_COMMANDS: frozenset[str] = frozenset({
    "companies", "company", "all", "price", "alert", "notifications", "etf", "alerts",
})

# Spot ETF в entities.json (источник: Farside / SoSoValue fallback)
TRACKED_ETF_TICKERS: tuple[str, ...] = ("IBIT", "FBTC", "GBTC", "ARKB")
TRACKED_ETF_NAMES: tuple[str, ...] = (
    "BlackRock IBIT",
    "Fidelity FBTC",
    "Grayscale GBTC",
    "ARK 21Shares ARKB",
)

# Публичные компании (CoinGecko), кроме Strategy
TRACKED_COMPANY_NAMES: tuple[str, ...] = (
    "Tesla",
    "Block",
    "MARA Holdings",
    "Riot Platforms",
    "Metaplanet",
)


def tracked_etf_summary(lang: str) -> str:
    """Сколько ETF и какие тикеры — для playbook / email."""
    n = len(TRACKED_ETF_TICKERS)
    tickers = ", ".join(TRACKED_ETF_TICKERS)
    if lang == "ru":
        return (
            f"В анализе бота {n} US spot Bitcoin ETF: {tickers}.\n"
            "Данные: дневные net-потоки (Farside; при блокировке — SoSoValue).\n"
            "В рейтинге /whales — AUM в BTC; алерты по потокам — Premium, автоматически."
        )
    return (
        f"The bot tracks {n} US spot Bitcoin ETFs: {tickers}.\n"
        "Data: daily net flows (Farside; SoSoValue fallback if blocked).\n"
        "/whales shows AUM in BTC; flow alerts are Premium, automatic."
    )


def is_etf_coverage_question(blob: str) -> bool:
    """Вопрос «сколько/какие ETF в боте» — кириллица ЕТФ и латиница."""
    low = blob.lower()
    if re.search(r"(сколько|какие|how many|which|what)\s+.{0,30}(етф|etf)\b", low):
        return True
    if re.search(r"\b(етф|etf)\b.{0,40}(входит|в бот|анализ|отслеж|track|cover|include|list)", low):
        return True
    if "сколько" in low and ("етф" in low or " etf" in low):
        return True
    return False


def is_companies_coverage_question(blob: str) -> bool:
    low = blob.lower()
    if re.search(r"(сколько|какие|how many|which)\s+.{0,35}(компани|company|корпорац)", low):
        return True
    if re.search(r"\b(компани|company)\w*.{0,40}(входит|в бот|анализ|отслеж|track|cover|include|list)", low):
        return True
    return False


def is_privacy_question(blob: str) -> bool:
    low = blob.lower()
    if any(w in low for w in ("private key", "seed phrase", "сид-фраз", "сид фраз")):
        return True
    if "приватн" in low and any(w in low for w in ("ключ", "кошелек", "кошельк", "wallet")):
        return True
    return False


def is_exchange_bot_question(blob: str) -> bool:
    low = blob.lower()
    if "биржа" in low or " exchange" in low:
        return True
    if is_retail_buy_bitcoin_question(low):
        return True
    if any(w in low for w in ("купить btc", "купить bitcoin", "buy bitcoin", "buy btc")):
        if "bot" in low or "бот" in low or "saylorwatch" in low or "telegram" in low:
            return True
    return False


def is_retail_buy_bitcoin_question(blob: str) -> bool:
    """Покупка BTC как инвестиция — не команда /buy (последняя покупка Strategy)."""
    low = blob.lower()
    buy_markers = (
        "как buy ",
        "где buy ",
        "how to buy",
        "where to buy",
        "buy bitcoin",
        "buy btc",
        "purchase bitcoin",
        "купить bitcoin",
        "купить btc",
        "купить битко",
        "приобрести bitcoin",
        "приобрести btc",
    )
    if not any(m in low for m in buy_markers):
        return False
    if "/buy" in low:
        return False
    if any(
        w in low
        for w in (
            "premium",
            "премиум",
            "subscribe",
            "подписк",
            "stars",
            "тариф",
            "plans",
        )
    ):
        return False
    strategy_buy = (
        "strategy",
        "saylor",
        "сайлор",
        "стратег",
        "последн",
        "latest",
        "крайн",
        "недавн",
        "команд",
        "command",
        "покупк strategy",
        "purchase strategy",
    )
    if any(w in low for w in strategy_buy):
        return False
    return True


def is_bot_created_question(blob: str) -> bool:
    low = blob.lower()
    when = (
        "когда создан",
        "когда запущ",
        "дата создан",
        "дата запуск",
        "when created",
        "when launched",
        "when was",
        "launch date",
        "since when",
        "с какого",
    )
    if not any(w in low for w in when):
        return False
    return any(w in low for w in (" bot ", "бот", "saylorwatch", "saylor watch"))


def is_start_command_question(blob: str) -> bool:
    low = blob.lower()
    if "/start" in low:
        return True
    if re.search(r"команда\s+start", low) or re.search(r"command\s+start", low):
        return True
    if any(w in low for w in ("означает", "значит", "what does", "what is", "зачем")):
        if " start" in low or low.endswith(" start") or " start?" in low:
            return True
    if re.search(r"зачем\s+.{0,24}start", low):
        return True
    return False


def is_free_tier_question(blob: str) -> bool:
    low = blob.lower()
    if re.search(r"что\s+.{0,12}free", low):
        return True
    if "что бесплатн" in low or "what is free" in low or "what's free" in low:
        return True
    return False


# Тикеры в еженедельном дайджесте (entities.json + Strategy)
WEEKLY_CORP_TICKERS: tuple[str, ...] = (
    "MSTR",
    "TSLA",
    "XYZ",
    "MARA",
    "RIOT",
    "3350.T",
)


def weekly_report_tickers_summary(lang: str) -> str:
    """Какие тикеры в еженедельном отчёте — для playbook / Ollama."""
    corps = ", ".join(WEEKLY_CORP_TICKERS)
    etfs = ", ".join(TRACKED_ETF_TICKERS)
    if lang == "ru":
        return (
            "В еженедельном отчёте за 7 дней по каждому тикеру: покупки/продажи BTC, "
            "нетто, баланс казны; по ETF — недельные net-потоки.\n"
            f"• Казны: {corps} (Strategy + Tesla, Block, MARA, Riot, Metaplanet)\n"
            f"• US spot ETF: {etfs}\n"
            "• Плюс: изменение цены BTC за неделю и крупнейшее движение казны.\n"
            "Premium — PNG (/weekly); Free — краткий текст по воскресеньям ~12:00 NY."
        )
    return (
        "The weekly report covers the past 7 days per ticker: BTC buys/sells, net, "
        "treasury balance; ETFs show weekly net flows.\n"
        f"• Treasuries: {corps} (Strategy + Tesla, Block, MARA, Riot, Metaplanet)\n"
        f"• US spot ETFs: {etfs}\n"
        "• Plus: BTC spot week change and largest treasury mover.\n"
        "Premium — PNG (/weekly); Free — short text Sundays ~12:00 NY."
    )


def is_weekly_report_question(blob: str) -> bool:
    """Вопрос о содержании/тикерах еженедельного отчёта (в т.ч. «трикеры», «отчёт»)."""
    low = blob.lower()
    weekly_markers = (
        "weekly", "digest", " report", "недельн", "еженедельн",
        "hebdomadaire", "week report", "weekly report",
    )
    content_markers = (
        "ticker", "тикер", "трикер", "symbol", "символ",
        "какие", "какой", "what", "which", "сколько", "содерж", "входит",
        "список", "list", "покаж", "будут", "включ",
    )
    has_weekly = any(w in low for w in weekly_markers)
    has_content = any(w in low for w in content_markers)
    if has_weekly and has_content:
        return True
    if re.search(r"(тикер|трикер|ticker).{0,45}(недельн|weekly|report|digest|сводк|отчет|отчёт)", low):
        return True
    if re.search(r"(недельн|weekly|report|digest|сводк|отчет|отчёт).{0,45}(тикер|трикер|ticker)", low):
        return True
    if "еженедельн" in low and any(w in low for w in ("отчет", "отчёт", "сводк", "дайджест")):
        return True
    return False


def tracked_companies_summary(lang: str) -> str:
    n = len(TRACKED_COMPANY_NAMES)
    names = ", ".join(TRACKED_COMPANY_NAMES)
    if lang == "ru":
        return (
            f"Плюс Strategy (MSTR): всего {n + 1} корпоративных казн в мониторинге.\n"
            f"Другие публичные компании ({n}): {names}.\n"
            "Алерты по покупкам/продажам — Premium, автоматически. Рейтинг: /whales."
        )
    return (
        f"Plus Strategy (MSTR): {n + 1} corporate treasuries tracked.\n"
        f"Other public companies ({n}): {names}.\n"
        "Buy/sell alerts — Premium, automatic. Ranking: /whales."
    )


class CommandSpec(TypedDict):
    scope: str  # user | admin
    ru: str
    en: str
    alt_ru: str
    alt_en: str


COMMAND_SPECS: dict[str, CommandSpec] = {
    "start": {
        "scope": "user",
        "ru": "Приветствие и главное меню: статус Strategy, строка «Цена BTC», кнопки. После первого /start в личном чате алерты включаются автоматически.",
        "en": "Welcome and main menu: Strategy status, BTC price line, buttons. After first /start in a private chat, alerts are enabled automatically.",
        "alt_ru": "",
        "alt_en": "",
    },
    "help": {
        "scope": "user",
        "ru": "Полный список команд бота (пользовательских и admin).",
        "en": "Full bot command list (user and admin).",
        "alt_ru": "",
        "alt_en": "",
    },
    "holdings": {
        "scope": "user",
        "ru": "Обзор BTC-казны Strategy: баланс, стоимость.",
        "en": "Strategy BTC treasury overview: balance and value.",
        "alt_ru": "",
        "alt_en": "",
    },
    "stats": {
        "scope": "user",
        "ru": "Детальная статистика Strategy: средняя цена покупки, PnL, рыночная стоимость, spot-цена BTC (CoinGecko).",
        "en": "Detailed Strategy stats: average purchase price, PnL, market value, BTC spot price (CoinGecko).",
        "alt_ru": "",
        "alt_en": "",
    },
    "buy": {
        "scope": "user",
        "ru": "Последняя зафиксированная покупка BTC Strategy.",
        "en": "Latest recorded Strategy BTC purchase.",
        "alt_ru": "",
        "alt_en": "",
    },
    "status": {
        "scope": "user",
        "ru": "Статус бота (online), аптайм, баланс Strategy и baseline для алертов — основная команда для пользователей вместо /info.",
        "en": "Bot status (online), uptime, Strategy balance and alert baseline — main user command instead of /info.",
        "alt_ru": "",
        "alt_en": "",
    },
    "site": {
        "scope": "user",
        "ru": "Сырые последние данные с strategy.com.",
        "en": "Raw latest data from strategy.com.",
        "alt_ru": "",
        "alt_en": "",
    },
    "whales": {
        "scope": "user",
        "ru": "Рейтинг крупнейших BTC-казн (Strategy, компании, ETF). Free: топ-7, Premium: топ-10.",
        "en": "Ranking of largest BTC treasuries. Free: top 7, Premium: top 10.",
        "alt_ru": "",
        "alt_en": "",
    },
    "plans": {
        "scope": "user",
        "ru": "Сравнение Free vs Premium: алерты, задержка, карточки, компании, ETF, /weekly.",
        "en": "Compare Free vs Premium: alerts, delay, cards, companies, ETF, /weekly.",
        "alt_ru": "",
        "alt_en": "",
    },
    "mysub": {
        "scope": "user",
        "ru": "Ваш текущий тариф и срок подписки Premium.",
        "en": "Your current plan and Premium expiry.",
        "alt_ru": "",
        "alt_en": "",
    },
    "subscribe": {
        "scope": "user",
        "ru": "Оплата Premium через Telegram Stars или активация promo (365 дней). Только в личном чате с @Saylor_w_bot.",
        "en": "Premium via Telegram Stars or founding promo (365 days). Private chat with @Saylor_w_bot only.",
        "alt_ru": "",
        "alt_en": "",
    },
    "weekly": {
        "scope": "user",
        "ru": "Premium: PNG-дайджест по запросу; также авто по воскресеньям ~12:00 NY.",
        "en": "Premium: on-demand PNG digest; also auto Sundays ~12:00 NY.",
        "alt_ru": "",
        "alt_en": "",
    },
    "donate": {
        "scope": "user",
        "ru": "Адреса BTC, ETH и TON (Gram) для поддержки сервера.",
        "en": "BTC, ETH and TON (Gram) addresses to support the server.",
        "alt_ru": "",
        "alt_en": "",
    },
    "social": {
        "scope": "user",
        "ru": "Ссылки на X (Twitter) и Reddit.",
        "en": "Links to X (Twitter) and Reddit.",
        "alt_ru": "",
        "alt_en": "",
    },
    "disclaimer": {
        "scope": "user",
        "ru": "Юридический дисклеймер: информация, не инвестиционный совет.",
        "en": "Legal disclaimer: informational only, not investment advice.",
        "alt_ru": "",
        "alt_en": "",
    },
    "language": {
        "scope": "user",
        "ru": "Выбор языка интерфейса (EN, RU, ES, DE, FR, ZH, JA, PT).",
        "en": "UI language selection (EN, RU, ES, DE, FR, ZH, JA, PT).",
        "alt_ru": "",
        "alt_en": "",
    },
    "lang": {
        "scope": "user",
        "ru": "То же, что /language — выбор языка интерфейса.",
        "en": "Same as /language — UI language selection.",
        "alt_ru": "",
        "alt_en": "",
    },
    "chatid": {
        "scope": "user",
        "ru": "Показывает ваш Telegram User ID и Chat ID (нужно для настройки admin-доступа на сервере).",
        "en": "Shows your Telegram User ID and Chat ID (used for admin access setup on the server).",
        "alt_ru": "",
        "alt_en": "",
    },
    "info": {
        "scope": "admin",
        "ru": (
            "Служебная команда администратора (не в публичном меню Telegram). "
            "Показывает: версию/commit, uptime, интервал мониторинга, настройки Stars/Premium/дайджеста, "
            "аналитику (уникальные пользователи, /start, активный Premium, Stars, founding promo)."
        ),
        "en": (
            "Admin-only diagnostics (not in the public Telegram menu). "
            "Shows: version/commit, uptime, monitor interval, Stars/Premium/digest settings, "
            "analytics (unique users, /start count, active Premium, Stars, founding promo)."
        ),
        "alt_ru": "Обычным пользователям недоступна — бот ответит «Только для админа». Для статуса Strategy: /status · Список команд: /help",
        "alt_en": "Not available to regular users — bot replies «Admin only». For Strategy status: /status · Commands: /help",
    },
    "check": {
        "scope": "admin",
        "ru": "Admin: принудительно запустить проверку Strategy, strategy.com, компаний и ETF.",
        "en": "Admin: force-run Strategy, strategy.com, company and ETF checks.",
        "alt_ru": "Только admin. Пользователям: /status или дождаться автоматических алертов после /start.",
        "alt_en": "Admin only. Users: /status or wait for automatic alerts after /start.",
    },
    "baseline": {
        "scope": "admin",
        "ru": "Admin: сбросить baseline Strategy на текущий live-баланс (для алертов о покупках/продажах).",
        "en": "Admin: reset Strategy alert baseline to current live balance.",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "setbaseline": {
        "scope": "admin",
        "ru": "Admin: установить baseline вручную (число BTC) или с live-данных.",
        "en": "Admin: set alert baseline manually (BTC amount) or from live data.",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "checkbuy": {
        "scope": "admin",
        "ru": "Admin: тест алерта о покупке Strategy (симуляция).",
        "en": "Admin: test Strategy purchase alert (simulation).",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "checksell": {
        "scope": "admin",
        "ru": "Admin: тест алерта о продаже Strategy (симуляция).",
        "en": "Admin: test Strategy sale alert (simulation).",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "testalert": {
        "scope": "admin",
        "ru": "Admin: отправить тестовое уведомление в alert-чат.",
        "en": "Admin: send a test notification to the alert chat.",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "botstats": {
        "scope": "admin",
        "ru": "Admin: аналитика — пользователи, Premium, Stars, founding promo (короче, чем /info).",
        "en": "Admin: analytics — users, Premium, Stars, founding promo (shorter than /info).",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "setsub": {
        "scope": "admin",
        "ru": "Admin: вручную выставить тариф пользователю (тестирование Free/Premium).",
        "en": "Admin: manually set a user's plan (Free/Premium testing).",
        "alt_ru": "Только admin. Пользователям: /subscribe и /mysub.",
        "alt_en": "Admin only. Users: /subscribe and /mysub.",
    },
    "share": {
        "scope": "admin",
        "ru": "Admin: сгенерировать текст для публикации в соцсетях (reddit/twitter и т.д.).",
        "en": "Admin: generate copy-paste text for social posts (reddit/twitter etc.).",
        "alt_ru": "Только admin. Пользователям: /social.",
        "alt_en": "Admin only. Users: /social.",
    },
    "restart": {
        "scope": "admin",
        "ru": "Admin: перезапуск процесса бота на сервере.",
        "en": "Admin: restart the bot process on the server.",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "clear": {
        "scope": "admin",
        "ru": "Admin: удалить последние сообщения бота в чате.",
        "en": "Admin: delete recent bot messages in the chat.",
        "alt_ru": "Только admin.",
        "alt_en": "Admin only.",
    },
    "uptime": {
        "scope": "admin",
        "ru": "Короткий аптайм процесса бота (в /help указана в блоке admin). Для полного статуса Strategy — /status.",
        "en": "Short process uptime (listed under admin in /help). For full Strategy status — /status.",
        "alt_ru": "Для пользователей обычно достаточно /status.",
        "alt_en": "For most users /status is enough.",
    },
}

COMMAND_QUESTION_MARKERS: tuple[str, ...] = (
    "что значит", "что делает", "зачем", "для чего", "что такое команда",
    "what does", "what is the", "what is /", "command mean", "explain the",
    "explain /", "означает", "означают", "расскажите про команд", "про команду /",
    "mean /", "does /", "qu'est-ce que", "à quoi sert",
    "о команд", "про команд", "скажи о команд", "скажите о команд",
    "какая команд", "какой команд", "какую команд", "which command", "what command",
)

BOT_OVERVIEW_MARKERS: tuple[str, ...] = (
    "содержан",
    "что там есть",
    "что там",
    "что умеет",
    "что может",
    "функци",
    "возможност",
    "расскажи о бот",
    "расскажите о бот",
    "описание бота",
    "основные функции",
    "что внутри",
    "какие функции",
    "чем занимается",
    "для чего бот",
    "что есть в бот",
    "что в боте",
    "what features",
    "what can the bot",
    "what can your bot",
    "tell me about the bot",
    "tell me about your bot",
    "bot capabilities",
    "main features",
    "overview of",
    "what's in the bot",
    "what is inside",
    "what does it do",
    "what do you offer",
    "fonctionnalit",
    "à quoi sert le bot",
    "de quoi s'agit",
)


def is_bot_overview_question(blob: str) -> bool:
    """Вопрос «что умеет бот / что внутри / основные функции» — не про одну команду."""
    low = blob.lower()
    if is_command_question(low) and extract_question_command(low):
        return False
    overview_phrases = (
        "что делает ваш бот",
        "что делает бот",
        "что такое saylorwatch",
        "что такое ваш бот",
        "about the bot",
        "about saylorwatch",
        "what is this bot",
        "what is saylorwatch",
        "what does your bot",
        "what does the bot",
    )
    if any(p in low for p in overview_phrases):
        return True
    has_bot = "бот" in low or "bot" in low or "saylorwatch" in low
    if has_bot and any(m in low for m in BOT_OVERVIEW_MARKERS):
        return True
    if any(m in low for m in ("расскаж", "рассказать", "опишите", "describe")) and has_bot:
        return True
    return False


SUBSCRIBE_INTENT_MARKERS: tuple[str, ...] = (
    "activate premium",
    "активац premium",
    "активац премиум",
    "подключить premium",
    "подключить премиум",
    "купить premium",
    "купить премиум",
    "оплатить premium",
    "оплатить премиум",
    "how to subscribe",
    "how do i subscribe",
    "get premium",
    "telegram stars",
    "350 stars",
    "year free",
    "1 year free",
    "/subscribe",
    "/mysub",
    "pay with stars",
    "оплата stars",
    "активировать подписк",
    "оформить premium",
    "оформить премиум",
)


def detect_subscribe_intent(blob: str) -> bool:
    """Вопрос про активацию/оплату Premium — playbook subscribe."""
    low = blob.lower()
    if any(m in low for m in SUBSCRIBE_INTENT_MARKERS):
        return True
    if "premium" in low or "премиум" in low or "подписк" in low:
        if any(
            w in low
            for w in (
                "how",
                "activate",
                "активац",
                "купить",
                "оплат",
                "получить",
                "подключ",
                "оформ",
                "stars",
                "тариф",
            )
        ):
            return True
    return False


def command_cheatsheet_text(*, lang: str = "en", include_admin: bool = True) -> str:
    """Краткая справка по каждой команде — для playbook и Ollama."""
    use_ru = lang == "ru"
    header = "КОМАНДЫ ПОЛЬЗОВАТЕЛЯ:" if use_ru else "USER COMMANDS:"
    lines = [header]
    for cmd in sorted(VALID_BOT_COMMANDS):
        spec = COMMAND_SPECS.get(cmd)
        if not spec:
            continue
        brief = spec["ru"] if use_ru else spec["en"]
        lines.append(f"/{cmd} — {brief}")
    if include_admin:
        admin_hdr = "ТОЛЬКО ADMIN (обычным — /status, /help):" if use_ru else "ADMIN-ONLY (users: /status, /help):"
        lines.append("")
        lines.append(admin_hdr)
        for cmd in sorted(ADMIN_ONLY_COMMANDS):
            spec = COMMAND_SPECS.get(cmd)
            if not spec:
                continue
            brief = (spec["alt_ru"] if use_ru else spec["alt_en"]) or (
                spec["ru"] if use_ru else spec["en"]
            )
            lines.append(f"/{cmd} — {brief}")
    return "\n".join(lines)


def command_cheatsheet_for_llm() -> str:
    """Двуязычная шпаргалка команд для system prompt Ollama."""
    return (
        "=== COMMAND CHEATSHEET (map user intent → these commands only) ===\n"
        + command_cheatsheet_text(lang="en")
        + "\n\n"
        + command_cheatsheet_text(lang="ru")
    )


def command_brief(cmd: str, lang: str) -> str | None:
    """Одна строка о команде — для быстрых ответов."""
    cmd = cmd.lower().strip().lstrip("/")
    if cmd in NONEXISTENT_COMMANDS:
        return _nonexistent_command_reply(cmd, lang)[:200]
    spec = COMMAND_SPECS.get(cmd)
    if not spec:
        return None
    use_ru = lang == "ru"
    title = f"/{cmd}"
    body = spec["ru"] if use_ru else spec["en"]
    if spec["scope"] == "admin":
        alt = (spec["alt_ru"] if use_ru else spec["alt_en"]).strip()
        if alt:
            return f"{title} — {alt}"
        return f"{title} — {body}"
    return f"{title} — {body}"

BOT_KNOWLEDGE_TEMPLATE = """
=== BOT KNOWLEDGE (@Saylor_w_bot) — use ONLY this, never invent ===

WHAT IT IS:
Telegram bot tracking BTC treasury moves: Strategy (MicroStrategy), public companies, US spot ETF flows.
Sources: strategy.com, CoinGecko, Farside/SosoValue (ETF). NOT an exchange or 24/7 price ticker.
NOT A BITCOIN SHOP: the bot does NOT sell or buy BTC for users. /buy = latest Strategy treasury purchase data only.
PUBLIC LAUNCH: June 2026 (@Saylor_w_bot); version string shown in /start welcome line.

USER COMMANDS (only these):
/start — welcome, menu, BTC price line (CoinGecko)
/holdings — Strategy BTC treasury overview
/stats — Strategy: cost basis, PnL, market value, BTC spot price line
/buy — latest Strategy Bitcoin purchase
/status — bot online, Strategy balance, alert baseline
/site — raw latest data from strategy.com
/whales — ranking of largest BTC treasuries (Free: top {free_top}, Premium: top {premium_top})
/plans — compare Free vs Premium features
/mysub — your subscription status
/subscribe — Premium via Telegram Stars (private chat only!)
/weekly — Premium: on-demand weekly PNG digest
/donate — tip BTC / ETH / TON (Gram) addresses
/social — links to X, Reddit & Discord
/disclaimer — legal disclaimer (not investment advice)
/help — full command list
/language or /lang — UI language (EN, RU, ES, DE, FR, ZH, JA, PT)
/chatid — your Telegram user ID

ADMIN COMMANDS (admin Telegram ID only — not in BotFather menu):
/info — full bot diagnostics & analytics
/check — force treasury/ETF/site check
/baseline — reset Strategy alert baseline to live data
/setbaseline — set baseline manually or from live
/checkbuy /checksell — simulate purchase/sale alerts
/testalert — test notification delivery
/botstats — user & subscription analytics
/setsub — set user plan (testing)
/share — generate social post text
/restart /clear — restart bot / delete recent messages
/uptime — short process uptime

COMMANDS THAT DO NOT EXIST:
/all alerts, /companies, /company, /price, /alert, /notifications, /etf, enterprise API

ALERTS (automatic — NO enable command):
After /start once in a private chat, buy/sell messages are pushed automatically.
Free: Strategy (MSTR treasury) only; ~{free_delay} min delay; 1 PNG card/week (+ large trades ≥100 BTC); text weekly summary.
Premium: instant; Strategy + company alerts (Tesla, MARA, Block, Metaplanet, Riot…) +
ETF daily flows (IBIT, FBTC, GBTC, ARKB) + strategy.com press/purchases; PNG image cards.

TRACKED ENTITIES (for «how many» questions):
• Strategy (MSTR) + 5 public companies: Tesla, Block, MARA, Riot, Metaplanet
• 4 US spot BTC ETFs: IBIT, FBTC, GBTC, ARKB
• No /companies or /etf commands — company & ETF alerts are Premium, automatic

PRIVACY (like whale trackers — read-only):
Never asks for private keys or seed phrases. Cannot move customer funds.
Only public treasury/ETF data + Telegram notifications.

PREMIUM & PAYMENT:
{stars} Telegram Stars / {billing_days} days via /subscribe (after founding promo ends).
Launch promo: first {promo_max} users → {promo_days} days Premium FREE:
/subscribe → button «🎁 PROMO: 1 year FREE» → «✅ Yes, activate promo» → /mysub.
/subscribe only works in private chat with @Saylor_w_bot (not in groups).

WEEKLY DIGEST:
Premium: /weekly — send PNG digest on demand.
Also auto-scheduled: Sundays ~12:00 America/New_York to Premium subscribers.
Free: auto text summary same schedule (no /weekly command).
Tickers in weekly report (7-day window): MSTR, TSLA, XYZ, MARA, RIOT, 3350.T + IBIT, FBTC, GBTC, ARKB + BTC spot week change.
Per ticker: corp buy/sell BTC, net, holdings; ETF weekly net flows; largest treasury mover.

FREE vs PREMIUM (summary — details: /plans):
Free: Strategy alerts (~{free_delay}m delay), 1 PNG/week (+ large trades), text weekly, /holdings /stats /status /buy /site, /whales top {free_top}.
Premium: instant alerts, all PNG cards, company+ETF+site alerts, /whales top {premium_top}, /weekly PNG.

SUPPORT EMAIL (SaylorWatch@outlook.com):
Payment disputes, refunds, legal/GDPR, bugs needing investigation — NOT for /subscribe activation.

WHEN CUSTOMER ASKS «what does /command mean»:
Answer about THAT command only. /info is admin-only — say so and point regular users to /status and /help.
Never reply with a generic command list unless they asked for all commands.
""".strip()


def is_command_question(blob: str) -> bool:
    low = blob.lower()
    if re.search(r"/[a-z][a-z0-9]*", low):
        if any(m in low for m in COMMAND_QUESTION_MARKERS):
            return True
        return ("коман" in low or "command" in low) and "/" in low
    return any(m in low for m in COMMAND_QUESTION_MARKERS) and (
        "команд" in low or "command" in low
    )


def detect_natural_command_topic(blob: str) -> str | None:
    """Вопрос про команду без слэша: «какая команда покажет последнюю покупку»."""
    low = blob.lower()
    strategy_ctx = ("saylor", "сайлор", "strategy", "стратег", "битко", "bitcoin", " btc", "btc ")
    buy_q = ("покуп", "buy", "purchase", "купил", "bought", "крайн", "последн", "latest", "недавн")
    alert_ctx = ("алерт", "alert", "уведом", "notification", "оповещ", "notify")
    if any(q in low for q in buy_q) and (
        any(c in low for c in strategy_ctx)
        or any(m in low for m in ("команд", "command"))
        or "/buy" in low
    ):
        if not any(a in low for a in alert_ctx):
            return "buy"
    if any(w in low for w in ("холдинг", "holdings", "казн", "treasury", "баланс strategy")):
        return "holdings"
    if any(w in low for w in ("whale", "кит", "держател", "рейтинг", "топ держ")):
        return "whales"
    return None


def extract_question_command(blob: str) -> str | None:
    m = re.search(r"/([a-z][a-z0-9]*)", blob.lower())
    return m.group(1) if m else None


def detect_command_topic(*, subject: str, body: str) -> str | None:
    blob = f"{subject} {body}".lower()
    cmd = extract_question_command(blob)
    if cmd:
        if is_command_question(blob):
            return f"command:{cmd}"
        subj = subject.strip().lower()
        if subj in {cmd, f"/{cmd}"} or subj.startswith(f"/{cmd} "):
            return f"command:{cmd}"
        cleaned = body.strip().lower()
        if cleaned in {cmd, f"/{cmd}"}:
            return f"command:{cmd}"
        # Короткое письмо с /command (часто тема пустая, в теле только команда + подпись)
        if len(body.strip()) <= 160 and cmd in COMMAND_SPECS:
            return f"command:{cmd}"
    natural = detect_natural_command_topic(blob)
    if natural:
        return natural
    if is_start_command_question(blob):
        return "start"
    return None


def detect_relaxed_faq_topic(*, subject: str, body: str) -> str | None:
    """Fallback: тема письма = команда или /info без текста вопроса."""
    subj = subject.strip()
    subj_low = subj.lower()
    if subj_low.startswith("/"):
        cmd = subj_low[1:].split()[0]
        if cmd:
            return f"command:{cmd}"
    if subj_low in COMMAND_SPECS or subj_low in NONEXISTENT_COMMANDS:
        return f"command:{subj_low}"
    for cmd in re.findall(r"/([a-z][a-z0-9]*)", subj_low):
        return f"command:{cmd}"
    core = body.strip().lower()
    if re.fullmatch(r"/?[a-z][a-z0-9]*", core):
        return f"command:{core.lstrip('/')}"
    if subj_low in {"help", "помощь", "support", "hi", "hello", "привет"}:
        return "help"
    if subj_low in {"о боте", "about bot", "about the bot", "what is the bot"}:
        return "what_is"
    return None


def resolve_faq_topic(*, subject: str, body: str) -> str | None:
    """Fallback: тема = /info, help и т.д. когда тело пустое или только подпись."""
    return detect_relaxed_faq_topic(subject=subject, body=body)


def _nonexistent_command_reply(cmd: str, lang: str) -> str:
    if cmd in {"companies", "company"}:
        if lang == "ru":
            return (
                f"Команды /{cmd} в боте нет.\n\n"
                "Рейтинг BTC-казн: /whales\n"
                "Алерты компаний (Tesla, MARA…) — Premium, автоматически после /start\n"
                "Тарифы: /plans"
            )
        return (
            f"/{cmd} does not exist.\n\n"
            "BTC treasury ranking: /whales\n"
            "Company alerts (Tesla, MARA…) — Premium, automatic after /start\n"
            "Tiers: /plans"
        )
    if cmd in {"etf", "alerts", "all"}:
        if lang == "ru":
            return (
                f"Команды /{cmd} нет.\n\n"
                "Алерты Strategy — автоматически после /start\n"
                "ETF-потоки (IBIT, FBTC…) — Premium, автоматически\n"
                "Тарифы: /plans"
            )
        return (
            f"/{cmd} is not a command.\n\n"
            "Strategy alerts — automatic after /start\n"
            "ETF flows (IBIT, FBTC…) — Premium, automatic\n"
            "Tiers: /plans"
        )
    if lang == "ru":
        return (
            f"Команды /{cmd} в @Saylor_w_bot нет.\n\n"
            "Список команд: /help в боте"
        )
    return f"/{cmd} is not a bot command.\n\nFull list: /help in @Saylor_w_bot"


def multi_faq_playbook_reply(*, subject: str, body: str, lang: str) -> str | None:
    """Составные очевидные вопросы (создание бота + /start, и т.п.)."""
    try:
        from faq_normalize import build_faq_blob
    except ImportError:
        build_faq_blob = lambda **kw: f"{kw.get('subject', '')} {kw.get('body', '')}".lower()

    blob = build_faq_blob(subject=subject, body=body)
    topics: list[str] = []
    for topic, pred in (
        ("not_exchange", is_retail_buy_bitcoin_question(blob)),
        ("bot_created", is_bot_created_question(blob)),
        ("command:start", is_start_command_question(blob)),
    ):
        if pred and topic not in topics:
            topics.append(topic)

    if not topics:
        return None
    if len(topics) == 1 and topics[0] == "command:start":
        return None

    parts: list[str] = []
    for topic in topics:
        block = playbook_text_for_topic(topic, lang)
        if block:
            parts.append(block)
    if not parts:
        return None
    return "\n\n".join(parts)


def multi_command_playbook_reply(*, subject: str, body: str, lang: str) -> str | None:
    """Несколько /команд в одном письме — объединённый ответ."""
    blob = f"{subject}\n{body}".lower()
    if not re.search(r"/[a-z][a-z0-9]*", blob):
        return None
    cmds: list[str] = []
    for m in re.finditer(r"/([a-z][a-z0-9]*)", blob):
        c = m.group(1)
        if c in VALID_BOT_COMMANDS and c not in cmds:
            cmds.append(c)
    if len(cmds) < 2:
        return None
    parts: list[str] = []
    for c in cmds[:5]:
        block = playbook_text_for_topic(f"command:{c}", lang)
        if not block:
            block = command_explanation(c, lang)
        if block:
            parts.append(block)
    if not parts:
        return None
    header = "Команды бота:\n\n" if lang == "ru" else "Bot commands:\n\n"
    return header + "\n\n".join(parts)


def command_explanation(cmd: str, lang: str) -> str:
    cmd = cmd.lower().strip()
    if cmd in NONEXISTENT_COMMANDS:
        return _nonexistent_command_reply(cmd, lang)
    spec = COMMAND_SPECS.get(cmd)
    if not spec:
        return _nonexistent_command_reply(cmd, lang)
    use_ru = lang == "ru"
    title = f"/{cmd}" + (" — команда администратора" if spec["scope"] == "admin" and use_ru else "")
    if spec["scope"] == "admin" and not use_ru:
        title = f"/{cmd} — admin command"
    elif spec["scope"] == "user":
        title = f"/{cmd}" if use_ru else f"/{cmd} command"
    body = spec["ru"] if use_ru else spec["en"]
    alt = (spec["alt_ru"] if use_ru else spec["alt_en"]).strip()
    lines = [title, "", body]
    if alt:
        lines.extend(["", alt])
    if spec["scope"] == "user":
        lines.extend([
            "",
            "1. Telegram → @Saylor_w_bot",
            f"2. /{cmd}",
        ])
    return "\n".join(lines)


def playbook_text_for_topic(topic: str, lang: str) -> str:
    if topic.startswith("command:"):
        return command_explanation(topic.split(":", 1)[1], lang)
    book = FAQ_PLAYBOOKS.get(topic, {})
    text = book.get(lang) or book.get("en", "")
    if topic == "etf" and text:
        text = text.format(etf_summary=tracked_etf_summary(lang))
    if topic == "companies" and text:
        text = text.format(companies_summary=tracked_companies_summary(lang))
    if topic == "weekly" and text:
        text = text.format(weekly_summary=weekly_report_tickers_summary(lang))
    return text


def topic_from_faq_hints(blob: str, *, min_score: int = 2, relaxed: bool = False) -> str | None:
    """Сопоставление по FAQ_TOPIC_HINTS (на нормализованном blob)."""
    best: str | None = None
    best_score = 0
    for topic, hints in FAQ_TOPIC_HINTS.items():
        score = sum(1 for h in hints if h in blob)
        if score > best_score:
            best_score = score
            best = topic
    if best_score >= min_score:
        return best
    if relaxed and best_score >= 1 and len(blob) >= 12:
        if looks_like_question(blob):
            return best
    return None


def bot_knowledge_text(cfg: Callable[[str, str], str] | None = None) -> str:
    get = cfg or (lambda k, d: d)
    return BOT_KNOWLEDGE_TEMPLATE.format(
        stars=get("PREMIUM_STARS", "350"),
        billing_days=get("PREMIUM_BILLING_DAYS", "30"),
        free_delay=get("FREE_ALERT_DELAY_MINUTES", "15"),
        promo_max=get("FOUNDING_PROMO_MAX", "100"),
        promo_days=get("FOUNDING_PROMO_DAYS", "365"),
        free_top="7",
        premium_top="10",
    )


FAQ_PLAYBOOKS: dict[str, dict[str, str]] = {
    "btc_price": {
        "en": (
            "Yes — spot BTC price (CoinGecko) is shown in the bot; SaylorWatch is mainly a "
            "treasury tracker, not a live ticker.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /start — «BTC price: …» in welcome\n"
            "3. Or /stats — «BTC price» line"
        ),
        "ru": (
            "Да — spot-цена BTC (CoinGecko) есть в боте; SaylorWatch — трекер казн, не биржевой тикер.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /start — строка «Цена BTC: …»\n"
            "3. Или /stats — строка «BTC price»"
        ),
    },
    "alerts": {
        "en": (
            "Yes — Strategy buy/sell alerts are automatic after /start in a private chat.\n\n"
            "1. Telegram → @Saylor_w_bot (private chat)\n"
            "2. /start — once\n"
            "3. Alerts arrive on each Strategy move\n\n"
            "Free: Strategy, ~15 min delay, 1 PNG/week, text weekly.\n"
            "Premium: instant + all cards; companies & ETF too — /plans"
        ),
        "ru": (
            "Да — алерты Strategy автоматические после /start в личном чате.\n\n"
            "1. Telegram → @Saylor_w_bot (личный чат)\n"
            "2. /start — один раз\n"
            "3. Сообщения при сделках Strategy\n\n"
            "Free: Strategy, ~15 мин, 1 PNG/нед, текстовая сводка по вс.\n"
            "Premium: мгновенно + карточки; компании и ETF — /plans"
        ),
    },
    "whales": {
        "en": (
            "Yes — /whales ranks the largest BTC treasuries (Strategy, companies, ETFs).\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /whales\n\n"
            "Free: top 7 · Premium: top 10 — /plans"
        ),
        "ru": (
            "Да — /whales показывает рейтинг крупнейших BTC-казн.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /whales\n\n"
            "Free: топ-7 · Premium: топ-10 — /plans"
        ),
    },
    "weekly": {
        "en": (
            "{weekly_summary}\n\n"
            "On demand: /weekly · Auto: Sundays ~12:00 NY.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. Premium: /subscribe · Status: /mysub\n"
            "3. /weekly"
        ),
        "ru": (
            "{weekly_summary}\n\n"
            "По запросу: /weekly · Авто: воскресенье ~12:00 NY.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. Premium: /subscribe · Статус: /mysub\n"
            "3. /weekly"
        ),
    },
    "buy": {
        "en": (
            "Latest Strategy BTC purchase:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /buy\n\n"
            "Live buy/sell alerts: automatic after /start."
        ),
        "ru": (
            "Последняя покупка BTC Strategy (Saylor) — команда /buy:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /buy — дата, объём и цена последней зафиксированной покупки\n\n"
            "Алерты о новых сделках: автоматически после /start."
        ),
    },
    "holdings": {
        "en": (
            "Strategy BTC treasury:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /holdings — balance overview\n"
            "3. /stats — avg price, PnL, BTC price\n"
            "4. /status — balance + alert baseline"
        ),
        "ru": (
            "Казна Strategy (BTC):\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /holdings — баланс\n"
            "3. /stats — ср. цена, PnL, цена BTC\n"
            "4. /status — баланс + baseline алертов"
        ),
    },
    "site": {
        "en": (
            "Raw Strategy data from strategy.com:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /site"
        ),
        "ru": (
            "Данные strategy.com:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /site"
        ),
    },
    "etf": {
        "en": (
            "{etf_summary}\n\n"
            "There is no /etf command — alerts are automatic on Premium.\n\n"
            "1. Telegram → @Saylor_w_bot · /start\n"
            "2. Premium: /subscribe → /mysub\n"
            "3. Compare tiers: /plans · ranking: /whales"
        ),
        "ru": (
            "{etf_summary}\n\n"
            "Команды /etf нет — алерты автоматические на Premium.\n\n"
            "1. Telegram → @Saylor_w_bot · /start\n"
            "2. Premium: /subscribe → /mysub\n"
            "3. Тарифы: /plans · рейтинг: /whales"
        ),
    },
    "companies": {
        "en": (
            "{companies_summary}\n\n"
            "No /companies command — alerts are automatic on Premium.\n\n"
            "1. Telegram → @Saylor_w_bot · /start\n"
            "2. Premium: /subscribe → /mysub\n"
            "3. /plans · /whales"
        ),
        "ru": (
            "{companies_summary}\n\n"
            "Команды /companies нет — алерты автоматические на Premium.\n\n"
            "1. Telegram → @Saylor_w_bot · /start\n"
            "2. Premium: /subscribe → /mysub\n"
            "3. /plans · /whales"
        ),
    },
    "subscribe": {
        "en": (
            "Activate Premium (private chat only):\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /subscribe\n"
            "3. Promo: «🎁 PROMO: 1 year FREE» → «✅ Yes, activate promo (365 days)»\n"
            "4. Or pay: «⭐ Pay 350 Stars · 30 days»\n"
            "5. /mysub"
        ),
        "ru": (
            "Активация Premium (только личный чат):\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /subscribe\n"
            "3. Акция: «🎁 PROMO: 1 year FREE» → «✅ Yes, activate promo (365 days)»\n"
            "4. Или оплата: «⭐ Pay 350 Stars · 30 days»\n"
            "5. /mysub"
        ),
    },
    "promo": {
        "en": (
            "Launch promo: first 100 users get 365 days Premium FREE (no Stars).\n\n"
            "1. Private chat → @Saylor_w_bot\n"
            "2. /subscribe → «🎁 PROMO: 1 year FREE» → confirm\n"
            "3. /mysub — verify\n\n"
            "When spots are full: regular Stars payment via /subscribe."
        ),
        "ru": (
            "Акция запуска: первым 100 — 365 дней Premium бесплатно (без Stars).\n\n"
            "1. Личный чат → @Saylor_w_bot\n"
            "2. /subscribe → «🎁 PROMO: 1 year FREE» → подтвердить\n"
            "3. /mysub — проверить\n\n"
            "Когда места закончатся — оплата Stars через /subscribe."
        ),
    },
    "mysub": {
        "en": "Check subscription:\n\n1. Telegram → @Saylor_w_bot\n2. /mysub",
        "ru": "Статус подписки:\n\n1. Telegram → @Saylor_w_bot\n2. /mysub",
    },
    "plans": {
        "en": (
            "Compare Free vs Premium:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /plans\n\n"
            "Free: Strategy alerts (~15m delay), 1 PNG/week, text weekly, /whales top 7.\n"
            "Premium: instant + all cards, companies, ETF, /whales top 10, /weekly PNG."
        ),
        "ru": (
            "Сравнить тарифы:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /plans\n\n"
            "Free: Strategy (~15 мин), 1 PNG/нед, текст по вс, /whales топ-7.\n"
            "Premium: мгновенно + все карточки, компании, ETF, /whales топ-10, /weekly PNG."
        ),
    },
    "language": {
        "en": "Change UI language:\n\n1. Telegram → @Saylor_w_bot\n2. /language (or /lang)",
        "ru": "Сменить язык:\n\n1. Telegram → @Saylor_w_bot\n2. /language (или /lang)",
    },
    "donate": {
        "en": (
            "Support the project (BTC, ETH, TON/Gram):\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /donate — addresses + wallet buttons"
        ),
        "ru": (
            "Поддержать проект (BTC, ETH, TON/Gram):\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /donate — адреса и кнопки кошельков"
        ),
    },
    "social": {
        "en": "Follow us:\n\n1. Telegram → @Saylor_w_bot\n2. /social — X, Reddit & Discord links",
        "ru": "Соцсети:\n\n1. Telegram → @Saylor_w_bot\n2. /social — X, Reddit и Discord",
    },
    "disclaimer": {
        "en": (
            "Legal disclaimer (not investment advice):\n\n"
            "1. Telegram → @Saylor_w_bot\n2. /disclaimer"
        ),
        "ru": (
            "Юридический дисклеймер (не инвестсовет):\n\n"
            "1. Telegram → @Saylor_w_bot\n2. /disclaimer"
        ),
    },
    "what_is": {
        "en": (
            "SaylorWatch is a Telegram treasury tracker — not an exchange and not a wallet.\n\n"
            "SaylorWatch (@Saylor_w_bot) — Telegram bot for Bitcoin treasury tracking:\n\n"
            "• Strategy: buys/sells, balance, stats (/holdings, /stats, /buy, /status, /site)\n"
            "• Company & US spot ETF flow alerts (Premium) — automatic after /start\n"
            "• Largest BTC holders ranking: /whales (Free: top 7, Premium: top 10)\n"
            "• Premium weekly PNG digest: /weekly · Free: text summary Sundays\n\n"
            "Tiers: Free (Strategy ~15 min, 1 PNG/week, text weekly) vs Premium (instant + all cards) — /plans\n"
            "Subscribe: /subscribe · status: /mysub\n\n"
            "1. Telegram → @Saylor_w_bot → /start\n"
            "2. Full command list: /help"
        ),
        "ru": (
            "SaylorWatch — трекер BTC-казн в Telegram, не биржа и не кошелёк.\n\n"
            "SaylorWatch (@Saylor_w_bot) — Telegram-бот для отслеживания BTC-казн:\n\n"
            "• Strategy: покупки/продажи, баланс, статистика (/holdings, /stats, /buy, /status, /site)\n"
            "• Алерты компаний и US spot ETF (Premium) — автоматически после /start\n"
            "• Рейтинг крупных держателей BTC: /whales (Free: топ-7, Premium: топ-10)\n"
            "• PNG-дайджест Premium: /weekly · Free: текстовая сводка по вс\n\n"
            "Тарифы: Free (Strategy ~15 мин, 1 PNG/нед, текст по вс) vs Premium (мгновенно + все карточки) — /plans\n"
            "Подписка: /subscribe · статус: /mysub\n\n"
            "1. Telegram → @Saylor_w_bot → /start\n"
            "2. Полный список команд: /help"
        ),
        "fr": (
            "SaylorWatch (@Saylor_w_bot) — bot Telegram pour suivre les trésoreries Bitcoin :\n\n"
            "• Strategy : achats/ventes, solde, stats (/holdings, /stats, /buy, /status, /site)\n"
            "• Alertes entreprises & flux ETF spot US (Premium) — automatiques après /start\n"
            "• Classement des plus grands détenteurs BTC : /whales (Free : top 5, Premium : top 10)\n"
            "• Digest hebdo Premium : /weekly\n\n"
            "Offres : Free (alertes Strategy ~30 min) vs Premium (instantané + cartes) — /plans\n"
            "Abonnement : /subscribe · statut : /mysub\n\n"
            "1. Telegram → @Saylor_w_bot → /start\n"
            "2. Liste complète : /help"
        ),
    },
    "privacy": {
        "en": (
            "No — SaylorWatch never asks for private keys, seed phrases, or wallet access.\n\n"
            "The bot only reads public treasury/ETF data and sends Telegram alerts.\n"
            "It cannot move funds or connect to your exchange accounts.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. Features: /help · /plans"
        ),
        "ru": (
            "Нет — SaylorWatch никогда не просит приватные ключи, сид-фразы или доступ к кошельку.\n\n"
            "Бот только читает публичные данные казн/ETF и шлёт алерты в Telegram.\n"
            "Он не может переводить средства и не подключается к биржевым аккаунтам.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. Возможности: /help · /plans"
        ),
    },
    "not_exchange": {
        "en": (
            "SaylorWatch does not sell or buy Bitcoin for you — it is a Telegram treasury tracker, "
            "not an exchange or wallet.\n\n"
            "The bot shows public data: Strategy/company/ETF holdings, alerts, /whales ranking.\n"
            "/buy in the bot = latest Strategy BTC purchase (info only), not a buy order.\n\n"
            "1. Telegram → @Saylor_w_bot → /start\n"
            "2. To buy BTC use a licensed exchange — the bot only displays treasury moves."
        ),
        "ru": (
            "SaylorWatch не продаёт и не покупает биткоин за вас — это Telegram-бот для отслеживания "
            "публичных BTC-казн, а не биржа и не кошелёк.\n\n"
            "Бот показывает данные: казны Strategy/компаний/ETF, алерты, рейтинг /whales.\n"
            "Команда /buy — последняя покупка BTC Strategy (справка), а не покупка через бота.\n\n"
            "1. Telegram → @Saylor_w_bot → /start\n"
            "2. Купить BTC — на лицензированной бирже; бот только показывает движения казн."
        ),
    },
    "bot_created": {
        "en": (
            "SaylorWatch (@Saylor_w_bot) launched publicly in June 2026.\n\n"
            "It tracks Bitcoin treasuries (Strategy, public companies, US spot ETF flows) — "
            "not a trading app. The current build version appears in the /start welcome line.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /start — welcome, menu, BTC price\n"
            "3. Full features: /help · /plans"
        ),
        "ru": (
            "SaylorWatch (@Saylor_w_bot) публично запущен в июне 2026 года.\n\n"
            "Бот отслеживает BTC-казны (Strategy, публичные компании, потоки US spot ETF) — "
            "это не торговое приложение. Текущая версия сборки указана в приветствии /start.\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /start — приветствие, меню, цена BTC\n"
            "3. Возможности: /help · /plans"
        ),
    },
    "help": {
        "en": (
            "Main commands:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /start · /help — menu & BTC price\n"
            "3. Strategy: /holdings · /stats · /buy · /status · /site\n"
            "4. /whales · /plans · /mysub · /subscribe\n"
            "5. Alerts: automatic after /start · Premium: /weekly"
        ),
        "ru": (
            "Основные команды:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /start · /help — меню и цена BTC\n"
            "3. Strategy: /holdings · /stats · /buy · /status · /site\n"
            "4. /whales · /plans · /mysub · /subscribe\n"
            "5. Алерты: после /start · Premium: /weekly"
        ),
    },
}

FAQ_TOPIC_HINTS: dict[str, tuple[str, ...]] = {
    "btc_price": (
        "курс биткоин", "курс btc", "цена биткоин", "цена btc", "bitcoin price", "btc price",
        "spot price", "котировк", "prix bitcoin", "cours bitcoin",
    ),
    "alerts": (
        "алерт", "уведом", "оповещ", "notification", "alert", "получать алерт",
        "when strategy", "когда strategy", "buy/sell alert", "сделк strategy",
    ),
    "whales": (
        "whale", "whales", "кит", "киты", "держател", "ranking", "top holder", "рейтинг",
        "крупнейш", "baleine",
    ),
    "weekly": (
        "weekly", "digest", "дайджест", "hebdomadaire", "сводк",
        "ticker", "weekly report", "week report", "недельн report",
        "еженедельн report", "report ticker",
    ),
    "buy": (
        "last purchase", "latest purchase", "последн покуп", "latest buy", "покупк strategy",
        "крайн покуп", "крайнюю покуп", "покупку сайлор", "покупку saylor", "команд покуп",
        "command purchase", "which command buy", "какая команд покуп",
    ),
    "holdings": (
        "holdings", "treasury", "казн", "баланс strategy", "сколько btc у strategy", "холдинг",
    ),
    "site": ("strategy.com", "/site", "сайт strategy", "official site"),
    "etf": (
        "etf", "етф", "ibit", "fbtc", "gbtc", "arkb", "etf flow", "etf-поток", "биткоин etf",
        "сколько etf", "сколько етф", "какие etf", "какие етф", "how many etf", "which etf",
        "входит в анализ", "в анализ", "в боте", "отслеживает etf", "отслеживает етф",
    ),
    "companies": (
        "tesla", "mara", "block", "metaplanet", "riot", "company alert", "компани",
        "public company", "корпорац", "сколько компани", "какие компани",
        "how many compan", "which compan",
    ),
    "subscribe": (
        "premium", "subscribe", "subscription", "stars", "премиум", "подписк", "купить premium",
        "activate premium", "активир", "оплат",
    ),
    "promo": (
        "promo", "founding", "акци", "бесплатн", "free year", "1 year free", "100 users",
        "launch promo",
    ),
    "mysub": ("mysub", "subscription status", "статус подписк", "окончан подписк"),
    "plans": ("plans", "free vs premium", "тариф", "что входит", "разница free", "free tier", "что free"),
    "language": ("language", "langue", "язык", "english", "russian", "сменить язык", "/lang"),
    "donate": ("donate", "donation", "tip", "don", "пожертв", "поддержать сервер"),
    "social": ("social", "twitter", "reddit", "discord", "x.com", "соцсет", "follow", "дискорд"),
    "disclaimer": ("disclaimer", "legal", "investment advice", "дисклеймер", "не совет"),
    "what_is": (
        "what is", "what does", "что такое", "что делает", "about saylorwatch", "о боте",
        "what is this bot", "содержан", "что там есть", "что там", "функци", "возможност",
        "расскаж", "описание бота", "основные функции", "что внутри", "что в боте",
        "features", "capabilities", "overview", "tell me about", "как работает бот",
        "для чего бот", "зачем бот", "что умеет",
    ),
    "not_exchange": (
        "купить bitcoin", "купить btc", "buy bitcoin", "buy btc", "как купить bitcoin",
        "как купить btc", "how to buy bitcoin", "how to buy btc", "где купить bitcoin",
        "где купить btc", "purchase bitcoin", "не биржа", "not an exchange",
        "продаёт bitcoin", "sell bitcoin",
    ),
    "bot_created": (
        "когда создан", "когда запущ", "дата создан", "дата запуск", "when created",
        "when launched", "launch date", "since when", "с какого времени",
    ),
    "help": (
        "help", "how to start", "commands list", "список команд", "какие команд",
        "all commands", "помощ", "как пользов", "aide", "comment utiliser",
        "с чего начать", "как начать", "как пользоваться",
    ),
    "privacy": (
        "private key", "seed phrase", "сид-фраз", "приватн ключ", "безопасн",
        "move funds", "перевести деньги", "нужен доступ к кошельк",
    ),
}

# (subject, customer_body, playbook_topic, lang) — few-shot для Ollama
CANONICAL_FAQ_SHOTS: list[tuple[str, str, str, str]] = [
    ("Info", "что значит команда /info", "command:info", "ru"),
    ("Re:", "Скажите можно ли узнать в вашем боте курс биткойна?", "btc_price", "ru"),
    ("Alerts", "Как получать алерты когда Strategy покупает биткоин?", "alerts", "ru"),
    ("Whales", "Как посмотреть топ держателей BTC?", "whales", "ru"),
    ("ETF", "Do you alert on IBIT ETF flows?", "etf", "en"),
    (
        "ETF count RU",
        "Скажи сколько ЕТФ входит в твой анализ в боте?",
        "etf",
        "ru",
    ),
    (
        "ETF count EN",
        "How many ETFs does the bot track?",
        "etf",
        "en",
    ),
    ("Premium", "How do I activate Premium?", "subscribe", "en"),
    ("Promo", "Есть ли бесплатная акция на Premium?", "promo", "ru"),
    ("Plans", "What is the difference between Free and Premium?", "plans", "en"),
    ("Companies", "What does /companies do?", "command:companies", "en"),
    ("About", "Что делает ваш бот?", "what_is", "ru"),
    ("Overview", "Расскажи о содержании бота что там есть?", "what_is", "ru"),
    ("Status", "Что делает команда /status?", "command:status", "ru"),
    ("Subscribe RU", "Как активировать Premium через Stars?", "subscribe", "ru"),
    ("Mysub", "How to check if my Premium is active?", "mysub", "en"),
    ("Start", "Зачем нужен /start?", "command:start", "ru"),
    ("Plans RU", "Чем отличается Free от Premium?", "plans", "ru"),
    (
        "Buy command",
        "Скажи о команде которая сообщит мне крайнюю покупку Сайлором Биткойна",
        "buy",
        "ru",
    ),
    (
        "Buy command EN",
        "Which command shows the latest Strategy Bitcoin purchase?",
        "buy",
        "en",
    ),
    (
        "Companies RU",
        "Сколько компаний отслеживает бот кроме Strategy?",
        "companies",
        "ru",
    ),
    (
        "Free tier RU",
        "Что бесплатно в боте?",
        "plans",
        "ru",
    ),
    (
        "Alerts auto RU",
        "Нужно ли включать уведомления отдельной командой?",
        "alerts",
        "ru",
    ),
    (
        "Privacy EN",
        "Do you need my wallet private keys?",
        "privacy",
        "en",
    ),
    (
        "Holdings RU",
        "Где посмотреть сколько BTC у Strategy?",
        "holdings",
        "ru",
    ),
    (
        "Not exchange RU",
        "Это биржа или можно купить биткоин через бота?",
        "what_is",
        "ru",
    ),
    (
        "Buy BTC RU",
        "скажи как купить биткойн",
        "not_exchange",
        "ru",
    ),
    (
        "Buy BTC EN",
        "How can I buy Bitcoin through your bot?",
        "not_exchange",
        "en",
    ),
    (
        "Bot created + start RU",
        "скажи когда создан бот и что означает команда старт?",
        "bot_created",
        "ru",
    ),
    (
        "Start command RU",
        "что означает команда /start",
        "command:start",
        "ru",
    ),
    (
        "Language RU",
        "Можно ли переключить язык интерфейса?",
        "language",
        "ru",
    ),
    (
        "Weekly RU",
        "Есть ли еженедельная сводка?",
        "weekly",
        "ru",
    ),
    (
        "Weekly tickers RU",
        "Скажите какие трикеры будут в недельном отчете?",
        "weekly",
        "ru",
    ),
    (
        "Weekly tickers EN",
        "Which tickers are included in the weekly report?",
        "weekly",
        "en",
    ),
    (
        "Weekly content RU",
        "Что входит в еженедельный дайджест по тикерам?",
        "weekly",
        "ru",
    ),
    (
        "Short help",
        "помощь",
        "help",
        "ru",
    ),
]

PLAYBOOK_NO_PS: frozenset[str] = frozenset({
    "subscribe", "mysub", "plans", "btc_price", "alerts", "whales", "weekly", "buy",
    "holdings", "site", "etf", "companies", "promo", "language", "donate", "social",
    "disclaimer", "what_is", "privacy", "not_exchange", "bot_created",
})
