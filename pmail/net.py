"""Reachability probes.

Cloud sessions (Claude Code on the web) run behind an egress proxy: raw TCP
is not routed at all, and HTTPS only reaches allowlisted hosts. Without these
probes a misconfigured environment shows up as a 30-second hang, which tells
nobody anything. These turn it into a sentence that names the fix.
"""

from __future__ import annotations

import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import Config

PROBE_TIMEOUT = 8


@dataclass
class Probe:
    ok: bool
    summary: str
    hint: str = ""


def _in_sandbox() -> bool:
    return bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))


def probe_smtp(config: Config) -> Probe:
    """Can we open a TCP socket to the SMTP host at all?"""
    try:
        socket.create_connection(
            (config.smtp_host, config.smtp_port), timeout=PROBE_TIMEOUT
        ).close()
        return Probe(True, f"{config.smtp_host}:{config.smtp_port} reachable")
    except (socket.timeout, TimeoutError):
        hint = (
            "Raw SMTP is not routed out of a Claude Code cloud session — only "
            "HTTPS goes through the egress proxy, so no allowlist entry fixes "
            "this. Use PMAIL_TRANSPORT=api from a cloud session, or run pmail "
            "from your own machine where SMTP works normally."
            if _in_sandbox()
            else "The connection timed out. A firewall is likely blocking "
            "outbound SMTP on this port; try 587 instead of 465."
        )
        return Probe(False, f"{config.smtp_host}:{config.smtp_port} timed out", hint)
    except OSError as exc:
        return Probe(False, f"{config.smtp_host}:{config.smtp_port} → {exc}")


def probe_api(config: Config) -> Probe:
    """Can we reach the OAuth host over HTTPS?"""
    url = f"{config.accounts_base}/oauth/v2/token"
    request = urllib.request.Request(url, data=b"", method="POST")
    try:
        urllib.request.urlopen(request, timeout=PROBE_TIMEOUT)
        return Probe(True, f"{config.accounts_base} reachable")
    except urllib.error.HTTPError:
        # Any HTTP status means the host answered: the network path is open.
        return Probe(True, f"{config.accounts_base} reachable")
    except urllib.error.URLError as exc:
        reason = str(getattr(exc, "reason", exc))
        blocked = "403" in reason or "tunnel" in reason.lower() or "forbidden" in reason.lower()
        hint = ""
        if _in_sandbox() and (blocked or "timed out" in reason.lower()):
            hint = (
                "The egress proxy refused this host. In the environment "
                "selector at claude.ai/code, edit the environment, set "
                "Network access to Custom, and add these to Allowed domains:\n"
                f"        mail.{config.api_base.split('mail.', 1)[-1]}\n"
                f"        accounts.{config.accounts_base.split('accounts.', 1)[-1]}\n"
                "      Then start a NEW session — running sessions keep the "
                "settings they started with."
            )
        return Probe(False, f"{config.accounts_base} → {reason}", hint)


def probe(config: Config) -> Probe:
    return probe_smtp(config) if config.transport == "smtp" else probe_api(config)
