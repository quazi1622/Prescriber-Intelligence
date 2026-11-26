// Cloudflare Worker: signed device decisions, administrator-gated revocation.
// Environment: DB (D1), ADMIN_TOKEN (secret), SIGNING_KEY_PKCS8_B64 (secret).
// Never store prescription datasets or send them to this endpoint.

const headers = { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" };
const json = (value, status=200) => new Response(JSON.stringify(value), {status, headers});
const b64bytes = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const b64 = b => btoa(String.fromCharCode(...new Uint8Array(b)));
const canonical = value => JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a],[b]) => a.localeCompare(b))));
const validId = s => typeof s === "string" && /^[a-zA-Z0-9_-]{1,100}$/.test(s);
const limitText = (s, n=120) => typeof s === "string" ? s.slice(0,n) : "";

async function signed(env, payload) {
  const key = await crypto.subtle.importKey(
    "pkcs8", b64bytes(env.SIGNING_KEY_PKCS8_B64),
    {name:"Ed25519"}, false, ["sign"]);
  const signature = await crypto.subtle.sign("Ed25519",key,
    new TextEncoder().encode(canonical(payload)));
  return {payload, signature:b64(signature)};
}
async function admin(req, env) {
  const auth=req.headers.get("Authorization") || "";
  if (!env.ADMIN_TOKEN || auth !== "Bearer " + env.ADMIN_TOKEN) return false;
  return true;
}
async function revision(env) {
  const row=await env.DB.prepare("SELECT version,enabled FROM settings WHERE id=1").first();
  if(!row) throw Error("Apply D1 migration before starting Worker");
  return row;
}

const adminHtml = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prescriber Intelligence · License Administration</title>
<style>
:root{font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#17313c;background:#f4f7fa}
*{box-sizing:border-box}body{margin:0}header{background:#103e4a;color:#fff;padding:22px max(24px,calc((100vw - 1180px)/2));display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}h1{font-size:23px;margin:0}header p{margin:5px 0 0;color:#b6d9de;font-size:13px}
main{max-width:1180px;padding:24px;margin:auto}section{background:white;border:1px solid #dce5ea;border-radius:14px;margin-bottom:18px;padding:20px;box-shadow:0 2px 10px #183e4810}h2{font-size:16px;margin:0 0 15px}
button,input,select{font:inherit}button{cursor:pointer;border-radius:8px;border:1px solid #b9ccd4;background:white;color:#17313c;padding:8px 12px;font-weight:600}button:hover:not(:disabled){background:#ebf4f5}button:disabled{opacity:.5;cursor:not-allowed}
.primary{background:#087b82;color:white;border-color:#087b82}.primary:hover:not(:disabled){background:#06666c}
.danger{color:#a52d32;border-color:#dcb8b9}.danger:hover:not(:disabled){background:#fff0f0}
input,select{border:1px solid #bdccd2;border-radius:8px;padding:10px;min-width:0}input[type=password]{width:min(430px,100%)}input[type=search]{flex:1;min-width:220px}
.row{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.between{justify-content:space-between}
.muted{color:#637b84;font-size:13px}.notice{padding:12px 14px;border-radius:8px;background:#ebf5f5;font-size:13px}.error{background:#fff1ef;color:#a12d34}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:18px}.stat{background:white;padding:19px;border:1px solid #dce5ea;border-radius:12px}.stat strong{font-size:29px;display:block;margin-top:6px}.stat span{font-size:12px;color:#637b84}
#app{display:none}table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;color:#637b84;font-weight:600;white-space:nowrap}td,th{border-bottom:1px solid #e7edf0;padding:13px 10px;vertical-align:top}tbody tr:hover{background:#f7fafa}.table-wrap{overflow-x:auto}.status{font-weight:700;font-size:12px}.approved{color:#087857}.pending{color:#a26b00}.blocked{color:#a52d32}
.actions{display:flex;gap:6px;flex-wrap:wrap}.actions button{padding:5px 8px;font-size:12px}.mono{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;word-break:break-all}
#feedback{margin-bottom:16px}#feedback:empty{display:none}#logout{color:white;border-color:#82a8ae;background:transparent}
@media(max-width:650px){main{padding:14px}.stats{grid-template-columns:repeat(2,1fr)}header{padding:18px}.stat{padding:14px}section{padding:14px}}
</style></head>
<body><header><div><h1>Prescriber Intelligence</h1><p>License Administration · Cloudflare D1</p></div><button id="logout" hidden>Sign out</button></header>
<main>
<section id="login"><h2>Administrator sign in</h2><p class="muted">Enter the Cloudflare <code>ADMIN_TOKEN</code>. Your token stays in this tab's memory and is never saved to browser storage.</p>
<form id="loginForm" class="row"><input id="token" type="password" autocomplete="off" aria-label="Administrator token" placeholder="Administrator token" required><button class="primary" type="submit">Unlock dashboard</button></form></section>
<div id="feedback" role="status" aria-live="polite"></div>
<div id="app">
<div class="stats">
<div class="stat"><span>Approved installations</span><strong id="approvedCount">0</strong></div>
<div class="stat"><span>Pending approval</span><strong id="pendingCount">0</strong></div>
<div class="stat"><span>Blocked installations</span><strong id="blockedCount">0</strong></div>
<div class="stat"><span>Registered installations</span><strong id="totalCount">0</strong></div>
</div>
<section><div class="row between"><div><h2>Global license access</h2><div id="globalStatus" class="muted">Checking…</div></div><div class="row"><button id="refresh">Refresh</button><button id="globalAction" class="danger">Disable all online access</button></div></div>
<p class="notice">Changes take effect on the next successful online license check (normally within 60 seconds). Previously approved offline computers remain usable until they reconnect.</p></section>
<section><div class="row between"><div><h2>Computers &amp; installations</h2><p class="muted">Usernames and hostnames are reported by client devices, not verified user identities. Approve only recognized installations.</p></div></div>
<div class="row" style="margin-bottom:15px"><input id="search" type="search" placeholder="Search Windows user, hostname, installation ID…" aria-label="Search installations"><select id="filter" aria-label="Filter installation status"><option value="all">All statuses</option><option value="pending">Pending</option><option value="approved">Approved</option><option value="blocked">Blocked</option></select></div>
<div class="table-wrap"><table><thead><tr><th>Windows user / computer</th><th>Installation ID</th><th>Effective access</th><th>Last seen (UTC)</th><th>Actions</th></tr></thead><tbody id="devices"></tbody></table></div>
<p id="paginationInfo" class="muted"></p></section>
</div></main><script src="/admin/app.js" defer></script></body></html>`;
const adminScript = `'use strict';
(() => {
  let token = '';
  let snapshot = { devices: [], blocked_machines: [], enabled: true };
  let busy = false;
  const el = id => document.getElementById(id);
  const setMessage = (message, error = false) => {
    const box = el('feedback');
    box.className = error ? 'notice error' : 'notice';
    box.textContent = message;
  };
  const authorized = value => {
    el('login').hidden = value;
    el('app').style.display = value ? 'block' : 'none';
    el('logout').hidden = !value;
  };
  async function api(path, body) {
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        'Authorization': 'Bearer ' + token,
        ...(body === undefined ? {} : {'Content-Type': 'application/json'})
      },
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      cache: 'no-store',
      credentials: 'omit'
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(response.status === 401 ? 'Invalid administrator token.' : (data.error || 'Request failed (HTTP ' + response.status + ').'));
    return data;
  }
  const cell = (row, content, css = '') => {
    const td = document.createElement('td');
    td.textContent = String(content ?? '');
    if (css) td.className = css;
    row.appendChild(td);
    return td;
  };
  function effective(device) {
    if (!snapshot.enabled) return 'blocked';
    if (device.machine_hash && snapshot.blocked_machines.some(b => b.machine_hash === device.machine_hash)) return 'blocked';
    return device.status;
  }
  const makeButton = (label, handler, css) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    if (css) button.className = css;
    button.disabled = busy;
    button.addEventListener('click', handler);
    return button;
  };
  function render() {
    const list = snapshot.devices || [];
    el('totalCount').textContent = list.length;
    ['approved','pending','blocked'].forEach(status => {
      el(status + 'Count').textContent = list.filter(d => effective(d) === status).length;
    });
    el('globalStatus').textContent = snapshot.enabled ? 'Enabled — approved, unblocked installations can connect' : 'DISABLED — all online authorization checks are blocked';
    el('globalAction').textContent = snapshot.enabled ? 'Disable all online access' : 'Restore global access';
    el('globalAction').className = snapshot.enabled ? 'danger' : 'primary';
    el('globalAction').disabled = busy;
    el('refresh').disabled = busy;
    const query = el('search').value.trim().toLowerCase();
    const filter = el('filter').value;
    const visible = list.filter(d =>
      (filter === 'all' || effective(d) === filter) &&
      [d.windows_user,d.hostname,d.device_id,d.machine_hash].some(x => String(x || '').toLowerCase().includes(query))
    );
    const tbody = el('devices');
    tbody.replaceChildren();
    for (const device of visible) {
      const tr = document.createElement('tr');
      const who = cell(tr, device.windows_user || '(unknown)');
      const hostname = document.createElement('div');
      hostname.className = 'muted'; hostname.textContent = device.hostname || '(no hostname)';
      who.appendChild(hostname);
      cell(tr, device.device_id, 'mono');
      const access = effective(device);
      const statusTd = cell(tr, access.toUpperCase(), 'status ' + access);
      if (device.status !== access) {
        const note = document.createElement('div');
        note.className = 'muted';
        note.textContent = device.status === 'approved' ? 'Stored approval overridden' : 'Stored: ' + device.status;
        statusTd.appendChild(note);
      }
      cell(tr, device.last_seen || 'Never');
      const controls = cell(tr, '', 'actions');
      const change = (status) => mutate(
        '/admin/device', {device_id: device.device_id, status},
        'Set ' + (device.windows_user || device.device_id) + ' / ' + (device.hostname || 'unknown computer') + ' to ' + status + '?'
      );
      if (device.status !== 'approved') controls.appendChild(makeButton('Approve', () => change('approved'), 'primary'));
      if (device.status !== 'blocked') controls.appendChild(makeButton('Block', () => change('blocked'), 'danger'));
      if (device.status !== 'pending') controls.appendChild(makeButton('Reset to pending', () => change('pending')));
      if (device.machine_hash) {
        const machineBlocked = snapshot.blocked_machines.some(m => m.machine_hash === device.machine_hash);
        controls.appendChild(makeButton(machineBlocked ? 'Unblock PC' : 'Block entire PC', () => mutate(
          '/admin/machine',
          {machine_hash: device.machine_hash, blocked: !machineBlocked},
          (machineBlocked ? 'Unblock' : 'Block') + ' this machine across every Windows account?'
        ), machineBlocked ? '' : 'danger'));
      }
      tbody.appendChild(tr);
    }
    if (!visible.length) {
      const tr = document.createElement('tr');
      const td = cell(tr, 'No matching installations.');
      td.colSpan = 5; tbody.appendChild(tr);
    }
    el('paginationInfo').textContent = 'Showing ' + visible.length + ' of ' + list.length + ' returned registrations (server limit: 500).';
  }
  async function load() {
    snapshot = await api('/admin/devices');
    authorized(true);
    render();
  }
  async function mutate(path, body, question) {
    if (busy || !confirm(question)) return;
    busy = true; render();
    try {
      await api(path, body);
      await load();
      setMessage('Change saved. Devices will receive the decision on their next successful online check.');
    } catch (error) {
      setMessage(error.message, true);
    } finally {
      busy = false; render();
    }
  }
  el('loginForm').addEventListener('submit', async event => {
    event.preventDefault();
    token = el('token').value.trim();
    if (!token) return;
    try {
      await load();
      el('token').value = '';
      setMessage('Administrator authenticated.');
    } catch (error) {
      token = '';
      setMessage(error.message, true);
    }
  });
  el('logout').addEventListener('click', () => {
    token = '';
    snapshot = {devices: [], blocked_machines: [], enabled: true};
    authorized(false);
    el('token').value = '';
    setMessage('Signed out. Administrator token cleared from this tab.');
  });
  el('refresh').addEventListener('click', async () => {
    try {await load(); setMessage('Latest registrations loaded.');}
    catch (error) {setMessage(error.message, true);}
  });
  el('search').addEventListener('input', render);
  el('filter').addEventListener('change', render);
  el('globalAction').addEventListener('click', () => mutate(
    '/admin/global',
    {enabled: !snapshot.enabled},
    snapshot.enabled
      ? 'GLOBAL SHUTDOWN: deny all connected clients? Previously approved offline devices will continue working until reconnecting.'
      : 'Restore global access? Individually blocked devices and machines remain blocked.'
  ));
  authorized(false);
})();`;
const adminPageHeaders = {
  "Content-Type": "text/html; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
};

export default {
  async fetch(req,env) {
    const u=new URL(req.url);
    if (req.method === "GET" && u.pathname === "/admin") return new Response(adminHtml, {headers: adminPageHeaders});
    if (req.method === "GET" && u.pathname === "/admin/app.js") return new Response(adminScript, {headers: {"Content-Type":"application/javascript; charset=utf-8","Cache-Control":"no-store","X-Content-Type-Options":"nosniff"}});
    if (req.method==="GET" && u.pathname==="/health") return json({ok:true});
    if (u.pathname==="/api/check" && req.method==="POST") {
      try {
        const data=await req.json();
        if(!validId(data.device_id))return json({error:"Invalid device id"},400);
        const id=data.device_id;
        const first=await env.DB.prepare(
          "INSERT OR IGNORE INTO devices(device_id,machine_hash,windows_user,hostname,app_version,status,last_seen) VALUES(?,?,?,?,?,'pending',datetime('now'))"
        ).bind(id,limitText(data.machine_hash,80),limitText(data.windows_user),
               limitText(data.hostname),limitText(data.app_version,40)).run();
        await env.DB.prepare(
          "UPDATE devices SET windows_user=?,hostname=?,app_version=?,last_seen=datetime('now') WHERE device_id=?"
        ).bind(limitText(data.windows_user),limitText(data.hostname),
               limitText(data.app_version,40),id).run();
        const device=await env.DB.prepare("SELECT status,machine_hash FROM devices WHERE device_id=?")
          .bind(id).first();
        const config=await revision(env);
        const machineBlocked = device.machine_hash
          ? await env.DB.prepare("SELECT machine_hash FROM blocked_machines WHERE machine_hash=?")
              .bind(device.machine_hash).first()
          : null;
        // Detect copied registration files: a previously bound machine ID must match.
        const mismatch=Boolean(device.machine_hash && data.machine_hash &&
                               device.machine_hash!==data.machine_hash);
        const status=(!config.enabled || mismatch || machineBlocked || device.status==="blocked")
          ? "blocked" : device.status==="approved" ? "approved" : "pending";
        const payload={
          device_id:id,status,revision:Number(config.version),
          machine_hash:device.machine_hash || "",
          issued_at:new Date().toISOString()
        };
        return json(await signed(env,payload));
      } catch (_) { return json({error:"License service unavailable"},503); }
    }
    if(u.pathname.startsWith("/admin/")) {
      if(!(await admin(req,env)))return json({error:"Unauthorized"},401);
      if(req.method==="GET" && u.pathname==="/admin/devices") {
        const devices=await env.DB.prepare(
          "SELECT device_id,machine_hash,windows_user,hostname,app_version,status,last_seen FROM devices ORDER BY last_seen DESC LIMIT 500"
        ).all();
        const setting=await revision(env);
        const blocked=await env.DB.prepare(
          "SELECT machine_hash,blocked_at FROM blocked_machines ORDER BY blocked_at DESC LIMIT 500"
        ).all();
        return json({enabled:Boolean(setting.enabled),version:setting.version,
                     devices:devices.results,blocked_machines:blocked.results});
      }
      if(req.method==="POST" && u.pathname==="/admin/global") {
        const data=await req.json();
        if(typeof data.enabled!=="boolean")return json({error:"enabled must be boolean"},400);
        await env.DB.prepare(
          "UPDATE settings SET enabled=?,version=version+1 WHERE id=1"
        ).bind(data.enabled?1:0).run();
        return json({ok:true,setting:await revision(env)});
      }
      if(req.method==="POST" && u.pathname==="/admin/machine") {
        const data=await req.json();
        if(typeof data.machine_hash!=="string" ||
           !/^[a-f0-9]{64}$/.test(data.machine_hash) ||
           typeof data.blocked!=="boolean") return json({error:"Invalid machine ID or blocked flag"},400);
        if(data.blocked)
          await env.DB.prepare("INSERT OR IGNORE INTO blocked_machines(machine_hash) VALUES(?)")
            .bind(data.machine_hash).run();
        else
          await env.DB.prepare("DELETE FROM blocked_machines WHERE machine_hash=?")
            .bind(data.machine_hash).run();
        await env.DB.prepare("UPDATE settings SET version=version+1 WHERE id=1").run();
        return json({ok:true,machine_hash:data.machine_hash,blocked:data.blocked});
      }
      if(req.method==="POST" && u.pathname==="/admin/device") {
        const data=await req.json();
        if(!validId(data.device_id)||!["approved","pending","blocked"].includes(data.status))
          return json({error:"Invalid device or status"},400);
        const r=await env.DB.prepare(
          "UPDATE devices SET status=? WHERE device_id=?"
        ).bind(data.status,data.device_id).run();
        if(!r.meta.changes)return json({error:"Unknown device"},404);
        await env.DB.prepare("UPDATE settings SET version=version+1 WHERE id=1").run();
        return json({ok:true,device_id:data.device_id,status:data.status});
      }
    }
    return json({error:"Not found"},404);
  }
};
