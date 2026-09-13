import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from pmail import audit, cli
from pmail.drafts import Draft

from .helpers import TempEnv


def run(*argv) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestCli(TempEnv):
    def new_draft(self, *extra) -> str:
        code, out, _ = run(
            "draft", "new",
            "--vn", "Email Sara and Raj about the release, cc finance.",
            "--subject", "Release moved", "--project", "Oakwood",
            "--body", "It slipped to Friday.",
            *extra,
        )
        self.assertEqual(code, 0, out)
        return Draft.all()[0].id

    def test_doctor_reports_ready_configuration(self):
        code, out, _ = run("doctor")
        self.assertEqual(code, 0)
        self.assertIn("credentials present", out)
        self.assertIn("LOCKED", out)

    def test_doctor_flags_missing_credentials(self):
        del os.environ["ZOHO_APP_PASSWORD"]
        code, out, _ = run("doctor")
        self.assertEqual(code, 1)
        self.assertIn("ZOHO_APP_PASSWORD", out)

    def test_parse_resolves_names_to_addresses(self):
        code, out, _ = run("parse", "--vn", "Email Sara and Raj, cc finance.")
        self.assertEqual(code, 0)
        self.assertIn("sara@example.com", out)
        self.assertIn("finance@example.com", out)

    def test_draft_new_routes_from_the_voice_note(self):
        draft = Draft.load(self.new_draft())
        self.assertEqual(
            {r.split("<")[-1].rstrip(">") for r in draft.message.to},
            {"sara@example.com", "raj@example.com"},
        )
        self.assertIn("finance@example.com", draft.message.cc[0])

    def test_draft_new_warns_about_someone_named_but_not_routed(self):
        _, out, _ = run("draft", "new", "--vn", "Email Sara. Raj should know too.",
                        "--to", "sara", "--subject", "S", "--body", "B")
        self.assertIn("Raj Patel", out)
        self.assertIn("not a recipient", out)

    def test_send_without_confirm_is_a_dry_run(self):
        draft_id = self.new_draft()
        with mock.patch("pmail.cli.dispatch") as dispatch:
            code, out, _ = run("send", draft_id)
        dispatch.assert_not_called()
        self.assertEqual(code, 0)
        self.assertIn("DRY RUN", out)

    def test_send_with_confirm_but_switch_off_is_blocked(self):
        draft_id = self.new_draft()
        with mock.patch("pmail.cli.dispatch") as dispatch:
            code, _, err = run("send", draft_id, "--confirm")
        dispatch.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("PMAIL_ALLOW_SEND", err)

    def test_send_with_both_unlocks_sends_once_and_is_logged(self):
        draft_id = self.new_draft()
        os.environ["PMAIL_ALLOW_SEND"] = "1"
        with mock.patch("pmail.cli.dispatch", return_value="smtp ok") as dispatch:
            code, out, _ = run("send", draft_id, "--confirm")
        dispatch.assert_called_once()
        self.assertEqual(code, 0)
        self.assertIn("Sent.", out)
        self.assertEqual(Draft.load(draft_id).status, "sent")
        self.assertEqual(audit.tail()[0]["subject"],
                         "[Bit68 - Oakwood] - Release moved")

    def test_resending_needs_an_explicit_flag(self):
        draft_id = self.new_draft()
        os.environ["PMAIL_ALLOW_SEND"] = "1"
        with mock.patch("pmail.cli.dispatch", return_value="ok"):
            run("send", draft_id, "--confirm")
            code, _, err = run("send", draft_id, "--confirm")
            self.assertEqual(code, 1)
            self.assertIn("already sent", err)
            code, _, _ = run("send", draft_id, "--confirm", "--resend")
            self.assertEqual(code, 0)

    def test_invalid_message_is_refused_even_when_unlocked(self):
        _, out, _ = run("draft", "new", "--vn", "Email Sara.", "--to", "sara",
                        "--subject", "", "--body", "")
        draft_id = Draft.all()[0].id
        os.environ["PMAIL_ALLOW_SEND"] = "1"
        with mock.patch("pmail.cli.dispatch") as dispatch:
            code, _, err = run("send", draft_id, "--confirm")
        dispatch.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("Refusing to send", err)

    def test_cancelled_draft_cannot_be_sent(self):
        draft_id = self.new_draft()
        run("draft", "cancel", draft_id)
        os.environ["PMAIL_ALLOW_SEND"] = "1"
        with mock.patch("pmail.cli.dispatch") as dispatch:
            code, _, err = run("send", draft_id, "--confirm")
        dispatch.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("cancelled", err)

    def test_draft_edit_changes_recipients(self):
        draft_id = self.new_draft()
        code, _, _ = run("draft", "edit", draft_id, "--to", "sam",
                         "--subject", "New subject")
        self.assertEqual(code, 0)
        draft = Draft.load(draft_id)
        # Editing the title keeps the project the draft already carried.
        self.assertEqual(draft.message.subject, "[Bit68 - Oakwood] - New subject")
        self.assertIn("sam@example.com", draft.message.to[0])

    def test_draft_edit_rejects_an_unknown_recipient(self):
        draft_id = self.new_draft()
        code, _, err = run("draft", "edit", draft_id, "--to", "Bartholomew")
        self.assertEqual(code, 1)
        self.assertIn("No contact", err)

    def test_contacts_add_and_list(self):
        code, _, _ = run("contacts", "add", "--key", "dana", "--name", "Dana Lee",
                         "--email", "dana@example.com", "--groups", "leads")
        self.assertEqual(code, 0)
        _, out, _ = run("contacts", "list")
        self.assertIn("dana@example.com", out)
        self.assertIn("leads", out)

    def test_contacts_add_refuses_to_clobber_without_force(self):
        code, _, err = run("contacts", "add", "--key", "sara",
                           "--email", "other@example.com")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def test_history_lists_sends(self):
        draft_id = self.new_draft()
        os.environ["PMAIL_ALLOW_SEND"] = "1"
        with mock.patch("pmail.cli.dispatch", return_value="ok"):
            run("send", draft_id, "--confirm")
        _, out, _ = run("history")
        self.assertIn("Release moved", out)


if __name__ == "__main__":
    unittest.main()
