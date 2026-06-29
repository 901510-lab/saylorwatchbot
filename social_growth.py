"""Рост через соцсети (Day 27): ссылки X/Reddit/Discord и шаблоны постов."""

from __future__ import annotations

import os
from dataclasses import dataclass

BOT_PUBLIC_URL = os.environ.get("BOT_PUBLIC_URL", "https://t.me/Saylor_w_bot").strip().rstrip("/")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "Saylor_w_bot").strip().lstrip("@")

_SOCIAL_ENV: tuple[tuple[str, str, str], ...] = (
    ("x", "SOCIAL_X_URL", "social_btn_x"),
    ("reddit", "SOCIAL_REDDIT_URL", "social_btn_reddit"),
    ("discord", "SOCIAL_DISCORD_URL", "social_btn_discord"),
)

_SOCIAL_START_PARAMS: dict[str, str] = {
    "social_x": "x",
    "social_reddit": "reddit",
    "social_discord": "discord",
    "social": "",
}


@dataclass(frozen=True)
class SocialLink:
    id: str
    url: str
    btn_key: str


def _env_url(key: str) -> str | None:
    value = os.environ.get(key, "").strip()
    return value if value.startswith(("http://", "https://")) else None


def configured_social_links() -> list[SocialLink]:
    links: list[SocialLink] = []
    for link_id, env_key, btn_key in _SOCIAL_ENV:
        url = _env_url(env_key)
        if url:
            links.append(SocialLink(link_id, url, btn_key))
    return links


def social_url_for_start_param(param: str) -> str | None:
    """Deep link ?start=social_discord → URL кнопки или None (показать /social целиком)."""
    link_id = _SOCIAL_START_PARAMS.get(param.strip().lower())
    if link_id is None:
        return None
    if not link_id:
        return ""
    for item in configured_social_links():
        if item.id == link_id:
            return item.url
    return None


def social_links_configured() -> bool:
    return bool(configured_social_links())


def bot_link() -> str:
    if BOT_PUBLIC_URL.startswith("http"):
        return BOT_PUBLIC_URL
    return f"https://t.me/{BOT_USERNAME}"


def bot_mention() -> str:
    return f"@{BOT_USERNAME}"


# --- Шаблоны постов (EN — для X/Reddit; Reddit title + body) ---

POST_KINDS = ("announce", "weekly", "whales", "reddit_comment")


def render_x_post(kind: str, lang: str = "en") -> str:
    link = bot_link()
    mention = bot_mention()
    if kind == "announce":
        return (
            "🟠 SaylorWatch — real-time BTC whale alerts\n\n"
            "• Strategy (Saylor) buy/sell alerts\n"
            "• Top corporate BTC holders + ETF flows\n"
            "• Auto Bloomberg-style cards — easy to repost\n\n"
            f"Free in Telegram → {link}\n\n"
            "#Bitcoin #BTC #MicroStrategy #Saylor"
        )
    if kind == "weekly":
        return (
            "📊 New: Weekly BTC Whale Digest (Premium)\n\n"
            "Every Sunday — snapshot of top holders, "
            "buy/sell activity & ETF flows in one PNG card.\n\n"
            f"Try the bot → {link}\n"
            f"Premium via {mention}\n\n"
            "#Bitcoin #BTC #WhaleAlert"
        )
    if kind == "whales":
        return (
            "🐋 Who holds the most BTC right now?\n\n"
            "SaylorWatch tracks Strategy, Tesla, MARA, Metaplanet, "
            "BlackRock IBIT & more — with instant alerts on moves.\n\n"
            f"→ {link}\n\n"
            "#Bitcoin #BTC #Treasury"
        )
    if kind == "reddit_comment":
        return (
            f"For live alerts with auto-generated cards, there's a free Telegram bot: {link} "
            f"({mention}). Tracks Strategy treasury moves, top corporate holders and ETF flows. "
            "Not financial advice — DYOR."
        )
    raise ValueError(f"Unknown post kind: {kind}")


def render_reddit_post(kind: str, lang: str = "en") -> tuple[str, str]:
    link = bot_link()
    if kind == "announce":
        title = (
            "[Tool] Telegram bot: instant alerts when Strategy (Saylor) buys or sells BTC "
            "+ whale/ETF tracking with auto cards"
        )
        body = (
            "I built **SaylorWatch** to monitor Bitcoin treasury moves in real time.\n\n"
            "**What it does:**\n"
            "- Alerts when Strategy (MicroStrategy) buys or sells BTC\n"
            "- Tracks other public BTC treasuries (Tesla, MARA, Metaplanet, etc.)\n"
            "- ETF daily net flows (IBIT, FBTC, GBTC, ARK)\n"
            "- Auto-generated PNG cards (handy for sharing)\n"
            "- Free tier + optional Premium (instant whale/ETF alerts, weekly digest)\n\n"
            f"**Bot:** {link}\n\n"
            "---\n"
            "*Not financial advice. I am not affiliated with Strategy or Michael Saylor. "
            "Always DYOR.*"
        )
        return title, body
    if kind == "weekly":
        title = "[OC] Weekly BTC whale snapshot — top holders, buys/sells & ETF flows (Telegram bot)"
        body = (
            "Premium users get a **Weekly Digest** every Sunday (12:00 NY): "
            "one PNG card with top BTC holders, net buy/sell by company, and ETF flow summary.\n\n"
            "Free tier still gets Strategy buy/sell alerts (with a short delay).\n\n"
            f"Bot link: {link}\n\n"
            "*Not financial advice.*"
        )
        return title, body
    if kind == "whales":
        title = "Top BTC corporate treasuries & ETF holdings — who are the biggest holders?"
        body = (
            "Quick pointer: if you want **live alerts** when these balances change "
            "(not just static rankings), SaylorWatchBot sends Telegram notifications "
            "with auto-generated cards.\n\n"
            f"{link}\n\n"
            "Covers Strategy, major public companies, and spot BTC ETF flows.\n\n"
            "*Not financial advice — sharing a tool I maintain.*"
        )
        return title, body
    if kind == "reddit_comment":
        body = render_x_post("reddit_comment")
        return "", body
    raise ValueError(f"Unknown post kind: {kind}")


def format_share_message(platform: str, kind: str) -> str:
    """Текст для admin /share — готово к копированию."""
    platform = platform.lower().strip()
    kind = kind.lower().strip()
    if platform in {"x", "twitter"}:
        return render_x_post(kind)
    if platform == "reddit":
        title, body = render_reddit_post(kind)
        if title:
            return f"TITLE:\n{title}\n\nBODY:\n{body}"
        return body
    raise ValueError(f"Unknown platform: {platform}")


def list_share_options() -> str:
    kinds = ", ".join(POST_KINDS)
    return (
        "Platforms: x, reddit\n"
        f"Kinds: {kinds}\n\n"
        "Examples:\n"
        "/share x announce\n"
        "/share reddit weekly\n"
        "/share reddit whales"
    )
