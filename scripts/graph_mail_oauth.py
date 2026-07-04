"""Microsoft Graph Mail.Send для личного @outlook.com.

SMTP на личных ящиках Microsoft часто заблокирован (SmtpClientAuthentication disabled).
Graph API с scope Mail.Send отправляет письма с того же адреса без SMTP.

Один раз: python3 scripts/email_support_agent.py --oauth-graph
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from outlook_oauth import load_tokens, save_tokens, token_file_path

# Microsoft Office (публичный desktop client, device code flow)
DEFAULT_GRAPH_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
GRAPH_AUTHORITY = "https://login.microsoftonline.com/consumers"
DEFAULT_GRAPH_SCOPES = (
    "https://graph.microsoft.com/Mail.Send "
    "https://graph.microsoft.com/Mail.Read "
    "offline_access"
)
DEVICE_CODE_URL = f"{GRAPH_AUTHORITY}/oauth2/v2.0/devicecode"
TOKEN_URL = f"{GRAPH_AUTHORITY}/oauth2/v2.0/token"
SEND_MAIL_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
INBOX_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
GRAPH_MAIL_FOLDERS: dict[str, str] = {
    "inbox": "inbox",
    "junkemail": "junkemail",
    "junk": "junkemail",
}


def _http_form(url: str, fields: dict[str, str], *, allow_oauth_pending: bool = False) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(detail)
        except json.JSONDecodeError:
            data = {}
        if allow_oauth_pending and data.get("error") in {
            "authorization_pending",
            "slow_down",
        }:
            return data
        raise RuntimeError(f"Graph OAuth error ({exc.code}): {detail}") from exc


def _graph_get(url: str, access_token: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph API ({exc.code}): {detail}") from exc


def _store_graph_tokens(data: dict, *, path: Path, mail_user: str) -> dict:
    now = int(time.time())
    expires_in = int(data.get("expires_in", 3600))
    stored = {
        "mail_user": mail_user,
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_at": now + expires_in,
        "scope": data.get("scope", ""),
        "token_type": data.get("token_type", "Bearer"),
    }
    if not stored["refresh_token"]:
        prev = load_tokens(path)
        if prev and prev.get("refresh_token"):
            stored["refresh_token"] = prev["refresh_token"]
    save_tokens(path, stored)
    return stored


def device_code_login(
    *,
    mail_user: str,
    client_id: str,
    scopes: str,
    token_path: Path,
) -> dict:
    dc = _http_form(
        DEVICE_CODE_URL,
        {"client_id": client_id, "scope": scopes},
    )
    if "device_code" not in dc:
        raise RuntimeError(f"Device code failed: {dc}")

    user_code = dc["user_code"]
    uri = dc.get("verification_uri") or dc.get("verification_uri_complete", "https://microsoft.com/devicelogin")
    interval = int(dc.get("interval", 5))
    expires_in = int(dc.get("expires_in", 900))
    device_code = dc["device_code"]

    print("Graph Mail.Send — OAuth2 (Microsoft)\n")
    print("1. Откройте:", uri)
    print("2. Введите код:", user_code)
    print("3. Войдите как", mail_user, "и разрешите доступ к почте.")
    print("4. **Не закрывайте терминал** — дождитесь «Graph OAuth сохранён».\n")
    print("Ожидание подтверждения", end="", flush=True)

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        data = _http_form(
            TOKEN_URL,
            {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id,
                "device_code": device_code,
            },
            allow_oauth_pending=True,
        )
        if "access_token" in data:
            print()
            stored = _store_graph_tokens(data, path=token_path, mail_user=mail_user)
            print("✅ Graph OAuth сохранён в", token_path)
            return stored
        err = data.get("error", "")
        if err == "authorization_pending":
            print(".", end="", flush=True)
            continue
        if err == "slow_down":
            interval += 5
            print(".", end="", flush=True)
            continue
        print()
        if err == "expired_token":
            raise RuntimeError("Код истёк — запустите --oauth-graph снова")
        raise RuntimeError(f"Graph OAuth: {data}")

    print()
    raise RuntimeError("Таймаут — не подтвердили вход в Microsoft")


def get_graph_access_token(
    *,
    mail_user: str,
    client_id: str,
    scopes: str,
    token_path: Path,
    refresh_skew: int = 300,
) -> str:
    tokens = load_tokens(token_path)
    if not tokens or not tokens.get("access_token"):
        raise RuntimeError(
            "Graph токен не найден. Запустите:\n"
            "  python3 scripts/email_support_agent.py --oauth-graph"
        )
    if tokens.get("mail_user", "").lower() != mail_user.lower():
        raise RuntimeError(
            f"Graph токен для {tokens.get('mail_user')}, а MAIL_USER={mail_user}. "
            "Повторите --oauth-graph."
        )
    now = int(time.time())
    if int(tokens.get("expires_at", 0)) - refresh_skew > now:
        return tokens["access_token"]
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise RuntimeError("Graph access_token истёк — повторите --oauth-graph")
    data = _http_form(
        TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh,
            "scope": scopes,
        },
    )
    if "access_token" not in data:
        raise RuntimeError(f"Graph refresh failed: {data}")
    stored = _store_graph_tokens(data, path=token_path, mail_user=mail_user)
    return stored["access_token"]


def send_mail(
    *,
    to: str,
    subject: str,
    body: str,
    mail_user: str,
    client_id: str,
    scopes: str,
    token_path: Path,
) -> None:
    access_token = get_graph_access_token(
        mail_user=mail_user,
        client_id=client_id,
        scopes=scopes,
        token_path=token_path,
    )
    stored = load_tokens(token_path) or {}
    scope = (stored.get("scope") or "").lower()
    if scope and "graph.microsoft.com" not in scope:
        raise RuntimeError(
            "Токен без Graph scope (это IMAP-токен). Запустите --oauth-graph."
        )

    subj = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    payload = {
        "message": {
            "subject": subj,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to}}],
        },
        "saveToSentItems": True,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        SEND_MAIL_URL,
        data=data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 202, 204):
                raise RuntimeError(f"Graph sendMail HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graph sendMail ({exc.code}): {detail}") from exc


def _message_body_text(msg: dict) -> str:
    body = msg.get("body") or {}
    content = (body.get("content") or "").strip()
    if content:
        if (body.get("contentType") or "").lower() == "html":
            content = _strip_html(content)
        return content[:8000]
    return (msg.get("bodyPreview") or "").strip()[:8000]


def _strip_html(raw: str) -> str:
    import html
    import re

    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+\n", "\n", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def fetch_folder_messages(
    *,
    folder: str,
    access_token: str,
    since_days: int = 14,
    since_datetime: datetime | None = None,
) -> list[dict]:
    folder_id = GRAPH_MAIL_FOLDERS.get(folder.lower(), folder)
    if since_datetime is not None:
        since = since_datetime.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        since = (datetime.now(UTC) - timedelta(days=since_days)).strftime("%Y-%m-%dT00:00:00Z")
    base_params = {
        "$filter": f"receivedDateTime ge {since}",
        "$orderby": "receivedDateTime asc",
        "$top": "100",
        "$select": "id,internetMessageId,subject,from,receivedDateTime,bodyPreview,body",
    }
    base_url = f"https://graph.microsoft.com/v1.0/me/mailFolders/{folder_id}/messages"
    url: str | None = f"{base_url}?{urllib.parse.urlencode(base_params)}"
    results: list[dict] = []
    while url:
        data = _graph_get(url, access_token)
        for msg in data.get("value") or []:
            from_obj = (msg.get("from") or {}).get("emailAddress") or {}
            from_email = from_obj.get("address") or ""
            from_name = from_obj.get("name") or ""
            from_hdr = f"{from_name} <{from_email}>" if from_name else from_email
            dt_raw = msg.get("receivedDateTime") or ""
            results.append(
                {
                    "uid": f"g:{msg.get('id', '')}",
                    "message_id": (msg.get("internetMessageId") or "").strip(),
                    "from": from_hdr,
                    "from_email": from_email,
                    "subject": msg.get("subject") or "(no subject)",
                    "date": dt_raw,
                    "body": _message_body_text(msg),
                    "folder": folder_id,
                }
            )
        url = data.get("@odata.nextLink")
    return results


def fetch_inbox_messages(
    *,
    mail_user: str,
    client_id: str,
    scopes: str,
    token_path: Path,
    since_days: int = 14,
    since_datetime: datetime | None = None,
    extra_folders: tuple[str, ...] = ("junkemail",),
) -> list[dict]:
    access_token = get_graph_access_token(
        mail_user=mail_user,
        client_id=client_id,
        scopes=scopes,
        token_path=token_path,
    )
    folders = ("inbox",) + tuple(f for f in extra_folders if f and f != "inbox")
    seen_mids: set[str] = set()
    results: list[dict] = []
    for folder in folders:
        batch = fetch_folder_messages(
            folder=folder,
            access_token=access_token,
            since_days=since_days,
            since_datetime=since_datetime,
        )
        for msg in batch:
            mid = (msg.get("message_id") or "").strip().lower()
            dedup = mid or msg["uid"]
            if dedup in seen_mids:
                continue
            seen_mids.add(dedup)
            results.append(msg)
    results.sort(key=lambda m: m.get("date") or "")
    return results
