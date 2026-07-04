"""План X-постов @paper_wallet_co: ротация, напоминания admin, Google Calendar."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from social_growth import bot_link, bot_mention, x_post_disclaimer

logger = logging.getLogger(__name__)

X_VARIANTS: tuple[str, ...] = ("table", "whales", "intro")
CALENDAR_EVENT_PREFIX = "X @paper_wallet_co · "

_DEFAULT_TZ = "Europe/Moscow"


@dataclass(frozen=True)
class ScheduledXPost:
    post_date: date
    variant: str
    title: str
    body: str
    image_hint: str


def _tz() -> ZoneInfo:
    name = os.environ.get("SOCIAL_X_TIMEZONE", _DEFAULT_TZ).strip() or _DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(_DEFAULT_TZ)


def _interval_days() -> int:
    return max(2, int(os.environ.get("SOCIAL_X_INTERVAL_DAYS", "4")))


def _schedule_start() -> date:
    raw = os.environ.get("SOCIAL_X_SCHEDULE_START", "").strip()
    if raw:
        return date.fromisoformat(raw)
    return datetime.now(_tz()).date()


def _paper_wallet_tg() -> str:
    ch = os.environ.get("PAPER_WALLET_CHANNEL", "@Paper_wallet_co").strip()
    return ch if ch.startswith("@") else f"@{ch}"


def _x_handle() -> str:
    h = os.environ.get("SOCIAL_X_HANDLE", "paper_wallet_co").strip().lstrip("@")
    return f"@{h}"


def _format_post_date(when: date) -> str:
    return when.strftime("%d %b %Y")


def _image_hint(variant: str) -> str:
    if variant == "table":
        return f"Screenshot: daily CoinGecko table from {_paper_wallet_tg()} (Telegram)"
    if variant == "whales":
        return "Image: assets/card_record.png or card_etf_inflow.png"
    return "Image: assets/announcement_card.png (pin-style)"


def render_x_paper_wallet(*, variant: str = "table", when: date | None = None) -> str:
    """EN post for @paper_wallet_co — tables + alerts brand."""
    variant = variant if variant in X_VARIANTS else "table"
    post_day = when or datetime.now(_tz()).date()
    label = _format_post_date(post_day)
    link = bot_link()
    tg = _paper_wallet_tg()
    mention = bot_mention()

    tags = "#Bitcoin #BTC #MarketCap"
    if variant == "table":
        return (
            f"Top cryptocurrencies by market cap · {label} · CoinGecko\n\n"
            f"Daily tables on Telegram → {tg}\n\n"
            f"Treasury & whale alerts (Strategy, corporates, ETF flows):\n"
            f"{link}\n\n"
            f"{x_post_disclaimer()}\n\n"
            f"{tags}"
        )
    if variant == "whales":
        return (
            "Who holds the most BTC right now?\n\n"
            f"{mention} ranks Strategy, Tesla, MARA, Metaplanet, "
            "IBIT/FBTC/GBTC/ARKB — alerts on moves.\n"
            "Free: Strategy (~15m delay). Premium: instant + all cards.\n\n"
            f"→ {link}\n\n"
            f"Daily CoinGecko tables → {tg}\n\n"
            f"{x_post_disclaimer()}\n\n"
            "#Bitcoin #MicroStrategy #BTC"
        )
    return (
        "Daily crypto snapshot — top market caps, 24h change, global BTC context.\n"
        "Source: CoinGecko · also on our Telegram channel.\n\n"
        f"When treasuries move (Strategy, corporates, ETF flows):\n"
        f"free alerts + PNG cards → {link}\n\n"
        f"Tables: {tg}\n"
        f"Alerts: {mention}\n\n"
        f"{x_post_disclaimer()}\n\n"
        "#Bitcoin #BTC #Crypto"
    )


def _variant_on_date(post_date: date) -> str:
    idx = (post_date - _schedule_start()).days // _interval_days()
    return X_VARIANTS[idx % len(X_VARIANTS)]


def upcoming_x_posts(*, count: int = 6, from_date: date | None = None) -> list[ScheduledXPost]:
    """Следующие N слотов постинга (каждые SOCIAL_X_INTERVAL_DAYS)."""
    start = _schedule_start()
    interval = _interval_days()
    today = from_date or datetime.now(_tz()).date()
    posts: list[ScheduledXPost] = []

    # первый слот >= today
    if today <= start:
        d = start
    else:
        delta = (today - start).days
        n = (delta + interval - 1) // interval
        d = start + timedelta(days=n * interval)
        if d < today:
            d += timedelta(days=interval)

    while len(posts) < count:
        variant = _variant_on_date(d)
        body = render_x_paper_wallet(variant=variant, when=d)
        posts.append(
            ScheduledXPost(
                post_date=d,
                variant=variant,
                title=f"{CALENDAR_EVENT_PREFIX}{variant}",
                body=body,
                image_hint=_image_hint(variant),
            )
        )
        d += timedelta(days=interval)
    return posts


def format_schedule_text(*, count: int = 6) -> str:
    lines = [
        f"X {_x_handle()} · every {_interval_days()} days · TZ {_tz().key}",
        f"Start: {_schedule_start().isoformat()}",
        "",
    ]
    for i, p in enumerate(upcoming_x_posts(count=count), 1):
        lines.append(f"{i}. {p.post_date.isoformat()} — {p.variant}")
        lines.append(f"   {p.image_hint}")
    lines.extend(
        [
            "",
            "Copy today's post: /share x paper_wallet",
            "Force variant: /share x paper_wallet whales",
            "Google Calendar (on PC): python3 scripts/social_calendar_sync.py",
        ]
    )
    return "\n".join(lines)


def _state_path() -> Path:
    return Path(os.environ.get("SOCIAL_X_STATE_FILE", "social_x_state.json"))


def _load_state() -> dict:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    path = _state_path()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _reminder_enabled() -> bool:
    return os.environ.get("SOCIAL_X_REMINDER_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def reminder_enabled() -> bool:
    return _reminder_enabled()


async def social_x_reminder_scheduler(bot, *, log_fn=None) -> None:
    """DM admin в день поста и за день до (Europe/Moscow по умолчанию)."""
    if not _reminder_enabled():
        return
    tz = _tz()
    hour = int(os.environ.get("SOCIAL_X_REMINDER_HOUR", "10"))
    minute = int(os.environ.get("SOCIAL_X_REMINDER_MINUTE", "0"))
    chat_id = os.environ.get("X_CHAT_ID", "").strip()
    if not chat_id:
        logger.warning("SOCIAL_X_REMINDER: no X_CHAT_ID")
        return

    while True:
        now = datetime.now(tz)
        try:
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        except ValueError:
            target = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep(max(1.0, (target - now).total_seconds()))

        now = datetime.now(tz)
        today = now.date()
        tomorrow = today + timedelta(days=1)
        state = _load_state()
        sent_on = state.get("reminder_sent_on", {})

        for offset, label in ((0, "today"), (1, "tomorrow")):
            day = today + timedelta(days=offset)
            key = f"{day.isoformat()}:{label}"
            if sent_on.get(key):
                continue
            post = next((p for p in upcoming_x_posts(count=12) if p.post_date == day), None)
            if not post:
                continue
            if label == "tomorrow":
                msg = (
                    f"📅 X post tomorrow ({post.post_date.isoformat()}) · {post.variant}\n\n"
                    f"{post.image_hint}\n\n"
                    f"/share x paper_wallet {post.variant}\n\n"
                    f"---\n{post.body}"
                )
            else:
                msg = (
                    f"📣 X post today ({post.post_date.isoformat()}) · {post.variant}\n\n"
                    f"{post.image_hint}\n\n"
                    f"/share x paper_wallet {post.variant}\n\n"
                    f"---\n{post.body}"
                )
            try:
                await bot.send_message(chat_id=int(chat_id), text=msg)
                sent_on[key] = now.isoformat()
                state["reminder_sent_on"] = sent_on
                _save_state(state)
                if log_fn:
                    log_fn(f"SOCIAL_X_REMINDER: {label} {post.post_date}")
            except Exception as exc:
                logger.warning("SOCIAL_X_REMINDER failed: %s", exc)
