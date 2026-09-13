import socket
import unittest
import urllib.error
from unittest import mock

from pmail import net
from pmail.config import Config

from .helpers import TempEnv


class TestProbes(TempEnv):
    def test_smtp_timeout_in_a_sandbox_names_the_real_cause(self):
        with mock.patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy:8080"}), \
             mock.patch("socket.create_connection", side_effect=socket.timeout()):
            probe = net.probe_smtp(Config.load())
        self.assertFalse(probe.ok)
        self.assertIn("not routed", probe.hint)
        self.assertIn("PMAIL_TRANSPORT=api", probe.hint)

    def test_smtp_timeout_outside_a_sandbox_suggests_the_other_port(self):
        with mock.patch.dict("os.environ", {"HTTPS_PROXY": "", "https_proxy": ""}), \
             mock.patch("socket.create_connection", side_effect=socket.timeout()):
            probe = net.probe_smtp(Config.load())
        self.assertFalse(probe.ok)
        self.assertIn("587", probe.hint)
        self.assertNotIn("cloud session", probe.hint)

    def test_smtp_success(self):
        with mock.patch("socket.create_connection"):
            self.assertTrue(net.probe_smtp(Config.load()).ok)

    def test_api_http_error_still_counts_as_reachable(self):
        # A 400 from Zoho means the host answered, so the path is open.
        error = urllib.error.HTTPError("url", 400, "Bad Request", {}, None)
        with mock.patch("urllib.request.urlopen", side_effect=error):
            self.assertTrue(net.probe_api(Config.load()).ok)

    def test_api_proxy_denial_names_the_hosts_to_allowlist(self):
        error = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
        with mock.patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy:8080"}), \
             mock.patch("urllib.request.urlopen", side_effect=error):
            probe = net.probe_api(Config.load())
        self.assertFalse(probe.ok)
        self.assertIn("mail.zoho.com", probe.hint)
        self.assertIn("accounts.zoho.com", probe.hint)
        self.assertIn("Allowed domains", probe.hint)

    def test_api_hint_uses_the_configured_region(self):
        import os
        os.environ["ZOHO_REGION"] = "eu"
        error = urllib.error.URLError("Tunnel connection failed: 403 Forbidden")
        with mock.patch.dict("os.environ", {"HTTPS_PROXY": "http://proxy:8080"}), \
             mock.patch("urllib.request.urlopen", side_effect=error):
            probe = net.probe_api(Config.load())
        self.assertIn("mail.zoho.eu", probe.hint)
        self.assertIn("accounts.zoho.eu", probe.hint)

    def test_probe_dispatches_on_transport(self):
        import os
        with mock.patch("pmail.net.probe_smtp") as smtp, mock.patch("pmail.net.probe_api") as api:
            net.probe(Config.load())
            smtp.assert_called_once()
            api.assert_not_called()
        os.environ["PMAIL_TRANSPORT"] = "api"
        with mock.patch("pmail.net.probe_smtp") as smtp, mock.patch("pmail.net.probe_api") as api:
            net.probe(Config.load())
            api.assert_called_once()
            smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
