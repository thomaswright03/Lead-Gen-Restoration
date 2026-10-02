# Salt Lake County poor-condition parcel finder

Finds homes the Salt Lake County Assessor has rated in poor condition and lists them for restoration lead generation. Python 3 standard library only.

## How it works

1. **Candidates** come from Utah UGRC's free `Parcels_SaltLake_LIR` layer (394,610 parcels). The assessor's *effective year built* reflects a building's remaining life rather than its age, so homes whose effective year is far in the past are the likely poor ones. The default cutoff is before 1990, which gives about 1,130 parcels countywide.
2. **Fetch** pulls each candidate's county detail page (`valuationInfoExpanded.cfm?parcel_id=<14 digits>`) at one request every 3 seconds. Raw HTML is cached so each page is fetched only once.
3. **Score** applies `rules.json` to the parsed condition ratings and flags parcels at or above the threshold.
4. **Review** the results in the dashboard or export them to CSV.

In the first 24 real candidates checked, 21 came back flagged.

## Usage

```
python3 assessor.py candidates                       # default: effective year built before 1990
python3 assessor.py candidates --max-eff-year 1995 --city "Salt Lake City" --owner-occupied
python3 assessor.py run [--limit 50]                 # fetch + score candidates not fetched yet; safe to stop and resume
python3 assessor.py fetch 16-16-158-010-0000 ...     # specific parcels (or --file parcels.txt)
python3 assessor.py rescore                          # after editing rules.json; no network
python3 assessor.py coords                           # map coordinates for candidates pulled before they were stored
python3 assessor.py export flagged.csv [--all] [--city Murray] [--min-score 9]
python3 dashboard.py [--port 8000]                   # filterable table + CSV download at http://127.0.0.1:8000
python3 snapshot.py results.html [--no-owner]        # one self-contained HTML page with filters, opens from disk
python3 -m unittest discover -s tests                # tests (synthetic pages, no network)
```

- Data lives in `assessor.db` (SQLite: `candidates` from the state layer, `parcels` with scraped results and the full parsed record in `raw_json`) and `cache/`. Set `ASSESSOR_DB` / `ASSESSOR_CACHE` to keep them elsewhere, and `ASSESSOR_DELAY` to change the request spacing.
- The results page has a map of the homes matching the current filters (Poor by default on a first visit). It asks for the viewer's location, sorts the table by distance, follows them as they walk, and links each home to directions. Location needs HTTPS, which the Vercel site has.
- **Recently Sold** pins show Salt Lake County homes sold in the last 90 days, from RentCast property records. Add `RENTCAST_API_KEY` to the Vercel project and press **Refresh sales** on the map; each refresh uses roughly 5 to 15 of the free plan's 50 monthly requests. Locally, `RENTCAST_API_KEY=... python3 sales.py [--days 90]` fills the same table in assessor.db. Utah doesn't disclose sale prices, so most pins have none.
- On the hosted site, each map pin has a **Stopped By** button: add notes, pick an outcome (Interested, Follow Up, Not Interested, Already Handled, Not Qualified, No Contact, Do Not Contact) and Save. Visits go in the Postgres `visits` table with the login username as the visitor, so each person should sign in with their own name. `pgstore.py sync` never touches that table. Knocked homes show as rings in the outcome's colour, and the Knocked filter separates them from homes not visited yet.
- `cache/`, `assessor.db` and CSV exports are git-ignored because they contain owner names.
- If the county returns 403 or 429, `run` stops instead of retrying. Run it again later and it picks up where it left off.

### Scheduling

The county's condition data is a yearly snapshot (the pages currently say "as it was, on May 22, 2026"), so a monthly job is plenty:

```
0 3 1 * *  cd /path/to/repo && python3 assessor.py candidates && python3 assessor.py run --max-age-days 180
```

### Recent sales, distress filings and listing agents

```
python3 recorder.py [--limit 100] [--all]            # free: last deed and distress filings from the county recorder
RENTCAST_API_KEY=... python3 listings.py              # listing agent contact for flagged homes on the market
RENTCAST_API_KEY=... python3 listings.py --status Inactive --days-old 365   # recently delisted or sold
```

- `recorder.py` reads the Recorder's free public search (4 requests per parcel). It stores the last deed (the sale date), the owner of record and any notice of default, trustee's deed, lis pendens, lien or judgment in the last 3 years. Utah is a non-disclosure state, so sale prices and agents are not in public records. A Utah "trust deed" is a mortgage and isn't counted as a sale.
- `listings.py` pulls RentCast sale listings around the Salt Lake Valley (500 per request; the free plan includes 50 requests a month) and matches them to parcels by street address. It stores the price, dates and the listing agent's and office's name, phone and email. RentCast's terms allow lawful direct marketing but prohibit sending unsolicited commercial email with the data.
- The buyer's agent on a past sale is only available from the MLS (UtahRealEstate.com), which requires a broker data license.
- The results page, CSV export and `pgstore.py sync` include these fields. The page has a Sales activity filter: sold in the last 12 months, for sale now, or distress filing.

### Hosting on Vercel

The repo deploys to Vercel as one Python function (`api/index.py`) that serves the results page behind a password. Scraping still runs outside Vercel; results are pushed to Postgres.

1. In the Vercel project, connect a Neon Postgres database (Storage) so `DATABASE_URL` is set, and add a `DASHBOARD_PASSWORD` environment variable. Any username works at the login prompt.
2. After a scrape, push the results: `pip install "psycopg[binary]"`, then `DATABASE_URL=... python3 pgstore.py sync`. Where port 5432 is blocked, `python3 pgstore.py sync --http` uses Neon's HTTPS SQL endpoint instead and needs no driver.

The site refuses to serve anything until `DASHBOARD_PASSWORD` is set, because the results include owner names.

## Scoring

`rules.json` assigns points per field value. The default threshold of 2 flags any Fair or worse rating on overall, interior or exterior condition.

| Field | Points |
|---|---|
| Overall Condition | Poor 4, Special obsolescence ("SPEC OBSOL") 3, Fair 2 |
| Interior / Exterior Condition | Poor 3, Fair 2 |
| Condo unit Interior Condition | Poor 3, Fair 2 |
| Visual Appeal | Poor 1 |
| Detached structure (garage, shed) Condition | Poor 1 |

## What condition data exists

Ratings come from the county's own field definitions (`FieldDescriptions/residenceRecord.html`):

| Field | Values | Used? |
|---|---|---|
| Overall / Interior / Exterior Condition | Excellent, Very Good, Good, Average, **Fair** ("maintenance, rehabilitation, and replacement needed on many items"), **Poor** ("major repairs needed"); Overall also allows special obsolescence | Main signal |
| Condo unit Interior Condition | Same scale as single letters (P, F, A...) | Yes. Condos have no exterior rating |
| Visual Appeal | Superior / Average / Poor (curb appeal vs. neighborhood) | Small extra signal |
| Detached structure Condition | Same scale, per garage/shed | Small extra signal |
| Kitchen / Bath Quality | Luxury / Modern / Standard / Basic | No. Finish level, not wear |
| Maintenance | High / Average / Minimum | No. Describes material type |

There is no room-by-room condition. The finest detail is interior vs exterior, plus garage.

## Access notes

- robots.txt (`apps.saltlakecounty.gov/robots.txt`): the `Disallow` rules sit under `User-agent: ReadableBot`; nothing blocks the detail pages for other agents. The parcel search results page loads reCAPTCHA v3, so this tool never uses the search. It goes straight to detail pages by parcel ID.
- The county disclaimer (`saltlakecounty.gov/disclaimer/`) is an as-is/no-warranty notice with no clause about automated access.
- **Official bulk alternative:** the Assessor sells the full CAMA database for $1,500 (385-468-7972, assessor@slco.org). That database would cover every parcel with no scraping.
- The state layer's effective year can lag the county page, especially for condos, so treat it as a pre-filter only.
