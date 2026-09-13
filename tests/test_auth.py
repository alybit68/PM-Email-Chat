import io
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from pmail import cli, net
from pmail.config import Config
from pmail.errors import ConfigError, SendFailed
from pmail.senders.zoho_api import exchange_code

from .helpers import TempEnv

OK_PROBE = net.Probe(True, "reachable")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class TestExchangeCode(TempEnv):
    def setUp(self):
        super().setUp()
        os.environ["PMAIL_TRANSPORT"] = "api"
        os.environ["ZOHO_CLIENT_ID"] = "cid"
        os.environ["ZOHO_CLIENT_SECRET"] = "secret"

    def test_missing_client_credentials_is_a_config_error(self):
        del os.environ["ZOHO_CLIENT_SECRET"]
        with self.assertRaises(ConfigError):
            exchange_code(Config.load(), "abc")

    def test_successful_exchange_returns_the_refresh_token(self):
        with mock.patch("pmail.senders.zoho_api._request",
                        return_value={"refresh_token": "r1", "access_token": "a1"}):
            payload = exchange_code(Config.load(), "abc")
        self.assertEqual(payload["refresh_token"], "r1")

    def test_expired_code_explains_that_codes_are_short_lived(self):
        with mock.patch("pmail.senders.zoho_api._request",
                        return_value={"error": "invalid_code"}):
            with self.assertRaises(SendFailed) as ctx:
                exchange_code(Config.load(), "abc")
        self.assertIn("single-use", str(ctx.exception))

    def test_invalid_client_points_at_the_region(self):
        with mock.patch("pmail.senders.zoho_api._request",
                        return_value={"error": "invalid_client"}):
            with self.assertRaises(SendFailed) as ctx:
                exchange_code(Config.load(), "abc")
        self.assertIn("ZOHO_REGION", str(ctx.exception))

    def test_the_code_is_stripped_before_sending(self):
        with mock.patch("pmail.senders.zoho_api._request",
                        return_value={"refresh_token": "r1"}) as request:
            exchange_code(Config.load(), "  abc\n")
        self.assertEqual(request.call_args.kwargs["form"]["code"], "abc")


class TestAuthCommand(TempEnv):
    def setUp(self):
        super().setUp()
        os.environ["PMAIL_TRANSPORT"] = "api"
        os.environ["ZOHO_CLIENT_ID"] = "cid"
        os.environ["ZOHO_CLIENT_SECRET"] = "secret"

    def test_blocked_network_is_reported_before_the_exchange(self):
        blocked = net.Probe(False, "403", "add mail.zoho.com to Allowed domains")
        with mock.patch("pmail.net.probe_api", return_value=blocked), \
             mock.patch("pmail.senders.zoho_api.exchange_code") as exchange:
            code, _, err = run("auth", "--code", "abc")
        exchange.assert_not_called()
        self.assertEqual(code, 1)
        self.assertIn("Allowed domains", err)

    def test_success_prints_the_env_lines_to_paste(self):
        with mock.patch("pmail.net.probe_api", return_value=OK_PROBE), \
             mock.patch("pmail.senders.zoho_api.exchange_code",
                        return_value={"refresh_token": "r1", "access_token": "a1"}), \
             mock.patch("pmail.senders.zoho_api.account_id", return_value="999"):
            code, out, _ = run("auth", "--code", "abc")
        self.assertEqual(code, 0)
        self.assertIn("ZOHO_REFRESH_TOKEN=r1", out)
        self.assertIn("ZOHO_ACCOUNT_ID=999", out)
        self.assertIn("PMAIL_TRANSPORT=api", out)

    def test_account_lookup_failure_does_not_lose_the_refresh_token(self):
        with mock.patch("pmail.net.probe_api", return_value=OK_PROBE), \
             mock.patch("pmail.senders.zoho_api.exchange_code",
                        return_value={"refresh_token": "r1", "access_token": "a1"}), \
             mock.patch("pmail.senders.zoho_api.account_id",
                        side_effect=SendFailed("no accounts")):
            code, out, _ = run("auth", "--code", "abc")
        self.assertEqual(code, 0)
        self.assertIn("ZOHO_REFRESH_TOKEN=r1", out)
        self.assertNotIn("ZOHO_ACCOUNT_ID", out)


if __name__ == "__main__":
    unittest.main()
