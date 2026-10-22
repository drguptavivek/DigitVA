"""Reusable envelope encryption for personal-data columns.

Policy: docs/policy/death-registration-identifiers.md, "Encryption at rest".

Each value gets its own random 256-bit data key (DEK) and is sealed with
AES-256-GCM, bound to its row by caller-supplied AAD (so a ciphertext copied to
another row fails to decrypt). The DEK is wrapped by a hybrid post-quantum KEM:
ML-KEM-768 and X25519 are both encapsulated and the two shared secrets are
joined by an HKDF-SHA256 combiner whose ``info`` binds the algorithm id, key id,
both KEM ciphertexts and both recipient public keys (X-Wing style), so the
value stays protected while either component holds. The combiner was changed
to bind the public keys before any value was written, so the ``v1`` prefix
stands and nothing needs migrating. Writers need only the PUBLIC keys; unwrapping needs the
private keys, which a process reads from a secret file.

Stored forms (crypto-agile: decrypt dispatches on the prefix)::

    value_ciphertext  v1:aes256gcm:<b64url(nonce || ciphertext+tag)>
    dek_wrapped       v1:aes256gcm+mlkem768x25519:<key_id>:<b64url(
                          mlkem_ct || x25519_eph_pub || nonce || wrapped_dek)>

Records (``seal_record`` / ``open_record``; PII policy
docs/policy/pii-encryption-at-rest.md, decision 10) share ONE DEK across all
their fields: the same two forms, a ``{field: value_ciphertext}`` map plus one
``dek_wrapped``, with AAD binding table, field and record id.

Every failure to open a blob raises ``PiiCryptoError`` with one generic
message naming only the caller's row reference and the key id; never
ciphertext, plaintext or key material.

Deliberately imports nothing from ``app`` at module level, so
``scripts/generate_pii_keys.py`` can load this file without the Flask app.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
from dataclasses import dataclass
from functools import cached_property

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import mlkem, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DATA_PREFIX = "v1:aes256gcm:"
WRAP_ALG = "aes256gcm+mlkem768x25519"
WRAP_PREFIX = f"v1:{WRAP_ALG}:"

KEY_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_BLIND_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")

_MLKEM_PUB_LEN = 1184
_MLKEM_SEED_LEN = 64
_MLKEM_CT_LEN = 1088
_X25519_LEN = 32
_NONCE_LEN = 12
_DEK_LEN = 32
_WRAPPED_DEK_LEN = _DEK_LEN + 16
_WRAP_BLOB_LEN = _MLKEM_CT_LEN + _X25519_LEN + _NONCE_LEN + _WRAPPED_DEK_LEN

_COMBINER_LABEL = b"digitva pii kem combiner v1"


class PiiCryptoError(Exception):
    """A blob could not be opened or a key is unusable. The message carries
    only a row reference and a key id."""


class PiiKeyConfigError(RuntimeError):
    """Key configuration is missing or malformed (startup refusal)."""


# ---------------------------------------------------------------------------
# Encoding and key containers
# ---------------------------------------------------------------------------

def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class KemPublicKey:
    key_id: str
    mlkem: bytes
    x25519: bytes

    def to_config(self) -> str:
        return f"{_b64e(self.mlkem)}.{_b64e(self.x25519)}"


@dataclass(frozen=True)
class KemPrivateKey:
    key_id: str
    mlkem_seed: bytes
    x25519: bytes

    def to_file_text(self) -> str:
        return f"{self.key_id}:{_b64e(self.mlkem_seed)}:{_b64e(self.x25519)}\n"

    def public_key(self) -> KemPublicKey:
        return KemPublicKey(
            self.key_id,
            mlkem.MLKEM768PrivateKey.from_seed_bytes(self.mlkem_seed).public_key().public_bytes_raw(),
            x25519.X25519PrivateKey.from_private_bytes(self.x25519).public_key().public_bytes_raw(),
        )

    @cached_property
    def kem_objects(self):
        """``(ML-KEM private, X25519 private, ML-KEM public bytes, X25519
        public bytes)``, built once per key object. The keyring is built once
        per process, so unwrapping no longer rebuilds them from the seed on
        every call. (``cached_property`` writes the instance ``__dict__``
        directly, which a frozen dataclass allows.)"""
        mlkem_key = mlkem.MLKEM768PrivateKey.from_seed_bytes(self.mlkem_seed)
        x25519_key = x25519.X25519PrivateKey.from_private_bytes(self.x25519)
        return (
            mlkem_key,
            x25519_key,
            mlkem_key.public_key().public_bytes_raw(),
            x25519_key.public_key().public_bytes_raw(),
        )


@dataclass(frozen=True)
class Keyring:
    """What a process holds: the key new values are wrapped with, the private
    keys it can unwrap with (empty for a writer-only process) and the blind
    index key."""

    public: KemPublicKey
    private: dict[str, KemPrivateKey]
    blind_key: bytes


def parse_public_key(text: str, key_id: str) -> KemPublicKey:
    """``<b64url ML-KEM-768 public>.<b64url X25519 public>`` plus *key_id*."""
    try:
        if not KEY_ID_RE.fullmatch(key_id or ""):
            raise ValueError
        m, x = (text or "").strip().split(".")
        key = KemPublicKey(key_id, _b64d(m), _b64d(x))
        if len(key.mlkem) != _MLKEM_PUB_LEN or len(key.x25519) != _X25519_LEN:
            raise ValueError
        # Rejects bytes that are the right length but not a key.
        mlkem.MLKEM768PublicKey.from_public_bytes(key.mlkem)
        x25519.X25519PublicKey.from_public_bytes(key.x25519)
        return key
    except Exception:
        raise PiiKeyConfigError("PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.") from None


def parse_private_key(text: str) -> KemPrivateKey:
    """``<key_id>:<b64url ML-KEM-768 seed>:<b64url X25519 private>``."""
    try:
        key_id, m, x = (text or "").strip().split(":")
        key = KemPrivateKey(key_id, _b64d(m), _b64d(x))
        if (
            not KEY_ID_RE.fullmatch(key_id)
            or len(key.mlkem_seed) != _MLKEM_SEED_LEN
            or len(key.x25519) != _X25519_LEN
        ):
            raise ValueError
        key.public_key()  # builds both keys: rejects an unusable seed
        return key
    except Exception:
        raise PiiKeyConfigError("A PII private key file is malformed.") from None


def parse_blind_key(text: str) -> bytes:
    """64 hex characters (32 bytes), as ``openssl rand -hex 32``."""
    if not _BLIND_KEY_RE.fullmatch((text or "").strip()):
        raise PiiKeyConfigError("PII_BLIND_INDEX_KEY must be 64 hexadecimal characters.")
    return bytes.fromhex(text.strip())


def generate_keyset(key_id: str | None = None) -> tuple[KemPublicKey, KemPrivateKey]:
    """A new hybrid key pair. *key_id* defaults to a random 12-hex id."""
    key_id = key_id or secrets.token_hex(6)
    private = KemPrivateKey(
        key_id,
        mlkem.MLKEM768PrivateKey.generate().private_bytes_raw(),
        x25519.X25519PrivateKey.generate().private_bytes_raw(),
    )
    return private.public_key(), private


def load_private_key_file(path: str) -> KemPrivateKey:
    try:
        with open(path, encoding="ascii") as handle:
            text = handle.read()
    except OSError:
        raise PiiKeyConfigError("A PII private key file is not readable.") from None
    return parse_private_key(text)


def build_keyring(config) -> Keyring:
    """The process keyring from the app *config* mapping. Raises
    ``PiiKeyConfigError`` for anything missing or malformed that was asked
    for; filling gaps with throwaway development keys is the caller's choice
    (``dev_defaults``)."""
    public = parse_public_key(
        config.get("PII_KEM_PUBLIC_KEY", ""), (config.get("PII_KEM_KEY_ID") or "").strip()
    )
    blind_key = parse_blind_key(config.get("PII_BLIND_INDEX_KEY", ""))
    private: dict[str, KemPrivateKey] = {}
    current_file = (config.get("PII_KEM_PRIVATE_KEY_FILE") or "").strip()
    previous = [
        p.strip() for p in (config.get("PII_KEM_PREVIOUS_PRIVATE_KEY_FILES") or "").split(",") if p.strip()
    ]
    for path in [current_file, *previous] if current_file else previous:
        key = load_private_key_file(path)
        private[key.key_id] = key
    if current_file:
        current = private.get(public.key_id)
        # The configured public key and the private file must be one pair.
        if current is None or current.public_key() != public:
            raise PiiKeyConfigError("PII_KEM_PRIVATE_KEY_FILE does not match PII_KEM_PUBLIC_KEY.")
    return Keyring(public, private, blind_key)


def dev_keyring(secret_key: str) -> Keyring:
    """Throwaway keys for development and test when nothing is configured:
    a fresh pair per process (never written anywhere) and a blind key derived
    from ``SECRET_KEY`` so indexes survive a restart."""
    public, private = generate_keyset("dev")
    blind = hmac.new(secret_key.encode("utf-8"), b"digitva pii blind index dev", hashlib.sha256).digest()
    return Keyring(public, {private.key_id: private}, blind)


_OTHER_PII_SETTINGS = (
    "PII_KEM_KEY_ID",
    "PII_KEM_PRIVATE_KEY_FILE",
    "PII_KEM_PREVIOUS_PRIVATE_KEY_FILES",
    "PII_BLIND_INDEX_KEY",
)


#: Where a KEM private key file sits by default: the compose secret mount, the
#: development key in the checkout (``private/``, under the app root) and the
#: production location outside it (``make ensure-secrets-prod``).
DEFAULT_PRIVATE_KEY_PATHS = ("/run/secrets/pii_kem_private_key", "/data/digitva-secrets/pii_kem_private_key")
_CHECKOUT_PRIVATE_KEY = os.path.join("private", "pii_kem_private_key")


def stray_private_key_files(app) -> list[str]:
    """Private key files a process that is not configured to read values
    (no ``PII_KEM_PRIVATE_KEY_FILE``: beat, a misconfigured service) can
    nevertheless read at the default paths. Owner decision 13: only the app
    and worker containers hold the private key."""
    checkout = os.path.join(os.path.dirname(app.root_path), _CHECKOUT_PRIVATE_KEY)
    return [
        path for path in (*DEFAULT_PRIVATE_KEY_PATHS, checkout)
        if os.path.isfile(path) and os.access(path, os.R_OK)
    ]


def _refuse_stray_private_key(app) -> None:
    """Production: a non-reader process that can read a private key file
    refuses to start (the key must not reach it: mask ``/app/private`` and
    mount the secret into app and worker only). Debug: a warning. Test:
    nothing (the test config never names a key file)."""
    if (app.config.get("PII_KEM_PRIVATE_KEY_FILE") or "").strip() or app.testing:
        return
    stray = stray_private_key_files(app)
    if not stray:
        return
    message = (
        f"This process is not configured to read personal data (no PII_KEM_PRIVATE_KEY_FILE) but can read "
        f"a PII private key file at {', '.join(stray)}. Keep the key outside the checkout and mount it into "
        "the app and worker only; see docs/current-state/runtime-and-operations.md, 'Registration identifier keys'."
    )
    if app.debug:
        app.logger.warning(message)
        return
    raise RuntimeError(message)


def init_app(app) -> None:
    """Build the keyring once at startup and keep it in ``app.extensions``.

    Production (not debug, not testing) refuses to start without a
    well-formed public key, key id and blind index key. A process that sets
    ``PII_KEM_PRIVATE_KEY_FILE`` is a reader and refuses without a readable,
    matching private key. Development and test fall back to throwaway keys
    only when no PII_* setting is configured at all: a public key left empty
    beside any other PII_* setting (a typo'd or missing key) refuses, so
    values are never written under a key nobody holds. A process that does
    NOT set ``PII_KEM_PRIVATE_KEY_FILE`` refuses in production when it can
    read a private key file at a default path (``_refuse_stray_private_key``).
    """
    _refuse_stray_private_key(app)
    config = app.config
    relaxed = app.debug or app.testing
    if relaxed and not (config.get("PII_KEM_PUBLIC_KEY") or "").strip():
        stray = next((name for name in _OTHER_PII_SETTINGS if (config.get(name) or "").strip()), None)
        if stray:
            raise RuntimeError(
                f"PII_KEM_PUBLIC_KEY is empty but {stray} is set; set the public key or clear "
                "every PII_* setting. See docs/current-state/runtime-and-operations.md, "
                "'Registration identifier keys'."
            )
        keyring = dev_keyring(config["SECRET_KEY"])
    else:
        try:
            keyring = build_keyring(config)
        except PiiKeyConfigError as exc:
            raise RuntimeError(
                f"{exc} See docs/current-state/runtime-and-operations.md, "
                "'Registration identifier keys'."
            ) from None
    app.extensions["pii_keyring"] = keyring


def _keyring() -> Keyring:
    from flask import current_app

    try:
        return current_app.extensions["pii_keyring"]
    except KeyError:
        raise PiiKeyConfigError("PII keys are not initialised.") from None


def current_key_id() -> str:
    return _keyring().public.key_id


def current_public_key() -> KemPublicKey:
    """The KEM public key new values are wrapped with; the station config
    hands it to offline stations (bundle spec 6.4 ``kem_public_key``)."""
    return _keyring().public


# ---------------------------------------------------------------------------
# Combiner and wrapping
# ---------------------------------------------------------------------------

def _field(raw: bytes) -> bytes:
    return struct.pack(">H", len(raw)) + raw


def combine(
    ss_mlkem: bytes, ss_x25519: bytes, key_id: str, mlkem_ct: bytes, eph_pub: bytes,
    mlkem_pub: bytes, x25519_pub: bytes,
) -> bytes:
    """The KEM combiner: HKDF-SHA256 over both shared secrets, with the
    algorithm id, key id, both KEM ciphertexts (the ephemeral X25519 public
    key is the X25519 ciphertext) and the recipient's ML-KEM and X25519 public
    keys in ``info``. Any change to this layout changes every key-encryption
    key: the fixed-input test pins it."""
    info = (
        _COMBINER_LABEL
        + _field(WRAP_ALG.encode("ascii"))
        + _field(key_id.encode("ascii"))
        + _field(mlkem_ct)
        + _field(eph_pub)
        + _field(mlkem_pub)
        + _field(x25519_pub)
    )
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(ss_mlkem + ss_x25519)


def _wrap_aad(key_id: str) -> bytes:
    return f"{key_id}|{WRAP_ALG}".encode("ascii")


def wrap_dek(dek: bytes, public: KemPublicKey) -> str:
    """Wrap *dek* to *public*: needs no private key."""
    ss_m, ct_m = mlkem.MLKEM768PublicKey.from_public_bytes(public.mlkem).encapsulate()
    eph = x25519.X25519PrivateKey.generate()
    ss_x = eph.exchange(x25519.X25519PublicKey.from_public_bytes(public.x25519))
    eph_pub = eph.public_key().public_bytes_raw()
    kek = combine(ss_m, ss_x, public.key_id, ct_m, eph_pub, public.mlkem, public.x25519)
    nonce = os.urandom(_NONCE_LEN)
    wrapped = AESGCM(kek).encrypt(nonce, dek, _wrap_aad(public.key_id))
    return WRAP_PREFIX + public.key_id + ":" + _b64e(ct_m + eph_pub + nonce + wrapped)


def _safe_key_id(raw: str) -> str:
    return raw if KEY_ID_RE.fullmatch(raw or "") else "?"


def _wrapped_key_id(dek_wrapped: str) -> str:
    parts = (dek_wrapped or "").split(":", 3)
    return _safe_key_id(parts[2]) if len(parts) == 4 else "?"


def _fail(row_ref: str, dek_wrapped: str) -> PiiCryptoError:
    return PiiCryptoError(
        f"PII value could not be decrypted (row {row_ref}, key {_wrapped_key_id(dek_wrapped)})."
    )


def unwrap_dek(dek_wrapped: str, *, row_ref: str) -> bytes:
    """The DEK inside *dek_wrapped*. Raises ``PiiCryptoError`` for an unknown
    version, algorithm or key id, a missing private key, or tampering."""
    try:
        version, alg, key_id, blob = dek_wrapped.split(":", 3)
        if (version, alg) != ("v1", WRAP_ALG):
            raise ValueError
        private = _keyring().private[key_id]
        raw = _b64d(blob)
        if len(raw) != _WRAP_BLOB_LEN:
            raise ValueError
        ct_m = raw[:_MLKEM_CT_LEN]
        eph_pub = raw[_MLKEM_CT_LEN:_MLKEM_CT_LEN + _X25519_LEN]
        nonce = raw[_MLKEM_CT_LEN + _X25519_LEN:_MLKEM_CT_LEN + _X25519_LEN + _NONCE_LEN]
        wrapped = raw[_MLKEM_CT_LEN + _X25519_LEN + _NONCE_LEN:]
        mlkem_key, x25519_key, mlkem_pub, x25519_pub = private.kem_objects
        ss_m = mlkem_key.decapsulate(ct_m)
        ss_x = x25519_key.exchange(x25519.X25519PublicKey.from_public_bytes(eph_pub))
        kek = combine(ss_m, ss_x, key_id, ct_m, eph_pub, mlkem_pub, x25519_pub)
        return AESGCM(kek).decrypt(nonce, wrapped, _wrap_aad(key_id))
    except Exception:  # every cause, including InvalidTag, is the same refusal
        raise _fail(row_ref, dek_wrapped) from None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_value(plaintext: str, aad: bytes) -> tuple[str, str, str]:
    """Seal *plaintext* under a fresh DEK bound to *aad* and wrap the DEK with
    the current public key. Returns ``(value_ciphertext, dek_wrapped, key_id)``."""
    keyring = _keyring()
    dek = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(_NONCE_LEN)
    sealed = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), aad)
    return (
        DATA_PREFIX + _b64e(nonce + sealed),
        wrap_dek(dek, keyring.public),
        keyring.public.key_id,
    )


def decrypt_value(value_ciphertext: str, dek_wrapped: str, aad: bytes, *, row_ref: str) -> str:
    """The plaintext of a sealed value; ``PiiCryptoError`` on any failure."""
    dek = unwrap_dek(dek_wrapped, row_ref=row_ref)
    try:
        version, alg, blob = value_ciphertext.split(":", 2)
        if (version, alg) != ("v1", "aes256gcm"):
            raise ValueError
        raw = _b64d(blob)
        return AESGCM(dek).decrypt(raw[:_NONCE_LEN], raw[_NONCE_LEN:], aad).decode("utf-8")
    except Exception:
        raise _fail(row_ref, dek_wrapped) from None


def rewrap_dek(dek_wrapped: str, *, row_ref: str) -> tuple[str, str]:
    """Unwrap with whichever private key wrapped it and wrap with the current
    public key. The data ciphertext is untouched. Returns
    ``(new_dek_wrapped, key_id)``."""
    dek = unwrap_dek(dek_wrapped, row_ref=row_ref)
    public = _keyring().public
    return wrap_dek(dek, public), public.key_id


def blind_index(context: bytes, normalised: str) -> str:
    """``hex(HMAC-SHA-512(blind key, context || 0x00 || value))``: equality
    only, bound to *context* (the identifier type id) so equal values under
    two types do not correlate."""
    return hmac.new(
        _keyring().blind_key, context + b"\x00" + normalised.encode("utf-8"), hashlib.sha512
    ).hexdigest()


# ---------------------------------------------------------------------------
# Record-level sealing (docs/policy/pii-encryption-at-rest.md, "Keys and
# blind indexes"): one DEK per record, one AES-GCM ciphertext per field
# ---------------------------------------------------------------------------

#: Most unwrapped DEKs one request or job batch keeps (OD10: about a page).
DEK_CACHE_MAX = 256
_DEK_CACHE_ATTR = "_pii_dek_cache"


def record_aad(table: str, field_id: str, row_id: bytes) -> bytes:
    """``table || 0x00 || column or field id || 0x00 || row id bytes``: a
    field's ciphertext opens only in its own table, field and record."""
    return table.encode("ascii") + b"\x00" + field_id.encode("utf-8") + b"\x00" + row_id


def seal_record(
    fields: dict[str, str], *, table: str, row_id: bytes
) -> tuple[dict[str, str], str, str]:
    """Seal every value of *fields* under ONE fresh DEK, each with its own
    nonce and ``record_aad(table, field, row_id)``, and wrap the DEK with the
    current public key (needs no private key). Values are text; the caller
    encodes anything else. Returns ``(sealed, dek_wrapped, key_id)`` where
    *sealed* is ``{field: "v1:aes256gcm:..."}`` and *dek_wrapped* has the
    per-value wrap format, so ``rewrap_dek`` re-wraps a record unchanged."""
    keyring = _keyring()
    dek = AESGCM.generate_key(bit_length=256)
    aead = AESGCM(dek)
    sealed = {}
    for name, value in fields.items():
        nonce = os.urandom(_NONCE_LEN)
        ciphertext = aead.encrypt(nonce, value.encode("utf-8"), record_aad(table, name, row_id))
        sealed[name] = DATA_PREFIX + _b64e(nonce + ciphertext)
    return sealed, wrap_dek(dek, keyring.public), keyring.public.key_id


def clear_dek_cache() -> None:
    """Drop every DEK this app context has unwrapped. The cache lives on
    ``flask.g``, so it already ends with the request or the job's app
    context; a long batch calls this between batches."""
    from flask import g

    g.pop(_DEK_CACHE_ATTR, None)


def _cached_dek(dek_wrapped: str, *, row_ref: str) -> bytes:
    """``unwrap_dek`` once per wrapped DEK per app context (OD10). Keyed by
    the wrapped string, which carries the key id; never persisted, never
    process-wide; the oldest entry is evicted past ``DEK_CACHE_MAX``."""
    from flask import g

    cache = g.get(_DEK_CACHE_ATTR)
    if cache is None:
        cache = {}
        setattr(g, _DEK_CACHE_ATTR, cache)
    dek = cache.get(dek_wrapped)
    if dek is None:
        dek = unwrap_dek(dek_wrapped, row_ref=row_ref)
        if len(cache) >= DEK_CACHE_MAX:
            cache.pop(next(iter(cache)))
        cache[dek_wrapped] = dek
    return dek


def open_record(
    sealed: dict[str, str],
    dek_wrapped: str,
    *,
    table: str,
    row_id: bytes,
    row_ref: str,
    only=None,
) -> dict[str, str]:
    """The plaintext of a sealed record, one unwrap (cached per request) for
    all its fields. *only* opens just those fields (names not sealed are
    left out). ``PiiCryptoError`` naming only *row_ref* and the key id on any
    failure: unknown version, wrong key, tamper, or a ciphertext moved to
    another table, field or record."""
    names = list(sealed) if only is None else [name for name in only if name in sealed]
    if not names:
        return {}
    aead = AESGCM(_cached_dek(dek_wrapped, row_ref=row_ref))
    opened = {}
    for name in names:
        try:
            version, alg, blob = sealed[name].split(":", 2)
            if (version, alg) != ("v1", "aes256gcm"):
                raise ValueError
            raw = _b64d(blob)
            opened[name] = aead.decrypt(
                raw[:_NONCE_LEN], raw[_NONCE_LEN:], record_aad(table, name, row_id)
            ).decode("utf-8")
        except Exception:
            raise _fail(row_ref, dek_wrapped) from None
    return opened


# ---------------------------------------------------------------------------
# Per-class blind-index subkeys
# ---------------------------------------------------------------------------

#: One HKDF subkey per kind of value, so a leaked index of one class does not
#: help with another. Registration identifiers keep ``blind_index`` (raw key
#: plus type-id context; policy Q3). There is no Aadhaar class.
BLIND_INDEX_CLASSES = frozenset({"phone", "abha_number", "abha_address", "payload-fp"})
_SUBKEY_INFO_PREFIX = b"digitva-pii-bidx/v1/"


def subkey(class_label: str) -> bytes:
    """``HKDF-SHA256(ikm = PII_BLIND_INDEX_KEY, salt = none, info =
    b"digitva-pii-bidx/v1/" + class, length = 64)``. ``ValueError`` for a
    class not in ``BLIND_INDEX_CLASSES``."""
    if class_label not in BLIND_INDEX_CLASSES:
        raise ValueError("Unknown blind index class.")
    return HKDF(
        algorithm=hashes.SHA256(), length=64, salt=None,
        info=_SUBKEY_INFO_PREFIX + class_label.encode("ascii"),
    ).derive(_keyring().blind_key)


def class_index(class_label: str, normalised: str) -> str:
    """``hex(HMAC-SHA-512(subkey(class), normalised))``: equality within one
    class only. The caller normalises (phone, ABHA rules in the policy)."""
    return hmac.new(subkey(class_label), normalised.encode("utf-8"), hashlib.sha512).hexdigest()


def blind_key_id() -> str:
    """First 8 hex of ``SHA-256(PII_BLIND_INDEX_KEY)``, stored beside every
    class index so a blind-key rotation can tell old rows from new."""
    return hashlib.sha256(_keyring().blind_key).hexdigest()[:8]


# ---------------------------------------------------------------------------
# Key generation (scripts/generate_pii_keys.py)
# ---------------------------------------------------------------------------

def _env_has(path: str, name: str) -> bool:
    try:
        with open(path, encoding="utf-8") as handle:
            return any(line.startswith(f"{name}=") and len(line.strip()) > len(name) + 1 for line in handle)
    except FileNotFoundError:
        return False


def write_new_keyset(private_file: str, env_file: str) -> None:
    """Write a new private key file (mode 0600, refused if it exists) and
    append ``PII_KEM_PUBLIC_KEY``, ``PII_KEM_KEY_ID`` and ``PII_BLIND_INDEX_KEY``
    to *env_file* unless already set there. Prints nothing and returns no
    key material. A failed env append removes the private file just created."""
    if os.path.exists(private_file):
        raise PiiKeyConfigError("The private key file already exists; refusing to overwrite it.")
    for name in ("PII_KEM_PUBLIC_KEY", "PII_KEM_KEY_ID", "PII_BLIND_INDEX_KEY"):
        if _env_has(env_file, name):
            raise PiiKeyConfigError(f"{name} is already set in the env file; refusing to replace it.")
    public, private = generate_keyset()
    fd = os.open(private_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as handle:
        handle.write(private.to_file_text())
    entries = (
        f"PII_KEM_PUBLIC_KEY={public.to_config()}\n"
        f"PII_KEM_KEY_ID={public.key_id}\n"
        f"PII_BLIND_INDEX_KEY={secrets.token_hex(32)}\n"
    )
    try:
        with open(env_file, "ab+") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell():
                handle.seek(-1, os.SEEK_END)
                if handle.read(1) != b"\n":
                    entries = "\n" + entries
            handle.write(entries.encode("utf-8"))
    except OSError:
        os.unlink(private_file)  # no orphan key file without its public settings
        raise PiiKeyConfigError("The env file could not be written; no key was kept.") from None
