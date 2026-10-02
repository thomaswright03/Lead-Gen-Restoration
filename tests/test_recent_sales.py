import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import assessor  # noqa: E402
import sales  # noqa: E402
import snapshot  # noqa: E402

HOMES = [
    {"id": "a", "addressLine1": "123 E Example Ave", "city": "Salt Lake City", "zipCode": "84111", "county": "Salt Lake",
     "latitude": 40.75, "longitude": -111.88, "propertyType": "Single Family", "bedrooms": 3, "bathrooms": 1.5,
     "squareFootage": 1400, "yearBuilt": 1925, "lastSaleDate": "2026-09-01T00:00:00.000Z", "lastSalePrice": None},
    {"id": "b", "addressLine1": "9 Other St", "county": "Davis", "latitude": 40.9, "longitude": -111.9,
     "lastSaleDate": "2026-09-02T00:00:00.000Z"},
    {"id": "a", "addressLine1": "123 E Example Ave", "county": "Salt Lake", "latitude": 40.75, "longitude": -111.88,
     "lastSaleDate": "2026-09-01T00:00:00.000Z"},
    {"id": "c", "addressLine1": "No Coords Rd", "county": "Salt Lake", "lastSaleDate": "2026-09-03T00:00:00.000Z"},
]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SalesTest(unittest.TestCase):
    def test_fetch_pages_until_short_batch(self):
        calls = []

        def opener(req, timeout):
            calls.append(req.full_url)
            return FakeResponse(json.dumps([{}] * (sales.PAGE if len(calls) == 1 else 3)).encode())

        homes, used = sales.fetch("k", days=60, max_requests=5, opener=opener)
        self.assertEqual((len(homes), used), (sales.PAGE + 3, 2))
        self.assertIn("saleDateRange=%2A%3A60", calls[0])
        self.assertIn("offset=500", calls[1])

    def test_rows_keep_county_homes_once(self):
        found = sales.rows(HOMES, fetched_at="2026-10-02T00:00:00+00:00")
        self.assertEqual([r["id"] for r in found], ["a"])
        self.assertEqual(found[0]["sale_date"], "2026-09-01")

    def test_snapshot_shows_sales_and_matches_flagged_parcels(self):
        con = assessor.db(":memory:")
        con.execute("INSERT INTO parcels (parcel_id, address, score, flagged) VALUES ('11111111111111', '123 E EXAMPLE AVE', 9, 1)")
        sales.replace(con, sales.rows(HOMES))
        page = snapshot.build(con)
        data = json.loads(page.split("const DATA = ", 1)[1].split(";\n", 1)[0])
        self.assertEqual(len(data["sales"]), 1)
        self.assertEqual(data["sales"][0]["parcel_id"], "11111111111111")
        self.assertNotIn("sale_price", data["sales"][0])


if __name__ == "__main__":
    unittest.main()
