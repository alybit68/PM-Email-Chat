import os
import unittest

from pmail.config import Config
from pmail.message import Message
from pmail.subject import (
    follows_convention,
    format_subject,
    project_of,
    title_of,
)
from pmail.transcript import parse

from .helpers import TempEnv


class TestSubjectConvention(TempEnv):
    def test_project_subject(self):
        self.assertEqual(
            format_subject("Release moved to Friday", project="Oakwood"),
            "[Bit68 - Oakwood] - Release moved to Friday",
        )

    def test_internal_subject(self):
        self.assertEqual(
            format_subject("Offsite dates", internal=True),
            "[Bit68 - Internal] - Offsite dates",
        )

    def test_internal_wins_over_a_project(self):
        self.assertEqual(
            format_subject("Offsite", project="Oakwood", internal=True),
            "[Bit68 - Internal] - Offsite",
        )

    def test_formatting_is_idempotent(self):
        once = format_subject("Release moved", project="Oakwood")
        self.assertEqual(format_subject(once, project="Oakwood"), once)
        self.assertEqual(format_subject(once), once)

    def test_reformatting_can_change_the_project(self):
        once = format_subject("Release moved", project="Oakwood")
        self.assertEqual(
            format_subject(once, project="Marina Bay"),
            "[Bit68 - Marina Bay] - Release moved",
        )

    def test_title_without_a_project_stays_bare(self):
        self.assertEqual(format_subject("Just a title"), "Just a title")

    def test_parts_are_recoverable(self):
        subject = "[Bit68 - Marina Bay] - Invoice query"
        self.assertEqual(project_of(subject), "Marina Bay")
        self.assertEqual(title_of(subject), "Invoice query")

    def test_title_of_an_unprefixed_subject_is_itself(self):
        self.assertEqual(title_of("Invoice query"), "Invoice query")

    def test_recognises_conforming_and_rejects_the_rest(self):
        self.assertTrue(follows_convention("[Bit68 - Internal] - Offsite"))
        self.assertTrue(follows_convention("[Bit68 - Acme Ltd] - Hello there"))
        for bad in ("Offsite", "[Bit68] - Offsite", "[Bit68 - Internal] Offsite",
                    "[Other - Internal] - Offsite", "[Bit68 - Internal] - "):
            self.assertFalse(follows_convention(bad), bad)

    def test_org_name_is_configurable(self):
        os.environ["PMAIL_SUBJECT_ORG"] = "Acme"
        self.assertEqual(format_subject("Hi", internal=True), "[Acme - Internal] - Hi")

    def test_a_nonconforming_subject_blocks_the_send(self):
        message = Message(subject="Bare subject", body="x", to=["a@b.com"])
        problems = message.validate(Config.load())
        self.assertTrue(any("house format" in p for p in problems))

    def test_a_conforming_subject_passes(self):
        message = Message(subject="[Bit68 - Oakwood] - Release moved",
                          body="x", to=["a@b.com"])
        self.assertEqual(message.validate(Config.load()), [])

    def test_the_convention_can_be_switched_off(self):
        os.environ["PMAIL_SUBJECT_CONVENTION"] = "0"
        message = Message(subject="Bare subject", body="x", to=["a@b.com"])
        self.assertEqual(message.validate(Config.load()), [])

    def test_an_empty_subject_reports_emptiness_not_the_format(self):
        problems = Message(subject="  ", body="x", to=["a@b.com"]).validate(Config.load())
        self.assertEqual(len(problems), 1)
        self.assertIn("empty", problems[0])


class TestInternalDetection(unittest.TestCase):
    def test_internal_is_read_from_the_voice_note(self):
        for text in ("Send an internal note to Sara about the offsite.",
                     "Email the team internally about Friday.",
                     "This is in-house, email Sara about it."):
            self.assertTrue(parse(text).internal, text)

    def test_client_facing_notes_are_not_internal(self):
        self.assertFalse(parse("Email Sara at the client about Friday.").internal)


if __name__ == "__main__":
    unittest.main()
