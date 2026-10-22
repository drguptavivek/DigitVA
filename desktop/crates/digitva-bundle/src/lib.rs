//! Offline `.dvb` bundle writer, station config verifier, and receipt processor
//! (`docs/policy/offline-bundle-and-transfer.md` and `docs/policy/offline-api-contract.md`).

use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use chrono::{DateTime, Utc};
use digitva_pii::{
    record_aad, seal_bytes_with_dek, wrap_dek, wrap_dek_deterministic, KemPublicKey,
    PiiKeyConfigError, DEK_LEN, NONCE_LEN,
};
use digitva_text::{is_reduced_national_id, to_jcs_string, NATIONAL_ID_FIELD};
use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey};
use rand::rngs::OsRng;
use rand::RngCore;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::io::Write;
use std::path::Path;
use unicode_normalization::UnicodeNormalization;
use uuid::Uuid;

pub const BUNDLE_FORMAT_VERSION: u32 = 1;
pub const STATION_CONFIG_FORMAT_VERSION: u32 = 1;

/// Maximum total bundle size in bytes (50 MiB).
pub const BUNDLE_MAX_BYTES: usize = 50 * 1024 * 1024;
/// Maximum number of records per bundle (5,000).
pub const BUNDLE_MAX_RECORDS: usize = 5_000;
/// Maximum byte length of a single record line including LF (2 MiB + 64 KiB).
pub const BUNDLE_MAX_LINE_BYTES: usize = 2 * 1024 * 1024 + 64 * 1024;
/// Maximum byte length of the manifest line (256 KiB).
pub const BUNDLE_MAX_MANIFEST_BYTES: usize = 256 * 1024;
/// Maximum number of supervisor correction records (`death_correction` + `identifiers_set`) per bundle.
pub const BUNDLE_MAX_CORRECTIONS: usize = 500;
/// Maximum byte length of `answers_json` (1 MiB).
pub const ANSWERS_JSON_MAX_BYTES: usize = 1024 * 1024;
/// Maximum byte length of a correction record plaintext / line (16 KiB).
pub const CORRECTION_MAX_LINE_BYTES: usize = 16 * 1024;

/// Ed25519 domain separation prefix for bundle manifest signatures (`"digitva-bundle-v1\0"`).
pub const BUNDLE_SIG_DOMAIN: &[u8] = b"digitva-bundle-v1\x00";
/// Ed25519 domain separation prefix for signed station configs (`"digitva-station-config-v1\0"`).
pub const STATION_CONFIG_SIG_DOMAIN: &[u8] = b"digitva-station-config-v1\x00";
/// Ed25519 domain separation prefix for signed ingest receipts (`"digitva-receipt-v1\0"`).
pub const RECEIPT_SIG_DOMAIN: &[u8] = b"digitva-receipt-v1\x00";

/// AAD table name for bundle records (`offline-bundle-and-transfer.md` Section 2.3).
pub const BUNDLE_AAD_TABLE: &str = "digitva_bundle";

/// Informant register fields that require a granted registration consent on `death_registration`.
pub const INFORMANT_REGISTER_FIELDS: &[&str] = &[
    "informant_name",
    "informant_phone",
    "informant_phone_2",
    "address",
    "address_house_street",
    "address_village_ward",
    "address_landmark",
];

/// Typed errors returned by `digitva-bundle`.
/// Never contains plaintext PII, Aadhaar digits, phone numbers, answers, or key material.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum BundleError {
    #[error("Station config format is invalid: {0}")]
    StationConfigInvalid(String),
    #[error("Station config signature verification failed.")]
    StationConfigSignatureInvalid,
    #[error("Station config unsupported version: {0}")]
    StationConfigVersionUnsupported(u32),
    #[error("Station config device_id mismatch (expected {expected}, got {actual}).")]
    StationConfigDeviceMismatch { expected: String, actual: String },
    #[error("Station config has no valid custodian onboarding record.")]
    StationNotOnboarded,
    #[error("Station config expired at {expires_at}.")]
    StationConfigExpired { expires_at: String },
    #[error("KEM key configuration error: {0}")]
    KemKeyInvalid(#[from] PiiKeyConfigError),
    #[error("Bundle must contain between 1 and {BUNDLE_MAX_RECORDS} records (got {0}).")]
    RecordCountOutOfRange(usize),
    #[error("Bundle exceeds maximum of {BUNDLE_MAX_CORRECTIONS} correction records (got {0}).")]
    TooManyCorrections(usize),
    #[error("Bundle sequence number must be >= 1.")]
    InvalidBundleSeq,
    #[error("Duplicate record client_id {0} in bundle.")]
    DuplicateClientId(Uuid),
    #[error("Actor user_id {actor_user_id} is not an active roster member with role {acting_role} for record {client_id}.")]
    ActorNotAuthorizedOnRoster {
        client_id: Uuid,
        actor_user_id: i64,
        acting_role: String,
    },
    #[error("Record {client_id} of type {record_type} cannot be submitted under acting_role {acting_role}.")]
    InvalidActingRoleForRecord {
        client_id: Uuid,
        record_type: String,
        acting_role: String,
    },
    #[error("Supervisor correction record {client_id} requires a non-empty reason of at most 500 characters.")]
    InvalidCorrectionReason { client_id: Uuid },
    #[error("Death registration {client_id} carries informant fields without a granted registration consent.")]
    ConsentRequired { client_id: Uuid },
    #[error("Interview submission {client_id} answers_sha256 does not match UTF-8 bytes of answers_json.")]
    AnswersHashMismatch { client_id: Uuid },
    #[error("Interview submission {client_id} violates the Id10073 reduced national ID rule.")]
    UnreducedNationalId { client_id: Uuid },
    #[error("Record {client_id} is invalid: {reason}")]
    RecordInvalid { client_id: Uuid, reason: String },
    #[error("Canonical JSON (JCS) error: {0}")]
    CanonicalJsonError(String),
    #[error("Bundle size or line limit exceeded: {0}")]
    SizeLimitExceeded(String),
    #[error("Receipt verification failed: {0}")]
    ReceiptInvalid(String),
    #[error("Bundle I/O error: {0}")]
    IoError(String),
}

#[inline]
fn b64u_encode(raw: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(raw)
}

#[inline]
fn b64u_decode(text: &str) -> Result<Vec<u8>, String> {
    let trimmed = text.trim_end_matches('=');
    if text.len() - trimmed.len() > 2 {
        return Err("excess base64 padding".to_string());
    }
    URL_SAFE_NO_PAD
        .decode(trimmed)
        .map_err(|_| "invalid base64url encoding".to_string())
}

/// Compute lowercase hex SHA-256 of `bytes`.
pub fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

/// Compute the 16-hex-character `signing_key_id` from a 32-byte Ed25519 public key
/// (`offline-bundle-and-transfer.md` Section 3.2: first 16 lowercase hex chars of SHA-256).
pub fn compute_signing_key_id(public_key_bytes: &[u8; 32]) -> String {
    let digest = Sha256::digest(public_key_bytes);
    hex::encode(&digest[..8])
}

/// Line 2 signature object used by `.dvb` bundles, signed station configs, and signed receipts.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BundleSignatureLine {
    pub alg: String,
    pub sig: String,
    pub signing_key_id: String,
}

/// Station or server Ed25519 signing key (RFC 8032 pure Ed25519, no prehash).
#[derive(Clone)]
pub struct StationSigningKey {
    signing_key: SigningKey,
}

impl fmt::Debug for StationSigningKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("StationSigningKey")
            .field("signing_key_id", &self.signing_key_id())
            .finish_non_exhaustive()
    }
}

impl StationSigningKey {
    /// Generate a new random Ed25519 signing key from the OS CSPRNG.
    pub fn generate() -> Self {
        let mut secret = [0u8; 32];
        OsRng.fill_bytes(&mut secret);
        Self::from_secret_bytes(&secret)
    }

    /// Construct from a 32-byte Ed25519 secret key seed.
    pub fn from_secret_bytes(secret: &[u8; 32]) -> Self {
        Self {
            signing_key: SigningKey::from_bytes(secret),
        }
    }

    /// Parse a 32-byte Ed25519 secret seed from base64url text.
    pub fn from_base64url_secret(text: &str) -> Result<Self, BundleError> {
        let raw = b64u_decode(text.trim())
            .map_err(|_| BundleError::StationConfigInvalid("Malformed Ed25519 secret key.".to_string()))?;
        let arr: [u8; 32] = raw
            .try_into()
            .map_err(|_| BundleError::StationConfigInvalid("Ed25519 secret key must be 32 bytes.".to_string()))?;
        Ok(Self::from_secret_bytes(&arr))
    }

    /// Raw 32-byte Ed25519 public key.
    pub fn public_key_bytes(&self) -> [u8; 32] {
        self.signing_key.verifying_key().to_bytes()
    }

    /// Unpadded base64url encoding of the 32-byte Ed25519 public key.
    pub fn public_key_base64url(&self) -> String {
        b64u_encode(&self.public_key_bytes())
    }

    /// First 16 lowercase hex characters of `SHA-256(public_key_bytes)`.
    pub fn signing_key_id(&self) -> String {
        compute_signing_key_id(&self.public_key_bytes())
    }

    /// Sign `domain_prefix || line1_without_lf` and return the `BundleSignatureLine`.
    pub fn sign_with_domain(&self, domain_prefix: &[u8], line1_without_lf: &[u8]) -> BundleSignatureLine {
        let mut msg = Vec::with_capacity(domain_prefix.len() + line1_without_lf.len());
        msg.extend_from_slice(domain_prefix);
        msg.extend_from_slice(line1_without_lf);
        let sig: Signature = self.signing_key.sign(&msg);
        BundleSignatureLine {
            alg: "ed25519".to_string(),
            sig: b64u_encode(&sig.to_bytes()),
            signing_key_id: self.signing_key_id(),
        }
    }

    /// Sign a bundle manifest line (`b"digitva-bundle-v1\x00" || manifest_line_bytes`).
    pub fn sign_manifest_line(&self, manifest_line_without_lf: &[u8]) -> BundleSignatureLine {
        self.sign_with_domain(BUNDLE_SIG_DOMAIN, manifest_line_without_lf)
    }
}

/// Verify an Ed25519 `BundleSignatureLine` over `domain_prefix || line1_without_lf`.
pub fn verify_ed25519_signature_line(
    public_key_bytes: &[u8; 32],
    domain_prefix: &[u8],
    line1_without_lf: &[u8],
    sig_line_json: &str,
) -> Result<BundleSignatureLine, BundleError> {
    let sig_obj: BundleSignatureLine = serde_json::from_str(sig_line_json)
        .map_err(|_| BundleError::StationConfigSignatureInvalid)?;
    if sig_obj.alg != "ed25519" {
        return Err(BundleError::StationConfigSignatureInvalid);
    }
    let expected_key_id = compute_signing_key_id(public_key_bytes);
    if sig_obj.signing_key_id != expected_key_id {
        return Err(BundleError::StationConfigSignatureInvalid);
    }
    let sig_bytes = b64u_decode(&sig_obj.sig)
        .map_err(|_| BundleError::StationConfigSignatureInvalid)?;
    let sig_arr: [u8; 64] = sig_bytes
        .try_into()
        .map_err(|_| BundleError::StationConfigSignatureInvalid)?;
    let signature = Signature::from_bytes(&sig_arr);
    let verifying_key = VerifyingKey::from_bytes(public_key_bytes)
        .map_err(|_| BundleError::StationConfigSignatureInvalid)?;

    let mut msg = Vec::with_capacity(domain_prefix.len() + line1_without_lf.len());
    msg.extend_from_slice(domain_prefix);
    msg.extend_from_slice(line1_without_lf);

    verifying_key
        .verify_strict(&msg, &signature)
        .map_err(|_| BundleError::StationConfigSignatureInvalid)?;
    Ok(sig_obj)
}

// ============================================================================
// Station Config (`offline-bundle-and-transfer.md` Section 6.4, Contract 4.1)
// ============================================================================

/// Roster role / acting role (`death_reporter`, `interviewer`, `station_supervisor`, `coder`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ActingRole {
    DeathReporter,
    Interviewer,
    StationSupervisor,
    Coder,
}

impl ActingRole {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::DeathReporter => "death_reporter",
            Self::Interviewer => "interviewer",
            Self::StationSupervisor => "station_supervisor",
            Self::Coder => "coder",
        }
    }
}

impl fmt::Display for ActingRole {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StationKemPublicKeyConfig {
    pub key_id: String,
    pub public: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ServerSigningKeyConfig {
    pub signing_key_id: String,
    pub public: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StationCustodian {
    pub name: String,
    pub designation: String,
    pub phone: Option<String>,
    pub email: Option<String>,
    pub onboarded_on: String,
    pub verified_by_user_id: i64,
}

impl StationCustodian {
    pub fn is_valid(&self) -> bool {
        let has_name = !self.name.trim().is_empty();
        let has_desig = !self.designation.trim().is_empty();
        let has_date = !self.onboarded_on.trim().is_empty();
        let has_phone = self
            .phone
            .as_deref()
            .map(|p| !p.trim().is_empty())
            .unwrap_or(false);
        let has_email = self
            .email
            .as_deref()
            .map(|e| !e.trim().is_empty())
            .unwrap_or(false);
        has_name && has_desig && has_date && (has_phone || has_email)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DesignationSpec {
    pub code: String,
    pub label: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RosterRoleGrant {
    pub role: ActingRole,
    pub project_id: String,
    pub site_id: String,
    pub org_unit_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RosterMember {
    pub user_id: i64,
    pub name: String,
    pub designation: String,
    pub roles: Vec<RosterRoleGrant>,
    pub active: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StationProjectConfig {
    pub project_id: String,
    /// The project's display name; configs that omit it show the id instead.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project_name: Option<String>,
    #[serde(default)]
    pub sites: Vec<String>,
    #[serde(default)]
    pub org_units: Vec<String>,
    /// Optional display names, `{site_id: name}`; older configs omit it (labels fall back to ids).
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub site_names: BTreeMap<String, String>,
    /// Optional display paths, `{org_unit_id: "District, Block, PHC"}` (top of the project's
    /// tree down to the unit, ", "-separated); older configs omit it.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub org_unit_paths: BTreeMap<String, String>,
    /// Optional `{org_unit_id: site_id}`; lets a roster grant without an org unit cover only that
    /// site's units. Older configs omit it (such a grant then covers every project org unit).
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub org_unit_sites: BTreeMap<String, String>,
    #[serde(default)]
    pub sealed_field_ids: Vec<String>,
    #[serde(default)]
    pub instrument_versions: Vec<String>,
    #[serde(default)]
    pub consent: Option<Value>,
    /// The project's form-options body exactly as the server's
    /// `GET /organization/<project>/form-options` serves it (enabled modules, locales, narration
    /// languages, translation versions, `instrument_version`, `definition_sha256`). Older
    /// configs omit it; the station then offers no form for the project.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub form_options: Option<Value>,
    /// `{locale: body}` of `GET /instruments/<code>/translations/<locale>` for each non-English
    /// locale the project offers.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub translations: BTreeMap<String, Value>,
    /// The station coding mode the project's own mode locks the station to (contract 4.3):
    /// `None` when the config predates the key (the station keeps its local choice),
    /// `Some(None)` for `null` (the station does not code this project), else
    /// `Some(Some("icd11_doris" | "icd10"))`.
    #[serde(default, deserialize_with = "present_option", skip_serializing_if = "Option::is_none")]
    pub coding_mode: Option<Option<String>>,
}

/// Wraps a present key in `Some`, so `null` reads as `Some(None)` and a missing key (serde
/// `default`) stays `None`.
fn present_option<'de, D: serde::Deserializer<'de>>(d: D) -> Result<Option<Option<String>>, D::Error> {
    Option::<String>::deserialize(d).map(Some)
}

/// Line 1 payload of the signed two-line station configuration file.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct StationConfigPayload {
    pub station_config_format_version: u32,
    pub config_id: Uuid,
    pub issued_at: String,
    pub expires_at: String,
    pub device_id: String,
    pub server_url: String,
    pub kem_public_key: StationKemPublicKeyConfig,
    pub server_signing_key: ServerSigningKeyConfig,
    #[serde(default)]
    pub projects: Vec<StationProjectConfig>,
    pub custodian: Option<StationCustodian>,
    #[serde(default)]
    pub designations: Vec<DesignationSpec>,
    #[serde(default)]
    pub roster: Vec<RosterMember>,
    #[serde(default)]
    pub purge: Vec<Uuid>,
}

/// Verified station configuration parsed from a two-line signed station config file.
#[derive(Debug, Clone)]
pub struct VerifiedStationConfig {
    pub config: StationConfigPayload,
    pub kem_public_key: KemPublicKey,
    pub server_verifying_key: [u8; 32],
    pub issued_at: DateTime<Utc>,
    pub expires_at: DateTime<Utc>,
}

fn split_two_line_signed_blob(raw: &str) -> Result<(&str, &str), String> {
    if raw.starts_with('\u{feff}') || raw.contains('\r') {
        return Err("Signed file must not contain BOM or CR.".to_string());
    }
    let stripped = raw.strip_suffix('\n').unwrap_or(raw);
    let mut lines = stripped.split('\n');
    let (Some(line1), Some(line2), None) = (lines.next(), lines.next(), lines.next()) else {
        return Err("Signed file must have exactly two lines.".to_string());
    };
    if line1.is_empty() || line2.is_empty() {
        return Err("Signed file lines must not be empty.".to_string());
    }
    Ok((line1, line2))
}

impl VerifiedStationConfig {
    /// Parse and verify a two-line signed station config (`b"digitva-station-config-v1\x00" || line1`).
    ///
    /// When `pinned_server_public_key` is provided, verifies the signature under the pinned key
    /// (allowing key rotation only via a config signed by the old key); otherwise verifies under
    /// `server_signing_key.public`.
    pub fn parse_and_verify(
        raw_two_line_text: &str,
        expected_device_id: &str,
        pinned_server_public_key: Option<&[u8; 32]>,
    ) -> Result<Self, BundleError> {
        let (line1, line2) = split_two_line_signed_blob(raw_two_line_text)
            .map_err(BundleError::StationConfigInvalid)?;

        let config: StationConfigPayload = serde_json::from_str(line1)
            .map_err(|e| BundleError::StationConfigInvalid(format!("Invalid JSON on line 1: {e}")))?;

        if config.station_config_format_version != STATION_CONFIG_FORMAT_VERSION {
            return Err(BundleError::StationConfigVersionUnsupported(
                config.station_config_format_version,
            ));
        }

        let payload_pub_vec = b64u_decode(&config.server_signing_key.public)
            .map_err(|_| BundleError::StationConfigInvalid("Malformed server_signing_key.public.".to_string()))?;
        let payload_pub_bytes: [u8; 32] = payload_pub_vec
            .try_into()
            .map_err(|_| BundleError::StationConfigInvalid("server_signing_key.public must be 32 bytes.".to_string()))?;
        if compute_signing_key_id(&payload_pub_bytes) != config.server_signing_key.signing_key_id {
            return Err(BundleError::StationConfigInvalid(
                "server_signing_key.signing_key_id does not match public key.".to_string(),
            ));
        }

        let verify_key = pinned_server_public_key.unwrap_or(&payload_pub_bytes);
        verify_ed25519_signature_line(verify_key, STATION_CONFIG_SIG_DOMAIN, line1.as_bytes(), line2)?;

        if config.device_id != expected_device_id {
            return Err(BundleError::StationConfigDeviceMismatch {
                expected: expected_device_id.to_string(),
                actual: config.device_id,
            });
        }

        let Some(ref custodian) = config.custodian else {
            return Err(BundleError::StationNotOnboarded);
        };
        if !custodian.is_valid() {
            return Err(BundleError::StationNotOnboarded);
        }

        let kem_public_key =
            KemPublicKey::parse(&config.kem_public_key.public, &config.kem_public_key.key_id)?;

        let issued_at = DateTime::parse_from_rfc3339(&config.issued_at)
            .map_err(|_| BundleError::StationConfigInvalid("Invalid issued_at timestamp.".to_string()))?
            .with_timezone(&Utc);
        let expires_at = DateTime::parse_from_rfc3339(&config.expires_at)
            .map_err(|_| BundleError::StationConfigInvalid("Invalid expires_at timestamp.".to_string()))?
            .with_timezone(&Utc);

        Ok(Self {
            config,
            kem_public_key,
            server_verifying_key: payload_pub_bytes,
            issued_at,
            expires_at,
        })
    }

    /// True if `now` is strictly after `expires_at`.
    pub fn is_expired(&self, now: DateTime<Utc>) -> bool {
        now > self.expires_at
    }

    /// Whole days remaining until `expires_at` (negative if already expired).
    pub fn days_until_expiry(&self, now: DateTime<Utc>) -> i64 {
        (self.expires_at - now).num_days()
    }

    /// True when 30 days or fewer remain before `expires_at` (`offline-bundle-and-transfer.md` Q9).
    pub fn needs_expiry_warning(&self, now: DateTime<Utc>) -> bool {
        (self.expires_at - now) <= chrono::Duration::days(30)
    }
}

/// Serialize and sign a `StationConfigPayload` into its canonical two-line form.
pub fn format_signed_station_config(
    payload: &StationConfigPayload,
    server_signing_key: &StationSigningKey,
) -> Result<String, BundleError> {
    let val = serde_json::to_value(payload)
        .map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;
    let line1 = to_jcs_string(&val).map_err(BundleError::CanonicalJsonError)?;
    let sig = server_signing_key.sign_with_domain(STATION_CONFIG_SIG_DOMAIN, line1.as_bytes());
    let sig_val =
        serde_json::to_value(&sig).map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;
    let line2 = to_jcs_string(&sig_val).map_err(BundleError::CanonicalJsonError)?;
    Ok(format!("{line1}\n{line2}\n"))
}

// ============================================================================
// Typed Bundle Records (`offline-bundle-and-transfer.md` Section 2.4)
// ============================================================================

/// Bundle record type in exact ingest/processing order (`offline-bundle-and-transfer.md` Section 5.3):
/// `death_registration`, `consent`, `death_correction`, `interview_submission`, `identifiers_set`, `coding_result`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordType {
    DeathRegistration,
    Consent,
    DeathCorrection,
    InterviewSubmission,
    IdentifiersSet,
    CodingResult,
    /// Reserved by the spec (digitva-jkvl): parsed in server receipts, never written or built here.
    AttachmentChunk,
}

impl RecordType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::DeathRegistration => "death_registration",
            Self::Consent => "consent",
            Self::DeathCorrection => "death_correction",
            Self::InterviewSubmission => "interview_submission",
            Self::IdentifiersSet => "identifiers_set",
            Self::CodingResult => "coding_result",
            Self::AttachmentChunk => "attachment_chunk",
        }
    }
}

impl fmt::Display for RecordType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Reference to a death case: either station-local `client_death_id` or server `death_id`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum DeathRef {
    ClientDeath { client_death_id: Uuid },
    ServerDeath { death_id: Uuid },
}

impl DeathRef {
    pub fn client_death(client_death_id: Uuid) -> Self {
        Self::ClientDeath { client_death_id }
    }

    pub fn server_death(death_id: Uuid) -> Self {
        Self::ServerDeath { death_id }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeathRegistrationRecord {
    pub site_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub org_unit_id: Option<String>,
    #[serde(flatten)]
    pub fields: BTreeMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub identifiers: Option<BTreeMap<String, String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub consent_client_id: Option<Uuid>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConsentDecision {
    Granted,
    Refused,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ConsentMode {
    Spoken,
    Tap,
    Signed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConsentPurposeGrant {
    pub code: String,
    pub granted: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ConsentRecord {
    pub death_ref: DeathRef,
    pub client_draft_id: Option<Uuid>,
    pub notice_version_id: Uuid,
    pub notice_language: String,
    pub notice_sha256: String,
    pub decision: ConsentDecision,
    pub purposes: Vec<ConsentPurposeGrant>,
    pub mode: ConsentMode,
    pub witness_present: bool,
    pub supersedes_client_id: Option<Uuid>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeathCorrectionRecord {
    pub death_ref: DeathRef,
    pub reason: String,
    pub if_updated_at: Option<String>,
    pub base_client_id: Option<Uuid>,
    pub changes: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IdentifiersSetRecord {
    pub death_ref: DeathRef,
    pub reason: String,
    pub if_updated_at: Option<String>,
    pub base_client_id: Option<Uuid>,
    pub identifiers: BTreeMap<String, Option<String>>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterviewDraftMeta {
    #[serde(rename = "instrumentVersion")]
    pub instrument_version: String,
    /// SHA-256 of the served definition slice the answers were filled on; absent only for an
    /// interview that recorded none (the server accepts absent, as from an older app).
    #[serde(rename = "definitionSha256", default, skip_serializing_if = "Option::is_none")]
    pub definition_sha256: Option<String>,
    #[serde(
        rename = "definitionExtensions",
        skip_serializing_if = "Option::is_none"
    )]
    pub definition_extensions: Option<Value>,
    #[serde(rename = "startedAt")]
    pub started_at: String,
    #[serde(rename = "completedAt", skip_serializing_if = "Option::is_none")]
    pub completed_at: Option<String>,
    #[serde(rename = "deviceClockAt", skip_serializing_if = "Option::is_none")]
    pub device_clock_at: Option<String>,
    #[serde(rename = "interviewOutcome")]
    pub interview_outcome: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterviewCompletion {
    pub valid: bool,
    pub issues: Vec<Value>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InterviewSubmissionRecord {
    pub site_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub org_unit_id: Option<String>,
    pub death_ref: DeathRef,
    pub draft: InterviewDraftMeta,
    pub completion: InterviewCompletion,
    pub answers_json: String,
    pub answers_sha256: String,
    pub consent_client_id: Option<Uuid>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CodingResultKind {
    Final,
    NotCodeable,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CodingResultRecord {
    pub client_draft_id: Uuid,
    pub coded_answers_sha256: String,
    pub kind: CodingResultKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub initial: Option<Value>,
    #[serde(rename = "final", skip_serializing_if = "Option::is_none")]
    pub final_cod: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub not_codeable: Option<Value>,
    /// The station coding mode the result was made in: `icd11_doris` or `icd10` (absent from
    /// records made before stations chose one).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub coding_mode: Option<String>,
}

/// Typed payload variants for a bundle record.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BundleRecordPayload {
    DeathRegistration(DeathRegistrationRecord),
    Consent(ConsentRecord),
    DeathCorrection(DeathCorrectionRecord),
    InterviewSubmission(InterviewSubmissionRecord),
    IdentifiersSet(IdentifiersSetRecord),
    CodingResult(CodingResultRecord),
}

impl BundleRecordPayload {
    pub fn record_type(&self) -> RecordType {
        match self {
            Self::DeathRegistration(_) => RecordType::DeathRegistration,
            Self::Consent(_) => RecordType::Consent,
            Self::DeathCorrection(_) => RecordType::DeathCorrection,
            Self::InterviewSubmission(_) => RecordType::InterviewSubmission,
            Self::IdentifiersSet(_) => RecordType::IdentifiersSet,
            Self::CodingResult(_) => RecordType::CodingResult,
        }
    }
}

/// Complete record envelope to be sealed into a `.dvb` bundle line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BundleRecordEnvelope {
    pub client_id: Uuid,
    pub project_id: String,
    pub actor_user_id: i64,
    pub acting_role: ActingRole,
    pub recorded_at: String,
    pub payload: BundleRecordPayload,
}

impl BundleRecordEnvelope {
    pub fn record_type(&self) -> RecordType {
        self.payload.record_type()
    }

    /// Convert into the plaintext JSON value (before JCS canonicalization).
    pub fn to_plaintext_value(&self, bundle_created_at: &str) -> Result<Value, BundleError> {
        let mut payload_val = match &self.payload {
            BundleRecordPayload::DeathRegistration(r) => serde_json::to_value(r),
            BundleRecordPayload::Consent(r) => {
                let mut sorted = r.clone();
                sorted.purposes.sort_by(|a, b| a.code.cmp(&b.code));
                serde_json::to_value(sorted)
            }
            BundleRecordPayload::DeathCorrection(r) => serde_json::to_value(r),
            BundleRecordPayload::InterviewSubmission(r) => {
                let mut cloned = r.clone();
                if cloned.draft.device_clock_at.is_none() {
                    cloned.draft.device_clock_at = Some(bundle_created_at.to_string());
                }
                serde_json::to_value(cloned)
            }
            BundleRecordPayload::IdentifiersSet(r) => serde_json::to_value(r),
            BundleRecordPayload::CodingResult(r) => serde_json::to_value(r),
        }
        .map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;

        let map = payload_val.as_object_mut().ok_or_else(|| {
            BundleError::CanonicalJsonError("Record payload did not serialize to object.".to_string())
        })?;
        map.insert(
            "record_type".to_string(),
            Value::String(self.record_type().as_str().to_string()),
        );
        map.insert(
            "client_id".to_string(),
            Value::String(self.client_id.to_string()),
        );
        map.insert(
            "project_id".to_string(),
            Value::String(self.project_id.clone()),
        );
        map.insert(
            "actor_user_id".to_string(),
            Value::Number(self.actor_user_id.into()),
        );
        map.insert(
            "acting_role".to_string(),
            Value::String(self.acting_role.as_str().to_string()),
        );
        map.insert(
            "recorded_at".to_string(),
            Value::String(self.recorded_at.clone()),
        );
        Ok(payload_val)
    }
}

/// Line 1 manifest of a `.dvb` bundle (`offline-bundle-and-transfer.md` Section 2.2).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BundleManifest {
    pub app_version: String,
    pub body_sha256: String,
    pub bundle_format_version: u32,
    pub bundle_id: Uuid,
    pub bundle_seq: u64,
    pub crate_version: String,
    pub created_at: String,
    pub dek_wrapped: String,
    pub device_id: String,
    pub instrument_versions: Vec<String>,
    pub kem_key_id: String,
    pub project_ids: Vec<String>,
    pub record_counts: BTreeMap<String, usize>,
    pub signing_key_id: String,
    pub station_config_id: Uuid,
}

/// Line 3.. record envelope on the wire (`{"client_id":"...","ct":"v1:aes256gcm:...","record_type":"..."}`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BundleRecordLine {
    pub client_id: Uuid,
    pub ct: String,
    pub record_type: RecordType,
}

/// Summary item returned to the caller per sealed record (`(client_id, record_type, answers_sha256?)`).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BundleManifestRecordItem {
    pub client_id: Uuid,
    pub record_type: RecordType,
    pub answers_sha256: Option<String>,
}

/// Per-record sealed metadata (non-PII: `client_id`, `record_type`, `aad`, `ct`) for test vector assertions.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SealedRecordMetadata {
    pub client_id: Uuid,
    pub record_type: RecordType,
    pub aad: Vec<u8>,
    pub ct: String,
}

/// Output of [`build_bundle`] and [`build_bundle_deterministic`].
#[derive(Debug, Clone)]
pub struct BuiltBundle {
    pub bytes: Vec<u8>,
    pub manifest_line: String,
    pub signature_line: String,
    pub manifest: BundleManifest,
    pub signature: BundleSignatureLine,
    pub items: Vec<BundleManifestRecordItem>,
    pub record_metadata: Vec<SealedRecordMetadata>,
}

/// Deterministic randomness inputs for reproducible bundle test vectors (`offline-bundle-and-transfer.md` Section 7).
#[derive(Debug, Clone)]
pub struct DeterministicBundleRandomness {
    pub bundle_id: Uuid,
    pub dek: [u8; DEK_LEN],
    pub mlkem_m: [u8; 32],
    pub x25519_eph_scalar: [u8; 32],
    pub wrap_nonce: [u8; NONCE_LEN],
    /// Per-record 12-byte nonces in the sorted ingest order (or keyed by `client_id` via `record_nonces`).
    pub record_nonces: BTreeMap<Uuid, [u8; NONCE_LEN]>,
}

fn value_is_non_empty(val: &Value) -> bool {
    match val {
        Value::Null => false,
        Value::String(s) => !s.trim().is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
        Value::Bool(_) | Value::Number(_) => true,
    }
}

fn check_id10073_recursive(val: &Value) -> bool {
    match val {
        Value::Object(map) => {
            for (k, v) in map {
                if k == NATIONAL_ID_FIELD {
                    match v {
                        Value::Null => {}
                        Value::String(s) if s.trim().is_empty() => {}
                        Value::String(s) => {
                            if !is_reduced_national_id(s) {
                                return false;
                            }
                        }
                        _ => return false,
                    }
                } else if !check_id10073_recursive(v) {
                    return false;
                }
            }
            true
        }
        Value::Array(arr) => arr.iter().all(check_id10073_recursive),
        _ => true,
    }
}

fn validate_actor_on_roster(
    station_config: &StationConfigPayload,
    record: &BundleRecordEnvelope,
) -> Result<(), BundleError> {
    let allowed_role_for_type = match record.record_type() {
        RecordType::DeathRegistration | RecordType::Consent => matches!(
            record.acting_role,
            ActingRole::DeathReporter | ActingRole::Interviewer
        ),
        RecordType::DeathCorrection | RecordType::IdentifiersSet => {
            record.acting_role == ActingRole::StationSupervisor
        }
        RecordType::InterviewSubmission => record.acting_role == ActingRole::Interviewer,
        RecordType::CodingResult => record.acting_role == ActingRole::Coder,
        // Reserved: the writer never emits it, so refuse any envelope that claims it.
        RecordType::AttachmentChunk => false,
    };
    if !allowed_role_for_type {
        return Err(BundleError::InvalidActingRoleForRecord {
            client_id: record.client_id,
            record_type: record.record_type().as_str().to_string(),
            acting_role: record.acting_role.as_str().to_string(),
        });
    }

    let Some(member) = station_config
        .roster
        .iter()
        .find(|m| m.user_id == record.actor_user_id && m.active)
    else {
        return Err(BundleError::ActorNotAuthorizedOnRoster {
            client_id: record.client_id,
            actor_user_id: record.actor_user_id,
            acting_role: record.acting_role.as_str().to_string(),
        });
    };

    let (required_site, required_ou): (Option<&str>, Option<&str>) = match &record.payload {
        BundleRecordPayload::DeathRegistration(r) => {
            (Some(r.site_id.as_str()), r.org_unit_id.as_deref())
        }
        BundleRecordPayload::InterviewSubmission(r) => {
            (Some(r.site_id.as_str()), r.org_unit_id.as_deref())
        }
        _ => (None, None),
    };

    let has_matching_grant = member.roles.iter().any(|g| {
        if g.role != record.acting_role || g.project_id != record.project_id {
            return false;
        }
        if let Some(site) = required_site {
            if g.site_id != site {
                return false;
            }
        }
        if let (Some(grant_ou), Some(rec_ou)) = (g.org_unit_id.as_deref(), required_ou) {
            if grant_ou != rec_ou {
                return false;
            }
        } else if g.org_unit_id.is_some() && required_site.is_some() && required_ou.is_none() {
            return false;
        }
        true
    });

    if !has_matching_grant {
        return Err(BundleError::ActorNotAuthorizedOnRoster {
            client_id: record.client_id,
            actor_user_id: record.actor_user_id,
            acting_role: record.acting_role.as_str().to_string(),
        });
    }

    Ok(())
}

/// Validate one record as `build_bundle` does: `recorded_at`, the actor's roster grant and the
/// payload rules. `granted_registration_consents` holds the client ids of the granted
/// registration consents travelling in the same bundle. Returns the parsed `recorded_at`.
/// The station calls it per record to hold back an invalid one instead of failing the export.
pub fn validate_bundle_record(
    station_config: &StationConfigPayload,
    rec: &BundleRecordEnvelope,
    granted_registration_consents: &BTreeSet<Uuid>,
) -> Result<DateTime<Utc>, BundleError> {
    let recorded_dt = DateTime::parse_from_rfc3339(&rec.recorded_at)
        .map_err(|_| BundleError::RecordInvalid {
            client_id: rec.client_id,
            reason: "recorded_at must be a valid RFC 3339 timestamp with offset.".to_string(),
        })?
        .with_timezone(&Utc);

    validate_actor_on_roster(station_config, rec)?;

    match &rec.payload {
        BundleRecordPayload::DeathRegistration(reg) => {
            if reg.site_id.trim().is_empty() {
                return Err(BundleError::RecordInvalid {
                    client_id: rec.client_id,
                    reason: "site_id must not be empty.".to_string(),
                });
            }
            // Offline always needs consent for informant details (owner decision, contract 5.5),
            // whatever the project's `consent_required` says.
            let has_informant_data = INFORMANT_REGISTER_FIELDS.iter().any(|&field_name| {
                reg.fields
                    .get(field_name)
                    .map(value_is_non_empty)
                    .unwrap_or(false)
            });
            if has_informant_data {
                let Some(cid) = reg.consent_client_id else {
                    return Err(BundleError::ConsentRequired {
                        client_id: rec.client_id,
                    });
                };
                if !granted_registration_consents.contains(&cid) {
                    return Err(BundleError::ConsentRequired {
                        client_id: rec.client_id,
                    });
                }
            }
        }
        BundleRecordPayload::Consent(c) => {
            if c.notice_language.trim().is_empty()
                || c.notice_sha256.len() != 64
                || !c.notice_sha256.bytes().all(|b| b.is_ascii_hexdigit())
                || c.purposes.is_empty()
            {
                return Err(BundleError::RecordInvalid {
                    client_id: rec.client_id,
                    reason: "Consent notice_language, notice_sha256, or purposes invalid."
                        .to_string(),
                });
            }
        }
        BundleRecordPayload::DeathCorrection(corr) => {
            let reason_nfc: String = corr.reason.trim().nfc().collect();
            let char_len = reason_nfc.chars().count();
            if !(1..=500).contains(&char_len) {
                return Err(BundleError::InvalidCorrectionReason {
                    client_id: rec.client_id,
                });
            }
            if corr.changes.is_empty() || corr.changes.contains_key("identifiers") {
                return Err(BundleError::RecordInvalid {
                    client_id: rec.client_id,
                    reason: "death_correction changes must be non-empty and must not contain 'identifiers'.".to_string(),
                });
            }
        }
        BundleRecordPayload::IdentifiersSet(id_set) => {
            let reason_nfc: String = id_set.reason.trim().nfc().collect();
            let char_len = reason_nfc.chars().count();
            if !(1..=500).contains(&char_len) {
                return Err(BundleError::InvalidCorrectionReason {
                    client_id: rec.client_id,
                });
            }
            if !(1..=50).contains(&id_set.identifiers.len()) {
                return Err(BundleError::RecordInvalid {
                    client_id: rec.client_id,
                    reason: "identifiers_set must contain between 1 and 50 identifier codes."
                        .to_string(),
                });
            }
            for val in id_set.identifiers.values().flatten() {
                if val.chars().count() > 256 {
                    return Err(BundleError::RecordInvalid {
                        client_id: rec.client_id,
                        reason: "identifier value exceeds 256 characters.".to_string(),
                    });
                }
            }
        }
        BundleRecordPayload::InterviewSubmission(sub) => {
            if sub.answers_json.len() > ANSWERS_JSON_MAX_BYTES {
                return Err(BundleError::SizeLimitExceeded(format!(
                    "Interview submission {} answers_json exceeds 1 MiB.",
                    rec.client_id
                )));
            }
            let actual_hash = sha256_hex(sub.answers_json.as_bytes());
            if !sub.answers_sha256.eq_ignore_ascii_case(&actual_hash) {
                return Err(BundleError::AnswersHashMismatch {
                    client_id: rec.client_id,
                });
            }
            let parsed_answers: Value =
                serde_json::from_str(&sub.answers_json).map_err(|_| {
                    BundleError::RecordInvalid {
                        client_id: rec.client_id,
                        reason: "answers_json is not valid JSON.".to_string(),
                    }
                })?;
            if !parsed_answers.is_object() {
                return Err(BundleError::RecordInvalid {
                    client_id: rec.client_id,
                    reason: "answers_json must be a JSON object.".to_string(),
                });
            }
            if !check_id10073_recursive(&parsed_answers) {
                return Err(BundleError::UnreducedNationalId {
                    client_id: rec.client_id,
                });
            }
        }
        BundleRecordPayload::CodingResult(coding) => {
            if coding.coded_answers_sha256.len() != 64
                || !coding
                    .coded_answers_sha256
                    .bytes()
                    .all(|b| b.is_ascii_hexdigit())
            {
                return Err(BundleError::RecordInvalid {
                    client_id: rec.client_id,
                    reason: "coded_answers_sha256 must be 64 hex characters.".to_string(),
                });
            }
        }
    }
    Ok(recorded_dt)
}

/// Build and sign a `.dvb` bundle using fresh OS CSPRNG keys and nonces.
pub fn build_bundle(
    station_config: &VerifiedStationConfig,
    signing_key: &StationSigningKey,
    device_id: &str,
    bundle_seq: u64,
    app_version: &str,
    now_utc: DateTime<Utc>,
    records: &[BundleRecordEnvelope],
) -> Result<BuiltBundle, BundleError> {
    let bundle_id = Uuid::new_v4();
    let mut dek = [0u8; DEK_LEN];
    let mut mlkem_m = [0u8; 32];
    let mut x25519_eph_scalar = [0u8; 32];
    let mut wrap_nonce = [0u8; NONCE_LEN];
    OsRng.fill_bytes(&mut dek);
    OsRng.fill_bytes(&mut mlkem_m);
    OsRng.fill_bytes(&mut x25519_eph_scalar);
    OsRng.fill_bytes(&mut wrap_nonce);

    let mut record_nonces = BTreeMap::new();
    for rec in records {
        let mut n = [0u8; NONCE_LEN];
        OsRng.fill_bytes(&mut n);
        record_nonces.insert(rec.client_id, n);
    }

    let det = DeterministicBundleRandomness {
        bundle_id,
        dek,
        mlkem_m,
        x25519_eph_scalar,
        wrap_nonce,
        record_nonces,
    };

    build_bundle_inner(
        station_config,
        signing_key,
        device_id,
        bundle_seq,
        app_version,
        now_utc,
        records,
        &det,
        false,
    )
}

/// Build and sign a `.dvb` bundle deterministically with caller-provided DEK, KEM randomness, and nonces.
pub fn build_bundle_deterministic(
    station_config: &VerifiedStationConfig,
    signing_key: &StationSigningKey,
    device_id: &str,
    bundle_seq: u64,
    app_version: &str,
    now_utc: DateTime<Utc>,
    records: &[BundleRecordEnvelope],
    randomness: &DeterministicBundleRandomness,
) -> Result<BuiltBundle, BundleError> {
    build_bundle_inner(
        station_config,
        signing_key,
        device_id,
        bundle_seq,
        app_version,
        now_utc,
        records,
        randomness,
        true,
    )
}

#[allow(clippy::too_many_arguments)]
fn build_bundle_inner(
    station_config: &VerifiedStationConfig,
    signing_key: &StationSigningKey,
    device_id: &str,
    bundle_seq: u64,
    app_version: &str,
    now_utc: DateTime<Utc>,
    records: &[BundleRecordEnvelope],
    randomness: &DeterministicBundleRandomness,
    use_deterministic_wrap: bool,
) -> Result<BuiltBundle, BundleError> {
    // 1. Validate station config onboarding, device match, and expiry
    let Some(ref custodian) = station_config.config.custodian else {
        return Err(BundleError::StationNotOnboarded);
    };
    if !custodian.is_valid() {
        return Err(BundleError::StationNotOnboarded);
    }
    if station_config.config.device_id != device_id {
        return Err(BundleError::StationConfigDeviceMismatch {
            expected: station_config.config.device_id.clone(),
            actual: device_id.to_string(),
        });
    }
    if station_config.is_expired(now_utc) {
        return Err(BundleError::StationConfigExpired {
            expires_at: station_config.config.expires_at.clone(),
        });
    }
    if bundle_seq == 0 {
        return Err(BundleError::InvalidBundleSeq);
    }
    if records.is_empty() || records.len() > BUNDLE_MAX_RECORDS {
        return Err(BundleError::RecordCountOutOfRange(records.len()));
    }

    // 2. Collect granted consent client_ids in this bundle and check for duplicate client_ids
    let mut seen_ids = BTreeSet::new();
    let mut granted_registration_consents = BTreeSet::new();
    let mut correction_count = 0usize;

    for rec in records {
        if !seen_ids.insert(rec.client_id) {
            return Err(BundleError::DuplicateClientId(rec.client_id));
        }
        if let BundleRecordPayload::Consent(c) = &rec.payload {
            if c.decision == ConsentDecision::Granted && c.client_draft_id.is_none() {
                granted_registration_consents.insert(rec.client_id);
            }
        }
        if matches!(
            rec.record_type(),
            RecordType::DeathCorrection | RecordType::IdentifiersSet
        ) {
            correction_count += 1;
        }
    }

    if correction_count > BUNDLE_MAX_CORRECTIONS {
        return Err(BundleError::TooManyCorrections(correction_count));
    }

    // 3. Parse timestamps, validate every record, and sort into canonical ingest order
    let mut indexed_records: Vec<(DateTime<Utc>, usize, &BundleRecordEnvelope)> =
        Vec::with_capacity(records.len());

    for (idx, rec) in records.iter().enumerate() {
        let recorded_dt =
            validate_bundle_record(&station_config.config, rec, &granted_registration_consents)?;
        indexed_records.push((recorded_dt, idx, rec));
    }

    // Sort by (record_type, recorded_at_utc, original_index)
    indexed_records.sort_by(|a, b| {
        a.2.record_type()
            .cmp(&b.2.record_type())
            .then_with(|| a.0.cmp(&b.0))
            .then_with(|| a.1.cmp(&b.1))
    });

    let created_at_str = now_utc.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let bundle_id = randomness.bundle_id;
    let bundle_id_bytes = bundle_id.as_bytes();

    let mut body_bytes = Vec::new();
    let mut project_ids_set = BTreeSet::new();
    let mut instrument_versions_set = BTreeSet::new();
    let mut record_counts: BTreeMap<String, usize> = BTreeMap::new();
    let mut items = Vec::with_capacity(indexed_records.len());
    let mut record_metadata = Vec::with_capacity(indexed_records.len());

    for (_, _, rec) in indexed_records {
        project_ids_set.insert(rec.project_id.nfc().collect::<String>());
        let rtype = rec.record_type();
        *record_counts
            .entry(rtype.as_str().to_string())
            .or_insert(0) += 1;

        let answers_sha256 = if let BundleRecordPayload::InterviewSubmission(sub) = &rec.payload {
            instrument_versions_set.insert(
                sub.draft
                    .instrument_version
                    .nfc()
                    .collect::<String>(),
            );
            Some(sub.answers_sha256.to_ascii_lowercase())
        } else {
            None
        };

        let pt_val = rec.to_plaintext_value(&created_at_str)?;
        let pt_jcs = to_jcs_string(&pt_val).map_err(BundleError::CanonicalJsonError)?;

        if matches!(
            rtype,
            RecordType::DeathCorrection | RecordType::IdentifiersSet
        ) && pt_jcs.len() > CORRECTION_MAX_LINE_BYTES
        {
            return Err(BundleError::SizeLimitExceeded(format!(
                "Correction record {} exceeds 16 KiB limit.",
                rec.client_id
            )));
        }

        let field_id = format!("{}/{}", rtype.as_str(), rec.client_id);
        let aad = record_aad(BUNDLE_AAD_TABLE, &field_id, bundle_id_bytes)?;
        let nonce = randomness
            .record_nonces
            .get(&rec.client_id)
            .ok_or_else(|| BundleError::RecordInvalid {
                client_id: rec.client_id,
                reason: "Missing record nonce.".to_string(),
            })?;

        let ct = seal_bytes_with_dek(&randomness.dek, nonce, &pt_jcs, &aad);

        let line_obj = BundleRecordLine {
            client_id: rec.client_id,
            ct: ct.clone(),
            record_type: rtype,
        };
        let line_val = serde_json::to_value(&line_obj)
            .map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;
        let mut line_str = to_jcs_string(&line_val).map_err(BundleError::CanonicalJsonError)?;
        line_str.push('\n');

        if line_str.len() > BUNDLE_MAX_LINE_BYTES {
            return Err(BundleError::SizeLimitExceeded(format!(
                "Record line for {} exceeds BUNDLE_MAX_LINE_BYTES.",
                rec.client_id
            )));
        }

        body_bytes.extend_from_slice(line_str.as_bytes());
        items.push(BundleManifestRecordItem {
            client_id: rec.client_id,
            record_type: rtype,
            answers_sha256,
        });
        record_metadata.push(SealedRecordMetadata {
            client_id: rec.client_id,
            record_type: rtype,
            aad,
            ct,
        });
    }

    let body_sha256 = sha256_hex(&body_bytes);

    let dek_wrapped = if use_deterministic_wrap {
        wrap_dek_deterministic(
            &randomness.dek,
            &station_config.kem_public_key,
            &randomness.mlkem_m,
            &randomness.x25519_eph_scalar,
            &randomness.wrap_nonce,
        )?
    } else {
        wrap_dek(&randomness.dek, &station_config.kem_public_key)
    };

    let manifest = BundleManifest {
        app_version: app_version.to_string(),
        body_sha256,
        bundle_format_version: BUNDLE_FORMAT_VERSION,
        bundle_id,
        bundle_seq,
        crate_version: env!("CARGO_PKG_VERSION").to_string(),
        created_at: created_at_str,
        dek_wrapped,
        device_id: device_id.to_string(),
        instrument_versions: instrument_versions_set.into_iter().collect(),
        kem_key_id: station_config.kem_public_key.key_id.clone(),
        project_ids: project_ids_set.into_iter().collect(),
        record_counts,
        signing_key_id: signing_key.signing_key_id(),
        station_config_id: station_config.config.config_id,
    };

    let manifest_val = serde_json::to_value(&manifest)
        .map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;
    let manifest_line = to_jcs_string(&manifest_val).map_err(BundleError::CanonicalJsonError)?;
    if manifest_line.len() + 1 > BUNDLE_MAX_MANIFEST_BYTES {
        return Err(BundleError::SizeLimitExceeded(
            "Manifest line exceeds BUNDLE_MAX_MANIFEST_BYTES.".to_string(),
        ));
    }

    let signature = signing_key.sign_manifest_line(manifest_line.as_bytes());
    let sig_val = serde_json::to_value(&signature)
        .map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;
    let signature_line = to_jcs_string(&sig_val).map_err(BundleError::CanonicalJsonError)?;

    let total_len = manifest_line.len() + 1 + signature_line.len() + 1 + body_bytes.len();
    if total_len > BUNDLE_MAX_BYTES {
        return Err(BundleError::SizeLimitExceeded(
            "Total bundle size exceeds BUNDLE_MAX_BYTES (50 MiB).".to_string(),
        ));
    }

    let mut bytes = Vec::with_capacity(total_len);
    bytes.extend_from_slice(manifest_line.as_bytes());
    bytes.push(b'\n');
    bytes.extend_from_slice(signature_line.as_bytes());
    bytes.push(b'\n');
    bytes.extend_from_slice(&body_bytes);

    Ok(BuiltBundle {
        bytes,
        manifest_line,
        signature_line,
        manifest,
        signature,
        items,
        record_metadata,
    })
}

/// Write bundle bytes atomically to `target_path` (temp file in same directory -> fsync -> rename).
/// Never leaves a partial file at `target_path`.
pub fn write_bundle_atomic(target_path: impl AsRef<Path>, bytes: &[u8]) -> Result<(), BundleError> {
    let target = target_path.as_ref();
    let parent = target
        .parent()
        .ok_or_else(|| BundleError::IoError("Target path has no parent directory.".to_string()))?;
    std::fs::create_dir_all(parent).map_err(|e| BundleError::IoError(e.to_string()))?;

    let tmp_name = format!(".digitva-bundle-tmp-{}.dvb", Uuid::new_v4());
    let tmp_path = parent.join(tmp_name);

    let write_res = (|| -> std::io::Result<()> {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&tmp_path)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(&tmp_path, target)?;
        Ok(())
    })();

    if let Err(e) = write_res {
        let _ = std::fs::remove_file(&tmp_path);
        return Err(BundleError::IoError(e.to_string()));
    }
    Ok(())
}

// ============================================================================
// Receipt Verification and Planning (`offline-bundle-and-transfer.md` 5.6, 7)
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RecordIngestOutcome {
    Accepted,
    Duplicate,
    Superseded,
    Pending,
    Rejected,
    NotProcessed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReceiptRecordOutcome {
    pub client_id: Uuid,
    pub record_type: RecordType,
    pub outcome: RecordIngestOutcome,
    #[serde(default)]
    pub code: Option<String>,
    #[serde(default)]
    pub received_sha256: Option<String>,
    #[serde(default)]
    pub death_id: Option<Uuid>,
    #[serde(default)]
    pub unique_id: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct BundleReceiptReport {
    pub bundle_id: Uuid,
    pub device_id: String,
    pub kem_key_id: String,
    pub status: String,
    pub counts: BTreeMap<String, usize>,
    #[serde(default)]
    pub missing_seq: Vec<u64>,
    pub records: Vec<ReceiptRecordOutcome>,
    #[serde(default)]
    pub purge: Vec<Uuid>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReceiptPlan {
    pub report: BundleReceiptReport,
    /// Records confirmed `accepted`, `duplicate`, or `superseded` (with matching `received_sha256` for interviews)
    /// that the station may safely delete from its local outbox.
    pub deletable_client_ids: Vec<Uuid>,
    /// Interview `client_id`s whose receipt outcome was `accepted`/`duplicate`/`superseded`
    /// but whose `received_sha256` did NOT match the station's local `answers_sha256` (must NOT be deleted).
    pub hash_mismatched_interviews: Vec<Uuid>,
    /// Records held as `pending` on the server (`(client_id, code)`, e.g. `doris_pending`); kept
    /// locally until a later receipt gives the final outcome.
    pub pending_records: Vec<(Uuid, Option<String>)>,
    /// Records rejected by the server (`(client_id, error_code)`).
    pub rejected_records: Vec<(Uuid, Option<String>)>,
    /// Sorted, unique `client_id`s from `purge` that the station must purge immediately.
    pub purge_client_ids: Vec<Uuid>,
}

/// Verify a two-line signed receipt (`b"digitva-receipt-v1\x00" || line1`) and compute the station's
/// deletion and purge plan (`offline-bundle-and-transfer.md` Section 5.6 & Section 7).
pub fn verify_and_plan_receipt(
    raw_two_line_receipt: &str,
    expected_device_id: &str,
    server_verifying_key: &[u8; 32],
    local_interview_hashes: &BTreeMap<Uuid, String>,
) -> Result<ReceiptPlan, BundleError> {
    let (line1, line2) =
        split_two_line_signed_blob(raw_two_line_receipt).map_err(BundleError::ReceiptInvalid)?;

    verify_ed25519_signature_line(
        server_verifying_key,
        RECEIPT_SIG_DOMAIN,
        line1.as_bytes(),
        line2,
    )
    .map_err(|_| BundleError::ReceiptInvalid("Receipt Ed25519 signature is invalid.".to_string()))?;

    let report: BundleReceiptReport = serde_json::from_str(line1)
        .map_err(|e| BundleError::ReceiptInvalid(format!("Invalid receipt JSON: {e}")))?;

    if report.device_id != expected_device_id {
        return Err(BundleError::ReceiptInvalid(format!(
            "Receipt device_id mismatch (expected {expected_device_id}, got {}).",
            report.device_id
        )));
    }

    let mut deletable_client_ids = Vec::new();
    let mut hash_mismatched_interviews = Vec::new();
    let mut pending_records = Vec::new();
    let mut rejected_records = Vec::new();

    for rec in &report.records {
        match rec.outcome {
            RecordIngestOutcome::Accepted
            | RecordIngestOutcome::Duplicate
            | RecordIngestOutcome::Superseded => {
                if rec.record_type == RecordType::InterviewSubmission {
                    let matches_hash = match (
                        local_interview_hashes.get(&rec.client_id),
                        rec.received_sha256.as_deref(),
                    ) {
                        (Some(expected_hash), Some(received_hash)) => {
                            expected_hash.eq_ignore_ascii_case(received_hash)
                        }
                        _ => false,
                    };
                    if matches_hash {
                        deletable_client_ids.push(rec.client_id);
                    } else {
                        hash_mismatched_interviews.push(rec.client_id);
                    }
                } else {
                    deletable_client_ids.push(rec.client_id);
                }
            }
            RecordIngestOutcome::Pending => {
                pending_records.push((rec.client_id, rec.code.clone()));
            }
            RecordIngestOutcome::Rejected => {
                rejected_records.push((rec.client_id, rec.code.clone()));
            }
            RecordIngestOutcome::NotProcessed => {}
        }
    }

    let purge_set: BTreeSet<Uuid> = report.purge.iter().copied().collect();
    let purge_client_ids: Vec<Uuid> = purge_set.into_iter().collect();

    Ok(ReceiptPlan {
        report,
        deletable_client_ids,
        hash_mismatched_interviews,
        pending_records,
        rejected_records,
        purge_client_ids,
    })
}

/// Format and sign a two-line receipt (`b"digitva-receipt-v1\x00" || line1`).
pub fn format_signed_receipt(
    report: &BundleReceiptReport,
    server_signing_key: &StationSigningKey,
) -> Result<String, BundleError> {
    let val = serde_json::to_value(report)
        .map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;
    let line1 = to_jcs_string(&val).map_err(BundleError::CanonicalJsonError)?;
    let sig = server_signing_key.sign_with_domain(RECEIPT_SIG_DOMAIN, line1.as_bytes());
    let sig_val =
        serde_json::to_value(&sig).map_err(|e| BundleError::CanonicalJsonError(e.to_string()))?;
    let line2 = to_jcs_string(&sig_val).map_err(BundleError::CanonicalJsonError)?;
    Ok(format!("{line1}\n{line2}\n"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use digitva_pii::{open_bytes_with_dek, unwrap_dek, KemPrivateKey};
    use serde_json::json;
    use std::path::PathBuf;

    fn load_test_kem_keys() -> (KemPublicKey, BTreeMap<String, KemPrivateKey>) {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/pii_envelope_vectors.json");
        let data: Value =
            serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        let kem_keys = data["deterministic"]["test_keys"]["kem_keys"]
            .as_array()
            .unwrap();
        let mut privates = BTreeMap::new();
        let mut tv1_pub = None;
        for entry in kem_keys {
            let kid = entry["key_id"].as_str().unwrap();
            let priv_k =
                KemPrivateKey::parse_file_text(entry["private_key_file_text"].as_str().unwrap())
                    .unwrap();
            let pub_k =
                KemPublicKey::parse(entry["public_key_config"].as_str().unwrap(), kid).unwrap();
            if kid == "tv1" {
                tv1_pub = Some(pub_k);
            }
            privates.insert(kid.to_string(), priv_k);
        }
        (tv1_pub.unwrap(), privates)
    }

    fn sample_keys_and_station_config() -> (
        StationSigningKey,
        StationSigningKey,
        VerifiedStationConfig,
        BTreeMap<String, KemPrivateKey>,
    ) {
        let (tv1_pub, privates) = load_test_kem_keys();
        let server_signing_key = StationSigningKey::from_secret_bytes(&[0x41u8; 32]);
        let station_signing_key = StationSigningKey::from_secret_bytes(&[0x52u8; 32]);

        let payload = StationConfigPayload {
            station_config_format_version: 1,
            config_id: Uuid::parse_str("a1000000-0000-4000-8000-000000000001").unwrap(),
            issued_at: "2026-10-20T00:00:00Z".to_string(),
            expires_at: "2027-04-18T00:00:00Z".to_string(),
            device_id: "station-phc-01".to_string(),
            server_url: "https://digitva.example.org".to_string(),
            kem_public_key: StationKemPublicKeyConfig {
                key_id: tv1_pub.key_id.clone(),
                public: tv1_pub.to_config(),
            },
            server_signing_key: ServerSigningKeyConfig {
                signing_key_id: server_signing_key.signing_key_id(),
                public: server_signing_key.public_key_base64url(),
            },
            projects: vec![StationProjectConfig {
                project_id: "P1".to_string(),
                project_name: None,
                sites: vec!["PHC01".to_string()],
                org_units: vec!["ou-sc-1".to_string()],
                site_names: BTreeMap::new(),
                org_unit_paths: BTreeMap::new(),
                org_unit_sites: BTreeMap::new(),
                sealed_field_ids: digitva_text::PII_FIELDS_FLOOR
                    .iter()
                    .map(|s| (*s).to_string())
                    .collect(),
                instrument_versions: vec!["2022_v1".to_string()],
                consent: Some(serde_json::json!({ "consent_required": true })),
                form_options: None,
                translations: BTreeMap::new(),
                coding_mode: None,
            }],
            custodian: Some(StationCustodian {
                name: "Dr. Meera Nair".to_string(),
                designation: "medical_officer".to_string(),
                phone: Some("9876543210".to_string()),
                email: None,
                onboarded_on: "2026-10-20".to_string(),
                verified_by_user_id: 1,
            }),
            designations: vec![DesignationSpec {
                code: "medical_officer".to_string(),
                label: "Medical Officer".to_string(),
            }],
            roster: vec![
                RosterMember {
                    user_id: 101,
                    name: "Reporter One".to_string(),
                    designation: "health_worker".to_string(),
                    roles: vec![RosterRoleGrant {
                        role: ActingRole::DeathReporter,
                        project_id: "P1".to_string(),
                        site_id: "PHC01".to_string(),
                        org_unit_id: None,
                    }],
                    active: true,
                },
                RosterMember {
                    user_id: 102,
                    name: "Interviewer One".to_string(),
                    designation: "health_worker".to_string(),
                    roles: vec![RosterRoleGrant {
                        role: ActingRole::Interviewer,
                        project_id: "P1".to_string(),
                        site_id: "PHC01".to_string(),
                        org_unit_id: Some("ou-sc-1".to_string()),
                    }],
                    active: true,
                },
                RosterMember {
                    user_id: 103,
                    name: "Supervisor One".to_string(),
                    designation: "medical_officer".to_string(),
                    roles: vec![RosterRoleGrant {
                        role: ActingRole::StationSupervisor,
                        project_id: "P1".to_string(),
                        site_id: "PHC01".to_string(),
                        org_unit_id: None,
                    }],
                    active: true,
                },
                RosterMember {
                    user_id: 104,
                    name: "Coder One".to_string(),
                    designation: "medical_officer".to_string(),
                    roles: vec![RosterRoleGrant {
                        role: ActingRole::Coder,
                        project_id: "P1".to_string(),
                        site_id: "PHC01".to_string(),
                        org_unit_id: None,
                    }],
                    active: true,
                },
            ],
            purge: vec![Uuid::parse_str("f0000000-0000-4000-8000-000000000099").unwrap()],
        };

        let signed_text = format_signed_station_config(&payload, &server_signing_key).unwrap();
        let verified = VerifiedStationConfig::parse_and_verify(
            &signed_text,
            "station-phc-01",
            Some(&server_signing_key.public_key_bytes()),
        )
        .unwrap();

        (server_signing_key, station_signing_key, verified, privates)
    }

    #[test]
    fn test_station_config_verification_and_expiry_warnings() {
        let (server_key, _station_key, verified, _privates) = sample_keys_and_station_config();

        let now = DateTime::parse_from_rfc3339("2026-10-21T10:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert!(!verified.is_expired(now));
        assert!(verified.days_until_expiry(now) > 150);
        assert!(!verified.needs_expiry_warning(now));

        // 25 days before expiry triggers warning
        let near_expiry = DateTime::parse_from_rfc3339("2027-03-25T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert!(!verified.is_expired(near_expiry));
        assert!(verified.needs_expiry_warning(near_expiry));

        // Wrong device_id is refused
        let signed_text = format_signed_station_config(&verified.config, &server_key).unwrap();
        assert_eq!(
            VerifiedStationConfig::parse_and_verify(&signed_text, "other-device", None)
                .unwrap_err(),
            BundleError::StationConfigDeviceMismatch {
                expected: "other-device".to_string(),
                actual: "station-phc-01".to_string()
            }
        );

        // Wrong pinned key is refused
        let wrong_server_key = StationSigningKey::from_secret_bytes(&[0x99u8; 32]);
        assert_eq!(
            VerifiedStationConfig::parse_and_verify(
                &signed_text,
                "station-phc-01",
                Some(&wrong_server_key.public_key_bytes()),
            )
            .unwrap_err(),
            BundleError::StationConfigSignatureInvalid
        );

        // Missing custodian is refused
        let mut no_custodian_cfg = verified.config.clone();
        no_custodian_cfg.custodian = None;
        let signed_no_cust =
            format_signed_station_config(&no_custodian_cfg, &server_key).unwrap();
        assert_eq!(
            VerifiedStationConfig::parse_and_verify(&signed_no_cust, "station-phc-01", None)
                .unwrap_err(),
            BundleError::StationNotOnboarded
        );
    }

    #[test]
    fn test_deterministic_bundle_all_record_types_ordering_and_opening() {
        let (_server_key, station_key, verified, privates) = sample_keys_and_station_config();

        let death_id = Uuid::parse_str("10000000-0000-4000-8000-000000000001").unwrap();
        let consent_id = Uuid::parse_str("20000000-0000-4000-8000-000000000002").unwrap();
        let corr_id = Uuid::parse_str("30000000-0000-4000-8000-000000000003").unwrap();
        let draft_id = Uuid::parse_str("40000000-0000-4000-8000-000000000004").unwrap();
        let idset_id = Uuid::parse_str("50000000-0000-4000-8000-000000000005").unwrap();
        let coding_id = Uuid::parse_str("60000000-0000-4000-8000-000000000006").unwrap();

        // Include decomposed Unicode 'e\u{0301}' inside `answers_json` to verify it is NOT NFC-normalised!
        let raw_answers_json =
            "{\"Id10019\":\"female\",\"Id10073\":\"XXXXXXXXX123\",\"note\":\"e\u{0301}\"}";
        let answers_sha256 = sha256_hex(raw_answers_json.as_bytes());

        let mut reg_fields = BTreeMap::new();
        reg_fields.insert(
            "deceased_name".to_string(),
            Value::String("e\u{0301}clair".to_string()),
        );
        reg_fields.insert(
            "informant_name".to_string(),
            Value::String("Ramesh".to_string()),
        );

        let mut corr_changes = BTreeMap::new();
        corr_changes.insert(
            "place_of_death".to_string(),
            Value::String("Hospital".to_string()),
        );

        let mut idset_map = BTreeMap::new();
        idset_map.insert(
            "crs_reg_no".to_string(),
            Some("CRS/2026/001".to_string()),
        );

        // Deliberately pass records in reverse/shuffled order to verify canonical ordering!
        let records = vec![
            BundleRecordEnvelope {
                client_id: coding_id,
                project_id: "P1".to_string(),
                actor_user_id: 104,
                acting_role: ActingRole::Coder,
                recorded_at: "2026-10-21T10:06:00Z".to_string(),
                payload: BundleRecordPayload::CodingResult(CodingResultRecord {
                    client_draft_id: draft_id,
                    coded_answers_sha256: answers_sha256.clone(),
                    kind: CodingResultKind::Final,
                    initial: Some(json!({"immediate_cod": "BA40"})),
                    final_cod: Some(json!({"conclusive_cod": "BA40"})),
                    not_codeable: None,
                    coding_mode: Some("icd10".to_string()),
                }),
            },
            BundleRecordEnvelope {
                client_id: idset_id,
                project_id: "P1".to_string(),
                actor_user_id: 103,
                acting_role: ActingRole::StationSupervisor,
                recorded_at: "2026-10-21T10:05:00Z".to_string(),
                payload: BundleRecordPayload::IdentifiersSet(IdentifiersSetRecord {
                    death_ref: DeathRef::client_death(death_id),
                    reason: "Added CRS certificate number".to_string(),
                    if_updated_at: None,
                    base_client_id: Some(corr_id),
                    identifiers: idset_map,
                }),
            },
            BundleRecordEnvelope {
                client_id: draft_id,
                project_id: "P1".to_string(),
                actor_user_id: 102,
                acting_role: ActingRole::Interviewer,
                recorded_at: "2026-10-21T10:04:00Z".to_string(),
                payload: BundleRecordPayload::InterviewSubmission(InterviewSubmissionRecord {
                    site_id: "PHC01".to_string(),
                    org_unit_id: Some("ou-sc-1".to_string()),
                    death_ref: DeathRef::client_death(death_id),
                    draft: InterviewDraftMeta {
                        instrument_version: "2022_v1".to_string(),
                        definition_sha256: Some("a".repeat(64)),
                        definition_extensions: None,
                        started_at: "2026-10-21T10:00:00Z".to_string(),
                        completed_at: Some("2026-10-21T10:04:00Z".to_string()),
                        device_clock_at: None,
                        interview_outcome: "completed".to_string(),
                    },
                    completion: InterviewCompletion {
                        valid: true,
                        issues: vec![],
                    },
                    answers_json: raw_answers_json.to_string(),
                    answers_sha256: answers_sha256.clone(),
                    consent_client_id: Some(consent_id),
                }),
            },
            BundleRecordEnvelope {
                client_id: corr_id,
                project_id: "P1".to_string(),
                actor_user_id: 103,
                acting_role: ActingRole::StationSupervisor,
                recorded_at: "2026-10-21T10:03:00Z".to_string(),
                payload: BundleRecordPayload::DeathCorrection(DeathCorrectionRecord {
                    death_ref: DeathRef::client_death(death_id),
                    reason: "Corrected place of death".to_string(),
                    if_updated_at: None,
                    base_client_id: Some(death_id),
                    changes: corr_changes,
                }),
            },
            BundleRecordEnvelope {
                client_id: consent_id,
                project_id: "P1".to_string(),
                actor_user_id: 101,
                acting_role: ActingRole::DeathReporter,
                recorded_at: "2026-10-21T10:02:00Z".to_string(),
                payload: BundleRecordPayload::Consent(ConsentRecord {
                    death_ref: DeathRef::client_death(death_id),
                    client_draft_id: None,
                    notice_version_id: Uuid::parse_str("b0000000-0000-4000-8000-000000000001")
                        .unwrap(),
                    notice_language: "hi".to_string(),
                    notice_sha256: "b".repeat(64),
                    decision: ConsentDecision::Granted,
                    purposes: vec![ConsentPurposeGrant {
                        code: "record_interview".to_string(),
                        granted: true,
                    }],
                    mode: ConsentMode::Spoken,
                    witness_present: false,
                    supersedes_client_id: None,
                }),
            },
            BundleRecordEnvelope {
                client_id: death_id,
                project_id: "P1".to_string(),
                actor_user_id: 101,
                acting_role: ActingRole::DeathReporter,
                recorded_at: "2026-10-21T10:01:00Z".to_string(),
                payload: BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
                    site_id: "PHC01".to_string(),
                    org_unit_id: None,
                    fields: reg_fields,
                    identifiers: None,
                    consent_client_id: Some(consent_id),
                }),
            },
        ];

        let mut record_nonces = BTreeMap::new();
        for (i, id) in [death_id, consent_id, corr_id, draft_id, idset_id, coding_id]
            .iter()
            .enumerate()
        {
            record_nonces.insert(*id, [(i as u8) + 1; 12]);
        }

        let randomness = DeterministicBundleRandomness {
            bundle_id: Uuid::parse_str("99999999-0000-4000-8000-000000000001").unwrap(),
            dek: [0x33u8; 32],
            mlkem_m: [0x44u8; 32],
            x25519_eph_scalar: [0x55u8; 32],
            wrap_nonce: [0x66u8; 12],
            record_nonces,
        };

        let now_utc = DateTime::parse_from_rfc3339("2026-10-21T11:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        let built1 = build_bundle_deterministic(
            &verified,
            &station_key,
            "station-phc-01",
            1,
            "0.1.0",
            now_utc,
            &records,
            &randomness,
        )
        .unwrap();

        let built2 = build_bundle_deterministic(
            &verified,
            &station_key,
            "station-phc-01",
            1,
            "0.1.0",
            now_utc,
            &records,
            &randomness,
        )
        .unwrap();

        // Byte-for-byte deterministic reproduction
        assert_eq!(built1.bytes, built2.bytes);

        // Verify record ordering: death_registration, consent, death_correction, interview_submission, identifiers_set, coding_result
        let ordered_types: Vec<RecordType> = built1.items.iter().map(|i| i.record_type).collect();
        assert_eq!(
            ordered_types,
            vec![
                RecordType::DeathRegistration,
                RecordType::Consent,
                RecordType::DeathCorrection,
                RecordType::InterviewSubmission,
                RecordType::IdentifiersSet,
                RecordType::CodingResult,
            ]
        );

        // Verify signature line over `b"digitva-bundle-v1\x00" || manifest_line`
        let bundle_text = std::str::from_utf8(&built1.bytes).unwrap();
        let lines: Vec<&str> = bundle_text.strip_suffix('\n').unwrap().split('\n').collect();
        assert_eq!(lines.len(), 2 + 6);
        verify_ed25519_signature_line(
            &station_key.public_key_bytes(),
            BUNDLE_SIG_DOMAIN,
            lines[0].as_bytes(),
            lines[1],
        )
        .unwrap();

        // Verify body_sha256 over exact bytes from line 3 to EOF (including final \n)
        let body_start = lines[0].len() + 1 + lines[1].len() + 1;
        assert_eq!(
            built1.manifest.body_sha256,
            sha256_hex(&built1.bytes[body_start..])
        );

        // Unwrap bundle DEK using server tv1 private key and decrypt every record line
        let unwrapped_dek =
            unwrap_dek(&built1.manifest.dek_wrapped, &privates, "bundle-test").unwrap();
        assert_eq!(unwrapped_dek, randomness.dek);

        for (idx, line_str) in lines[2..].iter().enumerate() {
            let rec_line: BundleRecordLine = serde_json::from_str(line_str).unwrap();
            let field_id = format!("{}/{}", rec_line.record_type.as_str(), rec_line.client_id);
            let aad = record_aad(
                BUNDLE_AAD_TABLE,
                &field_id,
                built1.manifest.bundle_id.as_bytes(),
            )
            .unwrap();
            assert_eq!(aad, built1.record_metadata[idx].aad);
            let pt = open_bytes_with_dek(&rec_line.ct, &unwrapped_dek, &aad, "rec", "tv1").unwrap();
            let pt_json: Value = serde_json::from_str(&pt).unwrap();
            assert_eq!(pt_json["client_id"], rec_line.client_id.to_string());
            assert_eq!(pt_json["record_type"], rec_line.record_type.as_str());

            if rec_line.record_type == RecordType::DeathRegistration {
                // Outside answers_json, strings are NFC-normalised ("e\u{0301}clair" -> "\u{00e9}clair")
                assert_eq!(pt_json["deceased_name"], "\u{00e9}clair");
            }
            if rec_line.record_type == RecordType::CodingResult {
                assert_eq!(pt_json["coding_mode"], "icd10");
            }
            if rec_line.record_type == RecordType::InterviewSubmission {
                // Inside answers_json, exact bytes are preserved without NFC normalisation!
                let got_answers = pt_json["answers_json"].as_str().unwrap();
                assert_eq!(got_answers, raw_answers_json);
                assert_eq!(sha256_hex(got_answers.as_bytes()), answers_sha256);
                assert_eq!(
                    pt_json["draft"]["deviceClockAt"],
                    built1.manifest.created_at
                );
            }
        }
    }

    #[test]
    fn test_refuses_unreduced_id10073_and_informant_without_consent_and_unauthorized_corrections() {
        let (_server_key, station_key, verified, _privates) = sample_keys_and_station_config();
        let now_utc = DateTime::parse_from_rfc3339("2026-10-21T11:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        let death_id = Uuid::new_v4();

        // 1. DeathRegistration with informant_phone but no consent_client_id -> ConsentRequired
        let mut reg_fields = BTreeMap::new();
        reg_fields.insert(
            "informant_phone".to_string(),
            Value::String("9876543210".to_string()),
        );
        let reg_no_consent = BundleRecordEnvelope {
            client_id: death_id,
            project_id: "P1".to_string(),
            actor_user_id: 101,
            acting_role: ActingRole::DeathReporter,
            recorded_at: "2026-10-21T10:01:00Z".to_string(),
            payload: BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
                site_id: "PHC01".to_string(),
                org_unit_id: None,
                fields: reg_fields,
                identifiers: None,
                consent_client_id: None,
            }),
        };
        assert_eq!(
            build_bundle(
                &verified,
                &station_key,
                "station-phc-01",
                1,
                "0.1.0",
                now_utc,
                &[reg_no_consent.clone()]
            )
            .unwrap_err(),
            BundleError::ConsentRequired {
                client_id: death_id
            }
        );

        // 2. InterviewSubmission with unreduced 12-digit Aadhaar in Id10073 -> UnreducedNationalId
        let draft_id = Uuid::new_v4();
        let bad_answers = "{\"Id10073\":\"234567890123\"}";
        let bad_sub = BundleRecordEnvelope {
            client_id: draft_id,
            project_id: "P1".to_string(),
            actor_user_id: 102,
            acting_role: ActingRole::Interviewer,
            recorded_at: "2026-10-21T10:04:00Z".to_string(),
            payload: BundleRecordPayload::InterviewSubmission(InterviewSubmissionRecord {
                site_id: "PHC01".to_string(),
                org_unit_id: Some("ou-sc-1".to_string()),
                death_ref: DeathRef::client_death(death_id),
                draft: InterviewDraftMeta {
                    instrument_version: "2022_v1".to_string(),
                    definition_sha256: Some("a".repeat(64)),
                    definition_extensions: None,
                    started_at: "2026-10-21T10:00:00Z".to_string(),
                    completed_at: Some("2026-10-21T10:04:00Z".to_string()),
                    device_clock_at: None,
                    interview_outcome: "completed".to_string(),
                },
                completion: InterviewCompletion {
                    valid: true,
                    issues: vec![],
                },
                answers_json: bad_answers.to_string(),
                answers_sha256: sha256_hex(bad_answers.as_bytes()),
                consent_client_id: None,
            }),
        };
        assert_eq!(
            build_bundle(
                &verified,
                &station_key,
                "station-phc-01",
                1,
                "0.1.0",
                now_utc,
                &[bad_sub]
            )
            .unwrap_err(),
            BundleError::UnreducedNationalId {
                client_id: draft_id
            }
        );

        // 3. DeathCorrection with acting_role = Interviewer -> InvalidActingRoleForRecord
        let corr_id = Uuid::new_v4();
        let mut changes = BTreeMap::new();
        changes.insert("sex".to_string(), Value::String("female".to_string()));
        let bad_corr = BundleRecordEnvelope {
            client_id: corr_id,
            project_id: "P1".to_string(),
            actor_user_id: 102,
            acting_role: ActingRole::Interviewer,
            recorded_at: "2026-10-21T10:03:00Z".to_string(),
            payload: BundleRecordPayload::DeathCorrection(DeathCorrectionRecord {
                death_ref: DeathRef::client_death(death_id),
                reason: "Fix sex".to_string(),
                if_updated_at: None,
                base_client_id: Some(death_id),
                changes,
            }),
        };
        assert!(matches!(
            build_bundle(
                &verified,
                &station_key,
                "station-phc-01",
                1,
                "0.1.0",
                now_utc,
                &[bad_corr]
            )
            .unwrap_err(),
            BundleError::InvalidActingRoleForRecord { .. }
        ));
    }

    #[test]
    fn test_receipt_verification_and_deletion_plan() {
        let (server_key, _station_key, _verified, _privates) = sample_keys_and_station_config();

        let reg_id = Uuid::parse_str("10000000-0000-4000-8000-000000000001").unwrap();
        let interview_ok_id = Uuid::parse_str("40000000-0000-4000-8000-000000000004").unwrap();
        let interview_bad_hash_id =
            Uuid::parse_str("40000000-0000-4000-8000-000000000005").unwrap();
        let coding_pending_id = Uuid::parse_str("60000000-0000-4000-8000-000000000006").unwrap();
        let corr_rejected_id = Uuid::parse_str("30000000-0000-4000-8000-000000000003").unwrap();
        let purge_id = Uuid::parse_str("90000000-0000-4000-8000-000000000099").unwrap();

        let good_hash = "c".repeat(64);
        let wrong_hash = "d".repeat(64);

        let mut local_hashes = BTreeMap::new();
        local_hashes.insert(interview_ok_id, good_hash.clone());
        local_hashes.insert(interview_bad_hash_id, good_hash.clone());

        let mut counts = BTreeMap::new();
        counts.insert("accepted".to_string(), 2);
        counts.insert("duplicate".to_string(), 1);
        counts.insert("pending".to_string(), 1);
        counts.insert("rejected".to_string(), 1);

        let report = BundleReceiptReport {
            bundle_id: Uuid::new_v4(),
            device_id: "station-phc-01".to_string(),
            kem_key_id: "tv1".to_string(),
            status: "processed".to_string(),
            counts,
            missing_seq: vec![],
            records: vec![
                ReceiptRecordOutcome {
                    client_id: reg_id,
                    record_type: RecordType::DeathRegistration,
                    outcome: RecordIngestOutcome::Accepted,
                    code: None,
                    received_sha256: None,
                    death_id: Some(Uuid::new_v4()),
                    unique_id: Some("P1-0001".to_string()),
                },
                ReceiptRecordOutcome {
                    client_id: interview_ok_id,
                    record_type: RecordType::InterviewSubmission,
                    outcome: RecordIngestOutcome::Duplicate,
                    code: None,
                    received_sha256: Some(good_hash),
                    death_id: None,
                    unique_id: None,
                },
                ReceiptRecordOutcome {
                    client_id: interview_bad_hash_id,
                    record_type: RecordType::InterviewSubmission,
                    outcome: RecordIngestOutcome::Accepted,
                    code: None,
                    received_sha256: Some(wrong_hash),
                    death_id: None,
                    unique_id: None,
                },
                ReceiptRecordOutcome {
                    client_id: coding_pending_id,
                    record_type: RecordType::CodingResult,
                    outcome: RecordIngestOutcome::Pending,
                    code: Some("not_ready".to_string()),
                    received_sha256: None,
                    death_id: None,
                    unique_id: None,
                },
                ReceiptRecordOutcome {
                    client_id: corr_rejected_id,
                    record_type: RecordType::DeathCorrection,
                    outcome: RecordIngestOutcome::Rejected,
                    code: Some("death_stale".to_string()),
                    received_sha256: None,
                    death_id: None,
                    unique_id: None,
                },
            ],
            purge: vec![purge_id, purge_id],
        };

        let signed_receipt = format_signed_receipt(&report, &server_key).unwrap();
        let plan = verify_and_plan_receipt(
            &signed_receipt,
            "station-phc-01",
            &server_key.public_key_bytes(),
            &local_hashes,
        )
        .unwrap();

        assert_eq!(plan.deletable_client_ids, vec![reg_id, interview_ok_id]);
        assert_eq!(plan.hash_mismatched_interviews, vec![interview_bad_hash_id]);
        assert_eq!(plan.pending_records, vec![(coding_pending_id, Some("not_ready".to_string()))]);
        assert_eq!(
            plan.rejected_records,
            vec![(corr_rejected_id, Some("death_stale".to_string()))]
        );
        assert_eq!(plan.purge_client_ids, vec![purge_id]);
    }

    #[test]
    fn test_receipt_with_attachment_chunk_outcome_verifies_and_plans() {
        let server_key = StationSigningKey::generate();
        let chunk_id = Uuid::parse_str("a0000000-0000-4000-8000-000000000001").unwrap();
        let report = BundleReceiptReport {
            bundle_id: Uuid::new_v4(),
            device_id: "station-phc-01".to_string(),
            kem_key_id: "tv1".to_string(),
            status: "processed".to_string(),
            counts: BTreeMap::new(),
            missing_seq: vec![],
            records: vec![ReceiptRecordOutcome {
                client_id: chunk_id,
                record_type: RecordType::AttachmentChunk,
                outcome: RecordIngestOutcome::Accepted,
                code: None,
                received_sha256: None,
                death_id: None,
                unique_id: None,
            }],
            purge: vec![],
        };
        let signed = format_signed_receipt(&report, &server_key).unwrap();
        assert!(signed.contains("\"attachment_chunk\""));
        let plan = verify_and_plan_receipt(
            &signed,
            "station-phc-01",
            &server_key.public_key_bytes(),
            &BTreeMap::new(),
        )
        .unwrap();
        assert_eq!(plan.deletable_client_ids, vec![chunk_id]);
    }

    #[test]
    fn test_write_bundle_atomic() {
        let tmp_dir = std::env::temp_dir().join(format!("digitva_bundle_test_{}", Uuid::new_v4()));
        let bundle_path = tmp_dir.join("test.dvb");
        let payload = b"line1\nline2\nline3\n";
        write_bundle_atomic(&bundle_path, payload).unwrap();
        let read_back = std::fs::read(&bundle_path).unwrap();
        assert_eq!(read_back, payload);
        let _ = std::fs::remove_dir_all(&tmp_dir);
    }

    #[test]
    fn test_within_type_ordering_correction_budget_roster_scope_and_jcs_integer_rule() {
        let (_server_key, station_key, verified, _privates) = sample_keys_and_station_config();
        let now_utc = DateTime::parse_from_rfc3339("2026-10-21T11:00:00Z")
            .unwrap()
            .with_timezone(&Utc);

        // 1. Within-type ordering by `recorded_at`
        let reg_later_id = Uuid::parse_str("10000000-0000-4000-8000-000000000010").unwrap();
        let reg_earlier_id = Uuid::parse_str("10000000-0000-4000-8000-000000000011").unwrap();
        let mut base_fields = BTreeMap::new();
        base_fields.insert("deceased_name".to_string(), Value::String("A".to_string()));

        let r_later = BundleRecordEnvelope {
            client_id: reg_later_id,
            project_id: "P1".to_string(),
            actor_user_id: 101,
            acting_role: ActingRole::DeathReporter,
            recorded_at: "2026-10-21T10:05:00Z".to_string(),
            payload: BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
                site_id: "PHC01".to_string(),
                org_unit_id: None,
                fields: base_fields.clone(),
                identifiers: None,
                consent_client_id: None,
            }),
        };
        let r_earlier = BundleRecordEnvelope {
            client_id: reg_earlier_id,
            project_id: "P1".to_string(),
            actor_user_id: 101,
            acting_role: ActingRole::DeathReporter,
            recorded_at: "2026-10-21T10:01:00Z".to_string(),
            payload: BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
                site_id: "PHC01".to_string(),
                org_unit_id: None,
                fields: base_fields.clone(),
                identifiers: None,
                consent_client_id: None,
            }),
        };
        let built = build_bundle(
            &verified,
            &station_key,
            "station-phc-01",
            1,
            "0.1.0",
            now_utc,
            &[r_later, r_earlier.clone()],
        )
        .unwrap();
        assert_eq!(built.items[0].client_id, reg_earlier_id);
        assert_eq!(built.items[1].client_id, reg_later_id);

        // 2. Expired station config at bundle build time
        let after_expiry = DateTime::parse_from_rfc3339("2028-01-01T00:00:00Z")
            .unwrap()
            .with_timezone(&Utc);
        assert!(matches!(
            build_bundle(
                &verified,
                &station_key,
                "station-phc-01",
                1,
                "0.1.0",
                after_expiry,
                &[r_earlier.clone()]
            )
            .unwrap_err(),
            BundleError::StationConfigExpired { .. }
        ));

        // 3. More than BUNDLE_MAX_CORRECTIONS (500) corrections -> TooManyCorrections(501)
        let mut changes = BTreeMap::new();
        changes.insert("sex".to_string(), Value::String("male".to_string()));
        let many_corrections: Vec<BundleRecordEnvelope> = (0..501)
            .map(|_| BundleRecordEnvelope {
                client_id: Uuid::new_v4(),
                project_id: "P1".to_string(),
                actor_user_id: 103,
                acting_role: ActingRole::StationSupervisor,
                recorded_at: "2026-10-21T10:03:00Z".to_string(),
                payload: BundleRecordPayload::DeathCorrection(DeathCorrectionRecord {
                    death_ref: DeathRef::client_death(reg_earlier_id),
                    reason: "Valid supervisor reason".to_string(),
                    if_updated_at: None,
                    base_client_id: Some(reg_earlier_id),
                    changes: changes.clone(),
                }),
            })
            .collect();
        assert_eq!(
            build_bundle(
                &verified,
                &station_key,
                "station-phc-01",
                1,
                "0.1.0",
                now_utc,
                &many_corrections
            )
            .unwrap_err(),
            BundleError::TooManyCorrections(501)
        );

        // 4. Float value in record fields -> CanonicalJsonError (JCS integer rule)
        let mut float_fields = BTreeMap::new();
        float_fields.insert("age_years".to_string(), json!(42.5));
        let float_rec = BundleRecordEnvelope {
            client_id: Uuid::new_v4(),
            project_id: "P1".to_string(),
            actor_user_id: 101,
            acting_role: ActingRole::DeathReporter,
            recorded_at: "2026-10-21T10:01:00Z".to_string(),
            payload: BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
                site_id: "PHC01".to_string(),
                org_unit_id: None,
                fields: float_fields,
                identifiers: None,
                consent_client_id: None,
            }),
        };
        assert!(matches!(
            build_bundle(
                &verified,
                &station_key,
                "station-phc-01",
                1,
                "0.1.0",
                now_utc,
                &[float_rec]
            )
            .unwrap_err(),
            BundleError::CanonicalJsonError(_)
        ));
    }
}
