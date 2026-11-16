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
