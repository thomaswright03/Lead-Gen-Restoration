import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import assessor  # noqa: E402
import listings  # noqa: E402
import recorder  # noqa: E402

FIX = ROOT / "tests" / "fixtures"


class RecorderTest(unittest.TestCase):
    def test_parse_and_summarize(self):
        rec = recorder.parse((FIX / "synthetic_recorder.html").read_text())
        self.assertEqual(len(rec["documents"]), 4)
        self.assertEqual(rec["owners"], [{"name": "EXAMPLE HOLDINGS LLC", "since": "2026-02-27"}])
        s = recorder.summarize(rec, today=dt.date(2026, 9, 29))
        self.assertEqual(s["last_transfer_date"], "2026-03-02")
        self.assertEqual(s["last_transfer_type"], "WARRANTY DEED")
        self.assertEqual(s["distress_filings"], "NOTICE OF DEFAULT 2025-01-15")

    def test_trust_deed_is_a_mortgage_not_a_sale(self):
        self.assertFalse(recorder._is_transfer("TRUST DEED"))
        self.assertFalse(recorder._is_transfer("ASSIGNMENT OF TRUST DEED"))
        self.assertTrue(recorder._is_transfer("TRUSTEES DEED"))
        self.assertTrue(recorder._is_distress("TRUSTEES DEED"))
        self.assertFalse(recorder._is_distress("RELEASE OF LIEN"))

    def test_rejects_unexpected_page(self):
        with self.assertRaises(ValueError):
            recorder.parse("<html>Please read and agree to the Terms of Service</html>")


class ListingsTest(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(listings.normalize("3444 South West Temple Street"), listings.normalize("3444 S WESTTEMPLE ST"))
        self.assertEqual(listings.normalize("1450 East 1700 South"), "1450E1700S")
        self.assertEqual(listings.normalize("3632 S 860 E", "Unit 37"), listings.normalize("3632 S 860 E # 37"))
        self.assertNotEqual(listings.normalize("3632 S 860 E # 37"), listings.normalize("3632 S 860 E # 41"))

    def test_fetch_pages_and_match(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        con = assessor.db(os.path.join(tmp.name, "t.db"))
        con.execute("INSERT INTO parcels (parcel_id, address, flagged, score) VALUES "
                    "('11111111111111', '123 E EXAMPLE AVE', 1, 9), ('22222222222222', '9 W OTHER ST', 1, 4)")
        page1 = [{"addressLine1": "123 East Example Avenue", "status": "Active", "price": 250000,
                  "listedDate": "2026-09-01T00:00:00.000Z", "formattedAddress": "123 E Example Ave, Salt Lake City, UT",
                  "listingAgent": {"name": "Test Agent", "phone": "8015550100", "email": "agent@example.com"},
                  "listingOffice": {"name": "Example Realty", "phone": "8015550101"}}]
        page1 += [{"addressLine1": f"{n} N Nowhere Rd", "status": "Active"} for n in range(listings.PAGE - 1)]
        page2 = [{"addressLine1": "9 W Other St", "status": "Inactive", "price": 199000}]
        requests = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout):
            requests.append(req)
            return Resp(json.dumps(page1 if len(requests) == 1 else page2).encode())

        pulled = list(listings.fetch_listings("key", max_requests=5, opener=opener))
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[0].get_header("X-api-key"), "key")
        self.assertEqual(listings.match(con, pulled), 2)
        rows = {r["parcel_id"]: r for r in assessor.query_parcels(con)}
        self.assertEqual(rows["11111111111111"]["agent_name"], "Test Agent")
        self.assertEqual(rows["11111111111111"]["listing_status"], "Active")
        self.assertEqual(rows["22222222222222"]["listing_status"], "Inactive")

    def test_budget_caps_requests(self):
        calls = []

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def opener(req, timeout):
            calls.append(req)
            return Resp(json.dumps([{"addressLine1": "1 A St"}] * listings.PAGE).encode())

        list(listings.fetch_listings("key", max_requests=3, opener=opener))
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
