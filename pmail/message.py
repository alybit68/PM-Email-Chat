"""Building and validating the outgoing message."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from pathlib import Path

from .config import Config
from .contacts import EMAIL_RE
from .subject import (
    convention_enforced,
    follows_convention,
    explain as explain_subject,
)
from .errors import SendBlocked


def address_of(entry: str) -> str:
    """Bare address from either 'Name <a@b.c>' or 'a@b.c'."""
    return parseaddr(entry)[1] or entry.strip()


def domain_of(entry: str) -> str:
    _, _, domain = address_of(entry).rpartition("@")
    return domain.lower()


@dataclass
class Message:
    subject: str = ""
    body: str = ""
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    reply_to: str = ""
    html: str = ""
    attachments: list[str] = field(default_factory=list)
    urgent: bool = False

    @property
    def all_recipients(self) -> list[str]:
        return [*self.to, *self.cc, *self.bcc]

    def validate(self, config: Config) -> list[str]:
        """Return every problem with this message, worst first.

        Collecting rather than raising lets the CLI show a full picture of what
        needs fixing before anything is sent.
        """
        problems: list[str] = []

        if not self.to:
            problems.append("No To: recipient.")
        if not self.subject.strip():
            problems.append("Subject is empty.")
        elif convention_enforced() and not follows_convention(self.subject):
            problems.append(
                f"Subject {self.subject!r} does not follow the house format. "
                + explain_subject()
            )
        if not self.body.strip() and not self.html.strip():
            problems.append("Body is empty.")

        for entry in self.all_recipients:
            addr = address_of(entry)
            if not EMAIL_RE.fullmatch(addr):
                problems.append(f"{entry!r} is not a valid email address.")

        # Header injection: a newline smuggled into a header would let a
        # mis-transcribed voice note add its own recipients.
        for label, value in (
            ("subject", self.subject),
            ("reply-to", self.reply_to),
            *[("recipient", r) for r in self.all_recipients],
        ):
            if "\n" in value or "\r" in value:
                problems.append(f"Newline in {label} — refusing to build headers.")

        count = len(self.all_recipients)
        if count > config.max_recipients:
            problems.append(
                f"{count} recipients exceeds PMAIL_MAX_RECIPIENTS={config.max_recipients}."
            )

        if config.allowed_domains:
            for entry in self.all_recipients:
                if domain_of(entry) not in config.allowed_domains:
                    problems.append(
                        f"{address_of(entry)} is outside PMAIL_ALLOWED_DOMAINS "
                        f"({', '.join(config.allowed_domains)})."
                    )

        for raw in self.attachments:
            if not Path(raw).is_file():
                problems.append(f"Attachment not found: {raw}")

        return problems

    def require_valid(self, config: Config) -> None:
        if problems := self.validate(config):
            raise SendBlocked(
                "Refusing to send:\n  - " + "\n  - ".join(problems)
            )

    def to_mime(self, config: Config) -> EmailMessage:
        """Render to a MIME message ready for SMTP."""
        mime = EmailMessage()
        mime["From"] = formataddr((config.from_name or "", config.email))
        mime["To"] = ", ".join(self.to)
        if self.cc:
            mime["Cc"] = ", ".join(self.cc)
        # Bcc is intentionally not written as a header; it is passed to the
        # server as an envelope recipient only.
        mime["Subject"] = self.subject
        mime["Date"] = formatdate(localtime=True)
        mime["Message-ID"] = make_msgid(domain=domain_of(config.email) or None)
        if self.reply_to:
            mime["Reply-To"] = self.reply_to
        if self.urgent:
            mime["X-Priority"] = "1"
            mime["Importance"] = "high"

        mime.set_content(self.body)
        if self.html:
            mime.add_alternative(self.html, subtype="html")

        for raw in self.attachments:
            path = Path(raw)
            guessed, _ = mimetypes.guess_type(path.name)
            maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
            mime.add_attachment(
                path.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )

        return mime

    def preview(self, config: Config) -> str:
        """Human-readable rendering used for the approval step."""
        lines = [
            f"From:    {formataddr((config.from_name or '', config.email))}",
            f"To:      {', '.join(self.to) or '(none)'}",
        ]
        if self.cc:
            lines.append(f"Cc:      {', '.join(self.cc)}")
        if self.bcc:
            lines.append(f"Bcc:     {', '.join(self.bcc)}")
        if self.reply_to:
            lines.append(f"Reply-To:{self.reply_to}")
        lines.append(f"Subject: {self.subject}")
        if self.urgent:
            lines.append("Priority: high")
        if self.attachments:
            lines.append(f"Attach:  {', '.join(self.attachments)}")
        lines.append("-" * 60)
        lines.append(self.body.rstrip())
        return "\n".join(lines)
