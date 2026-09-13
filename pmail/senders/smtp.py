"""Zoho Mail over SMTP.

Zoho exposes smtp.zoho.<tld> for free/personal mailboxes and smtppro.zoho.<tld>
for paid plans on a custom domain, on 465 (implicit SSL) or 587 (STARTTLS).
Authentication uses the mailbox address plus an app-specific password.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from pathlib import Path

from ..config import Config
from ..errors import SendFailed
from ..message import Message, address_of


def _ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    # Honour a corporate/proxy CA bundle when one is configured.
    bundle = os.environ.get("PMAIL_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if bundle and Path(bundle).is_file():
        context.load_verify_locations(bundle)
    return context


def connect(config: Config, timeout: int = 30) -> smtplib.SMTP:
    """Open an authenticated connection. Caller is responsible for quit()."""
    context = _ssl_context()
    try:
        if config.smtp_port == 465:
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                config.smtp_host, config.smtp_port, timeout=timeout, context=context
            )
        else:
            server = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=timeout)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
    except (OSError, smtplib.SMTPException) as exc:
        raise SendFailed(
            f"Could not reach {config.smtp_host}:{config.smtp_port} — {exc}. "
            "Check ZOHO_REGION/ZOHO_ACCOUNT_TYPE and that outbound SMTP is allowed."
        ) from exc

    try:
        server.login(config.email, config.app_password)
    except smtplib.SMTPAuthenticationError as exc:
        server.close()
        raise SendFailed(
            f"Zoho rejected the login for {config.email}: {exc.smtp_error.decode(errors='replace') if isinstance(exc.smtp_error, bytes) else exc.smtp_error}. "
            "With two-factor auth on, ZOHO_APP_PASSWORD must be an app-specific "
            "password (Zoho Mail → My Account → Security → App Passwords), not "
            "your login password."
        ) from exc
    except smtplib.SMTPException as exc:
        server.close()
        raise SendFailed(f"SMTP login failed: {exc}") from exc

    return server


def send_smtp(message: Message, config: Config) -> str:
    mime = message.to_mime(config)
    envelope = [address_of(r) for r in message.all_recipients]

    server = connect(config)
    try:
        refused = server.send_message(
            mime, from_addr=address_of(config.email), to_addrs=envelope
        )
    except smtplib.SMTPException as exc:
        raise SendFailed(f"Zoho refused the message: {exc}") from exc
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            server.close()

    if refused:
        raise SendFailed(
            "Some recipients were refused: "
            + ", ".join(f"{addr} ({code} {reason})" for addr, (code, reason) in refused.items())
        )

    return f"smtp {config.smtp_host}:{config.smtp_port} id={mime['Message-ID']}"


def check_connection(config: Config) -> str:
    """Used by `doctor` — authenticates then disconnects without sending."""
    server = connect(config, timeout=15)
    try:
        return f"authenticated as {config.email} on {config.smtp_host}:{config.smtp_port}"
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            server.close()
