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
export default {
  async fetch(req,env) {
    const u=new URL(req.url);
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
