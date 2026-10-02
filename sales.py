#!/usr/bin/env python3
"""Recently sold homes across Salt Lake County, from RentCast property records.

    RENTCAST_API_KEY=... python3 sales.py [--days 90] [--max-requests 15]

Pulls residential properties whose last sale falls within --days, keeps the ones in Salt Lake County,
and replaces the sales table in assessor.db. The hosted site does the same into Postgres from its
"Refresh sales" button. Each request returns up to 500 homes, and the free RentCast plan includes
50 requests a month, so --max-requests caps each refresh. Utah does not disclose sale prices, so
the price is often missing.
"""
import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

import assessor
import listings

API_URL = "https://api.rentcast.io/v1/properties"
# A circle around the valley that takes in the whole county; neighbours are dropped by the county field.
CENTER = listings.CENTER
RADIUS_MILES = 20
PAGE = 500
COUNTY = "Salt Lake"
PROPERTY_TYPES = "Single Family|Condo|Townhouse|Manufactured|Multi-Family"
SALE_COLS = ["id", "address", "city", "zip", "lat", "lon", "property_type", "bedrooms", "bathrooms",
             "square_footage", "year_built", "sale_date", "sale_price", "fetched_at"]


def fetch(api_key, days=90, max_requests=15, opener=None):
    """Return (homes, requests used): raw property records sold within `days`, page by page."""
    opener = opener or urllib.request.urlopen
    homes, used = [], 0
    while used < max_requests:
        params = {"latitude": CENTER[0], "longitude": CENTER[1], "radius": RADIUS_MILES,
                  "propertyType": PROPERTY_TYPES, "saleDateRange": f"*:{int(days)}",
                  "limit": PAGE, "offset": used * PAGE}
        req = urllib.request.Request(API_URL + "?" + urllib.parse.urlencode(params),
                                     headers={"X-Api-Key": api_key, "Accept": "application/json"})
        with opener(req, timeout=30) as resp:
            batch = json.loads(resp.read().decode())
        used += 1
        homes += batch
        if len(batch) < PAGE:
            break
    return homes, used


def rows(homes, fetched_at=None):
    """Salt Lake County homes with coordinates and a sale date, as dicts in SALE_COLS order."""
    fetched_at = fetched_at or assessor._now()
    out, seen = [], set()
    for h in homes:
        if (h.get("county") or "").lower() != COUNTY.lower() or h.get("latitude") is None or not h.get("lastSaleDate"):
            continue
        key = h.get("id") or h.get("formattedAddress")
        if key in seen:
            continue
        seen.add(key)
        out.append({"id": key, "address": h.get("addressLine1") or h.get("formattedAddress"), "city": h.get("city"),
                    "zip": h.get("zipCode"), "lat": h["latitude"], "lon": h["longitude"],
                    "property_type": h.get("propertyType"), "bedrooms": h.get("bedrooms"),
                    "bathrooms": h.get("bathrooms"), "square_footage": h.get("squareFootage"),
                    "year_built": h.get("yearBuilt"), "sale_date": h["lastSaleDate"][:10],
                    "sale_price": h.get("lastSalePrice"), "fetched_at": fetched_at})
    return out


def replace(con, sale_rows):
    """Swap the SQLite sales table for a fresh pull."""
    con.execute("DELETE FROM sales")
    con.executemany(f"INSERT INTO sales ({', '.join(SALE_COLS)}) VALUES ({', '.join('?' * len(SALE_COLS))})",
                    [tuple(r[c] for c in SALE_COLS) for r in sale_rows])
    con.commit()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--max-requests", type=int, default=15)
    args = ap.parse_args(argv)
    key = os.environ.get("RENTCAST_API_KEY")
    if not key:
        raise SystemExit("RENTCAST_API_KEY is not set")
    homes, used = fetch(key, args.days, args.max_requests)
    found = rows(homes)
    replace(assessor.db(), found)
    print(f"{len(found)} Salt Lake County homes sold in the last {args.days} days ({used} requests)")


if __name__ == "__main__":
    sys.exit(main())
