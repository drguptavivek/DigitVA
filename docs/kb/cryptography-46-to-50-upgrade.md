---
title: cryptography 46 to 50 upgrade and ML-KEM API
doc_type: kb
status: active
owner: engineering
last_updated: 2026-10-20
---

# cryptography 46.0.5 to 50.0.2

Verified on 2026-10-20 in `minerva_app_service`. Changelog read from
<https://cryptography.io/en/latest/changelog/>.

## Versions

- Before: `cryptography` 46.0.5, `pyopenssl` 26.2.0, pin `>=42.0.0`.
- After: `cryptography` 50.0.2, `pyopenssl` 26.4.0 (pulled by the resolver;
  `pyopenssl` requires `cryptography`), pin `cryptography>=48`. No other
  package changed in `uv.lock`.
- The wheel bundles **OpenSSL 4.0.3** (`backend.openssl_version_text()`),
  which is >= 3.5; ML-KEM needs no extra library. The interpreter's own
  `ssl.OPENSSL_VERSION` (3.5.7) is a separate copy and is irrelevant here.
- `app`, `celery worker` and `celery beat` share one Dockerfile but are three
  separate images; all three were rebuilt and report 50.0.2.

## Breaking changes 47 to 50 against our usage

| Release | Change | Affects us |
| --- | --- | --- |
| 47.0.0 | Removed `SECT*` binary curves, OpenSSL 1.1.x, LibreSSL < 4.1 | No (we use none) |
| 47.0.0 | Unsupported key algorithms raise `UnsupportedAlgorithm` not `ValueError`; invalid encodings raise `TypeError` | No (no key loading in app code) |
| 47.0.0 | Deprecated `CFB`/`OFB`/`CFB8`, `Camellia` (moved to decrepit), 64/128-bit `TripleDES` | No (Fernet uses AES-CBC, TOTP uses AES-GCM) |
| 48.0.0 | Python 3.8 dropped; CRL signature mismatch raises | No (Python 3.13; no CRLs) |
| 49.0.0 | Removed `x86_64` macOS and 32-bit Windows wheels | Dev note only: Docker images are Linux |
| 49.0.0 | Removed `PUBLIC_KEY_TYPES` and related aliases | No (not imported) |
| 49.0.0 | `ChaCha20` overflow raises; ECDSA/DSA cert signatures with NULL params raise `ValueError` | No |
| 50.0.0 | FFDH (`dh`) deprecated | No |

Our imports: `Fernet`, `hashes`, `PBKDF2HMAC` (`app/utils/credential_crypto.py`,
`app/__init__.py`), `AESGCM`, `HKDF`, `InvalidTag` (`app/services/totp_service.py`),
`x509`, `NameOID` (`app/services/tls_health_service.py`), and `ec` in tests.
None is touched by the changes above. The ODK credential, TOTP, passkey,
factor and TLS health tests pass on 50.0.2 (194 passed).

## Dependents (`uv tree --invert --package cryptography`)

- `digitva` direct (`cryptography>=48`).
- `pyopenssl` 26.4.0, required by `webauthn` 2.8.0 (which also depends on
  `cryptography` directly).
- `moto` 5.2.3 (dev group, `s3` extra).
- No upper bound imposed by any dependent.

## ML-KEM-768 and X25519 (verified API)

ML-KEM arrived in 47.0.0 for AWS-LC/BoringSSL builds and in 48.0.0 for
OpenSSL >= 3.5 (the published wheels). Module
`cryptography.hazmat.primitives.asymmetric.mlkem` exports
`MLKEM768PrivateKey`, `MLKEM768PublicKey`, `MLKEM1024PrivateKey`,
`MLKEM1024PublicKey`.

- `MLKEM768PrivateKey`: `generate()`, `from_seed_bytes(bytes)`,
  `public_key()`, `decapsulate(ciphertext) -> shared secret`,
  `private_bytes_raw()` (the 64-byte seed), `private_bytes(encoding, format, enc)`.
- `MLKEM768PublicKey`: `from_public_bytes(bytes)`, `encapsulate() -> (shared
  secret, ciphertext)` (note the order), `public_bytes_raw()`,
  `public_bytes(encoding, format)`.
- Sizes: shared secret 32 bytes, ciphertext 1088, raw public key 1184, raw
  private key (seed) 64. PKCS8 PEM private 172 chars, SPKI PEM public 1686
  chars. PEM keys load with `serialization.load_pem_private_key` /
  `load_pem_public_key`.
- X25519: `x25519.X25519PrivateKey.generate().exchange(peer_public_key)` works.

Working snippet (ran clean):

```python
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import mlkem, x25519

sk = mlkem.MLKEM768PrivateKey.generate()
pk = sk.public_key()
ss, ct = pk.encapsulate()                 # (32-byte secret, 1088-byte ct)
assert sk.decapsulate(ct) == ss
seed = sk.private_bytes_raw()             # 64 bytes
assert mlkem.MLKEM768PrivateKey.from_seed_bytes(seed).decapsulate(ct) == ss
raw = pk.public_bytes_raw()               # 1184 bytes
ss2, ct2 = mlkem.MLKEM768PublicKey.from_public_bytes(raw).encapsulate()
assert sk.decapsulate(ct2) == ss2
pem = sk.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())
assert s.load_pem_private_key(pem, None).decapsulate(ct) == ss
x, y = x25519.X25519PrivateKey.generate(), x25519.X25519PrivateKey.generate()
assert x.exchange(y.public_key()) == y.exchange(x.public_key())
```

The private key is stored as a seed, so persist the 64-byte seed (or PKCS8)
as the secret; there is no separate expanded-key format.

The envelope built on these primitives (combiner, wrap layout, record AAD,
blind indexes) is specified byte for byte, with test vectors, in
[docs/policy/pii-envelope-format.md](../policy/pii-envelope-format.md).
