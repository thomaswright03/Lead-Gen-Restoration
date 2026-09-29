#!/usr/bin/env python3
"""Match flagged parcels to for-sale listings and their listing agents (RentCast API).

    RENTCAST_API_KEY=... python3 listings.py [--status Active|Inactive] [--days-old 365] [--max-requests 20]

Pulls every listing within a radius covering Salt Lake County (500 per request), matches them to
stored parcels by normalized street address, and stores price, dates and listing agent/office contact
details. The free RentCast plan includes 50 requests a month, so --max-requests caps each run.

RentCast's API terms allow lawful direct marketing but prohibit using the data to send unsolicited
commercial email.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import assessor

API_URL = "https://api.rentcast.io/v1/listings/sale"
# A circle around the Salt Lake Valley that covers the county's populated area.
CENTER = (40.66, -111.93)
RADIUS_MILES = 16
PAGE = 500

SUFFIXES = {"AVENUE": "AVE", "STREET": "ST", "DRIVE": "DR", "ROAD": "RD", "LANE": "LN", "CIRCLE": "CIR",
            "COURT": "CT", "PLACE": "PL", "BOULEVARD": "BLVD", "PARKWAY": "PKWY", "TERRACE": "TER",
            "HIGHWAY": "HWY", "COVE": "CV", "TRAIL": "TRL", "SQUARE": "SQ"}
DIRECTIONS = {"NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}


def normalize(line1, line2=None):
    """Comparable key for a street address: '3444 S West Temple St', 'Unit 5' -> '3444SWESTTEMPLEST#5'."""
    text = (line1 or "").upper()
    unit = ""
    m = re.search(r"\s*(?:#|\bUNIT\b|\bAPT\b|\bSTE\b)\s*([A-Z0-9-]+)\s*$", text)
    if m:
        unit, text = m.group(1), text[:m.start()]
    if line2 and not unit:
        m = re.search(r"([A-Z0-9-]+)\s*$", line2.upper())
        unit = m.group(1) if m else ""
    words = re.findall(r"[A-Z0-9]+", text)
    out = []
    for i, w in enumerate(words):
        # Spell out directions only where they are directions: right after the house number, or after a
        # numbered grid street ("1450 E 1700 S"). "West Temple" keeps its WEST.
        is_direction_slot = i == 1 or (i == len(words) - 1 and i > 0 and words[i - 1].isdigit())
        out.append(DIRECTIONS.get(w, w) if is_direction_slot else SUFFIXES.get(w, w))
    return "".join(out) + (f"#{unit}" if unit else "")



def fetch_listings(api_key, status="Active", days_old=None, max_requests=20, opener=None):
    """Yield listing dicts page by page until exhausted or the request budget is spent."""
    opener = opener or urllib.request.urlopen
    for page in range(max_requests):
        params = {"latitude": CENTER[0], "longitude": CENTER[1], "radius": RADIUS_MILES, "status": status,
                  "limit": PAGE, "offset": page * PAGE}
        if days_old:
            params["daysOld"] = f"*:{int(days_old)}"
        req = urllib.request.Request(API_URL + "?" + urllib.parse.urlencode(params),
                                     headers={"X-Api-Key": api_key, "Accept": "application/json"})
        with opener(req, timeout=60) as resp:
            batch = json.loads(resp.read().decode())
        yield from batch
        if len(batch) < PAGE:
            return


def match(con, listings):
    """Store listings whose address matches a stored parcel. Returns the number matched."""
    index = {}
    for pid, address in con.execute("SELECT parcel_id, address FROM parcels"):
        index.setdefault(normalize(address), pid)
    matched = 0
    for li in listings:
        pid = index.get(normalize(li.get("addressLine1"), li.get("addressLine2")))
        if not pid:
            continue
        agent, office = li.get("listingAgent") or {}, li.get("listingOffice") or {}
        existing = con.execute("SELECT status, listed_date FROM listings WHERE parcel_id = ?", (pid,)).fetchone()
        # Keep an active listing over an older inactive one for the same parcel.
        if existing and existing[0] == "Active" and li.get("status") != "Active":
            continue
        con.execute("""INSERT OR REPLACE INTO listings (parcel_id, status, price, listed_date, removed_date,
                           days_on_market, agent_name, agent_phone, agent_email, office_name, office_phone,
                           mls_name, mls_number, listing_address, checked_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, li.get("status"), li.get("price"), (li.get("listedDate") or "")[:10] or None,
                     (li.get("removedDate") or "")[:10] or None, li.get("daysOnMarket"), agent.get("name"),
                     agent.get("phone"), agent.get("email"), office.get("name"), office.get("phone"),
                     li.get("mlsName"), li.get("mlsNumber"), li.get("formattedAddress"), assessor._now()))
        matched += 1
    con.commit()
    return matched


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--status", choices=["Active", "Inactive"], default="Active")
    ap.add_argument("--days-old", type=int, help="only listings first listed within this many days")
    ap.add_argument("--max-requests", type=int, default=20)
    args = ap.parse_args(argv)
    key = os.environ.get("RENTCAST_API_KEY")
    if not key:
        raise SystemExit("RENTCAST_API_KEY is not set")
    con = assessor.db()
    seen = []
    for li in fetch_listings(key, args.status, args.days_old, args.max_requests):
        seen.append(li)
    n = match(con, seen)
    print(f"{len(seen)} {args.status.lower()} listings pulled, {n} matched to stored parcels")


if __name__ == "__main__":
    sys.exit(main())
