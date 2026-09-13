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


def contacts_path() -> Path:
    return Path(os.environ.get("PMAIL_CONTACTS") or REPO_ROOT / "contacts.json")


@dataclass(frozen=True)
class Contact:
    key: str
    name: str
    email: str
    aliases: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    notes: str = ""

    @property
    def display(self) -> str:
        return f"{self.name} <{self.email}>" if self.name else self.email

    def handles(self) -> set[str]:
        """Every string that should resolve to this contact, lowercased."""
        parts = {self.key.lower(), self.email.lower()}
        parts.update(a.lower() for a in self.aliases)
        if self.name:
            parts.add(self.name.lower())
            first = self.name.split()[0].lower()
            parts.add(first)
        return {p for p in parts if p}


@dataclass
class AddressBook:
    contacts: list[Contact] = field(default_factory=list)
    groups: dict[str, list[str]] = field(default_factory=dict)

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

        return cls(contacts=contacts, groups=groups)

    def save(self, path: Path | None = None) -> Path:
        path = path or contacts_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "contacts": [
                {
                    k: v
                    for k, v in {
                        "key": c.key,
                        "name": c.name,
                        "email": c.email,
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

        needle = token.lower()
        matches = [c for c in self.contacts if needle in c.handles()]
        if len(matches) == 1:
            return matches

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
                "Add them with: python3 -m pmail contacts add ..."
            )
        raise ResolutionError(
            f"{token!r} is ambiguous — matches "
            + ", ".join(f"{c.key} ({c.display})" for c in matches)
            + ". Use the contact key instead."
        )

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
        lowered = text.lower()
        hits: dict[str, Contact] = {}

        for group in self.groups:
            if re.search(rf"\b{re.escape(group.lower())}\b", lowered):
                for contact in self.group_members(group):
                    hits.setdefault(contact.email.lower(), contact)

        for contact in self.contacts:
            for handle in contact.handles():
                # Single-word handles need a word boundary; "sam" must not match
                # "same". Multi-word handles are distinctive enough as substrings.
                if re.search(rf"\b{re.escape(handle)}\b", lowered):
                    hits.setdefault(contact.email.lower(), contact)
                    break

        return list(hits.values())
