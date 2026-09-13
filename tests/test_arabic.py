import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from pmail import cli
from pmail.contacts import AddressBook, Contact, normalise_handle
from pmail.drafts import Draft
from pmail.errors import ResolutionError
from pmail.transcript import parse

from .helpers import TempEnv

BOOK = {
    "contacts": [
        {"key": "sara-remax", "name": "Sara Diaz", "email": "sara@remax.example",
         "company": "RE/MAX", "company_aliases": ["ريماكس"], "aliases": ["سارة"]},
        {"key": "rami", "name": "Rami Fouad", "email": "rami@bit68.com",
         "company": "Bit68", "company_aliases": ["بت68"], "aliases": ["رامي"]},
    ],
    "groups": {},
}


class TestArabicNormalisation(unittest.TestCase):
    def test_arabic_survives_normalisation(self):
        self.assertEqual(normalise_handle("سارة"), "سارة")

    def test_arabic_connectors_are_dropped(self):
        self.assertEqual(normalise_handle("سارة من ريماكس"), "سارة ريماكس")
        self.assertEqual(normalise_handle("رامي في بت68"), "رامي بت68")

    def test_arabic_indic_digits_fold_to_ascii(self):
        self.assertEqual(normalise_handle("بت٦٨"), "بت68")

    def test_punctuation_still_collapses(self):
        self.assertEqual(normalise_handle("ريـ/ماكس"), "ريـماكس")


class TestBilingualResolution(TempEnv):
    book = BOOK

    def setUp(self):
        super().setUp()
        self.addresses = AddressBook.load()

    def test_same_person_in_either_language(self):
        for token in ("Sara from RE/MAX", "سارة من ريماكس", "سارة ريماكس",
                      "سارة", "sara from remax"):
            self.assertEqual(
                self.addresses.resolve(token)[0].email, "sara@remax.example", token
            )

    def test_arabic_indic_digits_in_a_company_name(self):
        for token in ("رامي من بت٦٨", "رامي من بت68", "Rami from Bit68"):
            self.assertEqual(
                self.addresses.resolve(token)[0].email, "rami@bit68.com", token
            )

    def test_arabic_company_name_addresses_everyone_there(self):
        self.assertEqual(
            [c.email for c in self.addresses.resolve("ريماكس")],
            ["sara@remax.example"],
        )

    def test_an_unknown_arabic_name_is_refused_not_guessed(self):
        with self.assertRaises(ResolutionError):
            self.addresses.resolve("خالد")

    def test_company_aliases_survive_a_save_and_load(self):
        path = self.tmp / "out.json"
        self.addresses.save(path)
        reloaded = AddressBook.load(path)
        self.assertEqual(reloaded.by_key("sara-remax").company_aliases, ("ريماكس",))


class TestArabicTranscript(unittest.TestCase):
    def test_arabic_is_detected(self):
        self.assertTrue(parse("ابعت إيميل لسارة").arabic)
        self.assertFalse(parse("Email Sara about it.").arabic)

    def test_unparsed_arabic_is_flagged_for_manual_routing(self):
        parsed = parse("ابعت إيميل لسارة إن الديلفري اتأجل للجمعة")
        self.assertTrue(parsed.needs_manual_routing)

    def test_english_notes_are_never_flagged(self):
        self.assertFalse(parse("Email Sara about it.").needs_manual_routing)
        # Even an English note naming nobody is not a translation failure.
        self.assertFalse(parse("Remind me to call the bank.").needs_manual_routing)

    def test_arabic_urgency_is_detected(self):
        for text in ("ابعت لسارة، الموضوع مستعجل", "ده ضروري وعاجل",
                     "محتاج الرد في أسرع وقت"):
            self.assertTrue(parse(text).urgent, text)

    def test_arabic_internal_is_detected(self):
        for text in ("ابعت إيميل داخلي للفريق", "ده إيميل داخلي"):
            self.assertTrue(parse(text).internal, text)

    def test_a_client_facing_arabic_note_is_not_internal(self):
        self.assertFalse(parse("ابعت إيميل للعميل عن الموضوع ده").internal)


class TestArabicDraftWarning(TempEnv):
    book = BOOK

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_arabic_note_without_explicit_recipients_warns_loudly(self):
        _, out, _ = self.run_cli(
            "draft", "new", "--vn", "ابعت إيميل لسارة إن الديلفري اتأجل",
            "--subject", "Delivery delayed", "--internal", "--body", "Body.",
        )
        self.assertIn("in Arabic", out)
        self.assertIn("--to explicitly", out)

    def test_arabic_note_with_explicit_recipients_does_not_warn(self):
        _, out, _ = self.run_cli(
            "draft", "new", "--vn", "ابعت إيميل لسارة إن الديلفري اتأجل",
            "--to", "sara-remax", "--project", "Oakwood",
            "--subject", "Delivery delayed", "--body", "Body.",
        )
        self.assertNotIn("in Arabic", out)
        self.assertIn("sara@remax.example", out)

    def test_the_arabic_original_is_kept_on_the_draft(self):
        arabic = "ابعت إيميل لسارة إن الديلفري اتأجل للجمعة"
        self.run_cli("draft", "new", "--vn", arabic, "--to", "sara-remax",
                     "--project", "Oakwood", "--subject", "Delivery delayed",
                     "--body", "Body.")
        # The English email is auditable against what was actually said.
        self.assertEqual(Draft.all()[0].transcript, arabic)


if __name__ == "__main__":
    unittest.main()
