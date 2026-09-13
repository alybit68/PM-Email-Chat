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


def exchange_code(config: Config, code: str) -> dict:
    """Trade a Self Client authorization code for a lasting refresh token.

    The code is single-use and expires in minutes, so the usual failure is
    simply being too slow; that gets its own message rather than Zoho's.
    """
    if not (config.client_id and config.client_secret):
        raise ConfigError(
            "ZOHO_CLIENT_ID and ZOHO_CLIENT_SECRET must be set before "
            "exchanging a code. Put them in your environment variables."
        )

    payload = _request(
        f"{config.accounts_base}/oauth/v2/token",
        method="POST",
        form={
            "code": code.strip(),
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "grant_type": "authorization_code",
        },
    )

    if refresh := payload.get("refresh_token"):
        return payload

    error = str(payload.get("error", payload))
    if "invalid_code" in error:
        raise SendFailed(
            "Zoho rejected the code as invalid. Authorization codes are "
            "single-use and expire in minutes — generate a fresh one in the "
            "API console and paste it straight away."
        )
    if "invalid_client" in error:
        raise SendFailed(
            "Zoho rejected the client id/secret. The usual cause is a region "
            f"mismatch: this tried {config.accounts_base}, so check that "
            "ZOHO_REGION matches the data centre the Self Client was created "
            "in."
        )
    raise SendFailed(f"Zoho did not return a refresh token: {error}")


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

    try:
        payload = _request(
            f"{config.api_base}/api/accounts/{account}/messages",
            method="POST",
            token=token,
            data=body,
        )
    except SendFailed as exc:
        raise _explain_send_failure(exc, config) from exc

    status = (payload.get("status") or {}).get("description", "sent")
    message_id = (payload.get("data") or {}).get("messageId", "")
    return f"api account={account} status={status} id={message_id}"


def _explain_send_failure(exc: SendFailed, config: Config) -> SendFailed:
    """Translate Zoho's mail-policy refusals into something actionable.

    Zoho reports an unvalidated From address as "Policy Violation in Subject",
    which sends you hunting through the subject line for a problem that is not
    there. The account API exposes the real cause as sendMailDetails.validated.
    """
    text = str(exc)
    if "5.7.7" not in text and "Policy Violation" not in text:
        return exc

    address = address_of(config.email)
    return SendFailed(
        f"Zoho refused the message with a policy violation. Despite the "
        f"wording, this is usually not about the subject line — it is "
        f"{address} not being validated as a send-from address.\n"
        "  Check, in order:\n"
        "    1. mailadmin.zoho.com -> Domains: is the domain verified, with "
        "MX, SPF and DKIM records all showing green?\n"
        "    2. Zoho Mail -> Settings -> Mail Accounts: does the From address "
        "show as verified?\n"
        "    3. A newly created organization can be outbound-restricted for "
        "the first day or so, and while a plan is mid-trial.\n"
        "  Nothing was sent, and nothing in this tool needs changing — the "
        "request reached Zoho and was refused at their mail-policy layer."
    )


def sending_is_validated(config: Config) -> tuple[bool, str]:
    """Whether Zoho considers the From address cleared to send."""
    token = access_token(config)
    account = account_id(config, token)
    payload = _request(f"{config.api_base}/api/accounts", token=token)

    wanted = address_of(config.email).lower()
    for entry in payload.get("data") or []:
        if str(entry.get("accountId")) != str(account):
            continue
        for detail in entry.get("sendMailDetails", []):
            if str(detail.get("fromAddress", "")).lower() == wanted:
                if detail.get("validated"):
                    return True, f"{wanted} is validated for sending"
                return False, (
                    f"{wanted} is NOT validated for sending — Zoho will refuse "
                    "messages with a misleading 'Policy Violation in Subject'. "
                    "Verify the domain and From address in the Zoho admin "
                    "console."
                )
    return False, f"{wanted} was not found among this account's send addresses"


def check_connection(config: Config) -> str:
    """Used by `doctor` — proves the token works without sending anything."""
    token = access_token(config)
    account = account_id(config, token)
    return f"token valid, accountId={account} on {config.api_base}"
