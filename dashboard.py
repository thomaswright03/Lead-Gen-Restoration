#!/usr/bin/env python3
"""Minimal dashboard for flagged parcels. Standard library only.

    python3 dashboard.py [--host 127.0.0.1] [--port 8000]

Serves a filterable table at / and the same filtered rows as CSV at /export.csv.
"""
import argparse
import html
import io
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import assessor
import sales

TABLE_COLS = [("parcel_id", "Parcel"), ("address", "Address"), ("city", "City"), ("property_type", "Type"), ("owner", "Owner"),
              ("year_built", "Built"), ("effective_year_built", "Eff. built"), ("market_value", "Market value"),
              ("overall_condition", "Overall"), ("interior_condition", "Interior"),
              ("exterior_condition", "Exterior"), ("visual_appeal", "Appeal"), ("score", "Score"),
              ("last_transfer_date", "Last transfer"), ("listing_status", "Listing"), ("agent_name", "Listing agent"),
              ("agent_phone", "Agent phone")]

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flagged Parcels</title>
<style>
:root {{ --bg:#fafaf9; --fg:#1c1917; --muted:#78716c; --line:#e7e5e4; --accent:#b45309; --poor:#b91c1c; --fair:#c2410c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#1c1917; --fg:#f5f5f4; --muted:#a8a29e; --line:#44403c; --accent:#f59e0b; --poor:#f87171; --fair:#fb923c; }} }}
body {{ margin:0; padding:16px; background:var(--bg); color:var(--fg); font:14px/1.4 system-ui, sans-serif; }}
h1 {{ font-size:20px; margin:0 0 4px; }}
.stats {{ color:var(--muted); margin-bottom:12px; }}
form {{ display:flex; flex-wrap:wrap; gap:12px; align-items:end; margin-bottom:12px; }}
label {{ display:flex; flex-direction:column; gap:2px; color:var(--muted); font-size:12px; }}
input, select, button {{ font:inherit; padding:4px 6px; }}
a {{ color:var(--accent); }}
.wrap {{ overflow-x:auto; }}
table {{ border-collapse:collapse; width:100%; }}
th, td {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); white-space:nowrap; }}
th {{ font-weight:600; position:sticky; top:0; background:var(--bg); }}
td.reasons {{ white-space:normal; color:var(--muted); font-size:12px; min-width:240px; }}
.POOR {{ color:var(--poor); font-weight:600; }} .FAIR {{ color:var(--fair); }}
</style></head><body>
<h1>Flagged parcels</h1>
<div class="stats">{stats}</div>
<form method="get">
  <label>City<select name="city"><option value="">All</option>{city_options}</select></label>
  <label>Min score<input type="number" name="min_score" value="{min_score}" style="width:6em"></label>
  <label style="flex-direction:row;align-items:center;gap:6px;color:inherit">
    <input type="checkbox" name="all" value="1" {all_checked}> Include unflagged</label>
  <button type="submit">Filter</button>
  <a href="export.csv?{query}">Download CSV ({count} rows)</a>
</form>
<div class="wrap"><table><thead><tr>{head}<th>Why flagged</th></tr></thead><tbody>{body}</tbody></table></div>
</body></html>"""


def _filters(qs):
    city = qs.get("city", [""])[0] or None
    raw_score = qs.get("min_score", [""])[0]
    min_score = int(raw_score) if raw_score.strip().lstrip("-").isdigit() else None
    include_all = qs.get("all", [""])[0] == "1"
    return city, min_score, include_all


def render(con, qs):
    city, min_score, include_all = _filters(qs)
    rows = assessor.query_parcels(con, not include_all, city, min_score)
    n_cand = con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    n_fetched, n_flagged = con.execute("SELECT COUNT(*), COALESCE(SUM(flagged), 0) FROM parcels").fetchone()
    cities = [r[0] for r in con.execute("SELECT DISTINCT city FROM candidates WHERE city IS NOT NULL ORDER BY city")]
    esc = lambda v: html.escape("" if v is None else str(v))
    body = []
    for r in rows:
        cells = []
        for key, _ in TABLE_COLS:
            v = r[key]
            if key == "parcel_id":
                cells.append(f'<td><a href="{esc(assessor.DETAIL_URL.format(pid=v))}" target="_blank" '
                             f'rel="noopener">{esc(v)}</a></td>')
            elif key.endswith("_condition"):
                cells.append(f'<td class="{esc((v or "").split(" ")[0])}">{esc(v)}</td>')
            else:
                cells.append(f"<td>{esc(v)}</td>")
        cells.append(f'<td class="reasons">{esc(r["reasons"])}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return PAGE.format(
        stats=f"{n_cand} candidates · {n_fetched} fetched · {n_flagged} flagged",
        city_options="".join(f'<option{" selected" if c == city else ""}>{esc(c)}</option>' for c in cities),
        min_score=esc(min_score if min_score is not None else ""),
        all_checked="checked" if include_all else "",
        query=esc(urllib.parse.urlencode({k: v[0] for k, v in qs.items()})),
        count=len(rows),
        head="".join(f"<th>{esc(label)}</th>" for _, label in TABLE_COLS),
        body="".join(body) or f'<tr><td colspan="{len(TABLE_COLS) + 1}">No parcels match.</td></tr>',
    )


class Handler(BaseHTTPRequestHandler):
    def open_db(self):
        return assessor.db()

    def authorized(self):
        return True

    def render_page(self, con, qs):
        return render(con, qs)

    def visitor(self):
        return "local"

    def save_visit(self, pid, outcome, notes, visitor):
        con = self.open_db()
        try:
            return assessor.add_visit(con, pid, outcome, notes, visitor)
        finally:
            con.close()

    def store_sales(self, sale_rows):
        con = self.open_db()
        try:
            sales.replace(con, sale_rows)
        finally:
            con.close()

    def refresh_sales(self, body):
        """Pull recently sold homes from RentCast and store them. JSON {days} to /sales/refresh."""
        key = os.environ.get("RENTCAST_API_KEY")
        if not key:
            return self._json(503, {"error": "RENTCAST_API_KEY is not set for this site"})
        try:
            days = min(max(int(body.get("days") or 90), 1), 365)
        except (TypeError, ValueError, AttributeError):
            return self._json(400, {"error": "days must be a number"})
        try:
            homes, used = sales.fetch(key, days)
        except Exception as exc:  # RentCast down, bad key, quota used up
            return self._json(502, {"error": f"RentCast request failed: {exc}"})
        found = sales.rows(homes)
        self.store_sales(found)
        self._json(200, {"homes": len(found), "requests": used, "days": days})

    def do_POST(self):
        """Log a "Stopped By" visit (JSON {parcel_id, outcome, notes} to /visits) or refresh recent sales."""
        if not self.authorized():
            return
        path = urllib.parse.urlsplit(self.path).path
        if not path.endswith(("/visits", "/sales/refresh")):
            return self._json(404, {"error": "not found"})
        # Requiring a JSON body blocks cross-site form posts, which cannot set this content type.
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._json(415, {"error": "expected application/json"})
        if path.endswith("/sales/refresh"):
            try:
                return self.refresh_sales(json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 2000)) or b"{}"))
            except ValueError:
                return self._json(400, {"error": "expected a JSON object"})
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= 20000:
            return self._json(413, {"error": "request too large"})
        try:
            pid, outcome, notes = assessor.validate_visit(json.loads(self.rfile.read(length)))
        except ValueError as exc:  # includes malformed JSON
            return self._json(400, {"error": str(exc)})
        self._json(200, {"visit": self.save_visit(pid, outcome, notes, self.visitor())})

    def _json(self, code, obj):
        self._send(code, "application/json", json.dumps(obj).encode())

    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if not self.authorized():
            return
        if url.path.endswith("favicon.ico"):
            return self._send(404, "text/plain", b"not found")
        con = self.open_db()
        try:
            if not url.path.endswith("/export.csv"):
                self._send(200, "text/html; charset=utf-8", self.render_page(con, qs).encode())
            else:
                city, min_score, include_all = _filters(qs)
                buf = io.StringIO()
                assessor.write_csv(assessor.query_parcels(con, not include_all, city, min_score), buf)
                self._send(200, "text/csv; charset=utf-8", buf.getvalue().encode(),
                           {"Content-Disposition": 'attachment; filename="flagged_parcels.csv"'})
        finally:
            con.close()

    def _send(self, code, ctype, data, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"serving on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
