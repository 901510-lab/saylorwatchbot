import os
import asyncio
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from telegram import Bot
from dotenv import load_dotenv

# === Загрузка переменных ===
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("X_CHAT_ID")
CHECK_URL = os.getenv("CHECK_URL")
CHECK_INTERVAL_MIN = int(os.getenv("CHECK_INTERVAL_MIN", "15"))
SEND_OK_NOTIFICATIONS = os.getenv("SEND_OK_NOTIFICATIONS", "true").lower() == "true"

bot = Bot(token=BOT_TOKEN)

LOG_FILE = "uptime.log"

# === Логирование в файл ===
def write_log(message: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] {message}\n")

# === Проверка сайта ===
def check_website():
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    try:
        response = requests.get(CHECK_URL, timeout=10)
        if response.status_code == 200:
            msg = f"🟢 [{timestamp}] Сайт {CHECK_URL} работает (код {response.status_code})"
            print(msg)
            write_log(msg)
            if SEND_OK_NOTIFICATIONS:
                asyncio.run(bot.send_message(chat_id=CHAT_ID, text=msg))
        else:
            msg = f"⚠️ [{timestamp}] Сайт {CHECK_URL} ответил кодом {response.status_code}"
            print(msg)
            write_log(msg)
            asyncio.run(bot.send_message(chat_id=CHAT_ID, text=msg))
    except Exception as e:
        msg = f"🔴 [{timestamp}] Ошибка при проверке {CHECK_URL}: {e}"
        print(msg)
        write_log(msg)
        asyncio.run(bot.send_message(chat_id=CHAT_ID, text=msg))

# === Планировщик ===
scheduler = BackgroundScheduler()
scheduler.add_job(check_website, 'interval', minutes=CHECK_INTERVAL_MIN)
scheduler.start()

# === Постоянный цикл, чтобы Render не засыпал ===
async def keep_alive():
    print("🚀 Бот запущен и работает 24/7!")
    while True:
        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(keep_alive())
