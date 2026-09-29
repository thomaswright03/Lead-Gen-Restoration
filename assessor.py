#!/usr/bin/env python3
"""Salt Lake County assessor condition scraper and poor-condition flagger (Phase 1 prototype).

Standard library only. Usage:
    python3 assessor.py fetch 16161580100000 [more parcel ids...]
    python3 assessor.py fetch --file parcels.txt
    python3 assessor.py export flagged.csv [--all]

Each parcel detail page is fetched once (raw HTML cached under cache/), parsed,
scored with rules.json, and stored in assessor.db. Requests are rate limited.
"""
import argparse
import csv
import datetime as dt
import html
import json
import re
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "assessor.db"
CACHE = BASE / "cache"
RULES_PATH = BASE / "rules.json"
DETAIL_URL = "https://apps.saltlakecounty.gov/assessor/new/valuationInfoExpanded.cfm?parcel_id={pid}"
USER_AGENT = "assessor-condition-research/0.1 (Python urllib; low-volume prototype)"
DELAY_SECONDS = 3.0

_last_request = 0.0


def normalize_pid(pid):
    digits = re.sub(r"\D", "", pid)
    if len(digits) != 14:
        raise ValueError(f"parcel id must have 14 digits: {pid!r}")
    return digits


def fetch_html(pid, refresh=False):
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{pid}.html"
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")
    global _last_request
    wait = DELAY_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    req = urllib.request.Request(DETAIL_URL.format(pid=pid), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    _last_request = time.monotonic()
    path.write_text(body, encoding="utf-8")
    return body


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# Record rows look like: <div class="landTable ..."><div>VALUE</div>LABEL</div>
_ROW = re.compile(r'<div class="(?:landTable|detStr)[^"]*">\s*<div[^>]*>(.*?)</div>\s*([^<]+?)\s*</div>', re.S)
_SUMMARY_ROW = re.compile(r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*</tr>", re.S)


def _rows(fragment):
    out = {}
    for value, label in _ROW.findall(fragment):
        out.setdefault(_text(label), _text(value))
    return out


def parse(page):
    if "Residence Record" not in page and "Land Record" not in page:
        raise ValueError("page has no parcel records (bad parcel id or site change)")
    rec = {"summary": {}, "land": {}, "residence": [], "detached": []}
    m = re.search(r'id="parcelFieldNames".*?</table>', page, re.S)
    if m:
        for label, value in _SUMMARY_ROW.findall(m.group(0)):
            rec["summary"][_text(label)] = _text(value)
    m = re.search(r"CAMA data,\s*as it was,\s*on\s*([A-Za-z]+ \d+, \d{4})", page)
    rec["cama_as_of"] = m.group(1).strip() if m else None

    # Split the page into its record sections by their headers.
    markers = [(mm.start(), mm.group(1)) for mm in re.finditer(
        r">\s*(Land Record|Residence Record|Detached Structure|Commercial|Legal Description)\s*<", page)]
    markers.append((len(page), "end"))
    for (start, name), (end, _) in zip(markers, markers[1:]):
        rows = _rows(page[start:end])
        if not rows:
            continue
        if name == "Land Record":
            rec["land"].update(rows)
        elif name == "Residence Record":
            rec["residence"].append(rows)
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


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS parcels (
        parcel_id TEXT PRIMARY KEY, address TEXT, owner TEXT, property_type TEXT,
        year_built TEXT, effective_year_built TEXT, market_value TEXT,
        overall_condition TEXT, interior_condition TEXT, exterior_condition TEXT,
        visual_appeal TEXT, score INTEGER, flagged INTEGER, reasons TEXT,
        cama_as_of TEXT, scraped_at TEXT, raw_json TEXT)""")
    return con


def process(pid, rules, con, refresh=False):
    rec = parse(fetch_html(pid, refresh))
    pts, flagged, reasons = score(rec, rules)
    s = rec["summary"]
    res = rec["residence"][0] if rec["residence"] else {}
    market = next((v for k, v in s.items() if k.endswith("Market Value")), "")
    row = {
        "parcel_id": pid, "address": s.get("Address"), "owner": s.get("Owner"),
        "property_type": s.get("Property Type"), "year_built": res.get("Year Built"),
        "effective_year_built": res.get("Effective Year Built"), "market_value": market,
        "overall_condition": res.get("Overall Condition"), "interior_condition": res.get("Interior Condition"),
        "exterior_condition": res.get("Exterior Condition"), "visual_appeal": res.get("Visual Appeal"),
        "score": pts, "flagged": int(flagged), "reasons": "; ".join(reasons),
        "cama_as_of": rec["cama_as_of"], "scraped_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "raw_json": json.dumps(rec),
    }
    cols = ", ".join(row)
    con.execute(f"INSERT OR REPLACE INTO parcels ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    con.commit()
    return row


EXPORT_COLS = ["parcel_id", "address", "owner", "property_type", "year_built", "effective_year_built",
               "market_value", "overall_condition", "interior_condition", "exterior_condition",
               "visual_appeal", "score", "flagged", "reasons", "cama_as_of", "scraped_at"]


def export(path, include_all):
    con = db()
    where = "" if include_all else "WHERE flagged = 1"
    rows = con.execute(f"SELECT {', '.join(EXPORT_COLS)} FROM parcels {where} ORDER BY score DESC").fetchall()
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(EXPORT_COLS)
        w.writerows(rows)
    return len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("parcels", nargs="*")
    f.add_argument("--file")
    f.add_argument("--refresh", action="store_true", help="ignore cached HTML")
    e = sub.add_parser("export")
    e.add_argument("path")
    e.add_argument("--all", action="store_true", help="include unflagged parcels")
    args = ap.parse_args()

    if args.cmd == "export":
        print(f"wrote {export(args.path, args.all)} rows to {args.path}")
        return
    pids = list(args.parcels)
    if args.file:
        pids += [line.strip() for line in open(args.file) if line.strip() and not line.startswith("#")]
    rules = json.loads(RULES_PATH.read_text())
    con = db()
    for raw in pids:
        try:
            row = process(normalize_pid(raw), rules, con, args.refresh)
            print(f"{row['parcel_id']}  {row['address']}  overall={row['overall_condition']} "
                  f"int={row['interior_condition']} ext={row['exterior_condition']}  "
                  f"score={row['score']} flagged={bool(row['flagged'])}")
        except Exception as exc:  # keep going on bad parcels
            print(f"{raw}: ERROR {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
