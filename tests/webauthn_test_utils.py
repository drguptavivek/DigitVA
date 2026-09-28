"""Synthetic WebAuthn ceremony data for tests.

Builds real authenticatorData/clientDataJSON/attestationObject/signature
bytes for a "none"-attestation EC P-256 credential, so
webauthn_service.verify_registration/verify_authentication run their actual
cryptographic verification against these fixtures -- nothing about
py_webauthn's own verify calls is mocked.

See docs/policy/authentication-factors.md section 2 for the RP contract this
mirrors (rp_id hash, user presence/verification flags, signature counter).
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def new_keypair():
    return ec.generate_private_key(ec.SECP256R1())


def cose_public_key(priv) -> bytes:
    numbers = priv.public_key().public_numbers()
    x = numbers.x.to_bytes(32, "big")
    y = numbers.y.to_bytes(32, "big")
    # COSE_Key for ES256: kty=EC2(2), alg=ES256(-7), crv=P-256(1), x, y.
    return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: x, -3: y})


def _flags_byte(*, up: bool, uv: bool, at: bool) -> bytes:
    flags = 0
    if up:
        flags |= 0x01
    if uv:
        flags |= 0x04
    if at:
        flags |= 0x40
    return bytes([flags])


def build_auth_data(
    rp_id: str,
    *,
    sign_count: int,
    up: bool = True,
    uv: bool = True,
    credential_id: bytes | None = None,
    cose_key: bytes | None = None,
) -> bytes:
    """Registration authData (attested credential data present) when
    ``credential_id``/``cose_key`` are given; a bare assertion authData
    otherwise."""
    rp_id_hash = hashlib.sha256(rp_id.encode("utf-8")).digest()
    at = credential_id is not None
    auth_data = rp_id_hash + _flags_byte(up=up, uv=uv, at=at) + struct.pack(">I", sign_count)
    if at:
        aaguid = b"\x00" * 16
        auth_data += aaguid + struct.pack(">H", len(credential_id)) + credential_id + cose_key
    return auth_data


def build_client_data_json(type_: str, challenge: bytes, origin: str) -> bytes:
    return json.dumps(
        {
            "type": type_,
            "challenge": b64url(challenge),
            "origin": origin,
            "crossOrigin": False,
        }
    ).encode("utf-8")


def build_registration_credential(
    *, rp_id: str, origin: str, challenge: bytes, credential_id: bytes, priv, uv: bool = True
) -> dict:
    cose_key = cose_public_key(priv)
    auth_data = build_auth_data(
        rp_id, sign_count=0, uv=uv, credential_id=credential_id, cose_key=cose_key
    )
    attestation_object = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
    client_data = build_client_data_json("webauthn.create", challenge, origin)
    return {
        "id": b64url(credential_id),
        "rawId": b64url(credential_id),
        "type": "public-key",
        "response": {
            "attestationObject": b64url(attestation_object),
            "clientDataJSON": b64url(client_data),
            "transports": ["internal"],
        },
    }


def build_authentication_credential(
    *,
    rp_id: str,
    origin: str,
    challenge: bytes,
    credential_id: bytes,
    priv,
    sign_count: int,
    uv: bool = True,
    user_handle: bytes | None = None,
) -> dict:
    auth_data = build_auth_data(rp_id, sign_count=sign_count, uv=uv)
    client_data = build_client_data_json("webauthn.get", challenge, origin)
    signature = priv.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
    response = {
        "authenticatorData": b64url(auth_data),
        "clientDataJSON": b64url(client_data),
        "signature": b64url(signature),
    }
    if user_handle is not None:
        response["userHandle"] = b64url(user_handle)
    return {
        "id": b64url(credential_id),
        "rawId": b64url(credential_id),
        "type": "public-key",
        "response": response,
    }
