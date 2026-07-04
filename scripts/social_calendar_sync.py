#!/usr/bin/env python3
"""Синхронизация расписания X @paper_wallet_co с Google Calendar (локальный ПК).

Один раз:
  1. Google Cloud Console → Calendar API → OAuth Desktop client → credentials.json
  2. bash scripts/setup_social_calendar.sh   # venv (Ubuntu PEP 668 — не pip в system)
  3. Скопируйте scripts/social_calendar.example.env → ~/.config/saylorwatch/social_calendar.env
  4. .venv-social/bin/python scripts/social_calendar_sync.py   # OAuth в браузере

Повторно (cron раз в неделю):
  .venv-social/bin/python scripts/social_calendar_sync.py --weeks 12
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    for env_path in (
        ROOT / ".env",
        Path.home() / ".config" / "saylorwatch" / "social_calendar.env",
    ):
        if env_path.is_file():
            load_dotenv(env_path, override=False)
except ImportError:
    pass

from social_schedule import CALENDAR_EVENT_PREFIX, ScheduledXPost, _tz, upcoming_x_posts

SCOPES = ["https://www.googleapis.com/auth/calendar"]
PROP_SOURCE = "saylorwatch_social"
PROP_DATE = "post_date"


def _credentials_path() -> Path:
    raw = os.environ.get("GOOGLE_CALENDAR_CREDENTIALS", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "saylorwatch" / "google_credentials.json"


def _token_path() -> Path:
    raw = os.environ.get("GOOGLE_CALENDAR_TOKEN", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".config" / "saylorwatch" / "google_token.json"


def _calendar_id() -> str:
    return os.environ.get("GOOGLE_CALENDAR_ID", "primary").strip() or "primary"


def _post_hour() -> int:
    return int(os.environ.get("SOCIAL_X_POST_HOUR", "11"))


def get_calendar_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit(
            "Run once: bash scripts/setup_social_calendar.sh\n"
            "Then: .venv-social/bin/python scripts/social_calendar_sync.py\n"
            f"Missing: {exc.name}"
        ) from exc

    creds_path = _credentials_path()
    token_path = _token_path()
    if not creds_path.is_file():
        raise SystemExit(
            f"Missing OAuth credentials: {creds_path}\n"
            "Download Desktop OAuth JSON from Google Cloud Console (Calendar API enabled)."
        )

    creds = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")

    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _event_body(post: ScheduledXPost) -> dict:
    tz = _tz()
    hour = _post_hour()
    start_dt = datetime.combine(post.post_date, datetime.min.time()).replace(
        hour=hour, minute=0, tzinfo=tz
    )
    end_dt = start_dt + timedelta(minutes=30)
    description = (
        f"{post.body}\n\n"
        f"---\n"
        f"Image: {post.image_hint}\n"
        f"Bot: /share x paper_wallet {post.variant}\n"
        f"Variant: {post.variant}"
    )
    return {
        "summary": post.title,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": str(tz)},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": str(tz)},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 24 * 60},
                {"method": "popup", "minutes": 120},
                {"method": "email", "minutes": 24 * 60},
            ],
        },
        "extendedProperties": {
            "private": {
                PROP_SOURCE: "paper_wallet",
                PROP_DATE: post.post_date.isoformat(),
                "variant": post.variant,
            }
        },
    }


def _list_managed_events(service) -> dict[str, dict]:
    """post_date ISO → event dict."""
    time_min = (datetime.now(_tz()) - timedelta(days=7)).isoformat()
    time_max = (datetime.now(_tz()) + timedelta(days=120)).isoformat()
    result: dict[str, dict] = {}
    page_token = None
    while True:
        resp = (
            service.events()
            .list(
                calendarId=_calendar_id(),
                timeMin=time_min,
                timeMax=time_max,
                privateExtendedProperty=f"{PROP_SOURCE}=paper_wallet",
                singleEvents=True,
                maxResults=250,
                pageToken=page_token,
            )
            .execute()
        )
        for item in resp.get("items", []):
            props = item.get("extendedProperties", {}).get("private", {})
            day = props.get(PROP_DATE)
            if day:
                result[day] = item
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return result


def sync_calendar(*, weeks: int = 8, dry_run: bool = False) -> None:
    posts = upcoming_x_posts(count=max(4, weeks * 2))
    service = None if dry_run else get_calendar_service()
    existing = {} if dry_run else _list_managed_events(service)
    cal_id = _calendar_id()

    created = updated = deleted = 0
    desired_dates = {p.post_date.isoformat() for p in posts}

    for post in posts:
        key = post.post_date.isoformat()
        body = _event_body(post)
        if key in existing:
            ev = existing[key]
            ev_id = ev["id"]
            if dry_run:
                print(f"UPDATE {key} {post.variant}")
                updated += 1
            else:
                service.events().patch(calendarId=cal_id, eventId=ev_id, body=body).execute()
                updated += 1
        else:
            if dry_run:
                print(f"CREATE {key} {post.variant} — {post.title}")
                created += 1
            else:
                service.events().insert(calendarId=cal_id, body=body).execute()
                created += 1

    for day, ev in existing.items():
        if day not in desired_dates:
            if dry_run:
                print(f"DELETE {day} {ev.get('summary', '')}")
                deleted += 1
            else:
                service.events().delete(calendarId=cal_id, eventId=ev["id"]).execute()
                deleted += 1

    print(
        f"Done: +{created} ~{updated} -{deleted} "
        f"({len(posts)} slots, calendar={cal_id}, prefix={CALENDAR_EVENT_PREFIX})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync X post schedule → Google Calendar")
    parser.add_argument("--weeks", type=int, default=8, help="How many weeks ahead to sync")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without API calls")
    args = parser.parse_args()
    sync_calendar(weeks=args.weeks, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
