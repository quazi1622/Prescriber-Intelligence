# Prescriber Intelligence — Browser license administration

## Deploy (Cloudflare dashboard, no CLI required)

1. Open the **prescriber-license** Worker in Cloudflare **Workers & Pages**.
2. Open **Edit code**, replace the existing `worker.js` content with the **entire** latest file from [cloudflare/src/index.js](https://github.com/quazi1622/Prescriber-Intelligence/blob/main/cloudflare/src/index.js), and click **Deploy**. Do **not** paste the JavaScript into the D1 SQL console.
3. Leave the existing binding named `DB` and secrets `ADMIN_TOKEN` and `SIGNING_KEY_PKCS8_B64` unchanged.
4. Visit `https://prescriber-license.sayera1900.workers.dev/admin` in a browser.
5. Enter the existing **ADMIN_TOKEN** (not the signing key). It is kept in page memory, not local/session storage. **Sign out** or close the tab when finished.
6. Approve or block pending registrations using the buttons. Confirm actions in the browser dialog. The API automatically increments the database revision when you make changes; **do not also run manual SQL to increment it**.
7. For a whole-PC block, use **Block entire PC** on a registered installation with a machine hash. This affects installations on that physical computer even across Windows accounts.
8. Use **Disable all online access** to shut down online licensing globally; **Restore global access** to reverse. Previously approved offline installations remain usable until they reconnect.

## Security and operational notes

- Dashboard route: `GET /admin`. JavaScript route: `GET /admin/app.js`. Both are public static resources without credentials. All actual device data and mutations require an administrator Bearer token via the existing `/admin/*` API.
- Private signing keys must remain only in Cloudflare Secrets. The administrator token must not be embedded in the Worker code, URL, bookmarks, application or GitHub repository.
- Keep the dashboard on HTTPS, avoid untrusted browser extensions, and sign out when done. The token is in memory and sent only in the HTTPS Authorization header to same-origin Worker requests.
- The dashboard lists up to 500 most-recently-seen registrations because the existing admin API has a 500-row limit. The counters summarize **returned registrations**, not necessarily all registered computers.
- The displayed effective status includes global shutdown and machine-level blocking overrides; the underlying device status may remain approved.
- Windows usernames and hostnames are self-reported by clients and should **not** be treated as strong identity verification. Registration alone never grants access.
- Network connectivity is required for new approvals and remote revocations. Existing approved offline installations retain access until they reconnect.
- Do not enable Cloudflare Access without separately supporting machine-to-machine authentication for the desktop client.
- Check Cloudflare Worker Logs for server errors and GitHub Actions for the JavaScript admin regression tests.

## API operations used by the dashboard

- `GET /admin/devices`: list devices, machine blocks, global state and authorization revision.
- `POST /admin/device`: `{device_id, status: "approved"|"blocked"|"pending"}`.
- `POST /admin/machine`: `{machine_hash, blocked: boolean}`.
- `POST /admin/global`: `{enabled: boolean}`.

All mutation endpoints automatically advance the revision. Avoid editing the same device simultaneously in D1 and the dashboard.
