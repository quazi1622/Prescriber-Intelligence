"""Operator CLI for Cloudflare device administration.

Usage:
  PI_WORKER_URL=https://... PI_ADMIN_TOKEN=... python cloudflare/admin.py list
  python cloudflare/admin.py approve DEVICE_ID
  python cloudflare/admin.py block DEVICE_ID
  python cloudflare/admin.py pending DEVICE_ID
  python cloudflare/admin.py shutdown
  python cloudflare/admin.py restore

Set secrets in environment or local secret store; do not commit them.
"""
import json,os,sys,urllib.request,urllib.error

URL=os.environ.get("PI_WORKER_URL","").rstrip("/")
TOKEN=os.environ.get("PI_ADMIN_TOKEN","")
def request(path,body=None):
    if not URL.startswith("https://") or not TOKEN:
        sys.exit("Set PI_WORKER_URL and PI_ADMIN_TOKEN environment variables")
    payload=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(URL+path,data=payload,
        headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json"},
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req,timeout=15) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit("Server error "+str(e.code)+": "+e.read().decode(errors="replace"))

if __name__=="__main__":
    if len(sys.argv)<2:
        sys.exit("Commands: list, approve ID, block ID, pending ID, shutdown, restore")
    cmd=sys.argv[1].lower()
    if cmd=="list":
        result=request("/admin/devices")
        print("Global:", "ENABLED" if result["enabled"] else "SHUT DOWN")
        for d in result["devices"]:
            print(d["device_id"],d["status"],"user=",d["windows_user"],
                  "computer=",d["hostname"],"last_seen=",d["last_seen"])
    elif cmd in ("approve","block","pending") and len(sys.argv)==3:
        status={"approve":"approved","block":"blocked","pending":"pending"}[cmd]
        print(request("/admin/device",{"device_id":sys.argv[2],"status":status}))
    elif cmd in ("shutdown","restore"):
        print(request("/admin/global",{"enabled":cmd=="restore"}))
    else:sys.exit("Invalid command")
