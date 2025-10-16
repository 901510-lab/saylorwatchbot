import os
import json
import time
import signal
import asyncio
import threading
from aiohttp import web
from telegram import Bot
from telegram.ext import ApplicationBuilder

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("X_CHAT_ID", "0"))
WEBHOOK_PORT = int(os.getenv("PORT", "10000"))

bot = Bot(token=BOT_TOKEN)

def write_log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

# === HTTP-хендлер (для future health/ping) ===
async def handle_webhook(request):
    data = await request.json()
    write_log(f"📩 Webhook data: {data}")
    return web.Response(text="OK")

# === учёт рестартов ===
RESTART_FILE = "restart_state.json"

def load_restart_state():
    try:
        with open(RESTART_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"restart_count": 0, "last_start_ts": None}

def save_restart_state(state: dict):
    with open(RESTART_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)

def fmt_seconds(sec: float) -> str:
    if sec is None or sec < 0:
        return "n/a"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)

# === Основной запуск ===
if __name__ == "__main__":
    write_log("🚀 SaylorWatchBot запущен / started (24/7 mode)")

    async def start_web():
        app_web = web.Application()
        app_web.router.add_get("/healthz", lambda _: web.Response(text="ok"))
        app_web.router.add_post("/webhook", handle_webhook)
        runner = web.AppRunner(app_web)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
        await site.start()
        write_log(f"🌐 Web server started on port {WEBHOOK_PORT}")

    # === Telegram-бот в отдельном потоке ===
    def start_bot():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        state = load_restart_state()
        prev_start = state.get("last_start_ts")
        uptime_prev = fmt_seconds(time.time() - prev_start) if prev_start else "n/a"
        state["restart_count"] = int(state.get("restart_count", 0)) + 1
        state["last_start_ts"] = int(time.time())
        save_restart_state(state)

        inst = os.getenv("RENDER_INSTANCE_ID", "unknown")
        commit = os.getenv("RENDER_GIT_COMMIT", "unknown")[:7]

        start_msg = (
            f"✅ Бот успешно запущен / Bot started successfully\n"
            f"🔁 Рестарт №: {state['restart_count']} | Пред. аптайм: {uptime_prev}\n"
            f"🧩 Instance: {inst} | Commit: {commit}"
        )

        try:
            loop.run_until_complete(bot.send_message(chat_id=CHAT_ID, text=start_msg))
        except Exception as e:
            write_log(f"⚠️ Не удалось отправить стартовое сообщение: {e}")

        # === корректный запуск polling без сигналов ===
        async def run_polling():
            app = ApplicationBuilder().token(BOT_TOKEN).build()
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            while True:
                await asyncio.sleep(60)

        loop.run_until_complete(run_polling())

    # === Запускаем web-сервер и keep-alive в основном loop ===
    asyncio.run(start_web())

    # === Стартуем Telegram-бот в отдельном потоке ===
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

    # === Ловим SIGTERM и SIGINT для уведомлений ===
    def shutdown_handler(*_):
        try:
            asyncio.run(bot.send_message(
                chat_id=CHAT_ID,
                text="🛑 Бот завершается (деплой/рестарт) / Bot is shutting down (deploy/restart)"
            ))
        except Exception:
            pass
        write_log("🛑 Завершение работы / Shutdown initiated")
        os._exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    # === основной keep-alive ===
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        shutdown_handler()
