//! PII Envelope Format (`docs/policy/pii-envelope-format.md`).
//!
//! Byte-exact implementation of the hybrid post-quantum envelope encryption
//! (`AES-256-GCM` + `ML-KEM-768` + `X25519` with `HKDF-SHA256` combiner) and
//! `HMAC-SHA-512` / `HKDF-SHA256` blind indexing specified by the central server.

use aes_gcm::{
    aead::{Aead, KeyInit, Payload},
    Aes256Gcm, Nonce,
};
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use hkdf::Hkdf;
use hmac::{Hmac, Mac};
use ml_kem::{
    kem::{Decapsulate, Encapsulate},
    B32, EncapsulateDeterministic, Encoded, EncodedSizeUser, KemCore, MlKem768,
};
use rand::rngs::OsRng;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256, Sha512};
use std::collections::BTreeMap;
use std::fmt;
use x25519_dalek::{PublicKey as X25519PublicKey, StaticSecret as X25519StaticSecret};

/// Prefix for per-value and per-field AES-256-GCM ciphertexts.
pub const DATA_PREFIX: &str = "v1:aes256gcm:";

/// Hybrid KEM wrap algorithm identifier.
pub const WRAP_ALG: &str = "aes256gcm+mlkem768x25519";

/// Prefix for wrapped DEK blobs (`"v1:aes256gcm+mlkem768x25519:"`).
pub const WRAP_PREFIX: &str = "v1:aes256gcm+mlkem768x25519:";

/// Raw 27-byte HKDF info prefix for the hybrid KEM combiner (not length-prefixed).
pub const COMBINER_LABEL: &[u8] = b"digitva pii kem combiner v1";

/// HKDF info prefix for per-class blind-index subkeys.
pub const SUBKEY_INFO_PREFIX: &[u8] = b"digitva-pii-bidx/v1/";

/// Allowed blind-index classes (case-sensitive; no Aadhaar class).
pub const BLIND_INDEX_CLASSES: &[&str] = &["phone", "abha_number", "abha_address", "payload-fp"];

pub const MLKEM768_PUBLIC_KEY_LEN: usize = 1184;
pub const MLKEM768_SEED_LEN: usize = 64;
pub const MLKEM768_CIPHERTEXT_LEN: usize = 1088;
pub const X25519_KEY_LEN: usize = 32;
pub const NONCE_LEN: usize = 12;
pub const DEK_LEN: usize = 32;
pub const GCM_TAG_LEN: usize = 16;
pub const WRAPPED_DEK_LEN: usize = DEK_LEN + GCM_TAG_LEN;
pub const WRAP_BLOB_LEN: usize =
    MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN + NONCE_LEN + WRAPPED_DEK_LEN;

type HmacSha512 = Hmac<Sha512>;
type MlKem768Ek = <MlKem768 as KemCore>::EncapsulationKey;

/// Check whether `key_id` strictly matches `^[A-Za-z0-9_-]{1,16}$` with no newline.
#[inline]
pub fn is_valid_key_id(key_id: &str) -> bool {
    (1..=16).contains(&key_id.len())
        && key_id
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
}

/// Return `raw` if it matches `^[A-Za-z0-9_-]{1,16}$`, otherwise `"?"`.
#[inline]
pub fn sanitise_key_id(raw: &str) -> &str {
    if is_valid_key_id(raw) {
        raw
    } else {
        "?"
    }
}

#[inline]
fn extract_wrapped_key_id(dek_wrapped: &str) -> &str {
    let mut parts = dek_wrapped.splitn(4, ':');
    let _v = parts.next();
    let _alg = parts.next();
    let kid = parts.next();
    let blob = parts.next();
    match (kid, blob) {
        (Some(k), Some(_)) => sanitise_key_id(k),
        _ => "?",
    }
}

/// Single generic error returned for any failure to decrypt or unwrap a PII blob.
///
/// Formats strictly as:
/// `"PII value could not be decrypted (row <row_ref>, key <sanitised_key_id>)."`
/// Never includes plaintext, ciphertext, DEKs, KEKs, shared secrets, or key material.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PiiCryptoError {
    pub row_ref: String,
    pub key_id: String,
}

impl PiiCryptoError {
    pub fn new(row_ref: impl Into<String>, raw_key_id: &str) -> Self {
        Self {
            row_ref: row_ref.into(),
            key_id: sanitise_key_id(raw_key_id).to_string(),
        }
    }

    pub fn from_wrapped(row_ref: impl Into<String>, dek_wrapped: &str) -> Self {
        Self::new(row_ref, extract_wrapped_key_id(dek_wrapped))
    }
}

impl fmt::Display for PiiCryptoError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "PII value could not be decrypted (row {}, key {}).",
            self.row_ref, self.key_id
        )
    }
}

impl std::error::Error for PiiCryptoError {}

/// Key or configuration error (startup or caller configuration refusal).
/// Never includes key material or secret values.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
#[error("{0}")]
pub struct PiiKeyConfigError(pub String);

#[inline]
fn b64u_encode(raw: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(raw)
}

#[inline]
fn b64u_decode_strict(text: &str) -> Result<Vec<u8>, ()> {
    URL_SAFE_NO_PAD.decode(text).map_err(|_| ())
}

#[inline]
fn b64u_decode_config(text: &str) -> Result<Vec<u8>, ()> {
    let trimmed = text.trim_end_matches('=');
    if text.len() - trimmed.len() > 2 {
        return Err(());
    }
    URL_SAFE_NO_PAD.decode(trimmed).map_err(|_| ())
}

fn validate_mlkem768_public_bytes(mlkem: &[u8]) -> Result<MlKem768Ek, PiiKeyConfigError> {
    if mlkem.len() != MLKEM768_PUBLIC_KEY_LEN {
        return Err(PiiKeyConfigError(
            "PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string(),
        ));
    }
    let enc = Encoded::<MlKem768Ek>::try_from(mlkem).map_err(|_| {
        PiiKeyConfigError("PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string())
    })?;
    let ek = MlKem768Ek::from_bytes(&enc);
    // FIPS 203 Section 7.2 modulus check: every 12-bit coefficient must be < q (3329).
    if ek.as_bytes().as_slice() != mlkem {
        return Err(PiiKeyConfigError(
            "PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string(),
        ));
    }
    Ok(ek)
}

/// Hybrid ML-KEM-768 + X25519 recipient public key.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct KemPublicKey {
    pub key_id: String,
    pub mlkem: Vec<u8>,
    pub x25519: [u8; 32],
}

impl KemPublicKey {
    /// Parse `<b64u(ML-KEM-768 public, 1184 bytes)>.<b64u(X25519 public, 32 bytes)>` and validate `key_id`.
    pub fn parse(text: &str, key_id: &str) -> Result<Self, PiiKeyConfigError> {
        if !is_valid_key_id(key_id) {
            return Err(PiiKeyConfigError(
                "PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string(),
            ));
        }
        let trimmed = text.trim();
        let mut parts = trimmed.split('.');
        let (Some(m_b64), Some(x_b64), None) = (parts.next(), parts.next(), parts.next()) else {
            return Err(PiiKeyConfigError(
                "PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string(),
            ));
        };
        let mlkem = b64u_decode_config(m_b64).map_err(|_| {
            PiiKeyConfigError("PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string())
        })?;
        let x_vec = b64u_decode_config(x_b64).map_err(|_| {
            PiiKeyConfigError("PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string())
        })?;
        if mlkem.len() != MLKEM768_PUBLIC_KEY_LEN || x_vec.len() != X25519_KEY_LEN {
            return Err(PiiKeyConfigError(
                "PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string(),
            ));
        }
        let _ = validate_mlkem768_public_bytes(&mlkem)?;
        let mut x25519 = [0u8; 32];
        x25519.copy_from_slice(&x_vec);
        let _ = X25519PublicKey::from(x25519);
        Ok(Self {
            key_id: key_id.to_string(),
            mlkem,
            x25519,
        })
    }

    /// Format as `<b64u(mlkem)>.<b64u(x25519)>` (unpadded base64url).
    pub fn to_config(&self) -> String {
        format!("{}.{}", b64u_encode(&self.mlkem), b64u_encode(&self.x25519))
    }
}

/// Hybrid ML-KEM-768 + X25519 private key (`d || z` 64-byte seed and 32-byte X25519 scalar).
#[derive(Clone, PartialEq, Eq)]
pub struct KemPrivateKey {
    pub key_id: String,
    pub mlkem_seed: [u8; 64],
    pub x25519: [u8; 32],
}

impl fmt::Debug for KemPrivateKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("KemPrivateKey")
            .field("key_id", &self.key_id)
            .finish_non_exhaustive()
    }
}

impl KemPrivateKey {
    /// Parse `<key_id>:<b64u(64-byte ML-KEM seed)>:<b64u(32-byte X25519 private)>`.
    pub fn parse_file_text(text: &str) -> Result<Self, PiiKeyConfigError> {
        let trimmed = text.trim();
        let mut parts = trimmed.split(':');
        let (Some(key_id), Some(m_b64), Some(x_b64), None) =
            (parts.next(), parts.next(), parts.next(), parts.next())
        else {
            return Err(PiiKeyConfigError(
                "A PII private key file is malformed.".to_string(),
            ));
        };
        if !is_valid_key_id(key_id) {
            return Err(PiiKeyConfigError(
                "A PII private key file is malformed.".to_string(),
            ));
        }
        let seed_vec = b64u_decode_config(m_b64).map_err(|_| {
            PiiKeyConfigError("A PII private key file is malformed.".to_string())
        })?;
        let x_vec = b64u_decode_config(x_b64).map_err(|_| {
            PiiKeyConfigError("A PII private key file is malformed.".to_string())
        })?;
        if seed_vec.len() != MLKEM768_SEED_LEN || x_vec.len() != X25519_KEY_LEN {
            return Err(PiiKeyConfigError(
                "A PII private key file is malformed.".to_string(),
            ));
        }
        let mut mlkem_seed = [0u8; 64];
        mlkem_seed.copy_from_slice(&seed_vec);
        let mut x25519 = [0u8; 32];
        x25519.copy_from_slice(&x_vec);
        let key = Self {
            key_id: key_id.to_string(),
            mlkem_seed,
            x25519,
        };
        let _ = key.public_key();
        Ok(key)
    }

    /// Format as `<key_id>:<b64u(mlkem_seed)>:<b64u(x25519)>\n`.
    pub fn to_file_text(&self) -> String {
        format!(
            "{}:{}:{}\n",
            self.key_id,
            b64u_encode(&self.mlkem_seed),
            b64u_encode(&self.x25519)
        )
    }

    /// Derive the corresponding [`KemPublicKey`] deterministically from the stored seed and scalar.
    pub fn public_key(&self) -> KemPublicKey {
        let d = B32::try_from(&self.mlkem_seed[..32]).expect("32-byte d slice");
        let z = B32::try_from(&self.mlkem_seed[32..64]).expect("32-byte z slice");
        let (_dk, ek) = MlKem768::generate_deterministic(&d, &z);
        let mlkem = ek.as_bytes().as_slice().to_vec();
        let sk_x = X25519StaticSecret::from(self.x25519);
        let pk_x = X25519PublicKey::from(&sk_x);
        KemPublicKey {
            key_id: self.key_id.clone(),
            mlkem,
            x25519: *pk_x.as_bytes(),
        }
    }
}

/// Process keyring container holding the active public key, available private keys, and blind key.
#[derive(Clone)]
pub struct Keyring {
    pub public: KemPublicKey,
    pub private: BTreeMap<String, KemPrivateKey>,
    pub blind_key: [u8; 32],
}

impl fmt::Debug for Keyring {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Keyring")
            .field("public_key_id", &self.public.key_id)
            .field("private_key_ids", &self.private.keys().collect::<Vec<_>>())
            .field("blind_key_id", &blind_key_id(&self.blind_key))
            .finish()
    }
}

/// Parse a 64-character hex `PII_BLIND_INDEX_KEY` into 32 raw bytes.
pub fn parse_blind_key(text: &str) -> Result<[u8; 32], PiiKeyConfigError> {
    let trimmed = text.trim();
    if trimmed.len() != 64 || !trimmed.bytes().all(|b| b.is_ascii_hexdigit()) {
        return Err(PiiKeyConfigError(
            "PII_BLIND_INDEX_KEY must be 64 hexadecimal characters.".to_string(),
        ));
    }
    let bytes = hex::decode(trimmed).map_err(|_| {
        PiiKeyConfigError("PII_BLIND_INDEX_KEY must be 64 hexadecimal characters.".to_string())
    })?;
    let mut out = [0u8; 32];
    out.copy_from_slice(&bytes);
    Ok(out)
}

/// Generate a fresh hybrid KEM keypair (`key_id` defaults to 12 random lowercase hex chars).
pub fn generate_keyset(
    key_id: Option<&str>,
) -> Result<(KemPublicKey, KemPrivateKey), PiiKeyConfigError> {
    let resolved_id = match key_id {
        Some(id) => {
            if !is_valid_key_id(id) {
                return Err(PiiKeyConfigError("PII_KEM_KEY_ID is malformed.".to_string()));
            }
            id.to_string()
        }
        None => {
            let mut id_bytes = [0u8; 6];
            OsRng.fill_bytes(&mut id_bytes);
            hex::encode(id_bytes)
        }
    };
    let mut mlkem_seed = [0u8; 64];
    let mut x25519 = [0u8; 32];
    OsRng.fill_bytes(&mut mlkem_seed);
    OsRng.fill_bytes(&mut x25519);
    let private = KemPrivateKey {
        key_id: resolved_id,
        mlkem_seed,
        x25519,
    };
    Ok((private.public_key(), private))
}

#[inline]
fn append_lp(buf: &mut Vec<u8>, field: &[u8]) {
    let len = u16::try_from(field.len()).expect("combiner field length fits in u16");
    buf.extend_from_slice(&len.to_be_bytes());
    buf.extend_from_slice(field);
}

/// Hybrid KEM combiner (`pii-envelope-format.md` Section 4.2):
/// `HKDF-SHA256(IKM = ss_mlkem || ss_x25519, salt = None, info = COMBINER_LABEL || lp(WRAP_ALG) || lp(key_id) || lp(mlkem_ct) || lp(eph_pub) || lp(mlkem_pub) || lp(x25519_pub), L = 32)`.
pub fn combine_kek(
    ss_mlkem: &[u8; 32],
    ss_x25519: &[u8; 32],
    key_id: &str,
    mlkem_ct: &[u8],
    eph_pub: &[u8; 32],
    mlkem_pub: &[u8],
    x25519_pub: &[u8; 32],
) -> [u8; 32] {
    let mut ikm = [0u8; 64];
    ikm[..32].copy_from_slice(ss_mlkem);
    ikm[32..].copy_from_slice(ss_x25519);

    let mut info = Vec::with_capacity(
        COMBINER_LABEL.len()
            + 2 * 6
            + WRAP_ALG.len()
            + key_id.len()
            + mlkem_ct.len()
            + eph_pub.len()
            + mlkem_pub.len()
            + x25519_pub.len(),
    );
    info.extend_from_slice(COMBINER_LABEL);
    append_lp(&mut info, WRAP_ALG.as_bytes());
    append_lp(&mut info, key_id.as_bytes());
    append_lp(&mut info, mlkem_ct);
    append_lp(&mut info, eph_pub);
    append_lp(&mut info, mlkem_pub);
    append_lp(&mut info, x25519_pub);

    let hk = Hkdf::<Sha256>::new(None, &ikm);
    let mut kek = [0u8; 32];
    hk.expand(&info, &mut kek)
        .expect("32-byte HKDF-SHA256 expand cannot fail");
    kek
}

#[inline]
fn wrap_aad(key_id: &str) -> Vec<u8> {
    format!("{key_id}|{WRAP_ALG}").into_bytes()
}

/// Construct record-level AAD (`ASCII(table) || 0x00 || UTF-8(field_id) || 0x00 || row_id`).
///
/// Refuses `table` or `field_id` containing `0x00` or non-ASCII `table` (`pii-envelope-format.md` Section 8).
pub fn record_aad(
    table: &str,
    field_id: &str,
    row_id: &[u8],
) -> Result<Vec<u8>, PiiKeyConfigError> {
    if !table.is_ascii() || table.as_bytes().contains(&0x00) {
        return Err(PiiKeyConfigError(
            "Record AAD table must be ASCII and must not contain 0x00.".to_string(),
        ));
    }
    if field_id.as_bytes().contains(&0x00) {
        return Err(PiiKeyConfigError(
            "Record AAD field_id must not contain 0x00.".to_string(),
        ));
    }
    let mut aad = Vec::with_capacity(table.len() + 1 + field_id.len() + 1 + row_id.len());
    aad.extend_from_slice(table.as_bytes());
    aad.push(0x00);
    aad.extend_from_slice(field_id.as_bytes());
    aad.push(0x00);
    aad.extend_from_slice(row_id);
    Ok(aad)
}

/// Wrap `dek` to `public` deterministically given explicit randomness inputs (test / vector hook).
pub fn wrap_dek_deterministic(
    dek: &[u8; 32],
    public: &KemPublicKey,
    mlkem_m: &[u8; 32],
    x25519_eph_scalar: &[u8; 32],
    wrap_nonce: &[u8; 12],
) -> Result<String, PiiKeyConfigError> {
    if !is_valid_key_id(&public.key_id) {
        return Err(PiiKeyConfigError(
            "PII_KEM_PUBLIC_KEY or PII_KEM_KEY_ID is malformed.".to_string(),
        ));
    }
    let ek = validate_mlkem768_public_bytes(&public.mlkem)?;
    let m = B32::from(*mlkem_m);
    let (ct_m, ss_m) = ek
        .encapsulate_deterministic(&m)
        .map_err(|_| PiiKeyConfigError("ML-KEM-768 encapsulation failed.".to_string()))?;

    let esk = X25519StaticSecret::from(*x25519_eph_scalar);
    let epk = X25519PublicKey::from(&esk);
    let recipient_pk_x = X25519PublicKey::from(public.x25519);
    let ss_x = esk.diffie_hellman(&recipient_pk_x);
    if !ss_x.was_contributory() {
        return Err(PiiKeyConfigError(
            "X25519 recipient public key produced a low-order shared secret.".to_string(),
        ));
    }

    let ss_m_arr: [u8; 32] = ss_m.as_slice().try_into().expect("32-byte ML-KEM secret");
    let kek = combine_kek(
        &ss_m_arr,
        ss_x.as_bytes(),
        &public.key_id,
        ct_m.as_slice(),
        epk.as_bytes(),
        &public.mlkem,
        &public.x25519,
    );

    let aead = Aes256Gcm::new_from_slice(&kek).expect("32-byte AES-256-GCM key");
    let aad = wrap_aad(&public.key_id);
    let wrapped = aead
        .encrypt(
            Nonce::from_slice(wrap_nonce),
            Payload {
                msg: dek,
                aad: &aad,
            },
        )
        .map_err(|_| PiiKeyConfigError("AES-256-GCM DEK wrapping failed.".to_string()))?;

    let mut payload = Vec::with_capacity(WRAP_BLOB_LEN);
    payload.extend_from_slice(ct_m.as_slice());
    payload.extend_from_slice(epk.as_bytes());
    payload.extend_from_slice(wrap_nonce);
    payload.extend_from_slice(&wrapped);
    debug_assert_eq!(payload.len(), WRAP_BLOB_LEN);

    Ok(format!(
        "{WRAP_PREFIX}{}:{}",
        public.key_id,
        b64u_encode(&payload)
    ))
}

/// Wrap `dek` to `public` using fresh OS CSPRNG randomness.
pub fn wrap_dek(dek: &[u8; 32], public: &KemPublicKey) -> String {
    let enc = Encoded::<MlKem768Ek>::try_from(public.mlkem.as_slice())
        .expect("KemPublicKey carries a 1184-byte ML-KEM-768 public key");
    let ek = MlKem768Ek::from_bytes(&enc);
    let (ct_m, ss_m) = ek
        .encapsulate(&mut OsRng)
        .expect("ML-KEM-768 encapsulation cannot fail");

    let esk = X25519StaticSecret::random_from_rng(OsRng);
    let epk = X25519PublicKey::from(&esk);
    let recipient_pk_x = X25519PublicKey::from(public.x25519);
    let ss_x = esk.diffie_hellman(&recipient_pk_x);
    assert!(
        ss_x.was_contributory(),
        "X25519 shared secret is non-contributory (low-order recipient public key)"
    );

    let ss_m_arr: [u8; 32] = ss_m.as_slice().try_into().expect("32-byte ML-KEM secret");
    let kek = combine_kek(
        &ss_m_arr,
        ss_x.as_bytes(),
        &public.key_id,
        ct_m.as_slice(),
        epk.as_bytes(),
        &public.mlkem,
        &public.x25519,
    );

    let mut wrap_nonce = [0u8; NONCE_LEN];
    OsRng.fill_bytes(&mut wrap_nonce);

    let aead = Aes256Gcm::new_from_slice(&kek).expect("32-byte AES-256-GCM key");
    let aad = wrap_aad(&public.key_id);
    let wrapped = aead
        .encrypt(
            Nonce::from_slice(&wrap_nonce),
            Payload {
                msg: dek,
                aad: &aad,
            },
        )
        .expect("AES-256-GCM DEK wrapping cannot fail");

    let mut payload = Vec::with_capacity(WRAP_BLOB_LEN);
    payload.extend_from_slice(ct_m.as_slice());
    payload.extend_from_slice(epk.as_bytes());
    payload.extend_from_slice(&wrap_nonce);
    payload.extend_from_slice(&wrapped);
    debug_assert_eq!(payload.len(), WRAP_BLOB_LEN);

    format!("{WRAP_PREFIX}{}:{}", public.key_id, b64u_encode(&payload))
}

/// Unwrap `dek_wrapped` using `private_keys`.
///
/// Any failure returns `PiiCryptoError` naming only `row_ref` and the sanitised `key_id`.
pub fn unwrap_dek(
    dek_wrapped: &str,
    private_keys: &BTreeMap<String, KemPrivateKey>,
    row_ref: &str,
) -> Result<[u8; 32], PiiCryptoError> {
    let fail = || PiiCryptoError::from_wrapped(row_ref, dek_wrapped);

    let mut parts = dek_wrapped.splitn(4, ':');
    let (Some(version), Some(alg), Some(key_id), Some(blob)) =
        (parts.next(), parts.next(), parts.next(), parts.next())
    else {
        return Err(fail());
    };
    if version != "v1" || alg != WRAP_ALG || !is_valid_key_id(key_id) {
        return Err(fail());
    }
    let private = private_keys.get(key_id).ok_or_else(fail)?;
    let raw = b64u_decode_strict(blob).map_err(|_| fail())?;
    if raw.len() != WRAP_BLOB_LEN {
        return Err(fail());
    }

    let ct_m_slice = &raw[..MLKEM768_CIPHERTEXT_LEN];
    let eph_pub_slice = &raw[MLKEM768_CIPHERTEXT_LEN..MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN];
    let nonce_slice = &raw[MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN
        ..MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN + NONCE_LEN];
    let wrapped_slice = &raw[MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN + NONCE_LEN..];

    let d = B32::try_from(&private.mlkem_seed[..32]).map_err(|_| fail())?;
    let z = B32::try_from(&private.mlkem_seed[32..64]).map_err(|_| fail())?;
    let (dk_m, ek_m) = MlKem768::generate_deterministic(&d, &z);

    let ct_m = ml_kem::Ciphertext::<MlKem768>::try_from(ct_m_slice).map_err(|_| fail())?;
    let ss_m = dk_m.decapsulate(&ct_m).map_err(|_| fail())?;
    let ss_m_arr: [u8; 32] = ss_m.as_slice().try_into().map_err(|_| fail())?;

    let mut eph_pub_bytes = [0u8; 32];
    eph_pub_bytes.copy_from_slice(eph_pub_slice);
    let eph_pub = X25519PublicKey::from(eph_pub_bytes);

    let sk_x = X25519StaticSecret::from(private.x25519);
    let pk_x = X25519PublicKey::from(&sk_x);
    let ss_x = sk_x.diffie_hellman(&eph_pub);
    // Reject all-zero / low-order X25519 points (`fail-wrap-eph-low-order`).
    if !ss_x.was_contributory() {
        return Err(fail());
    }

    let kek = combine_kek(
        &ss_m_arr,
        ss_x.as_bytes(),
        key_id,
        ct_m_slice,
        &eph_pub_bytes,
        ek_m.as_bytes().as_slice(),
        pk_x.as_bytes(),
    );

    let aead = Aes256Gcm::new_from_slice(&kek).map_err(|_| fail())?;
    let aad = wrap_aad(key_id);
    let dek_vec = aead
        .decrypt(
            Nonce::from_slice(nonce_slice),
            Payload {
                msg: wrapped_slice,
                aad: &aad,
            },
        )
        .map_err(|_| fail())?;
    if dek_vec.len() != DEK_LEN {
        return Err(fail());
    }
    let mut dek = [0u8; DEK_LEN];
    dek.copy_from_slice(&dek_vec);
    Ok(dek)
}

/// Seal `plaintext_utf8` under `dek` and `nonce` with `aad`, returning `v1:aes256gcm:<b64u(nonce || ct+tag)>`.
pub fn seal_bytes_with_dek(
    dek: &[u8; 32],
    nonce: &[u8; 12],
    plaintext_utf8: &str,
    aad: &[u8],
) -> String {
    let aead = Aes256Gcm::new_from_slice(dek).expect("32-byte AES-256-GCM key");
    let sealed = aead
        .encrypt(
            Nonce::from_slice(nonce),
            Payload {
                msg: plaintext_utf8.as_bytes(),
                aad,
            },
        )
        .expect("AES-256-GCM encryption cannot fail");
    let mut combined = Vec::with_capacity(NONCE_LEN + sealed.len());
    combined.extend_from_slice(nonce);
    combined.extend_from_slice(&sealed);
    format!("{DATA_PREFIX}{}", b64u_encode(&combined))
}

/// Open `value_ciphertext` (`v1:aes256gcm:<b64u>`) with `dek` and `aad`, validating strict UTF-8.
pub fn open_bytes_with_dek(
    value_ciphertext: &str,
    dek: &[u8; 32],
    aad: &[u8],
    row_ref: &str,
    key_id_for_err: &str,
) -> Result<String, PiiCryptoError> {
    let fail = || PiiCryptoError::new(row_ref, key_id_for_err);

    let mut parts = value_ciphertext.splitn(3, ':');
    let (Some(version), Some(alg), Some(blob)) = (parts.next(), parts.next(), parts.next()) else {
        return Err(fail());
    };
    if version != "v1" || alg != "aes256gcm" {
        return Err(fail());
    }
    let raw = b64u_decode_strict(blob).map_err(|_| fail())?;
    if raw.len() < NONCE_LEN + GCM_TAG_LEN {
        return Err(fail());
    }
    let (nonce_slice, ct_slice) = raw.split_at(NONCE_LEN);
    let aead = Aes256Gcm::new_from_slice(dek).map_err(|_| fail())?;
    let pt_bytes = aead
        .decrypt(
            Nonce::from_slice(nonce_slice),
            Payload {
                msg: ct_slice,
                aad,
            },
        )
        .map_err(|_| fail())?;
    String::from_utf8(pt_bytes).map_err(|_| fail())
}

/// Per-value encryption API (`pii-envelope-format.md` Section 5.1):
/// seals `plaintext` under a fresh 32-byte DEK and 12-byte nonce bound to `aad`,
/// wraps the DEK to `public`, and returns `(value_ciphertext, dek_wrapped, key_id)`.
pub fn encrypt_value(
    plaintext: &str,
    aad: &[u8],
    public: &KemPublicKey,
) -> (String, String, String) {
    let mut dek = [0u8; DEK_LEN];
    let mut nonce = [0u8; NONCE_LEN];
    OsRng.fill_bytes(&mut dek);
    OsRng.fill_bytes(&mut nonce);
    let value_ciphertext = seal_bytes_with_dek(&dek, &nonce, plaintext, aad);
    let dek_wrapped = wrap_dek(&dek, public);
    (value_ciphertext, dek_wrapped, public.key_id.clone())
}

/// Per-value decryption API (`pii-envelope-format.md` Section 5.1):
/// unwraps `dek_wrapped` and opens `value_ciphertext` with `aad`.
pub fn decrypt_value(
    value_ciphertext: &str,
    dek_wrapped: &str,
    aad: &[u8],
    private_keys: &BTreeMap<String, KemPrivateKey>,
    row_ref: &str,
) -> Result<String, PiiCryptoError> {
    let dek = unwrap_dek(dek_wrapped, private_keys, row_ref)?;
    let key_id_for_err = extract_wrapped_key_id(dek_wrapped);
    open_bytes_with_dek(value_ciphertext, &dek, aad, row_ref, key_id_for_err)
}

/// Re-wrap `dek_wrapped` from any held private key to `new_public`, leaving data ciphertexts untouched.
pub fn rewrap_dek(
    dek_wrapped: &str,
    private_keys: &BTreeMap<String, KemPrivateKey>,
    new_public: &KemPublicKey,
    row_ref: &str,
) -> Result<(String, String), PiiCryptoError> {
    let dek = unwrap_dek(dek_wrapped, private_keys, row_ref)?;
    Ok((wrap_dek(&dek, new_public), new_public.key_id.clone()))
}

/// Record-level sealing API (`pii-envelope-format.md` Section 5.2):
/// seals every field in `fields` under ONE fresh DEK, each with its own fresh 12-byte nonce
/// and `record_aad(table, field_id, row_id)`, and wraps the DEK to `public`.
pub fn seal_record(
    fields: &BTreeMap<String, String>,
    table: &str,
    row_id: &[u8],
    public: &KemPublicKey,
) -> Result<(BTreeMap<String, String>, String, String), PiiKeyConfigError> {
    // Validate table even when `fields` is empty.
    let _ = record_aad(table, "", row_id)?;

    let mut dek = [0u8; DEK_LEN];
    OsRng.fill_bytes(&mut dek);

    let mut sealed = BTreeMap::new();
    for (name, value) in fields {
        let aad = record_aad(table, name, row_id)?;
        let mut nonce = [0u8; NONCE_LEN];
        OsRng.fill_bytes(&mut nonce);
        sealed.insert(
            name.clone(),
            seal_bytes_with_dek(&dek, &nonce, value, &aad),
        );
    }
    let dek_wrapped = wrap_dek(&dek, public);
    Ok((sealed, dek_wrapped, public.key_id.clone()))
}

/// Record-level opening API (`pii-envelope-format.md` Section 5.2):
/// opens `sealed` (or the subset in `only` that is present in `sealed`) with a single DEK unwrap.
/// When the effective list of field names to open is empty, returns `Ok(BTreeMap::new())` without unwrapping.
pub fn open_record(
    sealed: &BTreeMap<String, String>,
    dek_wrapped: &str,
    table: &str,
    row_id: &[u8],
    private_keys: &BTreeMap<String, KemPrivateKey>,
    row_ref: &str,
    only: Option<&[String]>,
) -> Result<BTreeMap<String, String>, PiiCryptoError> {
    let names: Vec<&String> = match only {
        None => sealed.keys().collect(),
        Some(subset) => subset.iter().filter(|k| sealed.contains_key(*k)).collect(),
    };
    if names.is_empty() {
        return Ok(BTreeMap::new());
    }
    let dek = unwrap_dek(dek_wrapped, private_keys, row_ref)?;
    let key_id_for_err = extract_wrapped_key_id(dek_wrapped);
    let mut opened = BTreeMap::new();
    for name in names {
        let aad = record_aad(table, name, row_id)
            .map_err(|_| PiiCryptoError::from_wrapped(row_ref, dek_wrapped))?;
        let ct = &sealed[name];
        let pt = open_bytes_with_dek(ct, &dek, &aad, row_ref, key_id_for_err)?;
        opened.insert(name.clone(), pt);
    }
    Ok(opened)
}

/// First 8 lowercase hex characters (4 bytes) of `SHA-256(blind_key)`.
pub fn blind_key_id(blind_key: &[u8; 32]) -> String {
    let digest = Sha256::digest(blind_key);
    hex::encode(&digest[..4])
}

/// Identifier blind index (`pii-envelope-format.md` Section 6):
/// `hex(HMAC-SHA-512(key = blind_key, msg = context || 0x00 || UTF-8(normalised)))`.
pub fn blind_index(blind_key: &[u8; 32], context: &[u8], normalised: &str) -> String {
    let mut mac = <HmacSha512 as Mac>::new_from_slice(blind_key).expect("HMAC accepts any key length");
    mac.update(context);
    mac.update(&[0x00]);
    mac.update(normalised.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// Derive the 64-byte per-class blind-index subkey (`pii-envelope-format.md` Section 6):
/// `HKDF-SHA256(IKM = blind_key, salt = None, info = "digitva-pii-bidx/v1/" || class_label, L = 64)`.
pub fn subkey(blind_key: &[u8; 32], class_label: &str) -> Result<[u8; 64], PiiKeyConfigError> {
    if !BLIND_INDEX_CLASSES.contains(&class_label) {
        return Err(PiiKeyConfigError("Unknown blind index class.".to_string()));
    }
    let mut info = Vec::with_capacity(SUBKEY_INFO_PREFIX.len() + class_label.len());
    info.extend_from_slice(SUBKEY_INFO_PREFIX);
    info.extend_from_slice(class_label.as_bytes());

    let hk = Hkdf::<Sha256>::new(None, blind_key);
    let mut out = [0u8; 64];
    hk.expand(&info, &mut out)
        .expect("64-byte HKDF-SHA256 expand cannot fail");
    Ok(out)
}

/// Compute a 128-hex-character equality blind index for `class_label` (`phone`, `abha_number`, `abha_address`, `payload-fp`).
pub fn class_index(
    blind_key: &[u8; 32],
    class_label: &str,
    normalised: &str,
) -> Result<String, PiiKeyConfigError> {
    let sk = subkey(blind_key, class_label)?;
    let mut mac = <HmacSha512 as Mac>::new_from_slice(&sk).expect("HMAC accepts any key length");
    mac.update(normalised.as_bytes());
    Ok(hex::encode(mac.finalize().into_bytes()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use regex::Regex;
    use serde_json::{json, Value};
    use std::path::PathBuf;

    fn vectors_file_path() -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/pii_envelope_vectors.json")
    }

    fn load_vectors_json() -> Value {
        let path = vectors_file_path();
        let text = std::fs::read_to_string(&path)
            .unwrap_or_else(|e| panic!("failed to read vectors file {}: {e}", path.display()));
        serde_json::from_str(&text).expect("valid vectors JSON")
    }

    fn build_keyrings_from_vectors(
        data: &Value,
    ) -> (
        BTreeMap<String, KemPublicKey>,
        BTreeMap<String, KemPrivateKey>,
        [u8; 32],
    ) {
        let test_keys = &data["deterministic"]["test_keys"];
        let mut publics = BTreeMap::new();
        let mut privates = BTreeMap::new();

        for entry in test_keys["kem_keys"].as_array().expect("kem_keys array") {
            let key_id = entry["key_id"].as_str().unwrap();
            let priv_text = entry["private_key_file_text"].as_str().unwrap();
            let pub_cfg = entry["public_key_config"].as_str().unwrap();

            let priv_key = KemPrivateKey::parse_file_text(priv_text).expect("parse private key");
            let pub_key = KemPublicKey::parse(pub_cfg, key_id).expect("parse public key");

            assert_eq!(priv_key.key_id, key_id);
            assert_eq!(
                hex::encode(priv_key.mlkem_seed),
                entry["mlkem_seed_hex"].as_str().unwrap()
            );
            assert_eq!(
                hex::encode(priv_key.x25519),
                entry["x25519_private_hex"].as_str().unwrap()
            );
            assert_eq!(priv_key.public_key(), pub_key);
            assert_eq!(pub_key.to_config(), pub_cfg);
            assert_eq!(priv_key.to_file_text(), priv_text);

            let mlkem_sha256 = hex::encode(Sha256::digest(&pub_key.mlkem));
            assert_eq!(
                mlkem_sha256,
                entry["mlkem_public_sha256"].as_str().unwrap()
            );
            assert_eq!(
                hex::encode(pub_key.x25519),
                entry["x25519_public_hex"].as_str().unwrap()
            );

            publics.insert(key_id.to_string(), pub_key);
            privates.insert(key_id.to_string(), priv_key);
        }

        let blind_key = parse_blind_key(test_keys["blind_index_key_hex"].as_str().unwrap())
            .expect("parse blind key");
        (publics, privates, blind_key)
    }

    #[test]
    fn test_deterministic_vectors_and_references() {
        let data = load_vectors_json();
        let (_publics, _privates, blind_key) = build_keyrings_from_vectors(&data);
        let det = &data["deterministic"];

        // 1. Blind index checks
        let bidx = &det["blind_index"];
        assert_eq!(
            blind_key_id(&blind_key),
            bidx["blind_key_id"].as_str().unwrap()
        );

        for item in bidx["identifier"].as_array().unwrap() {
            let ctx = hex::decode(item["context_hex"].as_str().unwrap()).unwrap();
            let norm = item["normalised"].as_str().unwrap();
            let expected = item["index_hex"].as_str().unwrap();
            assert_eq!(blind_index(&blind_key, &ctx, norm), expected);
        }

        for (label, expected_val) in bidx["subkeys"].as_object().unwrap() {
            let sk = subkey(&blind_key, label).unwrap();
            assert_eq!(hex::encode(sk), expected_val.as_str().unwrap());
        }

        for item in bidx["class"].as_array().unwrap() {
            let cls = item["class"].as_str().unwrap();
            let norm = item["normalised"].as_str().unwrap();
            let expected = item["index_hex"].as_str().unwrap();
            assert_eq!(class_index(&blind_key, cls, norm).unwrap(), expected);
        }

        // Unknown class is rejected
        assert!(subkey(&blind_key, "aadhaar").is_err());
        assert!(class_index(&blind_key, "PHONE", "9876543210").is_err());

        // 2. Combiner check
        let comb = &det["combiner"];
        let inputs = &comb["inputs"];
        let ss_m: [u8; 32] = hex::decode(inputs["ss_mlkem_hex"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let ss_x: [u8; 32] = hex::decode(inputs["ss_x25519_hex"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let key_id = inputs["key_id"].as_str().unwrap();
        let ct_m = hex::decode(inputs["mlkem_ct_hex"].as_str().unwrap()).unwrap();
        let eph_pub: [u8; 32] = hex::decode(inputs["eph_pub_hex"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let pk_m = hex::decode(inputs["mlkem_pub_hex"].as_str().unwrap()).unwrap();
        let pk_x: [u8; 32] = hex::decode(inputs["x25519_pub_hex"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let kek = combine_kek(&ss_m, &ss_x, key_id, &ct_m, &eph_pub, &pk_m, &pk_x);
        assert_eq!(hex::encode(kek), comb["kek_hex"].as_str().unwrap());

        // 3. Reference primitives
        let reference = &det["reference"];
        // X25519 RFC 7748 6.1
        let x_ref = &reference["x25519_rfc7748_6_1"];
        let alice_priv: [u8; 32] = hex::decode(x_ref["alice_private_hex"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let bob_pub: [u8; 32] = hex::decode(x_ref["bob_public_hex"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let shared =
            X25519StaticSecret::from(alice_priv).diffie_hellman(&X25519PublicKey::from(bob_pub));
        assert_eq!(
            hex::encode(shared.as_bytes()),
            x_ref["shared_hex"].as_str().unwrap()
        );

        // HMAC-SHA-512 RFC 4231
        for case in reference["hmac_sha512_rfc4231"].as_array().unwrap() {
            let k = hex::decode(case["key_hex"].as_str().unwrap()).unwrap();
            let d = hex::decode(case["data_hex"].as_str().unwrap()).unwrap();
            let mut mac = <HmacSha512 as Mac>::new_from_slice(&k).unwrap();
            mac.update(&d);
            assert_eq!(
                hex::encode(mac.finalize().into_bytes()),
                case["mac_hex"].as_str().unwrap()
            );
        }

        // ML-KEM-768 pinned KAT
        let mlkem_ref = &reference["mlkem768_pinned"];
        let seed_bytes = hex::decode(mlkem_ref["seed"].as_str().unwrap()).unwrap();
        let d = B32::try_from(&seed_bytes[..32]).unwrap();
        let z = B32::try_from(&seed_bytes[32..64]).unwrap();
        let (dk, ek) = MlKem768::generate_deterministic(&d, &z);
        assert_eq!(
            hex::encode(Sha256::digest(ek.as_bytes().as_slice())),
            mlkem_ref["public_sha256"].as_str().unwrap()
        );
        let ct_bytes = hex::decode(mlkem_ref["ciphertext"].as_str().unwrap()).unwrap();
        let ct = ml_kem::Ciphertext::<MlKem768>::try_from(ct_bytes.as_slice()).unwrap();
        let ss = dk.decapsulate(&ct).unwrap();
        assert_eq!(
            hex::encode(ss.as_slice()),
            mlkem_ref["shared_secret"].as_str().unwrap()
        );
    }

    #[test]
    fn test_all_committed_envelope_vectors() {
        let data = load_vectors_json();
        let (publics, privates, _blind_key) = build_keyrings_from_vectors(&data);
        let vectors = data["vectors"].as_array().expect("vectors array");
        assert_eq!(vectors.len(), 48);

        let mut ok_count = 0usize;
        let mut fail_count = 0usize;

        for vec_obj in vectors {
            let id = vec_obj["id"].as_str().unwrap();
            let kind = vec_obj["kind"].as_str().unwrap();
            let expect = vec_obj["expect"].as_str().unwrap();
            let row_ref = vec_obj["row_ref"].as_str().unwrap();
            let dek_wrapped = vec_obj["dek_wrapped"].as_str().unwrap();

            if expect == "ok" {
                ok_count += 1;
                if kind == "value" {
                    let aad = hex::decode(vec_obj["aad_hex"].as_str().unwrap()).unwrap();
                    let vc = vec_obj["value_ciphertext"].as_str().unwrap();
                    let got = decrypt_value(vc, dek_wrapped, &aad, &privates, row_ref)
                        .unwrap_or_else(|e| panic!("vector {id} failed unexpectedly: {e}"));
                    assert_eq!(got, vec_obj["plaintext"].as_str().unwrap(), "vector {id}");
                    assert_eq!(
                        hex::encode(got.as_bytes()),
                        vec_obj["plaintext_hex"].as_str().unwrap(),
                        "vector {id} hex"
                    );
                } else if kind == "record" {
                    let table = vec_obj["table"].as_str().unwrap();
                    let row_id = hex::decode(vec_obj["row_id_hex"].as_str().unwrap()).unwrap();
                    let sealed: BTreeMap<String, String> =
                        serde_json::from_value(vec_obj["sealed"].clone()).unwrap();
                    let only_vec: Option<Vec<String>> =
                        serde_json::from_value(vec_obj["only"].clone()).unwrap();
                    let got = open_record(
                        &sealed,
                        dek_wrapped,
                        table,
                        &row_id,
                        &privates,
                        row_ref,
                        only_vec.as_deref(),
                    )
                    .unwrap_or_else(|e| panic!("vector {id} failed unexpectedly: {e}"));
                    let expected_map: BTreeMap<String, String> =
                        serde_json::from_value(vec_obj["plaintext"].clone()).unwrap();
                    assert_eq!(got, expected_map, "vector {id}");

                    let expected_hex: BTreeMap<String, String> =
                        serde_json::from_value(vec_obj["plaintext_hex"].clone()).unwrap();
                    let got_hex: BTreeMap<String, String> = got
                        .iter()
                        .map(|(k, v)| (k.clone(), hex::encode(v.as_bytes())))
                        .collect();
                    assert_eq!(got_hex, expected_hex, "vector {id} hex");
                } else {
                    panic!("unknown vector kind {kind}");
                }

                // Check intermediate values when present
                if let Some(inter) = vec_obj.get("intermediate").and_then(|v| v.as_object()) {
                    let unwrapped = unwrap_dek(dek_wrapped, &privates, row_ref).unwrap();
                    assert_eq!(
                        hex::encode(unwrapped),
                        inter["dek_hex"].as_str().unwrap(),
                        "vector {id} dek_hex"
                    );

                    // Also verify intermediate combiner KEK matches
                    let key_id = vec_obj["key_id"].as_str().unwrap();
                    let pub_key = &publics[key_id];
                    let parts: Vec<&str> = dek_wrapped.splitn(4, ':').collect();
                    let raw = b64u_decode_strict(parts[3]).unwrap();
                    let ct_m = &raw[..MLKEM768_CIPHERTEXT_LEN];
                    let eph_pub: [u8; 32] = raw
                        [MLKEM768_CIPHERTEXT_LEN..MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN]
                        .try_into()
                        .unwrap();
                    let wrap_nonce = &raw[MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN
                        ..MLKEM768_CIPHERTEXT_LEN + X25519_KEY_LEN + NONCE_LEN];
                    assert_eq!(
                        hex::encode(wrap_nonce),
                        inter["wrap_nonce_hex"].as_str().unwrap()
                    );
                    let ss_m: [u8; 32] = hex::decode(inter["ss_mlkem_hex"].as_str().unwrap())
                        .unwrap()
                        .try_into()
                        .unwrap();
                    let ss_x: [u8; 32] = hex::decode(inter["ss_x25519_hex"].as_str().unwrap())
                        .unwrap()
                        .try_into()
                        .unwrap();
                    let kek = combine_kek(
                        &ss_m,
                        &ss_x,
                        key_id,
                        ct_m,
                        &eph_pub,
                        &pub_key.mlkem,
                        &pub_key.x25519,
                    );
                    assert_eq!(
                        hex::encode(kek),
                        inter["kek_hex"].as_str().unwrap(),
                        "vector {id} kek_hex"
                    );
                }
            } else if expect == "fail" {
                fail_count += 1;
                let err = if kind == "value" {
                    let aad = hex::decode(vec_obj["aad_hex"].as_str().unwrap()).unwrap();
                    let vc = vec_obj["value_ciphertext"].as_str().unwrap();
                    decrypt_value(vc, dek_wrapped, &aad, &privates, row_ref)
                        .expect_err(&format!("vector {id} should have failed"))
                } else {
                    let table = vec_obj["table"].as_str().unwrap();
                    let row_id = hex::decode(vec_obj["row_id_hex"].as_str().unwrap()).unwrap();
                    let sealed: BTreeMap<String, String> =
                        serde_json::from_value(vec_obj["sealed"].clone()).unwrap();
                    let only_vec: Option<Vec<String>> =
                        serde_json::from_value(vec_obj["only"].clone()).unwrap();
                    open_record(
                        &sealed,
                        dek_wrapped,
                        table,
                        &row_id,
                        &privates,
                        row_ref,
                        only_vec.as_deref(),
                    )
                    .expect_err(&format!("vector {id} should have failed"))
                };

                let pattern = format!(
                    r"^PII value could not be decrypted \(row {}, key ([A-Za-z0-9_-]{{1,16}}|\?)\)\.$",
                    regex::escape(row_ref)
                );
                let re = Regex::new(&pattern).unwrap();
                let msg = err.to_string();
                assert!(
                    re.is_match(&msg),
                    "vector {id} error message '{msg}' did not match '{pattern}'"
                );
            } else {
                panic!("unexpected expect value {expect}");
            }
        }

        assert_eq!(ok_count, 14);
        assert_eq!(fail_count, 34);
    }

    #[test]
    fn test_rust_to_python_interoperability_vectors() {
        let data = load_vectors_json();
        let (publics, privates, _blind_key) = build_keyrings_from_vectors(&data);
        let tv1_pub = &publics["tv1"];
        let tv2_pub = &publics["tv2"];

        let aad = hex::decode("0d1e00000000400080000000000000017e9e0000000040008000000000000002")
            .unwrap();
        let (vc1, dw1, kid1) = encrypt_value("MCCD/2026/000777", &aad, tv1_pub);
        assert_eq!(kid1, "tv1");
        let (vc_uni, dw_uni, _) = encrypt_value("Zoë e\u{0301} राम 😀", &aad, tv2_pub);

        let row_id = hex::decode("5e1f0000000040008000000000000011").unwrap();
        let mut rec_fields = BTreeMap::new();
        rec_fields.insert("Id10017".to_string(), "\"Asha\"".to_string());
        rec_fields.insert("Id10018".to_string(), "\"Devi\"".to_string());
        rec_fields.insert("Id10073".to_string(), "\"XXXXXXXXX123\"".to_string());
        let (sealed_rec, dw_rec, _) =
            seal_record(&rec_fields, "map_payload_version_pii", &row_id, tv1_pub).unwrap();
        let (dw_rec_tv2, rewrap_kid) =
            rewrap_dek(&dw_rec, &privates, tv2_pub, "rust-record-rewrap").unwrap();
        assert_eq!(rewrap_kid, "tv2");

        let rust_vectors = json!({
            "format": "digitva-pii-envelope-vectors/v1",
            "producer": "digitva-pii (Rust)",
            "vectors": [
                {
                    "id": "rust-value-tv1",
                    "kind": "value",
                    "current_key_id": "tv1",
                    "aad_hex": hex::encode(&aad),
                    "value_ciphertext": vc1,
                    "dek_wrapped": dw1,
                    "row_ref": "rust-value-tv1",
                    "expect": "ok",
                    "plaintext": "MCCD/2026/000777",
                    "plaintext_hex": hex::encode("MCCD/2026/000777".as_bytes())
                },
                {
                    "id": "rust-value-unicode-tv2",
                    "kind": "value",
                    "current_key_id": "tv2",
                    "aad_hex": hex::encode(&aad),
                    "value_ciphertext": vc_uni,
                    "dek_wrapped": dw_uni,
                    "row_ref": "rust-value-unicode-tv2",
                    "expect": "ok",
                    "plaintext": "Zoë e\u{0301} राम 😀",
                    "plaintext_hex": hex::encode("Zoë e\u{0301} राम 😀".as_bytes())
                },
                {
                    "id": "rust-record-tv1",
                    "kind": "record",
                    "current_key_id": "tv1",
                    "table": "map_payload_version_pii",
                    "row_id_hex": hex::encode(&row_id),
                    "sealed": sealed_rec,
                    "dek_wrapped": dw_rec,
                    "only": null,
                    "row_ref": "rust-record-tv1",
                    "expect": "ok",
                    "plaintext": rec_fields
                },
                {
                    "id": "rust-record-rewrapped-tv2",
                    "kind": "record",
                    "current_key_id": "tv2",
                    "table": "map_payload_version_pii",
                    "row_id_hex": hex::encode(&row_id),
                    "sealed": sealed_rec,
                    "dek_wrapped": dw_rec_tv2,
                    "only": null,
                    "row_ref": "rust-record-rewrapped-tv2",
                    "expect": "ok",
                    "plaintext": rec_fields
                },
                {
                    "id": "rust-fail-wrong-aad",
                    "kind": "value",
                    "current_key_id": "tv1",
                    "aad_hex": "0000",
                    "value_ciphertext": vc1,
                    "dek_wrapped": dw1,
                    "row_ref": "rust-fail-wrong-aad",
                    "expect": "fail"
                }
            ]
        });

        // Verify Rust opens all positive vectors and fails negative vectors in `rust_vectors`
        for v in rust_vectors["vectors"].as_array().unwrap() {
            let expect = v["expect"].as_str().unwrap();
            let kind = v["kind"].as_str().unwrap();
            let row_ref = v["row_ref"].as_str().unwrap();
            let dw = v["dek_wrapped"].as_str().unwrap();
            if expect == "ok" {
                if kind == "value" {
                    let a = hex::decode(v["aad_hex"].as_str().unwrap()).unwrap();
                    let vc = v["value_ciphertext"].as_str().unwrap();
                    let pt = decrypt_value(vc, dw, &a, &privates, row_ref).unwrap();
                    assert_eq!(pt, v["plaintext"].as_str().unwrap());
                } else {
                    let tbl = v["table"].as_str().unwrap();
                    let rid = hex::decode(v["row_id_hex"].as_str().unwrap()).unwrap();
                    let s: BTreeMap<String, String> =
                        serde_json::from_value(v["sealed"].clone()).unwrap();
                    let pt = open_record(&s, dw, tbl, &rid, &privates, row_ref, None).unwrap();
                    let exp: BTreeMap<String, String> =
                        serde_json::from_value(v["plaintext"].clone()).unwrap();
                    assert_eq!(pt, exp);
                }
            } else {
                let a = hex::decode(v["aad_hex"].as_str().unwrap()).unwrap();
                let vc = v["value_ciphertext"].as_str().unwrap();
                assert!(decrypt_value(vc, dw, &a, &privates, row_ref).is_err());
            }
        }

        // Write to a temporary file and validate schema
        let tmp_path = std::env::temp_dir().join(format!(
            "digitva_rust_to_python_vectors_{}.json",
             std::process::id()
        ));
        std::fs::write(
            &tmp_path,
            serde_json::to_string_pretty(&rust_vectors).unwrap(),
        )
        .unwrap();
        let reloaded: Value =
            serde_json::from_str(&std::fs::read_to_string(&tmp_path).unwrap()).unwrap();
        assert_eq!(reloaded["format"], "digitva-pii-envelope-vectors/v1");
        assert_eq!(reloaded["vectors"].as_array().unwrap().len(), 5);
        if let Ok(emit_path) = std::env::var("DIGITVA_EMIT_RUST_VECTORS_PATH") {
            std::fs::copy(&tmp_path, emit_path).unwrap();
        }
        let _ = std::fs::remove_file(&tmp_path);
    }

    #[test]
    fn test_record_aad_refuses_null_bytes_and_non_ascii_table() {
        let row_id = [0x11u8; 16];
        assert!(record_aad("valid_table", "valid_field", &row_id).is_ok());
        assert!(record_aad("bad\0table", "field", &row_id).is_err());
        assert!(record_aad("table", "bad\0field", &row_id).is_err());
        assert!(record_aad("tåble", "field", &row_id).is_err());
    }

    #[test]
    fn test_key_validation_refuses_malformed_inputs() {
        let data = load_vectors_json();
        let (publics, _privates, _blind_key) = build_keyrings_from_vectors(&data);
        let tv1_cfg = publics["tv1"].to_config();

        // Bad key_id
        assert!(KemPublicKey::parse(&tv1_cfg, "").is_err());
        assert!(KemPublicKey::parse(&tv1_cfg, "too_long_key_id_17").is_err());
        assert!(KemPublicKey::parse(&tv1_cfg, "bad:id").is_err());
        assert!(KemPublicKey::parse(&tv1_cfg, "bad\nid").is_err());

        // Non-canonical ML-KEM coefficient >= q (3329): all 0xFF bytes in ML-KEM public key
        let bad_mlkem = vec![0xFFu8; MLKEM768_PUBLIC_KEY_LEN];
        let bad_cfg = format!("{}.{}", b64u_encode(&bad_mlkem), b64u_encode(&[0x11u8; 32]));
        assert!(KemPublicKey::parse(&bad_cfg, "tv1").is_err());
    }
}
