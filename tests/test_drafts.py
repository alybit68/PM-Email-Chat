import unittest

from pmail import audit
from pmail.drafts import Draft
from pmail.errors import PmailError
from pmail.message import Message

from .helpers import TempEnv


class TestDrafts(TempEnv):
    def make(self, **kwargs) -> Draft:
        message = Message(
            subject=kwargs.pop("subject", "Release moved"),
            body="Body text",
            to=["Sara <sara@example.com>"],
            cc=kwargs.pop("cc", []),
        )
        draft = Draft(transcript="Email Sara about the release.", message=message)
        draft.save()
        return draft

    def test_roundtrip_preserves_the_message(self):
        draft = self.make(cc=["raj@example.com"])
        loaded = Draft.load(draft.id)
        self.assertEqual(loaded.message.subject, "Release moved")
        self.assertEqual(loaded.message.cc, ["raj@example.com"])
        self.assertEqual(loaded.transcript, draft.transcript)

    def test_ids_are_unique(self):
        self.assertNotEqual(self.make().id, self.make().id)

    def test_load_accepts_a_unique_prefix(self):
        draft = self.make()
        self.assertEqual(Draft.load(draft.id[:13]).id, draft.id)

    def test_unknown_id_raises(self):
        with self.assertRaises(PmailError):
            Draft.load("nope")

    def test_list_is_newest_first(self):
        first, second = self.make(), self.make()
        ids = [d.id for d in Draft.all()]
        self.assertEqual(ids.index(second.id) < ids.index(first.id), second.id > first.id)

    def test_malformed_file_does_not_break_listing(self):
        self.make()
        (self.tmp / "drafts" / "broken.json").write_text("{oops", encoding="utf-8")
        self.assertEqual(len(Draft.all()), 1)

    def test_mark_sent_records_recipients(self):
        draft = self.make(cc=["raj@example.com"])
        draft.mark_sent("smtp", "id=<abc@example.com>")
        loaded = Draft.load(draft.id)
        self.assertEqual(loaded.status, "sent")
        self.assertIn("raj@example.com", loaded.sent["recipients"])


class TestAudit(TempEnv):
    def test_record_appends_one_line_per_send(self):
        message = Message(subject="Hi", body="x", to=["Sara <sara@example.com>"],
                          bcc=["legal@example.com"])
        audit.record("d1", message, "smtp", "ok", "Email Sara.")
        audit.record("d2", message, "smtp", "ok", "Email Sara again.")
        entries = audit.tail()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["draft_id"], "d1")
        self.assertEqual(entries[0]["to"], ["sara@example.com"])
        self.assertEqual(entries[0]["bcc"], ["legal@example.com"])

    def test_transcript_is_truncated(self):
        message = Message(subject="Hi", body="x", to=["sara@example.com"])
        audit.record("d1", message, "smtp", "ok", "y" * 1000)
        self.assertEqual(len(audit.tail()[0]["transcript_excerpt"]), 280)

    def test_tail_on_missing_log_is_empty(self):
        self.assertEqual(audit.tail(), [])


if __name__ == "__main__":
    unittest.main()
