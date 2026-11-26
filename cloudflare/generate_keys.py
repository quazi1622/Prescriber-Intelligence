"""Run locally to generate an Ed25519 Cloudflare signing keypair.

PRIVATE key is printed once; keep it in Cloudflare Worker secrets, never GitHub.
PUBLIC key goes into GitHub Actions secret PI_PUBLIC_KEY_B64.
"""
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key=Ed25519PrivateKey.generate()
private=key.private_bytes(
    serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()
)
public=key.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw
)
print("CLOUDFLARE SIGNING_KEY_PKCS8_B64 (PRIVATE; do not commit):")
print(base64.b64encode(private).decode())
print("\nGITHUB ACTIONS PI_PUBLIC_KEY_B64 (PUBLIC):")
print(base64.b64encode(public).decode())
