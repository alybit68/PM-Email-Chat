"""Draft storage: every send goes through a reviewable file on disk.

A draft is created from a voice note, shown to a human, and only then sent.
Keeping drafts as plain JSON means the approval step is inspectable and a
mis-heard recipient can be corrected by editing one file.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import REPO_ROOT
from .errors import PmailError
from .message import Message


def drafts_dir() -> Path:
    path = Path(os.environ.get("PMAIL_DRAFTS") or REPO_ROOT / "drafts")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    """Sortable, collision-resistant, and short enough to retype."""
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M") + "-" + secrets.token_hex(2)


@dataclass
class Draft:
    id: str = field(default_factory=new_id)
    status: str = "draft"  # draft | sent | cancelled
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    transcript: str = ""
    note: str = ""
    message: Message = field(default_factory=Message)
    sent: dict = field(default_factory=dict)

    # ---- persistence ------------------------------------------------------

    @property
    def path(self) -> Path:
        return drafts_dir() / f"{self.id}.json"

    def save(self) -> Path:
        self.updated_at = _now()
        payload = asdict(self)
        payload["message"] = asdict(self.message)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return self.path

    @classmethod
    def load(cls, draft_id: str) -> "Draft":
        path = drafts_dir() / f"{draft_id}.json"
        if not path.is_file():
            # Allow a unique prefix so "2026" style typos are forgiving.
            matches = sorted(drafts_dir().glob(f"{draft_id}*.json"))
            if len(matches) == 1:
                path = matches[0]
            elif not matches:
                raise PmailError(
                    f"No draft {draft_id!r}. List them with: python3 -m pmail draft list"
                )
            else:
                names = ", ".join(p.stem for p in matches)
                raise PmailError(f"{draft_id!r} matches several drafts: {names}")

        data = json.loads(path.read_text(encoding="utf-8"))
        message_data = data.pop("message", {}) or {}
        known = Message.__dataclass_fields__.keys()
        message = Message(**{k: v for k, v in message_data.items() if k in known})
        fields = cls.__dataclass_fields__.keys()
        return cls(message=message, **{k: v for k, v in data.items() if k in fields})

    @classmethod
    def all(cls) -> list["Draft"]:
        drafts = []
        for path in sorted(drafts_dir().glob("*.json"), reverse=True):
            try:
                drafts.append(cls.load(path.stem))
            except (PmailError, json.JSONDecodeError, TypeError):
                continue  # A malformed file should not break `draft list`.
        return drafts

    # ---- state ------------------------------------------------------------

    def mark_sent(self, transport: str, detail: str = "") -> None:
        self.status = "sent"
        self.sent = {
            "at": _now(),
            "transport": transport,
            "detail": detail,
            "recipients": [*self.message.to, *self.message.cc, *self.message.bcc],
        }
        self.save()

    def summary(self) -> str:
        flag = {"draft": "·", "sent": "✓", "cancelled": "✗"}.get(self.status, "?")
        subject = self.message.subject or "(no subject)"
        to = ", ".join(self.message.to) or "(no recipients)"
        return f"{flag} {self.id}  {subject[:44]:<44}  → {to[:40]}"
