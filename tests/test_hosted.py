import base64
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

import assessor  # noqa: E402
import index  # noqa: E402  (api/index.py)

FIXTURE = (ROOT / "tests" / "fixtures" / "synthetic_poor.html").read_text()
RULES = json.loads((ROOT / "rules.json").read_text())


class HostedHandlerTest(unittest.TestCase):
    """The Vercel handler, with Postgres swapped for a local SQLite db."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls._orig_cache = assessor.CACHE
        assessor.CACHE = Path(cls.tmp.name)
        (assessor.CACHE / "11111111111111.html").write_text(FIXTURE)
        db_path = os.path.join(cls.tmp.name, "t.db")
        con = assessor.db(db_path)
        con.execute("INSERT INTO candidates (parcel_id, city) VALUES ('11111111111111', 'Salt Lake City')")
        assessor.run_batch(["11111111111111"], RULES, con, log=lambda *_: None)
        con.close()

        class Local(index.handler):
            def open_db(self):
                return assessor.db(db_path)

            def log_message(self, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Local)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        assessor.CACHE = cls._orig_cache
        cls.tmp.cleanup()

    def get(self, path, password=None):
        req = urllib.request.Request(self.base + path)
        if password is not None:
            req.add_header("Authorization", "Basic " + base64.b64encode(f"x:{password}".encode()).decode())
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_requires_password_to_be_configured(self):
        os.environ.pop("DASHBOARD_PASSWORD", None)
        self.assertEqual(self.get("/", "anything")[0], 503)

    def test_login(self):
        os.environ["DASHBOARD_PASSWORD"] = "s3cret"
        self.assertEqual(self.get("/")[0], 401)
        self.assertEqual(self.get("/", "wrong")[0], 401)
        status, body = self.get("/", "s3cret")
        self.assertEqual(status, 200)
        self.assertIn("123 E EXAMPLE AVE", body)
        status, body = self.get("/export.csv", "s3cret")
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith("parcel_id,"))


if __name__ == "__main__":
    unittest.main()
