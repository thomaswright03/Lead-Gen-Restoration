#!/usr/bin/env python3
"""Write a self-contained HTML snapshot of the results (filters, sorting and CSV built in).

    python3 snapshot.py snapshot.html [--no-owner] [--artifact]

The page embeds the data, so it opens from disk or any static host.
--no-owner drops owner names. --artifact writes a bare fragment without the download button,
for hosts that add their own document wrapper and block downloads.
"""
import argparse
import datetime as dt
import html
import json

import assessor

TEMPLATE = r"""<title>Poor Condition Parcels</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: header with the run's totals, a by-city bar list that doubles as a filter, then the working table. */
:root {
  --bg: #f6f7f9; --panel: #ffffff; --fg: #1b2230; --muted: #5d6778; --line: #dfe3ea;
  --accent: #2748a8; --accent-soft: #e6ebf8;
  --poor: #b42318; --poor-soft: #fde8e6; --fair: #a15c07; --fair-soft: #fdf0dc; --ok: #3b6e4f; --ok-soft: #e4f1e8;
  --display: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #11151c; --panel: #181e27; --fg: #e6e9ef; --muted: #98a2b3; --line: #2a3240;
  --accent: #8ea8ff; --accent-soft: #1f2a47;
  --poor: #ff8a80; --poor-soft: #3a1a18; --fair: #f5b866; --fair-soft: #36280f; --ok: #8fd0a6; --ok-soft: #16301f;
  color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #11151c; --panel: #181e27; --fg: #e6e9ef; --muted: #98a2b3; --line: #2a3240;
  --accent: #8ea8ff; --accent-soft: #1f2a47;
  --poor: #ff8a80; --poor-soft: #3a1a18; --fair: #f5b866; --fair-soft: #36280f; --ok: #8fd0a6; --ok-soft: #16301f;
  color-scheme: dark; }
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font: 14px/1.45 var(--body); margin: 0; }
.wrap { max-width: 1320px; margin: 0 auto; padding-inline: 16px; padding-block: 24px 48px; display: grid; gap: 20px; }
header { display: grid; gap: 6px; }
.eyebrow { font: 500 11px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h1 { font: 600 28px/1.1 var(--display); margin: 0; text-wrap: balance; }
.sub { color: var(--muted); max-width: 70ch; margin: 0; }
.totals { display: flex; flex-wrap: wrap; gap: 8px 28px; margin-top: 6px; }
.total { display: grid; }
.total b { font: 600 24px/1.1 var(--display); font-variant-numeric: tabular-nums; }
.total span { color: var(--muted); font-size: 12px; }
.total.poor b { color: var(--poor); }
.grid { display: grid; grid-template-columns: minmax(0, 260px) minmax(0, 1fr); gap: 20px; align-items: start; }
@media (max-width: 820px) { .grid { grid-template-columns: minmax(0, 1fr); } #cities { max-height: 190px; overflow-y: auto; } }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; }
.cities { padding: 14px; display: grid; gap: 4px; }
.cities h2, .howto h2 { font: 600 13px/1.2 var(--display); letter-spacing: .02em; margin: 0 0 6px; }
.city { all: unset; box-sizing: border-box; width: 100%; cursor: pointer; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 8px; padding: 5px 6px; border-radius: 5px; }
.city:hover, .city:focus-visible { background: var(--accent-soft); }
.city:focus-visible { outline: 2px solid var(--accent); }
.city[aria-pressed="true"] { background: var(--accent-soft); color: var(--accent); font-weight: 600; }
.city .n { font: 500 12px var(--mono); font-variant-numeric: tabular-nums; color: var(--muted); }
.city .bar { grid-column: 1 / -1; height: 4px; background: var(--line); border-radius: 2px; overflow: hidden; }
.city .bar i { display: block; height: 100%; background: var(--accent); }
.main { display: grid; gap: 12px; min-width: 0; }
.controls { display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: end; }
.controls label { display: grid; gap: 3px; font-size: 12px; color: var(--muted); }
.controls input[type=search], .controls select { font: inherit; color: var(--fg); background: var(--panel); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; min-width: 0; }
.controls input[type=search] { width: 220px; max-width: 100%; }
.check { display: flex !important; align-items: center; gap: 6px; color: var(--fg) !important; font-size: 13px !important; padding-bottom: 6px; }
.actions { margin-left: auto; display: flex; gap: 8px; align-items: center; }
button.btn { font: 500 13px var(--body); color: var(--accent); background: var(--panel); border: 1px solid var(--accent); border-radius: 6px; padding: 6px 12px; cursor: pointer; }
button.btn:hover { background: var(--accent-soft); }
button.btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.status { font-size: 12px; color: var(--muted); }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); white-space: nowrap; vertical-align: top; }
th { font: 600 12px var(--body); color: var(--muted); position: sticky; top: 0; background: var(--panel); cursor: pointer; user-select: none; }
th[aria-sort="ascending"]::after { content: " ↑"; } th[aria-sort="descending"]::after { content: " ↓"; }
td.num { text-align: right; } th.num { text-align: right; }
td.pid a { font: 400 12px var(--mono); color: var(--accent); text-decoration: none; }
td.pid a:hover { text-decoration: underline; }
td.addr { font-weight: 500; }
td.small { color: var(--muted); font-size: 12px; }
.chip { display: inline-block; font: 600 11px/1 var(--mono); letter-spacing: .03em; padding: 4px 6px; border-radius: 4px; background: var(--ok-soft); color: var(--ok); }
.chip.POOR, .chip.SPEC { background: var(--poor-soft); color: var(--poor); }
.chip.FAIR { background: var(--fair-soft); color: var(--fair); }
.chip.none { background: transparent; color: var(--muted); font-weight: 400; }
.score { font: 600 13px var(--mono); }
.empty { padding: 24px; text-align: center; color: var(--muted); }
.howto { padding: 14px; font-size: 13px; color: var(--muted); display: grid; gap: 6px; }
.howto p { margin: 0; }
@media (prefers-reduced-motion: no-preference) { .city .bar i { transition: width .3s ease; } }
</style>

<div class="wrap">
  <header>
    <div class="eyebrow">Salt Lake County Assessor · condition ratings as of __CAMA__</div>
    <h1>Poor condition parcels</h1>
    <p class="sub">Homes the county appraiser rated Fair (“rehabilitation and replacement needed on many items”) or Poor (“major repairs needed”). Candidates come from the state parcel layer, filtered to an effective year built before 1990. Snapshot built __BUILT__.</p>
    <div class="totals">
      <div class="total"><b id="t-cand">0</b><span>candidates</span></div>
      <div class="total"><b id="t-checked">0</b><span>checked on county site</span></div>
      <div class="total"><b id="t-flag">0</b><span>flagged Fair or worse</span></div>
      <div class="total poor"><b id="t-poor">0</b><span>rated Poor overall</span></div>
    </div>
  </header>

  <div class="grid">
    <aside class="panel cities" aria-label="Flagged by city">
      <h2>Flagged by city</h2>
      <div id="cities"></div>
    </aside>
    <section class="main">
      <form class="controls" id="controls" onsubmit="return false">
        <label for="q">Search address or owner<input id="q" type="search" placeholder="e.g. 900 W"></label>
        <label for="cond">Overall condition<select id="cond">
          <option value="">Any</option><option value="POOR">Poor</option><option value="FAIR">Fair</option><option value="SPEC">Special obsolescence</option><option value="CONDO">Condo (interior only)</option>
        </select></label>
        <label for="minscore">Min score<select id="minscore"><option value="0">Any</option><option value="3">3+</option><option value="6">6+</option><option value="9">9+</option></select></label>
        <label class="check" for="all"><input id="all" type="checkbox"> Include not flagged</label>
        <div class="actions">
          <span class="status" id="status" role="status"></span>
          <button class="btn" type="button" id="copy">Copy CSV</button>
          __DOWNLOAD__
        </div>
      </form>
      <div class="panel tablewrap">
        <table>
          <thead><tr id="head"></tr></thead>
          <tbody id="body"></tbody>
        </table>
      </div>
      <div class="panel howto">
        <h2>Reading the score</h2>
        <p>Overall Poor 4, Special obsolescence 3, Fair 2 · Interior or Exterior Poor 3, Fair 2 · Condo interior Poor 3, Fair 2 · Poor curb appeal 1 · Poor garage or shed 1. Flagged at 2 or more.</p>
      </div>
    </section>
  </div>
</div>

<script>
const DATA = __DATA__;
const SHOW_OWNER = __SHOW_OWNER__;
const DETAIL = "https://apps.saltlakecounty.gov/assessor/new/valuationInfoExpanded.cfm?parcel_id=";
const COLS = [
  ["parcel_id", "Parcel", "pid"], ["address", "Address", "addr"], ["city", "City", ""],
  ...(SHOW_OWNER ? [["owner", "Owner", "small"]] : []),
  ["property_type", "Type", "small"], ["year_built", "Built", "num"], ["effective_year_built", "Eff. built", "num"],
  ["market_value", "Market value", "num"], ["overall_condition", "Overall", "cond"],
  ["interior_condition", "Interior", "cond"], ["exterior_condition", "Exterior", "cond"], ["score", "Score", "num score"],
];
const state = { city: "", sort: "score", dir: -1 };
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = v => Number(String(v || "").replace(/[^0-9.]/g, "")) || 0;
const condKey = v => (v || "").split(" ")[0];

try { const saved = JSON.parse(localStorage.getItem("pcp-filters") || "{}"); Object.assign(state, saved.state || {});
  for (const id of ["q", "cond", "minscore"]) if (saved[id] != null) $(id).value = saved[id];
  $("all").checked = !!saved.all; } catch (e) {}

function save() { try { localStorage.setItem("pcp-filters", JSON.stringify({ state, q: $("q").value, cond: $("cond").value, minscore: $("minscore").value, all: $("all").checked })); } catch (e) {} }

function filtered() {
  const q = $("q").value.trim().toLowerCase(), cond = $("cond").value, min = +$("minscore").value, all = $("all").checked;
  return DATA.rows.filter(r => (all || r.flagged)
    && (!state.city || r.city === state.city)
    && r.score >= min
    && (!cond || (cond === "CONDO" ? !r.overall_condition && r.interior_condition : condKey(r.overall_condition) === cond))
    && (!q || (r.address || "").toLowerCase().includes(q) || (SHOW_OWNER && (r.owner || "").toLowerCase().includes(q)) || r.parcel_id.includes(q)));
}

function sorted(rows) {
  const k = state.sort, d = state.dir;
  const val = r => k === "market_value" ? money(r[k]) : (["score", "year_built", "effective_year_built"].includes(k) ? Number(r[k]) || 0 : String(r[k] || "").toLowerCase());
  return rows.slice().sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * d || a.parcel_id.localeCompare(b.parcel_id));
}

function renderCities() {
  const counts = {};
  for (const r of DATA.rows) if (r.flagged) counts[r.city || "Unknown"] = (counts[r.city || "Unknown"] || 0) + 1;
  const list = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = list.length ? list[0][1] : 1;
  $("cities").innerHTML = [["", "All cities", list.reduce((s, x) => s + x[1], 0)], ...list.map(([c, n]) => [c, c, n])]
    .map(([val, label, n]) => `<button type="button" class="city" data-city="${esc(val)}" aria-pressed="${state.city === val}">
      <span>${esc(label)}</span><span class="n">${n}</span>${val ? `<span class="bar"><i style="width:${(n / max * 100).toFixed(1)}%"></i></span>` : ""}</button>`).join("");
}

function cell(r, [key, , cls]) {
  const v = r[key];
  if (cls === "pid") return `<td class="pid"><a href="${DETAIL}${esc(v)}" target="_blank" rel="noopener">${esc(v)}</a></td>`;
  if (cls === "cond") return `<td>${v ? `<span class="chip ${esc(condKey(v))}">${esc(v)}</span>` : `<span class="chip none">n/a</span>`}</td>`;
  if (key === "market_value") return `<td class="num">${esc(String(v || "").replace(/\s+/g, ""))}</td>`;
  return `<td class="${cls}">${esc(v)}</td>`;
}

function render() {
  const rows = sorted(filtered());
  $("head").innerHTML = COLS.map(([k, label, cls]) => `<th class="${cls.includes("num") ? "num" : ""}" data-k="${k}" tabindex="0" aria-sort="${state.sort === k ? (state.dir > 0 ? "ascending" : "descending") : "none"}">${label}</th>`).join("");
  $("body").innerHTML = rows.length ? rows.map(r => `<tr title="${esc(r.reasons)}">${COLS.map(c => cell(r, c)).join("")}</tr>`).join("")
    : `<tr><td class="empty" colspan="${COLS.length}">No parcels match these filters.</td></tr>`;
  $("status").textContent = `${rows.length} shown`;
  renderCities();
  save();
}

function csv(rows) {
  const keys = ["parcel_id", "address", "city", ...(SHOW_OWNER ? ["owner"] : []), "property_type", "year_built", "effective_year_built", "market_value", "overall_condition", "interior_condition", "exterior_condition", "visual_appeal", "score", "reasons"];
  const q = v => { const s = String(v ?? "").replace(/\s+/g, " ").trim(); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [keys.join(","), ...rows.map(r => keys.map(k => q(r[k])).join(","))].join("\n");
}

$("t-cand").textContent = DATA.candidates.toLocaleString();
$("t-checked").textContent = DATA.rows.length.toLocaleString();
$("t-flag").textContent = DATA.rows.filter(r => r.flagged).length.toLocaleString();
$("t-poor").textContent = DATA.rows.filter(r => condKey(r.overall_condition) === "POOR").length.toLocaleString();

$("controls").addEventListener("input", render);
$("cities").addEventListener("click", e => { const b = e.target.closest(".city"); if (b) { state.city = b.dataset.city; render(); } });
$("head").addEventListener("click", e => { const th = e.target.closest("th"); if (!th) return; const k = th.dataset.k;
  state.dir = state.sort === k ? -state.dir : (["score", "market_value"].includes(k) ? -1 : 1); state.sort = k; render(); });
$("head").addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); e.target.click(); } });
$("copy").addEventListener("click", () => {
  const text = csv(sorted(filtered()));
  navigator.clipboard.writeText(text).then(() => { $("status").textContent = "CSV copied"; },
    () => { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); $("status").textContent = "Press Ctrl+C to copy"; setTimeout(() => ta.remove(), 8000); });
});
const dl = $("download");
if (dl) dl.addEventListener("click", () => {
  const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csv(sorted(filtered()))], { type: "text/csv" }));
  a.download = "poor_condition_parcels.csv"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
});
render();
</script>
"""


DOC_HEAD = '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'


def build(con, show_owner=True, artifact=False):
    rows = assessor.query_parcels(con, flagged_only=False)
    keep = [c for c in assessor.EXPORT_COLS if c not in ("cama_as_of", "scraped_at") and (show_owner or c != "owner")]
    rows_out = [{k: r[k] for k in keep} for r in rows]
    cama = next((r["cama_as_of"] for r in rows if r["cama_as_of"]), "unknown")
    data = {"candidates": con.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], "rows": rows_out}
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    page = (TEMPLATE
            .replace("__DATA__", payload)
            .replace("__SHOW_OWNER__", "true" if show_owner else "false")
            .replace("__CAMA__", html.escape(cama))
            .replace("__BUILT__", dt.date.today().strftime("%B %-d, %Y"))
            .replace("__DOWNLOAD__", '<button class="btn" type="button" id="download">Download CSV</button>' if not artifact else ""))
    return page if artifact else DOC_HEAD + page


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path")
    ap.add_argument("--no-owner", action="store_true", help="leave owner names out of the page")
    ap.add_argument("--artifact", action="store_true", help="bare fragment, no download button")
    args = ap.parse_args()
    page = build(assessor.db(), not args.no_owner, args.artifact)
    with open(args.path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(f"wrote {args.path}")


if __name__ == "__main__":
    main()
