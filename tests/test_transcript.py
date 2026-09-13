import unittest

from pmail.transcript import normalise_spoken_addresses, parse


class TestTranscriptParsing(unittest.TestCase):
    def test_simple_send_to(self):
        p = parse("Send an email to Sara letting them know the build is green.")
        self.assertEqual(p.to, ["Sara"])

    def test_multiple_recipients_and_a_group(self):
        p = parse("Send an email to Sara and the dev team about the release.")
        self.assertEqual(p.to, ["Sara", "dev team"])

    def test_that_clause_does_not_swallow_the_recipient(self):
        self.assertEqual(parse("Email Sara that the release slipped.").to, ["Sara"])

    def test_let_know_phrasing(self):
        p = parse("Let Sara know that the release slipped to Friday.")
        self.assertEqual(p.to, ["Sara"])

    def test_tell_about_phrasing_expands_a_group(self):
        p = parse("Tell the dev team about the outage, and cc finance.")
        self.assertEqual(p.to, ["dev team"])
        self.assertIn("finance", p.cc)

    def test_shoot_an_email_phrasing(self):
        self.assertEqual(parse("Shoot Raj an email saying it is due Monday.").to, ["Raj"])

    def test_notify_multiple_people(self):
        self.assertEqual(parse("Notify Sara and Raj that the build is green.").to,
                         ["Sara", "Raj"])

    def test_pronoun_only_recipient_is_not_guessed(self):
        # "them" is not a routable recipient; the CLI must ask.
        self.assertTrue(parse("Tell them that the build broke.").is_empty())

    def test_cc_is_not_duplicated_into_to(self):
        p = parse("Email Sara and Raj about the outage, cc finance.")
        self.assertIn("finance", p.cc)
        self.assertNotIn("finance", p.to)

    def test_loop_in_phrasing_is_cc(self):
        p = parse("Write to Sara about the invoice, and keep Dan in the loop.")
        self.assertIn("Dan", p.cc)

    def test_bcc_is_detected(self):
        p = parse("Email Sara about payroll, bcc legal.")
        self.assertIn("legal", p.bcc)

    def test_spoken_address_is_normalised(self):
        self.assertEqual(
            normalise_spoken_addresses("raj at acme dot com"), "raj@acme.com"
        )
        self.assertEqual(
            normalise_spoken_addresses("raj at mail dot acme dot com"),
            "raj@mail.acme.com",
        )

    def test_address_is_not_truncated_at_the_domain_dot(self):
        p = parse("Email raj at acme dot com, saying the numbers are due Monday.")
        self.assertEqual(p.to, ["raj@acme.com"])

    def test_subject_stops_before_dictation(self):
        p = parse(
            "Email Sara, subject line Q3 budget review, saying we need "
            "the numbers by Monday."
        )
        self.assertEqual(p.subject_hint, "Q3 budget review")

    def test_body_hint_excludes_trailing_routing(self):
        p = parse("Email Sara saying the deploy is delayed. CC John please.")
        self.assertEqual(p.body_hint, "the deploy is delayed")
        self.assertIn("John", p.cc)

    def test_urgency_is_flagged(self):
        self.assertTrue(parse("Email Sara, it's urgent.").urgent)
        self.assertFalse(parse("Email Sara when you can.").urgent)

    def test_header_style_transcript(self):
        p = parse("To: ops-team. Subject: Incident postmortem. "
                  "Body: the root cause was a bad config push.")
        self.assertEqual(p.to, ["ops-team"])
        self.assertEqual(p.subject_hint, "Incident postmortem")
        self.assertEqual(p.body_hint, "the root cause was a bad config push.")

    def test_run_on_clause_is_not_mistaken_for_a_name(self):
        p = parse("Send an email to the whole engineering leadership group today.")
        self.assertNotIn(
            "whole engineering leadership group today", [t.lower() for t in p.to]
        )

    def test_empty_input_is_safe(self):
        p = parse("")
        self.assertTrue(p.is_empty())
        self.assertEqual(p.text, "")

    def test_no_recipients_detected_is_reported(self):
        self.assertTrue(parse("Remind me to call the bank tomorrow.").is_empty())

    def test_literal_addresses_are_collected(self):
        p = parse("Email Sara and finance@acme.com about the invoice.")
        self.assertIn("finance@acme.com", p.literal_addresses)


if __name__ == "__main__":
    unittest.main()
