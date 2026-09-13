"""Append-only record of everything that actually left the mailbox.

The container this runs in is ephemeral, so the log lives in the repo and is
committed. It is the answer to "what did it send while I wasn't looking".
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .config import REPO_ROOT
from .message import Message, address_of


def history_path() -> Path:
    path = Path(os.environ.get("PMAIL_HISTORY") or REPO_ROOT / "history" / "sent.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def record(
    draft_id: str,
    message: Message,
    transport: str,
    detail: str = "",
    transcript: str = "",
) -> Path:
    """Append one send to the history log.

    The transcript is truncated: the log is a routing audit trail, not an
    archive of everything ever dictated.
    """
    entry = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "draft_id": draft_id,
        "transport": transport,
        "detail": detail,
        "subject": message.subject,
        "to": [address_of(r) for r in message.to],
        "cc": [address_of(r) for r in message.cc],
        "bcc": [address_of(r) for r in message.bcc],
        "attachments": [Path(a).name for a in message.attachments],
        "transcript_excerpt": transcript[:280],
    }
    path = history_path()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path


def tail(limit: int = 20) -> list[dict]:
    path = history_path()
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries[-limit:]
