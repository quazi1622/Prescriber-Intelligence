# Prescriber Intelligence — Emerald Edition

Portable Windows desktop application using PySide6 and embedded DuckDB.

## Source and build
Run GitHub Actions workflow **Build portable Windows application** or `build_windows.bat` on a Windows development PC. Download the artifact ZIP, extract, and launch `Prescriber_Intelligence.exe` without administrator installation.

## Local data
The prescription and field-force data must remain on the user's PC. Create a writable `data` folder beside the executable and use:
- `rx_source.xlsx`: September prescription workbook
- `field_force.xlsx`: territory/personnel hierarchy
- `acd_recipient_audit.csv`: ACD region recipient audit

Import the workbook in the app. 51 ACD email drafts are generated locally as .eml files; no email is automatically sent. Verify missing recipient mappings and reporting metrics before sending.

This is an initial build: native Windows end-to-end runtime testing remains necessary.


## Product analytics and formatted email reports

- Import your latest Rx Excel worksheet in **Data / Import**. Re-import once after upgrading to create the local `rx_items` table for Brand and Generic filtering.
- Under **Analytics**, filter division (ACD/CCD), RSE, ASE, territory, Generic and Brand; choose Top 1–20.
- **APP (Apparent Prescription Preference)** is an observed share, not a proven clinical prescribing preference: distinct Rx for the selected brand divided by all observed distinct Rx for the same doctor in the selected generic, or all observed Rx if no generic is chosen. APP is blank unless a brand is selected.
- **Email Drafts** uses an HTML body inspired by the supplied five-page Azithrocin Rx report: teal heading, KPI blocks, action points, ranked prescribers, brand shares, competitors and MPE-level Top N.
- Email reports intentionally show the broader selected-generic comparison even when a target Brand is selected, so doctors writing competitor brands appear in the follow-up section. The dashboard Brand filter is more restrictive.
- Only ACD routing with verified RSE (To), ASE and parent ZSI (CC) is implemented. Unresolved groups remain blocked. **Nothing is sent automatically.**
- Report bodies have a plain-text fallback, and are stored as portable `.eml` drafts. No prescription CSV is attached.
- No national survey share, company attribution, or national rank is fabricated. The imported file supplies only locally observed Rx counts, which may not represent actual total prescribing behavior.

## Building

Pushes to `main` trigger the Windows Actions workflow with synthetic import, hierarchy and HTML-report tests before building. Check GitHub Actions for a green result and download its artifact. Compilation, Windows execution and real 700k-row stress testing must be verified independently.


## Beximco brand / competitor Rx share by generic

After updating, re-import the Excel Rx worksheet so `rx_items` includes the `Company Name` field. Then choose a **Generic** in the Analytics tab.

- **Beximco Brand Rx Share (%)** = unique observed prescriptions for the generic containing any brand with `Company Name` normalized to a value beginning with `Beximco`, divided by all unique observed prescriptions for that generic in the selected division, region, ASE and MPE.
- **Competitor Rx Share (%)** = unique observed prescriptions for the generic containing a nonempty `Company Name` not classified as Beximco, divided by the **same** generic prescription denominator.
- **Unclassified Company Share (%)** = prescriptions containing at least one row without a company name; do not assume they belong to competitors.
- **Overlapping Rx** = prescriptions that list both Beximco and competitor manufacturers. The two shares can sum above 100%; each is a prescription-presence share rather than an exclusive unit market share.
- **Selected Brand Share (%)** = unique observed prescriptions containing the selected brand divided by the generic total. This is distinct from aggregate **Beximco Brand Rx Share**, which includes all identified Beximco brands.

The report emails now include Beximco / competitor KPI tiles and a ranked **Leading competitor brands** table with distinct Rx counts and shares. Reports are still sent as unsent, locally generated, HTML-bodied `.eml` files with no CSV attachment. The exact `Company Name` source values should be audited for aliases before using this as an operational metric (e.g., abbreviations should not be silently interpreted as a manufacturer).

All shares refer to the imported observed sample, not a verified population market share. **Generic selection is mandatory** for manufacturer shares; unfiltered data do not yield a clinically meaningful denominator.


## Revised doctor-level Rx Share Analytics

Select a **Generic** (for example, Azithromycin) and a target **Brand** (Azithrocin is automatically selected when available). The top-prescriber table is grouped by ACD/CCD → RSE → ASE → MPE and **ranked by descending distinct Rx count for the selected generic**, with target-brand count and competitor count used as tie-breakers. The three shares for each doctor use:

1. **Generic Rx Share (%)** = doctor's distinct Rx containing the selected generic / doctor's distinct Rx for all generics, within the same territory × 100.
2. **Azithrocin / Selected Brand Rx Share (%)** = doctor's distinct selected-brand Rx / doctor's distinct Rx for the selected generic, within that territory × 100.
3. **Competitor Rx Share (%)** = doctor's distinct selected-generic Rx featuring a non-Beximco manufacturer / doctor's distinct Rx for that generic, within the territory × 100.

The main KPI cards aggregate these shares over the selected division, region, ASE and territory using distinct Rx numerators/denominators, rather than averaging doctor percentages. Competitor-only selection does not artificially narrow the denominator.

**Competitor brand share table:** This is **always grouped at the RSE regional level** within the selected generic. Choosing an ASE or MPE affects the doctor-level table and KPI cards, but **does not change the competitor-brand table**. If all RSE regions are selected, rows include the RSE code and each brand's **regional** generic-Rx denominator. Rows are sorted by observed competitor-brand Rx descending *within each region* (equivalent to share descending because the region's denominator is fixed).

Shares reflect observed Rx presence and can overlap if one Rx lists multiple brands/manufacturers. Empty Company Name is unclassified, not assumed to be a competitor. A single prescription must have a reliable unique Rx identifier. For the new ranking, the same Rx key is deduplicated per doctor/territory. Data remain local and are not uploaded to GitHub.


## Searchable dropdowns in Analytics

Every Analytics selection list—Division, RSE/Region, ASE, Territory, Generic and Brand—now includes an **editable search field, dropdown arrow and an adjacent ⌕ search button**. Type any part of an option (matching is case-insensitive), then select a suggestion, or use the arrow for the full list. The search button displays matching options; if the current selection hasn't been edited, it opens all alternatives. The Top N control remains numeric (1–20), rather than a text dropdown.

Partial search text is **not** accepted as a filter: the prior committed selection remains in force until a known option is chosen. Dependent filters (Region → ASE → Territory; Generic → Brand) are repopulated from imported local data, and the app retains any valid previous selection. This is client-side filtering over already loaded choice lists; no extra backend load occurs on every keystroke.


## Outlook + mobile email drafts (latest)

The **Email Drafts** tab now has an independent **Top N prescribers per MPE** numeric selector (1–20; default 10), separate from Analytics Top N. Every regional HTML email contains **up to N ranked doctors for each ASE/MPE territory**—not merely N doctors for the entire region—and adds a concise regional preview.

Each regional email includes the **regional competitor-wise brand and manufacturer breakdown** (distinct Rx share with that RSE's generic Rx as the denominator), top 12 observed brands, top 20 competitor brand/manufacturer combinations, and an opportunity section showing **only doctors with confirmed competitor-manufacturer Rx AND zero observed selected-brand Rx**. Top-N and abbreviated sections explicitly disclose their limits and total qualifying entries. Generic Rx share also discloses the all-product denominator. Shares represent observed samples, not national market share.

The 640 px desktop design keeps Outlook's Word-rendered table fallback with Tahoma and inline CSS. Email clients that support mobile media queries render a fluid-width report, 2-column KPI tiles and vertically stacked, labeled data rows on narrow screens. **Classic desktop Outlook does not support every responsive CSS feature**, and actual rendering still requires testing in classic Outlook, new Outlook, and Outlook Mobile.

The generator writes local, unsent HTML + text `.eml` files, **no CSV attachment**. Emails include draft metadata (`X-Unsent`, `Date`, and `Message-ID`). A **Sender Email (optional)** control sets `From` only to an address supplied by the operator; the app does not invent or spoof an address. Addresses and personal reports remain local. Regenerate drafts after installing a successful new Windows build to see the changes.
