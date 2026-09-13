import unittest

from pmail.contacts import AddressBook, Contact, normalise_handle
from pmail.errors import ResolutionError

from .helpers import TempEnv


class TestAddressBook(TempEnv):
    def setUp(self):
        super().setUp()
        self.book = AddressBook.load()

    def test_resolve_by_key_alias_and_first_name(self):
        for token in ("sara", "Sara", "sara d", "Sara Diaz", "sara@example.com"):
            self.assertEqual(self.book.resolve(token)[0].email, "sara@example.com", token)

    def test_resolve_group_expands_to_members(self):
        emails = {c.email for c in self.book.resolve("dev-team")}
        self.assertEqual(emails, {"sara@example.com", "raj@example.com"})

    def test_unknown_name_raises_rather_than_guessing(self):
        with self.assertRaises(ResolutionError):
            self.book.resolve("Bartholomew")

    def test_literal_address_is_accepted(self):
        result = self.book.resolve("someone@elsewhere.org")
        self.assertEqual(result[0].email, "someone@elsewhere.org")

    def test_prefix_match_finds_longer_name(self):
        self.assertEqual(self.book.resolve("samuel")[0].email, "sam@example.com")

    def test_ambiguity_is_reported(self):
        self.book.contacts.append(
            type(self.book.contacts[0])(key="sara2", name="Sara Quinn",
                                        email="squinn@example.com")
        )
        with self.assertRaises(ResolutionError) as ctx:
            self.book.resolve("sara")
        self.assertIn("ambiguous", str(ctx.exception))

    def test_resolve_all_collects_problems_without_raising(self):
        contacts, problems = self.book.resolve_all(["sara", "Nobody", "raj"])
        self.assertEqual(len(contacts), 2)
        self.assertEqual(len(problems), 1)

    def test_resolve_all_deduplicates(self):
        contacts, _ = self.book.resolve_all(["sara", "dev-team", "sara@example.com"])
        self.assertEqual(len(contacts), 2)

    def test_mentioned_in_finds_names_in_prose(self):
        emails = {c.email for c in self.book.mentioned_in("Tell Sara and Raj about it.")}
        self.assertEqual(emails, {"sara@example.com", "raj@example.com"})

    def test_mentioned_in_respects_word_boundaries(self):
        # "sam" must not match inside "same".
        self.assertEqual(self.book.mentioned_in("It is the same thing."), [])

    def test_save_creates_missing_parent_directories(self):
        path = self.tmp / "nested" / "deeper" / "contacts.json"
        self.book.save(path)
        self.assertTrue(path.is_file())

    def test_normalise_handle_collapses_punctuation_and_connectors(self):
        for variant in ("RE/MAX", "re-max", "Re.Max", "  REMAX  "):
            self.assertEqual(normalise_handle(variant), "remax", variant)
        self.assertEqual(normalise_handle("Sara from RE/MAX"), "sara remax")
        self.assertEqual(normalise_handle("Sara at Re-Max"), "sara remax")

    def test_roundtrip_save_and_load(self):
        path = self.tmp / "out.json"
        self.book.save(path)
        reloaded = AddressBook.load(path)
        self.assertEqual(len(reloaded.contacts), len(self.book.contacts))
        self.assertEqual(
            {c.email for c in reloaded.group_members("dev-team")},
            {"sara@example.com", "raj@example.com"},
        )


class TestCompanyLookup(TempEnv):
    """Two people share a first name; the company tells them apart."""

    book = {
        "contacts": [
            {"key": "sara-remax", "name": "Sara Diaz", "company": "RE/MAX",
             "email": "sara.diaz@remax.com"},
            {"key": "sara-c21", "name": "Sara Kim", "company": "Century 21",
             "email": "sara.kim@century21.com"},
            {"key": "john-remax", "name": "John Ruiz", "company": "RE/MAX",
             "email": "john.ruiz@remax.com"},
        ],
        "groups": {},
    }

    def setUp(self):
        super().setUp()
        self.book = AddressBook.load()

    def test_company_qualified_name_picks_the_right_person(self):
        for token in ("Sara from RE/MAX", "sara at remax", "Sara Re-Max",
                      "sara diaz remax"):
            resolved = self.book.resolve(token)
            self.assertEqual(len(resolved), 1, token)
            self.assertEqual(resolved[0].email, "sara.diaz@remax.com", token)

    def test_the_other_company_gets_the_other_sara(self):
        self.assertEqual(
            self.book.resolve("Sara from Century 21")[0].email,
            "sara.kim@century21.com",
        )

    def test_bare_first_name_is_ambiguous_not_guessed(self):
        with self.assertRaises(ResolutionError) as ctx:
            self.book.resolve("Sara")
        self.assertIn("ambiguous", str(ctx.exception))
        # The error must name both, so the user can pick.
        self.assertIn("sara-remax", str(ctx.exception))
        self.assertIn("sara-c21", str(ctx.exception))

    def test_bare_company_addresses_everyone_there(self):
        emails = {c.email for c in self.book.resolve("RE/MAX")}
        self.assertEqual(emails, {"sara.diaz@remax.com", "john.ruiz@remax.com"})

    def test_unknown_company_is_refused(self):
        with self.assertRaises(ResolutionError):
            self.book.resolve("Sara from Sotheby's")

    def test_label_shows_the_company_but_headers_do_not(self):
        sara = self.book.by_key("sara-remax")
        self.assertEqual(sara.label, "Sara Diaz (RE/MAX) <sara.diaz@remax.com>")
        self.assertEqual(sara.display, "Sara Diaz <sara.diaz@remax.com>")

    def test_mentioned_in_matches_company_qualified_prose(self):
        found = self.book.mentioned_in("Loop in Sara from RE/MAX on this.")
        self.assertEqual([c.email for c in found], ["sara.diaz@remax.com"])

    def test_a_bare_name_is_still_flagged_when_genuinely_separate(self):
        # Two distinct mentions: both Saras really are named, so warn on both.
        found = self.book.mentioned_in("Ask Sara Kim, and Sara from RE/MAX too.")
        self.assertEqual(
            {c.email for c in found},
            {"sara.kim@century21.com", "sara.diaz@remax.com"},
        )

    def test_company_survives_a_save_and_load(self):
        path = self.tmp / "out.json"
        self.book.save(path)
        reloaded = AddressBook.load(path)
        self.assertEqual(reloaded.by_key("sara-remax").company, "RE/MAX")


if __name__ == "__main__":
    unittest.main()
