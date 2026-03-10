"""
Reversible encryption for stored credentials (ODK usernames/passwords).

Design:
  - Pepper  : application secret from ODK_CREDENTIAL_PEPPER env var.
               Never stored in DB or source. Stored in .env / container env.
  - Salt    : 16 random bytes per value, stored as hex alongside the ciphertext.
               Ensures two identical plaintexts produce different ciphertexts.
  - KDF     : PBKDF2-HMAC-SHA256 (260 000 iterations) derives a 32-byte key
               from pepper + salt.
  - Cipher  : Fernet (AES-128-CBC + HMAC-SHA256) encrypts the plaintext.

Usage:
    from app.utils.credential_crypto import encrypt_credential, decrypt_credential

    ciphertext, salt_hex = encrypt_credential("secret", pepper)
    plaintext = decrypt_credential(ciphertext, salt_hex, pepper)
"""

import os
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


_KDF_ITERATIONS = 260_000


def get_odk_pepper() -> str:
    """Return the ODK credential pepper from app config or env.

    Raises RuntimeError if not configured — fail loudly rather than silently
    using an empty pepper.
    """
    # Prefer Flask app config when inside a request context
    try:
        from flask import current_app
        pepper = current_app.config.get("ODK_CREDENTIAL_PEPPER", "")
    except RuntimeError:
        pepper = os.environ.get("ODK_CREDENTIAL_PEPPER", "")

    if not pepper:
        raise RuntimeError(
            "ODK_CREDENTIAL_PEPPER is not set. "
            "Add it to your .env file or container environment."
        )
    return pepper


def _derive_fernet(pepper: str, salt_hex: str) -> Fernet:
    salt = bytes.fromhex(salt_hex)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=_KDF_ITERATIONS,
    )
    key = base64.urlsafe_b64encode(kdf.derive(pepper.encode("utf-8")))
    return Fernet(key)


def encrypt_credential(plaintext: str, pepper: str) -> tuple[str, str]:
    """Encrypt *plaintext* and return (ciphertext_str, salt_hex).

    Both values must be stored together; salt_hex is required for decryption.
    """
    salt_hex = os.urandom(16).hex()
    f = _derive_fernet(pepper, salt_hex)
    ciphertext = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ciphertext, salt_hex


def decrypt_credential(ciphertext: str, salt_hex: str, pepper: str) -> str:
    """Decrypt and return the original plaintext.

    Raises ValueError on decryption failure (wrong pepper/salt/tampered data).
    """
    try:
        f = _derive_fernet(pepper, salt_hex)
        return f.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, Exception) as exc:
        raise ValueError("Credential decryption failed.") from exc
