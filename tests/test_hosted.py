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
import sales  # noqa: E402
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

            def store_sales(self, sale_rows):  # stands in for Postgres
                con = assessor.db(db_path)
                try:
                    sales.replace(con, sale_rows)
                finally:
                    con.close()

            def save_visit(self, pid, outcome, notes, visitor):  # stands in for Postgres
                con = assessor.db(db_path)
                try:
                    return assessor.add_visit(con, pid, outcome, notes, visitor)
                finally:
                    con.close()

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

    def post(self, body, password="s3cret", user="Dana", ctype="application/json"):
        req = urllib.request.Request(self.base + "/visits", data=body.encode(), method="POST",
                                     headers={"Content-Type": ctype})
        req.add_header("Authorization", "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode())
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return exc.code, json.loads(body) if exc.headers.get("Content-Type") == "application/json" else body

    def test_stopped_by_visits(self):
        os.environ["DASHBOARD_PASSWORD"] = "s3cret"
        ok = json.dumps({"parcel_id": "11111111111111", "outcome": "Follow Up", "notes": "Back after 5 </script>"})
        self.assertEqual(self.post(ok, password="wrong")[0], 401)
        self.assertEqual(self.post(ok, ctype="text/plain")[0], 415)
        self.assertEqual(self.post(json.dumps({"parcel_id": "11111111111111", "outcome": "Maybe"}))[0], 400)
        self.assertEqual(self.post("not json")[0], 400)
        status, body = self.post(ok)
        self.assertEqual(status, 200)
        self.assertEqual((body["visit"]["outcome"], body["visit"]["visitor"]), ("Follow Up", "Dana"))
        status, page = self.get("/", "s3cret")
        self.assertIn('"outcome":"Follow Up"', page)
        self.assertIn("Back after 5 \\u003c/script>", page)
        self.assertNotIn("5 </script>", page)
        self.assertIn("const CAN_SAVE = true;", page)

    def test_refresh_sales(self):
        os.environ["DASHBOARD_PASSWORD"] = "s3cret"
        os.environ.pop("RENTCAST_API_KEY", None)
        req = lambda: urllib.request.Request(self.base + "/sales/refresh", data=b'{"days": 30}', method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(b"x:s3cret").decode()})
        with self.assertRaises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(req())
        self.assertEqual(err.exception.code, 503)
        os.environ["RENTCAST_API_KEY"] = "test"
        orig = sales.fetch
        sales.fetch = lambda key, days: ([{"id": "z", "addressLine1": "1 A St", "county": "Salt Lake", "latitude": 40.7,
                                            "longitude": -111.9, "lastSaleDate": "2026-09-20T00:00:00Z"}], 1)
        try:
            with urllib.request.urlopen(req()) as resp:
                self.assertEqual(json.loads(resp.read())["homes"], 1)
        finally:
            sales.fetch = orig
            os.environ.pop("RENTCAST_API_KEY", None)
        self.assertIn('"address":"1 A St"', self.get("/", "s3cret")[1])


if __name__ == "__main__":
    unittest.main()
