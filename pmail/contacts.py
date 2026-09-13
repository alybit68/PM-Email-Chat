"""The address book that turns names heard in a voice note into addresses.

This file is the reason the workflow is safe to automate: an email address is
only ever used if a human put it in contacts.json. Nothing guesses addresses.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import REPO_ROOT
from .errors import ResolutionError

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Words that join a person to their company in speech: "Sara from RE/MAX",
# "Raj at Century 21". They carry no identity, so they are dropped before
# matching and a spoken "Sara from RE/MAX" lines up with the stored contact.
_CONNECTORS = {
    "from", "at", "of", "with", "in", "the", "our", "my",
    # Arabic equivalents, so "سارة من ريماكس" matches the same contact as
    # "Sara from RE/MAX".
    "من", "في", "عند", "بتاع", "بتاعة", "بتاعت", "لدى", "ال",
}

# Arabic-Indic digits, so "بت٦٨" and "بت68" are the same company.
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def normalise_handle(value: str) -> str:
    """Lowercase, strip punctuation, drop connector words.

    "RE/MAX" and "remax" and "Re-Max" all collapse to the same key, which is
    what makes a dictated company name usable as a lookup.
    """
    cleaned = re.sub(r"[^\w\s]", "", value.lower().translate(_ARABIC_DIGITS))
    return " ".join(w for w in cleaned.split() if w not in _CONNECTORS)


def contacts_path() -> Path:
    return Path(os.environ.get("PMAIL_CONTACTS") or REPO_ROOT / "contacts.json")


@dataclass(frozen=True)
class Contact:
    key: str
    name: str
    email: str
    company: str = ""
    company_aliases: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    notes: str = ""

    @property
    def display(self) -> str:
        return f"{self.name} <{self.email}>" if self.name else self.email

    @property
    def label(self) -> str:
        """Display name with the company, for disambiguating in previews."""
        if self.company and self.name:
            return f"{self.name} ({self.company}) <{self.email}>"
        return self.display

    def handles(self) -> set[str]:
        """Every normalised string that should resolve to this contact.

        Includes company-qualified forms, so two people called Sara at
        different firms stay distinguishable when a voice note says
        "Sara from RE/MAX".
        """
        plain = {self.key, self.email, *self.aliases}
        if self.name:
            plain.add(self.name)
            plain.add(self.name.split()[0])

        parts = {normalise_handle(p) for p in plain}

        # Every spelling of the company, so a note in either language lands on
        # the same person: "Sara from RE/MAX" and "سارة من ريماكس".
        for spelling in (self.company, *self.company_aliases):
            company = normalise_handle(spelling)
            if not company:
                continue
            parts.update(f"{normalise_handle(p)} {company}" for p in plain if p)

        return {p for p in parts if p}


DEFAULT_COMMENT = (
    "Your address book. Claude only ever emails addresses that appear in this "
    "file, so nothing is guessed from a voice note. Edit by hand or with "
    "`python3 -m pmail contacts add`. Commit it — the container is wiped "
    "between sessions."
)


@dataclass
class AddressBook:
    contacts: list[Contact] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)
    comment: str = DEFAULT_COMMENT

    # ---- persistence ------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "AddressBook":
        path = path or contacts_path()
        if not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))

        contacts = [
            Contact(
                key=c["key"],
                name=c.get("name", ""),
                email=c["email"],
                company=c.get("company", ""),
                company_aliases=tuple(c.get("company_aliases", ())),
                aliases=tuple(c.get("aliases", ())),
                groups=tuple(c.get("groups", ())),
                notes=c.get("notes", ""),
            )
            for c in data.get("contacts", [])
        ]

        groups: dict[str, list[str]] = {
            name: list(spec.get("members", [])) if isinstance(spec, dict) else list(spec)
            for name, spec in data.get("groups", {}).items()
        }
        # A contact may also declare its own groups; merge those in.
        for contact in contacts:
            for group in contact.groups:
                members = groups.setdefault(group, [])
                if contact.key not in members:
                    members.append(contact.key)

        return cls(
            contacts=contacts,
            groups=groups,
            comment=data.get("_comment") or DEFAULT_COMMENT,
        )

    def save(self, path: Path | None = None) -> Path:
        path = path or contacts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict = {"_comment": self.comment} if self.comment else {}
        payload |= {
            "contacts": [
                {
                    k: v
                    for k, v in {
                        "key": c.key,
                        "name": c.name,
                        "email": c.email,
                        "company": c.company,
                        "company_aliases": list(c.company_aliases),
                        "aliases": list(c.aliases),
                        "groups": list(c.groups),
                        "notes": c.notes,
                    }.items()
                    if v
                }
                for c in sorted(self.contacts, key=lambda c: c.key)
            ],
            "groups": {
                name: {"members": sorted(members)}
                for name, members in sorted(self.groups.items())
                if name not in {g for c in self.contacts for g in c.groups}
            },
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return path

    # ---- lookup -----------------------------------------------------------

    def by_key(self, key: str) -> Contact | None:
        key = key.lower()
        return next((c for c in self.contacts if c.key.lower() == key), None)

    def group_members(self, name: str) -> list[Contact]:
        members = self.groups.get(name) or self.groups.get(name.lower())
        if members is None:
            lowered = {g.lower(): g for g in self.groups}
            if name.lower() in lowered:
                members = self.groups[lowered[name.lower()]]
        if members is None:
            return []
        return [c for key in members if (c := self.by_key(key))]

    def resolve(self, token: str) -> list[Contact]:
        """Resolve one token (a name, key, alias, group, or literal address).

        Raises ResolutionError with candidates when the token is ambiguous or
        unknown, so the caller can put the choice back to a human.
        """
        token = token.strip().strip(",.;:").strip()
        if not token:
            return []

        # A literal address the speaker spelled out: accept it as-is, but prefer
        # the address-book entry so we keep the display name.
        if EMAIL_RE.fullmatch(token):
            known = next(
                (c for c in self.contacts if c.email.lower() == token.lower()), None
            )
            return [known or Contact(key=token, name="", email=token)]

        if members := self.group_members(token):
            return members

        needle = normalise_handle(token)
        matches = [c for c in self.contacts if needle in c.handles()]
        if len(matches) == 1:
            return matches

        if not matches:
            # A bare company name addresses everyone there, like a group.
            if company := self.by_company(token):
                return company

        if not matches:
            # Fall back to a prefix match on name/key so "Sam" finds "Samuel".
            matches = [
                c
                for c in self.contacts
                if any(h.startswith(needle) for h in c.handles())
            ]

        if len(matches) == 1:
            return matches
        if not matches:
            raise ResolutionError(
                f"No contact, group, or address matches {token!r}. "
                "I will not guess an address — tell me theirs and I will save it: "
                "python3 -m pmail contacts add --key <handle> --email <address>"
            )
        raise ResolutionError(
            f"{token!r} is ambiguous — matches "
            + ", ".join(f"{c.key} ({c.label})" for c in matches)
            + ". Say which one, or use the contact key."
        )

    def by_company(self, name: str) -> list[Contact]:
        """Everyone at a company. Lets a note say 'send it to RE/MAX'."""
        needle = normalise_handle(name)
        if not needle:
            return []
        return [
            c
            for c in self.contacts
            if needle
            in {normalise_handle(s) for s in (c.company, *c.company_aliases) if s}
        ]

    def resolve_all(self, tokens: list[str]) -> tuple[list[Contact], list[str]]:
        """Resolve many tokens, de-duplicating by address.

        Returns (contacts, problems) rather than raising, so the CLI can show
        every unresolved name at once instead of one per run.
        """
        found: dict[str, Contact] = {}
        problems: list[str] = []
        for token in tokens:
            try:
                for contact in self.resolve(token):
                    found.setdefault(contact.email.lower(), contact)
            except ResolutionError as exc:
                problems.append(str(exc))
        return list(found.values()), problems

    def mentioned_in(self, text: str) -> list[Contact]:
        """Every contact or group whose handle appears in free text.

        Used to sanity-check a transcript: if the speaker names someone we did
        not route the mail to, the CLI surfaces it before anything is sent.
        """
        lowered = normalise_handle(text)
        hits: dict[str, Contact] = {}

        for group in self.groups:
            handle = normalise_handle(group)
            if handle and re.search(rf"\b{re.escape(handle)}\b", lowered):
                for contact in self.group_members(group):
                    hits.setdefault(contact.email.lower(), contact)

        # Match each contact on its most specific handle. Single-word handles
        # need a word boundary so "sam" does not match "same".
        best: dict[str, tuple[Contact, tuple[int, int]]] = {}
        for contact in self.contacts:
            for handle in sorted(contact.handles(), key=len, reverse=True):
                if match := re.search(rf"\b{re.escape(handle)}\b", lowered):
                    best[contact.email.lower()] = (contact, match.span())
                    break

        for email, (contact, span) in best.items():
            # A bare "sara" sitting inside "sara remax" is that person, not
            # every other Sara in the book — otherwise the not-routed warning
            # fires for someone who was never mentioned.
            shadowed = any(
                other != email
                and other_span[0] <= span[0]
                and span[1] <= other_span[1]
                and other_span[1] - other_span[0] > span[1] - span[0]
                for other, (_, other_span) in best.items()
            )
            if not shadowed:
                hits.setdefault(email, contact)

        return list(hits.values())
