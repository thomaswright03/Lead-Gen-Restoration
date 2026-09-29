#!/usr/bin/env python3
"""Salt Lake County assessor condition scraper and poor-condition flagger.

Standard library only. Typical flow:
    python3 assessor.py candidates --max-eff-year 1990     # free state parcel list -> candidates table
    python3 assessor.py run                                # fetch + score every candidate not yet fetched
    python3 assessor.py export flagged.csv                 # flagged parcels to CSV
    python3 dashboard.py                                   # browse and filter at http://localhost:8000

Single parcels can still be fetched directly:
    python3 assessor.py fetch 16-16-158-010-0000 [more ids...] [--file parcels.txt]

Each parcel detail page is fetched once (raw HTML cached under cache/), parsed,
scored with rules.json, and stored in assessor.db. Requests are rate limited.
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ASSESSOR_DB", BASE / "assessor.db"))
CACHE = Path(os.environ.get("ASSESSOR_CACHE", BASE / "cache"))
RULES_PATH = BASE / "rules.json"
DETAIL_URL = "https://apps.saltlakecounty.gov/assessor/new/valuationInfoExpanded.cfm?parcel_id={pid}"
# Utah UGRC statewide parcel layer (Land Information Records), Salt Lake County.
LIR_URL = ("https://services1.arcgis.com/99lidPhWCzftIe9K/arcgis/rest/services/"
           "Parcels_SaltLake_LIR/FeatureServer/0/query")
LIR_FIELDS = ["PARCEL_ID", "PARCEL_ADD", "PARCEL_CITY", "BUILT_YR", "EFFBUILT_YR",
              "PRIMARY_RES", "TOTAL_MKT_VALUE", "CURRENT_ASOF"]
LIR_PAGE = 2000
USER_AGENT = "assessor-condition-research/0.2 (Python urllib; rate limited)"
DELAY_SECONDS = float(os.environ.get("ASSESSOR_DELAY", "3.0"))
MAX_RETRIES = 3

_last_request = 0.0


class Blocked(Exception):
    """The county site refused us (403/429). Stop the run rather than push on."""


def normalize_pid(pid):
    digits = re.sub(r"\D", "", pid)
    if len(digits) != 14:
        raise ValueError(f"parcel id must have 14 digits: {pid!r}")
    return digits


def _get(url, timeout=30):
    """Rate-limited GET with a few retries on transient errors."""
    global _last_request
    for attempt in range(1, MAX_RETRIES + 1):
        wait = DELAY_SECONDS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                raise Blocked(f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}") from exc
            if exc.code < 500 or attempt == MAX_RETRIES:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == MAX_RETRIES:
                raise
        time.sleep(DELAY_SECONDS * 2 ** attempt)


def fetch_html(pid, refresh=False):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{pid}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")
    body = _get(DETAIL_URL.format(pid=pid))
    path.write_text(body, encoding="utf-8")
    return body


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# Record rows look like: <div class="landTable ..."><div>VALUE</div>LABEL</div>
_ROW = re.compile(r'<div class="(?:landTable|detStr)[^"]*">\s*<div[^>]*>(.*?)</div>\s*([^<]+?)\s*</div>', re.S)
# Condo unit records use single-letter codes for condition.
CONDITION_CODES = {"E": "EXCELLENT", "VG": "VERY GOOD", "G": "GOOD", "A": "AVERAGE", "F": "FAIR", "P": "POOR"}
_SUMMARY_ROW = re.compile(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", re.S)


def _rows(fragment):
    out = {}
    for value, label in _ROW.findall(fragment):
        out.setdefault(_text(label), _text(value))
    return out


def parse(page):
    if "Residence Record" not in page and "Land Record" not in page:
        raise ValueError("page has no parcel records (bad parcel id or site change)")
    rec = {"summary": {}, "land": {}, "residence": [], "condo": [], "detached": []}
    m = re.search(r'id="parcelFieldNames".*?</table>', page, re.S)
    if m:
        for label, value in _SUMMARY_ROW.findall(m.group(0)):
            rec["summary"][_text(label)] = _text(value)
    m = re.search(r"CAMA data,\s*as it was,\s*on\s*([A-Za-z]+ \d+, \d{4})", page)
    rec["cama_as_of"] = m.group(1).strip() if m else None

    # Split the page into its record sections by their headers.
    markers = [(mm.start(), mm.group(1)) for mm in re.finditer(
        r">\s*(Land Record|Residence Record|Condo Unit|Detached Structure|Commercial|Legal Description)\s*<", page)]
    markers.append((len(page), "end"))
    for (start, name), (end, _) in zip(markers, markers[1:]):
        rows = _rows(page[start:end])
        if not rows:
            continue
        if name == "Land Record":
            rec["land"].update(rows)
        elif name == "Residence Record":
            rec["residence"].append(rows)
        elif name == "Condo Unit":
            for k, v in rows.items():
                if k.endswith("Condition"):
                    rows[k] = CONDITION_CODES.get(v, v)
            rec["condo"].append(rows)
        elif name == "Detached Structure":
            rec["detached"].append(rows)
    return rec


def score(rec, rules):
    points, reasons = 0, []
    for key, table in rules["fields"].items():
        section, field = key.split(".", 1)
        for item in rec.get(section) or []:
            value = (item.get(field) or "").upper()
            for match, pts in table.items():
                if value.startswith(match):
                    points += pts
                    reasons.append(f"{section} {field}: {value}")
                    break
    return points, points >= rules["flag_threshold"], reasons


def db(path=None):
    con = sqlite3.connect(path or DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS parcels (
        parcel_id TEXT PRIMARY KEY, address TEXT, owner TEXT, property_type TEXT,
        year_built TEXT, effective_year_built TEXT, market_value TEXT,
        overall_condition TEXT, interior_condition TEXT, exterior_condition TEXT,
        visual_appeal TEXT, score INTEGER, flagged INTEGER, reasons TEXT,
        cama_as_of TEXT, scraped_at TEXT, raw_json TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS candidates (
        parcel_id TEXT PRIMARY KEY, address TEXT, city TEXT, built_yr INTEGER,
        eff_built_yr INTEGER, primary_res TEXT, market_value INTEGER,
        lir_as_of TEXT, added_at TEXT, last_error TEXT)""")
    # Filled by recorder.py (county recorder) and listings.py (RentCast).
    con.execute("""CREATE TABLE IF NOT EXISTS recorder (
        parcel_id TEXT PRIMARY KEY, last_transfer_date TEXT, last_transfer_type TEXT,
        owner_of_record TEXT, owner_since TEXT, distress_filings TEXT, documents_json TEXT, checked_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS listings (
        parcel_id TEXT PRIMARY KEY, status TEXT, price INTEGER, listed_date TEXT, removed_date TEXT,
        days_on_market INTEGER, agent_name TEXT, agent_phone TEXT, agent_email TEXT, office_name TEXT,
        office_phone TEXT, mls_name TEXT, mls_number TEXT, listing_address TEXT, checked_at TEXT)""")
    return con


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def process(pid, rules, con, refresh=False, scraped_at=None):
    rec = parse(fetch_html(pid, refresh))
    pts, flagged, reasons = score(rec, rules)
    s = rec["summary"]
    res = (rec["residence"] or rec["condo"] or [{}])[0]
    market = next((v for k, v in s.items() if k.endswith("Market Value")), "")
    row = {
        "parcel_id": pid, "address": s.get("Address"), "owner": s.get("Owner"),
        "property_type": s.get("Property Type"), "year_built": res.get("Year Built"),
        "effective_year_built": res.get("Effective Year Built") or res.get("Effective Y.B."), "market_value": market,
        "overall_condition": res.get("Overall Condition"), "interior_condition": res.get("Interior Condition"),
        "exterior_condition": res.get("Exterior Condition"), "visual_appeal": res.get("Visual Appeal"),
        "score": pts, "flagged": int(flagged), "reasons": "; ".join(reasons),
        "cama_as_of": rec["cama_as_of"], "scraped_at": scraped_at or _now(), "raw_json": json.dumps(rec),
    }
    cols = ", ".join(row)
    con.execute(f"INSERT OR REPLACE INTO parcels ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    con.commit()
    return row


def rescore(con, rules):
    """Re-apply rules.json to every stored parcel without fetching anything.

    Cached HTML is re-parsed when present so parser fixes apply too.
    """
    n = 0
    for pid, raw, scraped_at in con.execute("SELECT parcel_id, raw_json, scraped_at FROM parcels").fetchall():
        if (CACHE / f"{pid}.html").exists():
            process(pid, rules, con, scraped_at=scraped_at)
            n += 1
            continue
        pts, flagged, reasons = score(json.loads(raw), rules)
        con.execute("UPDATE parcels SET score = ?, flagged = ?, reasons = ? WHERE parcel_id = ?",
                    (pts, int(flagged), "; ".join(reasons), pid))
        n += 1
    con.commit()
    return n


def lir_where(max_eff_year, city=None, owner_occupied=False):
    clauses = ["PROP_CLASS = 'Residential'", "EFFBUILT_YR > 0", f"EFFBUILT_YR < {int(max_eff_year)}"]
    if city:
        clauses.append("UPPER(PARCEL_CITY) = '{}'".format(city.upper().replace("'", "''")))
    if owner_occupied:
        clauses.append("PRIMARY_RES = 'Y'")
    return " AND ".join(clauses)


def pull_candidates(con, where, limit=None):
    """Page through the state parcel layer and upsert matching parcels as candidates."""
    offset, added = 0, 0
    while True:
        params = {"where": where, "outFields": ",".join(LIR_FIELDS), "orderByFields": "OBJECTID",
                  "resultOffset": offset, "resultRecordCount": LIR_PAGE, "returnGeometry": "false", "f": "json"}
        data = json.loads(_get(LIR_URL + "?" + urllib.parse.urlencode(params), timeout=60))
        if "error" in data:
            raise RuntimeError(f"parcel layer query failed: {data['error']}")
        feats = data.get("features", [])
        for f in feats:
            a = f["attributes"]
            try:
                pid = normalize_pid(a["PARCEL_ID"] or "")
            except ValueError:
                continue
            asof = a.get("CURRENT_ASOF")
            asof = dt.datetime.fromtimestamp(asof / 1000, dt.timezone.utc).date().isoformat() if asof else None
            con.execute("""INSERT INTO candidates (parcel_id, address, city, built_yr, eff_built_yr,
                               primary_res, market_value, lir_as_of, added_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(parcel_id) DO UPDATE SET address = excluded.address, city = excluded.city,
                               built_yr = excluded.built_yr, eff_built_yr = excluded.eff_built_yr,
                               primary_res = excluded.primary_res, market_value = excluded.market_value,
                               lir_as_of = excluded.lir_as_of""",
                        (pid, a["PARCEL_ADD"], a["PARCEL_CITY"], a["BUILT_YR"], a["EFFBUILT_YR"],
                         a["PRIMARY_RES"], a["TOTAL_MKT_VALUE"], asof, _now()))
            added += 1
            if limit and added >= limit:
                con.commit()
                return added
        con.commit()
        if not feats or (len(feats) < LIR_PAGE and not data.get("exceededTransferLimit")):
            return added
        offset += len(feats)


def pending(con, max_age_days=None, limit=None):
    """Candidates never fetched, or fetched longer ago than max_age_days. Oldest effective year first."""
    sql = """SELECT c.parcel_id FROM candidates c LEFT JOIN parcels p USING (parcel_id)
             WHERE p.parcel_id IS NULL"""
    args = []
    if max_age_days is not None:
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)).isoformat(timespec="seconds")
        sql += " OR p.scraped_at < ?"
        args.append(cutoff)
    sql += " ORDER BY c.eff_built_yr, c.parcel_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in con.execute(sql, args)]


def run_batch(pids, rules, con, refresh=False, log=print):
    ok = errors = flagged = 0
    for i, pid in enumerate(pids, 1):
        try:
            row = process(pid, rules, con, refresh)
            con.execute("UPDATE candidates SET last_error = NULL WHERE parcel_id = ?", (pid,))
            ok += 1
            flagged += row["flagged"]
            log(f"[{i}/{len(pids)}] {pid}  {row['address']}  overall={row['overall_condition']} "
                f"int={row['interior_condition']} ext={row['exterior_condition']}  "
                f"score={row['score']} flagged={bool(row['flagged'])}")
        except Blocked as exc:
            log(f"stopping: {exc}. Wait before running again.")
            break
        except Exception as exc:  # keep going on bad parcels
            errors += 1
            con.execute("UPDATE candidates SET last_error = ? WHERE parcel_id = ?", (str(exc)[:500], pid))
            log(f"[{i}/{len(pids)}] {pid}: ERROR {exc}")
        con.commit()
    return ok, flagged, errors


EXPORT_COLS = ["parcel_id", "address", "city", "owner", "property_type", "year_built", "effective_year_built",
               "market_value", "overall_condition", "interior_condition", "exterior_condition",
               "visual_appeal", "score", "flagged", "reasons", "cama_as_of", "scraped_at",
               "last_transfer_date", "last_transfer_type", "distress_filings",
               "listing_status", "listing_price", "listed_date", "agent_name", "agent_phone", "agent_email",
               "office_name", "office_phone"]
# Where each export column comes from: p = parcels, c = candidates, r = recorder, l = listings.
_COL_SOURCE = {"city": "c.city", "last_transfer_date": "r.last_transfer_date",
               "last_transfer_type": "r.last_transfer_type", "distress_filings": "r.distress_filings",
               "listing_status": "l.status", "listing_price": "l.price", "listed_date": "l.listed_date",
               "agent_name": "l.agent_name", "agent_phone": "l.agent_phone", "agent_email": "l.agent_email",
               "office_name": "l.office_name", "office_phone": "l.office_phone"}


def query_parcels(con, flagged_only=True, city=None, min_score=None, order="score DESC"):
    """Stored parcels joined with city, recorder and listing data, as dicts in EXPORT_COLS order."""
    cols = ", ".join(_COL_SOURCE.get(c, f"p.{c}") for c in EXPORT_COLS)
    sql = (f"SELECT {cols} FROM parcels p LEFT JOIN candidates c USING (parcel_id) "
           "LEFT JOIN recorder r USING (parcel_id) LEFT JOIN listings l USING (parcel_id) WHERE 1 = 1")
    args = []
    if flagged_only:
        sql += " AND p.flagged = 1"
    if city:
        sql += " AND UPPER(c.city) = ?"
        args.append(city.upper())
    if min_score is not None:
        sql += " AND p.score >= ?"
        args.append(int(min_score))
    sql += f" ORDER BY p.{order}, p.parcel_id"
    return [dict(zip(EXPORT_COLS, r)) for r in con.execute(sql, args)]


def write_csv(rows, fh):
    w = csv.DictWriter(fh, fieldnames=EXPORT_COLS)
    w.writeheader()
    w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("candidates", help="pull likely-poor parcels from the free state parcel layer")
    c.add_argument("--max-eff-year", type=int, default=1990,
                   help="keep homes whose assessor effective year built is before this (default 1990)")
    c.add_argument("--city", help="limit to one city, e.g. 'Salt Lake City'")
    c.add_argument("--owner-occupied", action="store_true", help="only primary residences")
    c.add_argument("--limit", type=int)

    r = sub.add_parser("run", help="fetch and score candidates that have not been fetched yet")
    r.add_argument("--limit", type=int, help="stop after this many parcels")
    r.add_argument("--max-age-days", type=int, help="also re-fetch parcels scraped more than this many days ago")

    f = sub.add_parser("fetch", help="fetch and score specific parcel ids")
    f.add_argument("parcels", nargs="*")
    f.add_argument("--file")
    f.add_argument("--refresh", action="store_true", help="ignore cached HTML")

    sub.add_parser("rescore", help="re-apply rules.json to stored parcels")

    e = sub.add_parser("export", help="write parcels to CSV")
    e.add_argument("path")
    e.add_argument("--all", action="store_true", help="include unflagged parcels")
    e.add_argument("--city")
    e.add_argument("--min-score", type=int)
    args = ap.parse_args(argv)

    con = db()
    rules = json.loads(RULES_PATH.read_text())
    if args.cmd == "candidates":
        where = lir_where(args.max_eff_year, args.city, args.owner_occupied)
        n = pull_candidates(con, where, args.limit)
        total = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        print(f"{n} matching parcel rows; {total} candidates total, {len(pending(con))} not yet fetched")
    elif args.cmd == "run":
        pids = pending(con, args.max_age_days, args.limit)
        print(f"{len(pids)} parcels to fetch at one every {DELAY_SECONDS:g}s")
        ok, flagged, errors = run_batch(pids, rules, con, refresh=args.max_age_days is not None)
        print(f"done: {ok} fetched, {flagged} flagged, {errors} errors")
    elif args.cmd == "fetch":
        pids = list(args.parcels)
        if args.file:
            pids += [line.strip() for line in open(args.file) if line.strip() and not line.startswith("#")]
        good = []
        for raw in pids:
            try:
                good.append(normalize_pid(raw))
            except ValueError as exc:
                print(f"{raw}: ERROR {exc}", file=sys.stderr)
        run_batch(good, rules, con, args.refresh)
    elif args.cmd == "rescore":
        print(f"rescored {rescore(con, rules)} parcels")
    elif args.cmd == "export":
        rows = query_parcels(con, not args.all, args.city, args.min_score)
        with open(args.path, "w", newline="") as fh:
            write_csv(rows, fh)
        print(f"wrote {len(rows)} rows to {args.path}")


if __name__ == "__main__":
    main()
