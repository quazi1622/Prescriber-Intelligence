"""Signed online authorization with indefinite *approved-only* offline continuity.

No prescription data is sent. Revocation takes effect on next verified response;
a fully offline computer cannot be remotely contacted or revoked immediately.
"""
import base64
import getpass
import hashlib
import json
import os
import platform
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

try:
    from .license_settings import WORKER_URL, PUBLIC_KEY_B64
except ImportError:
    from license_settings import WORKER_URL, PUBLIC_KEY_B64


def state_dir():
    root = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    path = Path(root) / "PrescriberIntelligence" / "license"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_file():
    return state_dir() / "device.json"


def read_state():
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("device_id"), str):
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"device_id": str(uuid.uuid4()), "status": "unregistered", "issued_at": ""}


def write_state(record):
    path = state_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def machine_id():
    """Hash an ordinary read-only Windows registry identifier, not Rx data."""
    value = ""
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                value = str(winreg.QueryValueEx(key, "MachineGuid")[0])
        except (OSError, ValueError):
            pass
    # Fallback is scoped to this local user installation, not a strong PC ID.
    return hashlib.sha256(("pi-device-v1:" + value).encode()).hexdigest() if value else ""


def identity(state):
    return {
        "device_id": state["device_id"],
        "machine_hash": machine_id(),
        "windows_user": getpass.getuser()[:120],
        "hostname": platform.node()[:120],
        "app_version": "1.0",
    }


def configured():
    return bool(WORKER_URL.strip() and PUBLIC_KEY_B64.strip())


def verify_response(response, expected_device):
    payload = response["payload"]
    signature = base64.b64decode(response["signature"], validate=True)
    public_key = Ed25519PublicKey.from_public_bytes(
        base64.b64decode(PUBLIC_KEY_B64, validate=True))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")
    public_key.verify(signature, canonical)
    if payload["device_id"] != expected_device:
        raise ValueError("Authorization response was issued for a different device.")
    if payload["status"] not in ("approved", "pending", "blocked"):
        raise ValueError("Unknown access status.")
    # Strict UTC ISO timestamp, lexicographic comparison is stable here.
    datetime.strptime(payload["issued_at"], "%Y-%m-%dT%H:%M:%SZ")
    return payload


def check_access(timeout=5):
    """Return (allowed, reason). Only previously signed approvals permit offline use.

    Unknown device + outage is pending; a prior signed block remains blocked.
    Signed revocations are stored before returning, to survive a restart.
    """
    if not configured():
        return False, "Remote licensing is not configured in this build."
    state = read_state()
    url = WORKER_URL.rstrip("/") + "/api/check"
    request = urllib.request.Request(
        url, data=json.dumps(identity(state)).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError("Unexpected licensing response")
            raw = response.read(16_384)
        payload = verify_response(json.loads(raw), state["device_id"])
        if payload["issued_at"] >= state.get("issued_at", ""):
            state["status"] = payload["status"]
            state["issued_at"] = payload["issued_at"]
            write_state(state)
        else:
            # Ignore replayed older decisions; stored last decision wins.
            pass
    except (OSError, ValueError, KeyError, TypeError, UnicodeError,
            urllib.error.URLError) as exc:
        if state["status"] == "approved":
            return True, "Offline: previously approved access remains available."
        return False, ("Unable to verify authorization. Connect once for approval "
                       "or contact the software administrator.")
    status = state["status"]
    if status == "approved":
        return True, "Device authorized."
    if status == "pending":
        return False, "Device registration pending administrator approval."
    return False, "Access blocked by administrator." if status == "blocked" else "Device not authorized."
