"""Публикация анонса бота: отправляет карточку с подписью в канал/чат.

Запуск на сервере (там, где задан BOT_TOKEN):

    POST_CHAT_ID=@your_channel python3 post_announcement.py
    # или
    python3 post_announcement.py @your_channel

Опции через переменные окружения:
    POST_CHAT_ID  — куда постить: @username канала или числовой chat_id
    POST_LANG     — en (по умолчанию) или fr
    POST_IMAGE    — путь к картинке (по умолчанию assets/announcement_card.png)
    POST_PIN      — 1, чтобы сразу закрепить сообщение (бот должен быть админом)

Требуется: бот добавлен в канал как администратор с правом публикации
(и правом закрепления, если используешь POST_PIN=1).
"""

import asyncio
import os
import sys

from telegram import Bot

CAPTIONS = {
    "en": (
        "🟠 SaylorWatch tracks Bitcoin whale moves in real time.\n\n"
        "Instant alerts when Strategy (Michael Saylor) buys or sells BTC — "
        "with clean Bloomberg-style cards.\n\n"
        "₿ Holdings · avg price · unrealized PnL\n"
        "🚨 Buy/sell alerts\n"
        "🖼 Auto cards — easy to repost\n"
        "🌐 8 languages\n\n"
        "Try free → t.me/Saylor_w_bot   (tap /start)"
    ),
    "fr": (
        "🟠 SaylorWatch surveille les baleines du Bitcoin en temps réel.\n\n"
        "Alertes instantanées quand Strategy (Michael Saylor) achète ou vend "
        "du BTC — avec des cartes épurées façon Bloomberg.\n\n"
        "₿ Holdings · prix moyen · PnL latent\n"
        "🚨 Alertes achat/vente\n"
        "🖼 Cartes auto — faciles à partager\n"
        "🌐 8 langues\n\n"
        "Gratuit → t.me/Saylor_w_bot   (tape /start)"
    ),
}


async def main() -> int:
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        print("ОШИБКА: переменная BOT_TOKEN не задана.")
        return 1

    chat = os.environ.get("POST_CHAT_ID", "").strip() or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not chat:
        print("ОШИБКА: укажи канал/чат: POST_CHAT_ID=@your_channel или аргументом.")
        return 1

    lang = os.environ.get("POST_LANG", "en").strip().lower()
    caption = CAPTIONS.get(lang, CAPTIONS["en"])
    image = os.environ.get("POST_IMAGE", "assets/announcement_card.png")
    do_pin = os.environ.get("POST_PIN", "").strip() in {"1", "true", "yes", "on"}

    if not os.path.exists(image):
        print(f"ОШИБКА: картинка не найдена: {image}")
        return 1

    bot = Bot(token)
    with open(image, "rb") as f:
        msg = await bot.send_photo(chat_id=chat, photo=f, caption=caption)
    print(f"✅ Опубликовано. chat={chat} message_id={msg.message_id}")

    if do_pin:
        try:
            await bot.pin_chat_message(chat_id=chat, message_id=msg.message_id, disable_notification=True)
            print("📌 Сообщение закреплено.")
        except Exception as exc:
            print(f"⚠️ Не удалось закрепить (нужны права админа?): {type(exc).__name__}: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
