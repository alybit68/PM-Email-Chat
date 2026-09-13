"""Configuration loading for Zoho Mail.

Values come from the process environment, with a .env file in the repo root as
a fallback so local runs and Claude Code web sessions behave the same way.
Real credentials only ever live in the environment or in a gitignored .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent

# Zoho runs independent data centres; the hostname suffix differs per region.
REGION_TLDS = {
    "us": "zoho.com",
    "eu": "zoho.eu",
    "in": "zoho.in",
    "au": "zoho.com.au",
    "jp": "zoho.jp",
    "ca": "zoho.ca",
    "sa": "zoho.sa",
}

# The API and OAuth hosts do not always match the SMTP suffix (Canada notably).
REGION_API_TLDS = dict(REGION_TLDS, ca="zohocloud.ca")

TRUTHY = {"1", "true", "yes", "y", "on"}


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Parse a .env file into a dict. Returns {} when the file is absent.

    Deliberately minimal: KEY=VALUE per line, # comments, optional quotes. We
    avoid a dependency so the tool runs in a bare container with no install.
    """
    path = path or REPO_ROOT / ".env"
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _env(overlay: dict[str, str], key: str, default: str = "") -> str:
    """Process environment wins over .env, which wins over the default."""
    return os.environ.get(key) or overlay.get(key) or default


@dataclass
class Config:
    email: str = ""
    from_name: str = ""
    region: str = "us"
    account_type: str = "personal"
    transport: str = "smtp"

    smtp_host: str = ""
    smtp_port: int = 465
    app_password: str = ""

    client_id: str = ""
    client_secret: str = ""
    refresh_token: str = ""
    account_id: str = ""

    allow_send: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    max_recipients: int = 25

    @classmethod
    def load(cls, dotenv_path: Path | None = None) -> "Config":
        overlay = load_dotenv(dotenv_path)

        region = _env(overlay, "ZOHO_REGION", "us").lower().strip()
        if region not in REGION_TLDS:
            raise ConfigError(
                f"ZOHO_REGION={region!r} is not one of: {', '.join(sorted(REGION_TLDS))}"
            )

        account_type = _env(overlay, "ZOHO_ACCOUNT_TYPE", "personal").lower().strip()
        if account_type not in {"personal", "organization"}:
            raise ConfigError(
                "ZOHO_ACCOUNT_TYPE must be 'personal' or 'organization', "
                f"got {account_type!r}"
            )

        prefix = "smtppro" if account_type == "organization" else "smtp"
        default_host = f"{prefix}.{REGION_TLDS[region]}"

        try:
            port = int(_env(overlay, "ZOHO_SMTP_PORT", "465"))
        except ValueError as exc:
            raise ConfigError("ZOHO_SMTP_PORT must be an integer") from exc

        try:
            max_recipients = int(_env(overlay, "PMAIL_MAX_RECIPIENTS", "25"))
        except ValueError as exc:
            raise ConfigError("PMAIL_MAX_RECIPIENTS must be an integer") from exc

        domains = [
            d.strip().lower().lstrip("@")
            for d in _env(overlay, "PMAIL_ALLOWED_DOMAINS").split(",")
            if d.strip()
        ]

        return cls(
            email=_env(overlay, "ZOHO_EMAIL").strip(),
            from_name=_env(overlay, "ZOHO_FROM_NAME").strip(),
            region=region,
            account_type=account_type,
            transport=_env(overlay, "PMAIL_TRANSPORT", "smtp").lower().strip(),
            smtp_host=_env(overlay, "ZOHO_SMTP_HOST", default_host).strip(),
            smtp_port=port,
            app_password=_env(overlay, "ZOHO_APP_PASSWORD"),
            client_id=_env(overlay, "ZOHO_CLIENT_ID").strip(),
            client_secret=_env(overlay, "ZOHO_CLIENT_SECRET").strip(),
            refresh_token=_env(overlay, "ZOHO_REFRESH_TOKEN").strip(),
            account_id=_env(overlay, "ZOHO_ACCOUNT_ID").strip(),
            allow_send=_env(overlay, "PMAIL_ALLOW_SEND").lower() in TRUTHY,
            allowed_domains=domains,
            max_recipients=max_recipients,
        )

    @property
    def api_base(self) -> str:
        return f"https://mail.{REGION_API_TLDS[self.region]}"

    @property
    def accounts_base(self) -> str:
        return f"https://accounts.{REGION_API_TLDS[self.region]}"

    def missing_for_transport(self) -> list[str]:
        """Names of the settings still needed before this transport can send."""
        missing = []
        if not self.email:
            missing.append("ZOHO_EMAIL")
        if self.transport == "smtp":
            if not self.app_password:
                missing.append("ZOHO_APP_PASSWORD")
        elif self.transport == "api":
            for name, value in (
                ("ZOHO_CLIENT_ID", self.client_id),
                ("ZOHO_CLIENT_SECRET", self.client_secret),
                ("ZOHO_REFRESH_TOKEN", self.refresh_token),
            ):
                if not value:
                    missing.append(name)
        else:
            raise ConfigError(
                f"PMAIL_TRANSPORT must be 'smtp' or 'api', got {self.transport!r}"
            )
        return missing

    def require_ready(self) -> None:
        missing = self.missing_for_transport()
        if missing:
            raise ConfigError(
                "Missing configuration for the "
                f"{self.transport!r} transport: {', '.join(missing)}. "
                "See .env.example and run `python3 -m pmail doctor`."
            )
