import unittest

from pmail.contacts import AddressBook
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

    def test_roundtrip_save_and_load(self):
        path = self.tmp / "out.json"
        self.book.save(path)
        reloaded = AddressBook.load(path)
        self.assertEqual(len(reloaded.contacts), len(self.book.contacts))
        self.assertEqual(
            {c.email for c in reloaded.group_members("dev-team")},
            {"sara@example.com", "raj@example.com"},
        )


if __name__ == "__main__":
    unittest.main()
