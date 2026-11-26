"""Synthetic, offline-safe licensing tests; no network or real device telemetry."""
import base64
import io
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from app import device_license as license


class FakeResponse(io.BytesIO):
    status=200
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class DeviceLicenseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path=Path(self.tmp.name)/"device.json"
        self.patch_path=patch.object(license,"state_file",return_value=path)
        self.patch_path.start()
        self.addCleanup(self.patch_path.stop)
        private=Ed25519PrivateKey.generate()
        self.private=private
        pub=private.public_key().public_bytes(
            serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.patch_key=patch.object(license,"PUBLIC_KEY_B64",
            base64.b64encode(pub).decode())
        self.patch_url=patch.object(license,"WORKER_URL","https://example.workers.dev")
        self.patch_key.start()
        self.patch_url.start()
        self.addCleanup(self.patch_key.stop)
        self.addCleanup(self.patch_url.stop)
        self.patch_machine=patch.object(license,"machine_id",return_value="machine-1")
        self.patch_machine.start()
        self.addCleanup(self.patch_machine.stop)

    def signed(self,status,revision,device_id):
        payload={"device_id":device_id,"status":status,"revision":revision,
                 "machine_hash":"machine-1",
                 "issued_at":"2026-11-26T10:30:00.123Z"}
        encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),
                           ensure_ascii=False).encode("utf-8")
        signature=base64.b64encode(self.private.sign(encoded)).decode()
        return json.dumps({"payload":payload,"signature":signature}).encode()

    def test_new_unknown_device_offline_is_not_approved(self):
        with patch.object(license.urllib.request,"urlopen",side_effect=URLError("offline")):
            allowed,reason=license.check_access()
        self.assertFalse(allowed)
        self.assertIn("Authorization",reason)

    def test_signed_approval_survives_offline_then_revocation_persists(self):
        state=license.read_state()
        # Stable installation identity for this isolated test.
        license.write_state(state)
        device_id=state["device_id"]
        with patch.object(license.urllib.request,"urlopen",
                          return_value=FakeResponse(self.signed("approved",1,device_id))):
            self.assertTrue(license.check_access()[0])
        with patch.object(license.urllib.request,"urlopen",side_effect=URLError("offline")):
            self.assertTrue(license.check_access()[0])
        with patch.object(license.urllib.request,"urlopen",
                          return_value=FakeResponse(self.signed("blocked",2,device_id))):
            self.assertFalse(license.check_access()[0])
        with patch.object(license.urllib.request,"urlopen",side_effect=URLError("offline")):
            self.assertFalse(license.check_access()[0])

    def test_unsigned_forged_approval_never_unlocks_offline(self):
        state=license.read_state()
        state["status"]="approved"
        license.write_state(state)
        with patch.object(license.urllib.request,"urlopen",side_effect=URLError("offline")):
            self.assertFalse(license.check_access()[0])

    def test_copied_license_cache_cannot_authorize_other_computer(self):
        state=license.read_state()
        license.write_state(state)
        with patch.object(license.urllib.request,"urlopen",
                return_value=FakeResponse(self.signed("approved",3,state["device_id"]))):
            self.assertTrue(license.check_access()[0])
        with patch.object(license,"machine_id",return_value="different-machine"):
            with patch.object(license.urllib.request,"urlopen",side_effect=URLError("offline")):
                self.assertFalse(license.check_access()[0])

    def test_old_approval_cannot_overwrite_new_block(self):
        state=license.read_state()
        license.write_state(state)
        device_id=state["device_id"]
        with patch.object(license.urllib.request,"urlopen",
                          return_value=FakeResponse(self.signed("blocked",10,device_id))):
            self.assertFalse(license.check_access()[0])
        with patch.object(license.urllib.request,"urlopen",
                          return_value=FakeResponse(self.signed("approved",2,device_id))):
            self.assertFalse(license.check_access()[0])


if __name__=="__main__":
    unittest.main()
