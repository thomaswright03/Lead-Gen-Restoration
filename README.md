# Salt Lake County assessor condition scraper (Phase 1)

Checked 2026-09-29.

## What condition data exists

Every residential parcel page (`valuationInfoExpanded.cfm?parcel_id=<14 digits>`) has a Residence Record with appraiser-coded ratings. The scale comes from the county's own field definitions (`FieldDescriptions/residenceRecord.html`):

| Field | Values | Useful for flagging? |
|---|---|---|
| Overall / Interior / Exterior Condition | Excellent, Very Good, Good, Average, **Fair** ("maintenance, rehabilitation, and replacement needed on many items"), **Poor** ("major repairs needed"); Overall also allows Special (obsolescence) | Yes, the main signal |
| Visual Appeal | Superior / Average / Poor (curb appeal vs. neighborhood) | Weak extra signal |
| Detached structure Condition | Same scale, per garage/shed | Small extra signal |
| Kitchen / Bath Quality | Luxury / Modern / Standard / Basic | Quality of finish, not condition |
| Maintenance | High / Average / Minimum | Material type, not condition; ignored |
| Year Built vs Effective Year Built | years | Good proxy for "never renovated" |

There is no room-by-room condition. The finest granularity is interior vs exterior (plus garage). Data on the page is a CAMA snapshot ("as it was, on May 22, 2026"), so it refreshes roughly yearly.

## Access and legal notes

- robots.txt (`apps.saltlakecounty.gov/robots.txt`): the `Disallow` rules sit under `User-agent: ReadableBot`; nothing blocks the assessor detail pages for other agents. `/search` is listed and the parcel search results page loads reCAPTCHA v3. This tool never uses the search or touches the captcha: it goes straight to detail pages by parcel ID.
- County disclaimer (`saltlakecounty.gov/disclaimer/`) is an as-is/no-warranty notice. There's no terms-of-use clause about automated access or commercial use.
- Detail pages carry `<meta name="robots" content="noindex, nofollow">`. That's aimed at search engines, not a use restriction.
- **Official alternative:** the Assessor sells the full CAMA database (residential and commercial characteristics) for **$1,500** (listed as the 2025 database; call 385-468-7972 or email assessor@slco.org for a sample). For countywide coverage this is the sanctioned route and avoids ~395k page requests.
- **Free open data:** Utah UGRC's `Parcels_SaltLake_LIR` feature service lists all 394,610 parcels with parcel ID, address, year built, effective year built, value and primary-residence flag. It has no condition field and no owner name. It makes a free candidate list, and sorting by oldest effective year surfaced three Poor-condition homes out of three checked.
- I found nothing here that forbids this use. The outreach side (phone/text rules, door-to-door solicitor permits, referral-fee arrangements) wasn't researched and deserves a legal check before anyone contacts owners.

## Usage

Python 3 standard library only.

```
python3 assessor.py fetch 16-16-158-010-0000 16184590180000   # or --file parcels.txt
python3 assessor.py export flagged.csv          # flagged only; --all for everything
```

- Raw HTML cached in `cache/`, results in `assessor.db` (SQLite, table `parcels`, full parsed record in `raw_json`).
- One request every 3 s, honest User-Agent, one fetch per parcel unless `--refresh`.
- `cache/`, `assessor.db` and CSV exports are git-ignored because they contain owner names.
- Scoring lives in `rules.json` (points per field value, `flag_threshold`, default 2 = any Fair or worse on overall/interior/exterior).

## Sample run

| Parcel | Address | Overall / Int / Ext | Score | Flagged |
|---|---|---|---|---|
| 16184590180000 | 435 E Redondo Ave | Poor / Poor / Poor (type 993 "RESID (SALVAGE)") | 12 | yes |
| 16051780130000 | 858 E 200 S | Poor / Poor / Poor (LLC owner) | 10 | yes |
| 16064800070000 | 578 E 600 S | Poor / Fair / Poor | 9 | yes |
| 16161580100000 | 1450 E 1700 S | Average / Average / Average | 0 | no |
