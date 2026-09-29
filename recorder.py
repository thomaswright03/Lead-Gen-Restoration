#!/usr/bin/env python3
"""Recent sales and distress filings from the Salt Lake County Recorder's free public search.

    python3 recorder.py [--limit 50] [--all] [--refresh]

For each flagged parcel (or every fetched parcel with --all) this reads the recorded-document list
(entry number, date, document type) and the current owner of record, and stores them in assessor.db.
Utah is a non-disclosure state, so sale prices and agents are not in these records.
"""
import argparse
import datetime as dt
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import assessor

SEARCH_URL = "https://apps.saltlakecounty.gov/data-services/DataServicesAccess/PublicSearch.aspx"

# Filings that suggest financial distress (foreclosure, liens, lawsuits).
DISTRESS_PATTERNS = ("NOTICE OF DEFAULT", "LIS PENDENS", "TRUSTEES DEED", "TRUSTEE'S DEED", "NOTICE OF TRUSTEE",
                     "SHERIFFS DEED", "SHERIFF'S DEED", "JUDGMENT", "LIEN", "TAX SALE")

_last = 0.0


def _is_transfer(doc_type):
    """Deeds that usually mean the property changed hands. A Utah "TRUST DEED" is a mortgage, not a sale."""
    t = doc_type.upper().strip()
    return t.endswith("DEED") and not re.search(r"\bTRUST DEED\b", t)


def _is_distress(doc_type):
    t = doc_type.upper()
    return any(p in t for p in DISTRESS_PATTERNS) and "RELEASE" not in t and "RECONVEYANCE" not in t


def _form(page):
    return {n: html.unescape(v) for n, v in re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', page)}


def _text(fragment):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _open(opener, data=None):
    global _last
    wait = assessor.DELAY_SECONDS - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with opener.open(SEARCH_URL, body, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            raise assessor.Blocked(f"HTTP {exc.code} from recorder") from exc
        raise


def fetch_page(pid):
    """Walk the public search (terms, parcel mode, parcel) and return the result page HTML."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", assessor.USER_AGENT)]
    page = _open(opener)
    for field, value in (("chkAccept", "on"), ("chkParcelNumber", "on")):
        page = _open(opener, {**_form(page), field: value, "__EVENTTARGET": field})
    formatted = f"{pid[0:2]}-{pid[2:4]}-{pid[4:7]}-{pid[7:10]}-{pid[10:14]}"
    return _open(opener, {**_form(page), "txtParcelNumber": formatted, "__EVENTTARGET": "txtParcelNumber"})


def parse(page):
    if "grdPublicSearchDocuments" not in page and "lblDocCount" not in page:
        raise ValueError("recorder page has no document list (parcel not found or site change)")
    docs = []
    m = re.search(r'id="grdPublicSearchDocuments".*?</table>', page, re.S)
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0) if m else "", re.S):
        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 3 and cells[0].isdigit():
            date = dt.datetime.strptime(cells[1], "%m/%d/%Y").date().isoformat()
            docs.append({"entry": cells[0], "recorded": date, "doc_type": cells[2]})
    owners = []
    m = re.search(r'id="grdPublicSearch".*?</table>', page, re.S)
    for cell in re.findall(r"<td[^>]*>(.*?)</td>", m.group(0) if m else "", re.S):
        text = _text(cell).rstrip(", ")
        om = re.match(r"(.*?)\s+(\d{2}/\d{2}/\d{4})$", text)
        if om:
            owners.append({"name": om.group(1), "since": dt.datetime.strptime(om.group(2), "%m/%d/%Y").date().isoformat()})
        elif text:
            owners.append({"name": text, "since": None})
    return {"documents": docs, "owners": owners}


def summarize(rec, today=None):
    today = today or dt.date.today()
    transfers = [d for d in rec["documents"] if _is_transfer(d["doc_type"])]
    distress = [d for d in rec["documents"] if _is_distress(d["doc_type"])]
    last = max(transfers, key=lambda d: d["recorded"], default=None)
    recent_distress = [d for d in distress if (today - dt.date.fromisoformat(d["recorded"])).days <= 3 * 365]
    return {
        "last_transfer_date": last["recorded"] if last else None,
        "last_transfer_type": last["doc_type"] if last else None,
        "owner_of_record": "; ".join(o["name"] for o in rec["owners"]) or None,
        "owner_since": min((o["since"] for o in rec["owners"] if o["since"]), default=None),
        "distress_filings": "; ".join(f"{d['doc_type']} {d['recorded']}" for d in recent_distress) or None,
    }



def pending(con, include_all=False, refresh=False, limit=None):
    sql = "SELECT p.parcel_id FROM parcels p LEFT JOIN recorder r USING (parcel_id) WHERE 1 = 1"
    if not include_all:
        sql += " AND p.flagged = 1"
    if not refresh:
        sql += " AND r.parcel_id IS NULL"
    sql += " ORDER BY p.score DESC, p.parcel_id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [r[0] for r in con.execute(sql)]


def run(con, pids, log=print):
    ok = errors = 0
    for i, pid in enumerate(pids, 1):
        try:
            rec = parse(fetch_page(pid))
        except assessor.Blocked as exc:
            log(f"stopping: {exc}. Wait before running again.")
            break
        except Exception as exc:  # keep going on bad parcels
            errors += 1
            log(f"[{i}/{len(pids)}] {pid}: ERROR {exc}")
            continue
        s = summarize(rec)
        con.execute("""INSERT OR REPLACE INTO recorder (parcel_id, last_transfer_date, last_transfer_type,
                           owner_of_record, owner_since, distress_filings, documents_json, checked_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (pid, s["last_transfer_date"], s["last_transfer_type"], s["owner_of_record"], s["owner_since"],
                     s["distress_filings"], json.dumps(rec["documents"]), assessor._now()))
        con.commit()
        ok += 1
        log(f"[{i}/{len(pids)}] {pid}  last transfer {s['last_transfer_date']} ({s['last_transfer_type']})"
            f"{'  DISTRESS: ' + s['distress_filings'] if s['distress_filings'] else ''}")
    return ok, errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--all", action="store_true", help="every fetched parcel, not only flagged ones")
    ap.add_argument("--refresh", action="store_true", help="re-check parcels already looked up")
    args = ap.parse_args(argv)
    con = assessor.db()
    pids = pending(con, args.all, args.refresh, args.limit)
    print(f"{len(pids)} parcels to look up (4 requests each, one every {assessor.DELAY_SECONDS:g}s)")
    ok, errors = run(con, pids)
    print(f"done: {ok} looked up, {errors} errors")


if __name__ == "__main__":
    sys.exit(main())
