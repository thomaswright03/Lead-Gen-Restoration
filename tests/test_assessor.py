import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import assessor  # noqa: E402
import dashboard  # noqa: E402

FIXTURE = (ROOT / "tests" / "fixtures" / "synthetic_poor.html").read_text()
RULES = json.loads((ROOT / "rules.json").read_text())


class ParseTest(unittest.TestCase):
    def test_parses_summary_and_records(self):
        rec = assessor.parse(FIXTURE)
        self.assertEqual(rec["summary"]["Address"], "123 E EXAMPLE AVE")
        self.assertEqual(rec["summary"]["Owner"], "TEST OWNER")
        self.assertEqual(rec["cama_as_of"], "May 22, 2026")
        self.assertEqual(rec["land"]["Lot Use"], "RESIDENTIAL")
        res = rec["residence"][0]
        self.assertEqual(res["Overall Condition"], "POOR")
        self.assertEqual(res["Interior Condition"], "FAIR")
        self.assertEqual(res["Effective Year Built"], "1975")
        self.assertEqual(rec["detached"][0]["Condition"], "POOR")

    def test_condo_codes_are_expanded_and_scored(self):
        rec = assessor.parse((ROOT / "tests" / "fixtures" / "synthetic_condo.html").read_text())
        self.assertEqual(rec["residence"], [])
        self.assertEqual(rec["condo"][0]["Interior Condition"], "POOR")
        self.assertEqual(rec["condo"][0]["Interior Grade"], "F")  # grades are not condition codes
        self.assertEqual(assessor.score(rec, RULES)[:2], (3, True))

    def test_special_obsolescence_scores(self):
        rec = {"residence": [{"Overall Condition": "SPEC OBSOL"}]}
        self.assertEqual(assessor.score(rec, RULES)[0], 3)

    def test_rejects_page_without_records(self):
        with self.assertRaises(ValueError):
            assessor.parse("<html>There is a problem with the URL parameters</html>")

    def test_normalize_pid(self):
        self.assertEqual(assessor.normalize_pid("16-16-158-010-0000"), "16161580100000")
        with self.assertRaises(ValueError):
            assessor.normalize_pid("16-16-158")


class ScoreTest(unittest.TestCase):
    def test_poor_parcel_is_flagged(self):
        pts, flagged, reasons = assessor.score(assessor.parse(FIXTURE), RULES)
        # overall POOR 4 + interior FAIR 2 + exterior POOR 3 + detached POOR 1
        self.assertEqual(pts, 10)
        self.assertTrue(flagged)
        self.assertIn("residence Exterior Condition: POOR", reasons)

    def test_average_parcel_is_not_flagged(self):
        rec = {"residence": [{"Overall Condition": "AVERAGE", "Interior Condition": "AVERAGE",
                              "Exterior Condition": "GOOD", "Visual Appeal": "AVERAGE"}],
               "detached": [{"Condition": "FAIR"}]}
        self.assertEqual(assessor.score(rec, RULES)[:2], (0, False))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = assessor.db(os.path.join(self.tmp.name, "t.db"))
        self._orig_cache = assessor.CACHE
        assessor.CACHE = Path(self.tmp.name) / "cache"
        assessor.CACHE.mkdir()
        (assessor.CACHE / "11111111111111.html").write_text(FIXTURE)
        self.con.execute("INSERT INTO candidates (parcel_id, address, city, eff_built_yr) VALUES "
                         "('11111111111111', '123 E EXAMPLE AVE', 'Salt Lake City', 1975), "
                         "('22222222222222', '9 W OTHER ST', 'Sandy', 1980)")

    def tearDown(self):
        assessor.CACHE = self._orig_cache
        self.con.close()
        self.tmp.cleanup()

    def test_run_batch_uses_cache_and_tracks_pending(self):
        self.assertEqual(assessor.pending(self.con), ["11111111111111", "22222222222222"])
        ok, flagged, errors = assessor.run_batch(["11111111111111"], RULES, self.con, log=lambda *_: None)
        self.assertEqual((ok, flagged, errors), (1, 1, 0))
        self.assertEqual(assessor.pending(self.con), ["22222222222222"])

    def test_export_and_rescore(self):
        assessor.run_batch(["11111111111111"], RULES, self.con, log=lambda *_: None)
        rows = assessor.query_parcels(self.con, city="salt lake city")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["city"], "Salt Lake City")
        buf = io.StringIO()
        assessor.write_csv(rows, buf)
        self.assertIn("123 E EXAMPLE AVE", buf.getvalue())

        strict = dict(RULES, flag_threshold=99)
        assessor.rescore(self.con, strict)
        self.assertEqual(assessor.query_parcels(self.con), [])
        self.assertEqual(len(assessor.query_parcels(self.con, flagged_only=False)), 1)

    def test_dashboard_renders_and_escapes(self):
        assessor.run_batch(["11111111111111"], RULES, self.con, log=lambda *_: None)
        self.con.execute("UPDATE parcels SET owner = '<script>x</script>'")
        page = dashboard.render(self.con, {})
        self.assertIn("123 E EXAMPLE AVE", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>x", page)
        self.assertIn("2 candidates · 1 fetched · 1 flagged", page)


class CoordsTest(unittest.TestCase):
    def test_centroid_and_column_migration(self):
        self.assertEqual(assessor._centroid({"centroid": {"x": -111.96698411, "y": 40.84456225}}), (40.844562, -111.966984))
        self.assertEqual(assessor._centroid({}), (None, None))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE candidates (parcel_id TEXT PRIMARY KEY, address TEXT)")
            old.commit()
            old.close()
            cols = {r[1] for r in assessor.db(path).execute("PRAGMA table_info(candidates)")}
        self.assertTrue({"lat", "lon"} <= cols)


class WhereTest(unittest.TestCase):
    def test_where_clause(self):
        w = assessor.lir_where(1990, city="O'Brien", owner_occupied=True)
        self.assertIn("EFFBUILT_YR < 1990", w)
        self.assertIn("'O''BRIEN'", w)
        self.assertIn("PRIMARY_RES = 'Y'", w)
        self.assertNotIn("PRIMARY_RES", assessor.lir_where(1990))


if __name__ == "__main__":
    unittest.main()
