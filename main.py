# main.py
# SaylorWatchBot — мониторинг страницы с уведомлениями в Telegram
# Совместим с python-telegram-bot==13.15

import os
import json
import time
import signal
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from telegram import Bot, Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

# ---------- ЛОГИ ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
log = logging.getLogger("SaylorWatchBot")

# ---------- НАСТРОЙКИ И .ENV ----------
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
CHAT_ID   = os.getenv("X_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
CHECK_URL = os.getenv("CHECK_URL", "").strip()
STATE_FILE = os.getenv("STATE_FILE", str(Path.home() / ".saylorwatch_state.json"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "15"))
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "15"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env")
if not CHAT_ID:
    log.warning("X_CHAT_ID не задан: уведомления по расписанию не будут отправляться до его указания")

# ---------- ГЛОБАЛЬНОЕ СОСТОЯНИЕ ----------
state = {
    "url": CHECK_URL,
    "last_digest": None,
    "last_checked": None,
    "last_changed": None,
    "interval_min": CHECK_INTERVAL_MIN,
}

def load_state():
    fp = Path(STATE_FILE)
    if fp.exists():
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            state.update(data)
            log.info("Состояние загружено из %s", STATE_FILE)
        except Exception as e:
            log.warning("Не удалось прочитать состояние: %s", e)

def save_state():
    try:
        Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(STATE_FILE).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Не удалось сохранить состояние: %s", e)

load_state()

# ---------- УТИЛИТЫ ----------
def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()

def fetch_url(url: str) -> str:
    headers = {
        "User-Agent": "SaylorWatchBot/1.0 (+https://t.me/)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    # подрезаем слишком тяжёлые страницы
    text = r.text
    if len(text) > 2_000_000:
        text = text[:2_000_000]
    return text

def send(msg: str, parse_mode: str = None):
    if not CHAT_ID:
        log.info("CHAT_ID не задан — пропускаю отправку: %s", msg)
        return
    try:
        Bot(BOT_TOKEN).send_message(chat_id=CHAT_ID, text=msg, parse_mode=parse_mode or ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        log.warning("Не удалось отправить сообщение: %s", e)

# ---------- ОСНОВНАЯ ПРОВЕРКА ----------
def check_once(context: CallbackContext = None, manual: bool = False):
    if not state["url"]:
        log.info("URL не задан. Используй /seturl <url>")
        return

    url = state["url"]
    ts_start = time.time()
    try:
        html = fetch_url(url)
        dgst = digest_text(html)
        state["last_checked"] = now_iso()

        if state.get("last_digest") != dgst:
            # Изменение! Обновляем и уведомляем
            prev = state.get("last_digest")
            state["last_digest"] = dgst
            state["last_changed"] = state["last_checked"]
            save_state()

            title = "Обновление на странице" if prev else "Первичная фиксация состояния страницы"
            msg = (
                f"<b>{title}</b>\n"
                f"URL: <code>{url}</code>\n"
                f"Время: <code>{state['last_changed']}</code>\n"
            )
            send(msg)
            log.info("Изменение зафиксировано для %s", url)
        else:
            # без изменений
            save_state()
            log.info("Без изменений (%s)", url)
            if manual:
                send(f"Проверка вручную: изменений нет\nURL: <code>{url}</code>\nВремя: <code>{state['last_checked']}</code>")

    except requests.HTTPError as e:
        log.warning("HTTP ошибка %s при обращении к %s", e, url)
        if manual:
            send(f"HTTP ошибка при проверке: <code>{e}</code>\nURL: <code>{url}</code>")
    except Exception as e:
        log.warning("Ошибка проверки %s: %s", url, e)
        if manual:
            send(f"Ошибка проверки: <code>{e}</code>\nURL: <code>{url}</code>")
    finally:
        log.debug("Проверка заняла %.2f сек", time.time() - ts_start)

# ---------- КОМАНДЫ БОТА ----------
def cmd_start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "SaylorWatchBot запущен.\n"
        "Команды: /id /status /force /seturl /setinterval /help"
    )

def cmd_help(update: Update, context: CallbackContext):
    update.message.reply_text(
        "/id — показать ваш chat_id\n"
        "/status — показать текущие настройки и время последней проверки\n"
        "/force — немедленная проверка сейчас\n"
        "/seturl <url> — изменить мониторимый URL\n"
        "/setinterval <минуты> — изменить интервал проверок\n"
        "/help — помощь"
    )

def cmd_id(update: Update, context: CallbackContext):
    update.message.reply_text(f"Ваш chat_id: {update.effective_chat.id}")

def cmd_status(update: Update, context: CallbackContext):
    msg = (
        f"<b>Статус</b>\n"
        f"URL: <code>{state.get('url') or '—'}</code>\n"
        f"Интервал: <code>{state.get('interval_min')} мин</code>\n"
        f"Последняя проверка: <code>{state.get('last_checked') or '—'}</code>\n"
        f"Последнее изменение: <code>{state.get('last_changed') or '—'}</code>\n"
        f"Файл состояния: <code>{STATE_FILE}</code>"
    )
    update.message.reply_text(msg, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

def cmd_force(update: Update, context: CallbackContext):
    check_once(manual=True)

def cmd_seturl(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Использование: /seturl <url>")
        return
    url = context.args[0].strip()
    state["url"] = url
    # сбрасываем digest, чтобы первое изменение зафиксировалось корректно
    state["last_digest"] = None
    save_state()
    update.message.reply_text(f"URL обновлён: {url}\nПровожу проверку…")
    check_once(manual=True)

def cmd_setinterval(update: Update, context: CallbackContext):
    if not context.args:
        update.message.reply_text("Использование: /setinterval <минуты>")
        return
    try:
        m = max(1, int(context.args[0]))
    except ValueError:
        update.message.reply_text("Интервал должен быть числом минут (целое число ≥1).")
        return
    state["interval_min"] = m
    save_state()
    # перенастроим планировщик
    reschedule(m)
    update.message.reply_text(f"Интервал проверок обновлён: каждые {m} мин.")

# ---------- ПЛАНИРОВЩИК ----------
scheduler = BackgroundScheduler()
job_id = "watch_job"

def reschedule(minutes: int):
    try:
        if scheduler.get_job(job_id):
            scheduler.reschedule_job(job_id, trigger=IntervalTrigger(minutes=minutes))
        else:
            scheduler.add_job(check_once, IntervalTrigger(minutes=minutes), id=job_id, max_instances=1, coalesce=True)
        log.info("Запланировано каждые %d минут", minutes)
    except Exception as e:
        log.warning("Не удалось перенастроить планировщик: %s", e)

# ---------- MAIN ----------
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", cmd_start))
    dp.add_handler(CommandHandler("help", cmd_help))
    dp.add_handler(CommandHandler("id", cmd_id))
    dp.add_handler(CommandHandler("status", cmd_status))
    dp.add_handler(CommandHandler("force", cmd_force))
    dp.add_handler(CommandHandler("seturl", cmd_seturl))
    dp.add_handler(CommandHandler("setinterval", cmd_setinterval))

    # Старт бота
    updater.start_polling()
    log.info("SaylorWatchBot: бот запущен")

    # Первичная проверка и планировщик
    if state["url"]:
        check_once(manual=False)
    if state["interval_min"] > 0:
        reschedule(state["interval_min"])
        scheduler.start()

    # Пробуем отправить тест
    if CHAT_ID:
        try:
            Bot(BOT_TOKEN).send_message(chat_id=CHAT_ID, text="SaylorWatchBot запущен ✅")
        except Exception as e:
            log.info("Не удалось отправить тест: %s", e)

    # Корректное завершение по сигналам
    def shutdown(*_):
        log.info("Остановка…")
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
        updater.stop()
        updater.is_idle = False

    # signal.signal(signal.SIGINT, shutdown)
    # signal.signal(signal.SIGTERM, shutdown)

    updater.idle()

if __name__ == "__main__":
    main()
