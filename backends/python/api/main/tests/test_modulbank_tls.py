import os
import ssl
import unittest
from pathlib import Path

from main.modulbank import tls
from main.modulbank.client import ModulbankClient


class ModulbankTlsTest(unittest.TestCase):
    def test_bundle_has_certifi_and_russian_root(self):
        tls.ca_bundle_path.cache_clear()
        path = tls.ca_bundle_path()
        text = Path(path).read_text(encoding="utf-8")
        self.assertIn(Path(tls.certifi.where()).read_text(encoding="utf-8")[:200], text)
        ctx = ssl.create_default_context(cafile=path)
        subjects = [dict(x[0] for x in c["subject"]).get("commonName") for c in ctx.get_ca_certs()]
        self.assertIn("Russian Trusted Root CA", subjects)

    def test_client_session_verifies_with_bundle(self):
        tls.ca_bundle_path.cache_clear()
        client = ModulbankClient("t")
        self.assertEqual(client._http.verify, tls.ca_bundle_path())
        self.assertTrue(os.path.exists(client._http.verify))

    def test_env_override(self):
        tls.ca_bundle_path.cache_clear()
        os.environ["MODULBANK_CA_BUNDLE"] = "/etc/ssl/custom.pem"
        try:
            self.assertEqual(tls.ca_bundle_path(), "/etc/ssl/custom.pem")
        finally:
            del os.environ["MODULBANK_CA_BUNDLE"]
            tls.ca_bundle_path.cache_clear()


if __name__ == "__main__":
    unittest.main()
