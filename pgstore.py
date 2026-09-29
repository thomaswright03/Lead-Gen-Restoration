"""Mirror results to Postgres for the hosted dashboard, and read them back.

    python3 pgstore.py sync        # push local assessor.db to $DATABASE_URL

Needs `pip install "psycopg[binary]"`. The scraper itself stays standard-library only;
only this module and the Vercel function use Postgres.
"""
import os
import sys

import assessor

PARCEL_COLS = ["parcel_id", "address", "owner", "property_type", "year_built", "effective_year_built",
               "market_value", "overall_condition", "interior_condition", "exterior_condition",
               "visual_appeal", "score", "flagged", "reasons", "cama_as_of", "scraped_at"]
CANDIDATE_COLS = ["parcel_id", "address", "city", "built_yr", "eff_built_yr", "primary_res", "market_value",
                  "lir_as_of", "added_at", "last_error"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS parcels (
    parcel_id TEXT PRIMARY KEY, address TEXT, owner TEXT, property_type TEXT,
    year_built TEXT, effective_year_built TEXT, market_value TEXT,
    overall_condition TEXT, interior_condition TEXT, exterior_condition TEXT,
    visual_appeal TEXT, score INTEGER, flagged INTEGER, reasons TEXT,
    cama_as_of TEXT, scraped_at TEXT);
CREATE TABLE IF NOT EXISTS candidates (
    parcel_id TEXT PRIMARY KEY, address TEXT, city TEXT, built_yr INTEGER,
    eff_built_yr INTEGER, primary_res TEXT, market_value BIGINT,
    lir_as_of TEXT, added_at TEXT, last_error TEXT);
"""


def _connect(url=None):
    import psycopg
    # The Vercel Neon integration names the variable <PREFIX>_URL; accept the common prefixes.
    url = url or next((os.environ[k] for k in ("DATABASE_URL", "POSTGRES_URL", "STORAGE_URL") if os.environ.get(k)), None)
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(url)


def _upsert_sql(table, cols):
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
    return (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
            f"ON CONFLICT (parcel_id) DO UPDATE SET {updates}")


def sync(lite, url=None):
    """Upsert every local candidate and parcel into Postgres. Returns (candidates, parcels)."""
    cands = lite.execute(f"SELECT {', '.join(CANDIDATE_COLS)} FROM candidates").fetchall()
    parcels = lite.execute(f"SELECT {', '.join(PARCEL_COLS)} FROM parcels").fetchall()
    with _connect(url) as pg:
        with pg.cursor() as cur:
            cur.execute(SCHEMA)
            cur.executemany(_upsert_sql("candidates", CANDIDATE_COLS), cands)
            cur.executemany(_upsert_sql("parcels", PARCEL_COLS), parcels)
    return len(cands), len(parcels)


def load(url=None):
    """Copy the Postgres tables into an in-memory SQLite db shaped like assessor.db."""
    lite = assessor.db(":memory:")
    with _connect(url) as pg:
        pg.execute(SCHEMA)
        for table, cols in (("candidates", CANDIDATE_COLS), ("parcels", PARCEL_COLS)):
            rows = pg.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            lite.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
    lite.commit()
    return lite


if __name__ == "__main__":
    if sys.argv[1:] != ["sync"]:
        raise SystemExit(__doc__)
    n_cand, n_parc = sync(assessor.db())
    print(f"synced {n_cand} candidates and {n_parc} parcels")
