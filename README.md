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
