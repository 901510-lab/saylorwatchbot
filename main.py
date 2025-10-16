import os
import re
import json
import asyncio
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from aiohttp import web
from dotenv import load_dotenv

# === Настройки ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("X_CHAT_ID")
CHECK_URL = os.getenv("CHECK_URL", "https://saylortracker.com")
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "15"))
SEND_OK_NOTIFICATIONS = os.getenv("SEND_OK_NOTIFICATIONS", "true").lower() == "true"
WEBHOOK_PORT = int(os.getenv("PORT", 8080))

bot = Bot(token=BOT_TOKEN)
LOG_FILE = "uptime.log"
STATE_FILE = "saylor_state.json"

# === Вспомогательные функции ===
def write_log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_btc": 0}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

# === Проверка сайта ===
def check_website():
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        response = requests.get(CHECK_URL, timeout=10)
        if response.status_code == 200:
            msg = (
                f"🟢 [{timestamp}] Сайт {CHECK_URL} работает (код 200)\n"
                f"🟢 [{timestamp}] The website {CHECK_URL} is live (code 200)"
            )
            write_log(msg)
            if SEND_OK_NOTIFICATIONS:
                asyncio.run(bot.send_message(chat_id=CHAT_ID, text=msg))
        else:
            msg = (
                f"⚠️ [{timestamp}] Сайт {CHECK_URL} ответил кодом {response.status_code}\n"
                f"⚠️ [{timestamp}] The website {CHECK_URL} returned status {response.status_code}"
            )
            write_log(msg)
            asyncio.run(bot.send_message(chat_id=CHAT_ID, text=msg))
    except Exception as e:
        msg = (
            f"🔴 [{timestamp}] Ошибка при проверке {CHECK_URL}: {e}\n"
            f"🔴 [{timestamp}] Error while checking {CHECK_URL}: {e}"
        )
        write_log(msg)
        asyncio.run(bot.send_message(chat_id=CHAT_ID, text=msg))

# === Проверка покупок BTC на SaylorTracker ===
def check_saylortracker(triggered_by_webhook=False, triggered_by_command=False):
    url = (
        "https://saylortracker.com/api/partner-companies"
        "?companies=MSTR&include_historical_processed_metrics=true"
        "&include_partner_info=true&tab=charts"
    )
    ts = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()

        btc_now = None
        try:
            btc_now = int(data["MSTR"]["metrics"]["total_btc"])
        except Exception:
            text = json.dumps(data)
            match = re.search(r'"total_btc"\s*:\s*"?([\d,]+)"?', text)
            if match:
                btc_now = int(match.group(1).replace(",", ""))

        if btc_now is None:
            write_log(f"⚠️ [{ts}] Не удалось найти BTC в ответе API / Could not find BTC value")
            return

        state = load_state()
        last_btc = state.get("last_btc", 0)

        # Первая инициализация
        if last_btc == 0:
            save_state({"last_btc": btc_now})
            write_log(f"ℹ️ [{ts}] Инициализация: {btc_now:,} BTC / Initialized value".replace(",", " "))
            return

        # Новая покупка BTC
        if btc_now > last_btc:
            diff = btc_now - last_btc
            msg = (
                f"🟡 [{ts}] Новая покупка BTC обнаружена!\n"
                f"+{diff:,} BTC → {btc_now:,} BTC (MicroStrategy)\n\n"
                f"🟡 [{ts}] New Bitcoin purchase detected!\n"
                f"+{diff:,} BTC → {btc_now:,} BTC (MicroStrategy)"
            ).replace(",", " ")
            write_log(msg)
            asyncio.run(bot.send_message(chat_id=CHAT_ID, text=msg))
            save_state({"last_btc": btc_now})
        else:
            trigger = "🌐 (Webhook)" if triggered_by_webhook else "⚙️ (Таймер)" if not triggered_by_command else "📲 (Команда)"
            msg = (
                f"{trigger} [{ts}] Без изменений ({btc_now:,} BTC)\n"
                f"{trigger} [{ts}] No changes detected ({btc_now:,} BTC)"
            ).replace(",", " ")
            write_log(msg)

    except Exception as e:
        write_log(f"🔴 Ошибка при проверке saylortracker: {e}\n🔴 Error while checking saylortracker: {e}")

# === Telegram команды ===
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("📭 Лог пока пуст / Log is empty.")
        return
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()[-5:]
    text = "📊 Последние события / Recent events:\n\n" + "".join(lines)
    await update.message.reply_text(text)

async def trigger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚀 Проверка SaylorTracker запущена / Manual check started.")
    check_saylortracker(triggered_by_command=True)

# === Telegram бот ===
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("status", status))
app.add_handler(CommandHandler("trigger", trigger))

# === Планировщик ===
scheduler = BackgroundScheduler()
scheduler.add_job(check_website, "interval", minutes=CHECK_INTERVAL_MIN)
scheduler.add_job(check_saylortracker, "interval", minutes=60)
scheduler.start()

# === Webhook сервер (aiohttp) ===
async def handle_webhook(request):
    try:
        data = await request.json()
        source = data.get("source", "external")
        write_log(f"🌐 Получен webhook от {source} / Webhook received from {source}")
    except Exception:
        write_log("🌐 Получен webhook без данных / Webhook received (no JSON)")

    check_saylortracker(triggered_by_webhook=True)
    return web.Response(text="Webhook received and processed")

# === Keep Alive / Render entrypoint ===
async def keep_alive():
    write_log("🚀 SaylorWatchBot запущен / started (24/7 mode)")
    app_web = web.Application()
    app_web.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app_web)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()

    asyncio.create_task(app.run_polling())
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    import asyncio

    async def main():
        write_log("🚀 SaylorWatchBot запущен / started (24/7 mode)")
        app_web = web.Application()
        app_web.router.add_post("/webhook", handle_webhook)
        runner = web.AppRunner(app_web)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
        await site.start()

        # Отправляем уведомление о старте
        try:
            await bot.send_message(chat_id=CHAT_ID, text="✅ Бот успешно запущен / Bot started successfully")
        except Exceptio
