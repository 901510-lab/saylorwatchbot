#!/usr/bin/env python3
"""Быстрая проверка критичных модулей без Telegram API."""
from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

FAILURES: list[str] = []


def ok(name: str) -> None:
    print(f"  OK  {name}")


def fail(name: str, detail: str) -> None:
    FAILURES.append(f"{name}: {detail}")
    print(f"  FAIL {name}: {detail}")


def test_imports() -> None:
    modules = [
        "alert_delivery",
        "free_tier_perks",
        "user_lang_prefs",
        "subscribers",
        "subscription_reminders",
        "founding_promo",
        "social_growth",
        "entities",
        "i18n",
    ]
    optional = ["main", "subscription_payments", "weekly_digest", "whales"]
    for mod in modules:
        try:
            __import__(mod)
            ok(f"import {mod}")
        except Exception as exc:
            fail(f"import {mod}", str(exc))
    for mod in optional:
        try:
            __import__(mod)
            ok(f"import {mod}")
        except ImportError as exc:
            print(f"  SKIP import {mod} ({exc.name})")
        except Exception as exc:
            fail(f"import {mod}", str(exc))


def test_i18n_templates() -> None:
    from i18n import SUPPORTED_LANGS, t

    keys = [
        "premium_expiry_reminder",
        "founding_promo_offer",
        "founding_promo_confirm",
        "subscribe_btn_founding",
        "subscribe_offer_pay_hint",
        "free_weekly_title",
        "free_weekly_premium_hint",
    ]
    for lang in SUPPORTED_LANGS:
        for key in keys:
            try:
                t(
                    lang,
                    key,
                    days=3,
                    date="2027-01-01",
                    remaining=99,
                    max_slots=100,
                    next_slot=1,
                    price=7,
                    stars=350,
                    premium_top=10,
                    period="Jun 10–16",
                )
                ok(f"i18n {lang}/{key}")
            except Exception as exc:
                fail(f"i18n {lang}/{key}", str(exc))


def test_subscribers_expiry() -> None:
    from subscribers import Subscriber, calendar_days_until_expiry, expiry_date_label
    from subscription_plans import PlanId

    now = datetime.datetime(2026, 6, 14, 12, 0, tzinfo=datetime.UTC)
    sub = Subscriber(
        user_id=42,
        plan=PlanId.PREMIUM,
        expires_at="2026-06-17T10:00:00+00:00",
    )
    days = calendar_days_until_expiry(sub, now=now)
    if days != 3:
        fail("calendar_days_until_expiry", f"expected 3 got {days}")
    else:
        ok("calendar_days_until_expiry")
    if expiry_date_label(sub) != "2026-06-17":
        fail("expiry_date_label", expiry_date_label(sub) or "None")
    else:
        ok("expiry_date_label")


def test_founding_promo(tmp: Path) -> None:
    import founding_promo as fp
    import subscribers as subs

    fp.FOUNDING_PROMO_FILE = tmp / "founding_promo.json"
    subs.SUBSCRIBERS_FILE = tmp / "subscribers.json"
    fp.FOUNDING_PROMO_ENABLED = True
    fp.FOUNDING_PROMO_MAX = 100

    assert fp.promo_active()
    assert fp.eligible_for_founding(999001)
    result = fp.try_claim_founding_premium(999001)
    if result.status != "ok" or result.slot != 1:
        fail("founding claim", result.status)
    else:
        ok("founding claim")
    if fp.eligible_for_founding(999001):
        fail("founding eligible after claim", "still eligible")
    else:
        ok("founding not eligible after claim")


def test_reminders_state(tmp: Path) -> None:
    import subscription_reminders as sr
    from subscribers import Subscriber
    from subscription_plans import PlanId

    sr.STATE_FILE = tmp / "reminders.json"
    sr.ADMIN_CHAT_ID = "1"
    sr.REMINDER_DAYS_BEFORE = (3, 2, 1)

    sub = Subscriber(user_id=2, plan=PlanId.PREMIUM, expires_at="2026-06-17T00:00:00+00:00")
    from subscribers import calendar_days_until_expiry

    now = datetime.datetime(2026, 6, 14, 15, 0, tzinfo=datetime.UTC)
    days = calendar_days_until_expiry(sub, now=now)
    if days != 3:
        fail("reminder days_left", str(days))
    else:
        ok("reminder days_left=3")
    assert not sr._reminder_sent(2, "2026-06-17", 3)
    sr._mark_reminder_sent(2, "2026-06-17", 3)
    assert sr._reminder_sent(2, "2026-06-17", 3)
    ok("reminder idempotency")


def test_free_tier_perks(tmp: Path) -> None:
    import free_tier_perks as ftp
    from subscription_plans import PlanId

    ftp.PERKS_FILE = tmp / "free_tier_perks.json"
    ftp.FREE_WEEKLY_STRATEGY_CARDS = 1
    ftp.FREE_CARD_LARGE_BTC = 100.0

    assert ftp.free_strategy_card_allowed(
        42, entity_id="strategy", abs_delta_btc=10.0, plan=PlanId.FREE
    )
    ftp.record_free_strategy_card(42, abs_delta_btc=10.0)
    assert not ftp.free_strategy_card_allowed(
        42, entity_id="strategy", abs_delta_btc=10.0, plan=PlanId.FREE
    )
    assert ftp.free_strategy_card_allowed(
        42, entity_id="strategy", abs_delta_btc=150.0, plan=PlanId.FREE
    )
    ok("free_tier_perks weekly limit + large trade bypass")


def test_alert_gating() -> None:
    from alert_delivery import _allowed_for_plan, gating_enabled, resolve_recipients
    from subscription_plans import PlanId

    ok(f"gating_enabled={gating_enabled()}")
    if not _allowed_for_plan("strategy", PlanId.FREE, site_monitor=False):
        fail("free strategy", "blocked")
    else:
        ok("free gets strategy")
    if _allowed_for_plan("tesla", PlanId.FREE, site_monitor=False):
        fail("free tesla", "allowed")
    else:
        ok("free blocked tesla")
    recips = resolve_recipients("strategy", admin_user_id=1, site_monitor=False)
    if not recips or recips[0].user_id != 1:
        fail("resolve_recipients admin", str(recips))
    else:
        ok("resolve_recipients admin")


def test_social_growth() -> None:
    from social_growth import POST_KINDS, format_share_message, render_x_post

    for kind in POST_KINDS:
        if kind == "reddit_comment":
            text = format_share_message("reddit", kind)
        else:
            text = format_share_message("x", kind) if kind != "announce" else render_x_post(kind)
        if not text.strip():
            fail(f"social template {kind}", "empty")
        else:
            ok(f"social template {kind}")


def test_main_version() -> None:
    try:
        import main
    except ImportError as exc:
        print(f"  SKIP BOT_VERSION ({exc.name})")
        return
    ver = main.BOT_VERSION
    if not ver or "2026" not in ver:
        fail("BOT_VERSION", ver)
    else:
        ok(f"BOT_VERSION={ver}")


def main() -> int:
    print("SaylorWatchBot sanity check\n")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_imports()
        test_i18n_templates()
        test_subscribers_expiry()
        test_founding_promo(tmp)
        test_free_tier_perks(tmp)
        test_reminders_state(tmp)
        test_alert_gating()
        test_social_growth()
        test_main_version()

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}")
        for item in FAILURES:
            print(f"  - {item}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
