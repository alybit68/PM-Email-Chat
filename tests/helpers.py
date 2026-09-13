"""Shared fixtures: an isolated address book and draft directory per test."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

BOOK = {
    "contacts": [
        {"key": "sara", "name": "Sara Diaz", "email": "sara@example.com",
         "aliases": ["sara d"], "groups": ["dev-team"]},
        {"key": "raj", "name": "Raj Patel", "email": "raj@example.com",
         "groups": ["dev-team"]},
        {"key": "sam", "name": "Samuel Okoro", "email": "sam@example.com"},
        {"key": "finance", "name": "Finance Inbox", "email": "finance@example.com",
         "aliases": ["accounts"]},
    ],
    "groups": {"dev-team": {"members": ["sara", "raj"]}},
}


class TempEnv(unittest.TestCase):
    """Points PMAIL_* at a scratch directory and restores the environment."""

    book = BOOK

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._saved = dict(os.environ)

        contacts = self.tmp / "contacts.json"
        contacts.write_text(json.dumps(self.book), encoding="utf-8")

        for key in list(os.environ):
            if key.startswith(("PMAIL_", "ZOHO_")):
                del os.environ[key]

        os.environ["PMAIL_CONTACTS"] = str(contacts)
        os.environ["PMAIL_DRAFTS"] = str(self.tmp / "drafts")
        os.environ["PMAIL_HISTORY"] = str(self.tmp / "history" / "sent.jsonl")
        os.environ["ZOHO_EMAIL"] = "me@example.com"
        os.environ["ZOHO_FROM_NAME"] = "Me"
        os.environ["ZOHO_APP_PASSWORD"] = "test-password"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._saved)
        self._tmp.cleanup()
