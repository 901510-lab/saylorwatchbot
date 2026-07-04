"""Справочник команд и возможностей @Saylor_w_bot — источник истины для email FAQ."""

from __future__ import annotations

import re
from typing import Callable, TypedDict

from faq_normalize import looks_like_question

# Пользовательские команды (main.py BOT_COMMANDS, без admin-only)
VALID_BOT_COMMANDS: frozenset[str] = frozenset({
    "start", "holdings", "stats", "buy", "status", "site", "whales", "plans",
    "mysub", "subscribe", "weekly", "donate", "social", "partners", "disclaimer",
    "language", "lang", "help", "chatid",
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


def _word_in_blob(word: str, blob: str) -> bool:
    """Слово целиком — не подстрока внутри «поработаем» и т.п."""
    return bool(re.search(rf"(?:^|[^\w]){re.escape(word)}(?:$|[^\w])", blob, re.IGNORECASE))


def _has_bot_support_context(blob: str) -> bool:
    """Письмо реально про бота — не отклонять как личное."""
    low = blob.lower()
    if any(
        w in low
        for w in (
            "saylor_w_bot",
            "@saylor",
            "/start",
            "/subscribe",
            "/help",
            "/whales",
            "/plans",
            "/mysub",
            "saylorwatch",
            "strategy.com",
        )
    ):
        return True
    if any(
        _word_in_blob(w, low)
        for w in (
            "premium",
            "премиум",
            "подписк",
            "telegram",
            "алерт",
            "alert",
            "strategy",
            "стратег",
            "etf",
            "етф",
            "whale",
            "кит",
            "бот",
            "bot",
        )
    ):
        return True
    return False


def _offtopic_blocked(blob: str) -> bool:
    low = blob.lower()
    if any(
        w in low
        for w in (
            "gdpr",
            "delete my data",
            "удалите данные",
            "персональн данн",
            "personal data",
            "право на забвен",
        )
    ):
        return True
    return _has_bot_support_context(low)


RESUME_LINK_MARKERS: tuple[str, ...] = (
    "linkedin.com",
    "linked.in/in/",
    "hh.ru/resume",
    "headhunter.ru",
    "habr.com/career",
    "jobs.github.com",
    "portfolio",
    "портфолио",
    "резюме",
    "resume",
    "curriculum vitae",
    "cv.pdf",
    "my cv",
    "my resume",
    "attach resume",
    "приложил резюме",
    "прикрепляю резюме",
)

SPAM_OBVIOUS_MARKERS: tuple[str, ...] = (
    "click here",
    "limited time offer",
    "act now",
    "you have won",
    "вы выиграли",
    "congratulations you won",
    "без вложений заработ",
    "passive income guaranteed",
    "guaranteed profit",
    "гарантированн прибыл",
    "seo service",
    "buy followers",
    "накрутка подписчиков",
    "разместите рекламу",
    "buy ad",
    "guest post",
    "sponsored post",
    "продвижение канала",
    "инвестиционная возможность",
    "crypto investment opportunity",
    "winner",
    "unsubscribe",
    "отписаться от рассылки",
)

PERSONAL_SENDER_MARKERS: tuple[str, ...] = (
    "меня зовут",
    "my name is",
    "je m'appelle",
    "i am writing as",
    "мой телефон",
    "my phone",
    "tel:",
    "телефон:",
    "whatsapp",
    "контакт:",
    "отправитель:",
    "я, ",
    "год рождения",
    "date of birth",
)

PERSONAL_ADMIN_MARKERS: tuple[str, ...] = (
    "dear admin",
    "hello admin",
    "hi admin",
    "уважаемый админ",
    "дорогой админ",
    "администратор канала",
    "admin of the channel",
    "channel admin",
    "владелец канала",
    "owner of the channel",
    "автор канала",
    "channel owner",
    "личное письмо",
    "личное сообщение",
    "personal letter",
    "private letter",
    "not about the bot",
    "не про бот",
    "не о боте",
    "ответьте лично",
    "reply personally",
    "write me back personally",
    "напишите мне лично",
)

COLLABORATION_MARKERS: tuple[str, ...] = (
    "сотруднич",
    "collaborat",
    "partnership",
    "партнёрств",
    "партнерств",
    "поработаем",
    "поработать",
    "work together",
    "давайте вместе",
    "над проектом",
    "вашим проектом",
    "your project",
    "предложение о сотрудничестве",
    "business proposal",
    "совместн проект",
    "joint project",
    "мы уже говорили",
    "we already discussed",
    "я хотел бы",
    "i would like to work",
    "хотел бы с вами",
)


def has_resume_or_portfolio_link(blob: str) -> bool:
    low = blob.lower()
    return any(m in low for m in RESUME_LINK_MARKERS)


def has_personal_sender_data(blob: str) -> bool:
    low = blob.lower()
    if any(m in low for m in PERSONAL_SENDER_MARKERS):
        return True
    if re.search(r"\+\d{10,}", low):
        return True
    if re.search(r"\b\d{3}[-.)]\d{3}[-.)]\d{2}[-.)]\d{2}\b", low):
        return True
    return False


def is_obvious_spam_email(blob: str) -> bool:
    """Массовый спам / реклама — короткий авто-отказ."""
    if _offtopic_blocked(blob):
        return False
    low = blob.lower()
    if has_resume_or_portfolio_link(low) and has_personal_sender_data(low):
        if not any(m in low for m in SPAM_OBVIOUS_MARKERS):
            return False
    return any(m in low for m in SPAM_OBVIOUS_MARKERS)


def is_personal_resume_inquiry(blob: str) -> bool:
    """Физлицо + резюме/портфолио, не спам — редкий просмотр админом."""
    if _offtopic_blocked(blob):
        return False
    low = blob.lower()
    if is_obvious_spam_email(blob):
        return False
    if not has_resume_or_portfolio_link(low):
        return False
    if has_personal_sender_data(low):
        return True
    if any(m in low for m in PERSONAL_ADMIN_MARKERS):
        return True
    if any(m in low for m in ("hire me", "job application", "вакансия", "ищу работу", "looking for a job")):
        return True
    return False


def is_generic_personal_offtopic(blob: str) -> bool:
    """Личное админу без резюме или прочий off-topic."""
    if _offtopic_blocked(blob):
        return False
    if is_obvious_spam_email(blob) or is_personal_resume_inquiry(blob):
        return False
    low = blob.lower()
    if any(m in low for m in PERSONAL_ADMIN_MARKERS):
        return True
    if any(m in low for m in COLLABORATION_MARKERS):
        return True
    if len(low.strip()) > 60 and not looks_like_question(low):
        if any(
            w in low
            for w in (
                "пишу вам",
                "writing to you",
                "wanted to reach out",
                "хотел написать",
                "просто хотел",
                "хотел бы",
            )
        ):
            return True
    return False


def detect_offtopic_topic(blob: str) -> str | None:
    """spam_obvious | personal_resume | personal_offtopic | None."""
    if is_obvious_spam_email(blob):
        return "spam_obvious"
    if is_personal_resume_inquiry(blob):
        return "personal_resume"
    if is_generic_personal_offtopic(blob):
        return "personal_offtopic"
    return None


def is_personal_offtopic_email(blob: str) -> bool:
    """Любое письмо вне поддержки бота (включая спам)."""
    return detect_offtopic_topic(blob) is not None


def is_partners_question(blob: str) -> bool:
    low = blob.lower()
    return any(
        m in low
        for m in (
            "/partners",
            "partners command",
            "partner link",
            "partner exchange",
            "referral link",
            "referral code",
            "binance referral",
            "bybit referral",
            "ledger referral",
            "партнёрск",
            "партнерск",
            "реферал",
        )
    )


def is_refund_escalation(blob: str) -> bool:
    low = blob.lower()
    return any(
        m in low
        for m in (
            "refund",
            "chargeback",
            "dispute",
            "возврат",
            "верните деньги",
            "money back",
        )
    )


def is_exchange_bot_question(blob: str) -> bool:
    low = blob.lower()
    if "/partners" in low or "partners command" in low:
        return False
    if any(
        m in low
        for m in (
            "partner link",
            "partner exchange",
            "referral link",
            "referral code",
            "партнёрск",
            "партнерск",
            "реферал",
        )
    ):
        return False
    if "биржа" in low:
        return True
    if " exchange" in low:
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
        "ru": "Мини-вики: полный глоссарий всех команд и кнопок меню (пользовательских и admin).",
        "en": "Mini wiki: full glossary of all commands and menu buttons (user and admin).",
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
        "ru": "Ссылки на X (Twitter), Reddit и Discord.",
        "en": "Links to X (Twitter), Reddit and Discord.",
        "alt_ru": "",
        "alt_en": "",
    },
    "partners": {
        "scope": "user",
        "ru": (
            "Партнёрские ссылки на биржи и кошельки (Binance, Bybit, Ledger и др.) — "
            "если заданы PARTNER_*_URL в .env на сервере."
        ),
        "en": (
            "Partner links to exchanges and wallets (Binance, Bybit, Ledger, etc.) — "
            "when PARTNER_*_URL vars are set on the server."
        ),
        "alt_ru": "Не покупка BTC через бота — только referral-ссылки. Бот не биржа.",
        "alt_en": "Not buying BTC via the bot — referral links only. The bot is not an exchange.",
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

USER_COMMAND_ORDER: tuple[str, ...] = (
    "start",
    "help",
    "holdings",
    "stats",
    "buy",
    "status",
    "site",
    "whales",
    "plans",
    "mysub",
    "subscribe",
    "weekly",
    "donate",
    "social",
    "partners",
    "disclaimer",
    "language",
    "chatid",
)

ADMIN_COMMAND_ORDER: tuple[str, ...] = (
    "check",
    "baseline",
    "setbaseline",
    "checkbuy",
    "checksell",
    "testalert",
    "botstats",
    "setsub",
    "share",
    "info",
    "uptime",
    "clear",
    "restart",
)

MENU_BUTTON_WIKI: dict[str, dict[str, str]] = {
    "holdings": {
        "ru": "Обзор казны Strategy — то же, что /holdings.",
        "en": "Strategy treasury overview — same as /holdings.",
    },
    "stats": {
        "ru": "Статистика Strategy (средняя цена, PnL) — /stats.",
        "en": "Strategy stats (avg price, PnL) — /stats.",
    },
    "status": {
        "ru": "Статус бота и baseline — /status.",
        "en": "Bot status and alert baseline — /status.",
    },
    "check": {
        "ru": "Проверить сейчас — admin: /check (принудительный опрос).",
        "en": "Check now — admin: /check (force poll).",
    },
    "baseline": {
        "ru": "Сброс baseline Strategy — admin: /baseline.",
        "en": "Reset Strategy baseline — admin: /baseline.",
    },
    "help": {
        "ru": "Справочник команд — /help (эта мини-вики).",
        "en": "Command guide — /help (this mini wiki).",
    },
    "plans": {
        "ru": "Сравнение Free vs Premium — /plans.",
        "en": "Compare Free vs Premium — /plans.",
    },
    "subscribe": {
        "ru": "Оформить Premium (Stars) — /subscribe.",
        "en": "Get Premium (Stars) — /subscribe.",
    },
    "language": {
        "ru": "Язык интерфейса — /language.",
        "en": "UI language — /language.",
    },
    "hide_menu": {
        "ru": "Скрыть клавиатуру; вернуть — /start.",
        "en": "Hide keyboard; bring back with /start.",
    },
}


def _wiki_lang(lang: str) -> bool:
    return lang == "ru"


def format_help_wiki(lang: str, *, include_admin: bool = True) -> str:
    """Полный глоссарий команд для /help и email."""
    use_ru = _wiki_lang(lang)
    title = "📖 Мини-вики команд" if use_ru else "📖 Command mini wiki"
    intro = (
        "Краткое описание каждой команды. Алерты включаются после /start в личном чате."
        if use_ru
        else "Short guide to every command. Alerts turn on after /start in a private chat."
    )
    lines = [title, "", intro, ""]

    user_hdr = "👤 Команды пользователя" if use_ru else "👤 User commands"
    lines.append(user_hdr)
    for cmd in USER_COMMAND_ORDER:
        spec = COMMAND_SPECS.get(cmd)
        if not spec:
            continue
        brief = spec["ru"] if use_ru else spec["en"]
        lines.append(f"• /{cmd} — {brief}")
        alt = (spec["alt_ru"] if use_ru else spec["alt_en"]).strip()
        if alt:
            lines.append(f"  ↳ {alt}")
    lines.append("")
    lines.append("/lang — " + ("то же, что /language." if use_ru else "same as /language."))

    if include_admin:
        lines.append("")
        admin_hdr = (
            "🔧 Только admin (не в меню Telegram)"
            if use_ru
            else "🔧 Admin only (not in Telegram menu)"
        )
        lines.append(admin_hdr)
        for cmd in ADMIN_COMMAND_ORDER:
            spec = COMMAND_SPECS.get(cmd)
            if not spec:
                continue
            brief = spec["ru"] if use_ru else spec["en"]
            alt = (spec["alt_ru"] if use_ru else spec["alt_en"]).strip()
            line = f"• /{cmd} — {alt or brief}"
            lines.append(line)

    lines.append("")
    menu_hdr = "⌨️ Кнопки меню" if use_ru else "⌨️ Menu buttons"
    lines.append(menu_hdr)
    for action, spec in MENU_BUTTON_WIKI.items():
        body = spec["ru"] if use_ru else spec["en"]
        lines.append(f"• {action} — {body}")

    lines.append("")
    auto = (
        "🔔 Алерты buy/sell — автоматически после /start (Free: Strategy; Premium: +компании, ETF, strategy.com)."
        if use_ru
        else "🔔 Buy/sell alerts — automatic after /start (Free: Strategy; Premium: +companies, ETF, strategy.com)."
    )
    lines.append(auto)
    return "\n".join(lines)


def help_wiki_email_appendix(lang: str) -> str:
    """Компактный глоссарий для футера email — после дисклеймера."""
    use_ru = _wiki_lang(lang)
    hdr = "📖 Команды @Saylor_w_bot (кратко):" if use_ru else "📖 @Saylor_w_bot commands (short):"
    lines = [hdr]
    for cmd in USER_COMMAND_ORDER:
        if cmd in {"help", "chatid"}:
            continue
        spec = COMMAND_SPECS.get(cmd)
        if not spec:
            continue
        brief = spec["ru"] if use_ru else spec["en"]
        if len(brief) > 88:
            brief = brief[:85].rstrip() + "…"
        lines.append(f"• /{cmd} — {brief}")
    lines.append("")
    tail = (
        "Полный глоссарий: Telegram → @Saylor_w_bot → /help"
        if use_ru
        else "Full glossary: Telegram → @Saylor_w_bot → /help"
    )
    lines.append(tail)
    return "\n".join(lines)


def should_append_email_help_wiki(body: str) -> bool:
    """Не добавлять вики к спам-отказам и однострочным ответам."""
    low = body.lower()
    if any(m in low for m in ("unsolicited spam", "непрошенный спам", "will not be reviewed")):
        return False
    if len(body.strip()) < 40:
        return False
    if "📖 @saylor_w_bot commands" in low or "📖 команды @saylor_w_bot" in low:
        return False
    if "command mini wiki" in low or "мини-вики команд" in low:
        return False
    return True

# Поля вывода /info (и частично /botstats) — для разъяснения в email/Ollama
INFO_FIELD_SPECS: dict[str, dict[str, object]] = {
    "commit": {
        "aliases": ("commit", "коммит"),
        "ru": "Хеш git-сборки на хостинге (Render). Нужен админу для сопоставления с деплоем.",
        "en": "Git commit hash on hosting (Render). Helps admins match running code to a deploy.",
    },
    "instance": {
        "aliases": ("instance", "инстанс"),
        "ru": "ID инстанса на хостинге (Render). Служебное поле, не для пользователей.",
        "en": "Hosting instance ID (Render). Internal ops field, not for end users.",
    },
    "uptime": {
        "aliases": ("uptime", "аптайм", "время работы"),
        "ru": "Сколько времени текущий процесс бота работает без перезапуска.",
        "en": "How long the current bot process has been running without restart.",
    },
    "monitor_interval": {
        "aliases": ("monitor interval", "интервал монитор", "interval"),
        "ru": "Пауза в секундах между автоматическими проверками Strategy / ETF / компаний.",
        "en": "Seconds between automatic Strategy / ETF / company checks.",
    },
    "alive_ping": {
        "aliases": ("alive ping", "alive ping enabled", "пинг"),
        "ru": "Периодическое «я жив» в alert-чат админа. False = выключено (норма).",
        "en": "Periodic «I'm alive» message to the admin alert chat. False = off (normal).",
    },
    "strategy_site": {
        "aliases": ("strategy.com monitor", "strategy.com", "site monitor", "монитор strategy"),
        "ru": "Опрос strategy.com (пресс-релизы/покупки). True = включён, алерты Premium при новых данных.",
        "en": "Polling strategy.com (press/purchases). True = on; Premium alerts on new data.",
    },
    "stars": {
        "aliases": ("stars payments", "stars payment", "telegram stars", "⭐"),
        "ru": "Оплата Premium через Telegram Stars: включена ли и цена (⭐ / дней).",
        "en": "Premium via Telegram Stars: whether enabled and price (⭐ / days).",
    },
    "gating": {
        "aliases": ("alert gating", "gating", "free delay", "гейтинг", "задержк"),
        "ru": "Тарифная логика алертов: Free с задержкой (~15 мин), Premium мгновенно.",
        "en": "Alert tiers: Free with delay (~15 min), Premium instant.",
    },
    "weekly_digest": {
        "aliases": ("weekly digest", "дайджест", "digest"),
        "ru": "Авто-рассылка Weekly Digest Premium по воскресеньям (~12:00 NY).",
        "en": "Auto Weekly Digest to Premium on Sundays (~12:00 NY).",
    },
    "site_url": {
        "aliases": ("site url",),
        "ru": "URL страницы strategy.com для мониторинга (если задан в .env).",
        "en": "strategy.com page URL under monitoring (if set in .env).",
    },
    "trade_journal": {
        "aliases": ("trade journal", "journal", "журнал", "entries"),
        "ru": "Число записей в журнале сделок (transactions.json) — зафиксированные buy/sell Strategy и др.",
        "en": "Entries in the trade journal (transactions.json) — recorded Strategy buy/sell events, etc.",
    },
    "bot_version": {
        "aliases": ("bot version", "version", "версия"),
        "ru": "Строка версии сборки бота (дата/релиз).",
        "en": "Bot build version string (date/release).",
    },
    "server_time": {
        "aliases": ("server time", "время сервера"),
        "ru": "Текущее время на сервере (UTC) в момент /info.",
        "en": "Server clock (UTC) when /info was run.",
    },
    "unique_users": {
        "aliases": ("unique users", "уникальн пользов", "unique_users"),
        "ru": "Сколько разных Telegram user_id хотя бы раз нажали /start (без повторов одного человека).",
        "en": "How many distinct Telegram user_ids pressed /start at least once (one person counted once).",
    },
    "total_starts": {
        "aliases": ("total /start", "total start", "нажат /start", "start presses", "/start presses"),
        "ru": "Сколько раз всего вызывали /start (повторные нажатия считаются), без учёта admin (X_CHAT_ID).",
        "en": "Total /start command count (repeats count), excluding admin (X_CHAT_ID).",
    },
    "premium_active": {
        "aliases": ("premium active", "активн premium", "премиум актив"),
        "ru": "Пользователи с действующим Premium прямо сейчас.",
        "en": "Users with Premium currently active.",
    },
    "paid_stars": {
        "aliases": ("paid via stars", "stars earned", "оплат stars", "звёзд"),
        "ru": "Сколько оплат Premium через Stars и суммарно заработано ⭐.",
        "en": "How many Premium payments via Stars and total ⭐ earned.",
    },
    "founding_promo": {
        "aliases": ("founding promo", "founding", "акци", "promo:"),
        "ru": "Акция запуска: сколько из N слотов founding Premium уже занято / осталось.",
        "en": "Launch promo: how many of N founding Premium slots claimed / left.",
    },
    "last_visit": {
        "aliases": ("last visit", "последн визит", "last visit:"),
        "ru": "Когда последний раз кто-либо нажал /start (UTC).",
        "en": "When anyone last pressed /start (UTC).",
    },
}

# Общие поля блока Strategy (holdings / stats / status / buy)
_TREASURY_OUTPUT_FIELDS: dict[str, dict[str, object]] = {
    "btc_balance": {
        "aliases": ("₿", " btc\n", " btc ", "balance:", "баланс"),
        "ru": "Текущий баланс BTC в казне Strategy (live с strategy.com / CoinGecko).",
        "en": "Current Strategy BTC treasury balance (live from strategy.com / CoinGecko).",
    },
    "market_value": {
        "aliases": ("market value", "рыночн стоим", "≈ $", "≈ $", "~$"),
        "ru": "Оценка стоимости казны в USD по spot-цене BTC.",
        "en": "Treasury USD value at BTC spot price.",
    },
    "avg_price": {
        "aliases": ("avg price", "средн цен", "average price", "avg price:"),
        "ru": "Средняя цена покупки BTC Strategy (cost basis / BTC).",
        "en": "Strategy average BTC purchase price (cost basis / BTC).",
    },
    "pnl": {
        "aliases": ("pnl", "unrealized", "нереализ"),
        "ru": "Нереализованный PnL: рыночная стоимость минус cost basis.",
        "en": "Unrealized PnL: market value minus cost basis.",
    },
    "last_buy": {
        "aliases": ("last buy", "последн покуп", "last purchase"),
        "ru": "Последняя зафиксированная покупка: +BTC и дата (если есть в данных).",
        "en": "Latest recorded purchase: +BTC and date (when available).",
    },
    "source": {
        "aliases": ("source:", "источник:", "📡 source", "📡 источник"),
        "ru": "Откуда взяты цифры: Strategy (сайт) или CoinGecko.",
        "en": "Data source: Strategy site or CoinGecko.",
    },
    "cost_basis": {
        "aliases": ("cost basis", "себестоим", "база затрат"),
        "ru": "Суммарная себестоимость BTC-казны в USD.",
        "en": "Total USD cost basis of the BTC treasury.",
    },
    "btc_spot": {
        "aliases": ("btc price", "цена btc", "🪙 btc", "spot"),
        "ru": "Текущая spot-цена BTC (CoinGecko) на момент запроса.",
        "en": "Current BTC spot price (CoinGecko) at request time.",
    },
}

_ANALYTICS_OUTPUT_FIELDS: dict[str, dict[str, object]] = {
    k: INFO_FIELD_SPECS[k]
    for k in (
        "unique_users",
        "total_starts",
        "premium_active",
        "paid_stars",
        "founding_promo",
        "last_visit",
    )
}

COMMAND_FIELD_SPECS: dict[str, dict[str, dict[str, object]]] = {
    "info": INFO_FIELD_SPECS,
    "botstats": {
        **_ANALYTICS_OUTPUT_FIELDS,
        "premium_total": {
            "aliases": ("premium records", "premium total", "запис premium"),
            "ru": "Сколько раз в базе фигурировал Premium (включая истёкшие подписки).",
            "en": "How many Premium records exist (including expired subscriptions).",
        },
    },
    "status": {
        "bot_online": {
            "aliases": ("bot online", "бот онлайн", "✅ bot", "✅ бот"),
            "ru": "Бот отвечает и процесс на сервере запущен.",
            "en": "Bot is up and the server process is running.",
        },
        "uptime": INFO_FIELD_SPECS["uptime"],
        **_TREASURY_OUTPUT_FIELDS,
        "baseline": {
            "aliases": ("alert baseline", "baseline:", "baseline", "базов", "📊 baseline"),
            "ru": "Эталонный баланс Strategy для алертов: при отклонении ≥ порога — buy/sell уведомление.",
            "en": "Strategy balance baseline for alerts: buy/sell when live balance moves past threshold.",
        },
        "monitor_error": {
            "aliases": ("monitor error", "ошибка монитор"),
            "ru": "Последняя ошибка фонового мониторинга (видно только admin).",
            "en": "Last background monitor error (admin-only line).",
        },
    },
    "holdings": dict(_TREASURY_OUTPUT_FIELDS),
    "stats": dict(_TREASURY_OUTPUT_FIELDS),
    "buy": {
        "buy_delta": {
            "aliases": ("bitcoin buy", "latest buy", "последн покуп", "+", "−"),
            "ru": "Объём BTC в последней сделке Strategy (+ покупка).",
            "en": "BTC amount in Strategy's latest deal (+ purchase).",
        },
        "buy_usd": {
            "aliases": ("≈ $", "~$"),
            "ru": "Оценка сделки в USD (BTC × цена покупки или spot).",
            "en": "Deal USD estimate (BTC × purchase or spot price).",
        },
        "total_holdings": {
            "aliases": ("holdings:", "🏦 holdings", "🏦 холдинг", "total holdings"),
            "ru": "Общий баланс BTC Strategy после этой сделки.",
            "en": "Total Strategy BTC holdings after this trade.",
        },
        "buy_price": {
            "aliases": ("buy price", "цена покуп"),
            "ru": "Цена BTC в этой покупке (USD за BTC).",
            "en": "BTC price in this purchase (USD per BTC).",
        },
        "trade_date": {
            "aliases": ("📅", " on ", " дата"),
            "ru": "Дата покупки по данным strategy.com / журнала.",
            "en": "Purchase date from strategy.com / journal data.",
        },
        "avg_price": _TREASURY_OUTPUT_FIELDS["avg_price"],
        "pnl": _TREASURY_OUTPUT_FIELDS["pnl"],
    },
    "whales": {
        "rank_row": {
            "aliases": (" btc ·", " btc · ", "—", "rank.", "1.", "2."),
            "ru": "Строка рейтинга: место, имя (тикер), BTC, тип (компания/ETF/Strategy).",
            "en": "Ranking row: rank, name (ticker), BTC, type (company/ETF/Strategy).",
        },
        "footer_total": {
            "aliases": ("tracked:", "всего:", "across", "китов", "whales"),
            "ru": "Суммарный BTC у отслеживаемых китов и сколько строк в полном списке.",
            "en": "Total BTC across tracked whales and how many rows in the full list.",
        },
        "top_shown": {
            "aliases": ("top ", "топ-", "shown", "показано"),
            "ru": "Сколько позиций показано: Free топ-7, Premium топ-10.",
            "en": "How many ranks shown: Free top 7, Premium top 10.",
        },
        "etf_note": {
            "aliases": ("etf aum", "sosovalue", "etf omitted"),
            "ru": "Служебная пометка: AUM ETF не включён (нет API-ключа или временная ошибка).",
            "en": "Footnote: ETF AUM omitted (no API key or temporary error).",
        },
    },
    "site": {
        "site_btc": {
            "aliases": ("strategy.com —", "strategy.com -"),
            "ru": "Текущий баланс BTC на strategy.com по снимку страницы.",
            "en": "Current BTC on strategy.com from the page snapshot.",
        },
        "as_of": {
            "aliases": ("as of:", "на дату", "as of"),
            "ru": "Дата актуальности данных на сайте.",
            "en": "As-of date for the site data.",
        },
        "last_purchase": {
            "aliases": ("last purchase:", "последняя покупка:"),
            "ru": "Последняя покупка с сайта: BTC, дата, цена за BTC.",
            "en": "Latest site purchase: BTC, date, price per BTC.",
        },
        "latest_press": {
            "aliases": ("latest press:", "пресс:", "press release"),
            "ru": "Заголовок последнего пресс-релиза strategy.com (если есть).",
            "en": "Title of the latest strategy.com press release (if any).",
        },
        "site_url": {
            "aliases": ("strategy.com/", "purchases"),
            "ru": "Ссылка на страницу покупок strategy.com в ответе.",
            "en": "Link to strategy.com purchases page in the reply.",
        },
    },
    "mysub": {
        "plan": {
            "aliases": ("plan:", "тариф:", "free**", "premium**"),
            "ru": "Текущий тариф: Free или Premium (активен / истёк).",
            "en": "Current plan: Free or Premium (active / expired).",
        },
        "valid_until": {
            "aliases": ("valid until", "действует до", "until:"),
            "ru": "Дата окончания Premium-подписки.",
            "en": "Premium subscription expiry date.",
        },
        "days_left": {
            "aliases": ("days left", "дней остал", "осталось"),
            "ru": "Сколько дней Premium осталось до expires_at.",
            "en": "Days of Premium left until expires_at.",
        },
        "founding_badge": {
            "aliases": ("founding member", "founding", "акция", "promo spot"),
            "ru": "Метка founding promo: номер слота, если акцию уже активировали.",
            "en": "Founding promo badge: slot number if promo was claimed.",
        },
    },
    "plans": {
        "free_tier": {
            "aliases": ("free —", "free -", "🆓 free", "бесплатн"),
            "ru": "Бесплатный тариф: Strategy с задержкой, 1 PNG/нед, текстовая сводка, /whales топ-7.",
            "en": "Free tier: delayed Strategy alerts, 1 PNG/week, text weekly, /whales top 7.",
        },
        "premium_tier": {
            "aliases": ("premium —", "premium -", "⭐ premium", "премиум"),
            "ru": "Premium: мгновенные алерты, компании, ETF, strategy.com, /weekly, /whales топ-10.",
            "en": "Premium: instant alerts, companies, ETF, strategy.com, /weekly, /whales top 10.",
        },
        "founding_line": {
            "aliases": ("founding", "акция запуска", "promo:", "1 year free"),
            "ru": "Строка акции: сколько бесплатных founding-слотов Premium осталось.",
            "en": "Launch promo line: how many free founding Premium slots remain.",
        },
        "stars_price": {
            "aliases": ("⭐", "stars", "звёзд", "через /subscribe"),
            "ru": "Цена Premium в Telegram Stars и срок в днях.",
            "en": "Premium price in Telegram Stars and billing period in days.",
        },
    },
    "start": {
        "intro": {
            "aliases": ("saylorwatchbot", "build:", "сборк"),
            "ru": "Приветствие: что делает бот, версия сборки, кнопки меню.",
            "en": "Welcome text: what the bot does, build version, menu buttons.",
        },
        "btc_price_line": {
            "aliases": ("btc price", "цена btc", "₿ price", "spot"),
            "ru": "Строка spot-цены BTC (CoinGecko) под приветствием.",
            "en": "BTC spot price line (CoinGecko) under the welcome text.",
        },
        "status_block": {
            "aliases": ("bot online", "бот онлайн", "baseline"),
            "ru": "После приветствия бот сразу шлёт тот же блок, что /status (онлайн + казна + baseline).",
            "en": "After welcome, bot sends the same block as /status (online + treasury + baseline).",
        },
    },
    "chatid": {
        "chat_id": {
            "aliases": ("chat id:", "chat id", "id чата"),
            "ru": "ID Telegram-чата (для X_CHAT_ID на хостинге).",
            "en": "Telegram chat ID (for X_CHAT_ID on hosting).",
        },
        "user_id": {
            "aliases": ("user id:", "user id", "id пользов"),
            "ru": "Ваш Telegram user ID (в личке обычно совпадает с chat id).",
            "en": "Your Telegram user ID (in private chat usually equals chat id).",
        },
    },
    "subscribe": {
        "offer": {
            "aliases": ("premium", "subscribe", "купить", "оплат"),
            "ru": "Экран оплаты Premium: что входит, кнопки Stars / founding promo.",
            "en": "Premium checkout screen: features, Stars / founding promo buttons.",
        },
        "stars_amount": {
            "aliases": ("⭐", "stars", "звёзд"),
            "ru": "Сколько Telegram Stars списывается за период Premium.",
            "en": "How many Telegram Stars are charged for the Premium period.",
        },
        "private_chat_only": {
            "aliases": ("private chat", "личн", "групп"),
            "ru": "/subscribe работает только в личном чате с @Saylor_w_bot, не в группах.",
            "en": "/subscribe works only in a private chat with @Saylor_w_bot, not in groups.",
        },
    },
    "weekly": {
        "premium_gate": {
            "aliases": ("premium only", "только premium", "weekly digest is"),
            "ru": "Сообщение, если Free: /weekly доступен только Premium.",
            "en": "Message for Free users: /weekly is Premium-only.",
        },
        "digest_sent": {
            "aliases": ("digest sent", "дайджест отправ", "weekly digest sent"),
            "ru": "Подтверждение: PNG-дайджест за период отправлен в чат.",
            "en": "Confirmation: PNG digest for the period was sent to the chat.",
        },
        "digest_caption": {
            "aliases": ("whale of the week", "кит недели", "premium weekly"),
            "ru": "Подпись к PNG: период, кит недели, тикеры, пометка * для оценочных продаж.",
            "en": "PNG caption: period, whale of the week, tickers, * for estimated sells.",
        },
    },
    "donate": {
        "addresses": {
            "aliases": ("bitcoin", "btc:", "eth:", "ton:", "адрес"),
            "ru": "Адреса кошельков BTC / ETH / TON для добровольных донатов серверу.",
            "en": "BTC / ETH / TON wallet addresses for voluntary server donations.",
        },
        "wallet_buttons": {
            "aliases": ("metamask", "rabby", "mempool", "кнопк"),
            "ru": "Кнопки открывают кошелёк или explorer с адресом для копирования.",
            "en": "Buttons open wallet or explorer with the address to copy.",
        },
    },
    "partners": {
        "partner_links": {
            "aliases": ("binance", "bybit", "ledger", "referral", "реферал", "partner"),
            "ru": "Список партнёрских referral-ссылок (биржи, кошельки) из PARTNER_*_URL на сервере.",
            "en": "Partner referral links (exchanges, wallets) from PARTNER_*_URL on the server.",
        },
        "not_exchange": {
            "aliases": ("not an exchange", "не биржа", "buy btc"),
            "ru": "Бот не продаёт BTC — только ссылки; покупка на стороне биржи/кошелька.",
            "en": "Bot does not sell BTC — links only; purchase happens on the exchange/wallet site.",
        },
    },
    "social": {
        "bot_link": {
            "aliases": ("@saylor_w_bot", "t.me/", "open bot"),
            "ru": "Ссылка открыть бота в Telegram.",
            "en": "Link to open the bot in Telegram.",
        },
        "social_links": {
            "aliases": ("x (twitter)", "reddit", "discord", "twitter"),
            "ru": "Кнопки на официальные соцсети проекта.",
            "en": "Buttons to official project social channels.",
        },
    },
    "disclaimer": {
        "nfa": {
            "aliases": ("investment advice", "инвестицион", "not financial"),
            "ru": "Не инвестиционный совет; только публичная информация.",
            "en": "Not investment advice; public information only.",
        },
        "affiliation": {
            "aliases": ("not affiliated", "не аффилир", "mstr", "saylor"),
            "ru": "Бот не связан с Strategy (MSTR) и Michael Saylor.",
            "en": "Bot is not affiliated with Strategy (MSTR) or Michael Saylor.",
        },
        "subscription_note": {
            "aliases": ("paid subscription", "подписк", "does not grant"),
            "ru": "Подписка даёт доступ к алертам, не долю или доход.",
            "en": "Subscription grants alerts access, not ownership or income.",
        },
    },
    "check": {
        "holdings_result": {
            "aliases": ("holdings:", "баланс:"),
            "ru": "Результат проверки Strategy: без изменений / алерт / ошибка fetch.",
            "en": "Strategy check result: no change / alert / fetch error.",
        },
        "site_result": {
            "aliases": ("strategy.com:", "site:"),
            "ru": "Результат опроса strategy.com при ручном /check.",
            "en": "strategy.com poll result on manual /check.",
        },
        "companies_result": {
            "aliases": ("companies:", "компани:"),
            "ru": "Статус проверки казн компаний (Tesla, MARA…).",
            "en": "Company treasury check status (Tesla, MARA…).",
        },
        "etf_result": {
            "aliases": ("etf:", "etf "),
            "ru": "Статус проверки дневных ETF-потоков (IBIT, FBTC…).",
            "en": "Daily ETF flow check status (IBIT, FBTC…).",
        },
    },
    "baseline": {
        "reset_line": {
            "aliases": ("baseline reset", "сброс baseline", "reset to live"),
            "ru": "Baseline сброшен на текущий live-баланс Strategy — от него считаются алерты.",
            "en": "Baseline reset to current live Strategy balance — alerts measure from here.",
        },
    },
    "setbaseline": {
        "manual_btc": {
            "aliases": ("baseline set", "baseline =", "установлен"),
            "ru": "Admin задал baseline вручную (число BTC) для тестов алертов.",
            "en": "Admin set baseline manually (BTC number) for alert testing.",
        },
    },
    "uptime": {
        "process_uptime": {
            "aliases": ("uptime:", "⏱ uptime", "аптайм"),
            "ru": "Время работы процесса бота без перезапуска (короче, чем /status).",
            "en": "Bot process uptime without restart (shorter than /status).",
        },
    },
    "testalert": {
        "delivery_test": {
            "aliases": ("test alert", "тест", "alerts are working"),
            "ru": "Проверка доставки уведомлений в alert-чат admin.",
            "en": "Tests notification delivery to the admin alert chat.",
        },
    },
    "setsub": {
        "grant_revoke": {
            "aliases": ("premium", "reset to free", "setsub", "user "),
            "ru": "Admin вручную выдал или отозвал Premium у user_id (тестирование).",
            "en": "Admin manually granted or revoked Premium for a user_id (testing).",
        },
    },
}

COMMAND_OUTPUT_MARKERS: dict[str, tuple[str, ...]] = {
    "info": ("🧠 bot information", "bot information\n", "alive ping enabled"),
    "botstats": ("📊 bot analytics", "premium records:", "files: bot_stats"),
    "status": ("✅ bot online", "✅ бот онлайн", "alert baseline:", "📊 baseline:", "📊 alert baseline"),
    "holdings": ("btc treasury", "btc treasury\n", "strategy · btc", "казн"),
    "stats": ("treasury stats", "статистик", "cost basis", "себестоим"),
    "buy": ("latest buy", "последн", "strategy · latest", "bitcoin buy"),
    "whales": ("top 10 btc", "топ-10", "btc whales", "btc-кит", "whales footer"),
    "site": ("strategy.com —", "as of:", "latest press:"),
    "mysub": ("your subscription", "ваша подписка", "plan: **", "тариф:"),
    "plans": ("saylorwatch plans", "тарифы saylorwatch", "free — $0", "🆓 free"),
    "chatid": ("chat id:", "user id:", "x_chat_id"),
    "check": ("holdings: no change", "holdings: purchase", "companies:", "etf:"),
    "donate": ("support the bot", "поддерж", "bitcoin (btc)"),
    "partners": ("partner links", "партнёрск", "referral", "binance"),
    "disclaimer": ("⚖️ disclaimer", "not investment advice", "не является инвестицион"),
}

FIELD_LABELS: dict[str, dict[str, tuple[str, str]]] = {
    "info": {
        "commit": ("Commit", "Commit"),
        "instance": ("Instance", "Instance"),
        "uptime": ("Uptime", "Uptime"),
        "monitor_interval": ("Monitor interval", "Monitor interval"),
        "alive_ping": ("Alive ping enabled", "Alive ping enabled"),
        "strategy_site": ("Strategy.com monitor", "Strategy.com monitor"),
        "stars": ("Stars payments", "Stars payments"),
        "gating": ("Alert gating", "Alert gating"),
        "weekly_digest": ("Weekly digest", "Weekly digest"),
        "site_url": ("Site URL", "Site URL"),
        "trade_journal": ("Trade journal", "Trade journal"),
        "bot_version": ("Bot version", "Bot version"),
        "server_time": ("Server Time", "Server Time"),
        "unique_users": ("Unique users (/start)", "Unique users (/start)"),
        "total_starts": ("Total /start presses", "Total /start presses"),
        "premium_active": ("Premium active", "Premium active"),
        "paid_stars": ("Paid via Stars", "Paid via Stars"),
        "founding_promo": ("Founding promo", "Founding promo"),
        "last_visit": ("Last visit", "Last visit"),
    },
    "botstats": {
        "unique_users": ("Unique users (/start)", "Unique users (/start)"),
        "total_starts": ("Total /start presses", "Total /start presses"),
        "premium_active": ("Premium active", "Premium active"),
        "premium_total": ("Premium records", "Premium records"),
        "paid_stars": ("Paid via Stars", "Paid via Stars"),
        "founding_promo": ("Founding promo", "Founding promo"),
        "last_visit": ("Last visit", "Last visit"),
    },
    "status": {
        "bot_online": ("Bot online", "Bot online"),
        "uptime": ("Uptime", "Uptime"),
        "btc_balance": ("BTC balance", "BTC balance"),
        "market_value": ("Market value", "Market value"),
        "avg_price": ("Avg price", "Avg price"),
        "pnl": ("Unrealized PnL", "Unrealized PnL"),
        "last_buy": ("Last buy", "Last buy"),
        "source": ("Source", "Source"),
        "baseline": ("Alert baseline", "Alert baseline"),
        "monitor_error": ("Monitor error", "Monitor error"),
    },
    "holdings": {
        "btc_balance": ("BTC balance", "BTC balance"),
        "market_value": ("Market value", "Market value"),
        "avg_price": ("Avg price", "Avg price"),
        "pnl": ("Unrealized PnL", "Unrealized PnL"),
        "last_buy": ("Last buy", "Last buy"),
        "source": ("Source", "Source"),
    },
    "stats": {
        "btc_balance": ("Holdings", "Holdings"),
        "market_value": ("Market value", "Market value"),
        "btc_spot": ("BTC spot price", "BTC spot price"),
        "cost_basis": ("Cost basis", "Cost basis"),
        "avg_price": ("Avg price", "Avg price"),
        "pnl": ("Unrealized PnL", "Unrealized PnL"),
        "last_buy": ("Last buy", "Last buy"),
        "source": ("Source", "Source"),
    },
    "buy": {
        "buy_delta": ("Buy amount", "Buy amount"),
        "buy_usd": ("USD estimate", "USD estimate"),
        "total_holdings": ("Total holdings", "Total holdings"),
        "buy_price": ("Buy price", "Buy price"),
        "trade_date": ("Date", "Date"),
        "avg_price": ("Avg price", "Avg price"),
        "pnl": ("Unrealized PnL", "Unrealized PnL"),
    },
    "whales": {
        "rank_row": ("Ranking row", "Ranking row"),
        "footer_total": ("Total tracked BTC", "Total tracked BTC"),
        "top_shown": ("Top N shown", "Top N shown"),
        "etf_note": ("ETF note", "ETF note"),
    },
    "site": {
        "site_btc": ("Site BTC total", "Site BTC total"),
        "as_of": ("As of date", "As of date"),
        "last_purchase": ("Last purchase", "Last purchase"),
        "latest_press": ("Latest press", "Latest press"),
        "site_url": ("Purchases URL", "Purchases URL"),
    },
    "mysub": {
        "plan": ("Plan", "Plan"),
        "valid_until": ("Valid until", "Valid until"),
        "days_left": ("Days left", "Days left"),
        "founding_badge": ("Founding badge", "Founding badge"),
    },
    "plans": {
        "free_tier": ("Free tier", "Free tier"),
        "premium_tier": ("Premium tier", "Premium tier"),
        "founding_line": ("Founding promo", "Founding promo"),
        "stars_price": ("Stars price", "Stars price"),
    },
    "start": {
        "intro": ("Welcome", "Welcome"),
        "btc_price_line": ("BTC price line", "BTC price line"),
        "status_block": ("Status block", "Status block"),
    },
    "chatid": {
        "chat_id": ("Chat ID", "Chat ID"),
        "user_id": ("User ID", "User ID"),
    },
    "subscribe": {
        "offer": ("Premium offer", "Premium offer"),
        "stars_amount": ("Stars amount", "Stars amount"),
        "private_chat_only": ("Private chat only", "Private chat only"),
    },
    "weekly": {
        "premium_gate": ("Premium gate", "Premium gate"),
        "digest_sent": ("Digest sent", "Digest sent"),
        "digest_caption": ("Digest caption", "Digest caption"),
    },
    "donate": {
        "addresses": ("Wallet addresses", "Wallet addresses"),
        "wallet_buttons": ("Wallet buttons", "Wallet buttons"),
    },
    "partners": {
        "partner_links": ("Partner links", "Partner links"),
        "not_exchange": ("Not an exchange", "Not an exchange"),
    },
    "social": {
        "bot_link": ("Bot link", "Bot link"),
        "social_links": ("Social links", "Social links"),
    },
    "disclaimer": {
        "nfa": ("Not advice", "Not advice"),
        "affiliation": ("Affiliation", "Affiliation"),
        "subscription_note": ("Subscription note", "Subscription note"),
    },
    "check": {
        "holdings_result": ("Strategy check", "Strategy check"),
        "site_result": ("Site check", "Site check"),
        "companies_result": ("Companies check", "Companies check"),
        "etf_result": ("ETF check", "ETF check"),
    },
    "baseline": {"reset_line": ("Baseline reset", "Baseline reset")},
    "setbaseline": {"manual_btc": ("Manual baseline", "Manual baseline")},
    "uptime": {"process_uptime": ("Process uptime", "Process uptime")},
    "testalert": {"delivery_test": ("Test delivery", "Test delivery")},
    "setsub": {"grant_revoke": ("Grant/revoke", "Grant/revoke")},
}

COMMAND_FIELD_FOOTNOTES: dict[str, tuple[str, str]] = {
    "info": (
        "/info — только admin (X_CHAT_ID). Пользователям: /status · короче: /botstats.",
        "/info is admin-only (X_CHAT_ID). Users: /status · shorter: /botstats.",
    ),
    "botstats": (
        "/botstats — только admin. Пользователям: /mysub и /plans.",
        "/botstats is admin-only. Users: /mysub and /plans.",
    ),
    "status": (
        "Основная пользовательская команда вместо /info.",
        "Main user-facing status command instead of /info.",
    ),
    "check": ("/check — только admin.", "/check is admin-only."),
    "baseline": ("/baseline — только admin.", "/baseline is admin-only."),
    "setbaseline": ("/setbaseline — только admin.", "/setbaseline is admin-only."),
    "uptime": ("/uptime — admin; пользователям обычно /status.", "/uptime is admin; users usually use /status."),
    "testalert": ("/testalert — только admin.", "/testalert is admin-only."),
    "setsub": ("/setsub — только admin.", "/setsub is admin-only."),
}

_FIELD_QUESTION_MARKERS: tuple[str, ...] = (
    "что значит пункт",
    "что значит строка",
    "что значит поле",
    "объясни значение",
    "объясните значение",
    "расшифруй",
    "что означает",
    "explain this field",
    "explain this line",
    "what does this mean",
    "what does this line",
    "what does this field",
)


def detect_output_command(blob: str) -> str | None:
    """Определить команду по вставленному выводу бота."""
    low = blob.lower()
    order = (
        "info",
        "botstats",
        "disclaimer",
        "mysub",
        "plans",
        "whales",
        "stats",
        "holdings",
        "buy",
        "site",
        "chatid",
        "donate",
        "check",
        "status",
    )
    for cmd in order:
        for marker in COMMAND_OUTPUT_MARKERS.get(cmd, ()):
            if marker in low or marker in blob:
                return cmd
    return None


def mentioned_command_fields(cmd: str, blob: str) -> list[str]:
    specs = COMMAND_FIELD_SPECS.get(cmd)
    if not specs:
        return []
    low = blob.lower()
    found: list[str] = []
    for key, spec in specs.items():
        aliases = spec.get("aliases", ())
        if any(str(a).lower() in low for a in aliases):  # type: ignore[union-attr]
            found.append(key)
    return found


def infer_command_from_fields(blob: str) -> str | None:
    scores: dict[str, int] = {}
    for cmd in COMMAND_FIELD_SPECS:
        n = len(mentioned_command_fields(cmd, blob))
        if n:
            scores[cmd] = n
    if not scores:
        return None
    return max(scores, key=scores.get)


def command_fields_glossary(cmd: str, lang: str, field_keys: list[str] | None = None) -> str:
    specs = COMMAND_FIELD_SPECS.get(cmd)
    if not specs:
        return ""
    use_ru = lang == "ru"
    keys = field_keys or list(specs.keys())
    header = f"Значение полей /{cmd}:" if use_ru else f"/{cmd} field meanings:"
    lines = [header, ""]
    labels = FIELD_LABELS.get(cmd, {})
    for key in keys:
        spec = specs.get(key)
        if not spec:
            continue
        label = labels.get(key, (key.replace("_", " ").title(), key.replace("_", " ").title()))
        label_text = label[0] if use_ru else label[1]
        body = spec["ru"] if use_ru else spec["en"]
        lines.append(f"• {label_text} — {body}")
    foot = COMMAND_FIELD_FOOTNOTES.get(cmd)
    if foot:
        lines.extend(["", foot[0] if use_ru else foot[1]])
    return "\n".join(lines)


def is_command_fields_question(blob: str) -> bool:
    """Вопрос про поля вывода любой команды или вставленный ответ бота."""
    if detect_output_command(blob):
        return True
    low = blob.lower()
    if any(m in low for m in _FIELD_QUESTION_MARKERS):
        return bool(infer_command_from_fields(blob) or detect_output_command(blob))
    explicit_m = re.search(r"/([a-z][a-z0-9]*)", low)
    explicit = explicit_m.group(1) if explicit_m else None
    if explicit and explicit in COMMAND_FIELD_SPECS:
        if any(m in low for m in _FIELD_QUESTION_MARKERS) or len(mentioned_command_fields(explicit, blob)) >= 2:
            return True
    if infer_command_from_fields(blob) and any(
        m in low
        for m in (
            *_FIELD_QUESTION_MARKERS,
            "unique users",
            "baseline",
            "cost basis",
            "whale",
            "plan:",
            "тариф",
        )
    ):
        return True
    return is_info_fields_question(blob)


def is_info_fields_question(blob: str) -> bool:
    """Вопрос про поля /info, /botstats или вставленный вывод команды."""
    low = blob.lower()
    if "bot information" in low or "📊 analytics" in blob or "🧠" in blob:
        return True
    if any(
        m in low
        for m in (
            "unique users",
            "уникальн пользов",
            "total /start",
            "нажат /start",
            "alive ping",
            "trade journal",
            "журнал сделок",
            "strategy.com monitor",
            "last visit",
            "последн визит",
            "premium active",
            "founding promo",
            "monitor interval",
            "alert gating",
            "что значит пункт",
            "объясни значение",
            "explain this field",
            "what does this mean",
            "расшифруй",
            "что означает",
        )
    ):
        return True
    return False


def mentioned_info_fields(blob: str) -> list[str]:
    found = mentioned_command_fields("info", blob)
    if found:
        return found
    if is_info_fields_question(blob):
        return list(INFO_FIELD_SPECS.keys())
    return []


def info_fields_glossary(lang: str, field_keys: list[str] | None = None) -> str:
    """Пояснение полей /info — все или только запрошенные."""
    return command_fields_glossary("info", lang, field_keys)


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


def is_commands_list_question(blob: str) -> bool:
    """Вопрос «какие команды / полный список / функции и команды»."""
    low = blob.lower()
    list_markers = (
        "какие команд",
        "список команд",
        "все команд",
        "команды бота",
        "команда поддерж",
        "commands does",
        "commands do",
        "commands list",
        "list of command",
        "all command",
        "what commands",
        "which commands",
        "какие функции и команд",
        "функции и команд",
        "функции бота и команд",
        "commands and feature",
        "features and command",
        "поддерживает команд",
        "есть ли команд",
        "перечислите команд",
        "раскрыт",
        "опишите команд",
        "describe the command",
        "bot command",
    )
    if any(m in low for m in list_markers):
        if is_command_question(low) and not any(
            w in low for w in ("какие", "список", "все команд", "what commands", "which commands", "list of")
        ):
            return False
        return True
    if "команд" in low and any(
        w in low for w in ("какие", "список", "все", "перечис", "list", "what", "which", "какую")
    ):
        if len(re.findall(r"/[a-z][a-z0-9]*", low)) >= 2:
            return True
        if any(w in low for w in ("бот", "bot", "saylorwatch", "@saylor")):
            return True
    return False


def customer_wants_command_reference(blob: str) -> bool:
    """Клиент просит справочник команд — в ответе допустимы admin-команды."""
    low = blob.lower()
    if is_commands_list_question(low):
        return True
    if is_bot_overview_question(low) and any(
        w in low for w in ("команд", "command", "функци", "feature", "/help")
    ):
        return True
    return False


def extract_mentioned_commands(blob: str) -> list[str]:
    """Все /команды из письма (user + admin)."""
    seen: list[str] = []
    for m in re.finditer(r"/([a-z][a-z0-9]*)", blob.lower()):
        c = m.group(1)
        if c in seen:
            continue
        if c in VALID_BOT_COMMANDS or c in ADMIN_ONLY_COMMANDS:
            seen.append(c)
    return seen


def help_playbook_text(lang: str) -> str:
    """Полный справочник команд для email /help."""
    use_ru = lang == "ru"
    if use_ru:
        intro = (
            "SaylorWatch (@Saylor_w_bot) — мини-вики команд в Telegram:\n"
            "(алерты включаются автоматически после /start в личном чате)"
        )
        steps = "1. Telegram → @Saylor_w_bot\n2. /help — тот же глоссарий внутри бота"
    else:
        intro = (
            "SaylorWatch (@Saylor_w_bot) — Telegram command mini wiki:\n"
            "(alerts turn on automatically after /start in a private chat)"
        )
        steps = "1. Telegram → @Saylor_w_bot\n2. /help — same glossary inside the bot"
    return f"{intro}\n\n{format_help_wiki(lang, include_admin=True)}\n\n{steps}"


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
    return format_help_wiki(lang, include_admin=include_admin)


def command_cheatsheet_text_legacy(*, lang: str = "en", include_admin: bool = True) -> str:
    """Legacy sorted cheatsheet (tests)."""
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
/partners — partner links (exchanges & wallets, referral)
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
After /weekly: inline buttons export printable report — PDF, HTML (browser print), CSV, text table.
Also auto-scheduled: Sundays ~12:00 America/New_York to Premium subscribers.
Free: auto text summary same schedule (no /weekly command).
Tickers in weekly report (7-day window): MSTR, TSLA, XYZ, MARA, RIOT, 3350.T + IBIT, FBTC, GBTC, ARKB + BTC spot week change.
Per ticker: corp buy/sell BTC, net, holdings; ETF weekly net flows; largest treasury mover.

FREE vs PREMIUM (summary — details: /plans):
Free: Strategy alerts (~{free_delay}m delay), 1 PNG/week (+ large trades), text weekly, /holdings /stats /status /buy /site, /whales top {free_top}.
Premium: instant alerts, all PNG cards, company+ETF+site alerts, /whales top {premium_top}, /weekly PNG.

SUPPORT EMAIL (SaylorWatch@outlook.com):
Payment disputes, refunds, legal/GDPR, bugs needing investigation — NOT for /subscribe activation.
NOT for personal messages to the channel owner/admin or collaboration pitches — low-priority review only, no guarantee.
Obvious spam gets a one-line decline. Bot questions → @Saylor_w_bot /help.

WHEN CUSTOMER ASKS «what does /command mean»:
Answer about THAT command only. /info is admin-only — say so and point regular users to /status and /help.
If they paste bot output or ask what a field/line means — explain EACH mentioned field
(see COMMAND OUTPUT FIELD MEANINGS in BOT KNOWLEDGE; /status /stats /holdings /whales /mysub /plans /info…).
Never reply with a generic command list unless they asked for all commands.

COMMAND OUTPUT FIELD MEANINGS (explain each line when customer pastes bot output):
User: /status (online, uptime, BTC, baseline) · /holdings & /stats (balance, PnL, cost basis, spot)
· /buy (last purchase) · /whales (rank rows, top N) · /site (strategy.com snapshot) · /mysub & /plans (tiers)
· /start (welcome + same as /status) · /chatid · /weekly · /donate · /social · /disclaimer
Admin: /info · /botstats · /check · /baseline · /uptime · /testalert · /setsub
Never invent live numbers — only explain what each label measures.
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
        if c in VALID_BOT_COMMANDS or c in ADMIN_ONLY_COMMANDS:
            if c not in cmds:
                cmds.append(c)
    if len(cmds) < 2:
        return None
    parts: list[str] = []
    for c in cmds[:5]:
        block = playbook_text_for_topic(f"command:{c}", lang, context_blob=blob)
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
    if spec["scope"] == "admin":
        lines.extend([
            "",
            "Полный список команд (user + admin): /help в боте или спросите нас про /help."
            if use_ru
            else "Full command list (user + admin): /help in the bot or ask us about /help.",
        ])
    elif spec["scope"] == "user":
        lines.extend([
            "",
            "1. Telegram → @Saylor_w_bot",
            f"2. /{cmd}",
        ])
    return "\n".join(lines)


def playbook_fewshot_text(topic: str, lang: str, *, max_chars: int = 520) -> str:
    """Короткий эталон для Ollama few-shot — без полного cheatsheet (иначе timeout)."""
    if topic.startswith("command:"):
        text = command_explanation(topic.split(":", 1)[1], lang)
    elif topic == "help":
        book = FAQ_PLAYBOOKS.get("help", {})
        short = book.get(lang) or book.get("en", "")
        if short:
            return short
    text = playbook_text_for_topic(topic, lang)
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit("\n", 1)[0]
    return cut + "…"


def playbook_text_for_topic(topic: str, lang: str, *, context_blob: str = "") -> str:
    if topic == "help":
        return help_playbook_text(lang)
    if topic.startswith("command:"):
        cmd = topic.split(":", 1)[1]
        text = command_explanation(cmd, lang)
        if cmd in COMMAND_FIELD_SPECS:
            blob = context_blob or ""
            specs = COMMAND_FIELD_SPECS[cmd]
            fields = mentioned_command_fields(cmd, blob) if blob else list(specs.keys())
            if cmd == "botstats" and blob:
                analytics = tuple(specs.keys())
                fields = [k for k in fields if k in analytics] or list(analytics)
            elif not fields:
                fields = list(specs.keys())
            glossary = command_fields_glossary(cmd, lang, fields)
            if glossary:
                text += "\n\n" + glossary
        return text
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
            "• Classement des plus grands détenteurs BTC : /whales (Free : top 7, Premium : top 10)\n"
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
            "Command mini wiki in the bot:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /help — full glossary of every command & menu button\n"
            "3. Strategy: /holdings · /stats · /buy · /status · /site\n"
            "4. /whales · /plans · /mysub · /subscribe · Premium: /weekly"
        ),
        "ru": (
            "Мини-вики команд в боте:\n\n"
            "1. Telegram → @Saylor_w_bot\n"
            "2. /help — полный глоссарий команд и кнопок меню\n"
            "3. Strategy: /holdings · /stats · /buy · /status · /site\n"
            "4. /whales · /plans · /mysub · /subscribe · Premium: /weekly"
        ),
    },
    "personal_offtopic": {
        "en": (
            "This address is only for SaylorWatch bot support (@Saylor_w_bot) — "
            "commands, Premium, alerts, and technical questions about the Telegram bot.\n\n"
            "We do not reply here to personal messages addressed to the channel administrator "
            "or collaboration pitches about joint projects. Such messages are out of scope.\n\n"
            "Bot questions: Telegram → @Saylor_w_bot → /help."
        ),
        "ru": (
            "Этот адрес только для поддержки бота SaylorWatch (@Saylor_w_bot) — "
            "команды, Premium, алерты и технические вопросы по Telegram-боту.\n\n"
            "Личные письма администратору канала и предложения о сотрудничестве "
            "над проектом здесь не рассматриваются.\n\n"
            "Вопросы по боту: Telegram → @Saylor_w_bot → /help."
        ),
    },
    "spam_obvious": {
        "en": (
            "This message was identified as unsolicited spam and will not be reviewed. "
            "No further reply is planned."
        ),
        "ru": (
            "Письмо определено как непрошенный спам и не рассматривается. "
            "Дальнейший ответ не планируется."
        ),
    },
    "personal_resume": {
        "en": (
            "This inbox is for SaylorWatch bot support (@Saylor_w_bot) only — not personal mail "
            "to the channel administrator.\n\n"
            "If your message is not spam, the admin may review it when time allows. "
            "We do not guarantee a personal reply.\n\n"
            "Questions about the Telegram bot: @Saylor_w_bot → /help."
        ),
        "ru": (
            "Этот ящик — только поддержка бота SaylorWatch (@Saylor_w_bot), "
            "не личная переписка с администратором канала.\n\n"
            "Если это не спам, администратор может просмотреть обращение при наличии времени. "
            "Личный ответ не гарантируется.\n\n"
            "Вопросы по боту: @Saylor_w_bot → /help."
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
    "personal_offtopic": (
        "dear admin", "channel admin", "channel owner", "personal letter",
        "уважаемый админ", "владелец канала", "личное письмо", "not about the bot",
    ),
    "spam_obvious": (
        "click here", "limited time offer", "you have won", "seo service",
        "buy followers", "вы выиграли", "guest post", "разместите рекламу",
    ),
    "personal_resume": (
        "linkedin.com", "my resume", "резюме", "portfolio", "hire me",
        "job application", "меня зовут", "my name is",
    ),
}

# (subject, customer_body, playbook_topic, lang) — few-shot для Ollama
CANONICAL_FAQ_SHOTS: list[tuple[str, str, str, str]] = [
    ("Info", "что значит команда /info", "command:info", "ru"),
    ("Info fields", "Объясните: Unique users (/start): 4 — что это в /info?", "command:info", "ru"),
    ("Bot output", "Alive ping enabled: False\nTrade journal: 5 entries\nUnique users (/start): 4", "command:info", "ru"),
    ("Status fields", "✅ Бот онлайн\n📊 Baseline: 528000 BTC\nЧто значит baseline?", "command:status", "ru"),
    ("Stats fields", "Cost basis: $50B\nUnrealized PnL\nЧто это в /stats?", "command:stats", "ru"),
    ("Commands", "какие команды есть в боте? что делает /info", "help", "ru"),
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
    (
        "Personal admin RU",
        "Уважаемый админ канала! Хотел лично обсудить сотрудничество.",
        "personal_offtopic",
        "ru",
    ),
    (
        "Personal admin EN",
        "Dear channel admin — not about the bot. Please call me back personally.",
        "personal_offtopic",
        "en",
    ),
    (
        "Spam pitch EN",
        "Hello! SEO services for your crypto channel. Special offer — click here!",
        "spam_obvious",
        "en",
    ),
    (
        "Resume RU",
        "Меня зовут Иван, ищу работу. Резюме: linkedin.com/in/ivanov. Телефон +79001234567",
        "personal_resume",
        "ru",
    ),
    (
        "Collaboration RU",
        "я хотел бы с вами посотрудничать. давайте вместе поработаем над проектом вашим.",
        "personal_offtopic",
        "ru",
    ),
    (
        "Resume EN",
        "My name is John. Job application — resume: linkedin.com/in/john. Not about the bot.",
        "personal_resume",
        "en",
    ),
]

PLAYBOOK_NO_PS: frozenset[str] = frozenset({
    "subscribe", "mysub", "plans", "btc_price", "alerts", "whales", "weekly", "buy",
    "holdings", "site", "etf", "companies", "promo", "language", "donate", "social",
    "disclaimer", "what_is", "privacy", "not_exchange", "bot_created",
    "personal_offtopic", "personal_resume", "spam_obvious",
})

# Без дисклеймера NFA — только подпись поддержки (для короткого спам-отказа)
PLAYBOOK_MINIMAL_REPLY: frozenset[str] = frozenset({"spam_obvious"})
