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
RECORDER_COLS = ["parcel_id", "last_transfer_date", "last_transfer_type", "owner_of_record", "owner_since",
                 "distress_filings", "checked_at"]
LISTING_COLS = ["parcel_id", "status", "price", "listed_date", "removed_date", "days_on_market", "agent_name",
                "agent_phone", "agent_email", "office_name", "office_phone", "mls_name", "mls_number",
                "listing_address", "checked_at"]
TABLES = (("candidates", CANDIDATE_COLS), ("parcels", PARCEL_COLS), ("recorder", RECORDER_COLS),
          ("listings", LISTING_COLS))

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
CREATE TABLE IF NOT EXISTS recorder (
    parcel_id TEXT PRIMARY KEY, last_transfer_date TEXT, last_transfer_type TEXT,
    owner_of_record TEXT, owner_since TEXT, distress_filings TEXT, checked_at TEXT);
CREATE TABLE IF NOT EXISTS listings (
    parcel_id TEXT PRIMARY KEY, status TEXT, price BIGINT, listed_date TEXT, removed_date TEXT,
    days_on_market INTEGER, agent_name TEXT, agent_phone TEXT, agent_email TEXT, office_name TEXT,
    office_phone TEXT, mls_name TEXT, mls_number TEXT, listing_address TEXT, checked_at TEXT);
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
    """Upsert every local row into Postgres. Returns {table: row count}."""
    counts = {}
    with _connect(url) as pg:
        with pg.cursor() as cur:
            cur.execute(SCHEMA)
            for table, cols in TABLES:
                rows = lite.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
                cur.executemany(_upsert_sql(table, cols), rows)
                counts[table] = len(rows)
    return counts


def load(url=None):
    """Copy the Postgres tables into an in-memory SQLite db shaped like assessor.db."""
    lite = assessor.db(":memory:")
    with _connect(url) as pg:
        pg.execute(SCHEMA)
        for table, cols in TABLES:
            rows = pg.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            lite.executemany(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", rows)
    lite.commit()
    return lite


if __name__ == "__main__":
    if sys.argv[1:] != ["sync"]:
        raise SystemExit(__doc__)
    counts = sync(assessor.db())
    print("synced " + ", ".join(f"{n} {table}" for table, n in counts.items()))
