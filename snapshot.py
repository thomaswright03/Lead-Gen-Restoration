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
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
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
.chip.listed { background: var(--accent-soft); color: var(--accent); }
.distress { color: var(--poor); }
td.small { white-space: normal; min-width: 9em; }
.score { font: 600 13px var(--mono); }
.empty { padding: 24px; text-align: center; color: var(--muted); }
.howto { padding: 14px; font-size: 13px; color: var(--muted); display: grid; gap: 6px; }
.howto p { margin: 0; }
@media (prefers-reduced-motion: no-preference) { .city .bar i { transition: width .3s ease; } }
/* Map of the filtered homes, with the viewer's live location for door-knocking. */
.mapbox { padding: 12px; display: grid; gap: 10px; }
.maphead { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; }
.maphead h2 { font: 600 13px/1.2 var(--display); letter-spacing: .02em; margin: 0; }
.maphead .status { flex: 1 1 16em; }
#map { height: 440px; border-radius: 6px; border: 1px solid var(--line); z-index: 0; }
@media (max-width: 820px) { #map { height: 62vh; } }
.legend { display: flex; gap: 12px; font-size: 12px; color: var(--muted); }
.legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: -1px; }
.leaflet-popup-content-wrapper, .leaflet-popup-tip { background: var(--panel); color: var(--fg); }
.leaflet-popup-content { font: 13px/1.45 var(--body); margin: 10px 12px; }
.leaflet-popup-content b { font-weight: 600; }
.leaflet-popup-content a { color: var(--accent); }
.leaflet-container a.leaflet-popup-close-button { color: var(--muted); }
.pop-links { display: flex; gap: 12px; margin-top: 6px; }
td.dist { font: 500 13px var(--mono); }
td.dist a { font: 500 12px var(--body); color: var(--accent); margin-left: 6px; }
td.addr button { all: unset; cursor: pointer; }
td.addr button:hover { text-decoration: underline; }
td.addr button:focus-visible { outline: 2px solid var(--accent); }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(.85) contrast(.9); } }
:root[data-theme="dark"] .leaflet-tile-pane { filter: invert(1) hue-rotate(180deg) brightness(.85) contrast(.9); }
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
        <label for="activity">Sales activity<select id="activity">
          <option value="">Any</option><option value="sold">Sold in last 12 months</option><option value="listed">For sale now</option><option value="distress">Distress filing (3 yrs)</option>
        </select></label>
        <label for="minscore">Min score<select id="minscore"><option value="0">Any</option><option value="3">3+</option><option value="6">6+</option><option value="9">9+</option></select></label>
        <label class="check" for="all"><input id="all" type="checkbox"> Include not flagged</label>
        <div class="actions">
          <span class="status" id="status" role="status"></span>
          <button class="btn" type="button" id="copy">Copy CSV</button>
          __DOWNLOAD__
        </div>
      </form>
      <div class="panel mapbox" id="mapbox">
        <div class="maphead">
          <h2>Map</h2>
          <span class="status" id="mapstatus" role="status"></span>
          <div class="legend" aria-hidden="true"><span><i style="background:var(--poor)"></i>Poor</span><span><i style="background:var(--fair)"></i>Fair</span><span><i style="background:var(--accent)"></i>You</span></div>
          <button class="btn" type="button" id="locate">Find homes near me</button>
        </div>
        <div id="map" role="region" aria-label="Map of the homes in the table"></div>
      </div>
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

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
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
  ["last_transfer_date", "Last transfer", "transfer"], ["listing_status", "Listing", "listing"],
];
const state = { city: "", sort: "score", dir: -1 };
const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const money = v => Number(String(v || "").replace(/[^0-9.]/g, "")) || 0;
const condKey = v => (v || "").split(" ")[0];
const YEAR_AGO = new Date(Date.now() - 365 * 864e5).toISOString().slice(0, 10);

// First visit: start on the Poor homes, the door-knocking list. Saved filters win after that.
$("cond").value = "POOR";
try { const saved = JSON.parse(localStorage.getItem("pcp-filters") || "{}"); Object.assign(state, saved.state || {});
  for (const id of ["q", "cond", "minscore", "activity"]) if (saved[id] != null) $(id).value = saved[id];
  $("all").checked = !!saved.all; } catch (e) {}

function save() { try { localStorage.setItem("pcp-filters", JSON.stringify({ state, q: $("q").value, cond: $("cond").value, minscore: $("minscore").value, activity: $("activity").value, all: $("all").checked })); } catch (e) {} }

function filtered() {
  const q = $("q").value.trim().toLowerCase(), cond = $("cond").value, min = +$("minscore").value, all = $("all").checked;
  const act = $("activity").value;
  return DATA.rows.filter(r => (all || r.flagged)
    && (!state.city || r.city === state.city)
    && r.score >= min
    && (!act || (act === "sold" ? (r.last_transfer_date || "") >= YEAR_AGO : act === "listed" ? r.listing_status === "Active" : !!r.distress_filings))
    && (!cond || (cond === "CONDO" ? !r.overall_condition && r.interior_condition : condKey(r.overall_condition) === cond))
    && (!q || (r.address || "").toLowerCase().includes(q) || (SHOW_OWNER && (r.owner || "").toLowerCase().includes(q)) || r.parcel_id.includes(q)));
}

function sorted(rows) {
  const k = state.sort, d = state.dir;
  const val = r => k === "distance" ? (r._dist ?? Infinity) : k === "market_value" ? money(r[k]) : k === "listing_status" ? (r[k] === "Active" ? 2 : r[k] ? 1 : 0) : (["score", "year_built", "effective_year_built"].includes(k) ? Number(r[k]) || 0 : String(r[k] || "").toLowerCase());
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
  if (cls === "transfer") return `<td class="small">${v ? `${esc(v)}<br>${esc((r.last_transfer_type || "").toLowerCase())}` : ""}${r.distress_filings ? `<br><span class="distress">${esc(r.distress_filings)}</span>` : ""}</td>`;
  if (cls === "listing") {
    if (!v) return "<td></td>";
    const contact = [r.agent_name, r.agent_phone, r.agent_email].filter(Boolean).map(esc).join(" · ");
    const office = [r.office_name, r.office_phone].filter(Boolean).map(esc).join(" · ");
    const price = r.listing_price ? " $" + Number(r.listing_price).toLocaleString() : "";
    return `<td class="small"><span class="chip ${v === "Active" ? "listed" : "none"}">${esc(v)}</span>${price}${contact ? `<br>${contact}` : ""}${office ? `<br>${office}` : ""}</td>`;
  }
  if (cls === "num dist") return `<td class="dist">${r._dist == null ? "" : miles(r._dist)}${r.lat ? `<a href="${directions(r)}" target="_blank" rel="noopener">Directions</a>` : ""}</td>`;
  if (cls === "addr") return `<td class="addr">${r.lat ? `<button type="button" data-pid="${esc(r.parcel_id)}" title="Show on map">${esc(v)}</button>` : esc(v)}</td>`;
  if (key === "market_value") return `<td class="num">${esc(String(v || "").replace(/\s+/g, ""))}</td>`;
  return `<td class="${cls}">${esc(v)}</td>`;
}

function render() {
  const rows = sorted(filtered());
  const cols = here ? [["distance", "Distance", "num dist"], ...COLS] : COLS;
  if (!here && state.sort === "distance") { state.sort = "score"; state.dir = -1; }
  $("head").innerHTML = cols.map(([k, label, cls]) => `<th class="${cls.includes("num") ? "num" : ""}" data-k="${k}" tabindex="0" aria-sort="${state.sort === k ? (state.dir > 0 ? "ascending" : "descending") : "none"}">${label}</th>`).join("");
  $("body").innerHTML = rows.length ? rows.map(r => `<tr title="${esc(r.reasons)}">${cols.map(c => cell(r, c)).join("")}</tr>`).join("")
    : `<tr><td class="empty" colspan="${cols.length}">No parcels match these filters.</td></tr>`;
  $("status").textContent = `${rows.length} shown`;
  renderCities();
  drawMap(rows);
  save();
}

// ---- Map and location -------------------------------------------------------------------------
let map = null, layer = null, meDot = null, meRing = null, here = null, watchId = null, fitted = false, lastDrawn = null;
const markers = {};
const miles = d => d < 0.1 ? `${Math.round(d * 5280 / 10) * 10} ft` : `${d.toFixed(d < 10 ? 1 : 0)} mi`;
const directions = r => `https://www.google.com/maps/dir/?api=1&destination=${r.lat},${r.lon}`;
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function haversine(a, b, c, d) {
  const R = 3958.8, rad = x => x * Math.PI / 180, dLat = rad(c - a), dLon = rad(d - b);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a)) * Math.cos(rad(c)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function popup(r) {
  const conds = [["Overall", r.overall_condition], ["Interior", r.interior_condition], ["Exterior", r.exterior_condition]]
    .filter(x => x[1]).map(([k, v]) => `${k} <span class="chip ${esc(condKey(v))}">${esc(v)}</span>`).join(" ");
  return `<b>${esc(r.address)}</b>${r.city ? `, ${esc(r.city)}` : ""}<br>${conds}<br>Score ${esc(r.score)} · built ${esc(r.year_built || "?")}`
    + (SHOW_OWNER && r.owner ? `<br>${esc(r.owner)}` : "")
    + (r.last_transfer_date ? `<br>Last transfer ${esc(r.last_transfer_date)}` : "")
    + (r.listing_status === "Active" ? `<br><span class="chip listed">For sale</span> ${esc(r.agent_name || "")} ${esc(r.agent_phone || "")}` : "")
    + (r._dist != null ? `<br>${miles(r._dist)} away` : "")
    + `<div class="pop-links"><a href="${directions(r)}" target="_blank" rel="noopener">Directions</a><a href="${DETAIL}${esc(r.parcel_id)}" target="_blank" rel="noopener">County record</a></div>`;
}
function initMap() {
  if (!window.L) { $("mapstatus").textContent = "The map could not load here."; $("map").hidden = true; $("locate").hidden = true; return; }
  map = L.map("map", { preferCanvas: true, scrollWheelZoom: false }).setView([40.66, -111.93], 11);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }).addTo(map);
  map.on("focus", () => map.scrollWheelZoom.enable());
  map.on("blur", () => map.scrollWheelZoom.disable());
  layer = L.layerGroup().addTo(map);
}
function drawMap(rows) {
  if (!map) return;
  layer.clearLayers();
  for (const k in markers) delete markers[k];
  const colors = { POOR: css("--poor"), SPEC: css("--poor"), FAIR: css("--fair") };
  const pts = [];
  for (const r of rows) {
    if (r.lat == null) continue;
    const color = colors[condKey(r.overall_condition || r.interior_condition)] || css("--muted");
    const m = L.circleMarker([r.lat, r.lon], { radius: 6, weight: 1.5, color: css("--panel"), fillColor: color, fillOpacity: .9 })
      .bindPopup(() => popup(r), { maxWidth: 280 });
    m.addTo(layer); markers[r.parcel_id] = m; pts.push([r.lat, r.lon]);
  }
  const near = here && rows.filter(r => r._dist != null).reduce((a, r) => (!a || r._dist < a._dist ? r : a), null);
  $("mapstatus").textContent = `${pts.length} ${pts.length === 1 ? "home" : "homes"} on the map`
    + (near ? ` · nearest is ${miles(near._dist)} away` : "");
  // Frame the results until the viewer's location takes over.
  if (!here && pts.length && (!fitted || lastDrawn !== pts.length)) { map.fitBounds(pts, { padding: [20, 20], maxZoom: 15, animate: false }); fitted = true; }
  lastDrawn = pts.length;
}
function setHere(pos) {
  const first = !here, { latitude: lat, longitude: lon, accuracy } = pos.coords;
  const moved = here ? haversine(here[0], here[1], lat, lon) * 5280 : Infinity;
  here = [lat, lon];
  if (map) {
    if (!meDot) {
      meRing = L.circle(here, { radius: accuracy, color: css("--accent"), weight: 1, fillOpacity: .08, interactive: false }).addTo(map);
      meDot = L.circleMarker(here, { radius: 8, color: "#fff", weight: 3, fillColor: css("--accent"), fillOpacity: 1 }).bindTooltip("You").addTo(map);
    } else { meDot.setLatLng(here); meRing.setLatLng(here).setRadius(accuracy); }
  }
  if (first || moved > 100) {  // re-sort when the viewer has walked about a block
    for (const r of DATA.rows) r._dist = r.lat == null ? null : haversine(lat, lon, r.lat, r.lon);
    if (first) state.sort = "distance", state.dir = 1;
    render();
    if (first && map) {  // frame the viewer with the five closest homes
      const near = sorted(filtered()).filter(r => r._dist != null).slice(0, 5).map(r => [r.lat, r.lon]);
      map.fitBounds([here, ...near], { padding: [30, 30], maxZoom: 17, animate: false });
    }
  }
}
function locErr(err) {
  const msg = err.code === 1 ? "Location is blocked. Allow it for this site in your browser settings to see what's nearby."
    : "Couldn't get your location. Try again outdoors or with Wi-Fi on.";
  $("mapstatus").textContent = msg; stopWatch();
}
function stopWatch() { if (watchId != null) navigator.geolocation.clearWatch(watchId); watchId = null; $("locate").textContent = "Find homes near me"; }
function locate() {
  if (!("geolocation" in navigator)) { $("mapstatus").textContent = "This browser can't share your location."; return; }
  if (watchId != null) { stopWatch(); return; }
  $("mapstatus").textContent = "Finding your location…";
  watchId = navigator.geolocation.watchPosition(setHere, locErr, { enableHighAccuracy: true, maximumAge: 15000, timeout: 20000 });
  $("locate").textContent = "Stop following me";
  if (here && map) map.setView(here, Math.max(map.getZoom(), 15));
}

function csv(rows) {
  const keys = ["parcel_id", "address", "city", ...(SHOW_OWNER ? ["owner"] : []), "property_type", "year_built", "effective_year_built", "market_value", "overall_condition", "interior_condition", "exterior_condition", "visual_appeal", "score", "reasons", "last_transfer_date", "last_transfer_type", "distress_filings", "listing_status", "listing_price", "listed_date", "agent_name", "agent_phone", "agent_email", "office_name", "office_phone"];
  const q = v => { const s = String(v ?? "").replace(/\s+/g, " ").trim(); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [keys.join(","), ...rows.map(r => keys.map(k => q(r[k])).join(","))].join("\n");
}

$("t-cand").textContent = DATA.candidates.toLocaleString();
$("t-checked").textContent = DATA.rows.length.toLocaleString();
$("t-flag").textContent = DATA.rows.filter(r => r.flagged).length.toLocaleString();
$("t-poor").textContent = DATA.rows.filter(r => condKey(r.overall_condition) === "POOR").length.toLocaleString();

$("controls").addEventListener("input", render);
$("locate").addEventListener("click", locate);
$("body").addEventListener("click", e => { const b = e.target.closest("button[data-pid]"); const m = b && markers[b.dataset.pid];
  if (!m) return; map.setView(m.getLatLng(), Math.max(map.getZoom(), 17)); m.openPopup(); $("mapbox").scrollIntoView({ behavior: "smooth", block: "start" }); });
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
initMap();
render();
locate();  // asks for the viewer's location on load; the button retries or stops it
</script>
"""


DOC_HEAD = '<!doctype html>\n<html lang="en">\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'


def build(con, show_owner=True, artifact=False):
    rows = assessor.query_parcels(con, flagged_only=False)
    keep = [c for c in assessor.EXPORT_COLS if c not in ("cama_as_of", "scraped_at") and (show_owner or c != "owner")]
    rows_out = [{k: r[k] for k in keep} for r in rows]
    for r in rows_out:  # about 1 m precision is plenty for a map pin and keeps the page small
        for k in ("lat", "lon"):
            if r[k] is not None:
                r[k] = round(float(r[k]), 5)
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
