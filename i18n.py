"""UI strings for SaylorWatchBot (default: English)."""

from __future__ import annotations

from typing import Any

DEFAULT_LANG = "en"

SUPPORTED_LANGS = ("en", "ru", "es", "de", "fr", "zh", "ja", "pt")

LANG_OPTIONS: tuple[tuple[str, str], ...] = (
    ("en", "🇺🇸 English"),
    ("ru", "🇷🇺 Русский"),
    ("es", "🇪🇸 Español"),
    ("de", "🇩🇪 Deutsch"),
    ("fr", "🇫🇷 Français"),
    ("zh", "🇨🇳 中文"),
    ("ja", "🇯🇵 日本語"),
    ("pt", "🇧🇷 Português"),
)

LANG_NATIVE_NAMES = dict(LANG_OPTIONS)

# fmt: off
TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "btn_status": "📊 Status",
        "btn_check": "🔄 Check now",
        "btn_buy_check": "💰 Purchase check",
        "btn_sell_check": "📉 Sale check",
        "btn_baseline": "📌 Reset baseline",
        "btn_help": "❓ Help",
        "btn_language": "🌐 Language",
        "btn_hide_menu": "⌨️ Hide menu",
        "btn_back": "◀️ Back to menu",
        "lang_menu_title": "Choose your language / Выберите язык:",
        "lang_set": "Language set to {name}. Menu updated.",
        "deny_admin": "⛔ Admin only.\nYour User ID: {user_id}\nServer X_CHAT_ID: {chat_id}\nThey must match. Use /chatid",
        "chatid_help": "For X_CHAT_ID on hosting use:\nChat ID: {chat_id}\nUser ID: {user_id}\n\nIn a private chat they are usually the same.\nDo not use the bot's own ID.",
        "start_intro": (
            "SaylorWatchBot — Strategy BTC intelligence.\n\n"
            "🏦 /holdings — treasury overview\n"
            "📊 /stats — avg price & PnL\n"
            "🟠 /buy — latest purchase\n"
            "🔔 Auto alerts on every buy & sell\n\n"
            "Source: Strategy · Build: {version}"
        ),
        "status_online": "✅ Bot online",
        "status_uptime": "⏱ Uptime: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 Source: {source}",
        "status_last_purchase": "🛒 Last purchase (site): {btc} BTC on {date}",
        "status_fetch_fail": "⚠️ Failed to fetch Strategy balance",
        "status_baseline": "📊 Alert baseline: {btc} BTC",
        "status_baseline_unset": "📊 Alert baseline: not set yet",
        "status_monitor_error": "⚠️ Monitor error: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": (
            "SaylorWatchBot — help\n\n"
            "🏦 /holdings — treasury overview\n"
            "📊 /stats — avg price, cost basis & PnL\n"
            "🟠 /buy — latest Bitcoin purchase\n"
            "📡 /status — bot status & baseline\n"
            "🌐 /site — raw data from strategy.com\n"
            "🔔 Auto alerts (with image cards) on every buy & sell\n\n"
            "Admin: /check /baseline /checkbuy /checksell /testalert\n"
            "/chatid /info /uptime /clear /restart\n\n"
            "Version: {version}"
        ),
        "testalert_sent": "✅ Test alert sent to Chat ID {chat_id}.",
        "testalert_fail": "❌ Send failed: {error}\nCheck /chatid and X_CHAT_ID on hosting.",
        "testalert_message": "✅ Test: alerts are working. Purchase & sale monitoring is on.",
        "check_checking": "Checking strategy.com and CoinGecko…",
        "check_holdings_line": "Holdings: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "Could not fetch data (strategy.com / CoinGecko)",
        "check_baseline_saved": "Baseline saved: {btc} BTC",
        "check_no_change": "No change. Now {current} BTC, baseline {baseline} BTC (threshold {threshold} BTC).",
        "check_purchase_sent": "Purchase alert sent: +{delta} BTC",
        "check_sale_sent": "Sale alert sent: {delta} BTC",
        "baseline_reset": "Baseline reset to live balance: {btc} BTC",
        "simulate_purchase_setup": "Test baseline lowered ({btc} BTC). Running purchase check…",
        "simulate_sale_setup": "Test baseline raised ({btc} BTC). Running sale check…",
        "setbaseline_usage": (
            "Usage:\n"
            "/setbaseline — baseline = current live balance\n"
            "/setbaseline 800000 — baseline = 800000 BTC (for testing)"
        ),
        "setbaseline_live": "Baseline = current balance: {btc} BTC",
        "setbaseline_invalid": "Enter a BTC number, e.g. /setbaseline 800000",
        "setbaseline_manual": "Baseline set: {btc} BTC.\nNext /check uses live data (threshold {threshold} BTC).",
        "fetch_treasury_fail": "Failed to fetch treasury data (strategy.com / CoinGecko).",
        "hide_menu": "Menu hidden. Send /start to show it again.",
        "access_denied": "⛔ Access denied.",
        "restart": "🔄 Restarting instance…",
        "clear_done": "🧹 Deleted messages: {count}",
        "clear_error": "⚠️ Error clearing messages: {error}",
        "site_disabled": "strategy.com monitoring is off (ENABLE_STRATEGY_SITE=false).",
        "site_fetch_fail": (
            "Could not load strategy.com.\n"
            "Common cause: User-Agent blocked (HTTP 403). "
            "Update main.py to 2026-05-24.4+ and restart."
        ),
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "As of: {date}",
        "site_last_purchase": "Last purchase: {btc} BTC on {date} @ {price}",
        "site_latest_press": "Latest press: {title}",
        "alert_purchase": "💰 Strategy — BTC purchase\nWas: {was} BTC\nNow: {now} BTC\nChange: +{delta} BTC\nValue: {usd}",
        "alert_sale": "📉 Strategy — BTC sale\nWas: {was} BTC\nNow: {now} BTC\nChange: −{delta} BTC\nValue: {usd}",
        "alert_site_purchase": (
            "🏢 Strategy.com — BTC purchase reported\n"
            "Date: {date}\nAcquired: {count} BTC\nPrice: {price}\n"
            "Total holdings: {total} BTC\nSource: {url}"
        ),
        "alert_site_press": "📰 Strategy.com — new press release",
        "alive_ping": "✅ Still alive (uptime: {uptime})",
        "site_note_init": "Strategy.com monitor initialized (no alerts on first run)",
        "site_note_unavailable": "Strategy.com unavailable",
        "site_note_press": "new BTC press release on strategy.com",
        "site_note_purchase": "new purchase on strategy.com (+{btc} BTC)",
        "btn_holdings": "🏦 Holdings",
        "btn_stats": "📊 Stats",
        "lbl_holdings": "🏦 Holdings",
        "lbl_avg_price": "📈 Avg Price",
        "lbl_pnl": "💰 Unrealized PnL",
        "lbl_last_buy": "🟠 Last Buy",
        "lbl_buy_price": "🟠 Buy Price",
        "lbl_source": "📡 Source",
        "source_strategy_short": "Strategy",
        "source_coingecko_short": "CoinGecko",
        "alert_buy_title": "🟠 STRATEGY · BITCOIN BUY",
        "alert_sell_title": "🔴 STRATEGY · BITCOIN SELL",
        "holdings_title": "🟠 STRATEGY · BTC TREASURY",
        "stats_title": "📊 STRATEGY · TREASURY STATS",
        "buy_title": "🟠 STRATEGY · LATEST BUY",
        "buy_none": "No purchase data available yet.",
        "stats_cost_basis": "💵 Cost basis",
        "stats_market_value": "💼 Market value",
        "stats_btc_price": "🪙 BTC price",
        "disclaimer_short": "ℹ️ Informational only · not investment advice · /disclaimer",
        "disclaimer_full": (
            "⚖️ Disclaimer\n\n"
            "SaylorWatchBot shares public treasury/market information for educational "
            "and informational purposes only. It is NOT investment, financial, legal or "
            "tax advice, and not a personal recommendation or an offer/solicitation to "
            "buy or sell any asset.\n\n"
            "Data may be delayed, incomplete or inaccurate. Crypto assets are highly "
            "volatile — you can lose your entire capital. Always do your own research "
            "and consult a licensed professional before making decisions.\n\n"
            "🇺🇸 US: Not financial or investment advice. The operator is not a registered "
            "investment adviser or broker-dealer.\n"
            "🇪🇺 EU/UK: Not a personal recommendation or investment research within the "
            "meaning of MiFID II / FCA rules.\n\n"
            "A paid subscription (if any) only covers access to information and "
            "notifications. It does NOT grant any profit, revenue, dividend, ownership "
            "stake or right to income, and does not guarantee any result.\n\n"
            "Not affiliated with Strategy (MicroStrategy), Michael Saylor or any exchange. "
            "Use at your own risk."
        ),
        "disclaimer_terms": "📄 Terms & Privacy: {url}",
    },
    "ru": {
        "btn_status": "📊 Статус",
        "btn_check": "🔄 Проверить",
        "btn_buy_check": "💰 Тест покупки",
        "btn_sell_check": "📉 Тест продажи",
        "btn_baseline": "📌 Сброс baseline",
        "btn_help": "❓ Помощь",
        "btn_language": "🌐 Язык",
        "btn_hide_menu": "⌨️ Скрыть меню",
        "btn_back": "◀️ В меню",
        "lang_menu_title": "Выберите язык / Choose your language:",
        "lang_set": "Язык: {name}. Меню обновлено.",
        "deny_admin": "⛔ Только для админа.\nUser ID: {user_id}\nX_CHAT_ID: {chat_id}\nДолжны совпадать. /chatid",
        "chatid_help": "Для X_CHAT_ID:\nChat ID: {chat_id}\nUser ID: {user_id}\n\nВ личке обычно совпадают.\nНе используйте ID бота.",
        "start_intro": (
            "SaylorWatchBot — BTC-аналитика по Strategy.\n\n"
            "🏦 /holdings — баланс казны\n"
            "📊 /stats — ср. цена и PnL\n"
            "🟠 /buy — последняя покупка\n"
            "🔔 Авто-алерты на каждую покупку и продажу\n\n"
            "Источник: Strategy · Сборка: {version}"
        ),
        "status_online": "✅ Бот онлайн",
        "status_uptime": "⏱ Аптайм: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 Источник: {source}",
        "status_last_purchase": "🛒 Последняя покупка: {btc} BTC ({date})",
        "status_fetch_fail": "⚠️ Не удалось получить баланс Strategy",
        "status_baseline": "📊 Baseline: {btc} BTC",
        "status_baseline_unset": "📊 Baseline: ещё не задан",
        "status_monitor_error": "⚠️ Ошибка монитора: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": (
            "SaylorWatchBot — справка\n\n"
            "🏦 /holdings — баланс казны\n"
            "📊 /stats — ср. цена, затраты и PnL\n"
            "🟠 /buy — последняя покупка BTC\n"
            "📡 /status — статус бота и baseline\n"
            "🌐 /site — данные с strategy.com\n"
            "🔔 Авто-алерты (с image-карточками) на покупки и продажи\n\n"
            "Админ: /check /baseline /checkbuy /checksell /testalert\n"
            "/chatid /info /uptime /clear /restart\n\n"
            "Версия: {version}"
        ),
        "testalert_sent": "✅ Тест отправлен в Chat ID {chat_id}.",
        "testalert_fail": "❌ Ошибка: {error}\nПроверьте /chatid и X_CHAT_ID.",
        "testalert_message": "✅ Тест: уведомления работают. Мониторинг покупок и продаж включён.",
        "check_checking": "Проверяю strategy.com и CoinGecko…",
        "check_holdings_line": "Баланс: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "Не удалось получить данные (strategy.com / CoinGecko)",
        "check_baseline_saved": "Baseline сохранён: {btc} BTC",
        "check_no_change": "Без изменений. Сейчас {current} BTC, baseline {baseline} BTC (порог {threshold} BTC).",
        "check_purchase_sent": "Алерт покупки: +{delta} BTC",
        "check_sale_sent": "Алерт продажи: {delta} BTC",
        "baseline_reset": "Baseline = live: {btc} BTC",
        "simulate_purchase_setup": "Тестовый baseline ниже ({btc} BTC). Проверка покупки…",
        "simulate_sale_setup": "Тестовый baseline выше ({btc} BTC). Проверка продажи…",
        "setbaseline_usage": "/setbaseline — текущий баланс\n/setbaseline 800000 — для теста",
        "setbaseline_live": "Baseline = {btc} BTC",
        "setbaseline_invalid": "Укажите число, напр. /setbaseline 800000",
        "setbaseline_manual": "Baseline: {btc} BTC. Порог /check: {threshold} BTC.",
        "fetch_treasury_fail": "Нет данных (strategy.com / CoinGecko).",
        "hide_menu": "Меню скрыто. /start — снова показать.",
        "access_denied": "⛔ Доступ запрещён.",
        "restart": "🔄 Перезапуск…",
        "clear_done": "🧹 Удалено сообщений: {count}",
        "clear_error": "⚠️ Ошибка: {error}",
        "site_disabled": "Мониторинг strategy.com выключен.",
        "site_fetch_fail": "Не удалось загрузить strategy.com.\nЧасто HTTP 403 — обновите main.py 2026-05-24.4+.",
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "На дату: {date}",
        "site_last_purchase": "Покупка: {btc} BTC ({date}) @ {price}",
        "site_latest_press": "Пресс: {title}",
        "alert_purchase": "💰 Strategy — покупка BTC\nБыло: {was} BTC\nСейчас: {now} BTC\nИзменение: +{delta} BTC\nОценка: {usd}",
        "alert_sale": "📉 Strategy — продажа BTC\nБыло: {was} BTC\nСейчас: {now} BTC\nИзменение: −{delta} BTC\nОценка: {usd}",
        "alert_site_purchase": (
            "🏢 Strategy.com — покупка BTC\n"
            "Дата: {date}\nКуплено: {count} BTC\nЦена: {price}\n"
            "Всего: {total} BTC\n{url}"
        ),
        "alert_site_press": "📰 Strategy.com — новый пресс-релиз",
        "alive_ping": "✅ Бот работает (аптайм: {uptime})",
        "site_note_init": "Монитор strategy.com инициализирован",
        "site_note_unavailable": "strategy.com недоступен",
        "site_note_press": "новый BTC пресс-релиз",
        "site_note_purchase": "новая покупка (+{btc} BTC)",
        "btn_holdings": "🏦 Баланс",
        "btn_stats": "📊 Статистика",
        "lbl_holdings": "🏦 Баланс",
        "lbl_avg_price": "📈 Ср. цена",
        "lbl_pnl": "💰 Бумажная прибыль",
        "lbl_last_buy": "🟠 Покупка",
        "lbl_buy_price": "🟠 Цена покупки",
        "lbl_source": "📡 Источник",
        "source_strategy_short": "Strategy",
        "source_coingecko_short": "CoinGecko",
        "alert_buy_title": "🟠 STRATEGY · ПОКУПКА BTC",
        "alert_sell_title": "🔴 STRATEGY · ПРОДАЖА BTC",
        "holdings_title": "🟠 STRATEGY · КАЗНА BTC",
        "stats_title": "📊 STRATEGY · СТАТИСТИКА",
        "buy_title": "🟠 STRATEGY · ПОСЛЕДНЯЯ ПОКУПКА",
        "buy_none": "Пока нет данных о покупках.",
        "stats_cost_basis": "💵 Затраты",
        "stats_market_value": "💼 Рыночная стоимость",
        "stats_btc_price": "🪙 Цена BTC",
        "disclaimer_short": "ℹ️ Только информация · не инвест-рекомендация · /disclaimer",
        "disclaimer_full": (
            "⚖️ Дисклеймер\n\n"
            "SaylorWatchBot публикует открытые данные о казне и рынке исключительно в "
            "информационных и образовательных целях. Это НЕ инвестиционная, финансовая, "
            "юридическая или налоговая консультация и НЕ персональная рекомендация, "
            "оферта или призыв покупать/продавать какой-либо актив.\n\n"
            "Данные могут быть неполными, неточными или приходить с задержкой. "
            "Криптоактивы крайне волатильны — можно потерять весь капитал. Всегда "
            "проводите собственный анализ и консультируйтесь с лицензированным "
            "специалистом перед принятием решений.\n\n"
            "🇺🇸 США: Не является финансовой или инвестиционной рекомендацией. Оператор "
            "не является зарегистрированным инвестиционным советником или брокером-дилером.\n"
            "🇪🇺 ЕС/Великобритания: Не является персональной рекомендацией или "
            "инвестиционным исследованием в смысле MiFID II / правил FCA.\n\n"
            "Платная подписка (если есть) оплачивает только доступ к информации и "
            "уведомлениям. Она НЕ даёт права на прибыль, доход, дивиденды, долю или "
            "владение и не гарантирует какой-либо результат.\n\n"
            "Бот не аффилирован со Strategy (MicroStrategy), Майклом Сейлором или какой-либо "
            "биржей. Используйте на свой риск."
        ),
        "disclaimer_terms": "📄 Условия и конфиденциальность: {url}",
    },
    "es": {
        "btn_status": "📊 Estado",
        "btn_check": "🔄 Comprobar",
        "btn_buy_check": "💰 Prueba compra",
        "btn_sell_check": "📉 Prueba venta",
        "btn_baseline": "📌 Reiniciar base",
        "btn_help": "❓ Ayuda",
        "btn_language": "🌐 Idioma",
        "btn_hide_menu": "⌨️ Ocultar menú",
        "btn_back": "◀️ Menú",
        "lang_menu_title": "Elija idioma / Choose language:",
        "lang_set": "Idioma: {name}. Menú actualizado.",
        "deny_admin": "⛔ Solo admin.\nUser ID: {user_id}\nX_CHAT_ID: {chat_id}\nDeben coincidir. /chatid",
        "chatid_help": "Para X_CHAT_ID:\nChat ID: {chat_id}\nUser ID: {user_id}",
        "start_intro": "SaylorWatchBot — tesorería BTC de Strategy.\n\n• Alertas de compras y ventas\n• strategy.com y CoinGecko\n\nBotones o /help. 🌐 Idioma\nBuild: {version}",
        "status_online": "✅ Bot en línea",
        "status_uptime": "⏱ Tiempo activo: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 Fuente: {source}",
        "status_last_purchase": "🛒 Última compra: {btc} BTC ({date})",
        "status_fetch_fail": "⚠️ No se pudo obtener el saldo",
        "status_baseline": "📊 Baseline: {btc} BTC",
        "status_baseline_unset": "📊 Baseline: sin definir",
        "status_monitor_error": "⚠️ Error: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": "Ayuda — botones y /start /status /check /language\nVersión: {version}",
        "testalert_sent": "✅ Prueba enviada a {chat_id}.",
        "testalert_fail": "❌ Error: {error}",
        "testalert_message": "✅ Prueba: alertas activas.",
        "check_checking": "Comprobando strategy.com y CoinGecko…",
        "check_holdings_line": "Saldo: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "Sin datos (strategy.com / CoinGecko)",
        "check_baseline_saved": "Baseline guardado: {btc} BTC",
        "check_no_change": "Sin cambios. {current} BTC, baseline {baseline} (umbral {threshold}).",
        "check_purchase_sent": "Alerta compra: +{delta} BTC",
        "check_sale_sent": "Alerta venta: {delta} BTC",
        "baseline_reset": "Baseline = {btc} BTC",
        "simulate_purchase_setup": "Baseline de prueba ({btc} BTC)…",
        "simulate_sale_setup": "Baseline de prueba ({btc} BTC)…",
        "setbaseline_usage": "/setbaseline o /setbaseline 800000",
        "setbaseline_live": "Baseline = {btc} BTC",
        "setbaseline_invalid": "Número BTC, ej. /setbaseline 800000",
        "setbaseline_manual": "Baseline: {btc} BTC. Umbral: {threshold}.",
        "fetch_treasury_fail": "Error al obtener datos.",
        "hide_menu": "Menú oculto. /start",
        "access_denied": "⛔ Acceso denegado.",
        "restart": "🔄 Reiniciando…",
        "clear_done": "🧹 Eliminados: {count}",
        "clear_error": "⚠️ Error: {error}",
        "site_disabled": "strategy.com desactivado.",
        "site_fetch_fail": "No se pudo cargar strategy.com.",
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "Fecha: {date}",
        "site_last_purchase": "Compra: {btc} BTC ({date}) @ {price}",
        "site_latest_press": "Prensa: {title}",
        "alert_purchase": "💰 Strategy — compra BTC\nAntes: {was}\nAhora: {now}\n+{delta} BTC\n{usd}",
        "alert_sale": "📉 Strategy — venta BTC\nAntes: {was}\nAhora: {now}\n−{delta} BTC\n{usd}",
        "alert_site_purchase": "🏢 Strategy.com — compra\n{date}\n{count} BTC\n{price}\nTotal: {total}\n{url}",
        "alert_site_press": "📰 Strategy.com — comunicado",
        "alive_ping": "✅ Activo ({uptime})",
        "site_note_init": "Monitor strategy.com iniciado",
        "site_note_unavailable": "strategy.com no disponible",
        "site_note_press": "nuevo comunicado BTC",
        "site_note_purchase": "nueva compra (+{btc} BTC)",
    },
    "de": {
        "btn_status": "📊 Status",
        "btn_check": "🔄 Jetzt prüfen",
        "btn_buy_check": "💰 Kauf-Test",
        "btn_sell_check": "📉 Verkauf-Test",
        "btn_baseline": "📌 Baseline zurück",
        "btn_help": "❓ Hilfe",
        "btn_language": "🌐 Sprache",
        "btn_hide_menu": "⌨️ Menü aus",
        "btn_back": "◀️ Menü",
        "lang_menu_title": "Sprache wählen:",
        "lang_set": "Sprache: {name}. Menü aktualisiert.",
        "deny_admin": "⛔ Nur Admin. /chatid",
        "chatid_help": "X_CHAT_ID:\nChat: {chat_id}\nUser: {user_id}",
        "start_intro": "SaylorWatchBot — Strategy BTC-Treasury.\n\n• Kauf-/Verkaufsalarme\n• strategy.com, CoinGecko\n\n{version}",
        "status_online": "✅ Bot online",
        "status_uptime": "⏱ Laufzeit: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 Quelle: {source}",
        "status_last_purchase": "🛒 Letzter Kauf: {btc} BTC ({date})",
        "status_fetch_fail": "⚠️ Saldo nicht abrufbar",
        "status_baseline": "📊 Baseline: {btc} BTC",
        "status_baseline_unset": "📊 Baseline: nicht gesetzt",
        "status_monitor_error": "⚠️ Fehler: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": "Hilfe — /start /status /check /language\n{version}",
        "testalert_sent": "✅ Test an {chat_id}.",
        "testalert_fail": "❌ Fehler: {error}",
        "testalert_message": "✅ Test: Alarme aktiv.",
        "check_checking": "Prüfe strategy.com und CoinGecko…",
        "check_holdings_line": "Bestand: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "Keine Daten",
        "check_baseline_saved": "Baseline: {btc} BTC",
        "check_no_change": "Keine Änderung. {current} BTC, Baseline {baseline}.",
        "check_purchase_sent": "Kaufalarm: +{delta} BTC",
        "check_sale_sent": "Verkaufsalarm: {delta} BTC",
        "baseline_reset": "Baseline: {btc} BTC",
        "simulate_purchase_setup": "Test-Baseline ({btc} BTC)…",
        "simulate_sale_setup": "Test-Baseline ({btc} BTC)…",
        "setbaseline_usage": "/setbaseline oder Zahl",
        "setbaseline_live": "Baseline = {btc} BTC",
        "setbaseline_invalid": "Zahl eingeben, z.B. 800000",
        "setbaseline_manual": "Baseline: {btc} BTC",
        "fetch_treasury_fail": "Daten nicht verfügbar.",
        "hide_menu": "Menü aus. /start",
        "access_denied": "⛔ Zugriff verweigert.",
        "restart": "🔄 Neustart…",
        "clear_done": "🧹 Gelöscht: {count}",
        "clear_error": "⚠️ Fehler: {error}",
        "site_disabled": "strategy.com aus.",
        "site_fetch_fail": "strategy.com nicht erreichbar.",
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "Stand: {date}",
        "site_last_purchase": "Kauf: {btc} BTC ({date}) @ {price}",
        "site_latest_press": "Presse: {title}",
        "alert_purchase": "💰 Strategy — Kauf\n{was} → {now} (+{delta} BTC)\n{usd}",
        "alert_sale": "📉 Strategy — Verkauf\n{was} → {now} (−{delta} BTC)\n{usd}",
        "alert_site_purchase": "🏢 Strategy.com — Kauf\n{date}\n{count} BTC\n{total} gesamt\n{url}",
        "alert_site_press": "📰 Strategy.com — Presse",
        "alive_ping": "✅ Aktiv ({uptime})",
        "site_note_init": "strategy.com Monitor gestartet",
        "site_note_unavailable": "strategy.com nicht verfügbar",
        "site_note_press": "neue BTC-Presse",
        "site_note_purchase": "neuer Kauf (+{btc} BTC)",
    },
    "fr": {
        "btn_status": "📊 Statut",
        "btn_check": "🔄 Vérifier",
        "btn_buy_check": "💰 Test achat",
        "btn_sell_check": "📉 Test vente",
        "btn_baseline": "📌 Réinit. base",
        "btn_help": "❓ Aide",
        "btn_language": "🌐 Langue",
        "btn_hide_menu": "⌨️ Masquer",
        "btn_back": "◀️ Menu",
        "lang_menu_title": "Choisissez la langue:",
        "lang_set": "Langue : {name}. Menu mis à jour.",
        "deny_admin": "⛔ Admin seulement. /chatid",
        "chatid_help": "X_CHAT_ID:\nChat: {chat_id}\nUser: {user_id}",
        "start_intro": "SaylorWatchBot — trésorerie BTC Strategy.\n\n• Alertes achats/ventes\nBuild: {version}",
        "status_online": "✅ Bot en ligne",
        "status_uptime": "⏱ Actif: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 Source: {source}",
        "status_last_purchase": "🛒 Dernier achat: {btc} BTC ({date})",
        "status_fetch_fail": "⚠️ Solde indisponible",
        "status_baseline": "📊 Baseline: {btc} BTC",
        "status_baseline_unset": "📊 Baseline: non définie",
        "status_monitor_error": "⚠️ Erreur: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": "Aide — /start /status /language\n{version}",
        "testalert_sent": "✅ Test envoyé à {chat_id}.",
        "testalert_fail": "❌ Erreur: {error}",
        "testalert_message": "✅ Test: alertes actives.",
        "check_checking": "Vérification strategy.com et CoinGecko…",
        "check_holdings_line": "Solde: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "Données indisponibles",
        "check_baseline_saved": "Baseline: {btc} BTC",
        "check_no_change": "Aucun changement. {current} BTC, baseline {baseline}.",
        "check_purchase_sent": "Alerte achat: +{delta} BTC",
        "check_sale_sent": "Alerte vente: {delta} BTC",
        "baseline_reset": "Baseline: {btc} BTC",
        "simulate_purchase_setup": "Test baseline ({btc} BTC)…",
        "simulate_sale_setup": "Test baseline ({btc} BTC)…",
        "setbaseline_usage": "/setbaseline ou nombre",
        "setbaseline_live": "Baseline = {btc} BTC",
        "setbaseline_invalid": "Nombre BTC requis",
        "setbaseline_manual": "Baseline: {btc} BTC",
        "fetch_treasury_fail": "Échec des données.",
        "hide_menu": "Menu masqué. /start",
        "access_denied": "⛔ Accès refusé.",
        "restart": "🔄 Redémarrage…",
        "clear_done": "🧹 Supprimés: {count}",
        "clear_error": "⚠️ Erreur: {error}",
        "site_disabled": "strategy.com désactivé.",
        "site_fetch_fail": "Impossible de charger strategy.com.",
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "Au: {date}",
        "site_last_purchase": "Achat: {btc} BTC ({date}) @ {price}",
        "site_latest_press": "Presse: {title}",
        "alert_purchase": "💰 Strategy — achat BTC\n{was} → {now} (+{delta})\n{usd}",
        "alert_sale": "📉 Strategy — vente BTC\n{was} → {now} (−{delta})\n{usd}",
        "alert_site_purchase": "🏢 Strategy.com — achat\n{date}\n{count} BTC\n{url}",
        "alert_site_press": "📰 Strategy.com — communiqué",
        "alive_ping": "✅ Actif ({uptime})",
        "site_note_init": "Moniteur strategy.com initialisé",
        "site_note_unavailable": "strategy.com indisponible",
        "site_note_press": "nouveau communiqué BTC",
        "site_note_purchase": "nouvel achat (+{btc} BTC)",
    },
    "zh": {
        "btn_status": "📊 状态",
        "btn_check": "🔄 立即检查",
        "btn_buy_check": "💰 买入测试",
        "btn_sell_check": "📉 卖出测试",
        "btn_baseline": "📌 重置基准",
        "btn_help": "❓ 帮助",
        "btn_language": "🌐 语言",
        "btn_hide_menu": "⌨️ 隐藏菜单",
        "btn_back": "◀️ 返回",
        "lang_menu_title": "选择语言 / Choose language:",
        "lang_set": "语言已设为 {name}。",
        "deny_admin": "⛔ 仅管理员。/chatid",
        "chatid_help": "X_CHAT_ID:\nChat: {chat_id}\nUser: {user_id}",
        "start_intro": "SaylorWatchBot — Strategy BTC 储备监控。\n\n• 买卖提醒\n• strategy.com / CoinGecko\n\n{version}",
        "status_online": "✅ 在线",
        "status_uptime": "⏱ 运行: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 来源: {source}",
        "status_last_purchase": "🛒 最近买入: {btc} BTC ({date})",
        "status_fetch_fail": "⚠️ 无法获取余额",
        "status_baseline": "📊 基准: {btc} BTC",
        "status_baseline_unset": "📊 基准: 未设置",
        "status_monitor_error": "⚠️ 错误: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": "帮助 — /start /status /language\n{version}",
        "testalert_sent": "✅ 已发送到 {chat_id}",
        "testalert_fail": "❌ 失败: {error}",
        "testalert_message": "✅ 测试：提醒正常。",
        "check_checking": "正在检查 strategy.com 和 CoinGecko…",
        "check_holdings_line": "持仓: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "无法获取数据",
        "check_baseline_saved": "基准已保存: {btc} BTC",
        "check_no_change": "无变化。当前 {current} BTC，基准 {baseline}。",
        "check_purchase_sent": "买入提醒: +{delta} BTC",
        "check_sale_sent": "卖出提醒: {delta} BTC",
        "baseline_reset": "基准已重置: {btc} BTC",
        "simulate_purchase_setup": "测试基准 ({btc} BTC)…",
        "simulate_sale_setup": "测试基准 ({btc} BTC)…",
        "setbaseline_usage": "/setbaseline 或数字",
        "setbaseline_live": "基准 = {btc} BTC",
        "setbaseline_invalid": "请输入数字",
        "setbaseline_manual": "基准: {btc} BTC",
        "fetch_treasury_fail": "获取数据失败",
        "hide_menu": "菜单已隐藏。/start",
        "access_denied": "⛔ 拒绝访问",
        "restart": "🔄 重启中…",
        "clear_done": "🧹 已删除: {count}",
        "clear_error": "⚠️ 错误: {error}",
        "site_disabled": "strategy.com 已关闭",
        "site_fetch_fail": "无法加载 strategy.com",
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "日期: {date}",
        "site_last_purchase": "买入: {btc} BTC ({date}) @ {price}",
        "site_latest_press": "新闻: {title}",
        "alert_purchase": "💰 Strategy — 买入\n{was} → {now} (+{delta} BTC)\n{usd}",
        "alert_sale": "📉 Strategy — 卖出\n{was} → {now} (−{delta} BTC)\n{usd}",
        "alert_site_purchase": "🏢 Strategy.com — 买入\n{date}\n{count} BTC\n{url}",
        "alert_site_press": "📰 Strategy.com — 新闻",
        "alive_ping": "✅ 运行中 ({uptime})",
        "site_note_init": "strategy.com 监控已初始化",
        "site_note_unavailable": "strategy.com 不可用",
        "site_note_press": "新 BTC 新闻",
        "site_note_purchase": "新买入 (+{btc} BTC)",
    },
    "ja": {
        "btn_status": "📊 ステータス",
        "btn_check": "🔄 今すぐ確認",
        "btn_buy_check": "💰 購入テスト",
        "btn_sell_check": "📉 売却テスト",
        "btn_baseline": "📌 基準リセット",
        "btn_help": "❓ ヘルプ",
        "btn_language": "🌐 言語",
        "btn_hide_menu": "⌨️ メニュー非表示",
        "btn_back": "◀️ メニュー",
        "lang_menu_title": "言語を選択 / Choose language:",
        "lang_set": "言語: {name}",
        "deny_admin": "⛔ 管理者のみ /chatid",
        "chatid_help": "X_CHAT_ID:\nChat: {chat_id}\nUser: {user_id}",
        "start_intro": "SaylorWatchBot — Strategy BTC 監視\n\n• 売買アラート\n{version}",
        "status_online": "✅ オンライン",
        "status_uptime": "⏱ 稼働: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 ソース: {source}",
        "status_last_purchase": "🛒 最終購入: {btc} BTC ({date})",
        "status_fetch_fail": "⚠️ 残高取得失敗",
        "status_baseline": "📊 基準: {btc} BTC",
        "status_baseline_unset": "📊 基準: 未設定",
        "status_monitor_error": "⚠️ エラー: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": "ヘルプ — /language\n{version}",
        "testalert_sent": "✅ 送信: {chat_id}",
        "testalert_fail": "❌ エラー: {error}",
        "testalert_message": "✅ テスト成功",
        "check_checking": "strategy.com と CoinGecko を確認中…",
        "check_holdings_line": "保有量: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "データ取得失敗",
        "check_baseline_saved": "基準保存: {btc} BTC",
        "check_no_change": "変化なし。{current} BTC、基準 {baseline}",
        "check_purchase_sent": "購入アラート: +{delta} BTC",
        "check_sale_sent": "売却アラート: {delta} BTC",
        "baseline_reset": "基準リセット: {btc} BTC",
        "simulate_purchase_setup": "テスト基準 ({btc} BTC)…",
        "simulate_sale_setup": "テスト基準 ({btc} BTC)…",
        "setbaseline_usage": "/setbaseline または数値",
        "setbaseline_live": "基準 = {btc} BTC",
        "setbaseline_invalid": "数値を入力",
        "setbaseline_manual": "基準: {btc} BTC",
        "fetch_treasury_fail": "データ取得失敗",
        "hide_menu": "メニュー非表示 /start",
        "access_denied": "⛔ 拒否",
        "restart": "🔄 再起動…",
        "clear_done": "🧹 削除: {count}",
        "clear_error": "⚠️ エラー: {error}",
        "site_disabled": "strategy.com 無効",
        "site_fetch_fail": "strategy.com 読込失敗",
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "日付: {date}",
        "site_last_purchase": "購入: {btc} BTC ({date}) @ {price}",
        "site_latest_press": "プレス: {title}",
        "alert_purchase": "💰 Strategy — 購入\n{was} → {now} (+{delta} BTC)\n{usd}",
        "alert_sale": "📉 Strategy — 売却\n{was} → {now} (−{delta} BTC)\n{usd}",
        "alert_site_purchase": "🏢 Strategy.com — 購入\n{date}\n{count} BTC\n{url}",
        "alert_site_press": "📰 Strategy.com — プレス",
        "alive_ping": "✅ 稼働中 ({uptime})",
        "site_note_init": "strategy.com 監視開始",
        "site_note_unavailable": "strategy.com 利用不可",
        "site_note_press": "新しい BTC プレス",
        "site_note_purchase": "新規購入 (+{btc} BTC)",
    },
    "pt": {
        "btn_status": "📊 Status",
        "btn_check": "🔄 Verificar",
        "btn_buy_check": "💰 Teste compra",
        "btn_sell_check": "📉 Teste venda",
        "btn_baseline": "📌 Redefinir base",
        "btn_help": "❓ Ajuda",
        "btn_language": "🌐 Idioma",
        "btn_hide_menu": "⌨️ Ocultar menu",
        "btn_back": "◀️ Menu",
        "lang_menu_title": "Escolha o idioma:",
        "lang_set": "Idioma: {name}. Menu atualizado.",
        "deny_admin": "⛔ Somente admin. /chatid",
        "chatid_help": "X_CHAT_ID:\nChat: {chat_id}\nUser: {user_id}",
        "start_intro": "SaylorWatchBot — tesouraria BTC da Strategy.\n\n• Alertas de compra e venda\nBuild: {version}",
        "status_online": "✅ Bot online",
        "status_uptime": "⏱ Ativo: {uptime}",
        "status_balance": "🏢 {name}\n💰 {btc} BTC (~{usd})\n📡 Fonte: {source}",
        "status_last_purchase": "🛒 Última compra: {btc} BTC ({date})",
        "status_fetch_fail": "⚠️ Falha ao obter saldo",
        "status_baseline": "📊 Baseline: {btc} BTC",
        "status_baseline_unset": "📊 Baseline: não definida",
        "status_monitor_error": "⚠️ Erro: {error}",
        "source_strategy": "strategy.com",
        "source_coingecko": "CoinGecko",
        "help_body": "Ajuda — /start /status /language\n{version}",
        "testalert_sent": "✅ Teste enviado para {chat_id}.",
        "testalert_fail": "❌ Erro: {error}",
        "testalert_message": "✅ Teste: alertas ativos.",
        "check_checking": "Verificando strategy.com e CoinGecko…",
        "check_holdings_line": "Saldo: {result}",
        "check_site_line": "Strategy.com: {result}",
        "check_fetch_error": "Sem dados",
        "check_baseline_saved": "Baseline: {btc} BTC",
        "check_no_change": "Sem alteração. {current} BTC, baseline {baseline}.",
        "check_purchase_sent": "Alerta compra: +{delta} BTC",
        "check_sale_sent": "Alerta venda: {delta} BTC",
        "baseline_reset": "Baseline: {btc} BTC",
        "simulate_purchase_setup": "Baseline de teste ({btc} BTC)…",
        "simulate_sale_setup": "Baseline de teste ({btc} BTC)…",
        "setbaseline_usage": "/setbaseline ou número",
        "setbaseline_live": "Baseline = {btc} BTC",
        "setbaseline_invalid": "Informe um número BTC",
        "setbaseline_manual": "Baseline: {btc} BTC",
        "fetch_treasury_fail": "Falha ao obter dados.",
        "hide_menu": "Menu oculto. /start",
        "access_denied": "⛔ Acesso negado.",
        "restart": "🔄 Reiniciando…",
        "clear_done": "🧹 Apagadas: {count}",
        "clear_error": "⚠️ Erro: {error}",
        "site_disabled": "strategy.com desativado.",
        "site_fetch_fail": "Não foi possível carregar strategy.com.",
        "site_header": "🌐 strategy.com — {btc} BTC",
        "site_as_of": "Em: {date}",
        "site_last_purchase": "Compra: {btc} BTC ({date}) @ {price}",
        "site_latest_press": "Imprensa: {title}",
        "alert_purchase": "💰 Strategy — compra BTC\n{was} → {now} (+{delta})\n{usd}",
        "alert_sale": "📉 Strategy — venda BTC\n{was} → {now} (−{delta})\n{usd}",
        "alert_site_purchase": "🏢 Strategy.com — compra\n{date}\n{count} BTC\n{url}",
        "alert_site_press": "📰 Strategy.com — release",
        "alive_ping": "✅ Ativo ({uptime})",
        "site_note_init": "Monitor strategy.com iniciado",
        "site_note_unavailable": "strategy.com indisponível",
        "site_note_press": "novo release BTC",
        "site_note_purchase": "nova compra (+{btc} BTC)",
    },
}
# fmt: on

# Fill missing keys from English
for _code in SUPPORTED_LANGS:
    if _code == "en":
        continue
    for _key, _val in TEXTS["en"].items():
        TEXTS[_code].setdefault(_key, _val)

MENU_ACTIONS = (
    "status",
    "holdings",
    "stats",
    "check",
    "buy_check",
    "sell_check",
    "baseline",
    "help",
    "language",
    "hide_menu",
    "back",
)

_LANG_LABEL_TO_CODE = {label: code for code, label in LANG_OPTIONS}


def t(lang: str, key: str, **kwargs: Any) -> str:
    code = lang if lang in SUPPORTED_LANGS else DEFAULT_LANG
    template = TEXTS[code].get(key) or TEXTS["en"][key]
    return template.format(**kwargs) if kwargs else template


def lang_from_button(text: str) -> str | None:
    return _LANG_LABEL_TO_CODE.get(text.strip())


def resolve_menu_action(text: str) -> str | None:
    stripped = text.strip()
    if lang_from_button(stripped):
        return None
    for code in SUPPORTED_LANGS:
        for action in MENU_ACTIONS:
            if stripped == t(code, f"btn_{action}"):
                return action
    return None
