"""Mirror results to Postgres for the hosted dashboard, and read them back.

    python3 pgstore.py sync          # push local assessor.db to $DATABASE_URL
    python3 pgstore.py sync --http   # same, over Neon's HTTPS SQL endpoint (for networks that block port 5432)

Needs `pip install "psycopg[binary]"`. The scraper itself stays standard-library only;
only this module and the Vercel function use Postgres.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

import assessor

PARCEL_COLS = ["parcel_id", "address", "owner", "property_type", "year_built", "effective_year_built",
               "market_value", "overall_condition", "interior_condition", "exterior_condition",
               "visual_appeal", "score", "flagged", "reasons", "cama_as_of", "scraped_at"]
CANDIDATE_COLS = ["parcel_id", "address", "city", "built_yr", "eff_built_yr", "primary_res", "market_value",
                  "lir_as_of", "added_at", "last_error", "lat", "lon"]
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
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS lon DOUBLE PRECISION;
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


def _database_url(url=None):
    url = url or next((os.environ[k] for k in ("DATABASE_URL", "POSTGRES_URL", "STORAGE_URL") if os.environ.get(k)), None)
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _neon_http(url, query, params=()):
    """Run one statement through Neon's SQL-over-HTTPS endpoint."""
    host = urllib.parse.urlsplit(url).hostname
    req = urllib.request.Request(f"https://{host}/sql", json.dumps({"query": query, "params": list(params)}).encode(),
                                 {"Neon-Connection-String": url, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def sync_http(lite, url=None, chunk=200):
    """Like sync(), but over HTTPS in multi-row upserts."""
    url = _database_url(url)
    for stmt in filter(None, (s.strip() for s in SCHEMA.split(";"))):
        _neon_http(url, stmt)
    counts = {}
    for table, cols in TABLES:
        rows = lite.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
        for i in range(0, len(rows), chunk):
            part = rows[i:i + chunk]
            values = ", ".join("(" + ", ".join(f"${r * len(cols) + c + 1}" for c in range(len(cols))) + ")"
                               for r in range(len(part)))
            params = [None if v is None else str(v) for row in part for v in row]
            _neon_http(url, f"INSERT INTO {table} ({', '.join(cols)}) VALUES {values} "
                            f"ON CONFLICT (parcel_id) DO UPDATE SET {updates}", params)
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
    if sys.argv[1:2] != ["sync"]:
        raise SystemExit(__doc__)
    counts = (sync_http if "--http" in sys.argv else sync)(assessor.db())
    print("synced " + ", ".join(f"{n} {table}" for table, n in counts.items()))
