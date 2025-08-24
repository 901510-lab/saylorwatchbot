import os, time, logging, requests
from bs4 import BeautifulSoup
from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# === НАСТРОЙКИ ===
TOKEN = os.environ["TELEGRAM_TOKEN"]  # токен берём из переменной среды
bot = Bot(token=TOKEN)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def ping(update: Update, context: CallbackContext):
    update.message.reply_text("SaylorWatchBot онлайн ✅")

def saylor(update: Update, context: CallbackContext):
    """Пример: парсим страницу и шлём апдейт"""
    try:
        url = "https://example.com"  # подставь свой источник
        html = requests.get(url, timeout=15).text
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.string if soup.title else "no-title"
        update.message.reply_text(f"Последнее обновление: {title}")
    except Exception as e:
        logging.exception(e)
        update.message.reply_text(f"Ошибка: {e}")

def main():
    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("ping", ping))
    dp.add_handler(CommandHandler("saylor", saylor))
    updater.start_polling(drop_pending_updates=True)
    logging.info("SaylorWatchBot запущен (long polling)")
    updater.idle()

if _name_ == "_main_":
    main()
