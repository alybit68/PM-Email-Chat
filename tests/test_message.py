import unittest

from pmail.config import Config
from pmail.errors import SendBlocked
from pmail.message import Message, address_of, domain_of

from .helpers import TempEnv


class TestMessage(TempEnv):
    def setUp(self):
        super().setUp()
        self.config = Config.load()

    def valid(self, **kwargs) -> Message:
        base = dict(subject="Subject", body="Body", to=["Sara <sara@example.com>"])
        base.update(kwargs)
        return Message(**base)

    def test_valid_message_has_no_problems(self):
        self.assertEqual(self.valid().validate(self.config), [])

    def test_missing_pieces_are_all_reported(self):
        problems = Message().validate(self.config)
        self.assertEqual(len(problems), 3)  # no To, no subject, no body

    def test_newline_in_subject_is_refused(self):
        problems = self.valid(subject="Hi\nBcc: attacker@evil.com").validate(self.config)
        self.assertTrue(any("Newline" in p for p in problems))

    def test_newline_in_recipient_is_refused(self):
        problems = self.valid(to=["a@b.com\nBcc: x@y.com"]).validate(self.config)
        self.assertTrue(any("Newline" in p for p in problems))

    def test_invalid_address_is_refused(self):
        problems = self.valid(to=["not-an-address"]).validate(self.config)
        self.assertTrue(any("not a valid email" in p for p in problems))

    def test_domain_allowlist(self):
        self.config.allowed_domains = ["acme.com"]
        self.assertTrue(self.valid().validate(self.config))
        self.config.allowed_domains = ["example.com"]
        self.assertEqual(self.valid().validate(self.config), [])

    def test_recipient_cap(self):
        self.config.max_recipients = 2
        message = self.valid(to=[f"p{i}@example.com" for i in range(3)])
        self.assertTrue(any("exceeds" in p for p in message.validate(self.config)))

    def test_missing_attachment_is_reported(self):
        problems = self.valid(attachments=["/nope/missing.pdf"]).validate(self.config)
        self.assertTrue(any("Attachment not found" in p for p in problems))

    def test_require_valid_raises(self):
        with self.assertRaises(SendBlocked):
            Message().require_valid(self.config)

    def test_bcc_is_not_written_as_a_header(self):
        mime = self.valid(bcc=["secret@example.com"]).to_mime(self.config)
        self.assertIsNone(mime["Bcc"])
        self.assertNotIn("secret@example.com", str(mime))

    def test_cc_is_written_as_a_header(self):
        mime = self.valid(cc=["raj@example.com"]).to_mime(self.config)
        self.assertIn("raj@example.com", mime["Cc"])

    def test_urgent_sets_priority_headers(self):
        mime = self.valid(urgent=True).to_mime(self.config)
        self.assertEqual(mime["X-Priority"], "1")

    def test_html_alternative_is_attached(self):
        mime = self.valid(html="<p>Hi</p>").to_mime(self.config)
        self.assertTrue(mime.is_multipart())

    def test_attachment_is_embedded(self):
        path = self.tmp / "notes.txt"
        path.write_text("hello", encoding="utf-8")
        mime = self.valid(attachments=[str(path)]).to_mime(self.config)
        self.assertIn("notes.txt", str(mime))

    def test_from_header_uses_configured_identity(self):
        mime = self.valid().to_mime(self.config)
        self.assertEqual(mime["From"], "Me <me@example.com>")

    def test_address_helpers(self):
        self.assertEqual(address_of("Sara Diaz <sara@example.com>"), "sara@example.com")
        self.assertEqual(domain_of("Sara <sara@Example.COM>"), "example.com")

    def test_preview_hides_nothing_the_recipient_will_see(self):
        preview = self.valid(cc=["raj@example.com"]).preview(self.config)
        self.assertIn("raj@example.com", preview)
        self.assertIn("Subject", preview)


if __name__ == "__main__":
    unittest.main()
