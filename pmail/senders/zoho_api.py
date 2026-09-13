"""Zoho Mail over the REST API (OAuth 2.0).

An alternative to SMTP for accounts where SMTP is disabled or where you would
rather grant a scoped token than an app password. Needs a Self Client from
https://api-console.zoho.com with scopes:
    ZohoMail.messages.CREATE,ZohoMail.accounts.READ

Stdlib only: urllib honours HTTPS_PROXY from the environment automatically.
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..config import Config
from ..errors import ConfigError, SendFailed
from ..message import Message, address_of

_TIMEOUT = 30


def _context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    bundle = os.environ.get("PMAIL_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if bundle and Path(bundle).is_file():
        context.load_verify_locations(bundle)
    return context


def _request(url: str, *, method: str = "GET", token: str = "", data: dict | None = None,
             form: dict | None = None) -> dict:
    if form is not None:
        payload = urllib.parse.urlencode(form).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
    elif data is not None:
        payload = json.dumps(data).encode()
        headers = {"Content-Type": "application/json"}
    else:
        payload, headers = None, {}

    if token:
        headers["Authorization"] = f"Zoho-oauthtoken {token}"

    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT, context=_context()) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:600]
        raise SendFailed(f"Zoho API {method} {url} → HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SendFailed(f"Could not reach {url}: {exc.reason}") from exc

    try:
        return json.loads(body) if body.strip() else {}
    except json.JSONDecodeError as exc:
        raise SendFailed(f"Zoho API returned non-JSON: {body[:300]}") from exc


def access_token(config: Config) -> str:
    """Exchange the long-lived refresh token for a short-lived access token."""
    if not config.refresh_token:
        raise ConfigError("ZOHO_REFRESH_TOKEN is not set.")

    payload = _request(
        f"{config.accounts_base}/oauth/v2/token",
        method="POST",
        form={
            "refresh_token": config.refresh_token,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "grant_type": "refresh_token",
        },
    )
    token = payload.get("access_token")
    if not token:
        raise SendFailed(
            "Zoho did not return an access token: "
            f"{payload.get('error', payload)}. Re-issue the refresh token and "
            "confirm ZOHO_REGION matches the data centre it was created in."
        )
    return token


def account_id(config: Config, token: str) -> str:
    """The numeric account id the send endpoint is keyed on."""
    if config.account_id:
        return config.account_id

    payload = _request(f"{config.api_base}/api/accounts", token=token)
    accounts = payload.get("data") or []
    if not accounts:
        raise SendFailed("Zoho returned no accounts for this token.")

    wanted = address_of(config.email).lower()
    for account in accounts:
        addresses = {
            str(entry.get("mailId", "")).lower()
            for entry in account.get("emailAddress", [])
        }
        if wanted in addresses or str(account.get("primaryEmailAddress", "")).lower() == wanted:
            return str(account["accountId"])

    # Fall back to the first account rather than failing outright, but say so.
    return str(accounts[0]["accountId"])


def send_api(message: Message, config: Config) -> str:
    if message.attachments:
        raise SendFailed(
            "The API transport does not upload attachments. Set "
            "PMAIL_TRANSPORT=smtp to send this message with its attachments."
        )

    token = access_token(config)
    account = account_id(config, token)

    body = {
        "fromAddress": address_of(config.email),
        "toAddress": ",".join(address_of(r) for r in message.to),
        "subject": message.subject,
        "content": message.html or message.body,
        "mailFormat": "html" if message.html else "plaintext",
    }
    if message.cc:
        body["ccAddress"] = ",".join(address_of(r) for r in message.cc)
    if message.bcc:
        body["bccAddress"] = ",".join(address_of(r) for r in message.bcc)
    if message.reply_to:
        body["replyTo"] = address_of(message.reply_to)

    payload = _request(
        f"{config.api_base}/api/accounts/{account}/messages",
        method="POST",
        token=token,
        data=body,
    )

    status = (payload.get("status") or {}).get("description", "sent")
    message_id = (payload.get("data") or {}).get("messageId", "")
    return f"api account={account} status={status} id={message_id}"


def check_connection(config: Config) -> str:
    """Used by `doctor` — proves the token works without sending anything."""
    token = access_token(config)
    account = account_id(config, token)
    return f"token valid, accountId={account} on {config.api_base}"
