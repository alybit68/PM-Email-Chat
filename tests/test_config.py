import os
import unittest

from pmail.config import Config, load_dotenv
from pmail.errors import ConfigError

from .helpers import TempEnv


class TestConfig(TempEnv):
    def test_personal_account_uses_smtp_host(self):
        config = Config.load()
        self.assertEqual(config.smtp_host, "smtp.zoho.com")
        self.assertEqual(config.smtp_port, 465)

    def test_organization_account_uses_smtppro(self):
        os.environ["ZOHO_ACCOUNT_TYPE"] = "organization"
        self.assertEqual(Config.load().smtp_host, "smtppro.zoho.com")

    def test_region_changes_every_host(self):
        os.environ["ZOHO_REGION"] = "eu"
        config = Config.load()
        self.assertEqual(config.smtp_host, "smtp.zoho.eu")
        self.assertEqual(config.api_base, "https://mail.zoho.eu")
        self.assertEqual(config.accounts_base, "https://accounts.zoho.eu")

    def test_canada_api_host_differs_from_smtp_host(self):
        os.environ["ZOHO_REGION"] = "ca"
        config = Config.load()
        self.assertEqual(config.smtp_host, "smtp.zoho.ca")
        self.assertEqual(config.api_base, "https://mail.zohocloud.ca")

    def test_explicit_host_overrides_derived_one(self):
        os.environ["ZOHO_SMTP_HOST"] = "smtp.custom.example"
        self.assertEqual(Config.load().smtp_host, "smtp.custom.example")

    def test_bad_region_is_rejected(self):
        os.environ["ZOHO_REGION"] = "atlantis"
        with self.assertRaises(ConfigError):
            Config.load()

    def test_send_switch_is_off_unless_truthy(self):
        self.assertFalse(Config.load().allow_send)
        for value in ("1", "true", "YES", "on"):
            os.environ["PMAIL_ALLOW_SEND"] = value
            self.assertTrue(Config.load().allow_send, value)
        for value in ("0", "false", "no", ""):
            os.environ["PMAIL_ALLOW_SEND"] = value
            self.assertFalse(Config.load().allow_send, value)

    def test_api_transport_needs_oauth_settings(self):
        os.environ["PMAIL_TRANSPORT"] = "api"
        missing = Config.load().missing_for_transport()
        self.assertIn("ZOHO_CLIENT_ID", missing)
        self.assertIn("ZOHO_REFRESH_TOKEN", missing)

    def test_dotenv_parsing(self):
        path = self.tmp / ".env"
        path.write_text(
            '# comment\nZOHO_EMAIL="quoted@example.com"\nEMPTY=\nBAD_LINE\n'
            "ZOHO_FROM_NAME=Spaced Name\n",
            encoding="utf-8",
        )
        values = load_dotenv(path)
        self.assertEqual(values["ZOHO_EMAIL"], "quoted@example.com")
        self.assertEqual(values["ZOHO_FROM_NAME"], "Spaced Name")
        self.assertNotIn("BAD_LINE", values)

    def test_process_env_beats_dotenv(self):
        path = self.tmp / ".env"
        path.write_text("ZOHO_EMAIL=fromfile@example.com\n", encoding="utf-8")
        os.environ["ZOHO_EMAIL"] = "fromenv@example.com"
        self.assertEqual(Config.load(path).email, "fromenv@example.com")


if __name__ == "__main__":
    unittest.main()
