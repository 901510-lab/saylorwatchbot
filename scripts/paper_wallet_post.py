#!/usr/bin/env python3
"""CLI для Paper Wallet — локальный тест или ручной пост (основной режим: сервер main.py).

Примеры:
    python3 scripts/paper_wallet_post.py --dry-run
    python3 scripts/paper_wallet_post.py --force
    python3 scripts/paper_wallet_post.py --check
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_env_file(path: Path) -> None:
    """Простой парсер .env — работает без python-dotenv."""
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    except OSError:
        pass


_load_env_file(ROOT / ".env")
_load_env_file(Path(__file__).resolve().parent / "paper_wallet.env")

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    load_dotenv(Path(__file__).resolve().parent / "paper_wallet.env")
except ImportError:
    pass

from paper_wallet import (  # noqa: E402
    PAPER_WALLET_CHANNEL,
    PAPER_WALLET_POST_HOUR,
    PAPER_WALLET_POST_MINUTE,
    PAPER_WALLET_TIMEZONE,
    already_posted_today,
    bot_link,
    bot_name,
    build_random_separator_block,
    build_ticker_line,
    caption_for_block,
    collect_daily_sets,
    deliver_paper_wallet_daily,
    digest_tz,
    paper_wallet_enabled,
    fetch_global_snapshot,
    load_coin_icons,
    promo_line,
    render_market_table,
    today_key,
)

logger = logging.getLogger(__name__)


async def run(*, dry_run: bool, force: bool) -> int:
    if not dry_run and not force and already_posted_today():
        print(f"SKIP: already posted {today_key()}")
        return 0

    from datetime import datetime

    tz = digest_tz()
    now = datetime.now(tz)

    top_rows, bottom_rows, mid_symbols = await collect_daily_sets()
    if not top_rows or not bottom_rows:
        print("ERROR: CoinGecko returned no data")
        return 1

    btc_change = None
    for r in top_rows:
        if r.symbol == "BTC":
            btc_change = r.change_24h
            break
    global_snap = await fetch_global_snapshot(btc_change_24h=btc_change)
    icons_top, icons_bottom = await asyncio.gather(
        load_coin_icons(top_rows),
        load_coin_icons(bottom_rows),
    )

    promo = promo_line() if os.environ.get("PAPER_WALLET_IMAGE_PROMO", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    } else ""
    top_png = render_market_table(
        top_rows,
        title="Cryptocurrency Prices by Market Cap",
        subtitle=f"Top {len(top_rows)} · USD · {now.strftime('%d %b %Y')}",
        promo_line=promo,
        global_snap=global_snap,
        icons=icons_top,
    )
    bottom_png = render_market_table(
        bottom_rows,
        title="Smallest Market Cap (with volume)",
        subtitle=f"Random {len(bottom_rows)} · min volume filter · {now.strftime('%d %b %Y')}",
        promo_line=promo,
        global_snap=global_snap,
        icons=icons_bottom,
    )
    if top_png is None or bottom_png is None:
        print("ERROR: PNG render failed (Pillow?)")
        return 1

    sep_top = build_random_separator_block()
    tickers = build_ticker_line(mid_symbols)
    sep_bottom = build_random_separator_block()

    if dry_run:
        out_dir = ROOT / "assets" / "paper_wallet_preview"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "top.png").write_bytes(top_png.getvalue())
        (out_dir / "bottom.png").write_bytes(bottom_png.getvalue())
        preview = (
            f"--- 1. random (before top table) ---\n{sep_top}\n\n"
            f"--- 2. top table (top.png) ---\n\n"
            f"--- 3. promo ---\n{tickers}\n\n"
            f"--- 4. random (before bottom table) ---\n{sep_bottom}\n\n"
            f"--- 5. bottom table (bottom.png) ---"
        )
        (out_dir / "order.txt").write_text(preview, encoding="utf-8")
        print(f"DRY-RUN: saved to {out_dir}")
        print(preview)
        return 0

    token = os.environ.get("PAPER_WALLET_BOT_TOKEN", "").strip() or os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        print("ERROR: нет токена бота.")
        print("  Добавьте BOT_TOKEN в .env или PAPER_WALLET_BOT_TOKEN в scripts/paper_wallet.env")
        print("  Превью без Telegram: python3 scripts/paper_wallet_post.py --dry-run")
        return 1

    try:
        from telegram import Bot
    except ImportError:
        print("ERROR: установите зависимости: pip install python-telegram-bot")
        return 1

    bot = Bot(token)
    ok = await deliver_paper_wallet_daily(bot, force=force, log_fn=print)
    return 0 if ok else 1


def check_config() -> int:
    print("Paper Wallet — config check\n")
    print(f"  enabled: {paper_wallet_enabled()}")
    print(f"  channel: {PAPER_WALLET_CHANNEL}")
    print(f"  timezone: {PAPER_WALLET_TIMEZONE}")
    print(f"  post time: {PAPER_WALLET_POST_HOUR}:{PAPER_WALLET_POST_MINUTE:02d}")
    print(f"  bot link: {bot_link()}")
    print(f"  bot name: {bot_name()}")
    print(f"  min volume USD: {os.environ.get('PAPER_WALLET_MIN_VOLUME_USD', '100000')}")
    try:
        from PIL import Image  # noqa: F401

        print("  Pillow: OK")
    except ImportError:
        print("  Pillow: MISSING")
        return 1
    if not paper_wallet_enabled():
        print("\nSet PAPER_WALLET_ENABLED=true in .env on the server")
        return 1
    print("\nOK — scheduler runs inside main.py on JustRunMy")
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Paper Wallet channel post (CLI)",
        epilog=(
            "Примеры:\n"
            "  python3 scripts/paper_wallet_post.py --dry-run\n"
            "  python3 scripts/paper_wallet_post.py --force\n"
            "  python3 scripts/paper_wallet_post.py --check"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        return check_config()
    return asyncio.run(run(dry_run=args.dry_run, force=args.force))


if __name__ == "__main__":
    raise SystemExit(main())
