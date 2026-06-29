#!/usr/bin/env python3
"""Локальный AI-помощник для SaylorWatch@outlook.com.

Outlook IMAP + Graph Mail.Send (или SMTP/Gmail) + Ollama + Telegram.

Режимы (EMAIL_AGENT_MODE):
  auto    — FAQ → автоответ (Graph); сложное → черновик + Telegram вам
  draft   — черновик в Drafts (Evolution)
  suggest — только Telegram + файл
  send    — авто-отправка всего (осторожно)

Примеры:
  python3 scripts/email_support_agent.py              # новые письма
  python3 scripts/email_support_agent.py --startup   # после включения ПК (catch-up)
  python3 scripts/email_support_agent.py --weekly     # саммари за 7 дней
  python3 scripts/email_support_agent.py --oauth-login # OAuth2 IMAP (чтение)
  python3 scripts/email_support_agent.py --oauth-graph # OAuth2 Graph (отправка)
  python3 scripts/email_support_agent.py --test-send you@example.com
  python3 scripts/email_support_agent.py --dry-run    # без IMAP, тест Ollama
"""

from __future__ import annotations

import argparse
import email
import hashlib
import html
import imaplib
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import UTC, datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dataclasses import dataclass
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path

from outlook_oauth import (
    DEFAULT_CLIENT_ID,
    DEFAULT_REDIRECT_URI,
    DEFAULT_SCOPES,
    get_access_token,
    interactive_login,
    load_tokens,
    token_file_path,
    xoauth2_string,
)
from graph_mail_oauth import (
    DEFAULT_GRAPH_CLIENT_ID,
    DEFAULT_GRAPH_SCOPES,
    device_code_login,
    fetch_inbox_messages,
    get_graph_access_token,
    send_mail as graph_send_mail,
)
from bot_knowledge import (
    ADMIN_ONLY_COMMANDS,
    CANONICAL_FAQ_SHOTS,
    FAQ_PLAYBOOKS,
    FAQ_TOPIC_HINTS,
    FORBIDDEN_COMMAND_PHRASES,
    PLAYBOOK_NO_PS,
    VALID_BOT_COMMANDS,
    bot_knowledge_text,
    detect_command_topic,
    detect_natural_command_topic,
    extract_question_command,
    is_command_question,
    multi_command_playbook_reply,
    playbook_text_for_topic,
    resolve_faq_topic,
    detect_relaxed_faq_topic,
    is_bot_overview_question,
    detect_subscribe_intent,
    command_cheatsheet_for_llm,
    command_cheatsheet_text,
    is_etf_coverage_question,
    is_companies_coverage_question,
    is_privacy_question,
    is_exchange_bot_question,
    is_free_tier_question,
    is_retail_buy_bitcoin_question,
    is_bot_created_question,
    is_start_command_question,
    is_weekly_report_question,
    multi_faq_playbook_reply,
    topic_from_faq_hints,
)
from faq_normalize import build_faq_blob, normalize_faq_blob

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from json_store import atomic_write_json, file_lock
ENV_FILE = Path(__file__).with_name("email_support.env")
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

SYSTEM_PROMPT = """You are the support assistant for SaylorWatch — Telegram bot @Saylor_w_bot.

Rules:
- Reply in the SAME language as the customer's email (Russian, English, French, etc.).
- ANSWER THE ACTUAL QUESTION FIRST. Use ONLY facts from BOT KNOWLEDGE below.
- Be concise, professional. Max ~120 words for FAQ.
- Do NOT push Premium or /subscribe unless the customer asked about subscription/plans.
- NOT financial advice. Not affiliated with Strategy or Michael Saylor.
- Subscription is activated IN @Saylor_w_bot — never «email us to subscribe».
- Email SaylorWatch@outlook.com is for disputes, legal, bugs — not for activating Premium.
- Write ONLY the email body. Numbered steps for how-to questions.
- If NOT covered by BOT KNOWLEDGE — reply EXACTLY: UNCERTAIN: <short reason in English>"""

MODEST_FOOTER: dict[str, str] = {
    "en": "P.S. Premium adds instant whale-deal alerts — /plans in the bot.",
    "ru": "P.S. Premium — мгновенные алерты о сделках; тарифы: /plans в боте.",
    "fr": "P.S. Premium — alertes instantanées ; détails : /plans dans le bot.",
}

HEDGE_PHRASES: tuple[str, ...] = (
    "возможно",
    "вероятно",
    "не уверен",
    "not sure",
    "i think",
    "maybe",
    "perhaps",
    "might be",
    "could be",
    "je pense",
    "peut-être",
)

# Короткие ответы — не слать авто-ответ повторно
NO_REPLY_PHRASES = frozenset({
    "ok", "okay", "thanks", "thank you", "thx", "received", "noted", "yes", "no",
    "спасибо", "ок", "понятно", "принято", "хорошо",
})

OUR_REPLY_MARKERS = (
    "We have received your message and will reply within",
    "Мы получили ваше письмо",
    "Premium is activated in our Telegram bot",
    "Premium активируется в Telegram-боте",
    "To activate Premium:",
    "Активация Premium:",
    "Activate Premium (private chat only)",
    "Активация Premium (только личный чат)",
    "🎁 PROMO: 1 year FREE",
    "Pay 350 Stars",
    "Pay 350 Stars · 30 days",
    "Full command list: /help",
    "Полный список команд: /help",
    "SaylorWatch (@Saylor_w_bot)",
    "SaylorWatch Support",
)

OUR_REPLY_ECHO_PHRASES = (
    "activate premium (private chat only)",
    "активация premium (только личный чат)",
    "1. telegram → @saylor_w_bot",
    "2. /subscribe",
    "3. promo:",
    "3. акция:",
    "4. or pay:",
    "4. или оплата:",
    "5. /mysub",
    "saylorwatch support ·",
    "полный список команд: /help",
)

ADMIN_NOTIFY_HINTS = (
    "refund",
    "chargeback",
    "dispute",
    "legal",
    "lawyer",
    "attorney",
    "court",
    "lawsuit",
    "sue",
    "gdpr",
    "delete my data",
    "privacy",
    "personal data",
    "partnership",
    "b2b",
    "api access",
    "scam",
    "fraud",
    "threat",
    "возврат",
    "жалоб",
    "прокурат",
    "суд",
    "юрист",
    "удалите данные",
    "персональн",
    "партнёр",
    "партнер",
    "коммерческ",
)

REPLY_PROMPT = """You write support email replies for SaylorWatch (@Saylor_w_bot).

REASONING (do this mentally before writing):
1) Classify intent: single /command meaning · how-to workflow · bot overview · billing · other.
2) Map intent to 1–3 commands from COMMAND CHEATSHEET only — never invent commands.
3) How-to questions (Premium, alerts, whales…) → numbered steps starting with Telegram → @Saylor_w_bot.
4) «What does /X mean» → explain THAT command only; /info is admin-only → point to /status and /help.

OUTPUT FORMAT (follow exactly):
1) One direct sentence answering YES/NO or the core question.
2) Optional second sentence: brief context (what the bot is / is not).
3) Blank line.
4) Numbered steps: «1. Telegram → … @Saylor_w_bot» then commands.
5) NO subject line. NO long goodbye. NO signature (added automatically).

STYLE: short, factual — like whale/treasury bot support (Maestro Whale Bot, Cryptocurrency Alerting):
direct answer first, numbered Telegram steps, read-only / no keys, NFA disclaimer when relevant.

GOOD PATTERN (RU example):
«Да — в боте 4 spot ETF: IBIT, FBTC, GBTC, ARKB. Алерты по потокам — Premium, автоматически.

1. Telegram → @Saylor_w_bot · /start
2. Тарифы: /plans · рейтинг: /whales»

RULES:
- Same language as the customer.
- Only use commands from COMMAND CHEATSHEET. Never invent commands.
- If the question is outside FAQ facts — output ONLY: UNCERTAIN: <reason> (do not guess).
- Do NOT mention Premium or /subscribe unless the customer asked about subscription/plans.
- Subscription is in the Telegram bot only — never «email us to subscribe».
- Max ~120 words."""

BAD_REPLY_EXAMPLE = """BAD (never write like this):
«…2. /all alerts…» or «/whales для курса» or «/companies» or «сначала Premium /subscribe».
Why bad: /all alerts does NOT exist (alerts are automatic after /start); wrong commands; pushes Premium unprompted."""

OLLAMA_UNCERTAIN_SHOT: tuple[str, str] = (
    "Subject: API\n\nDo you offer an enterprise REST API with API keys?\n\n---\nWrite the reply body.",
    "UNCERTAIN: no public enterprise API in product FAQ",
)

OLLAMA_REPLY_OPTIONS = {"temperature": 0.12, "num_predict": 320, "top_p": 0.9}


def ollama_chat_timeout_seconds() -> int:
    return max(15, int(cfg("OLLAMA_CHAT_TIMEOUT", "90")))

SIGNATURE = "\n\n--\nSaylorWatch Support · SaylorWatch@outlook.com"

EMAIL_DISCLAIMER: dict[str, str] = {
    "ru": (
        "⚠️ Не является инвестиционным советом. SaylorWatch — информационный бот; "
        "не аффилирован с Strategy (MSTR) или Michael Saylor. Подробнее: /disclaimer в @Saylor_w_bot."
    ),
    "en": (
        "⚠️ Not investment advice. SaylorWatch is informational only; "
        "not affiliated with Strategy (MSTR) or Michael Saylor. See /disclaimer in @Saylor_w_bot."
    ),
    "fr": (
        "⚠️ Pas un conseil en investissement. SaylorWatch est informatif uniquement; "
        "non affilié à Strategy (MSTR) ou Michael Saylor. Voir /disclaimer dans @Saylor_w_bot."
    ),
}

_DISCLAIMER_MARKERS = (
    "not investment advice",
    "не является инвестиционным",
    "pas un conseil en investissement",
    "не инвестиционный совет",
)

# Подписи почтовых клиентов — не считать содержимым письма
EMAIL_BOILERPLATE_MARKERS: tuple[str, ...] = (
    "sent with proton mail",
    "sent from my iphone",
    "sent from my ipad",
    "sent from outlook",
    "sent from mail for windows",
    "get outlook for",
    "sent from yahoo mail",
    "sent from gmail",
    "envoyé depuis",
    "envoyé de mon",
)

ACK_BODY_RU = (
    "Спасибо за письмо.\n\n"
    "Мы получили его и ответим в течение 1–2 рабочих дней."
)

ACK_BODY_EN = (
    "Thank you for your message.\n\n"
    "We received it and will reply within 1–2 business days."
)


def load_env() -> dict[str, str]:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())
    return {k: os.environ.get(k, "") for k in os.environ}


def cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def load_state(path: Path) -> dict:
    if not path.exists():
        return _fresh_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        bak = path.with_suffix(path.suffix + ".bak")
        if bak.exists():
            try:
                print(f"WARN: state corrupt, loading backup: {exc}")
                state = json.loads(bak.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                print(f"ERROR: state corrupt and backup failed: {exc}")
                raise
        else:
            print(f"ERROR: state corrupt, no backup: {exc}")
            raise
    except OSError as exc:
        print(f"ERROR: state read failed: {exc}")
        return _fresh_state()
    if "week_stats" not in state:
        state["week_stats"] = _empty_week_stats()
    state.setdefault("replied_fingerprints", [])
    state.setdefault("replied_message_ids", [])
    state.setdefault("incomplete_replies", {})
    state.setdefault("last_reply_at", {})
    state.setdefault("recent_reply_fingerprints", {})
    _migrate_replied_message_ids(state)
    return state


def _fresh_state() -> dict:
    return {
        "processed_uids": [],
        "weekly_last": None,
        "week_stats": _empty_week_stats(),
        "replied_fingerprints": [],
        "replied_message_ids": [],
        "incomplete_replies": {},
        "last_reply_at": {},
    }


def _empty_week_stats() -> dict:
    return {
        "period_start": datetime.now(UTC).isoformat(),
        "received": 0,
        "processed": 0,
        "auto_replied": 0,
        "ack_only": 0,
        "escalated": 0,
        "skipped": 0,
        "send_failed": 0,
        "items": [],
    }


def _week_stats(state: dict) -> dict:
    ws = state.setdefault("week_stats", _empty_week_stats())
    for key in ("received", "processed", "auto_replied", "ack_only", "escalated", "skipped", "send_failed"):
        ws.setdefault(key, 0)
    ws.setdefault("items", [])
    ws.setdefault("period_start", datetime.now(UTC).isoformat())
    return ws


def record_mail_stat(
    state: dict,
    *,
    from_email: str,
    subject: str,
    action: str,
    reason: str = "",
) -> None:
    """action: auto_replied | ack_only | escalated | skipped | send_failed"""
    ws = _week_stats(state)
    if action == "skipped":
        ws["skipped"] += 1
        return
    ws["received"] += 1
    ws["processed"] += 1
    if action in ("auto_replied", "ack_only", "escalated", "send_failed"):
        ws[action] += 1
    items = ws.setdefault("items", [])
    items.append(
        {
            "at": datetime.now(UTC).isoformat(),
            "from": from_email,
            "subject": subject[:120],
            "action": action,
            "reason": reason[:80],
        }
    )
    ws["items"] = items[-50:]


def admin_notify_required(*, subject: str, body: str, reason: str) -> bool:
    """Telegram админу: только refund/legal/партнёрство — не FAQ."""
    return reason == "keyword-escalate"


def save_state(path: Path, state: dict, *, already_locked: bool = False) -> None:
    lock_path = path.with_suffix(path.suffix + ".lock")
    if already_locked:
        atomic_write_json(path, state, indent=2)
        return
    with file_lock(lock_path):
        atomic_write_json(path, state, indent=2)


def ollama_chat(
    user_message: str,
    *,
    dry_run: bool = False,
    system: str | None = None,
    few_shot: list[tuple[str, str]] | None = None,
    options: dict | None = None,
) -> str:
    if dry_run:
        return (
            "[DRY RUN] Premium: Telegram → @Saylor_w_bot → /subscribe → кнопка акции или Stars → /mysub"
        )
    url = f"{cfg('OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')}/api/chat"
    messages: list[dict[str, str]] = [{"role": "system", "content": system or SYSTEM_PROMPT}]
    for user_turn, assistant_turn in few_shot or []:
        messages.append({"role": "user", "content": user_turn})
        messages.append({"role": "assistant", "content": assistant_turn})
    messages.append({"role": "user", "content": user_message})
    opts = dict(OLLAMA_REPLY_OPTIONS)
    if options:
        opts.update(options)
    payload = {
        "model": cfg("OLLAMA_MODEL", "qwen2.5:3b"),
        "messages": messages,
        "stream": False,
        "options": opts,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = ollama_chat_timeout_seconds()

    def _call() -> dict:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            data = pool.submit(_call).result(timeout=timeout + 5)
    except FuturesTimeoutError as exc:
        raise RuntimeError(
            f"Ollama timeout ({timeout}s) — playbook не сработал, будет ACK клиенту"
        ) from exc
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            model = cfg("OLLAMA_MODEL", "qwen2.5:3b")
            raise RuntimeError(
                f"Ollama: модель «{model}» не найдена (404). "
                f"Выполните: ollama pull {model}  или измените OLLAMA_MODEL в email_support.env"
            ) from exc
        raise RuntimeError(f"Ollama HTTP {exc.code}: {exc.reason}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"Ollama недоступен ({url}): {exc}") from exc
    message = data.get("message") or {}
    text = (message.get("content") or "").strip()
    if not text:
        raise RuntimeError("Ollama вернул пустой ответ")
    return text


def _looks_russian(text: str) -> bool:
    return sum(1 for c in text if "\u0400" <= c <= "\u04ff") > len(text) * 0.08


def _reply_lang(subject: str, body: str) -> str:
    text = f"{subject} {body}"
    if _looks_russian(text):
        return "ru"
    low = text.lower()
    fr_markers = (
        "bonjour", "merci", "comment", "aide", "abonnement", "cordialement",
        "n'hésitez", "ravi", "pourriez", "hebdomadaire", "baleine", "alerte",
        "résumé", "commande", "utiliser", "disposition",
    )
    if any(m in low for m in fr_markers):
        return "fr"
    if sum(1 for c in text if c in "àâäéèêëïîôùûüçœ") >= 2:
        return "fr"
    return "en"


def email_disclaimer_for_text(text: str) -> str:
    lang = _reply_lang("", text)
    return EMAIL_DISCLAIMER.get(lang) or EMAIL_DISCLAIMER["en"]


def reply_signature(body: str) -> str:
    body = body.rstrip()
    low = body.lower()
    if not any(m in low for m in _DISCLAIMER_MARKERS):
        body = f"{body}\n\n{email_disclaimer_for_text(body)}"
    return body + SIGNATURE


def normalize_email_text(text: str) -> str:
    """HTML-сущности (&#1084; → м), остатки тегов."""
    import re

    text = html.unescape(text.replace("\r\n", "\n"))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text)


def strip_forward_metadata(text: str) -> str:
    """Убирает шапку пересылки (Proton/Outlook), оставляет текст вопроса."""
    import re

    meta_bits = (
        "forwarded message",
        "переслан",
        "original message",
        "-----",
        "от:",
        "from:",
        "дата:",
        "date:",
        "тема:",
        "subject:",
        "кому:",
        "to:",
    )
    kept: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        low = stripped.lower()
        if not stripped:
            continue
        if any(m in low for m in meta_bits):
            continue
        if re.search(r"saylorwatch@", low) and len(stripped) < 100:
            continue
        kept.append(stripped)
    return "\n".join(kept).strip()


def strip_quoted_reply(text: str) -> str:
    """Убирает цитаты переписки — отвечаем только на новый текст."""
    import re

    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        low = stripped.lower()
        if re.match(r"^on .+ wrote:$", low):
            break
        if "-----original message-----" in low:
            break
        if stripped.startswith(">"):
            continue
        if stripped == "--" and out:
            break
        out.append(line)
    return "\n".join(out).strip()


def strip_email_boilerplate(text: str) -> str:
    """Убирает подписи Proton/Outlook/iPhone — часто единственное «тело» после цитаты."""
    lines = text.replace("\r\n", "\n").split("\n")
    kept: list[str] = []
    for line in lines:
        low = line.strip().lower()
        if any(m in low for m in EMAIL_BOILERPLATE_MARKERS):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def text_from_quoted_lines(text: str) -> str:
    """Текст в строках «> …» — когда клиент ответил без нового текста."""
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        s = line.strip()
        if s.startswith(">"):
            lines.append(s.lstrip(">").strip())
    return "\n".join(lines).strip()


def text_after_original_marker(text: str) -> str:
    low = text.lower()
    for marker in ("оригинальное сообщение", "original message"):
        idx = low.find(marker)
        if idx >= 0:
            return text[idx + len(marker) :].strip()
    return ""


def customer_message_text(raw_body: str) -> str:
    raw = normalize_email_text(raw_body)
    core = strip_email_boilerplate(strip_forward_metadata(strip_quoted_reply(raw))).strip()
    if core and not is_trivial_reply(core) and len(core.strip()) >= 12:
        return core
    for alt_src in (text_from_quoted_lines(raw), text_after_original_marker(raw)):
        alt = strip_email_boilerplate(strip_forward_metadata(alt_src)).strip()
        if alt and not is_trivial_reply(alt):
            return alt
    if core:
        return core
    return strip_email_boilerplate(strip_forward_metadata(raw)).strip()


_PLACEHOLDER_SUBJECTS = frozenset({
    "(no subject)",
    "(без темы)",
    "no subject",
    "без темы",
    "(без теми)",
})


def normalize_subject(subject: str) -> str:
    """Пустая тема / (No Subject) — не считаем содержимым."""
    s = html.unescape((subject or "").strip())
    if not s:
        return ""
    if s.lower() in _PLACEHOLDER_SUBJECTS:
        return ""
    return s


def effective_customer_text(*, subject: str, raw_body: str) -> str:
    """Текст вопроса: тело письма; если пусто — осмысленная тема (мобильные клиенты)."""
    core = customer_message_text(raw_body)
    subj_text = normalize_subject(subject)
    if core and not is_trivial_reply(core):
        return core
    if subj_text and not is_trivial_reply(subj_text):
        return subj_text
    if core:
        return core
    return subj_text


def has_customer_inquiry(*, subject: str, raw_body: str) -> bool:
    if mail_has_faq_intent(subject=subject, body=raw_body):
        return True
    eff = effective_customer_text(subject=subject, raw_body=raw_body)
    return bool(eff.strip()) and not is_trivial_reply(eff)


def empty_inquiry_prompt_reply(*, subject: str, raw_body: str) -> str:
    """Клиент написал без текста вопроса — просим уточнить (тема может быть пустой)."""
    hint = effective_customer_text(subject=subject, raw_body=raw_body) or normalize_email_text(raw_body)
    lang = _reply_lang(subject, hint)
    if lang == "ru":
        text = (
            "Здравствуйте!\n\n"
            "Мы получили ваше письмо, но не видим текста вопроса.\n\n"
            "Пожалуйста, напишите вопрос в теле письма — тема может быть пустой "
            "(это нормально).\n\n"
            "Например: как подключить Premium, что делает /subscribe, "
            "почему не отвечает /info в боте."
        )
    elif lang == "fr":
        text = (
            "Bonjour,\n\n"
            "Nous avons bien reçu votre message, mais le texte de la question est vide.\n\n"
            "Écrivez votre question dans le corps du mail — l'objet peut rester vide.\n\n"
            "Ex. : Premium, /subscribe, /info dans le bot Telegram."
        )
    else:
        text = (
            "Hello,\n\n"
            "We received your email, but the question text appears empty.\n\n"
            "Please write your question in the message body — an empty subject is fine.\n\n"
            "E.g. Premium, /subscribe, or /info in the Telegram bot."
        )
    return reply_signature(text)


def reply_subject_line(original: str) -> str:
    if normalize_subject(original):
        subj = original.strip()
        return subj if subj.lower().startswith("re:") else f"Re: {subj}"
    return "Re: SaylorWatch support"


def faq_search_blob(*, subject: str, raw_body: str) -> str:
    """Весь текст для поиска FAQ (пересылки, HTML-сущности, кириллица)."""
    norm_subj = normalize_subject(subject)
    eff = effective_customer_text(subject=subject, raw_body=raw_body)
    raw = f"{norm_subj}\n{normalize_email_text(raw_body)}\n{eff}"
    return build_faq_blob(subject=norm_subj or subject, body=raw)


def mail_has_faq_intent(*, subject: str, body: str) -> bool:
    blob = faq_search_blob(subject=subject, raw_body=body)
    core = effective_customer_text(subject=subject, raw_body=body)
    norm_subj = normalize_subject(subject)
    if detect_faq_topic(subject=norm_subj, body=core):
        return True
    if detect_faq_topic(subject=norm_subj, body=blob):
        return True
    if resolve_faq_topic(subject=norm_subj, body=core):
        return True
    if resolve_faq_topic(subject=norm_subj, body=blob):
        return True
    if detect_natural_command_topic(blob.lower()):
        return True
    if extract_question_command(blob.lower()):
        return True
    return False


def is_trivial_reply(body: str) -> bool:
    norm = " ".join(body.lower().split())
    if len(norm) < 3:
        return True
    if norm in NO_REPLY_PHRASES:
        return True
    if len(norm) < 25 and norm.rstrip(".!") in NO_REPLY_PHRASES:
        return True
    return False


def is_echo_of_our_reply(body: str, *, subject: str = "") -> bool:
    """Письмо — пересылка/цитата нашего авто-ответа (повторно не отвечаем)."""
    raw_low = body.lower()
    echo_score = sum(1 for p in OUR_REPLY_ECHO_PHRASES if p in raw_low)
    marker_score = sum(1 for m in OUR_REPLY_MARKERS if m.lower() in raw_low)
    cleaned = effective_customer_text(subject=subject, raw_body=body)
    cleaned_len = len(cleaned.strip())

    if echo_score >= 3 or (echo_score >= 2 and cleaned_len < 60):
        return True
    if marker_score >= 2 and cleaned_len < 80:
        return True
    if marker_score >= 3:
        return True

    if mail_has_faq_intent(subject=subject, body=body) and cleaned_len >= 20:
        return False
    if cleaned_len < 20:
        return marker_score >= 1 or echo_score >= 1
    hits = marker_score
    return hits >= 2 or (hits >= 1 and cleaned_len < 120)


def _word_in_blob(word: str, blob: str) -> bool:
    return bool(re.search(rf"\b{re.escape(word)}\b", blob, flags=re.I))


def normalize_message_id(raw: str) -> str:
    return raw.strip().strip("<>").lower()


def message_uid_key(message_id: str) -> str:
    mid = normalize_message_id(message_id)
    if not mid:
        return ""
    return f"mid:{hashlib.sha256(mid.encode()).hexdigest()[:32]}"


def _replied_ids_set(state: dict) -> set[str]:
    ids = {str(k) for k in (state.get("replied_message_ids") or []) if k}
    for k in state.get("processed_uids") or []:
        ks = str(k)
        if ks.startswith("mid:"):
            ids.add(ks)
    return ids


def _migrate_replied_message_ids(state: dict) -> None:
    """Перенос mid: из processed_uids в отдельный список (не обрезается вместе с uid)."""
    replied = list(state.get("replied_message_ids") or [])
    known = set(replied)
    for k in state.get("processed_uids") or []:
        ks = str(k)
        if ks.startswith("mid:") and ks not in known:
            replied.append(ks)
            known.add(ks)
    state["replied_message_ids"] = replied[-500:]


def record_replied_message_id(state: dict, item: dict) -> None:
    mid_key = message_uid_key(item.get("message_id") or "")
    if not mid_key:
        return
    ids = state.setdefault("replied_message_ids", [])
    if mid_key not in ids:
        ids.append(mid_key)
    state["replied_message_ids"] = ids[-500:]
    clear_incomplete_reply(state, item)


def incomplete_reply_key(item: dict) -> str:
    mid_key = message_uid_key(item.get("message_id") or "")
    return mid_key or str(item["uid"])


def is_incomplete_reply(state: dict, item: dict) -> bool:
    return incomplete_reply_key(item) in (state.get("incomplete_replies") or {})


def record_incomplete_reply(state: dict, item: dict, *, reason: str) -> None:
    key = incomplete_reply_key(item)
    state.setdefault("incomplete_replies", {})[key] = {
        "uid": item["uid"],
        "from_email": item.get("from_email", ""),
        "subject": (item.get("subject") or "")[:120],
        "reason": reason[:80],
        "at": datetime.now(UTC).isoformat(),
    }


def clear_incomplete_reply(state: dict, item: dict) -> None:
    inc = state.get("incomplete_replies") or {}
    key = incomplete_reply_key(item)
    if key in inc:
        del inc[key]
        state["incomplete_replies"] = inc


def repair_incomplete_from_stats(state: dict) -> int:
    """Перенос ack/ollama-error из week_stats в очередь дозаполнения."""
    added = 0
    items = (state.get("week_stats") or {}).get("items") or []
    for it in items:
        action = it.get("action") or ""
        reason = it.get("reason") or ""
        if action not in ("escalated", "ack_only") or reason not in (
            "ollama-error",
            "uncertain",
            "ollama disabled",
            "faq playbook miss",
        ):
            continue
        subj = (it.get("subject") or "").strip()
        frm = (it.get("from") or "").strip().lower()
        if not subj or not frm:
            continue
        later_ok = any(
            j.get("subject") == subj
            and j.get("from") == frm
            and j.get("action") == "auto_replied"
            and (j.get("at") or "") >= (it.get("at") or "")
            for j in items
        )
        if later_ok:
            continue
        key = f"stat:{frm}:{subj.lower()[:80]}"
        inc = state.setdefault("incomplete_replies", {})
        if key not in inc:
            inc[key] = {
                "uid": "",
                "from_email": frm,
                "subject": subj,
                "reason": reason,
                "at": it.get("at") or datetime.now(UTC).isoformat(),
                "stat_key": key,
            }
            added += 1
    return added


def message_processed(state: dict, item: dict, *, reprocess: bool = False) -> bool:
    if reprocess:
        return False
    if is_incomplete_reply(state, item):
        return False
    processed = set(state.get("processed_uids") or [])
    if item["uid"] in processed:
        return True
    mid_key = message_uid_key(item.get("message_id") or "")
    return bool(mid_key and mid_key in _replied_ids_set(state))


def message_already_answered(
    state: dict, item: dict, fingerprint: str, *, reprocess: bool = False
) -> bool:
    if reprocess:
        return False
    if is_incomplete_reply(state, item):
        return False
    if message_processed(state, item, reprocess=False):
        return True
    if already_replied_fingerprint(state, fingerprint):
        return True
    return False


def mark_message_processed(processed: set[str], item: dict) -> None:
    processed.add(item["uid"])
    mid_key = message_uid_key(item.get("message_id") or "")
    if mid_key:
        processed.add(mid_key)


def message_fingerprint(*, from_email: str, subject: str, body: str) -> str:
    core = effective_customer_text(subject=subject, raw_body=body)[:500].lower()
    subj = normalize_subject(subject).lower()[:80]
    blob = f"{from_email.lower()}|{subj}|{core}"
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def already_replied_fingerprint(state: dict, fp: str) -> bool:
    return fp in set(state.get("replied_fingerprints") or [])


def record_reply_fingerprint(state: dict, fp: str) -> None:
    fps = state.setdefault("replied_fingerprints", [])
    if fp not in fps:
        fps.append(fp)
    state["replied_fingerprints"] = fps[-300:]


def sender_in_cooldown(state: dict, from_email: str, fingerprint: str) -> bool:
    """Не чаще одного ответа на тот же текст; разные письма — без паузы."""
    hours = max(0, int(cfg("REPLY_COOLDOWN_HOURS", "4")))
    if hours == 0:
        return False
    if already_replied_fingerprint(state, fingerprint):
        return True
    by_fp = state.get("recent_reply_fingerprints", {})
    last = by_fp.get(fingerprint)
    if not last:
        return False
    dt = parse_iso_dt(last)
    if not dt:
        return False
    return datetime.now(UTC) - dt < timedelta(hours=hours)


def record_sender_reply(state: dict, from_email: str, fingerprint: str) -> None:
    lr = state.setdefault("last_reply_at", {})
    lr[from_email.lower()] = datetime.now(UTC).isoformat()
    recent = state.setdefault("recent_reply_fingerprints", {})
    recent[fingerprint] = datetime.now(UTC).isoformat()
    # храним последние 300 отпечатков
    if len(recent) > 300:
        for k in list(recent.keys())[:-300]:
            del recent[k]


def ack_reply(customer_body: str) -> str:
    body = ACK_BODY_RU if _looks_russian(customer_body) else ACK_BODY_EN
    return reply_signature(body)


def _customer_asks_api(*, subject: str, body: str) -> bool:
    blob = f"{normalize_subject(subject)} {effective_customer_text(subject=subject, raw_body=body)}".lower()
    markers = (
        " api", "api?", "rest api", "enterprise api", "api key", "api keys",
        "public api", "developer api", "webhook", "интеграц", "есть ли api",
        "do you have an api", "offer an api", "api access",
    )
    return any(m in blob for m in markers)


def detect_faq_topic(*, subject: str, body: str) -> str | None:
    norm_subj = normalize_subject(subject)
    blob = build_faq_blob(subject=norm_subj or subject, body=body)
    cmd_topic = detect_command_topic(subject=norm_subj or subject, body=body)
    if cmd_topic:
        return cmd_topic
    if is_retail_buy_bitcoin_question(blob):
        return "not_exchange"
    if is_bot_created_question(blob) and not is_start_command_question(blob):
        return "bot_created"
    if is_start_command_question(blob) and not is_bot_overview_question(blob):
        if is_bot_created_question(blob):
            return "bot_created"
        return detect_command_topic(subject=norm_subj or subject, body=body) or "command:start"
    if is_bot_overview_question(blob):
        return "what_is"
    if detect_subscribe_intent(blob):
        return "subscribe"
    subj_low = (norm_subj or subject).strip().lower()
    if subj_low in {"help", "помощь", "support", "hi", "hello", "привет", "aide", "bonjour", "l"}:
        if len(blob) < 25:
            return "help"
    price_q = ("курс", "цена", "price", "prix", "cours", "сколько стоит", "котировк", "узнать")
    coin_w = ("биткоин", "биткойн", "bitcoin", " btc", "btc ", "btc\n")
    if any(p in blob for p in price_q) and any(w in blob for w in coin_w):
        return "btc_price"
    if any(
        w in blob
        for w in ("founding", "launch promo", "1 year free", "100 users", "бесплатн", "акци запуск")
    ) and any(w in blob for w in ("promo", "акци", "free", "бесплат", "founding")):
        return "promo"
    if any(w in blob for w in ("what is", "what does", "что такое", "about the bot", "о боте")):
        if not is_command_question(blob):
            return "what_is"
    if is_etf_coverage_question(blob):
        return "etf"
    if is_companies_coverage_question(blob):
        return "companies"
    if is_weekly_report_question(blob):
        return "weekly"
    if is_privacy_question(blob):
        return "privacy"
    if is_exchange_bot_question(blob):
        return "not_exchange"
    if is_free_tier_question(blob):
        return "plans"
    if any(
        w in blob
        for w in (
            "ibit", "fbtc", "gbtc", "arkb", "etf flow", "etf-поток", " etf", "etf ",
            "етф", " eтф",
        )
    ):
        return "etf"
    if any(w in blob for w in ("tesla", "mara", "metaplanet", "riot platforms", "company alert", "компани")):
        return "companies"
    if any(w in blob for w in ("holdings", "холдинг", "казн", "treasury balance", "баланс strategy")):
        return "holdings"
    if "strategy.com" in blob or "/site" in blob or "сайт strategy" in blob:
        return "site"
    if any(w in blob for w in ("donate", "donation", "пожертв", "tip btc")):
        return "donate"
    if any(w in blob for w in ("disclaimer", "investment advice", "дисклеймер", "не совет")):
        return "disclaimer"
    if any(w in blob for w in ("social", "twitter", "reddit", "соцсет", " follow ")):
        if not (re.search(r"/[a-z][a-z0-9]*", blob) and is_command_question(blob)):
            return "social"
    alert_w = ("алерт", "уведом", "оповещ", "alert", "notify", "notification")
    deal_w = ("strategy", "стратег", "saylor", "покуп", "продаж", "buy", "sell", "сделк")
    if any(a in blob for a in alert_w) or (
        any(_word_in_blob(d, blob) for d in deal_w)
        and any(w in blob for w in ("когда", "when", "получ", "get", "receive", "как получ"))
    ):
        if not any(w in blob for w in ("whale", "кит", "baleine", "держател", "ranking", "рейтинг", "топ")):
            return "alerts"
    if any(w in blob for w in ("weekly", "digest", "дайджест", "hebdomadaire", "résumé hebdo")):
        return "weekly"
    if any(
        w in blob
        for w in (
            "last purchase",
            "latest purchase",
            "последн",
            "latest buy",
            "покупк strategy",
            "крайн",
            "недавн покуп",
        )
    ) and any(
        w in blob
        for w in ("покуп", "buy", "purchase", "saylor", "сайлор", "strategy", "стратег", "битко", "bitcoin")
    ):
        if not is_retail_buy_bitcoin_question(blob):
            return "buy"
    if any(w in blob for w in ("language", "langue", "язык", "/lang", " switch ", "сменить язык")):
        return "language"
    if any(w in blob for w in ("whale", "whales", "кит", "киты", "baleine", "держател", "ranking", "рейтинг")):
        if not any(p in blob for p in price_q):
            return "whales"
    if any(w in blob for w in ("private key", "seed phrase", "сид-фраз", "приватн")):
        return "privacy"
    hinted = topic_from_faq_hints(blob, min_score=2)
    if hinted:
        return hinted
    return topic_from_faq_hints(blob, min_score=1, relaxed=True)


def faq_playbook_reply(*, subject: str, body: str) -> str | None:
    lang = _reply_lang(subject, body)
    multi_faq = multi_faq_playbook_reply(subject=subject, body=body, lang=lang)
    if multi_faq:
        return reply_signature(multi_faq)
    multi = multi_command_playbook_reply(subject=subject, body=body, lang=lang)
    if multi:
        return reply_signature(multi)
    core = effective_customer_text(subject=subject, raw_body=body)
    blob = faq_search_blob(subject=subject, raw_body=body)
    norm_subj = normalize_subject(subject)
    topic = detect_faq_topic(subject=norm_subj or subject, body=core)
    if not topic:
        topic = detect_faq_topic(subject=norm_subj or subject, body=blob)
    if not topic:
        topic = resolve_faq_topic(subject=norm_subj or subject, body=core)
    if not topic:
        topic = resolve_faq_topic(subject=norm_subj or subject, body=blob)
    if not topic:
        cmd = extract_question_command(blob.lower())
        if cmd:
            topic = f"command:{cmd}"
    if not topic:
        return None
    if not topic.startswith("command:") and topic not in FAQ_PLAYBOOKS:
        return None
    text = playbook_text_for_topic(topic, lang)
    if not text:
        return None
    if topic not in PLAYBOOK_NO_PS and topic != "help" and not topic.startswith("command:"):
        footer = MODEST_FOOTER.get(lang) or MODEST_FOOTER["en"]
        text = f"{text}\n\n{footer}"
    return reply_signature(text)


def classify_auto_send(*, subject: str, body: str, dry_run: bool = False) -> tuple[bool, str]:
    """В auto-режиме отвечаем сами на всё, кроме refund/legal/партнёрства."""
    if dry_run:
        return True, "dry-run"
    core = effective_customer_text(subject=subject, raw_body=body)
    norm_subj = normalize_subject(subject)
    search = faq_search_blob(subject=subject, raw_body=body)
    blob = search.lower()
    escalate_hints = (
        "refund", "chargeback", "dispute", "legal", "lawyer", "gdpr", "delete my data",
        "partnership", "scam", "fraud",
        "возврат", "жалоб", "юрист", "удалите данные", "партнёр",
        "купить ваш бот", "купить бот", "buy your bot", "acquire the bot",
    )
    if _customer_asks_api(subject=subject, body=body):
        return False, "keyword-escalate"
    if any(h in blob for h in escalate_hints):
        return False, "keyword-escalate"
    bug_phrases = ("bug report", "report a bug", "багрепорт", "сообщить об ошибке")
    if any(p in blob for p in bug_phrases):
        return False, "keyword-escalate"
    if detect_faq_topic(subject=norm_subj or subject, body=core) or detect_faq_topic(
        subject=norm_subj or subject, body=search
    ):
        return True, "faq-topic"
    if resolve_faq_topic(subject=norm_subj or subject, body=core) or resolve_faq_topic(
        subject=norm_subj or subject, body=search
    ):
        return True, "faq-topic"
    if extract_question_command(blob):
        return True, "faq-topic"
    subj_low = (norm_subj or subject).strip().lower()
    if subj_low in {"help", "помощь", "support", "hi", "hello", "привет", "aide", "bonjour"}:
        return True, "short-help-subject"
    if core and len(core.strip()) >= 3 and not is_trivial_reply(core):
        return True, "body-inquiry"
    # В auto отвечаем на всё, кроме keyword-escalate (см. docstring).
    return True, "general-inquiry"


def _playbook_text(topic: str, lang: str) -> str:
    return playbook_text_for_topic(topic, lang)


def _few_shot_turns(*, max_pairs: int | None = None, prefer_topic: str | None = None) -> list[tuple[str, str]]:
    """Пары user/assistant для обучения стилю Ollama."""
    shots = list(CANONICAL_FAQ_SHOTS)
    if prefer_topic:
        shots.sort(key=lambda s: 0 if s[2] == prefer_topic else 1)
    if max_pairs is not None:
        shots = shots[: max(1, max_pairs)]
    turns: list[tuple[str, str]] = []
    for subj, body, topic, lang in shots:
        gold = _playbook_text(topic, lang)
        if not gold:
            continue
        user_turn = f"Subject: {subj}\n\n{body}\n\n---\nWrite the reply body."
        turns.append((user_turn, gold))
    turns.append(OLLAMA_UNCERTAIN_SHOT)
    return turns


def build_ollama_reply_system() -> str:
    model = cfg("OLLAMA_MODEL", "qwen2.5:3b").lower()
    knowledge = "\n\n" + command_cheatsheet_for_llm() + "\n\n"
    if "saylorwatch-support" not in model:
        knowledge += "=== BOT KNOWLEDGE ===\n" + bot_knowledge_text(cfg) + "\n\n"
    return REPLY_PROMPT + "\n\n" + SYSTEM_PROMPT + knowledge + BAD_REPLY_EXAMPLE


def _customer_user_prompt(*, subject: str, body: str, from_hdr: str) -> str:
    topic = detect_faq_topic(subject=subject, body=body)
    hint = ""
    if topic and topic in FAQ_PLAYBOOKS:
        lang = _reply_lang(subject, body)
        ref = _playbook_text(topic, lang)
        hint = f"\n\nStyle reference for a similar question (do not copy blindly):\n{ref}"
    elif re.search(r"/[a-z][a-z0-9]*", body.lower()):
        lang = _reply_lang(subject, body)
        hint = (
            f"\n\nRelevant command briefs (use COMMAND CHEATSHEET for facts):\n"
            + command_cheatsheet_text(lang=lang, include_admin=False)[:1200]
        )
    return (
        f"From: {from_hdr}\nSubject: {subject}\n\n{body}\n\n---\nWrite the reply body.{hint}"
    )


def polish_llm_reply(text: str) -> str:
    """Убирает лишние прощания и дубли подписи от модели."""
    import re

    text = re.sub(r"\n--\s*\nSaylorWatch Support.*", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(
        r"\n+(Cordialement|Best regards|Sincerely|Je reste à votre disposition|С уважением).*$",
        "",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    return text.strip()


def _extract_slash_commands(text: str) -> list[str]:
    import re

    found: list[str] = []
    for m in re.finditer(r"/([a-z][a-z0-9]*)", text.lower()):
        found.append(m.group(1))
    return found


def validate_llm_reply(text: str, *, customer_body: str = "", subject: str = "") -> bool:
    """False → не отправлять клиенту (только ACK)."""
    if _customer_asks_api(subject=subject, body=customer_body):
        return False
    if not text or len(text.strip()) < 40:
        return False
    low = text.lower()
    if any(p in low for p in FORBIDDEN_COMMAND_PHRASES):
        return False
    if any(h in low for h in HEDGE_PHRASES):
        return False
    for cmd in _extract_slash_commands(text):
        blob = f"{subject} {customer_body}".lower()
        asked = extract_question_command(blob) if is_command_question(blob) else None
        if asked and cmd == asked:
            continue
        if cmd in ADMIN_ONLY_COMMANDS or cmd not in VALID_BOT_COMMANDS:
            return False
    asked_premium = any(
        w in f"{customer_body}".lower()
        for w in ("premium", "subscribe", "подписк", "премиум", "stars", "тариф", "plans")
    )
    if not asked_premium and "/subscribe" in low:
        return False
    return True


def parse_ollama_reply(raw: str, *, customer_body: str = "", subject: str = "") -> tuple[bool, str]:
    raw = raw.strip()
    if raw.upper().startswith("UNCERTAIN:"):
        return False, raw
    body = polish_llm_reply(raw)
    if not validate_llm_reply(body, customer_body=customer_body, subject=subject):
        return False, raw
    return True, body


@dataclass
class ReplyOutcome:
    text: str | None
    confident: bool
    source: str  # playbook | ollama | uncertain | ollama-error
    detail: str = ""


def _uncertain_detail(raw: str) -> str:
    raw = raw.strip()
    if raw.upper().startswith("UNCERTAIN:"):
        return raw.split(":", 1)[1].strip() or raw
    return raw[:300]


def generate_reply_outcome(
    *,
    subject: str,
    body: str,
    from_hdr: str,
    dry_run: bool = False,
    raw_body: str | None = None,
) -> ReplyOutcome:
    raw = raw_body if raw_body is not None else body
    playbook = faq_playbook_reply(subject=subject, body=raw)
    if playbook:
        return ReplyOutcome(playbook, True, "playbook")

    search_blob = faq_search_blob(subject=subject, raw_body=raw)
    topic = detect_faq_topic(subject=subject, body=search_blob)
    if not topic:
        core = effective_customer_text(subject=subject, raw_body=raw)
        topic = detect_faq_topic(subject=subject, body=core)
    if topic and topic in FAQ_PLAYBOOKS:
        lang = _reply_lang(subject, effective_customer_text(subject=subject, raw_body=raw))
        text = playbook_text_for_topic(topic, lang)
        if text:
            return ReplyOutcome(reply_signature(text), True, "playbook-topic")

    if mail_has_faq_intent(subject=subject, body=raw):
        cmd = extract_question_command(faq_search_blob(subject=subject, raw_body=raw).lower())
        if cmd:
            lang = _reply_lang(subject, effective_customer_text(subject=subject, raw_body=raw))
            text = playbook_text_for_topic(f"command:{cmd}", lang)
            if text:
                return ReplyOutcome(reply_signature(text), True, "playbook")
        help_text = playbook_text_for_topic(
            "help", _reply_lang(subject, effective_customer_text(subject=subject, raw_body=raw))
        )
        if help_text:
            return ReplyOutcome(reply_signature(help_text), True, "playbook")
        print("FAQ intent — Ollama пропущен")
        return ReplyOutcome(None, False, "uncertain", "faq playbook miss")

    core = effective_customer_text(subject=subject, raw_body=raw)

    if cfg("OLLAMA_ENABLED", "true").lower() in {"0", "false", "no"}:
        print("Ollama отключён (OLLAMA_ENABLED=false) — ACK клиенту")
        return ReplyOutcome(None, False, "uncertain", "ollama disabled")

    prompt = _customer_user_prompt(subject=subject, body=core or body, from_hdr=from_hdr)
    try:
        raw_ollama = ollama_chat(
            prompt,
            dry_run=dry_run,
            system=build_ollama_reply_system(),
            few_shot=_few_shot_turns(
                max_pairs=int(cfg("OLLAMA_FEW_SHOT_MAX", "4") or "4"),
                prefer_topic=detect_faq_topic(
                    subject=subject,
                    body=faq_search_blob(subject=subject, raw_body=raw),
                ),
            ),
        )
        ok, polished = parse_ollama_reply(raw_ollama, customer_body=core or body, subject=subject)
        if ok:
            return ReplyOutcome(reply_signature(polished), True, "ollama")
        detail = _uncertain_detail(raw_ollama)
        print(f"Ollama: неуверенный ответ — ACK клиенту ({detail[:120]}…)")
        return ReplyOutcome(None, False, "uncertain", detail)
    except RuntimeError as exc:
        forced = faq_playbook_reply(subject=subject, body=raw)
        if forced:
            print(f"Ollama: ошибка — отправлен playbook ({exc})")
            return ReplyOutcome(forced, True, "playbook-after-ollama-error")
        print(f"Ollama: ошибка — ACK клиенту ({exc})")
        return ReplyOutcome(None, False, "ollama-error", str(exc))


def generate_reply(*, subject: str, body: str, from_hdr: str, dry_run: bool = False) -> str:
    outcome = generate_reply_outcome(
        subject=subject, body=body, from_hdr=from_hdr, dry_run=dry_run
    )
    if outcome.confident and outcome.text:
        return outcome.text
    return ack_reply(body)


def telegram_notify_manual_reply(
    *,
    from_hdr: str,
    subject: str,
    body: str,
    source: str,
    detail: str,
) -> None:
    excerpt = body.strip()[:900]
    telegram_send(
        f"📩 AI не уверен — нужен ваш ответ\n"
        f"From: {from_hdr}\n"
        f"Subj: {subject}\n"
        f"Причина: {source}"
        + (f" — {detail}" if detail else "")
        + "\n\n"
        f"Клиенту ушло авто-подтверждение (без выдуманного FAQ).\n\n"
        f"--- письмо ---\n{excerpt}"
    )


def telegram_send(text: str) -> None:
    token = cfg("TELEGRAM_BOT_TOKEN")
    chat_id = cfg("TELEGRAM_ADMIN_CHAT_ID")
    if not token or not chat_id:
        print("Telegram: пропуск (нет TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID)")
        return
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {"chat_id": int(chat_id), "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            json.loads(resp.read())
        print("Telegram: отправлено")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        print(f"Telegram: ошибка {exc.code} — проверьте TELEGRAM_BOT_TOKEN / TELEGRAM_ADMIN_CHAT_ID ({detail})")
    except urllib.error.URLError as exc:
        print(f"Telegram: сеть недоступна — {exc}")


def state_path() -> Path:
    return ROOT / cfg("STATE_FILE", "scripts/.email_support_state.json")


def parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def weekly_summary_due(state: dict) -> bool:
    last = parse_iso_dt(state.get("weekly_last"))
    if last is None:
        return True
    return datetime.now(UTC) - last >= timedelta(days=7)


def wait_for_services(*, dry_run: bool = False) -> None:
    """Ждёт почту (Graph или IMAP) и Ollama после включения ПК."""
    if dry_run:
        return
    wait_sec = max(0, int(cfg("STARTUP_WAIT_SECONDS", "45")))
    if wait_sec:
        print(f"Waiting {wait_sec}s before mail check…")
        time.sleep(wait_sec)

    imap_timeout = max(10, int(cfg("IMAP_WAIT_SECONDS", cfg("BRIDGE_WAIT_SECONDS", "120"))))
    ollama_timeout = max(10, int(cfg("OLLAMA_WAIT_SECONDS", "60")))

    read_method = mail_read_method()
    use_graph_read = read_method == "graph" or (read_method == "auto" and _graph_read_ready())

    if use_graph_read:
        deadline_graph = time.monotonic() + imap_timeout
        while time.monotonic() < deadline_graph:
            try:
                user = cfg("MAIL_USER")
                client_id, scopes, token_path = _graph_settings()
                fetch_inbox_messages(
                    mail_user=user,
                    client_id=client_id,
                    scopes=scopes,
                    token_path=token_path,
                    since_days=1,
                )
                print("Mail read: Graph OK")
                break
            except Exception as exc:
                print(f"Graph not ready: {exc}")
                time.sleep(5)
        else:
            raise RuntimeError(
                f"Graph не ответил за {imap_timeout}s — проверьте --oauth-graph"
            )
    else:
        deadline_imap = time.monotonic() + imap_timeout
        while time.monotonic() < deadline_imap:
            try:
                mail = imap_select_with_retry(cfg("MAIL_INBOX", "INBOX"), attempts=2)
                mail.logout()
                print("Mail read: IMAP OK")
                break
            except Exception as exc:
                print(f"IMAP not ready: {exc}")
                time.sleep(5)
        else:
            raise RuntimeError(
                f"IMAP не ответил за {imap_timeout}s — проверьте OAuth (--oauth-login) или почту"
            )

    if cfg("EMAIL_AGENT_MODE", "draft").lower() == "suggest" and not cfg("OLLAMA_URL"):
        return
    deadline_ollama = time.monotonic() + ollama_timeout
    base = cfg("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = cfg("OLLAMA_MODEL", "qwen2.5:3b")
    url = f"{base}/api/tags"
    while time.monotonic() < deadline_ollama:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    names = {m.get("name", "") for m in data.get("models", [])}
                    if model not in names and f"{model}:latest" not in names:
                        installed = ", ".join(sorted(names)) or "(нет моделей)"
                        raise RuntimeError(
                            f"модель «{model}» не установлена. Доступно: {installed}. "
                            f"Выполните: ollama pull {model}"
                        )
                    print(f"Ollama: OK ({model})")
                    break
        except RuntimeError:
            raise
        except Exception as exc:
            print(f"Ollama not ready: {exc}")
            time.sleep(3)
    else:
        raise RuntimeError(f"Ollama не ответил за {ollama_timeout}s — запустите ollama serve")


def _env_bool(key: str, default: bool = False) -> bool:
    val = cfg(key, "true" if default else "false").lower()
    return val in {"1", "true", "yes", "on"}


def _oauth_settings() -> tuple[str, str, str, Path]:
    client_id = cfg("OAUTH_CLIENT_ID", DEFAULT_CLIENT_ID)
    redirect_uri = cfg("OAUTH_REDIRECT_URI", DEFAULT_REDIRECT_URI)
    scopes = cfg("OAUTH_SCOPES", DEFAULT_SCOPES)
    token_path = token_file_path(cfg("OAUTH_TOKEN_FILE", "scripts/.email_oauth.json"))
    return client_id, redirect_uri, scopes, token_path


def mail_auth_mode() -> str:
    mode = cfg("MAIL_AUTH", "oauth").lower()
    if mode in {"oauth", "password"}:
        return mode
    return "oauth"


def oauth_access_token() -> str:
    user = cfg("MAIL_USER")
    if not user:
        raise RuntimeError("Задайте MAIL_USER в scripts/email_support.env")
    client_id, redirect_uri, scopes, token_path = _oauth_settings()
    return get_access_token(
        mail_user=user,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        token_path=token_path,
    )


def oauth_login_cli() -> None:
    user = cfg("MAIL_USER")
    if not user:
        raise RuntimeError("Задайте MAIL_USER в scripts/email_support.env")
    client_id, redirect_uri, scopes, token_path = _oauth_settings()
    interactive_login(
        mail_user=user,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=scopes,
        token_path=token_path,
    )


def _graph_settings() -> tuple[str, str, Path]:
    client_id = cfg("GRAPH_CLIENT_ID", DEFAULT_GRAPH_CLIENT_ID)
    scopes = cfg("GRAPH_SCOPES", DEFAULT_GRAPH_SCOPES)
    token_path = token_file_path(cfg("GRAPH_TOKEN_FILE", "scripts/.email_graph_oauth.json"))
    return client_id, scopes, token_path


def oauth_graph_cli() -> None:
    user = cfg("MAIL_USER")
    if not user:
        raise RuntimeError("Задайте MAIL_USER в scripts/email_support.env")
    client_id, scopes, token_path = _graph_settings()
    device_code_login(
        mail_user=user,
        client_id=client_id,
        scopes=scopes,
        token_path=token_path,
    )


def send_methods() -> list[str]:
    raw = cfg("EMAIL_SEND_METHOD", "graph").lower().replace(" ", "")
    methods = [m for m in raw.split(",") if m] or ["graph"]
    if (
        cfg("GMAIL_USER")
        and cfg("GMAIL_APP_PASSWORD")
        and "gmail" not in methods
        and _env_bool("GMAIL_AUTO_FALLBACK", True)
    ):
        methods.append("gmail")
    return methods


def send_ready_status() -> tuple[bool, str]:
    """Проверка: хотя бы один канал отправки настроен и Graph-токен валиден."""
    for method in send_methods():
        if method == "graph":
            _, _, token_path = _graph_settings()
            if not load_tokens(token_path):
                continue
            try:
                user = cfg("MAIL_USER")
                client_id, scopes, _ = _graph_settings()
                get_graph_access_token(
                    mail_user=user,
                    client_id=client_id,
                    scopes=scopes,
                    token_path=token_path,
                )
                return True, "graph"
            except Exception as exc:
                return False, f"Graph токен недействителен: {exc}"
        elif method == "gmail":
            if cfg("GMAIL_USER") and cfg("GMAIL_APP_PASSWORD"):
                return True, "gmail"
        elif method == "smtp":
            if cfg("MAIL_USER") and (
                mail_auth_mode() == "oauth" or cfg("MAIL_PASSWORD")
            ):
                return True, "smtp"
    return False, "нет токена Graph (--oauth-graph) и не задан Gmail"


def send_reply_retry(
    reply_to: str,
    subject: str,
    body: str,
    *,
    attempts: int | None = None,
) -> None:
    n = attempts if attempts is not None else max(1, int(cfg("SEND_RETRY_ATTEMPTS", "3")))
    delay = max(1, int(cfg("SEND_RETRY_DELAY", "5")))
    last: Exception | None = None
    for i in range(n):
        try:
            send_reply(reply_to, subject, body)
            return
        except Exception as exc:
            last = exc
            if i + 1 < n:
                time.sleep(delay)
    assert last is not None
    raise last


def _queue_pending(
    state: dict,
    *,
    uid: str,
    to: str,
    subject: str,
    body: str,
    kind: str,
    error: str,
) -> None:
    pending = state.setdefault("pending_replies", {})
    now = datetime.now(UTC).isoformat()
    if uid in pending:
        entry = pending[uid]
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_error"] = error[:500]
        entry["last_attempt"] = now
    else:
        pending[uid] = {
            "to": to,
            "subject": subject,
            "body": body,
            "kind": kind,
            "attempts": 1,
            "last_error": error[:500],
            "first_attempt": now,
            "last_attempt": now,
        }


def process_pending_replies(
    state: dict,
    *,
    dry_run: bool = False,
) -> int:
    """Повторная отправка из очереди (timer каждые 30 мин)."""
    pending = state.get("pending_replies") or {}
    if not pending:
        return 0
    if dry_run:
        print(f"[dry-run] pending replies: {len(pending)}")
        return 0
    ready, _ = send_ready_status()
    if not ready:
        return 0
    processed = set(state.get("processed_uids", []))
    sent = 0
    alert_every = max(1, int(cfg("SEND_ALERT_EVERY", "10")))
    for uid, item in list(pending.items()):
        to = item["to"]
        subj = item["subject"]
        body = item["body"]
        attempts = int(item.get("attempts", 0))
        try:
            send_reply_retry(to, subj, body)
            del pending[uid]
            processed.add(uid)
            sent += 1
            print(f"Pending sent uid={uid} → {to}")
        except Exception as exc:
            item["attempts"] = attempts + 1
            item["last_error"] = str(exc)[:500]
            item["last_attempt"] = datetime.now(UTC).isoformat()
            if item["attempts"] == 1 or item["attempts"] % alert_every == 0:
                telegram_send(
                    f"🚨 Auto-send не удался (uid={uid}, попытка {item['attempts']})\n"
                    f"To: {to}\nОшибка: {exc}\n"
                    f"Повтор при следующем опросе. Проверьте --oauth-graph или Gmail."
                )
            print(f"Pending retry failed uid={uid}: {exc}")
    state["pending_replies"] = pending
    state["processed_uids"] = sorted(processed)[-500:]
    return sent


def _norm_mail_subj(subject: str) -> str:
    s = normalize_subject(subject or "").strip().lower()
    return s if s else "(no subject)"


def _incomplete_matches_item(item: dict, meta: dict) -> bool:
    if meta.get("uid") and item["uid"] == meta["uid"]:
        return True
    frm = (meta.get("from_email") or "").strip().lower()
    if frm and item.get("from_email", "").lower() != frm:
        return False
    want = _norm_mail_subj(meta.get("subject") or "")
    got = _norm_mail_subj(item.get("subject") or "")
    if want in {"(no subject)", "no subject"}:
        return got in {"(no subject)", "no subject"} and bool(meta.get("uid"))
    return want == got


def process_incomplete_replies(
    state: dict,
    messages: list[dict],
    *,
    dry_run: bool = False,
) -> int:
    """Дозаполнение: был только ACK — отправить playbook, если теперь известен ответ."""
    repair_incomplete_from_stats(state)
    inc = state.get("incomplete_replies") or {}
    if not inc:
        return 0
    if not dry_run:
        ready, detail = send_ready_status()
        if not ready:
            print(f"Incomplete follow-up: send not ready ({detail})")
            return 0
    handled = 0
    for key, meta in list(inc.items()):
        item = next((m for m in messages if _incomplete_matches_item(m, meta)), None)
        if not item:
            continue
        mid_key = message_uid_key(item.get("message_id") or "")
        if mid_key and mid_key in _replied_ids_set(state):
            if key in inc:
                del inc[key]
            continue
        raw = item["body"].strip()
        subj = item["subject"]
        playbook = faq_playbook_reply(subject=subj, body=raw)
        if not playbook:
            continue
        if dry_run:
            print(f"[dry-run] Follow-up FAQ → {item['from_email']} subj={subj[:50]!r}")
            handled += 1
            continue
        try:
            send_reply_retry(item["from_email"], reply_subject_line(subj), playbook)
            fp = message_fingerprint(from_email=item["from_email"], subject=subj, body=raw)
            record_reply_fingerprint(state, fp)
            record_sender_reply(state, item["from_email"], fp)
            record_replied_message_id(state, item)
            if key in inc:
                del inc[key]
            state["incomplete_replies"] = inc
            record_mail_stat(
                state,
                from_email=item["from_email"],
                subject=subj,
                action="auto_replied",
                reason="followup-playbook",
            )
            print(f"Follow-up FAQ sent → {item['from_email']} ({subj[:50]!r})")
            handled += 1
        except Exception as exc:
            print(f"Follow-up failed subj={subj[:40]!r}: {exc}")
    return handled


def alert_stale_unprocessed(state: dict, messages: list[dict]) -> None:
    """Telegram, если письмо клиента в ящике > N ч без ответа."""
    hours = max(1, int(cfg("STALE_MAIL_ALERT_HOURS", "4")))
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    last_alert = parse_iso_dt(state.get("stale_mail_alert_at"))
    if last_alert and (datetime.now(UTC) - last_alert).total_seconds() < 3600:
        return
    stale: list[str] = []
    for item in messages:
        if _skip_sender(item.get("from_email", "")):
            continue
        dt = parse_iso_dt(item.get("date"))
        if not dt or dt > cutoff:
            continue
        raw = item["body"].strip()
        fp = message_fingerprint(
            from_email=item["from_email"], subject=item["subject"], body=raw
        )
        if is_incomplete_reply(state, item):
            stale.append(f"• {item['subject'][:50]} — только ACK, ждёт FAQ")
            continue
        if not message_already_answered(state, item, fp):
            stale.append(f"• {item['subject'][:50]} от {item['from_email']}")
    if not stale:
        return
    state["stale_mail_alert_at"] = datetime.now(UTC).isoformat()
    telegram_send(
        "⚠️ SaylorWatch mail: письма без полного ответа\n"
        f"(старше {hours} ч)\n\n"
        + "\n".join(stale[:8])
    )


def _send_smtp(reply_to: str, subject: str, body: str) -> None:
    host = cfg("SMTP_HOST", "127.0.0.1")
    port = int(cfg("SMTP_PORT", "1025"))
    user = cfg("MAIL_USER")
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = reply_to
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if _env_bool("SMTP_USE_SSL"):
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            if mail_auth_mode() == "oauth":
                _smtp_xoauth2(smtp, user, oauth_access_token())
            else:
                smtp.login(user, cfg("MAIL_PASSWORD"))
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            if mail_auth_mode() == "oauth":
                _smtp_xoauth2(smtp, user, oauth_access_token())
            else:
                smtp.login(user, cfg("MAIL_PASSWORD"))
            smtp.send_message(msg)


def _send_gmail(reply_to: str, subject: str, body: str) -> None:
    user = cfg("GMAIL_USER")
    password = cfg("GMAIL_APP_PASSWORD")
    if not user or not password:
        raise RuntimeError("GMAIL_USER и GMAIL_APP_PASSWORD нужны для метода gmail")
    msg = MIMEMultipart()
    msg["From"] = user
    msg["To"] = reply_to
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(user, password.replace(" ", ""))
        smtp.send_message(msg)


def _imap_xoauth2(mail: imaplib.IMAP4, user: str, access_token: str) -> None:
    auth = xoauth2_string(user, access_token)
    mail.authenticate("XOAUTH2", lambda _: auth.encode())


def _smtp_xoauth2(smtp: smtplib.SMTP, user: str, access_token: str) -> None:
    auth = xoauth2_string(user, access_token)
    smtp.auth("XOAUTH2", lambda challenge=None: auth)


def connect_imap() -> imaplib.IMAP4:
    host = cfg("IMAP_HOST", "127.0.0.1")
    port = int(cfg("IMAP_PORT", "1143"))
    user = cfg("MAIL_USER")
    if not user:
        raise RuntimeError("Задайте MAIL_USER в scripts/email_support.env")
    if _env_bool("IMAP_USE_SSL"):
        mail = imaplib.IMAP4_SSL(host, port)
    else:
        mail = imaplib.IMAP4(host, port)
        mail.starttls()
    if mail_auth_mode() == "oauth":
        _imap_xoauth2(mail, user, oauth_access_token())
    else:
        password = cfg("MAIL_PASSWORD")
        if not password:
            raise RuntimeError("MAIL_AUTH=password, но MAIL_PASSWORD пуст")
        mail.login(user, password)
    return mail


def _imap_select(mail: imaplib.IMAP4, folder: str) -> None:
    typ, data = mail.select(folder)
    if typ != "OK":
        detail = (data[0].decode() if data and data[0] else typ) or typ
        raise RuntimeError(detail)


def imap_select_with_retry(folder: str, *, attempts: int | None = None) -> imaplib.IMAP4:
    """SELECT с переподключением (Evolution может держать INBOX)."""
    n = attempts if attempts is not None else max(1, int(cfg("IMAP_SELECT_RETRIES", "4")))
    delay = max(1, int(cfg("IMAP_SELECT_RETRY_DELAY", "3")))
    last: Exception | None = None
    for i in range(n):
        mail = None
        try:
            mail = connect_imap()
            _imap_select(mail, folder)
            return mail
        except Exception as exc:
            last = exc
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass
            if i + 1 < n:
                print(f"IMAP {folder}: {exc} — retry {i + 2}/{n}…")
                time.sleep(delay)
    assert last is not None
    raise last


def mail_read_method() -> str:
    mode = cfg("MAIL_READ_METHOD", "auto").lower()
    if mode in {"imap", "graph", "auto"}:
        return mode
    return "auto"


def _graph_read_ready() -> bool:
    _, _, token_path = _graph_settings()
    return bool(load_tokens(token_path))


def fetch_messages(
    *, since_days: int | None = None, since_datetime: datetime | None = None
) -> list[dict]:
    lookback = since_days if since_days is not None else int(cfg("INBOX_LOOKBACK_DAYS", "14"))
    method = mail_read_method()

    if method == "graph" or (method == "auto" and _graph_read_ready()):
        try:
            user = cfg("MAIL_USER")
            client_id, scopes, token_path = _graph_settings()
            msgs = fetch_inbox_messages(
                mail_user=user,
                client_id=client_id,
                scopes=scopes,
                token_path=token_path,
                since_days=lookback,
                since_datetime=since_datetime,
            )
            if since_datetime is not None:
                msgs = [
                    m
                    for m in msgs
                    if not m.get("date")
                    or (parse_iso_dt(m["date"]) or datetime.min.replace(tzinfo=UTC))
                    >= since_datetime.astimezone(UTC)
                ]
            print(f"Graph: fetched {len(msgs)} message(s)")
            return msgs
        except Exception as exc:
            if method == "graph":
                raise
            print(f"Graph read failed ({exc}) — fallback IMAP")

    inbox = cfg("MAIL_INBOX", "INBOX")
    mail = imap_select_with_retry(inbox)
    if since_datetime is not None:
        criterion = f'SINCE {since_datetime.astimezone(UTC).strftime("%d-%b-%Y")}'
    elif since_days is None:
        criterion = "ALL"
    else:
        criterion = (
            f'SINCE {(datetime.now(UTC) - timedelta(days=since_days)).strftime("%d-%b-%Y")}'
        )
    _, data = mail.search(None, criterion)
    ids = data[0].split() if data[0] else []
    results: list[dict] = []
    since_utc = since_datetime.astimezone(UTC) if since_datetime is not None else None
    for uid in ids:
        _, msg_data = mail.fetch(uid, "(RFC822)")
        if not msg_data or not msg_data[0]:
            continue
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        from_hdr = msg.get("From", "")
        subject = msg.get("Subject", "(no subject)")
        date_hdr = msg.get("Date")
        try:
            dt = parsedate_to_datetime(date_hdr) if date_hdr else None
            if dt is not None and dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            dt = None
        if since_utc is not None and dt is not None and dt.astimezone(UTC) < since_utc:
            continue
        body = extract_body(msg)
        msg_id = (msg.get("Message-ID") or msg.get("Message-Id") or "").strip()
        results.append(
            {
                "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                "message_id": msg_id,
                "from": from_hdr,
                "from_email": parseaddr(from_hdr)[1],
                "subject": subject,
                "date": dt.isoformat() if dt else "",
                "body": body[:8000],
            }
        )
    mail.logout()
    print(f"IMAP: fetched {len(results)} message(s)")
    return results


def extract_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and not part.get_filename():
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace").strip()
        return ""
    payload = msg.get_payload(decode=True)
    if not payload:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace").strip()


def save_draft(reply_to: str, subject: str, body: str) -> None:
    drafts = cfg("MAIL_DRAFTS", "Drafts")
    mail = imap_select_with_retry(drafts)
    msg = MIMEMultipart()
    msg["To"] = reply_to
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    raw = msg.as_bytes()
    mail.append(
        drafts,
        "\\Draft",
        None,
        raw,
    )
    mail.logout()


def send_reply(reply_to: str, subject: str, body: str, *, in_reply_to: str = "") -> None:
    user = cfg("MAIL_USER")
    if not user:
        raise RuntimeError("Задайте MAIL_USER в scripts/email_support.env")
    errors: list[str] = []
    for method in send_methods():
        try:
            if method == "graph":
                client_id, scopes, token_path = _graph_settings()
                graph_send_mail(
                    to=reply_to,
                    subject=subject,
                    body=body,
                    mail_user=user,
                    client_id=client_id,
                    scopes=scopes,
                    token_path=token_path,
                )
            elif method == "gmail":
                _send_gmail(reply_to, subject, body)
            elif method == "smtp":
                _send_smtp(reply_to, subject, body)
            else:
                raise RuntimeError(f"Неизвестный EMAIL_SEND_METHOD: {method}")
            print(f"Sent ({method}) → {reply_to}")
            return
        except Exception as exc:
            errors.append(f"{method}: {exc}")
    raise RuntimeError("Send failed — " + "; ".join(errors))


def _skip_sender(from_email: str) -> bool:
    addr = from_email.lower().strip()
    if not addr:
        return True
    if addr == cfg("MAIL_USER").lower():
        return True
    skip_domains = (
        "microsoft.com",
        "accountprotection.microsoft.com",
        "office365.com",
    )
    skip_local = ("no-reply", "noreply", "donotreply", "mailer-daemon", "postmaster")
    local, _, domain = addr.rpartition("@")
    if any(domain.endswith(d) for d in skip_domains):
        return True
    if any(local.startswith(p) for p in skip_local):
        return True
    return False


def forget_messages_for_retry(state: dict, *, subject_contains: str) -> int:
    """Сброс dedup для повторной отправки (одна тема, без --reprocess всего ящика)."""
    needle = subject_contains.strip().lower()
    if not needle:
        return 0
    processed = set(state.get("processed_uids") or [])
    replied_ids = list(state.get("replied_message_ids") or [])
    fps = list(state.get("replied_fingerprints") or [])
    recent = dict(state.get("recent_reply_fingerprints") or {})
    removed = 0
    for m in fetch_messages():
        if needle not in (m.get("subject") or "").lower():
            continue
        processed.discard(m["uid"])
        mid = message_uid_key(m.get("message_id") or "")
        if mid:
            processed.discard(mid)
            if mid in replied_ids:
                replied_ids.remove(mid)
        fp = message_fingerprint(
            from_email=m["from_email"],
            subject=m["subject"],
            body=m.get("body") or "",
        )
        if fp in fps:
            fps.remove(fp)
        if fp in recent:
            del recent[fp]
        removed += 1
    state["processed_uids"] = _trim_uid_keys(processed)
    state["replied_message_ids"] = replied_ids[-500:]
    state["replied_fingerprints"] = fps[-300:]
    state["recent_reply_fingerprints"] = recent
    state.pop("sent_outbound_hashes", None)
    return removed


def _trim_uid_keys(processed: set[str]) -> list[str]:
    """Обрезать только IMAP/Graph uid — mid: хранятся в replied_message_ids."""
    return sorted(k for k in processed if not str(k).startswith("mid:"))[-200:]


def catchup_since_datetime(state: dict) -> datetime:
    """Окно catch-up после перезагрузки: с last_run, не весь ящик за 30 дней."""
    last_run = parse_iso_dt(state.get("last_run"))
    buffer_h = max(0, int(cfg("CATCHUP_BUFFER_HOURS", "2")))
    max_days = max(1, int(cfg("CATCHUP_MAX_DAYS", "3")))
    now = datetime.now(UTC)
    if last_run:
        since = last_run - timedelta(hours=buffer_h)
    else:
        since = now - timedelta(days=1)
    cap = now - timedelta(days=max_days)
    return max(since, cap)


def process_inbox(
    *,
    dry_run: bool = False,
    since_days: int | None = None,
    since_datetime: datetime | None = None,
    reprocess: bool = False,
    ignore_cooldown: bool = False,
) -> int:
    sp = state_path()
    lock_path = sp.with_suffix(sp.suffix + ".lock")
    with file_lock(lock_path):
        return _process_inbox_locked(
            sp,
            dry_run=dry_run,
            since_days=since_days,
            since_datetime=since_datetime,
            reprocess=reprocess,
            ignore_cooldown=ignore_cooldown,
        )


def _process_inbox_locked(
    sp: Path,
    *,
    dry_run: bool = False,
    since_days: int | None = None,
    since_datetime: datetime | None = None,
    reprocess: bool = False,
    ignore_cooldown: bool = False,
) -> int:
    state = load_state(sp)
    processed = set(state.get("processed_uids", []))
    pending = state.get("pending_replies") or {}
    mode = cfg("EMAIL_AGENT_MODE", "auto").lower()
    handled = 0
    lookback = since_days if since_days is not None else int(cfg("INBOX_LOOKBACK_DAYS", "14"))

    if not dry_run and mode in {"auto", "send"}:
        ready, status_detail = send_ready_status()
        if not ready:
            warned = state.get("send_not_ready_warned")
            if not warned:
                telegram_send(
                    "🚨 SaylorWatch mail: авто-отправка не настроена.\n"
                    f"{status_detail}\n\n"
                    "Один раз:\n"
                    "  python3 scripts/email_support_agent.py --oauth-graph"
                )
                state["send_not_ready_warned"] = datetime.now(UTC).isoformat()
        handled += process_pending_replies(state, dry_run=dry_run)

    if dry_run:
        messages = [
            {
                "uid": "dry-1",
                "from": "User <user@example.com>",
                "from_email": "user@example.com",
                "subject": "How to get Premium?",
                "date": datetime.now(UTC).isoformat(),
                "body": "Hello, how do I subscribe to Premium and is the promo still available?",
            }
        ]
    else:
        messages = fetch_messages(since_days=lookback, since_datetime=since_datetime)

    if not dry_run:
        handled += process_incomplete_replies(state, messages, dry_run=dry_run)
        alert_stale_unprocessed(state, messages)

    for item in messages:
        uid = item["uid"]
        raw_body = item["body"].strip()
        orig_subj = item["subject"]
        fp_early = message_fingerprint(
            from_email=item["from_email"], subject=orig_subj, body=raw_body
        )
        if not dry_run and message_already_answered(
            state, item, fp_early, reprocess=reprocess
        ):
            mark_message_processed(processed, item)
            continue
        if uid in pending and not reprocess:
            continue
        body = effective_customer_text(subject=orig_subj, raw_body=raw_body)
        subj = orig_subj
        if is_echo_of_our_reply(raw_body, subject=orig_subj):
            if not mail_has_faq_intent(subject=orig_subj, body=raw_body):
                mark_message_processed(processed, item)
                if not dry_run:
                    record_mail_stat(
                        state, from_email=item["from_email"], subject=subj, action="skipped"
                    )
                print(f"Skip uid={uid} (echo of our reply — без повторной отправки)")
                continue
        if not has_customer_inquiry(subject=orig_subj, raw_body=raw_body):
            fp_empty = message_fingerprint(
                from_email=item["from_email"], subject=orig_subj, body=raw_body
            )
            if not reprocess and already_replied_fingerprint(state, fp_empty):
                mark_message_processed(processed, item)
                print(f"Skip uid={uid} (duplicate empty fingerprint)")
                continue
            if dry_run:
                print(f"[dry-run] Prompt reply (empty) → {item['from_email']}")
            else:
                outbound = empty_inquiry_prompt_reply(subject=orig_subj, raw_body=raw_body)
                send_reply_retry(
                    item["from_email"],
                    reply_subject_line(orig_subj),
                    outbound,
                )
                fp_empty = message_fingerprint(
                    from_email=item["from_email"], subject=orig_subj, body=raw_body
                )
                record_reply_fingerprint(state, fp_empty)
                record_sender_reply(state, item["from_email"], fp_empty)
                record_replied_message_id(state, item)
                record_mail_stat(
                    state,
                    from_email=item["from_email"],
                    subject=subj,
                    action="auto_replied",
                    reason="empty-prompt",
                )
                print(f"Prompt reply (empty/no-subject) → {item['from_email']}")
            mark_message_processed(processed, item)
            handled += 1
            continue
        fp = message_fingerprint(from_email=item["from_email"], subject=orig_subj, body=raw_body)
        if not reprocess and already_replied_fingerprint(state, fp):
            mark_message_processed(processed, item)
            print(f"Skip uid={uid} (duplicate fingerprint)")
            continue
        if not reprocess and not ignore_cooldown and sender_in_cooldown(state, item["from_email"], fp):
            print(f"Skip uid={uid} (cooldown {item['from_email']}, повторим позже)")
            continue
        # не отвечать системным и самому себе
        if _skip_sender(item["from_email"]):
            mark_message_processed(processed, item)
            if not dry_run:
                record_mail_stat(state, from_email=item["from_email"], subject=item["subject"], action="skipped")
            continue

        subj = item["subject"]
        folder = item.get("folder") or "inbox"
        if folder == "junkemail":
            print(f"Junk folder: uid={uid} from={item['from_email']} subj={subj[:60]!r}")
        print(f"Handling uid={uid} from={item['from_email']} subj={subj[:60]!r}")

        try:
            sent = _process_one_message(
                item=item,
                uid=uid,
                body=body,
                raw_body=raw_body,
                fp=fp,
                mode=mode,
                dry_run=dry_run,
                state=state,
                subj=subj,
            )
        except Exception as exc:
            print(f"ERROR uid={uid}: {exc}")
            if not dry_run:
                telegram_send(
                    f"🚨 Ошибка обработки письма uid={uid}\n"
                    f"From: {item['from']}\n"
                    f"Subj: {subj}\n"
                    f"Ошибка: {exc}\n"
                    f"Письмо пропущено — следующий прогон повторит."
                )
            continue

        if not sent and not dry_run:
            print(f"Не помечаем uid={uid} обработанным — отправка не удалась")
            continue

        mark_message_processed(processed, item)
        handled += 1
        print(f"Processed uid={uid} from={item['from_email']}")

    if not dry_run:
        state["processed_uids"] = _trim_uid_keys(processed)
        state["pending_replies"] = state.get("pending_replies") or {}
        state["last_run"] = datetime.now(UTC).isoformat()
        save_state(sp, state, already_locked=True)
        if handled == 0 and messages:
            print(
                f"Inbox: {len(messages)} писем в окне — новых для ответа нет "
                f"(обработаны, дубликат или cooldown)"
            )
    return handled


def _process_one_message(
    *,
    item: dict,
    uid: str,
    body: str,
    raw_body: str,
    fp: str,
    mode: str,
    dry_run: bool,
    state: dict,
    subj: str,
) -> bool:
    """True если ответ клиенту ушёл (или dry-run)."""
    if dry_run:
        print(f"[dry-run] uid={uid} mode={mode} to={item['from_email']}")
        return True
    if mode == "auto":
        auto_ok, reason = classify_auto_send(subject=subj, body=raw_body, dry_run=dry_run)
        notify_admin = admin_notify_required(subject=subj, body=raw_body, reason=reason)
        outbound = ack_reply(body)
        kind = "ack"
        reply = ""
        stat_reason = reason
        notify_uncertain = False
        uncertain_detail = ""
        if auto_ok:
            outcome = generate_reply_outcome(
                subject=subj,
                body=body,
                from_hdr=item["from"],
                dry_run=dry_run,
                raw_body=raw_body,
            )
            if outcome.confident and outcome.text:
                outbound = outcome.text
                reply = outcome.text
                kind = "faq"
                stat_reason = (
                    reason if outcome.source == "playbook" else f"{reason}+{outcome.source}"
                )
            else:
                forced = faq_playbook_reply(subject=subj, body=raw_body)
                if forced:
                    outbound = forced
                    reply = forced
                    kind = "faq"
                    stat_reason = "playbook-forced"
                    print(f"Playbook forced → {item['from_email']}")
                else:
                    outbound = ack_reply(body)
                    reply = ""
                    kind = "ack"
                    stat_reason = outcome.source or "uncertain"
                    notify_uncertain = True
                    uncertain_detail = outcome.detail
        elif notify_admin:
            esc = generate_reply_outcome(
                subject=subj,
                body=body,
                from_hdr=item["from"],
                dry_run=dry_run,
            )
            reply = esc.text if esc.confident and esc.text else ""
        try:
            send_reply_retry(item["from_email"], reply_subject_line(subj), outbound)
            record_reply_fingerprint(state, fp)
            record_sender_reply(state, item["from_email"], fp)
            if kind == "faq":
                record_replied_message_id(state, item)
            elif kind == "ack":
                record_incomplete_reply(state, item, reason=stat_reason)
            if kind == "faq":
                record_mail_stat(
                    state,
                    from_email=item["from_email"],
                    subject=subj,
                    action="auto_replied",
                    reason=stat_reason,
                )
                print(f"Auto-reply sent → {item['from_email']} ({stat_reason})")
            elif notify_admin:
                save_draft(item["from_email"], subj, reply)
                record_mail_stat(
                    state,
                    from_email=item["from_email"],
                    subject=subj,
                    action="escalated",
                    reason=reason,
                )
                telegram_send(
                    f"⚠️ Нужен ваш ответ\n"
                    f"From: {item['from']}\n"
                    f"Subj: {subj}\n"
                    f"Причина: {reason}\n\n"
                    f"Клиенту ушло авто-подтверждение. Черновик ответа — в Evolution (Drafts).\n\n"
                    f"--- AI draft ---\n{reply[:2500]}"
                )
            elif notify_uncertain:
                record_mail_stat(
                    state,
                    from_email=item["from_email"],
                    subject=subj,
                    action="escalated" if not mail_has_faq_intent(subject=subj, body=raw_body) else "ack_only",
                    reason=stat_reason,
                )
                if mail_has_faq_intent(subject=subj, body=raw_body):
                    print(f"FAQ intent — Telegram пропущен → {item['from_email']} ({stat_reason})")
                else:
                    telegram_notify_manual_reply(
                        from_hdr=item["from"],
                        subject=subj,
                        body=body,
                        source=stat_reason,
                        detail=uncertain_detail,
                    )
                    print(f"Ack + Telegram → {item['from_email']} ({stat_reason})")
            else:
                record_mail_stat(
                    state,
                    from_email=item["from_email"],
                    subject=subj,
                    action="ack_only",
                    reason=stat_reason if auto_ok else reason,
                )
                print(
                    f"Ack sent → {item['from_email']} "
                    f"({stat_reason if auto_ok else reason}, без Telegram)"
                )
            return True
        except Exception as exc:
            _queue_pending(
                state,
                uid=uid,
                to=item["from_email"],
                subject=subj,
                body=outbound,
                kind=kind,
                error=str(exc),
            )
            record_mail_stat(
                state,
                from_email=item["from_email"],
                subject=subj,
                action="send_failed",
                reason=str(exc)[:80],
            )
            telegram_send(
                f"🚨 Не удалось отправить (uid={uid})\n"
                f"To: {item['from_email']}\n"
                f"Ошибка: {exc}\n"
                f"Повтор при следующем опросе. Проверьте --oauth-graph."
            )
            print(f"Queued uid={uid} for retry: {exc}")
        return False

    if mode == "send":
        reply = generate_reply(
            subject=subj,
            body=body,
            from_hdr=item["from"],
            dry_run=dry_run,
        )
        try:
            send_reply_retry(item["from_email"], subj, reply)
            record_mail_stat(
                state,
                from_email=item["from_email"],
                subject=subj,
                action="auto_replied",
            )
        except Exception as exc:
            _queue_pending(
                state,
                uid=uid,
                to=item["from_email"],
                subject=subj,
                body=reply,
                kind="faq",
                error=str(exc),
            )
            record_mail_stat(
                state,
                from_email=item["from_email"],
                subject=subj,
                action="send_failed",
                reason=str(exc)[:80],
            )
            telegram_send(f"🚨 Send queued (uid={uid}): {exc}")
            return False
        return True

    if mode == "draft":
        reply = generate_reply(
            subject=subj,
            body=body,
            from_hdr=item["from"],
            dry_run=dry_run,
        )
        save_draft(item["from_email"], subj, reply)
        record_mail_stat(
            state,
            from_email=item["from_email"],
            subject=subj,
            action="escalated",
            reason="draft-mode",
        )
        return True

    reply = generate_reply(
        subject=subj,
        body=body,
        from_hdr=item["from"],
        dry_run=dry_run,
    )
    out = ROOT / "scripts" / "drafts" / f"{uid}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"To: {item['from_email']}\nSubject: Re: {subj}\n\n{reply}",
        encoding="utf-8",
    )
    record_mail_stat(
        state,
        from_email=item["from_email"],
        subject=subj,
        action="escalated",
        reason="suggest-mode",
    )
    return True


def startup_catchup(*, dry_run: bool = False, reprocess: bool = False) -> int:
    """После включения ПК: догнать только письма с момента last_run, не весь ящик."""
    wait_for_services(dry_run=dry_run)
    sp = state_path()
    state = load_state(sp)
    since_dt = catchup_since_datetime(state)
    last_run = parse_iso_dt(state.get("last_run"))
    downtime = ""
    if last_run:
        hours = int((datetime.now(UTC) - last_run).total_seconds() // 3600)
        downtime = f" (ПК был выключен ~{hours} ч.)"

    print(f"Catch-up window: since {since_dt.isoformat()}{downtime}")
    n = process_inbox(dry_run=dry_run, since_datetime=since_dt, reprocess=reprocess)
    if n > 0:
        print(f"Catch-up{downtime}: обработано {n} писем")
    elif not dry_run:
        print(f"Catch-up: новых писем нет (окно с {since_dt.date()}){downtime}")

    state = load_state(sp)
    if weekly_summary_due(state):
        print("Weekly summary due — generating…")
        weekly_summary(dry_run=dry_run)
    elif not dry_run:
        print("Weekly summary: ещё не пора (след. через 7 дней после last weekly)")
    return n


def _action_label(action: str) -> str:
    labels = {
        "auto_replied": "авто-ответ",
        "ack_only": "подтверждение",
        "escalated": "эскалация",
        "skipped": "пропущено",
        "send_failed": "ошибка отправки",
    }
    return labels.get(action, action)


def _ru_letter_count(n: int) -> str:
    """«24 письма», «1 письмо», «5 писем»."""
    n_abs = abs(int(n))
    mod100 = n_abs % 100
    mod10 = n_abs % 10
    if 11 <= mod100 <= 19:
        word = "писем"
    elif mod10 == 1:
        word = "письмо"
    elif 2 <= mod10 <= 4:
        word = "письма"
    else:
        word = "писем"
    return f"{n_abs} {word}"


def _mail_item_line(it: dict) -> str:
    day = (it.get("at") or "")[:10] or "?"
    subj = (it.get("subject") or "")[:50]
    act = _action_label(it.get("action") or "")
    reason = it.get("reason") or ""
    extra = f" ({reason})" if reason and it.get("action") == "escalated" else ""
    return f"[{day}] {subj} — {act}{extra}"


def _group_mail_items(items: list[dict]) -> tuple[list[str], dict[str, list[dict]]]:
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for it in items:
        frm = it.get("from") or "?"
        if frm not in groups:
            groups[frm] = []
            order.append(frm)
        groups[frm].append(it)
    return order, groups


def format_weekly_report(ws: dict) -> str:
    received = int(ws.get("received", 0))
    processed = int(ws.get("processed", 0))
    period_start = ws.get("period_start", "")
    start_day = period_start[:10] if period_start else "?"
    end_day = datetime.now(UTC).strftime("%Y-%m-%d")

    lines = [
        "📊 SaylorWatch — отчёт за неделю",
        f"Период: {start_day} — {end_day}",
        "",
        f"Поступило: {received} писем.",
        f"Обработано: {processed} писем.",
    ]
    auto_n = int(ws.get("auto_replied", 0))
    ack_n = int(ws.get("ack_only", 0))
    esc_n = int(ws.get("escalated", 0))
    fail_n = int(ws.get("send_failed", 0))
    skip_n = int(ws.get("skipped", 0))
    if received or skip_n:
        if received:
            lines.append("")
            lines.append("По типам:")
            if auto_n:
                lines.append(f"  • авто-ответ (FAQ): {auto_n}")
            if ack_n:
                lines.append(f"  • подтверждение без эскалации: {ack_n}")
            if esc_n:
                lines.append(f"  • эскалация (нужен вы): {esc_n}")
            if fail_n:
                lines.append(f"  • ошибки отправки: {fail_n}")
        if skip_n:
            if not received:
                lines.append("")
                lines.append("По типам:")
            lines.append(f"  • пропущено (системные/пустые): {skip_n}")

    items = ws.get("items") or []
    if items:
        lines.append("")
        lines.append("Письма:")
        order, groups = _group_mail_items(items)
        display_items = items[-20:]
        max_detail = 20

        if len(order) == 1:
            frm = order[0]
            n = len(groups[frm])
            lines.append(f"  {frm} — {_ru_letter_count(n)}")
            shown = [it for it in display_items if (it.get("from") or "?") == frm]
            for it in shown:
                lines.append(f"  • {_mail_item_line(it)}")
            if n > len(shown):
                lines.append(f"  … показаны последние {len(shown)} из {n}")
        else:
            for frm in order:
                group = groups[frm]
                n = len(group)
                lines.append(f"  • {frm} — {_ru_letter_count(n)}")
                shown = [it for it in display_items if (it.get("from") or "?") == frm]
                for it in shown[:max_detail]:
                    lines.append(f"      • {_mail_item_line(it)}")
                if n > len(shown):
                    hidden = n - len(shown)
                    lines.append(f"      … ещё {hidden}")

    pending = ws.get("pending_at_report") or 0
    if pending:
        lines.append("")
        lines.append(f"В очереди на повторную отправку: {pending}")

    return "\n".join(lines)


def weekly_summary(*, dry_run: bool = False) -> None:
    state_path_val = state_path()
    state = load_state(state_path_val)
    ws = _week_stats(state)
    pending_n = len(state.get("pending_replies") or {})
    ws["pending_at_report"] = pending_n

    text = format_weekly_report(ws)
    if dry_run:
        print(text)
        return

    telegram_send(text)
    print(text)

    state["weekly_last"] = datetime.now(UTC).isoformat()
    state["week_stats"] = _empty_week_stats()
    save_state(state_path_val, state)


def main() -> int:
    parser = argparse.ArgumentParser(description="SaylorWatch email + Ollama agent")
    parser.add_argument("--weekly", action="store_true", help="Weekly summary to Telegram")
    parser.add_argument("--force-weekly", action="store_true", help="Weekly summary even if not due")
    parser.add_argument(
        "--startup",
        action="store_true",
        help="После включения ПК: catch-up пропущенных писем (+ weekly если пора)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Test without IMAP")
    parser.add_argument(
        "--oauth-login",
        action="store_true",
        help="Один раз: OAuth2 IMAP (чтение почты, live.com)",
    )
    parser.add_argument(
        "--oauth-graph",
        action="store_true",
        help="Один раз: OAuth2 Graph Mail.Send (авто-отправка ответов)",
    )
    parser.add_argument(
        "--test-send",
        metavar="EMAIL",
        help="Тестовое письмо через Graph/SMTP/Gmail (после --oauth-graph)",
    )
    parser.add_argument(
        "--setup-check",
        action="store_true",
        help="Проверить IMAP + Graph/Gmail отправку (без обработки писем)",
    )
    parser.add_argument(
        "--test-reply",
        metavar="TEXT",
        help="Проверить ответ Ollama на текст письма (без отправки)",
    )
    parser.add_argument(
        "--force-ollama",
        action="store_true",
        help="С --test-reply: всегда через Ollama (без playbook)",
    )
    parser.add_argument(
        "--reprocess",
        action="store_true",
        help="Повторно обработать письма (⚠️ может отправить дубликаты ответов)",
    )
    parser.add_argument(
        "--retry-subject",
        metavar="TEXT",
        help="Повторить ответ для писем, в теме которых есть TEXT (без reprocess всего ящика)",
    )
    args = parser.parse_args()

    if ENV_FILE.exists():
        load_env()
    else:
        print("Подсказка: cp scripts/email_support.example.env scripts/email_support.env")

    try:
        if args.oauth_login:
            oauth_login_cli()
            return 0
        if args.oauth_graph:
            oauth_graph_cli()
            return 0
        if args.test_send:
            send_reply(
                args.test_send,
                "SaylorWatch test",
                "Test auto-send from email_support_agent.py — Graph Mail.Send OK.",
            )
            print(f"Test sent to {args.test_send}")
            return 0
        if args.test_reply:
            if args.force_ollama:
                prompt = _customer_user_prompt(
                    subject="Test",
                    body=args.test_reply,
                    from_hdr="Test User <test@example.com>",
                )
                prefer = detect_faq_topic(subject="Test", body=args.test_reply)
                raw = ollama_chat(
                    prompt,
                    dry_run=args.dry_run,
                    system=build_ollama_reply_system(),
                    few_shot=_few_shot_turns(max_pairs=3, prefer_topic=prefer),
                    options={"num_predict": 320},
                )
                ok, polished = parse_ollama_reply(
                    raw, customer_body=args.test_reply, subject="Test"
                )
                if ok:
                    print(f"[ollama OK]\n{reply_signature(polished)}")
                else:
                    print(f"[ollama UNCERTAIN — клиенту только ACK]\n{raw}")
            else:
                out = generate_reply_outcome(
                    subject="Test",
                    body=args.test_reply,
                    from_hdr="Test User <test@example.com>",
                    dry_run=args.dry_run,
                )
                tag = "OK" if out.confident else "ACK ONLY"
                print(f"[{out.source} · {tag}]")
                print(out.text if out.confident and out.text else ack_reply(args.test_reply))
            return 0
        if args.setup_check:
            wait_for_services(dry_run=args.dry_run)
            ready, detail = send_ready_status()
            read_method = mail_read_method()
            if read_method == "graph" or (read_method == "auto" and _graph_read_ready()):
                msgs = fetch_messages(since_days=1)
                print(f"IMAP: skip (read via Graph) · Send: {'OK (' + detail + ')' if ready else 'FAIL — ' + detail}")
                print(f"Graph read: OK ({len(msgs)} msg in 1d lookback)")
            else:
                mail = imap_select_with_retry(cfg("MAIL_INBOX", "INBOX"))
                mail.logout()
                print(f"IMAP: OK · Send: {'OK (' + detail + ')' if ready else 'FAIL — ' + detail}")
            if not ready:
                print("\nЗапустите: python3 scripts/email_support_agent.py --oauth-graph")
                print("(Не закрывайте терминал до сообщения «Graph OAuth сохранён»)")
            return 0 if ready else 1
        if args.startup:
            n = startup_catchup(dry_run=args.dry_run, reprocess=args.reprocess)
            print(f"Startup catch-up done. Handled {n} message(s).")
        elif args.weekly:
            wait_for_services(dry_run=args.dry_run)
            sp = state_path()
            state = load_state(sp)
            if weekly_summary_due(state) or args.force_weekly:
                weekly_summary(dry_run=args.dry_run)
            else:
                print("Weekly summary: ещё не пора (используйте --force-weekly)")
        else:
            sp = state_path()
            state = load_state(sp)
            if args.retry_subject:
                n_forget = forget_messages_for_retry(state, subject_contains=args.retry_subject)
                save_state(sp, state)
                print(f"Retry subject «{args.retry_subject}»: сброшено {n_forget} писем")
            n = process_inbox(
                dry_run=args.dry_run,
                reprocess=args.reprocess,
                ignore_cooldown=bool(args.retry_subject),
            )
            print(f"Done. Handled {n} message(s). Mode={cfg('EMAIL_AGENT_MODE', 'auto')}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
