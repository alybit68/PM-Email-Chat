"""Transports that put a message on the wire."""

from __future__ import annotations

from ..config import Config
from ..errors import ConfigError
from ..message import Message


def send(message: Message, config: Config) -> str:
    """Dispatch to the configured transport. Returns a detail string."""
    if config.transport == "smtp":
        from .smtp import send_smtp

        return send_smtp(message, config)
    if config.transport == "api":
        from .zoho_api import send_api

        return send_api(message, config)
    raise ConfigError(f"Unknown PMAIL_TRANSPORT {config.transport!r}; use smtp or api.")
