"""The house subject-line convention.

Every outgoing subject reads:

    [Bit68 - Acme Portal] - Release moved to Friday
    [Bit68 - Internal] - Offsite dates

The project slot carries the client or project name; internal mail uses the
literal word "Internal". Applying this in code rather than by habit means it
survives a rushed voice note.
"""

from __future__ import annotations

import os
import re

DEFAULT_ORG = "Bit68"
INTERNAL = "Internal"


def org_name() -> str:
    return os.environ.get("PMAIL_SUBJECT_ORG") or DEFAULT_ORG


def convention_enforced() -> bool:
    """On by default; set PMAIL_SUBJECT_CONVENTION=0 to allow free subjects."""
    return (os.environ.get("PMAIL_SUBJECT_CONVENTION") or "1").lower() not in {
        "0", "false", "no", "off",
    }


def pattern() -> re.Pattern[str]:
    return re.compile(rf"^\[{re.escape(org_name())} - .+\] - .+$")


def follows_convention(subject: str) -> bool:
    return bool(pattern().fullmatch(subject.strip()))


def project_of(subject: str) -> str:
    """The project slot of an already-formatted subject, or ''."""
    match = re.match(rf"^\[{re.escape(org_name())} - (?P<p>.+?)\] - ", subject.strip())
    return match.group("p") if match else ""


def title_of(subject: str) -> str:
    """The subject without its prefix, or the whole thing if unprefixed."""
    subject = subject.strip()
    match = re.match(rf"^\[{re.escape(org_name())} - .+?\] - (?P<t>.+)$", subject)
    return match.group("t") if match else subject


def format_subject(title: str, project: str | None = None, internal: bool = False) -> str:
    """Build a conventional subject. Idempotent — re-formatting is safe.

    An existing prefix is kept unless a new project is given explicitly, so
    editing a draft's title does not silently drop its project.
    """
    title = title.strip()
    existing = project_of(title)
    bare = title_of(title)

    if internal:
        slot = INTERNAL
    elif project:
        slot = project.strip()
    elif existing:
        slot = existing
    else:
        return bare  # Nothing to build from; validation flags it.

    return f"[{org_name()} - {slot}] - {bare}"


def explain() -> str:
    return (
        f"Subjects must read '[{org_name()} - <project>] - <title>', using "
        f"'{INTERNAL}' as the project for internal mail. Pass --project "
        "<name> or --internal when creating the draft."
    )
