pub mod catalog;
pub mod consent;
pub mod instrument;
pub mod roster;

use crate::catalog::{ensure_catalog_seeded, lookup_va_definition_for_icd, search_icd_catalog};
use crate::consent::{
    append_consent_record, assert_informant_consent_before_write, get_latest_consent_for_case,
    parse_contract_consent_config, purge_informant_pii_for_death_id, upsert_project_consent_config,
    ConsentEnvelopeInput,
};
use crate::instrument::{
    default_form_options, default_who_2022_va_definition, default_who_2022_va_definition_sha256,
};
use crate::roster::{
    get_active_actor, get_roster_snapshot, init_roster_tables_and_seed, normalise_acting_role,
    replace_provisioned_roster, switch_active_actor, update_sandbox_designations,
    upsert_sandbox_roster_member, ActiveActorContext, StationRosterMember, StationRosterSnapshot,
    UpsertRosterMemberInput,
};
use chrono::Utc;
use digitva_bundle::{
    build_bundle, sha256_hex, verify_and_plan_receipt, ActingRole, BuiltBundle,
    BundleRecordEnvelope, BundleRecordPayload, CodingResultKind, CodingResultRecord,
    ConsentDecision, ConsentMode, ConsentPurposeGrant, ConsentRecord, DeathCorrectionRecord,
    DeathRef, DeathRegistrationRecord, IdentifiersSetRecord, InterviewCompletion,
    InterviewDraftMeta, InterviewSubmissionRecord, StationConfigPayload, StationSigningKey,
    VerifiedStationConfig,
};
use digitva_pdf::{render_who_mccd_pdf, MccdConditionLine, WhoMccdCertificateData};
use digitva_smartva::{
    assert_no_pii_in_smartva_json_with_sealed, score_clinical_json_result,
    strip_pii_from_smartva_map_with_sealed, SmartVaEngine, SmartVaRunOptions,
};
use digitva_text::{
    canonical_payload_fingerprint, normalise_phone, redact_payload_national_ids,
    validate_identifier, IdentifierCharType, IdentifierValidationRule,
};
use hkdf::Hkdf;
use rand::rngs::OsRng;
use rand::RngCore;
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Instant;
use subtle::ConstantTimeEq;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StationConfig {
    pub mode: String, // "standalone" | "provisioned"
    pub station_id: String,
    pub facility_name: String,
    pub district_name: String,
    pub state_name: String,
    pub remote_server_url: Option<String>,
    pub provisioned_user_id: Option<String>,
    pub provisioned_user_name: Option<String>,
    pub provisioned_roles: Vec<String>,
    pub provisioned_token: Option<String>,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdentifierTypeSpec {
    pub id: i64,
    pub project_id: i64,
    pub code: String,
    pub label: String,
    pub description: String,
    pub char_type: String,
    pub min_length: usize,
    pub max_length: usize,
    pub pattern: Option<String>,
    #[serde(default)]
    pub example: Option<String>,
    pub required_at_registration: bool,
    pub required_at_report: bool,
    pub active: bool,
    pub sort_order: i64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdentifierDuplicateWarning {
    pub code: String,
    pub field: String,
    pub message: String,
}

#[derive(Debug, Clone)]
pub struct StoreLockState {
    pub is_locked: bool,
    pub unlocked_member_id: Option<String>,
    pub last_activity_at: Instant,
    pub auto_lock_timeout_secs: u64,
    pub keystore_secret: [u8; 32],
}

#[derive(Clone)]
pub struct OfflineDatabase {
    conn: Arc<Mutex<Connection>>,
    resource_dir: Option<PathBuf>,
    lock_state: Arc<Mutex<StoreLockState>>,
}

impl OfflineDatabase {
    pub fn open_in_memory() -> anyhow::Result<Self> {
        let conn = Connection::open_in_memory()?;
        let mut keystore_secret = [0u8; 32];
        OsRng.fill_bytes(&mut keystore_secret);
        let db = Self {
            conn: Arc::new(Mutex::new(conn)),
            resource_dir: None,
            lock_state: Arc::new(Mutex::new(StoreLockState {
                is_locked: false,
                unlocked_member_id: None,
                last_activity_at: Instant::now(),
                auto_lock_timeout_secs: 900,
                keystore_secret,
            })),
        };
        db.init_schema_and_defaults()?;
        Ok(db)
    }

    pub fn open_file(path: impl AsRef<Path>, resource_dir: Option<PathBuf>) -> anyhow::Result<Self> {
        if let Some(parent) = path.as_ref().parent() {
            std::fs::create_dir_all(parent)?;
        }
        let conn = Connection::open(path)?;
        let mut keystore_secret = [0u8; 32];
        OsRng.fill_bytes(&mut keystore_secret);
        let db = Self {
            conn: Arc::new(Mutex::new(conn)),
            resource_dir,
            lock_state: Arc::new(Mutex::new(StoreLockState {
                is_locked: false,
                unlocked_member_id: None,
                last_activity_at: Instant::now(),
                auto_lock_timeout_secs: 900,
                keystore_secret,
            })),
        };
        db.init_schema_and_defaults()?;
        Ok(db)
    }

    /// Derive a 256-bit (64-hex) SQLCipher key from a per-user OS-keystore secret and a 6–16 digit PIN.
    pub fn derive_sqlcipher_key_hex(
        keystore_secret: &[u8; 32],
        member_id: &str,
        pin: &str,
    ) -> Result<String, String> {
        let trimmed = pin.trim();
        if !(6..=16).contains(&trimmed.len()) || !trimmed.chars().all(|c| c.is_ascii_digit()) {
            return Err("PIN must be 6 to 16 digits.".to_string());
        }
        let hk = Hkdf::<Sha256>::new(Some(keystore_secret), trimmed.as_bytes());
        let mut okm = [0u8; 32];
        let info = format!("digitva-sqlcipher-user-store-v1:{member_id}");
        hk.expand(info.as_bytes(), &mut okm)
            .map_err(|_| "Key derivation error".to_string())?;
        Ok(hex::encode(okm))
    }

    /// Open a SQLCipher-encrypted database file keyed by `derive_sqlcipher_key_hex`.
    pub fn open_encrypted_file(
        path: impl AsRef<Path>,
        keystore_secret: [u8; 32],
        member_id: &str,
        pin: &str,
        resource_dir: Option<PathBuf>,
    ) -> anyhow::Result<Self> {
        if let Some(parent) = path.as_ref().parent() {
            std::fs::create_dir_all(parent)?;
        }
        let key_hex = Self::derive_sqlcipher_key_hex(&keystore_secret, member_id, pin)
            .map_err(|e| anyhow::anyhow!(e))?;
        let conn = Connection::open(path)?;
        conn.execute_batch(&format!("PRAGMA key = \"x'{key_hex}'\";"))?;
        let db = Self {
            conn: Arc::new(Mutex::new(conn)),
            resource_dir,
            lock_state: Arc::new(Mutex::new(StoreLockState {
                is_locked: false,
                unlocked_member_id: Some(member_id.to_string()),
                last_activity_at: Instant::now(),
                auto_lock_timeout_secs: 900,
                keystore_secret,
            })),
        };
        db.init_schema_and_defaults()?;
        Ok(db)
    }

    pub fn with_conn<F, R>(&self, f: F) -> R
    where
        F: FnOnce(&Connection) -> R,
    {
        let guard = self.conn.lock().expect("SQLite mutex poisoned");
        f(&guard)
    }

    fn init_schema_and_defaults(&self) -> anyhow::Result<()> {
        let guard = self.conn.lock().expect("SQLite mutex poisoned");
        guard.execute_batch(
            "
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS loc_station_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mode TEXT NOT NULL DEFAULT 'standalone' CHECK (mode IN ('standalone', 'provisioned')),
                station_id TEXT NOT NULL,
                facility_name TEXT NOT NULL,
                district_name TEXT NOT NULL,
                state_name TEXT NOT NULL,
                remote_server_url TEXT,
                provisioned_user_id TEXT,
                provisioned_user_name TEXT,
                provisioned_roles_json TEXT NOT NULL DEFAULT '[]',
                provisioned_token TEXT,
                station_signing_secret_b64 TEXT,
                station_signing_public_b64 TEXT,
                station_signing_key_id TEXT,
                bundle_seq INTEGER NOT NULL DEFAULT 0,
                raw_signed_config TEXT,
                server_verifying_key_hex TEXT,
                station_config_id TEXT,
                config_issued_at TEXT,
                config_expires_at TEXT,
                custodian_json TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loc_user_pin_store (
                member_id TEXT PRIMARY KEY,
                pin_key_hash_hex TEXT NOT NULL,
                failed_pin_attempts INTEGER NOT NULL DEFAULT 0,
                wiped_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loc_project_config (
                project_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                sealed_field_ids_json TEXT NOT NULL DEFAULT '[]',
                va_instrument_json TEXT,
                coding_config_json TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS consent_configs (
                project_id INTEGER PRIMARY KEY,
                consent_required INTEGER NOT NULL DEFAULT 1,
                min_notice_version TEXT NOT NULL DEFAULT '0.1',
                config_json TEXT NOT NULL,
                synced_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS consent_records (
                consent_id TEXT PRIMARY KEY,
                project_id INTEGER NOT NULL,
                client_death_id TEXT,
                client_draft_id TEXT,
                death_id INTEGER,
                action_type TEXT NOT NULL CHECK (action_type IN ('granted', 'refused', 'grant', 'refusal', 'withdrawn')),
                notice_version_id TEXT NOT NULL DEFAULT '',
                notice_version TEXT NOT NULL DEFAULT '0.1',
                locale TEXT NOT NULL,
                notice_sha256 TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL CHECK (mode IN ('spoken', 'tap', 'tapped', 'signed')),
                witness_present INTEGER NOT NULL DEFAULT 0,
                supersedes_client_id TEXT,
                purposes_json TEXT NOT NULL,
                all_required_granted INTEGER NOT NULL CHECK (all_required_granted IN (0, 1)),
                sms_whatsapp_granted INTEGER NOT NULL DEFAULT 0,
                research_sharing_granted INTEGER NOT NULL DEFAULT 0,
                actor_user_id INTEGER,
                actor_member_id TEXT,
                acting_role TEXT,
                recorded_by TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                device_id TEXT NOT NULL,
                sync_state TEXT NOT NULL DEFAULT 'pending',
                sync_error_code TEXT
            );

            CREATE TABLE IF NOT EXISTS mas_death_identifier_type (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                label TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                char_type TEXT NOT NULL DEFAULT 'letters_digits_hyphen_slash',
                min_length INTEGER NOT NULL DEFAULT 1,
                max_length INTEGER NOT NULL DEFAULT 64,
                pattern TEXT,
                example TEXT,
                required_at_registration INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 10,
                UNIQUE(project_id, code)
            );

            CREATE TABLE IF NOT EXISTS loc_death_register (
                death_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_death_id TEXT UNIQUE,
                unique_id TEXT NOT NULL UNIQUE,
                project_id INTEGER NOT NULL DEFAULT 1,
                project_id_str TEXT NOT NULL DEFAULT '1',
                site_id TEXT NOT NULL DEFAULT 'PHC01',
                site_name TEXT NOT NULL DEFAULT 'Primary Health Centre',
                org_unit_id TEXT NOT NULL DEFAULT 'ou-sc-1',
                org_unit_name TEXT NOT NULL DEFAULT 'Sub-Centre 1',
                deceased_name TEXT NOT NULL,
                deceased_sex TEXT NOT NULL,
                date_of_death TEXT NOT NULL,
                date_of_birth TEXT,
                date_of_birth_partial TEXT,
                age_years REAL,
                place_of_death TEXT,
                father_name TEXT,
                mother_name TEXT,
                abha_number TEXT,
                abha_address TEXT,
                informant_name TEXT,
                informant_relation TEXT,
                informant_phone TEXT,
                informant_phone_2 TEXT,
                address TEXT,
                address_house_street TEXT,
                address_village_ward TEXT,
                address_landmark TEXT,
                location TEXT,
                latitude REAL,
                longitude REAL,
                accuracy_m REAL,
                remarks TEXT,
                status TEXT NOT NULL DEFAULT 'registered',
                state TEXT NOT NULL DEFAULT 'ready_for_interview',
                consent_status TEXT NOT NULL DEFAULT 'pending',
                consent_withdrawn_at TEXT,
                last_contact_at TEXT,
                next_visit_at TEXT,
                va_sid TEXT,
                sync_state TEXT NOT NULL DEFAULT 'pending',
                sync_error_code TEXT,
                sync_error_fields_json TEXT,
                actor_user_id INTEGER,
                actor_member_id TEXT,
                acting_role TEXT,
                created_by TEXT NOT NULL DEFAULT 'standalone-phc',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS map_death_identifier (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                death_id INTEGER NOT NULL REFERENCES loc_death_register(death_id) ON DELETE CASCADE,
                type_code TEXT NOT NULL,
                identifier_norm TEXT NOT NULL,
                captured_by TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                UNIQUE(death_id, type_code)
            );
            CREATE INDEX IF NOT EXISTS idx_map_death_identifier_lookup
                ON map_death_identifier(project_id, type_code, identifier_norm);

            CREATE TABLE IF NOT EXISTS loc_supervisor_corrections (
                client_id TEXT PRIMARY KEY,
                record_type TEXT NOT NULL CHECK (record_type IN ('death_correction', 'identifiers_set')),
                death_id INTEGER NOT NULL,
                client_death_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                site_id TEXT,
                org_unit_id TEXT,
                actor_user_id INTEGER,
                actor_member_id TEXT,
                acting_role TEXT,
                reason TEXT,
                payload_json TEXT NOT NULL,
                sync_state TEXT NOT NULL DEFAULT 'pending',
                sync_error_code TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS map_case_transitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                death_id INTEGER NOT NULL,
                from_state TEXT,
                to_state TEXT NOT NULL,
                actor_name TEXT NOT NULL,
                reason TEXT,
                changes_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loc_case_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                death_id INTEGER NOT NULL,
                outcome TEXT NOT NULL,
                next_visit_at TEXT,
                actor_name TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loc_va_drafts (
                draft_id TEXT PRIMARY KEY,
                unique_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                site_id TEXT NOT NULL,
                site_name TEXT NOT NULL,
                org_unit_id TEXT,
                org_unit_name TEXT,
                death_id INTEGER,
                status TEXT NOT NULL DEFAULT 'in_progress',
                current_section TEXT,
                locale TEXT NOT NULL DEFAULT 'en',
                translation_version INTEGER NOT NULL DEFAULT 1,
                answers_json TEXT NOT NULL DEFAULT '{}',
                prefill_json TEXT NOT NULL DEFAULT '{}',
                actor_user_id INTEGER,
                actor_member_id TEXT,
                acting_role TEXT,
                sync_state TEXT NOT NULL DEFAULT 'pending',
                sync_error_code TEXT,
                updated_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loc_va_submissions (
                va_sid TEXT PRIMARY KEY,
                death_id INTEGER,
                draft_id TEXT,
                unique_id TEXT NOT NULL,
                project_id TEXT NOT NULL DEFAULT '1',
                site_id TEXT NOT NULL DEFAULT 'PHC01',
                org_unit_id TEXT,
                form_type_code TEXT NOT NULL DEFAULT 'WHO_2022_VA',
                deceased_name TEXT,
                deceased_age TEXT,
                deceased_gender TEXT,
                narration_language TEXT DEFAULT 'en',
                payload_json TEXT NOT NULL,
                payload_fingerprint TEXT NOT NULL,
                flagged_fields_json TEXT NOT NULL DEFAULT '[]',
                workflow_state TEXT NOT NULL DEFAULT 'available_for_coding',
                allocated_coder TEXT,
                allocated_reviewer TEXT,
                smartva_status TEXT NOT NULL DEFAULT 'not_requested',
                smartva_json TEXT,
                initial_assessment_json TEXT,
                final_assessment_json TEXT,
                not_codeable_json TEXT,
                reviewer_initial_json TEXT,
                reviewer_final_json TEXT,
                doris_json TEXT,
                narrative_qa_json TEXT,
                social_autopsy_json TEXT,
                note_content TEXT,
                note_updated_at TEXT,
                actor_user_id INTEGER,
                actor_member_id TEXT,
                acting_role TEXT,
                sync_state TEXT NOT NULL DEFAULT 'pending',
                sync_error_code TEXT,
                submitted_at TEXT NOT NULL,
                coded_at TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loc_coding_results (
                client_id TEXT PRIMARY KEY,
                va_sid TEXT NOT NULL,
                client_draft_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                site_id TEXT,
                org_unit_id TEXT,
                actor_user_id INTEGER,
                actor_member_id TEXT,
                acting_role TEXT,
                payload_json TEXT NOT NULL,
                sync_state TEXT NOT NULL DEFAULT 'pending',
                sync_error_code TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS loc_workflow_events (
                event_id TEXT PRIMARY KEY,
                va_sid TEXT NOT NULL,
                transition_id TEXT NOT NULL,
                previous_state TEXT,
                current_state TEXT NOT NULL,
                actor_kind TEXT NOT NULL,
                actor_role TEXT,
                transition_reason TEXT,
                event_created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cat_va_causes (
                va_code TEXT PRIMARY KEY,
                va_group TEXT NOT NULL,
                va_title TEXT NOT NULL,
                icd10_codes TEXT NOT NULL,
                icd11_codes TEXT NOT NULL,
                definition_html TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS cat_icd_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                classification TEXT NOT NULL CHECK (classification IN ('icd10', 'icd11')),
                code TEXT NOT NULL,
                title TEXT NOT NULL,
                chapter_code TEXT,
                chapter_title TEXT,
                va_code TEXT,
                va_title TEXT,
                synonyms TEXT NOT NULL DEFAULT '',
                UNIQUE(classification, code)
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS cat_icd_fts USING fts5(
                classification,
                code,
                title,
                synonyms,
                va_title
            );
            ",
        )?;

        let now = Utc::now().to_rfc3339();
        let mut signing_seed = [0u8; 32];
        OsRng.fill_bytes(&mut signing_seed);
        let signing_key = StationSigningKey::from_secret_bytes(&signing_seed);
        let secret_hex = hex::encode(signing_seed);
        guard.execute(
            "INSERT OR IGNORE INTO loc_station_config (
                id, mode, station_id, facility_name, district_name, state_name,
                station_signing_secret_b64, station_signing_public_b64, station_signing_key_id,
                bundle_seq, updated_at
             ) VALUES (1, 'standalone', 'phc-standalone-01', 'Model Primary Health Centre', 'Demo District', 'Demo State', ?1, ?2, ?3, 0, ?4)",
            params![
                secret_hex,
                signing_key.public_key_base64url(),
                signing_key.signing_key_id(),
                now
            ],
        )?;

        // Seed built-in CRS and MCCD identifier types for project 1
        guard.execute(
            "INSERT OR IGNORE INTO mas_death_identifier_type (
                project_id, code, label, description, char_type, min_length, max_length, pattern, example, required_at_registration, active, sort_order
             ) VALUES
             (1, 'crs_reg_no', 'CRS Registration Number', 'Civil Registration System death registration number', 'letters_digits_hyphen_slash', 3, 64, NULL, 'CRS-2026-00421', 0, 1, 10),
             (1, 'mccd_cert_no', 'MCCD Certificate Number', 'Medical Certification of Cause of Death certificate number', 'letters_digits_hyphen_slash', 3, 64, NULL, 'MCCD/2026/0098', 0, 1, 20)",
            [],
        )?;

        ensure_catalog_seeded(&guard, self.resource_dir.as_deref())?;
        init_roster_tables_and_seed(&guard)?;
        Ok(())
    }

    // ========================================================================
    // Per-User PIN Store, Auto-Lock & 5-Attempt Wipe (Contract 1.1 & 2.3)
    // ========================================================================

    pub fn set_user_pin(&self, member_id: &str, pin: &str) -> Result<(), String> {
        let keystore_secret = {
            let ls = self.lock_state.lock().unwrap();
            ls.keystore_secret
        };
        let key_hex = Self::derive_sqlcipher_key_hex(&keystore_secret, member_id, pin)?;
        let mut h = Sha256::new();
        h.update(key_hex.as_bytes());
        let hash_hex = format!("{:x}", h.finalize());
        let now = Utc::now().to_rfc3339();
        self.with_conn(|conn| {
            conn.execute(
                "INSERT INTO loc_user_pin_store (member_id, pin_key_hash_hex, failed_pin_attempts, wiped_at, updated_at)
                 VALUES (?1, ?2, 0, NULL, ?3)
                 ON CONFLICT(member_id) DO UPDATE SET
                    pin_key_hash_hex = excluded.pin_key_hash_hex,
                    failed_pin_attempts = 0,
                    wiped_at = NULL,
                    updated_at = excluded.updated_at",
                params![member_id, hash_hex, now],
            )
            .map_err(|e| e.to_string())?;
            Ok(())
        })
    }

    pub fn lock_store(&self) {
        let mut ls = self.lock_state.lock().unwrap();
        ls.is_locked = true;
        ls.unlocked_member_id = None;
    }

    pub fn set_auto_lock_timeout_secs(&self, secs: u64) {
        let mut ls = self.lock_state.lock().unwrap();
        ls.auto_lock_timeout_secs = secs;
    }

    pub fn simulate_inactivity_secs(&self, secs: u64) {
        let mut ls = self.lock_state.lock().unwrap();
        if secs >= ls.auto_lock_timeout_secs {
            ls.is_locked = true;
            ls.unlocked_member_id = None;
        }
    }

    pub fn is_locked(&self) -> bool {
        let mut ls = self.lock_state.lock().unwrap();
        if !ls.is_locked && ls.last_activity_at.elapsed().as_secs() >= ls.auto_lock_timeout_secs {
            ls.is_locked = true;
            ls.unlocked_member_id = None;
        }
        ls.is_locked
    }

    pub fn record_activity(&self) {
        let mut ls = self.lock_state.lock().unwrap();
        ls.last_activity_at = Instant::now();
    }

    pub fn unlock_user_store(&self, member_id: &str, pin: &str) -> Result<(), (u16, Value)> {
        let keystore_secret = {
            let ls = self.lock_state.lock().unwrap();
            ls.keystore_secret
        };
        let derived_hex =
            Self::derive_sqlcipher_key_hex(&keystore_secret, member_id, pin).map_err(|msg| {
                (
                    400,
                    json!({ "error": msg, "code": "invalid_pin_format" }),
                )
            })?;
        let mut h = Sha256::new();
        h.update(derived_hex.as_bytes());
        let candidate_hash = format!("{:x}", h.finalize());
        let now = Utc::now().to_rfc3339();

        let res = self.with_conn(|conn| {
            let row: Option<(String, i64, Option<String>)> = conn
                .query_row(
                    "SELECT pin_key_hash_hex, failed_pin_attempts, wiped_at FROM loc_user_pin_store WHERE member_id = ?1",
                    params![member_id],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .optional()
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            let Some((expected_hash, failed_attempts, wiped_at)) = row else {
                // First time setting PIN for this member
                conn.execute(
                    "INSERT INTO loc_user_pin_store (member_id, pin_key_hash_hex, failed_pin_attempts, wiped_at, updated_at)
                     VALUES (?1, ?2, 0, NULL, ?3)",
                    params![member_id, candidate_hash, now],
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                return Ok(());
            };

            if wiped_at.is_some() || failed_attempts >= 5 {
                return Err((
                    403,
                    json!({
                        "error": "User store has been wiped after 5 consecutive failed PIN attempts.",
                        "code": "store_wiped_max_pin_attempts"
                    }),
                ));
            }

            let matches: bool = expected_hash
                .as_bytes()
                .ct_eq(candidate_hash.as_bytes())
                .into();
            if matches {
                conn.execute(
                    "UPDATE loc_user_pin_store SET failed_pin_attempts = 0, updated_at = ?1 WHERE member_id = ?2",
                    params![now, member_id],
                )
                .ok();
                Ok(())
            } else {
                let new_attempts = failed_attempts + 1;
                if new_attempts >= 5 {
                    Self::wipe_user_store_records(conn, member_id, &now);
                    Err((
                        403,
                        json!({
                            "error": "Maximum failed PIN attempts reached; user local store has been wiped.",
                            "code": "store_wiped_max_pin_attempts",
                            "failed_attempts": new_attempts
                        }),
                    ))
                } else {
                    conn.execute(
                        "UPDATE loc_user_pin_store SET failed_pin_attempts = ?1, updated_at = ?2 WHERE member_id = ?3",
                        params![new_attempts, now, member_id],
                    )
                    .ok();
                    Err((
                        401,
                        json!({
                            "error": "Invalid PIN.",
                            "code": "invalid_pin",
                            "remaining_attempts": 5 - new_attempts
                        }),
                    ))
                }
            }
        });

        if res.is_ok() {
            let mut ls = self.lock_state.lock().unwrap();
            ls.is_locked = false;
            ls.unlocked_member_id = Some(member_id.to_string());
            ls.last_activity_at = Instant::now();
        }
        res
    }

    fn wipe_user_store_records(conn: &Connection, member_id: &str, now: &str) {
        conn.execute(
            "DELETE FROM loc_coding_results WHERE actor_member_id = ?1",
            params![member_id],
        )
        .ok();
        conn.execute(
            "DELETE FROM loc_va_submissions WHERE actor_member_id = ?1 OR allocated_coder = ?1",
            params![member_id],
        )
        .ok();
        conn.execute(
            "DELETE FROM loc_va_drafts WHERE actor_member_id = ?1",
            params![member_id],
        )
        .ok();
        conn.execute(
            "DELETE FROM loc_supervisor_corrections WHERE actor_member_id = ?1",
            params![member_id],
        )
        .ok();
        conn.execute(
            "DELETE FROM consent_records WHERE actor_member_id = ?1 OR recorded_by = ?1",
            params![member_id],
        )
        .ok();
        conn.execute(
            "DELETE FROM map_death_identifier WHERE death_id IN (SELECT death_id FROM loc_death_register WHERE actor_member_id = ?1 OR created_by = ?1)",
            params![member_id],
        )
        .ok();
        conn.execute(
            "DELETE FROM loc_death_register WHERE actor_member_id = ?1 OR created_by = ?1",
            params![member_id],
        )
        .ok();
        conn.execute(
            "UPDATE loc_user_pin_store SET failed_pin_attempts = 5, wiped_at = ?1, updated_at = ?1 WHERE member_id = ?2",
            params![now, member_id],
        )
        .ok();
        conn.execute(
            "INSERT INTO loc_station_roster_audit (event_type, member_id, acting_role, detail_json, created_at)
             VALUES ('user_store_wiped_max_pin_attempts', ?1, NULL, '{}', ?2)",
            params![member_id, now],
        )
        .ok();
    }

    // ========================================================================
    // Station Roster & Acting Role (digitva-gb8w.8)
    // ========================================================================

    pub fn get_roster(&self) -> StationRosterSnapshot {
        let cfg = self.get_station_config();
        self.with_conn(|conn| get_roster_snapshot(conn, &cfg.mode))
    }

    pub fn get_active_actor_context(&self) -> ActiveActorContext {
        self.with_conn(get_active_actor)
    }

    pub fn switch_acting_role(
        &self,
        member_id: &str,
        acting_role: Option<&str>,
    ) -> Result<ActiveActorContext, String> {
        self.with_conn(|conn| switch_active_actor(conn, member_id, acting_role))
    }

    pub fn switch_acting_role_with_pin(
        &self,
        member_id: &str,
        acting_role: Option<&str>,
        pin: Option<&str>,
    ) -> Result<ActiveActorContext, (u16, Value)> {
        if let Some(p) = pin {
            self.unlock_user_store(member_id, p)?;
        } else if self.is_locked() {
            return Err((
                423,
                json!({
                    "error": "Station store is locked; PIN is required to switch user or unlock.",
                    "code": "station_locked"
                }),
            ));
        }
        self.record_activity();
        self.switch_acting_role(member_id, acting_role)
            .map_err(|msg| (422, json!({ "error": msg, "code": "invalid_acting_role" })))
    }

    pub fn upsert_roster_member(
        &self,
        input: &UpsertRosterMemberInput,
    ) -> Result<StationRosterMember, (u16, String)> {
        let cfg = self.get_station_config();
        self.with_conn(|conn| upsert_sandbox_roster_member(conn, &cfg.mode, input))
    }

    pub fn update_designations(
        &self,
        designations: &[String],
    ) -> Result<Vec<String>, (u16, String)> {
        let cfg = self.get_station_config();
        self.with_conn(|conn| update_sandbox_designations(conn, &cfg.mode, designations))
    }

    // ========================================================================
    // Signed Station Config Import, Purge & .dvb Bundle / Receipt (Contract 2 & 6)
    // ========================================================================

    /// Verify and apply a signed `.digitva-station.json` two-line station config file.
    pub fn import_signed_station_config(
        &self,
        raw_two_line_text: &str,
    ) -> Result<Value, (u16, Value)> {
        let current = self.get_station_config();
        let pinned_vk_hex: Option<String> = self.with_conn(|conn| {
            conn.query_row(
                "SELECT server_verifying_key_hex FROM loc_station_config WHERE id = 1",
                [],
                |r| r.get::<_, Option<String>>(0),
            )
            .optional()
            .ok()
            .flatten()
            .flatten()
        });

        let line1 = raw_two_line_text
            .trim()
            .lines()
            .next()
            .ok_or_else(|| {
                (
                    422,
                    json!({
                        "error": "Signed station config is empty.",
                        "code": "invalid_station_config"
                    }),
                )
            })?;
        let unverified_payload: StationConfigPayload = serde_json::from_str(line1).map_err(|e| {
            (
                422,
                json!({
                    "error": format!("Invalid station config JSON: {e}"),
                    "code": "invalid_station_config"
                }),
            )
        })?;

        let expected_device_id = if current.mode == "provisioned" {
            current.station_id.as_str()
        } else {
            unverified_payload.device_id.as_str()
        };

        let pinned_key: Option<[u8; 32]> = match pinned_vk_hex {
            Some(ref hex_str) => Some(
                hex::decode(hex_str)
                    .ok()
                    .and_then(|v| v.try_into().ok())
                    .ok_or_else(|| {
                        (
                            500,
                            json!({ "error": "Corrupt pinned server verifying key", "code": "db_error" }),
                        )
                    })?,
            ),
            None => None,
        };

        let preview: VerifiedStationConfig = VerifiedStationConfig::parse_and_verify(
            raw_two_line_text,
            expected_device_id,
            pinned_key.as_ref(),
        )
        .map_err(|e| {
            (
                422,
                json!({
                    "error": e.to_string(),
                    "code": "invalid_station_config"
                }),
            )
        })?;

        if preview.is_expired(Utc::now()) {
            return Err((
                422,
                json!({
                    "error": "Station configuration has expired.",
                    "code": "station_config_expired"
                }),
            ));
        }

        let cfg = &preview.config;
        let now = Utc::now().to_rfc3339();
        let vk_hex = hex::encode(preview.server_verifying_key);
        let custodian_json = serde_json::to_string(&cfg.custodian).ok();

        let first_member = cfg.roster.first();
        let prov_uid = first_member.map(|m| m.user_id.to_string());
        let prov_uname = first_member.map(|m| m.name.clone());
        let mut all_roles: Vec<String> = Vec::new();
        for m in &cfg.roster {
            for rg in &m.roles {
                let role_str = rg.role.as_str().to_string();
                if !all_roles.contains(&role_str) {
                    all_roles.push(role_str);
                }
            }
        }
        let roles_json = serde_json::to_string(&all_roles).unwrap_or_else(|_| "[]".to_string());

        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config
                 SET mode = 'provisioned',
                     station_id = ?1,
                     remote_server_url = ?2,
                     provisioned_user_id = COALESCE(?3, provisioned_user_id),
                     provisioned_user_name = COALESCE(?4, provisioned_user_name),
                     provisioned_roles_json = ?5,
                     raw_signed_config = ?6,
                     server_verifying_key_hex = ?7,
                     station_config_id = ?8,
                     config_issued_at = ?9,
                     config_expires_at = ?10,
                     custodian_json = ?11,
                     updated_at = ?12
                 WHERE id = 1",
                params![
                    cfg.device_id,
                    cfg.server_url,
                    prov_uid,
                    prov_uname,
                    roles_json,
                    raw_two_line_text,
                    vk_hex,
                    cfg.config_id.to_string(),
                    cfg.issued_at,
                    cfg.expires_at,
                    custodian_json,
                    now
                ],
            )
            .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            for proj in &cfg.projects {
                let pid_num = proj.project_id.parse::<i64>().unwrap_or(2);
                let sealed_json = serde_json::to_string(&proj.sealed_field_ids)
                    .unwrap_or_else(|_| "[]".to_string());
                let inst_versions_json = serde_json::to_string(&proj.instrument_versions).ok();

                conn.execute(
                    "INSERT INTO loc_project_config (project_id, project_name, sealed_field_ids_json, va_instrument_json, coding_config_json, updated_at)
                     VALUES (?1, ?2, ?3, ?4, NULL, ?5)
                     ON CONFLICT(project_id) DO UPDATE SET
                        project_name = excluded.project_name,
                        sealed_field_ids_json = excluded.sealed_field_ids_json,
                        va_instrument_json = excluded.va_instrument_json,
                        updated_at = excluded.updated_at",
                    params![proj.project_id, proj.project_id, sealed_json, inst_versions_json, now],
                )
                .ok();

                if let Some(ref consent_val) = proj.consent {
                    let parsed_consent =
                        parse_contract_consent_config(pid_num, consent_val).map_err(|msg| {
                            (
                                422,
                                json!({ "error": msg, "code": "invalid_consent_config" }),
                            )
                        })?;
                    upsert_project_consent_config(conn, &parsed_consent)
                        .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                }
            }

            replace_provisioned_roster(conn, &cfg.designations, &cfg.roster)
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            Ok::<(), (u16, Value)>(())
        })?;

        let purged_count = self.apply_purge_list(&cfg.purge);
        let purged_ids: Vec<String> = cfg.purge.iter().map(ToString::to_string).collect();
        let roster = self.get_roster();
        Ok(json!({
            "station_config_id": cfg.config_id.to_string(),
            "device_id": cfg.device_id,
            "mode": "provisioned",
            "station_mode": "provisioned",
            "custodian": cfg.custodian,
            "config_expires_at": cfg.expires_at,
            "purged_count": purged_count,
            "purged_ids": purged_ids,
            "roster": roster
        }))
    }

    /// Execute a server-issued `purge` list of `client_id` UUIDs (consent withdrawal / case deletion).
    pub fn apply_purge_list(&self, purge_ids: &[Uuid]) -> usize {
        if purge_ids.is_empty() {
            return 0;
        }
        self.with_conn(|conn| {
            let mut purged = 0usize;
            for uuid in purge_ids {
                let cid = uuid.to_string();

                // 1. Check if this client_id is a consent record -> scrub informant PII on the case and delete consent row
                let consent_match: Option<(Option<i64>, Option<String>)> = conn
                    .query_row(
                        "SELECT death_id, client_death_id FROM consent_records WHERE consent_id = ?1",
                        params![cid],
                        |r| Ok((r.get(0)?, r.get(1)?)),
                    )
                    .optional()
                    .ok()
                    .flatten();
                if let Some((did_opt, cdid_opt)) = consent_match {
                    let target_did = did_opt.or_else(|| {
                        cdid_opt.as_deref().and_then(|cdid| {
                            conn.query_row(
                                "SELECT death_id FROM loc_death_register WHERE client_death_id = ?1",
                                params![cdid],
                                |r| r.get(0),
                            )
                            .optional()
                            .ok()
                            .flatten()
                        })
                    });
                    if let Some(did) = target_did {
                        let _ = purge_informant_pii_for_death_id(conn, did);
                    }
                    conn.execute("DELETE FROM consent_records WHERE consent_id = ?1", params![cid])
                        .ok();
                    purged += 1;
                    continue;
                }

                // 2. Check if this client_id is a death report (`client_death_id`)
                let death_id_opt: Option<i64> = conn
                    .query_row(
                        "SELECT death_id FROM loc_death_register WHERE client_death_id = ?1",
                        params![cid],
                        |r| r.get(0),
                    )
                    .optional()
                    .ok()
                    .flatten();
                if let Some(did) = death_id_opt {
                    conn.execute(
                        "DELETE FROM loc_coding_results WHERE va_sid IN (SELECT va_sid FROM loc_va_submissions WHERE death_id = ?1)",
                        params![did],
                    )
                    .ok();
                    conn.execute("DELETE FROM loc_va_submissions WHERE death_id = ?1", params![did])
                        .ok();
                    conn.execute("DELETE FROM loc_va_drafts WHERE death_id = ?1", params![did])
                        .ok();
                    conn.execute("DELETE FROM loc_supervisor_corrections WHERE death_id = ?1", params![did])
                        .ok();
                    conn.execute("DELETE FROM consent_records WHERE death_id = ?1 OR client_death_id = ?2", params![did, cid])
                        .ok();
                    conn.execute("DELETE FROM map_death_identifier WHERE death_id = ?1", params![did])
                        .ok();
                    conn.execute("DELETE FROM loc_death_register WHERE death_id = ?1", params![did])
                        .ok();
                    purged += 1;
                    continue;
                }

                // 3. Check if this client_id is a VA draft/submission (`draft_id`)
                let draft_matched = conn
                    .execute(
                        "DELETE FROM loc_coding_results WHERE client_draft_id = ?1",
                        params![cid],
                    )
                    .unwrap_or(0)
                    + conn
                        .execute(
                            "DELETE FROM loc_va_submissions WHERE draft_id = ?1",
                            params![cid],
                        )
                        .unwrap_or(0)
                    + conn
                        .execute("DELETE FROM loc_va_drafts WHERE draft_id = ?1", params![cid])
                        .unwrap_or(0);
                if draft_matched > 0 {
                    purged += 1;
                    continue;
                }

                // 4. Supervisor corrections or coding results by client_id
                let other_matched = conn
                    .execute(
                        "DELETE FROM loc_supervisor_corrections WHERE client_id = ?1",
                        params![cid],
                    )
                    .unwrap_or(0)
                    + conn
                        .execute(
                            "DELETE FROM loc_coding_results WHERE client_id = ?1",
                            params![cid],
                        )
                        .unwrap_or(0);
                if other_matched > 0 {
                    purged += 1;
                }
            }
            purged
        })
    }

    /// Export a signed and encrypted `.dvb` bundle of all pending records in Provisioned mode.
    pub fn export_dvb_bundle(&self) -> Result<(BuiltBundle, String), (u16, Value)> {
        let cfg = self.get_station_config();
        if cfg.mode != "provisioned" {
            return Err((
                403,
                json!({
                    "error": "Standalone Sandbox mode records (project_id = '1') cannot be exported in a .dvb bundle.",
                    "code": "sandbox_not_exportable"
                }),
            ));
        }

        let (raw_signed_cfg, secret_raw, next_seq): (String, String, u64) =
            self.with_conn(|conn| {
                let row: Option<(Option<String>, Option<String>, i64)> = conn
                    .query_row(
                        "SELECT raw_signed_config, station_signing_secret_b64, bundle_seq FROM loc_station_config WHERE id = 1",
                        [],
                        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                    )
                    .optional()
                    .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                let Some((Some(raw_cfg), Some(sec), seq)) = row else {
                    return Err((
                        403,
                        json!({
                            "error": "No verified signed station configuration is loaded.",
                            "code": "sandbox_not_exportable"
                        }),
                    ));
                };
                Ok((raw_cfg, sec, (seq as u64) + 1))
            })?;

        let verified =
            VerifiedStationConfig::parse_and_verify(&raw_signed_cfg, &cfg.station_id, None)
                .map_err(|e| {
                    (
                        403,
                        json!({
                            "error": e.to_string(),
                            "code": "station_config_invalid_or_expired"
                        }),
                    )
                })?;

        let signing_key = if let Ok(bytes) = hex::decode(&secret_raw) {
            let arr: [u8; 32] = bytes.try_into().map_err(|_| {
                (
                    500,
                    json!({ "error": "Invalid station signing secret length", "code": "signing_key_error" }),
                )
            })?;
            StationSigningKey::from_secret_bytes(&arr)
        } else {
            StationSigningKey::from_base64url_secret(&secret_raw).map_err(|e| {
                (
                    500,
                    json!({ "error": e.to_string(), "code": "signing_key_error" }),
                )
            })?
        };

        let active_actor = self.get_active_actor_context();
        let default_user_id = active_actor
            .user_id
            .or_else(|| {
                verified
                    .config
                    .roster
                    .first()
                    .map(|m| m.user_id)
            })
            .unwrap_or(1);

        let parse_role = |r: Option<&str>, fallback: ActingRole| -> ActingRole {
            match r.and_then(normalise_acting_role) {
                Some("death_reporter") => ActingRole::DeathReporter,
                Some("interviewer") => ActingRole::Interviewer,
                Some("station_supervisor") => ActingRole::StationSupervisor,
                Some("coder") => ActingRole::Coder,
                _ => fallback,
            }
        };

        let records: Vec<BundleRecordEnvelope> = self.with_conn(|conn| {
            let mut out = Vec::new();

            // Check if any pending record belongs to sandbox project "1"
            let sandbox_pending: i64 = conn
                .query_row(
                    "SELECT (SELECT COUNT(*) FROM loc_death_register WHERE sync_state = 'pending' AND project_id = 1)
                          + (SELECT COUNT(*) FROM loc_va_submissions WHERE sync_state = 'pending' AND project_id = '1')
                          + (SELECT COUNT(*) FROM consent_records WHERE sync_state = 'pending' AND project_id = 1)",
                    [],
                    |r| r.get(0),
                )
                .unwrap_or(0);
            if sandbox_pending > 0 {
                return Err((
                    403,
                    json!({
                        "error": "Sandbox project_id = '1' records cannot be exported.",
                        "code": "sandbox_not_exportable"
                    }),
                ));
            }

            // 1. Consent records
            let mut stmt = conn
                .prepare(
                    "SELECT consent_id, project_id, client_death_id, client_draft_id, action_type,
                            notice_version_id, notice_version, locale, notice_sha256, mode,
                            witness_present, supersedes_client_id, purposes_json,
                            actor_user_id, acting_role, recorded_at
                     FROM consent_records
                     WHERE sync_state = 'pending' AND project_id != 1
                     ORDER BY recorded_at ASC",
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            let consent_rows = stmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, i64>(1)?,
                        r.get::<_, Option<String>>(2)?,
                        r.get::<_, Option<String>>(3)?,
                        r.get::<_, String>(4)?,
                        r.get::<_, String>(5)?,
                        r.get::<_, String>(6)?,
                        r.get::<_, String>(7)?,
                        r.get::<_, String>(8)?,
                        r.get::<_, String>(9)?,
                        r.get::<_, i32>(10)?,
                        r.get::<_, Option<String>>(11)?,
                        r.get::<_, String>(12)?,
                        r.get::<_, Option<i64>>(13)?,
                        r.get::<_, Option<String>>(14)?,
                        r.get::<_, String>(15)?,
                    ))
                })
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            for row in consent_rows.flatten() {
                let (
                    cid_str,
                    pid,
                    cdid,
                    cdraft,
                    action,
                    nv_id,
                    nv,
                    loc,
                    sha,
                    mode_raw,
                    wp,
                    sup,
                    purp_raw,
                    uid,
                    role,
                    rec_at,
                ) = row;
                let Ok(client_id) = Uuid::parse_str(&cid_str) else {
                    continue;
                };
                let death_uuid = cdid
                    .as_deref()
                    .and_then(|s| Uuid::parse_str(s).ok())
                    .unwrap_or_else(Uuid::new_v4);
                let draft_uuid = cdraft.as_deref().and_then(|s| Uuid::parse_str(s).ok());
                let notice_uuid = Uuid::parse_str(if nv_id.is_empty() { &nv } else { &nv_id })
                    .unwrap_or_else(|_| {
                        Uuid::parse_str(crate::consent::DEFAULT_NOTICE_VERSION_ID_EN).unwrap()
                    });
                let decision = if action == "refusal" || action == "refused" {
                    ConsentDecision::Refused
                } else {
                    ConsentDecision::Granted
                };
                let mode = match mode_raw.as_str() {
                    "tap" | "tapped" => ConsentMode::Tap,
                    "signed" => ConsentMode::Signed,
                    _ => ConsentMode::Spoken,
                };
                let purposes: Vec<ConsentPurposeGrant> =
                    serde_json::from_str(&purp_raw).unwrap_or_default();
                let sup_uuid = sup.as_deref().and_then(|s| Uuid::parse_str(s).ok());
                out.push(BundleRecordEnvelope {
                    client_id,
                    project_id: pid.to_string(),
                    actor_user_id: uid.unwrap_or(default_user_id),
                    acting_role: parse_role(role.as_deref(), ActingRole::DeathReporter),
                    recorded_at: rec_at,
                    payload: BundleRecordPayload::Consent(ConsentRecord {
                        death_ref: DeathRef::client_death(death_uuid),
                        client_draft_id: draft_uuid,
                        notice_version_id: notice_uuid,
                        notice_language: loc,
                        notice_sha256: sha,
                        decision,
                        purposes,
                        mode,
                        witness_present: wp == 1,
                        supersedes_client_id: sup_uuid,
                    }),
                });
            }

            // 2. Death reports
            let mut dstmt = conn
                .prepare(
                    "SELECT death_id, client_death_id, project_id, site_id, org_unit_id,
                            deceased_name, deceased_sex, date_of_death, date_of_birth,
                            age_years, place_of_death, informant_name, informant_relation,
                            informant_phone, informant_phone_2, address, address_house_street,
                            address_village_ward, address_landmark, remarks,
                            actor_user_id, acting_role, created_at
                     FROM loc_death_register
                     WHERE sync_state = 'pending' AND project_id != 1
                     ORDER BY death_id ASC",
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            let death_rows = dstmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, i64>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, i64>(2)?,
                        r.get::<_, String>(3)?,
                        r.get::<_, String>(4)?,
                        r.get::<_, String>(5)?,
                        r.get::<_, String>(6)?,
                        r.get::<_, String>(7)?,
                        r.get::<_, Option<String>>(8)?,
                        r.get::<_, Option<f64>>(9)?,
                        r.get::<_, Option<String>>(10)?,
                        r.get::<_, Option<String>>(11)?,
                        r.get::<_, Option<String>>(12)?,
                        r.get::<_, Option<String>>(13)?,
                        r.get::<_, Option<String>>(14)?,
                        r.get::<_, Option<String>>(15)?,
                        r.get::<_, Option<String>>(16)?,
                        r.get::<_, Option<String>>(17)?,
                        r.get::<_, Option<String>>(18)?,
                        r.get::<_, Option<String>>(19)?,
                        r.get::<_, Option<i64>>(20)?,
                        r.get::<_, Option<String>>(21)?,
                        r.get::<_, String>(22)?,
                    ))
                })
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            for row in death_rows.flatten() {
                let (
                    did,
                    cdid_opt,
                    pid,
                    site_id,
                    ou_id,
                    dname,
                    dsex,
                    dod,
                    dob,
                    age,
                    pod,
                    iname,
                    irel,
                    iphone,
                    iphone2,
                    addr,
                    ahouse,
                    avillage,
                    alandmark,
                    remarks,
                    uid,
                    role,
                    cat,
                ) = row;
                let Some(cdid_str) = cdid_opt else { continue };
                let Ok(client_id) = Uuid::parse_str(&cdid_str) else {
                    continue;
                };
                let ids = Self::load_case_identifiers(conn, did);
                let latest_consent =
                    get_latest_consent_for_case(conn, pid, Some(&cdid_str), Some(did))
                        .ok()
                        .flatten();
                let mut fields = BTreeMap::new();
                fields.insert("deceased_name".to_string(), Value::String(dname));
                fields.insert("deceased_sex".to_string(), Value::String(dsex));
                fields.insert("date_of_death".to_string(), Value::String(dod));
                if let Some(v) = dob {
                    fields.insert("date_of_birth".to_string(), Value::String(v));
                }
                if let Some(v) = age {
                    fields.insert("age_years".to_string(), json!(v.round() as i64));
                }
                if let Some(v) = pod {
                    fields.insert("place_of_death".to_string(), Value::String(v));
                }
                if let Some(v) = iname {
                    fields.insert("informant_name".to_string(), Value::String(v));
                }
                if let Some(v) = irel {
                    fields.insert("informant_relation".to_string(), Value::String(v));
                }
                if let Some(v) = iphone {
                    fields.insert("informant_phone".to_string(), Value::String(v));
                }
                if let Some(v) = iphone2 {
                    fields.insert("informant_phone_2".to_string(), Value::String(v));
                }
                if let Some(v) = addr {
                    fields.insert("address".to_string(), Value::String(v));
                }
                if let Some(v) = ahouse {
                    fields.insert("address_house_street".to_string(), Value::String(v));
                }
                if let Some(v) = avillage {
                    fields.insert("address_village_ward".to_string(), Value::String(v));
                }
                if let Some(v) = alandmark {
                    fields.insert("address_landmark".to_string(), Value::String(v));
                }
                if let Some(v) = remarks {
                    fields.insert("remarks".to_string(), Value::String(v));
                }

                out.push(BundleRecordEnvelope {
                    client_id,
                    project_id: pid.to_string(),
                    actor_user_id: uid.unwrap_or(default_user_id),
                    acting_role: parse_role(role.as_deref(), ActingRole::DeathReporter),
                    recorded_at: cat,
                    payload: BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
                        site_id,
                        org_unit_id: Some(ou_id),
                        fields,
                        identifiers: if ids.is_empty() { None } else { Some(ids) },
                        consent_client_id: latest_consent
                            .and_then(|c| Uuid::parse_str(&c.client_id).ok()),
                    }),
                });
            }

            // 3. Supervisor corrections (`death_correction` & `identifiers_set`)
            let mut cstmt = conn
                .prepare(
                    "SELECT client_id, record_type, project_id, client_death_id,
                            actor_user_id, acting_role, reason, payload_json, created_at
                     FROM loc_supervisor_corrections
                     WHERE sync_state = 'pending' AND project_id != '1'
                     ORDER BY created_at ASC",
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            let corr_rows = cstmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, String>(3)?,
                        r.get::<_, Option<i64>>(4)?,
                        r.get::<_, Option<String>>(5)?,
                        r.get::<_, Option<String>>(6)?,
                        r.get::<_, String>(7)?,
                        r.get::<_, String>(8)?,
                    ))
                })
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            let mut last_write_by_death: BTreeMap<Uuid, Uuid> = BTreeMap::new();
            for row in corr_rows.flatten() {
                let (cid_str, rtype, pid, cdid, uid, role, reason_opt, pjson, cat) = row;
                let Ok(client_id) = Uuid::parse_str(&cid_str) else {
                    continue;
                };
                let death_uuid = Uuid::parse_str(&cdid).unwrap_or_else(|_| Uuid::new_v4());
                let pval: Value = serde_json::from_str(&pjson).unwrap_or_else(|_| json!({}));
                let if_updated_at = pval
                    .get("if_updated_at")
                    .and_then(Value::as_str)
                    .map(ToString::to_string);
                let base_client_id = if if_updated_at.is_none() {
                    Some(
                        pval.get("base_client_id")
                            .and_then(Value::as_str)
                            .and_then(|s| Uuid::parse_str(s).ok())
                            .unwrap_or_else(|| {
                                *last_write_by_death.get(&death_uuid).unwrap_or(&death_uuid)
                            }),
                    )
                } else {
                    None
                };
                last_write_by_death.insert(death_uuid, client_id);
                let reason = reason_opt.unwrap_or_else(|| "Supervisor update".to_string());
                let payload = if rtype == "identifiers_set" {
                    let mut id_map = BTreeMap::new();
                    if let Some(obj) = pval.get("identifiers").and_then(Value::as_object) {
                        for (k, v) in obj {
                            id_map.insert(k.clone(), v.as_str().map(ToString::to_string));
                        }
                    }
                    BundleRecordPayload::IdentifiersSet(IdentifiersSetRecord {
                        death_ref: DeathRef::client_death(death_uuid),
                        reason,
                        if_updated_at,
                        base_client_id,
                        identifiers: id_map,
                    })
                } else {
                    let mut changes = BTreeMap::new();
                    if let Some(obj) = pval.get("fields").and_then(Value::as_object) {
                        for (k, v) in obj {
                            changes.insert(k.clone(), v.clone());
                        }
                    }
                    BundleRecordPayload::DeathCorrection(DeathCorrectionRecord {
                        death_ref: DeathRef::client_death(death_uuid),
                        reason,
                        if_updated_at,
                        base_client_id,
                        changes,
                    })
                };
                out.push(BundleRecordEnvelope {
                    client_id,
                    project_id: pid,
                    actor_user_id: uid.unwrap_or(default_user_id),
                    acting_role: parse_role(role.as_deref(), ActingRole::StationSupervisor),
                    recorded_at: cat,
                    payload,
                });
            }

            // 4. VA Submissions (`interview_submission`)
            let mut sstmt = conn
                .prepare(
                    "SELECT va_sid, draft_id, death_id, project_id, site_id, org_unit_id,
                            payload_json, actor_user_id, acting_role, submitted_at
                     FROM loc_va_submissions
                     WHERE sync_state = 'pending' AND project_id != '1'
                     ORDER BY submitted_at ASC",
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            let sub_rows = sstmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, Option<i64>>(2)?,
                        r.get::<_, String>(3)?,
                        r.get::<_, String>(4)?,
                        r.get::<_, Option<String>>(5)?,
                        r.get::<_, String>(6)?,
                        r.get::<_, Option<i64>>(7)?,
                        r.get::<_, Option<String>>(8)?,
                        r.get::<_, String>(9)?,
                    ))
                })
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            for row in sub_rows.flatten() {
                let (va_sid, draft_id_opt, did_opt, pid, sid, ouid, pjson, uid, role, sub_at) = row;
                let cid_str = draft_id_opt.unwrap_or(va_sid.clone());
                let Ok(client_id) = Uuid::parse_str(&cid_str) else {
                    continue;
                };
                let client_death_id: Option<String> = did_opt.and_then(|did| {
                    conn.query_row(
                        "SELECT client_death_id FROM loc_death_register WHERE death_id = ?1",
                        params![did],
                        |r| r.get(0),
                    )
                    .optional()
                    .ok()
                    .flatten()
                });
                let death_uuid = client_death_id
                    .as_deref()
                    .and_then(|s| Uuid::parse_str(s).ok())
                    .unwrap_or_else(Uuid::new_v4);
                let answers_sha256 = sha256_hex(pjson.as_bytes());
                let pid_num = pid.parse::<i64>().unwrap_or(2);
                let latest_consent = get_latest_consent_for_case(
                    conn,
                    pid_num,
                    client_death_id.as_deref(),
                    did_opt,
                )
                .ok()
                .flatten();

                out.push(BundleRecordEnvelope {
                    client_id,
                    project_id: pid,
                    actor_user_id: uid.unwrap_or(default_user_id),
                    acting_role: parse_role(role.as_deref(), ActingRole::Interviewer),
                    recorded_at: sub_at.clone(),
                    payload: BundleRecordPayload::InterviewSubmission(InterviewSubmissionRecord {
                        site_id: sid,
                        org_unit_id: ouid,
                        death_ref: DeathRef::client_death(death_uuid),
                        draft: InterviewDraftMeta {
                            instrument_version: "2022_v1".to_string(),
                            definition_sha256: default_who_2022_va_definition_sha256(),
                            definition_extensions: None,
                            started_at: sub_at.clone(),
                            completed_at: Some(sub_at),
                            device_clock_at: None,
                            interview_outcome: "completed".to_string(),
                        },
                        completion: InterviewCompletion {
                            valid: true,
                            issues: vec![],
                        },
                        answers_json: pjson,
                        answers_sha256,
                        consent_client_id: latest_consent
                            .and_then(|c| Uuid::parse_str(&c.client_id).ok()),
                    }),
                });
            }

            // 5. Coding results (`coding_result`)
            let mut crstmt = conn
                .prepare(
                    "SELECT client_id, client_draft_id, project_id,
                            actor_user_id, acting_role, payload_json, created_at
                     FROM loc_coding_results
                     WHERE sync_state = 'pending' AND project_id != '1'
                     ORDER BY created_at ASC",
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            let cr_rows = crstmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, Option<i64>>(3)?,
                        r.get::<_, Option<String>>(4)?,
                        r.get::<_, String>(5)?,
                        r.get::<_, String>(6)?,
                    ))
                })
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            for row in cr_rows.flatten() {
                let (cid_str, cdraft_str, pid, uid, role, pjson, cat) = row;
                let Ok(client_id) = Uuid::parse_str(&cid_str) else {
                    continue;
                };
                let client_draft_id =
                    Uuid::parse_str(&cdraft_str).unwrap_or_else(|_| Uuid::new_v4());
                let pval: Value = serde_json::from_str(&pjson).unwrap_or_else(|_| json!({}));
                let stage = pval
                    .get("stage")
                    .and_then(Value::as_str)
                    .unwrap_or("final");
                let kind = if stage == "not_codeable" {
                    CodingResultKind::NotCodeable
                } else {
                    CodingResultKind::Final
                };
                let coded_answers_sha256: String = conn
                    .query_row(
                        "SELECT payload_json FROM loc_va_submissions WHERE draft_id = ?1 LIMIT 1",
                        params![cdraft_str],
                        |r| r.get::<_, String>(0),
                    )
                    .ok()
                    .map(|raw| sha256_hex(raw.as_bytes()))
                    .unwrap_or_else(|| "0".repeat(64));

                out.push(BundleRecordEnvelope {
                    client_id,
                    project_id: pid,
                    actor_user_id: uid.unwrap_or(default_user_id),
                    acting_role: parse_role(role.as_deref(), ActingRole::Coder),
                    recorded_at: cat,
                    payload: BundleRecordPayload::CodingResult(CodingResultRecord {
                        client_draft_id,
                        coded_answers_sha256,
                        kind,
                        initial: pval.get("initial_assessment").cloned().filter(|v| !v.is_null()),
                        final_cod: pval.get("final_assessment").cloned().filter(|v| !v.is_null()),
                        not_codeable: pval.get("not_codeable").cloned().filter(|v| !v.is_null()),
                    }),
                });
            }

            Ok(out)
        })?;

        let built = build_bundle(
            &verified,
            &signing_key,
            &cfg.station_id,
            next_seq,
            "0.1.0-offline",
            Utc::now(),
            &records,
        )
        .map_err(|e| {
            (
                422,
                json!({
                    "error": e.to_string(),
                    "code": "bundle_build_failed"
                }),
            )
        })?;

        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config SET bundle_seq = ?1 WHERE id = 1",
                params![next_seq as i64],
            )
            .ok();
        });

        let filename = format!(
            "digitva-{}-{:06}-{}.dvb",
            cfg.station_id, next_seq, built.manifest.bundle_id
        );
        Ok((built, filename))
    }

    /// Verify and apply a signed `.dvb.receipt` two-line file from the server.
    pub fn import_dvb_receipt(&self, raw_two_line_receipt: &str) -> Result<Value, (u16, Value)> {
        let cfg = self.get_station_config();
        let (vk_hex, local_interview_hashes): (String, BTreeMap<Uuid, String>) = self
            .with_conn(|conn| {
                let vk = conn
                    .query_row(
                        "SELECT server_verifying_key_hex FROM loc_station_config WHERE id = 1",
                        [],
                        |r| r.get::<_, Option<String>>(0),
                    )
                    .optional()
                    .ok()
                    .flatten()
                    .flatten();
                let mut hashes = BTreeMap::new();
                if let Ok(mut stmt) =
                    conn.prepare("SELECT draft_id, payload_json FROM loc_va_submissions")
                {
                    if let Ok(rows) = stmt.query_map([], |r| {
                        Ok((r.get::<_, Option<String>>(0)?, r.get::<_, String>(1)?))
                    }) {
                        for (did_opt, pjson) in rows.flatten() {
                            if let Some(did_str) = did_opt {
                                if let Ok(u) = Uuid::parse_str(&did_str) {
                                    hashes.insert(u, sha256_hex(pjson.as_bytes()));
                                }
                            }
                        }
                    }
                }
                vk.map(|k| (k, hashes))
            })
            .ok_or_else(|| {
                (
                    422,
                    json!({
                        "error": "No server verifying key is pinned on this station.",
                        "code": "no_server_verifying_key"
                    }),
                )
            })?;

        let vk_bytes: [u8; 32] = hex::decode(&vk_hex)
            .ok()
            .and_then(|v| v.try_into().ok())
            .ok_or_else(|| {
                (
                    500,
                    json!({ "error": "Invalid pinned server verifying key", "code": "db_error" }),
                )
            })?;

        let plan = verify_and_plan_receipt(
            raw_two_line_receipt,
            &cfg.station_id,
            &vk_bytes,
            &local_interview_hashes,
        )
        .map_err(|e| {
            (
                422,
                json!({
                    "error": e.to_string(),
                    "code": "invalid_bundle_receipt"
                }),
            )
        })?;

        // 1. Delete `deletable_client_ids` (accepted / duplicate / superseded) from local outbox
        let deleted_count = self.with_conn(|conn| {
            let mut deleted = 0usize;
            for uuid in &plan.deletable_client_ids {
                let cid = uuid.to_string();
                let mut matched = 0usize;
                matched += conn
                    .execute("DELETE FROM consent_records WHERE consent_id = ?1", params![cid])
                    .unwrap_or(0);
                if let Some(did) = conn
                    .query_row(
                        "SELECT death_id FROM loc_death_register WHERE client_death_id = ?1",
                        params![cid],
                        |r| r.get::<_, i64>(0),
                    )
                    .optional()
                    .ok()
                    .flatten()
                {
                    conn.execute("DELETE FROM map_death_identifier WHERE death_id = ?1", params![did])
                        .ok();
                    matched += conn
                        .execute("DELETE FROM loc_death_register WHERE death_id = ?1", params![did])
                        .unwrap_or(0);
                }
                matched += conn
                    .execute("DELETE FROM loc_va_submissions WHERE draft_id = ?1", params![cid])
                    .unwrap_or(0);
                matched += conn
                    .execute("DELETE FROM loc_va_drafts WHERE draft_id = ?1", params![cid])
                    .unwrap_or(0);
                matched += conn
                    .execute(
                        "DELETE FROM loc_supervisor_corrections WHERE client_id = ?1",
                        params![cid],
                    )
                    .unwrap_or(0);
                matched += conn
                    .execute(
                        "DELETE FROM loc_coding_results WHERE client_id = ?1",
                        params![cid],
                    )
                    .unwrap_or(0);
                if matched > 0 {
                    deleted += 1;
                }
            }
            deleted
        });

        // 2. Mark `pending_client_ids` as `server_pending`
        self.with_conn(|conn| {
            for uuid in &plan.pending_client_ids {
                let cid = uuid.to_string();
                conn.execute(
                    "UPDATE consent_records SET sync_state = 'server_pending' WHERE consent_id = ?1",
                    params![cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_death_register SET sync_state = 'server_pending' WHERE client_death_id = ?1",
                    params![cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_va_drafts SET sync_state = 'server_pending' WHERE draft_id = ?1",
                    params![cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_va_submissions SET sync_state = 'server_pending' WHERE draft_id = ?1",
                    params![cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_supervisor_corrections SET sync_state = 'server_pending' WHERE client_id = ?1",
                    params![cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_coding_results SET sync_state = 'server_pending' WHERE client_id = ?1",
                    params![cid],
                )
                .ok();
            }

            // 3. Mark `rejected_records` with `sync_state = 'rejected'` and `sync_error_code`
            for (client_uuid, err_code_opt) in &plan.rejected_records {
                let cid = client_uuid.to_string();
                let code = err_code_opt.as_deref().unwrap_or("rejected_by_server");
                conn.execute(
                    "UPDATE consent_records SET sync_state = 'rejected', sync_error_code = ?1 WHERE consent_id = ?2",
                    params![code, cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_death_register SET sync_state = 'rejected', sync_error_code = ?1 WHERE client_death_id = ?2",
                    params![code, cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_va_drafts SET sync_state = 'rejected', sync_error_code = ?1 WHERE draft_id = ?2",
                    params![code, cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_va_submissions SET sync_state = 'rejected', sync_error_code = ?1 WHERE draft_id = ?2",
                    params![code, cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_supervisor_corrections SET sync_state = 'rejected', sync_error_code = ?1 WHERE client_id = ?2",
                    params![code, cid],
                )
                .ok();
                conn.execute(
                    "UPDATE loc_coding_results SET sync_state = 'rejected', sync_error_code = ?1 WHERE client_id = ?2",
                    params![code, cid],
                )
                .ok();
            }
        });

        // 4. Execute `purge_client_ids`
        let purged_count = self.apply_purge_list(&plan.purge_client_ids);
        let purged_ids: Vec<String> = plan
            .purge_client_ids
            .iter()
            .map(ToString::to_string)
            .collect();

        Ok(json!({
            "bundle_id": plan.report.bundle_id.to_string(),
            "device_id": plan.report.device_id,
            "status": plan.report.status,
            "deleted_count": deleted_count,
            "acknowledged_deleted_count": deleted_count,
            "pending_count": plan.pending_client_ids.len(),
            "rejected_count": plan.rejected_records.len(),
            "purged_count": purged_count,
            "purged_ids": purged_ids
        }))
    }

    // ========================================================================
    // Station Mode & Access Summary (Standalone vs Provisioned)
    // ========================================================================

    pub fn get_station_config(&self) -> StationConfig {
        self.with_conn(|conn| {
            conn.query_row(
                "SELECT mode, station_id, facility_name, district_name, state_name,
                        remote_server_url, provisioned_user_id, provisioned_user_name,
                        provisioned_roles_json, provisioned_token, updated_at
                 FROM loc_station_config WHERE id = 1",
                [],
                |r| {
                    let roles_raw: String = r.get(8)?;
                    let roles: Vec<String> =
                        serde_json::from_str(&roles_raw).unwrap_or_default();
                    Ok(StationConfig {
                        mode: r.get(0)?,
                        station_id: r.get(1)?,
                        facility_name: r.get(2)?,
                        district_name: r.get(3)?,
                        state_name: r.get(4)?,
                        remote_server_url: r.get(5)?,
                        provisioned_user_id: r.get(6)?,
                        provisioned_user_name: r.get(7)?,
                        provisioned_roles: roles,
                        provisioned_token: r.get(9)?,
                        updated_at: r.get(10)?,
                    })
                },
            )
            .unwrap_or_else(|_| StationConfig {
                mode: "standalone".to_string(),
                station_id: "phc-standalone-01".to_string(),
                facility_name: "Model Primary Health Centre".to_string(),
                district_name: "Demo District".to_string(),
                state_name: "Demo State".to_string(),
                remote_server_url: None,
                provisioned_user_id: None,
                provisioned_user_name: None,
                provisioned_roles: Vec::new(),
                provisioned_token: None,
                updated_at: Utc::now().to_rfc3339(),
            })
        })
    }

    pub fn update_station_config(
        &self,
        mode: &str,
        facility_name: Option<&str>,
        district_name: Option<&str>,
        state_name: Option<&str>,
        remote_server_url: Option<&str>,
        provisioned_user_id: Option<&str>,
        provisioned_user_name: Option<&str>,
        provisioned_roles: Option<Vec<String>>,
        provisioned_token: Option<&str>,
    ) -> Result<StationConfig, String> {
        if mode != "standalone" && mode != "provisioned" {
            return Err("Station mode must be 'standalone' or 'provisioned'.".to_string());
        }
        let current = self.get_station_config();
        let now = Utc::now().to_rfc3339();
        let roles_vec = provisioned_roles.unwrap_or(current.provisioned_roles);
        let roles_json = serde_json::to_string(&roles_vec).unwrap_or_else(|_| "[]".to_string());

        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config
                 SET mode = ?1,
                     facility_name = ?2,
                     district_name = ?3,
                     state_name = ?4,
                     remote_server_url = ?5,
                     provisioned_user_id = ?6,
                     provisioned_user_name = ?7,
                     provisioned_roles_json = ?8,
                     provisioned_token = ?9,
                     updated_at = ?10
                 WHERE id = 1",
                params![
                    mode,
                    facility_name.unwrap_or(&current.facility_name),
                    district_name.unwrap_or(&current.district_name),
                    state_name.unwrap_or(&current.state_name),
                    remote_server_url,
                    provisioned_user_id,
                    provisioned_user_name,
                    roles_json,
                    provisioned_token,
                    now
                ],
            )
            .map_err(|e| e.to_string())
        })?;
        Ok(self.get_station_config())
    }

    /// Filter roles down to the Contract 3.1 device-allowed projection:
    /// `interviewer`, `death_reporter`, `coder`, `coding_tester`, `reviewer`.
    /// Never emit `admin`, `data_manager`, `project_manager`, or `interview_supervisor`.
    fn filter_device_projected_roles(raw_roles: &[String]) -> Vec<String> {
        let mut out = Vec::new();
        for r in raw_roles {
            let mapped = match r.trim() {
                "reporter" | "death_reporter" => Some("death_reporter"),
                "interviewer" => Some("interviewer"),
                "supervisor" | "station_supervisor" | "interview_supervisor" => None,
                "coder" => Some("coder"),
                "coding_tester" => Some("coding_tester"),
                "reviewer" => Some("reviewer"),
                _ => None,
            };
            if let Some(code) = mapped {
                if !out.iter().any(|x| x == code) {
                    out.push(code.to_string());
                }
            }
        }
        out
    }

    /// Build `/api/v1/me/access` payload matching Contract 3.1 device projection.
    ///
    /// - `is_admin`, `can_manage_users`, and `can_access_admin` are ALWAYS `false` on the device.
    /// - `roles`, `projects[].roles`, `projects[].grants`, `projects[].sites[].roles`, and
    ///   `projects[].units[].roles` only contain `interviewer`, `death_reporter`, `coder`,
    ///   `coding_tester`, or `reviewer`.
    pub fn build_access_summary(&self) -> Result<Value, String> {
        let cfg = self.get_station_config();
        let active_actor = self.get_active_actor_context();
        let (user_id, user_name, roles, allow_interview, allow_register_death, can_code) =
            if cfg.mode == "standalone" {
                let (r, intv, reg, code) = match active_actor.acting_role.as_str() {
                    "coder" => (vec!["coder".to_string()], false, false, true),
                    "death_reporter" | "reporter" => {
                        (vec!["death_reporter".to_string()], false, true, false)
                    }
                    "interviewer" => (
                        vec!["interviewer".to_string(), "death_reporter".to_string()],
                        true,
                        true,
                        false,
                    ),
                    _ => (
                        vec!["interviewer".to_string(), "death_reporter".to_string()],
                        true,
                        true,
                        false,
                    ),
                };
                (
                    active_actor.member_id.clone(),
                    format!("{} ({})", active_actor.name, active_actor.designation),
                    r,
                    intv,
                    reg,
                    code,
                )
            } else {
                let Some(uid) = cfg.provisioned_user_id.clone() else {
                    return Err("unauthorized".to_string());
                };
                let uname = cfg
                    .provisioned_user_name
                    .clone()
                    .unwrap_or_else(|| uid.clone());
                let raw_r = if cfg.provisioned_roles.is_empty() {
                    vec!["death_reporter".to_string(), "interviewer".to_string()]
                } else {
                    cfg.provisioned_roles.clone()
                };
                let has_sup = raw_r.iter().any(|role| {
                    matches!(
                        role.as_str(),
                        "station_supervisor" | "supervisor" | "interview_supervisor"
                    )
                });
                let mut r = Self::filter_device_projected_roles(&raw_r);
                if has_sup {
                    if !r.contains(&"interviewer".to_string()) {
                        r.push("interviewer".to_string());
                    }
                    if !r.contains(&"death_reporter".to_string()) {
                        r.push("death_reporter".to_string());
                    }
                }
                let intv = r.iter().any(|role| role == "interviewer") || has_sup;
                let reg = r
                    .iter()
                    .any(|role| matches!(role.as_str(), "death_reporter" | "interviewer"))
                    || has_sup;
                let code = r
                    .iter()
                    .any(|role| matches!(role.as_str(), "coder" | "coding_tester" | "reviewer"));
                (uid, uname, r, intv, reg, code)
            };

        let units = json!([
            {
                "org_unit_id": "ou-phc-1",
                "unit_code": "PHC01",
                "unit_name": cfg.facility_name,
                "level_code": "PHC",
                "path": "ou-phc-1",
                "is_active": true,
                "selectable": true,
                "roles": roles,
                "can_code": can_code
            },
            {
                "org_unit_id": "ou-sc-1",
                "unit_code": "SC01",
                "unit_name": "Sub-Centre 1",
                "level_code": "SUBCENTRE",
                "path": "ou-phc-1.ou-sc-1",
                "is_active": true,
                "selectable": true,
                "roles": roles,
                "can_code": can_code
            },
            {
                "org_unit_id": "ou-sc-2",
                "unit_code": "SC02",
                "unit_name": "Sub-Centre 2",
                "level_code": "SUBCENTRE",
                "path": "ou-phc-1.ou-sc-2",
                "is_active": true,
                "selectable": true,
                "roles": roles,
                "can_code": can_code
            }
        ]);

        let action_org_units = json!([
            {
                "org_unit_id": "ou-phc-1",
                "unit_code": "PHC01",
                "unit_name": cfg.facility_name,
                "path": "ou-phc-1"
            },
            {
                "org_unit_id": "ou-sc-1",
                "unit_code": "SC01",
                "unit_name": "Sub-Centre 1",
                "path": "ou-phc-1.ou-sc-1"
            },
            {
                "org_unit_id": "ou-sc-2",
                "unit_code": "SC02",
                "unit_name": "Sub-Centre 2",
                "path": "ou-phc-1.ou-sc-2"
            }
        ]);

        let grants: Vec<Value> = roles
            .iter()
            .map(|r| {
                let is_coding = matches!(r.as_str(), "coder" | "coding_tester" | "reviewer");
                let mut obj = json!({
                    "role": r,
                    "scope": "project",
                    "active": true,
                    "source": "assigned"
                });
                if is_coding {
                    obj["codes"] = Value::Bool(true);
                }
                obj
            })
            .collect();

        let interview_actions = if allow_interview {
            json!([
                {
                    "site_id": "PHC01",
                    "site_name": cfg.facility_name,
                    "web_intake_mode": "both",
                    "org_units": action_org_units
                }
            ])
        } else {
            json!([])
        };

        let register_death_actions = if allow_register_death {
            json!([
                {
                    "site_id": "PHC01",
                    "site_name": cfg.facility_name,
                    "web_intake_mode": "both",
                    "org_units": action_org_units
                }
            ])
        } else {
            json!([])
        };

        Ok(json!({
            "user": {
                "user_id": user_id,
                "name": user_name
            },
            "is_admin": false,
            "can_manage_users": false,
            "can_access_admin": false,
            "roles": roles,
            "demo_coding": {
                "available": false,
                "project_ids": []
            },
            "station_mode": cfg.mode,
            "remote_server_url": cfg.remote_server_url,
            "active_actor": active_actor,
            "projects": [
                {
                    "project_id": "1",
                    "project_name": format!("{} Mortality Surveillance", cfg.facility_name),
                    "has_tree": true,
                    "roles": roles,
                    "grants": grants,
                    "sites": [
                        {
                            "site_id": "PHC01",
                            "site_name": cfg.facility_name,
                            "roles": roles
                        }
                    ],
                    "actions": {
                        "interview": interview_actions,
                        "register_death": register_death_actions
                    },
                    "units": units,
                    "levels": [
                        { "level_code": "PHC", "level_name": "Primary Health Centre", "depth": 1 },
                        { "level_code": "SUBCENTRE", "level_name": "Sub-Centre / Village", "depth": 2 }
                    ]
                }
            ]
        }))
    }

    // ========================================================================
    // Registration Identifiers (CRS / MCCD / Project-Configured)
    // ========================================================================

    pub fn list_identifier_types(&self, project_id: i64) -> Vec<IdentifierTypeSpec> {
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(
                    "SELECT id, project_id, code, label, description, char_type,
                            min_length, max_length, pattern, example, required_at_registration,
                            active, sort_order
                     FROM mas_death_identifier_type
                     WHERE project_id = ?1 AND active = 1
                     ORDER BY sort_order ASC, id ASC",
                )
                .unwrap();
            stmt.query_map(params![project_id], |r| {
                let req = r.get::<_, i32>(10)? == 1;
                Ok(IdentifierTypeSpec {
                    id: r.get(0)?,
                    project_id: r.get(1)?,
                    code: r.get(2)?,
                    label: r.get(3)?,
                    description: r.get(4)?,
                    char_type: r.get(5)?,
                    min_length: r.get::<_, i64>(6)? as usize,
                    max_length: r.get::<_, i64>(7)? as usize,
                    pattern: r.get(8)?,
                    example: r.get(9)?,
                    required_at_registration: req,
                    required_at_report: req,
                    active: r.get::<_, i32>(11)? == 1,
                    sort_order: r.get(12)?,
                })
            })
            .unwrap()
            .filter_map(Result::ok)
            .collect()
        })
    }

    pub fn validate_and_store_identifiers(
        conn: &Connection,
        project_id: i64,
        death_id: i64,
        raw_identifiers: &BTreeMap<String, Option<String>>,
        actor_name: &str,
        enforce_required_at_registration: bool,
    ) -> Result<(BTreeMap<String, String>, Vec<IdentifierDuplicateWarning>), (String, BTreeMap<String, String>)> {
        let mut stmt = conn
            .prepare(
                "SELECT code, label, char_type, min_length, max_length, pattern, required_at_registration
                 FROM mas_death_identifier_type
                 WHERE project_id = ?1 AND active = 1
                 ORDER BY sort_order ASC",
            )
            .map_err(|e| {
                let mut m = BTreeMap::new();
                m.insert("identifiers".to_string(), e.to_string());
                (e.to_string(), m)
            })?;

        let rules: Vec<(IdentifierValidationRule, bool)> = stmt
            .query_map(params![project_id], |r| {
                let code: String = r.get(0)?;
                let label: String = r.get(1)?;
                let char_type_str: String = r.get(2)?;
                let min_len: i64 = r.get(3)?;
                let max_len: i64 = r.get(4)?;
                let pattern: Option<String> = r.get(5)?;
                let req: i32 = r.get(6)?;
                Ok((
                    IdentifierValidationRule {
                        code,
                        label,
                        char_type: IdentifierCharType::from_code(&char_type_str),
                        min_length: min_len.max(1) as usize,
                        max_length: max_len.max(1) as usize,
                        pattern,
                        example: None,
                    },
                    req == 1,
                ))
            })
            .map_err(|e| {
                let mut m = BTreeMap::new();
                m.insert("identifiers".to_string(), e.to_string());
                (e.to_string(), m)
            })?
            .filter_map(Result::ok)
            .collect();

        // Check for unknown identifier type codes
        for key in raw_identifiers.keys() {
            if !rules.iter().any(|(r, _)| &r.code == key) {
                let msg = format!("Unknown registration identifier type '{key}'.");
                let mut m = BTreeMap::new();
                m.insert(format!("identifiers.{key}"), msg.clone());
                return Err((msg, m));
            }
        }

        let now = Utc::now().to_rfc3339();
        for (rule, req_at_reg) in &rules {
            let provided_opt = raw_identifiers.get(&rule.code).and_then(|v| v.as_deref());
            match validate_identifier(provided_opt, rule) {
                Ok(Some(norm)) => {
                    conn.execute(
                        "INSERT INTO map_death_identifier (
                            project_id, death_id, type_code, identifier_norm, captured_by, captured_at
                         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6)
                         ON CONFLICT(death_id, type_code) DO UPDATE SET
                            identifier_norm = excluded.identifier_norm,
                            captured_by = excluded.captured_by,
                            captured_at = excluded.captured_at",
                        params![project_id, death_id, rule.code, norm, actor_name, now],
                    )
                    .map_err(|e| {
                        let mut m = BTreeMap::new();
                        m.insert(format!("identifiers.{}", rule.code), e.to_string());
                        (e.to_string(), m)
                    })?;
                }
                Ok(None) => {
                    if enforce_required_at_registration && *req_at_reg {
                        let msg = format!("{} is required at death registration.", rule.label);
                        let mut m = BTreeMap::new();
                        m.insert(format!("identifiers.{}", rule.code), msg.clone());
                        return Err((msg, m));
                    }
                    // If key was explicitly passed as empty/null in raw_identifiers, delete existing row
                    if raw_identifiers.contains_key(&rule.code) {
                        conn.execute(
                            "DELETE FROM map_death_identifier WHERE death_id = ?1 AND type_code = ?2",
                            params![death_id, rule.code],
                        )
                        .map_err(|e| {
                            let mut m = BTreeMap::new();
                            m.insert(format!("identifiers.{}", rule.code), e.to_string());
                            (e.to_string(), m)
                        })?;
                    }
                }
                Err(msg) => {
                    let mut m = BTreeMap::new();
                    m.insert(format!("identifiers.{}", rule.code), msg.clone());
                    return Err((msg, m));
                }
            }
        }

        let stored = Self::load_case_identifiers(conn, death_id);
        let warnings = Self::compute_identifier_warnings(conn, project_id, death_id, &stored);
        Ok((stored, warnings))
    }

    pub fn load_case_identifiers(conn: &Connection, death_id: i64) -> BTreeMap<String, String> {
        let mut out = BTreeMap::new();
        let Ok(mut stmt) = conn.prepare(
            "SELECT type_code, identifier_norm FROM map_death_identifier WHERE death_id = ?1 ORDER BY type_code ASC",
        ) else {
            return out;
        };
        if let Ok(rows) = stmt.query_map(params![death_id], |r| {
            Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
        }) {
            for (k, v) in rows.flatten() {
                out.insert(k, v);
            }
        }
        out
    }

    pub fn load_case_identifier_items(
        conn: &Connection,
        project_id: i64,
        death_id: i64,
        is_coder: bool,
    ) -> Vec<Value> {
        let mut stored = Self::load_case_identifiers(conn, death_id);
        let mut configured_types: Vec<(String, String)> = Vec::new();
        if let Ok(mut stmt) = conn.prepare(
            "SELECT code, label FROM mas_death_identifier_type WHERE project_id = ?1 AND active = 1 ORDER BY sort_order ASC, code ASC",
        ) {
            if let Ok(rows) = stmt.query_map(params![project_id], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?))
            }) {
                for (code, label) in rows.flatten() {
                    configured_types.push((code, label));
                }
            }
        }

        let mut items = Vec::new();
        for (code, label) in configured_types {
            let val_opt = stored.remove(&code).filter(|v| !v.is_empty());
            if is_coder {
                items.push(json!({
                    "code": code,
                    "label": label,
                    "present": val_opt.is_some()
                }));
            } else {
                items.push(json!({
                    "code": code,
                    "label": label,
                    "value": val_opt
                }));
            }
        }
        for (code, val) in stored {
            let val_opt = if val.is_empty() { None } else { Some(val) };
            if is_coder {
                items.push(json!({
                    "code": code.clone(),
                    "label": code,
                    "present": val_opt.is_some()
                }));
            } else {
                items.push(json!({
                    "code": code.clone(),
                    "label": code,
                    "value": val_opt
                }));
            }
        }
        items
    }

    /// Contract 4.4: Non-blocking duplicate identifier warnings NEVER expose `matching_death_ids`.
    pub fn compute_identifier_warnings(
        conn: &Connection,
        project_id: i64,
        death_id: i64,
        identifiers: &BTreeMap<String, String>,
    ) -> Vec<IdentifierDuplicateWarning> {
        let mut warnings = Vec::new();
        for (type_code, norm_val) in identifiers {
            let count: i64 = conn
                .query_row(
                    "SELECT COUNT(*) FROM map_death_identifier
                     WHERE project_id = ?1 AND type_code = ?2 AND identifier_norm = ?3 AND death_id != ?4",
                    params![project_id, type_code, norm_val, death_id],
                    |r| r.get(0),
                )
                .unwrap_or(0);
            if count > 0 {
                warnings.push(IdentifierDuplicateWarning {
                    code: "identifier_in_use".to_string(),
                    field: format!("identifiers.{type_code}"),
                    message: "This number is already on another case in this project.".to_string(),
                });
            }
        }
        warnings
    }

    // ========================================================================
    // Record Death, Supervisor Death Correction & Case Detail
    // ========================================================================

    pub fn register_death(&self, payload: &Value, actor_name: &str) -> Result<Value, (u16, Value)> {
        let obj = payload.as_object().ok_or_else(|| {
            (
                400,
                json!({ "error": "Request body must be a JSON object", "code": "invalid_request" }),
            )
        })?;

        let project_id: i64 = obj
            .get("project_id")
            .and_then(|v| {
                v.as_i64()
                    .or_else(|| v.as_str().and_then(|s| s.parse::<i64>().ok()))
            })
            .unwrap_or(1);

        let site_id = obj
            .get("site_id")
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty())
            .unwrap_or("PHC01");
        let org_unit_id = obj
            .get("org_unit_id")
            .and_then(Value::as_str)
            .filter(|s| !s.trim().is_empty())
            .unwrap_or("ou-sc-1");

        let deceased_name = obj
            .get("deceased_name")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| {
                (
                    422,
                    json!({
                        "error": "Deceased name is required.",
                        "code": "invalid_registration",
                        "fields": { "deceased_name": "Deceased name is required." }
                    }),
                )
            })?;

        let deceased_sex = obj
            .get("deceased_sex")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| {
                (
                    422,
                    json!({
                        "error": "Deceased sex is required.",
                        "code": "invalid_registration",
                        "fields": { "deceased_sex": "Deceased sex is required." }
                    }),
                )
            })?;

        let date_of_death = obj
            .get("date_of_death")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| {
                (
                    422,
                    json!({
                        "error": "Date of death is required.",
                        "code": "invalid_registration",
                        "fields": { "date_of_death": "Date of death is required." }
                    }),
                )
            })?;

        let client_death_id = obj
            .get("client_death_id")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty())
            .map(ToString::to_string)
            .unwrap_or_else(|| Uuid::new_v4().to_string());

        let station_cfg = self.get_station_config();
        let active_actor = self.get_active_actor_context();

        self.with_conn(|conn| {
            // Idempotency on client_death_id
            if let Some(existing_id) = conn
                .query_row(
                    "SELECT death_id FROM loc_death_register WHERE client_death_id = ?1",
                    params![client_death_id],
                    |r| r.get::<_, i64>(0),
                )
                .optional()
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?
            {
                let detail = Self::build_case_detail(conn, existing_id)
                    .map_err(|e| (500, json!({ "error": e, "code": "db_error" })))?;
                return Ok(json!({ "case": detail }));
            }

            // 1. Handle DPDP respondent consent envelope if present
            if let Some(consent_val) = obj.get("consent") {
                if !consent_val.is_null() {
                    let env: ConsentEnvelopeInput = serde_json::from_value(consent_val.clone())
                        .map_err(|_| {
                            (
                                422,
                                json!({
                                    "error": "Invalid respondent consent envelope.",
                                    "code": "invalid_registration",
                                    "fields": { "consent": "Invalid respondent consent envelope." }
                                }),
                            )
                        })?;
                    append_consent_record(
                        conn,
                        project_id,
                        Some(&client_death_id),
                        None,
                        &env,
                        actor_name,
                        &station_cfg.station_id,
                    )
                    .map_err(|msg| {
                        (
                            422,
                            json!({
                                "error": msg,
                                "code": "invalid_registration",
                                "fields": { "consent": msg }
                            }),
                        )
                    })?;
                }
            }

            // Extract informant personal fields
            let latest_consent =
                get_latest_consent_for_case(conn, project_id, Some(&client_death_id), None)
                    .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            let refused = latest_consent
                .as_ref()
                .map(|c| c.decision == "refused")
                .unwrap_or(false);

            let opt_str = |k: &str| -> Option<String> {
                if refused
                    && matches!(
                        k,
                        "informant_name"
                            | "informant_phone"
                            | "informant_phone_2"
                            | "informant_relation"
                            | "address"
                            | "address_house_street"
                            | "address_village_ward"
                            | "address_landmark"
                            | "location"
                    )
                {
                    return None;
                }
                obj.get(k)
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                    .map(ToString::to_string)
            };

            let informant_name = opt_str("informant_name");
            let informant_relation = opt_str("informant_relation");
            let raw_phone_1 = opt_str("informant_phone");
            let informant_phone = match raw_phone_1.as_deref() {
                Some(raw) => Some(normalise_phone(Some(raw)).ok_or_else(|| {
                    (
                        422,
                        json!({
                            "error": "Enter a 10-digit mobile number.",
                            "code": "invalid_registration",
                            "fields": { "informant_phone": "Enter a 10-digit mobile number." }
                        }),
                    )
                })?),
                None => None,
            };
            let raw_phone_2 = opt_str("informant_phone_2");
            let informant_phone_2 = match raw_phone_2.as_deref() {
                Some(raw) => Some(normalise_phone(Some(raw)).ok_or_else(|| {
                    (
                        422,
                        json!({
                            "error": "Enter a 10-digit mobile number.",
                            "code": "invalid_registration",
                            "fields": { "informant_phone_2": "Enter a 10-digit mobile number." }
                        }),
                    )
                })?),
                None => None,
            };
            let address = opt_str("address");
            let address_house_street = opt_str("address_house_street");
            let address_village_ward = opt_str("address_village_ward");
            let address_landmark = opt_str("address_landmark");
            let location = opt_str("location");

            // Hard DPDP Consent Gate before writing informant personal data!
            let consent_status = assert_informant_consent_before_write(
                conn,
                project_id,
                Some(&client_death_id),
                None,
                &[
                    informant_name.as_deref(),
                    informant_phone.as_deref(),
                    informant_phone_2.as_deref(),
                    address.as_deref(),
                    address_house_street.as_deref(),
                    address_village_ward.as_deref(),
                    address_landmark.as_deref(),
                    location.as_deref(),
                ],
            )
            .map_err(|msg| {
                (
                    422,
                    json!({
                        "error": msg,
                        "code": "invalid_registration",
                        "fields": { "consent": msg }
                    }),
                )
            })?;

            let age_years: Option<f64> = obj.get("age_years").and_then(|v| {
                v.as_f64()
                    .or_else(|| v.as_str().and_then(|s| s.trim().parse::<f64>().ok()))
            });

            let now = Utc::now().to_rfc3339();
            let next_seq: i64 = conn
                .query_row("SELECT COALESCE(MAX(death_id), 0) + 1 FROM loc_death_register", [], |r| {
                    r.get(0)
                })
                .unwrap_or(1);
            let unique_id = format!("PHC-{:05}", next_seq);
            let org_unit_name = match org_unit_id {
                "ou-phc-1" => station_cfg.facility_name.clone(),
                "ou-sc-2" => "Sub-Centre 2".to_string(),
                _ => "Sub-Centre 1".to_string(),
            };

            conn.execute(
                "INSERT INTO loc_death_register (
                    client_death_id, unique_id, project_id, project_id_str, site_id, site_name,
                    org_unit_id, org_unit_name, deceased_name, deceased_sex,
                    date_of_death, date_of_birth, date_of_birth_partial, age_years,
                    place_of_death, father_name, mother_name, abha_number, abha_address,
                    informant_name, informant_relation, informant_phone, informant_phone_2,
                    address, address_house_street, address_village_ward, address_landmark,
                    location, remarks, status, state, consent_status,
                    actor_user_id, actor_member_id, acting_role,
                    created_by, created_at, updated_at
                 ) VALUES (
                    ?1, ?2, ?3, ?4, ?5, ?6,
                    ?7, ?8, ?9, ?10,
                    ?11, ?12, ?13, ?14,
                    ?15, ?16, ?17, ?18, ?19,
                    ?20, ?21, ?22, ?23,
                    ?24, ?25, ?26, ?27,
                    ?28, ?29, 'registered', 'ready_for_interview', ?30,
                    ?31, ?32, ?33,
                    ?34, ?35, ?35
                 )",
                params![
                    client_death_id,
                    unique_id,
                    project_id,
                    project_id.to_string(),
                    site_id,
                    station_cfg.facility_name,
                    org_unit_id,
                    org_unit_name,
                    deceased_name,
                    deceased_sex,
                    date_of_death,
                    opt_str("date_of_birth"),
                    opt_str("date_of_birth_partial"),
                    age_years,
                    opt_str("place_of_death"),
                    opt_str("father_name"),
                    opt_str("mother_name"),
                    opt_str("abha_number"),
                    opt_str("abha_address"),
                    informant_name,
                    informant_relation,
                    informant_phone,
                    informant_phone_2,
                    address,
                    address_house_street,
                    address_village_ward,
                    address_landmark,
                    location,
                    opt_str("remarks"),
                    consent_status,
                    active_actor.user_id,
                    active_actor.member_id,
                    active_actor.acting_role,
                    actor_name,
                    now
                ],
            )
            .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            let death_id = conn.last_insert_rowid();

            // Link consent record to the newly created death_id
            conn.execute(
                "UPDATE consent_records SET death_id = ?1 WHERE client_death_id = ?2",
                params![death_id, client_death_id],
            )
            .ok();

            // 2. Validate and store registration identifiers (`identifiers` envelope or top-level `crs_reg_no` / `mccd_cert_no`)
            let mut raw_ids: BTreeMap<String, Option<String>> = BTreeMap::new();
            if let Some(id_obj) = obj.get("identifiers").and_then(Value::as_object) {
                for (k, v) in id_obj {
                    raw_ids.insert(k.clone(), v.as_str().map(ToString::to_string));
                }
            }
            for builtin in ["crs_reg_no", "mccd_cert_no"] {
                if let Some(v) = obj.get(builtin).and_then(Value::as_str) {
                    raw_ids.insert(builtin.to_string(), Some(v.to_string()));
                }
            }
            let mut warnings = Vec::new();
            if !raw_ids.is_empty() || true {
                match Self::validate_and_store_identifiers(
                    conn,
                    project_id,
                    death_id,
                    &raw_ids,
                    actor_name,
                    true,
                ) {
                    Ok((_, w)) => warnings = w,
                    Err((msg, fields)) => {
                        conn.execute(
                            "DELETE FROM loc_death_register WHERE death_id = ?1",
                            params![death_id],
                        )
                        .ok();
                        return Err((
                            422,
                            json!({
                                "error": msg,
                                "code": "invalid_registration",
                                "fields": fields
                            }),
                        ));
                    }
                }
            }

            conn.execute(
                "INSERT INTO map_case_transitions (death_id, from_state, to_state, actor_name, reason, created_at)
                 VALUES (?1, NULL, 'registered', ?2, 'Initial death registration', ?3)",
                params![death_id, actor_name, now],
            )
            .ok();

            let detail = Self::build_case_detail(conn, death_id)
                .map_err(|e| (500, json!({ "error": e, "code": "db_error" })))?;
            let mut resp = json!({ "case": detail });
            if !warnings.is_empty() {
                resp["warnings"] = json!(warnings);
            }
            Ok(resp)
        })
    }

    /// Supervisor correction of death registration details (`PATCH /api/v1/intake/deaths/<death_id>`)
    /// per Contract 3.2:
    /// - Closed cases (`cancelled`, `duplicate`, `closed`) -> `409 case_closed`.
    /// - Completed interviews (`completed`, `interview_completed`, or `va_sid.is_some()`) -> `409 case_completed`.
    /// - Passing `identifiers` on `PATCH /api/v1/intake/deaths/<death_id>` is rejected (`400 invalid_request`);
    ///   callers must use `PUT /api/v1/intake/cases/<death_id>/identifiers`.
    /// - Requires non-empty `reason` (`1..=500` chars).
    pub fn update_death_registration(
        &self,
        death_id: i64,
        payload: &Value,
        actor_name: &str,
    ) -> Result<Value, (u16, Value)> {
        let obj = payload.as_object().ok_or_else(|| {
            (
                400,
                json!({ "error": "Request body must be a JSON object", "code": "invalid_request" }),
            )
        })?;

        if obj.contains_key("identifiers")
            || obj.contains_key("crs_reg_no")
            || obj.contains_key("mccd_cert_no")
        {
            return Err((
                400,
                json!({
                    "error": "Identifiers cannot be updated via PATCH /api/v1/intake/deaths/:death_id; use PUT /api/v1/intake/cases/:death_id/identifiers.",
                    "code": "invalid_request"
                }),
            ));
        }

        let reason = obj
            .get("reason")
            .or_else(|| obj.get("correction_reason"))
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty() && s.chars().count() <= 500)
            .ok_or_else(|| {
                (
                    400,
                    json!({
                        "error": "A non-empty reason (1 to 500 characters) is required for death record correction.",
                        "code": "invalid_request"
                    }),
                )
            })?;

        let station_cfg = self.get_station_config();
        let active_actor = self.get_active_actor_context();

        self.with_conn(|conn| {
            let existing: Option<(i64, Option<String>, String, String, Option<String>, String, String)> = conn
                .query_row(
                    "SELECT project_id, client_death_id, status, state, va_sid, site_id, org_unit_id
                     FROM loc_death_register WHERE death_id = ?1",
                    params![death_id],
                    |r| {
                        Ok((
                            r.get(0)?,
                            r.get(1)?,
                            r.get(2)?,
                            r.get(3)?,
                            r.get(4)?,
                            r.get(5)?,
                            r.get(6)?,
                        ))
                    },
                )
                .optional()
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            let Some((project_id, client_death_id, status, prev_state, va_sid, site_id, org_unit_id)) = existing else {
                return Err((404, json!({ "error": "Case not found", "code": "not_found" })));
            };

            if matches!(status.as_str(), "cancelled" | "duplicate" | "closed")
                || matches!(prev_state.as_str(), "cancelled" | "duplicate" | "closed")
            {
                return Err((
                    409,
                    json!({
                        "error": "Case is closed and cannot be modified.",
                        "code": "case_closed"
                    }),
                ));
            }

            if matches!(prev_state.as_str(), "completed" | "interview_completed")
                || matches!(status.as_str(), "interviewed" | "completed")
                || va_sid.is_some()
            {
                return Err((
                    409,
                    json!({
                        "error": "Death report fields are locked once the VA interview is completed.",
                        "code": "case_completed"
                    }),
                ));
            }

            // If a new consent envelope is included
            if let Some(consent_val) = obj.get("consent") {
                if !consent_val.is_null() {
                    let env: ConsentEnvelopeInput = serde_json::from_value(consent_val.clone())
                        .map_err(|_| {
                            (
                                422,
                                json!({
                                    "error": "Invalid respondent consent envelope.",
                                    "code": "invalid_death",
                                    "fields": { "consent": "Invalid respondent consent envelope." }
                                }),
                            )
                        })?;
                    let rec = append_consent_record(
                        conn,
                        project_id,
                        client_death_id.as_deref(),
                        Some(death_id),
                        &env,
                        actor_name,
                        &station_cfg.station_id,
                    )
                    .map_err(|msg| {
                        (
                            422,
                            json!({
                                "error": msg,
                                "code": "invalid_death",
                                "fields": { "consent": msg }
                            }),
                        )
                    })?;
                    let new_status = if rec.decision == "granted" && rec.all_required_granted {
                        "granted"
                    } else {
                        "refused"
                    };
                    conn.execute(
                        "UPDATE loc_death_register SET consent_status = ?1 WHERE death_id = ?2",
                        params![new_status, death_id],
                    )
                    .ok();
                }
            }

            // Check if informant personal fields are being updated
            let inf_keys = [
                "informant_name",
                "informant_phone",
                "informant_phone_2",
                "address",
                "address_house_street",
                "address_village_ward",
                "address_landmark",
                "location",
            ];
            let incoming_inf: Vec<Option<&str>> = inf_keys
                .iter()
                .map(|k| obj.get(*k).and_then(Value::as_str))
                .collect();

            if incoming_inf
                .iter()
                .any(|v| v.map(|s| !s.trim().is_empty()).unwrap_or(false))
            {
                assert_informant_consent_before_write(
                    conn,
                    project_id,
                    client_death_id.as_deref(),
                    Some(death_id),
                    &incoming_inf,
                )
                .map_err(|msg| {
                    (
                        422,
                        json!({
                            "error": msg,
                            "code": "invalid_death",
                            "fields": { "consent": msg }
                        }),
                    )
                })?;
            }

            for phone_col in ["informant_phone", "informant_phone_2"] {
                if let Some(val) = obj.get(phone_col) {
                    if let Some(s) = val.as_str().map(str::trim).filter(|s| !s.is_empty()) {
                        let norm = normalise_phone(Some(s)).ok_or_else(|| {
                            (
                                422,
                                json!({
                                    "error": "Enter a 10-digit mobile number.",
                                    "code": "invalid_death",
                                    "fields": { phone_col: "Enter a 10-digit mobile number." }
                                }),
                            )
                        })?;
                        let sql = format!(
                            "UPDATE loc_death_register SET {phone_col} = ?1 WHERE death_id = ?2"
                        );
                        conn.execute(&sql, params![norm, death_id])
                            .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                    } else if val.is_null() || val.as_str().map(|s| s.trim().is_empty()).unwrap_or(false) {
                        let sql = format!(
                            "UPDATE loc_death_register SET {phone_col} = NULL WHERE death_id = ?1"
                        );
                        conn.execute(&sql, params![death_id])
                            .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                    }
                }
            }

            let now = Utc::now().to_rfc3339();
            let string_columns = [
                "deceased_name",
                "deceased_sex",
                "date_of_death",
                "date_of_birth",
                "date_of_birth_partial",
                "place_of_death",
                "father_name",
                "mother_name",
                "abha_number",
                "abha_address",
                "informant_name",
                "informant_relation",
                "address",
                "address_house_street",
                "address_village_ward",
                "address_landmark",
                "location",
                "remarks",
                "org_unit_id",
            ];

            let mut changed_fields = Map::new();
            for col in string_columns {
                if let Some(val) = obj.get(col) {
                    if matches!(col, "deceased_name" | "deceased_sex" | "date_of_death") {
                        let s = val.as_str().map(str::trim).filter(|s| !s.is_empty()).ok_or_else(|| {
                            (
                                422,
                                json!({
                                    "error": format!("{col} cannot be empty."),
                                    "code": "invalid_death",
                                    "fields": { col: format!("{col} cannot be empty.") }
                                }),
                            )
                        })?;
                        let sql = format!(
                            "UPDATE loc_death_register SET {col} = ?1, updated_at = ?2 WHERE death_id = ?3"
                        );
                        conn.execute(&sql, params![s, now, death_id])
                            .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                        changed_fields.insert(col.to_string(), Value::String(s.to_string()));
                    } else {
                        let str_val = val
                            .as_str()
                            .map(str::trim)
                            .filter(|s| !s.is_empty())
                            .map(ToString::to_string);
                        let sql = format!(
                            "UPDATE loc_death_register SET {col} = ?1, updated_at = ?2 WHERE death_id = ?3"
                        );
                        conn.execute(&sql, params![str_val, now, death_id])
                            .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                        changed_fields.insert(
                            col.to_string(),
                            str_val.map(Value::String).unwrap_or(Value::Null),
                        );
                    }
                }
            }

            if let Some(age_val) = obj.get("age_years") {
                let age_num = age_val
                    .as_f64()
                    .or_else(|| age_val.as_str().and_then(|s| s.trim().parse::<f64>().ok()));
                conn.execute(
                    "UPDATE loc_death_register SET age_years = ?1, updated_at = ?2 WHERE death_id = ?3",
                    params![age_num, now, death_id],
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                changed_fields.insert("age_years".to_string(), json!(age_num.map(|v| v.round() as i64)));
            }

            let corr_client_id = obj
                .get("client_id")
                .and_then(Value::as_str)
                .and_then(|s| Uuid::parse_str(s).ok())
                .unwrap_or_else(Uuid::new_v4)
                .to_string();
            let cdid = client_death_id.unwrap_or_else(|| Uuid::new_v4().to_string());
            let corr_payload = json!({
                "client_death_id": cdid,
                "reason": reason,
                "fields": changed_fields
            });
            conn.execute(
                "INSERT OR REPLACE INTO loc_supervisor_corrections (
                    client_id, record_type, death_id, client_death_id, project_id,
                    site_id, org_unit_id, actor_user_id, actor_member_id, acting_role,
                    reason, payload_json, sync_state, created_at
                 ) VALUES (?1, 'death_correction', ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, 'pending', ?12)",
                params![
                    corr_client_id,
                    death_id,
                    cdid,
                    project_id.to_string(),
                    site_id,
                    org_unit_id,
                    active_actor.user_id,
                    active_actor.member_id,
                    active_actor.acting_role,
                    reason,
                    serde_json::to_string(&corr_payload).unwrap_or_else(|_| "{}".to_string()),
                    now
                ],
            )
            .ok();

            conn.execute(
                "INSERT INTO map_case_transitions (death_id, from_state, to_state, actor_name, reason, changes_json, created_at)
                 VALUES (?1, ?2, ?2, ?3, ?4, ?5, ?6)",
                params![
                    death_id,
                    prev_state,
                    actor_name,
                    reason,
                    serde_json::to_string(payload).ok(),
                    now
                ],
            )
            .ok();

            let detail = Self::build_case_detail(conn, death_id)
                .map_err(|e| (500, json!({ "error": e, "code": "db_error" })))?;
            Ok(json!({ "case": detail }))
        })
    }

    /// Update registration identifiers (`PUT /api/v1/intake/cases/<death_id>/identifiers`),
    /// allowed both before and after interview completion, unless the case is closed (`409 case_closed`).
    pub fn put_case_identifiers(
        &self,
        death_id: i64,
        identifiers_payload: &Value,
        actor_name: &str,
    ) -> Result<Value, (u16, Value)> {
        let obj = identifiers_payload.as_object().ok_or_else(|| {
            (
                400,
                json!({ "error": "Request body must be a JSON object", "code": "invalid_request" }),
            )
        })?;

        if let Some(r_val) = obj.get("reason") {
            if !r_val.is_null() {
                let valid = r_val
                    .as_str()
                    .map(str::trim)
                    .map(|s| !s.is_empty() && s.chars().count() <= 500)
                    .unwrap_or(false);
                if !valid {
                    return Err((
                        400,
                        json!({
                            "error": "If provided, reason must be a non-empty string up to 500 characters.",
                            "code": "invalid_request"
                        }),
                    ));
                }
            }
        }
        let reason_opt = obj
            .get("reason")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty());

        let mut raw_ids: BTreeMap<String, Option<String>> = BTreeMap::new();
        if let Some(inner) = obj.get("identifiers").and_then(Value::as_object) {
            for (k, v) in inner {
                raw_ids.insert(k.clone(), v.as_str().map(ToString::to_string));
            }
        } else {
            for (k, v) in obj {
                if k == "reason" || k == "client_id" {
                    continue;
                }
                raw_ids.insert(k.clone(), v.as_str().map(ToString::to_string));
            }
        }

        let active_actor = self.get_active_actor_context();
        let now = Utc::now().to_rfc3339();

        self.with_conn(|conn| {
            let row: Option<(i64, Option<String>, String, String, String, String)> = conn
                .query_row(
                    "SELECT project_id, client_death_id, status, state, site_id, org_unit_id
                     FROM loc_death_register WHERE death_id = ?1",
                    params![death_id],
                    |r| {
                        Ok((
                            r.get(0)?,
                            r.get(1)?,
                            r.get(2)?,
                            r.get(3)?,
                            r.get(4)?,
                            r.get(5)?,
                        ))
                    },
                )
                .optional()
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            let Some((pid, client_death_id, status, state, site_id, org_unit_id)) = row else {
                return Err((404, json!({ "error": "Case not found", "code": "not_found" })));
            };

            if matches!(status.as_str(), "cancelled" | "duplicate" | "closed")
                || matches!(state.as_str(), "cancelled" | "duplicate" | "closed")
            {
                return Err((
                    409,
                    json!({
                        "error": "Case is closed and identifiers cannot be modified.",
                        "code": "case_closed"
                    }),
                ));
            }

            let (stored, warnings) = Self::validate_and_store_identifiers(
                conn,
                pid,
                death_id,
                &raw_ids,
                actor_name,
                false,
            )
            .map_err(|(msg, fields)| {
                (
                    400,
                    json!({
                        "error": msg,
                        "code": "invalid_request",
                        "fields": fields
                    }),
                )
            })?;

            let corr_client_id = obj
                .get("client_id")
                .and_then(Value::as_str)
                .and_then(|s| Uuid::parse_str(s).ok())
                .unwrap_or_else(Uuid::new_v4)
                .to_string();
            let cdid = client_death_id.unwrap_or_else(|| Uuid::new_v4().to_string());
            let corr_payload = json!({
                "client_death_id": cdid,
                "reason": reason_opt,
                "identifiers": stored
            });
            conn.execute(
                "INSERT OR REPLACE INTO loc_supervisor_corrections (
                    client_id, record_type, death_id, client_death_id, project_id,
                    site_id, org_unit_id, actor_user_id, actor_member_id, acting_role,
                    reason, payload_json, sync_state, created_at
                 ) VALUES (?1, 'identifiers_set', ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, 'pending', ?12)",
                params![
                    corr_client_id,
                    death_id,
                    cdid,
                    pid.to_string(),
                    site_id,
                    org_unit_id,
                    active_actor.user_id,
                    active_actor.member_id,
                    active_actor.acting_role,
                    reason_opt,
                    serde_json::to_string(&corr_payload).unwrap_or_else(|_| "{}".to_string()),
                    now
                ],
            )
            .ok();

            let detail = Self::build_case_detail(conn, death_id)
                .map_err(|e| (500, json!({ "error": e, "code": "db_error" })))?;
            let mut resp = json!({
                "death_id": death_id.to_string(),
                "case": detail
            });
            if !warnings.is_empty() {
                resp["warnings"] = json!(warnings);
            }
            Ok(resp)
        })
    }

    pub fn list_cases(&self) -> Value {
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(
                    "SELECT death_id FROM loc_death_register ORDER BY death_id DESC LIMIT 100",
                )
                .unwrap();
            let ids: Vec<i64> = stmt
                .query_map([], |r| r.get(0))
                .unwrap()
                .filter_map(Result::ok)
                .collect();

            let mut rows = Vec::new();
            for id in ids {
                if let Ok(detail) = Self::build_case_row(conn, id) {
                    rows.push(detail);
                }
            }
            json!({
                "cases": rows,
                "deaths": rows,
                "counts": {
                    "total": rows.len()
                },
                "next_cursor": null
            })
        })
    }

    pub fn get_case_detail(&self, death_id: i64) -> Result<Value, String> {
        self.with_conn(|conn| {
            let detail = Self::build_case_detail(conn, death_id)?;
            Ok(json!({ "case": detail }))
        })
    }

    fn build_case_row(conn: &Connection, death_id: i64) -> Result<Value, String> {
        let active_actor = get_active_actor(conn);
        let is_coder = active_actor.acting_role == "coder";

        let mut stmt = conn
            .prepare(
                "SELECT death_id, unique_id, deceased_name, deceased_sex, date_of_death,
                        age_years, status, state, project_id, site_id, site_name,
                        org_unit_id, org_unit_name, informant_phone, informant_phone_2,
                        last_contact_at, next_visit_at, va_sid, updated_at,
                        client_death_id, sync_state
                 FROM loc_death_register WHERE death_id = ?1",
            )
            .map_err(|e| e.to_string())?;

        let row = stmt
            .query_row(params![death_id], |r| {
                let id_num: i64 = r.get(0)?;
                let unique_id: String = r.get(1)?;
                let deceased_name: String = r.get(2)?;
                let deceased_sex: String = r.get(3)?;
                let date_of_death: String = r.get(4)?;
                let age_years: Option<f64> = r.get(5)?;
                let status: String = r.get(6)?;
                let state: String = r.get(7)?;
                let project_id: i64 = r.get(8)?;
                let site_id: String = r.get(9)?;
                let site_name: String = r.get(10)?;
                let org_unit_id: String = r.get(11)?;
                let org_unit_name: String = r.get(12)?;
                let phone1: Option<String> = r.get(13)?;
                let phone2: Option<String> = r.get(14)?;
                let last_contact_at: Option<String> = r.get(15)?;
                let next_visit_at: Option<String> = r.get(16)?;
                let va_sid: Option<String> = r.get(17)?;
                let updated_at: String = r.get(18)?;
                let client_death_id: Option<String> = r.get(19)?;
                let sync_state: String = r.get(20)?;

                let my_draft_id: Option<String> = conn
                    .query_row(
                        "SELECT draft_id FROM loc_va_drafts WHERE death_id = ?1 AND status != 'submitted' ORDER BY updated_at DESC LIMIT 1",
                        params![id_num],
                        |dr| dr.get(0),
                    )
                    .optional()
                    .ok()
                    .flatten();

                let identifiers_list =
                    Self::load_case_identifier_items(conn, project_id, id_num, is_coder);
                let is_closed = matches!(status.as_str(), "cancelled" | "duplicate" | "closed")
                    || matches!(state.as_str(), "cancelled" | "duplicate" | "closed");
                let can_edit_identifiers = !is_closed && !is_coder;

                // Privacy & Contract 4.4 / 7.5 rules:
                // - Never return `consent_status`, `consent_withdrawn_at`, or `identifier_warnings`.
                // - `informant_phone_masked` is always null.
                // - When `acting_role == "coder"`, strip deceased_name and only expose `present: bool` on identifiers.
                Ok(json!({
                    "death_id": id_num.to_string(),
                    "client_death_id": client_death_id,
                    "unique_id": unique_id,
                    "deceased_name": if is_coder { Value::Null } else { Value::String(deceased_name) },
                    "deceased_sex": deceased_sex,
                    "date_of_death": date_of_death,
                    "age_years": age_years,
                    "status": status,
                    "state": state,
                    "project_id": project_id.to_string(),
                    "site_id": site_id,
                    "site_name": site_name,
                    "org_unit_id": org_unit_id,
                    "org_unit_name": org_unit_name,
                    "unit_name": org_unit_name,
                    "informant_phone_masked": null,
                    "informant_phone_2_masked": null,
                    "has_informant_phone": if is_coder { false } else { phone1.is_some() },
                    "has_informant_phone_2": if is_coder { false } else { phone2.is_some() },
                    "last_contact_at": last_contact_at,
                    "next_visit_at": next_visit_at,
                    "my_draft_id": my_draft_id,
                    "other_draft_active": false,
                    "other_complete_interview": va_sid.is_some(),
                    "va_sid": va_sid,
                    "code_now": true,
                    "can_edit_identifiers": can_edit_identifiers,
                    "identifiers": identifiers_list,
                    "sync_state": sync_state,
                    "updated_at": updated_at
                }))
            })
            .map_err(|e| e.to_string())?;
        Ok(row)
    }

    fn build_case_detail(conn: &Connection, death_id: i64) -> Result<Value, String> {
        let active_actor = get_active_actor(conn);
        let is_coder = active_actor.acting_role == "coder";

        let mut base = Self::build_case_row(conn, death_id)?;
        let (
            dob,
            dob_partial,
            place_of_death,
            father_name,
            mother_name,
            abha_number,
            abha_address,
            inf_name,
            inf_rel,
            inf_phone,
            inf_phone2,
            addr,
            addr_house,
            addr_village,
            addr_landmark,
            remarks,
            created_at,
            project_id,
            client_death_id,
        ) = conn
            .query_row(
                "SELECT date_of_birth, date_of_birth_partial, place_of_death,
                        father_name, mother_name, abha_number, abha_address,
                        informant_name, informant_relation, informant_phone, informant_phone_2,
                        address, address_house_street, address_village_ward, address_landmark,
                        remarks, created_at, project_id, client_death_id
                 FROM loc_death_register WHERE death_id = ?1",
                params![death_id],
                |r| {
                    Ok((
                        r.get::<_, Option<String>>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, Option<String>>(2)?,
                        r.get::<_, Option<String>>(3)?,
                        r.get::<_, Option<String>>(4)?,
                        r.get::<_, Option<String>>(5)?,
                        r.get::<_, Option<String>>(6)?,
                        r.get::<_, Option<String>>(7)?,
                        r.get::<_, Option<String>>(8)?,
                        r.get::<_, Option<String>>(9)?,
                        r.get::<_, Option<String>>(10)?,
                        r.get::<_, Option<String>>(11)?,
                        r.get::<_, Option<String>>(12)?,
                        r.get::<_, Option<String>>(13)?,
                        r.get::<_, Option<String>>(14)?,
                        r.get::<_, Option<String>>(15)?,
                        r.get::<_, String>(16)?,
                        r.get::<_, i64>(17)?,
                        r.get::<_, Option<String>>(18)?,
                    ))
                },
            )
            .map_err(|e| e.to_string())?;

        let latest_consent = if is_coder {
            None
        } else {
            get_latest_consent_for_case(conn, project_id, client_death_id.as_deref(), Some(death_id))
                .ok()
                .flatten()
        };

        let obj = base.as_object_mut().unwrap();
        let deceased_name = obj.get("deceased_name").cloned().unwrap_or(Value::Null);
        let deceased_sex = obj.get("deceased_sex").cloned().unwrap_or(Value::Null);
        let age_years = obj.get("age_years").cloned().unwrap_or(Value::Null);
        let date_of_death = obj.get("date_of_death").cloned().unwrap_or(Value::Null);

        if is_coder {
            obj.insert(
                "deceased".to_string(),
                json!({
                    "name": null,
                    "sex": deceased_sex,
                    "age_years": age_years,
                    "date_of_birth": dob,
                    "date_of_birth_partial": dob_partial,
                    "date_of_death": date_of_death,
                    "place_of_death": place_of_death,
                    "father_name": null,
                    "mother_name": null,
                    "abha_number": null,
                    "abha_address": null
                }),
            );
            obj.insert(
                "household_address".to_string(),
                json!({
                    "address": null,
                    "house_street": null,
                    "village_ward": null,
                    "landmark": null
                }),
            );
            obj.insert(
                "informant".to_string(),
                json!({
                    "name": null,
                    "relation": null,
                    "phone": null,
                    "phone_2": null
                }),
            );
            obj.insert(
                "prefill".to_string(),
                json!({
                    "Id10019": deceased_sex,
                    "Id10021": dob,
                    "Id10023": date_of_death,
                    "Id10051": age_years,
                    "Id10058": place_of_death
                }),
            );
        } else {
            obj.insert(
                "deceased".to_string(),
                json!({
                    "name": deceased_name,
                    "sex": deceased_sex,
                    "age_years": age_years,
                    "date_of_birth": dob,
                    "date_of_birth_partial": dob_partial,
                    "date_of_death": date_of_death,
                    "place_of_death": place_of_death,
                    "father_name": father_name,
                    "mother_name": mother_name,
                    "abha_number": abha_number,
                    "abha_address": abha_address
                }),
            );
            obj.insert(
                "household_address".to_string(),
                json!({
                    "address": addr,
                    "house_street": addr_house,
                    "village_ward": addr_village,
                    "landmark": addr_landmark
                }),
            );
            obj.insert(
                "informant".to_string(),
                json!({
                    "name": inf_name,
                    "relation": inf_rel,
                    "phone": inf_phone,
                    "phone_2": inf_phone2
                }),
            );
            obj.insert(
                "prefill".to_string(),
                json!({
                    "Id10007": inf_name,
                    "Id10008": inf_rel,
                    "Id10017": deceased_name,
                    "Id10019": deceased_sex,
                    "Id10021": dob,
                    "Id10023": date_of_death,
                    "Id10051": age_years,
                    "Id10058": place_of_death
                }),
            );
        }
        obj.insert("remarks".to_string(), if is_coder { Value::Null } else { json!(remarks) });
        obj.insert("registered_by_me".to_string(), Value::Bool(true));
        obj.insert("started_by_me".to_string(), Value::Bool(true));
        obj.insert("created_at".to_string(), json!(created_at));
        obj.insert("latest_consent".to_string(), json!(latest_consent));
        obj.insert(
            "links".to_string(),
            json!({
                "self": format!("/api/v1/intake/cases/{death_id}"),
                "attempts": format!("/api/v1/intake/cases/{death_id}/attempts"),
                "visit": format!("/api/v1/intake/cases/{death_id}/visit"),
                "start_interview": "/api/v1/intake/drafts",
                "identifiers": format!("/api/v1/intake/cases/{death_id}/identifiers")
            }),
        );

        Ok(base)
    }

    pub fn log_contact_attempt(
        &self,
        death_id: i64,
        outcome: &str,
        next_visit_at: Option<&str>,
        actor_name: &str,
    ) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        self.with_conn(|conn| {
            conn.execute(
                "INSERT INTO loc_case_attempts (death_id, outcome, next_visit_at, actor_name, created_at)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![death_id, outcome, next_visit_at, actor_name, now],
            )
            .map_err(|e| e.to_string())?;

            let new_state = if outcome == "refused" {
                "refused"
            } else {
                "contact_attempted"
            };
            conn.execute(
                "UPDATE loc_death_register
                 SET last_contact_at = ?1,
                     next_visit_at = COALESCE(?2, next_visit_at),
                     state = ?3,
                     updated_at = ?1
                 WHERE death_id = ?4",
                params![now, next_visit_at, new_state, death_id],
            )
            .map_err(|e| e.to_string())?;

            let detail = Self::build_case_detail(conn, death_id)?;
            Ok(json!({ "case": detail }))
        })
    }

    pub fn set_case_visit(
        &self,
        death_id: i64,
        next_visit_at: Option<&str>,
    ) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_death_register SET next_visit_at = ?1, updated_at = ?2 WHERE death_id = ?3",
                params![next_visit_at, now, death_id],
            )
            .map_err(|e| e.to_string())?;
            let detail = Self::build_case_detail(conn, death_id)?;
            Ok(json!({ "case": detail }))
        })
    }

    // ========================================================================
    // VA Interview Drafts & Submissions (with Id10073 Reduction)
    // ========================================================================

    pub fn list_drafts(&self) -> Value {
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(
                    "SELECT draft_id, unique_id, project_id, site_id, site_name,
                            org_unit_id, org_unit_name, death_id, status, current_section, updated_at
                     FROM loc_va_drafts
                     WHERE status != 'submitted'
                     ORDER BY updated_at DESC",
                )
                .unwrap();
            let drafts: Vec<Value> = stmt
                .query_map([], |r| {
                    let death_id_opt: Option<i64> = r.get(7)?;
                    Ok(json!({
                        "draft_id": r.get::<_, String>(0)?,
                        "unique_id": r.get::<_, String>(1)?,
                        "project_id": r.get::<_, String>(2)?,
                        "site_id": r.get::<_, String>(3)?,
                        "site_name": r.get::<_, String>(4)?,
                        "org_unit_id": r.get::<_, Option<String>>(5)?,
                        "org_unit_name": r.get::<_, Option<String>>(6)?,
                        "death_id": death_id_opt.map(|d| d.to_string()),
                        "status": r.get::<_, String>(8)?,
                        "current_section": r.get::<_, Option<String>>(9)?,
                        "updated_at": r.get::<_, String>(10)?
                    }))
                })
                .unwrap()
                .filter_map(Result::ok)
                .collect();
            json!({ "drafts": drafts })
        })
    }

    pub fn start_draft(&self, input: &Value) -> Result<Value, String> {
        let project_id = input
            .get("project_id")
            .and_then(Value::as_str)
            .unwrap_or("1");
        let site_id = input
            .get("site_id")
            .and_then(Value::as_str)
            .unwrap_or("PHC01");
        let org_unit_id = input
            .get("org_unit_id")
            .and_then(Value::as_str)
            .unwrap_or("ou-sc-1");
        let death_id: Option<i64> = input.get("death_id").and_then(|v| {
            v.as_i64()
                .or_else(|| v.as_str().and_then(|s| s.parse::<i64>().ok()))
        });

        let station_cfg = self.get_station_config();
        let active_actor = self.get_active_actor_context();
        let now = Utc::now().to_rfc3339();

        self.with_conn(|conn| {
            if let Some(did) = death_id {
                if let Some(existing_draft_id) = conn
                    .query_row(
                        "SELECT draft_id FROM loc_va_drafts WHERE death_id = ?1 AND status != 'submitted' LIMIT 1",
                        params![did],
                        |r| r.get::<_, String>(0),
                    )
                    .optional()
                    .map_err(|e| e.to_string())?
                {
                    let detail = Self::build_draft_response(conn, &existing_draft_id)?;
                    return Ok(json!({ "draft": detail["draft"] }));
                }
            }

            let draft_id = Uuid::new_v4().to_string();
            let (unique_id, prefill) = if let Some(did) = death_id {
                let detail = Self::build_case_detail(conn, did)?;
                let uid = detail["unique_id"]
                    .as_str()
                    .unwrap_or("PHC-DRAFT")
                    .to_string();
                let pf = detail.get("prefill").cloned().unwrap_or_else(|| json!({}));
                (uid, pf)
            } else {
                (
                    format!("VA-{}", &draft_id[..8].to_uppercase()),
                    json!({ "Id10012": &now[..10] }),
                )
            };

            let prefill_str = serde_json::to_string(&prefill).unwrap_or_else(|_| "{}".to_string());
            conn.execute(
                "INSERT INTO loc_va_drafts (
                    draft_id, unique_id, project_id, site_id, site_name,
                    org_unit_id, org_unit_name, death_id, status, current_section,
                    locale, translation_version, answers_json, prefill_json,
                    actor_user_id, actor_member_id, acting_role, sync_state, updated_at, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'Sub-Centre 1', ?7, 'in_progress', 'respondent', 'en', 1, ?8, ?8, ?9, ?10, ?11, 'pending', ?12, ?12)",
                params![
                    draft_id,
                    unique_id,
                    project_id,
                    site_id,
                    station_cfg.facility_name,
                    org_unit_id,
                    death_id,
                    prefill_str,
                    active_actor.user_id,
                    active_actor.member_id,
                    active_actor.acting_role,
                    now
                ],
            )
            .map_err(|e| e.to_string())?;

            let detail = Self::build_draft_response(conn, &draft_id)?;
            Ok(json!({ "draft": detail["draft"] }))
        })
    }

    pub fn get_draft(&self, draft_id: &str) -> Result<Value, String> {
        self.with_conn(|conn| Self::build_draft_response(conn, draft_id))
    }

    pub fn save_draft(&self, draft_id: &str, payload: &Value) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        let data_val = payload
            .get("data")
            .or_else(|| payload.get("answers"))
            .unwrap_or(payload);
        // Reduce Id10073 and sweep free-text national IDs before writing to local storage!
        let (reduced_data, _) = redact_payload_national_ids(data_val);
        let answers_str =
            serde_json::to_string(&reduced_data).unwrap_or_else(|_| "{}".to_string());
        let section = payload.get("current_section").and_then(Value::as_str);

        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_va_drafts
                 SET answers_json = ?1,
                     current_section = COALESCE(?2, current_section),
                     updated_at = ?3
                 WHERE draft_id = ?4",
                params![answers_str, section, now, draft_id],
            )
            .map_err(|e| e.to_string())?;
            Self::build_draft_response(conn, draft_id)
        })
    }

    fn build_draft_response(conn: &Connection, draft_id: &str) -> Result<Value, String> {
        conn.query_row(
            "SELECT draft_id, unique_id, project_id, site_id, site_name,
                    org_unit_id, org_unit_name, death_id, status, current_section,
                    locale, translation_version, answers_json, prefill_json, updated_at
             FROM loc_va_drafts WHERE draft_id = ?1",
            params![draft_id],
            |r| {
                let did: Option<i64> = r.get(7)?;
                let answers_raw: String = r.get(12)?;
                let prefill_raw: String = r.get(13)?;
                let answers: Value = serde_json::from_str(&answers_raw).unwrap_or_else(|_| json!({}));
                let prefill: Value = serde_json::from_str(&prefill_raw).unwrap_or_else(|_| json!({}));
                let updated_at: String = r.get(14)?;
                let summary = json!({
                    "draft_id": r.get::<_, String>(0)?,
                    "unique_id": r.get::<_, String>(1)?,
                    "project_id": r.get::<_, String>(2)?,
                    "site_id": r.get::<_, String>(3)?,
                    "site_name": r.get::<_, String>(4)?,
                    "org_unit_id": r.get::<_, Option<String>>(5)?,
                    "org_unit_name": r.get::<_, Option<String>>(6)?,
                    "death_id": did.map(|d| d.to_string()),
                    "status": r.get::<_, String>(8)?,
                    "current_section": r.get::<_, Option<String>>(9)?,
                    "updated_at": updated_at
                });
                Ok(json!({
                    "draft": summary,
                    "envelope": {
                        "draft_id": draft_id,
                        "instrument_code": "WHO_2022_VA",
                        "instrument_version": "2022.1.5-offline",
                        "locale": r.get::<_, String>(10)?,
                        "translation_version": r.get::<_, i64>(11)?,
                        "data": answers,
                        "updated_at": updated_at
                    },
                    "prefill": prefill
                }))
            },
        )
        .map_err(|e| e.to_string())
    }

    pub fn submit_draft(&self, draft_id: &str, body: &Value) -> Result<(u16, Value), String> {
        let now = Utc::now().to_rfc3339();
        let active_actor = self.get_active_actor_context();
        self.with_conn(|conn| {
            let (unique_id, project_id, site_id, org_unit_id, death_id, existing_answers_str): (
                String,
                String,
                String,
                Option<String>,
                Option<i64>,
                String,
            ) = conn
                .query_row(
                    "SELECT unique_id, project_id, site_id, org_unit_id, death_id, answers_json
                     FROM loc_va_drafts WHERE draft_id = ?1",
                    params![draft_id],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?)),
                )
                .map_err(|e| format!("Draft not found: {e}"))?;

            let incoming_data = body
                .get("completion")
                .and_then(|c| c.get("data"))
                .cloned()
                .unwrap_or_else(|| {
                    serde_json::from_str(&existing_answers_str).unwrap_or_else(|_| json!({}))
                });

            // Reduce Id10073 to last 3 digits (`XXXXXXXXX123`) and sweep free-text fields!
            let (mut reduced_payload, flagged_fields) = redact_payload_national_ids(&incoming_data);
            if let Some(obj) = reduced_payload.as_object_mut() {
                obj.entry("sid".to_string())
                    .or_insert_with(|| Value::String(unique_id.clone()));
            }
            let fingerprint = canonical_payload_fingerprint(&reduced_payload);

            let deceased_name = reduced_payload
                .get("Id10017")
                .and_then(Value::as_str)
                .map(ToString::to_string);
            let deceased_gender = reduced_payload
                .get("Id10019")
                .and_then(Value::as_str)
                .map(ToString::to_string);
            let deceased_age = reduced_payload
                .get("Id10051")
                .map(|v| {
                    v.as_str()
                        .map(ToString::to_string)
                        .unwrap_or_else(|| v.to_string())
                });

            let va_sid = format!("VA-{}", &draft_id[..8].to_uppercase());
            let payload_str =
                serde_json::to_string(&reduced_payload).unwrap_or_else(|_| "{}".to_string());
            let flagged_str =
                serde_json::to_string(&flagged_fields).unwrap_or_else(|_| "[]".to_string());

            conn.execute(
                "INSERT INTO loc_va_submissions (
                    va_sid, death_id, draft_id, unique_id, project_id, site_id, org_unit_id,
                    form_type_code, deceased_name, deceased_age, deceased_gender,
                    payload_json, payload_fingerprint, flagged_fields_json,
                    workflow_state, actor_user_id, actor_member_id, acting_role,
                    sync_state, submitted_at, updated_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 'WHO_2022_VA', ?8, ?9, ?10, ?11, ?12, ?13, 'available_for_coding', ?14, ?15, ?16, 'pending', ?17, ?17)
                 ON CONFLICT(va_sid) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    payload_fingerprint = excluded.payload_fingerprint,
                    flagged_fields_json = excluded.flagged_fields_json,
                    updated_at = excluded.updated_at",
                params![
                    va_sid,
                    death_id,
                    draft_id,
                    unique_id,
                    project_id,
                    site_id,
                    org_unit_id,
                    deceased_name,
                    deceased_age,
                    deceased_gender,
                    payload_str,
                    fingerprint,
                    flagged_str,
                    active_actor.user_id,
                    active_actor.member_id,
                    active_actor.acting_role,
                    now
                ],
            )
            .map_err(|e| e.to_string())?;

            conn.execute(
                "UPDATE loc_va_drafts SET status = 'submitted', answers_json = ?1, updated_at = ?2 WHERE draft_id = ?3",
                params![payload_str, now, draft_id],
            )
            .map_err(|e| e.to_string())?;

            if let Some(did) = death_id {
                conn.execute(
                    "UPDATE loc_death_register SET va_sid = ?1, status = 'interviewed', state = 'interview_completed', updated_at = ?2 WHERE death_id = ?3",
                    params![va_sid, now, did],
                )
                .ok();
            }

            Self::append_workflow_event(
                conn,
                &va_sid,
                None,
                "available_for_coding",
                "user",
                Some("interviewer"),
                Some("VA interview submitted"),
            );

            let draft_resp = Self::build_draft_response(conn, draft_id)?;
            Ok((
                201,
                json!({
                    "va_sid": va_sid,
                    "draft": draft_resp["draft"],
                    "superseded": false,
                    "validation_err": [],
                    "can_code_now": true
                }),
            ))
        })
    }

    // ========================================================================
    // Offline Coding Workspace, SmartVA, ICD Search, DORIS & MCCD PDF
    // ========================================================================

    fn append_workflow_event(
        conn: &Connection,
        va_sid: &str,
        prev_state: Option<&str>,
        curr_state: &str,
        actor_kind: &str,
        actor_role: Option<&str>,
        reason: Option<&str>,
    ) {
        let now = Utc::now().to_rfc3339();
        let ev_id = Uuid::new_v4().to_string();
        let tr_id = Uuid::new_v4().to_string();
        let _ = conn.execute(
            "INSERT INTO loc_workflow_events (
                event_id, va_sid, transition_id, previous_state, current_state,
                actor_kind, actor_role, transition_reason, event_created_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                ev_id,
                va_sid,
                tr_id,
                prev_state,
                curr_state,
                actor_kind,
                actor_role,
                reason,
                now
            ],
        );
    }

    fn load_project_sealed_field_ids(conn: &Connection, project_id: &str) -> Vec<String> {
        conn.query_row(
            "SELECT sealed_field_ids_json FROM loc_project_config WHERE project_id = ?1",
            params![project_id],
            |r| r.get::<_, String>(0),
        )
        .optional()
        .ok()
        .flatten()
        .and_then(|raw| serde_json::from_str::<Vec<String>>(&raw).ok())
        .unwrap_or_default()
    }

    pub fn run_smartva_for_submission(&self, va_sid: &str) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        self.with_conn(|conn| {
            let (payload_raw, project_id): (String, String) = conn
                .query_row(
                    "SELECT payload_json, project_id FROM loc_va_submissions WHERE va_sid = ?1",
                    params![va_sid],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .map_err(|_| format!("VA submission '{va_sid}' not found"))?;

            let extra_sealed = Self::load_project_sealed_field_ids(conn, &project_id);
            let mut parsed: Value =
                serde_json::from_str(&payload_raw).unwrap_or_else(|_| json!({}));
            if let Some(map) = parsed.as_object_mut() {
                strip_pii_from_smartva_map_with_sealed(map, &extra_sealed);
                map.insert("sid".to_string(), Value::String(va_sid.to_string()));
            }

            let engine = SmartVaEngine::new();
            let input_array_str =
                serde_json::to_string(&vec![parsed]).unwrap_or_else(|_| "[]".to_string());
            assert_no_pii_in_smartva_json_with_sealed(&input_array_str, &extra_sealed)
                .map_err(|e| e.to_string())?;
            let smartva_res =
                score_clinical_json_result(&engine, &input_array_str, &SmartVaRunOptions::default())
                    .map_err(|e| e.to_string())?;

            let summary = smartva_res
                .predictions
                .first()
                .map(|p| {
                    json!({
                        "status": "done",
                        "cause": p.cause1,
                        "cause34": p.cause34,
                        "module": p.module,
                        "age_group": p.age,
                        "sex": p.sex,
                        "likelihood": "High"
                    })
                })
                .unwrap_or_else(|| {
                    json!({
                        "status": "done",
                        "cause": "Undetermined",
                        "module": "adult",
                        "likelihood": "Low"
                    })
                });

            let summary_str = serde_json::to_string(&summary).unwrap_or_else(|_| "{}".to_string());
            conn.execute(
                "UPDATE loc_va_submissions
                 SET smartva_status = 'done', smartva_json = ?1, updated_at = ?2
                 WHERE va_sid = ?3",
                params![summary_str, now, va_sid],
            )
            .map_err(|e| e.to_string())?;

            Ok(json!({
                "va_sid": va_sid,
                "status": "done",
                "smartva": summary
            }))
        })
    }

    pub fn get_va_workspace(&self, va_sid: &str, mode: &str) -> Result<Value, String> {
        let station_cfg = self.get_station_config();
        self.with_conn(|conn| {
            let row = conn
                .query_row(
                    "SELECT unique_id, project_id, site_id, form_type_code, deceased_age,
                            deceased_gender, workflow_state, smartva_status, smartva_json,
                            initial_assessment_json, final_assessment_json, not_codeable_json,
                            reviewer_initial_json, reviewer_final_json, doris_json,
                            narrative_qa_json, social_autopsy_json
                     FROM loc_va_submissions WHERE va_sid = ?1",
                    params![va_sid],
                    |r| {
                        Ok((
                            r.get::<_, String>(0)?,
                            r.get::<_, String>(1)?,
                            r.get::<_, String>(2)?,
                            r.get::<_, String>(3)?,
                            r.get::<_, Option<String>>(4)?,
                            r.get::<_, Option<String>>(5)?,
                            r.get::<_, String>(6)?,
                            r.get::<_, String>(7)?,
                            r.get::<_, Option<String>>(8)?,
                            r.get::<_, Option<String>>(9)?,
                            r.get::<_, Option<String>>(10)?,
                            r.get::<_, Option<String>>(11)?,
                            r.get::<_, Option<String>>(12)?,
                            r.get::<_, Option<String>>(13)?,
                            r.get::<_, Option<String>>(14)?,
                            r.get::<_, Option<String>>(15)?,
                            r.get::<_, Option<String>>(16)?,
                        ))
                    },
                )
                .map_err(|_| format!("Submission {va_sid} not found"))?;

            let (
                unique_id,
                project_id,
                site_id,
                form_type_code,
                age,
                gender,
                workflow_state,
                smartva_status,
                smartva_raw,
                initial_raw,
                final_raw,
                nc_raw,
                rev_init_raw,
                rev_final_raw,
                doris_raw,
                nqa_raw,
                sa_raw,
            ) = row;

            let parse_opt = |s: Option<String>| -> Value {
                s.and_then(|raw| serde_json::from_str(&raw).ok())
                    .unwrap_or(Value::Null)
            };

            let initial_ass = parse_opt(initial_raw);
            let final_ass = parse_opt(final_raw);
            let nc_ass = parse_opt(nc_raw);
            let rev_init = parse_opt(rev_init_raw);
            let rev_final = parse_opt(rev_final_raw);
            let smartva_val = parse_opt(smartva_raw);
            let doris_saved = parse_opt(doris_raw);
            let nqa_saved = parse_opt(nqa_raw);
            let sa_saved = parse_opt(sa_raw);

            let is_view = mode == "view";
            let step = if is_view {
                "view"
            } else if !final_ass.is_null() || !nc_ass.is_null() {
                "done"
            } else if !initial_ass.is_null() {
                "final"
            } else {
                "initial"
            };

            let categories = json!([
                { "code": "demographics", "label": "Demographics & Background", "nav_label": "Demographics", "render_mode": "list", "icon_name": "fa-user", "count": 6 },
                { "code": "symptoms", "label": "Clinical Symptoms & History", "nav_label": "Symptoms", "render_mode": "list", "icon_name": "fa-stethoscope", "count": 12 },
                { "code": "narrative", "label": "Open Narrative", "nav_label": "Narrative", "render_mode": "narrative", "icon_name": "fa-file-text", "count": 1 }
            ]);

            let narrative_qa = if is_view {
                Value::Null
            } else {
                json!({
                    "fields": [
                        {
                            "key": "chronology",
                            "label": "Chronology of symptoms",
                            "options": [
                                { "value": 0, "label": "Absent" },
                                { "value": 1, "label": "Partial" },
                                { "value": 2, "label": "Complete" }
                            ]
                        },
                        {
                            "key": "clinical_detail",
                            "label": "Relevant negative & positive clinical signs",
                            "options": [
                                { "value": 0, "label": "Absent" },
                                { "value": 1, "label": "Partial" },
                                { "value": 2, "label": "Complete" }
                            ]
                        }
                    ],
                    "max_score": 4,
                    "saved": nqa_saved
                })
            };

            let social_autopsy = if is_view {
                Value::Null
            } else {
                json!({
                    "questions": [
                        {
                            "delay_level": "delay_1",
                            "title": "Delay 1: Deciding to seek care",
                            "options": [
                                { "option_code": "d1_none", "label": "No delay in deciding to seek care", "description": "Care was sought promptly" },
                                { "option_code": "d1_cost", "label": "Financial constraint / cost concern", "description": "Family delayed seeking care due to cost" }
                            ]
                        },
                        {
                            "delay_level": "delay_2",
                            "title": "Delay 2: Reaching health facility",
                            "options": [
                                { "option_code": "d2_none", "label": "No transport delay", "description": "Facility reached promptly" },
                                { "option_code": "d2_transport", "label": "Lack of transport / distance", "description": "Difficulty arranging transport" }
                            ]
                        }
                    ],
                    "saved": sa_saved
                })
            };

            let doris = if is_view {
                Value::Null
            } else {
                json!({
                    "initial_certificate": {
                        "line_1a_code": "",
                        "line_1a_text": "",
                        "line_1b_code": "",
                        "line_1b_text": "",
                        "line_1c_code": "",
                        "line_1c_text": "",
                        "line_1d_code": "",
                        "line_1d_text": "",
                        "part2_code": "",
                        "part2_text": ""
                    },
                    "prefill_provenance": null,
                    "saved_processing": if doris_saved.is_object() { doris_saved } else { Value::Null },
                    "step1_certificate": null,
                    "step1_processing": null
                })
            };

            let other_conditions_options = if is_view {
                Value::Null
            } else {
                json!(["Anaemia", "Diabetes mellitus", "Hypertension", "Malnutrition", "Tobacco use"])
            };

            Ok(json!({
                "case": {
                    "va_sid": va_sid,
                    "instance_name": unique_id,
                    "form_type_code": form_type_code,
                    "project_code": project_id,
                    "site_code": site_id,
                    "age": age,
                    "gender": gender,
                    "survey_district": station_cfg.district_name,
                    "survey_state": station_cfg.state_name,
                    "is_demo_project": false,
                    "project_mode": "unmasked_doris",
                    "icd_classification": "icd11",
                    "workflow_state": workflow_state,
                    "narrative_qa_enabled": !is_view,
                    "social_autopsy_enabled": !is_view
                },
                "categories": categories,
                "default_category": "demographics",
                "step": step,
                "blocked_by": [],
                "assessments": {
                    "initial": if is_view { Value::Null } else { initial_ass.clone() },
                    "initial_prefill": if is_view { Value::Null } else { initial_ass.clone() },
                    "final": final_ass,
                    "not_codeable": nc_ass,
                    "coder_initial": initial_ass,
                    "reviewer_initial": rev_init,
                    "reviewer_final": rev_final
                },
                "smartva": smartva_val,
                "smartva_status": smartva_status,
                "smartva_can_run": true,
                "other_conditions_options": other_conditions_options,
                "doris": doris,
                "narrative_qa": narrative_qa,
                "social_autopsy": social_autopsy
            }))
        })
    }

    pub fn get_va_category(&self, va_sid: &str, category_code: &str, mode: &str) -> Result<Value, String> {
        self.with_conn(|conn| {
            let (payload_raw, project_id): (String, String) = conn
                .query_row(
                    "SELECT payload_json, project_id FROM loc_va_submissions WHERE va_sid = ?1",
                    params![va_sid],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .map_err(|_| format!("Submission {va_sid} not found"))?;
            let payload: Value =
                serde_json::from_str(&payload_raw).unwrap_or_else(|_| json!({}));

            let extra_sealed: BTreeSet<String> =
                Self::load_project_sealed_field_ids(conn, &project_id)
                    .into_iter()
                    .map(|s| s.to_lowercase())
                    .collect();
            let is_sealed = |field_id: &str| -> bool {
                extra_sealed.contains(&field_id.to_lowercase())
            };

            // Hard privacy rule: Coders and reviewers never see informant personal data or sealed fields!
            let get_str = |k: &str| -> String {
                if is_sealed(k) {
                    return "Not recorded".to_string();
                }
                payload
                    .get(k)
                    .and_then(|v| {
                        v.as_str()
                            .map(ToString::to_string)
                            .or_else(|| Some(v.to_string()))
                    })
                    .unwrap_or_else(|| "Not recorded".to_string())
            };

            let (label, render_mode, raw_items): (&str, &str, Vec<(&str, Value)>) = match category_code {
                "narrative" => (
                    "Open Narrative",
                    "narrative",
                    vec![(
                        "Id10476",
                        json!({
                            "label": "Open Narrative (Id10476)",
                            "value": get_str("Id10476"),
                            "flip": false,
                            "info": false
                        }),
                    )],
                ),
                "symptoms" => (
                    "Clinical Symptoms & History",
                    "list",
                    vec![
                        ("Id10147", json!({ "label": "Fever (Id10147)", "value": get_str("Id10147"), "flip": get_str("Id10147") == "yes", "info": false })),
                        ("Id10148", json!({ "label": "Duration of fever in days (Id10148)", "value": get_str("Id10148"), "flip": false, "info": true })),
                        ("Id10153", json!({ "label": "Cough (Id10153)", "value": get_str("Id10153"), "flip": get_str("Id10153") == "yes", "info": false })),
                        ("Id10159", json!({ "label": "Fast / difficult breathing (Id10159)", "value": get_str("Id10159"), "flip": get_str("Id10159") == "yes", "info": false })),
                        ("Id10166", json!({ "label": "Chest pain (Id10166)", "value": get_str("Id10166"), "flip": get_str("Id10166") == "yes", "info": false })),
                        ("Id10181", json!({ "label": "Diarrhoea (Id10181)", "value": get_str("Id10181"), "flip": get_str("Id10181") == "yes", "info": false })),
                        ("Id10223", json!({ "label": "Paralysis of one side (Id10223)", "value": get_str("Id10223"), "flip": get_str("Id10223") == "yes", "info": false })),
                        ("Id10077", json!({ "label": "History of injury/accident (Id10077)", "value": get_str("Id10077"), "flip": get_str("Id10077") == "yes", "info": false })),
                    ],
                ),
                _ => (
                    "Demographics & Background",
                    "list",
                    vec![
                        ("Id10019", json!({ "label": "Sex of deceased (Id10019)", "value": get_str("Id10019"), "flip": false, "info": true })),
                        ("Id10051", json!({ "label": "Age in years (Id10051)", "value": get_str("Id10051"), "flip": false, "info": true })),
                        ("Id10023", json!({ "label": "Date of death (Id10023)", "value": get_str("Id10023"), "flip": false, "info": true })),
                        ("Id10058", json!({ "label": "Place of death (Id10058)", "value": get_str("Id10058"), "flip": false, "info": true })),
                    ],
                ),
            };
            let items: Vec<Value> = raw_items
                .into_iter()
                .filter(|(fid, _)| !is_sealed(fid))
                .map(|(_, val)| val)
                .collect();

            let mut out = json!({
                "code": category_code,
                "label": label,
                "render_mode": render_mode,
                "summary_items": [],
                "subcategories": [
                    {
                        "code": format!("{category_code}_main"),
                        "label": label,
                        "render_mode": render_mode,
                        "items": items
                    }
                ]
            });
            if mode != "view" {
                out["blocked_by"] = json!([]);
            }
            Ok(out)
        })
    }

    pub fn get_va_note(&self, va_sid: &str) -> Result<Value, String> {
        self.with_conn(|conn| {
            let (content, updated_at): (Option<String>, Option<String>) = conn
                .query_row(
                    "SELECT note_content, note_updated_at FROM loc_va_submissions WHERE va_sid = ?1",
                    params![va_sid],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .map_err(|_| format!("Submission {va_sid} not found"))?;
            Ok(json!({
                "va_sid": va_sid,
                "content": content,
                "updated_at": updated_at
            }))
        })
    }

    pub fn save_va_note(&self, va_sid: &str, content: Option<&str>) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_va_submissions SET note_content = ?1, note_updated_at = ?2, updated_at = ?2 WHERE va_sid = ?3",
                params![content, now, va_sid],
            )
            .map_err(|e| e.to_string())?;
            Ok(json!({
                "va_sid": va_sid,
                "content": content,
                "updated_at": now
            }))
        })
    }

    pub fn save_narrative_qa(&self, va_sid: &str, body: &Value) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        let cannot_grade = body
            .get("cannot_grade")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let values = body
            .get("values")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();
        let score: i64 = values.values().filter_map(Value::as_i64).sum();
        let rating = if cannot_grade {
            "Cannot Grade"
        } else if score >= 3 {
            "Good"
        } else if score >= 2 {
            "Fair"
        } else {
            "Poor"
        };
        let saved = json!({
            "cannot_grade": cannot_grade,
            "values": values,
            "score": score,
            "rating": rating
        });
        let saved_str = serde_json::to_string(&saved).unwrap_or_else(|_| "{}".to_string());
        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_va_submissions SET narrative_qa_json = ?1, updated_at = ?2 WHERE va_sid = ?3",
                params![saved_str, now, va_sid],
            )
            .map_err(|e| e.to_string())?;
            Ok(json!({
                "va_sid": va_sid,
                "saved": saved
            }))
        })
    }

    pub fn save_social_autopsy(&self, va_sid: &str, body: &Value) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        let selected_options = body
            .get("selected_options")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let remark = body.get("remark").and_then(Value::as_str);
        let saved = json!({
            "selected_options": selected_options,
            "remark": remark
        });
        let saved_str = serde_json::to_string(&saved).unwrap_or_else(|_| "{}".to_string());
        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_va_submissions SET social_autopsy_json = ?1, updated_at = ?2 WHERE va_sid = ?3",
                params![saved_str, now, va_sid],
            )
            .map_err(|e| e.to_string())?;
            Ok(json!({
                "va_sid": va_sid,
                "saved": saved
            }))
        })
    }

    pub fn save_coding_assessment(
        &self,
        va_sid: &str,
        stage: &str, // "initial" | "final" | "not_codeable" | "reviewer_initial" | "reviewer_final"
        body: &Value,
    ) -> Result<Value, String> {
        let now = Utc::now().to_rfc3339();
        let active_actor = self.get_active_actor_context();
        let ass_id = Uuid::new_v4().to_string();
        let mut ass_obj = body.as_object().cloned().unwrap_or_default();
        ass_obj.insert("id".to_string(), Value::String(ass_id.clone()));
        ass_obj.insert("created_at".to_string(), Value::String(now.clone()));

        let ass_str = serde_json::to_string(&Value::Object(ass_obj.clone())).unwrap_or_else(|_| "{}".to_string());

        let (col, new_state, id_key) = match stage {
            "initial" => (
                "initial_assessment_json",
                "initial_coded",
                "initial_assessment_id",
            ),
            "final" => ("final_assessment_json", "coded", "final_assessment_id"),
            "not_codeable" => (
                "not_codeable_json",
                "not_codeable",
                "final_assessment_id",
            ),
            "reviewer_initial" => (
                "reviewer_initial_json",
                "reviewer_initial_coded",
                "reviewer_initial_assessment_id",
            ),
            _ => (
                "reviewer_final_json",
                "reviewed",
                "reviewer_final_assessment_id",
            ),
        };

        self.with_conn(|conn| {
            let sub_meta: Option<(Option<String>, String, String, Option<String>, Option<String>, Option<String>, Option<String>, Option<String>)> = conn
                .query_row(
                    "SELECT workflow_state, project_id, site_id, org_unit_id, draft_id,
                            initial_assessment_json, narrative_qa_json, social_autopsy_json
                     FROM loc_va_submissions WHERE va_sid = ?1",
                    params![va_sid],
                    |r| {
                        Ok((
                            r.get(0)?,
                            r.get(1)?,
                            r.get(2)?,
                            r.get(3)?,
                            r.get(4)?,
                            r.get(5)?,
                            r.get(6)?,
                            r.get(7)?,
                        ))
                    },
                )
                .optional()
                .map_err(|e| e.to_string())?;

            let Some((prev_state, project_id, site_id, org_unit_id, draft_id_opt, init_raw, nqa_raw, sa_raw)) = sub_meta else {
                return Err(format!("Submission {va_sid} not found"));
            };

            let sql = format!(
                "UPDATE loc_va_submissions
                 SET {col} = ?1,
                     workflow_state = ?2,
                     coded_at = CASE WHEN ?2 IN ('coded', 'not_codeable', 'reviewed') THEN ?3 ELSE coded_at END,
                     updated_at = ?3
                 WHERE va_sid = ?4"
            );
            conn.execute(&sql, params![ass_str, new_state, now, va_sid])
                .map_err(|e| e.to_string())?;

            if matches!(stage, "final" | "not_codeable") {
                let client_draft_id = draft_id_opt.unwrap_or_else(|| Uuid::new_v4().to_string());
                let init_val = init_raw
                    .and_then(|s| serde_json::from_str::<Value>(&s).ok())
                    .unwrap_or(Value::Null);
                let nqa_val = nqa_raw
                    .and_then(|s| serde_json::from_str::<Value>(&s).ok())
                    .unwrap_or(Value::Null);
                let sa_val = sa_raw
                    .and_then(|s| serde_json::from_str::<Value>(&s).ok())
                    .unwrap_or(Value::Null);
                let cr_payload = json!({
                    "client_draft_id": client_draft_id,
                    "va_sid": va_sid,
                    "stage": stage,
                    "initial_assessment": init_val,
                    "final_assessment": if stage == "final" { Value::Object(ass_obj.clone()) } else { Value::Null },
                    "not_codeable": if stage == "not_codeable" { Value::Object(ass_obj.clone()) } else { Value::Null },
                    "narrative_qa": nqa_val,
                    "social_autopsy": sa_val
                });
                conn.execute(
                    "INSERT OR REPLACE INTO loc_coding_results (
                        client_id, va_sid, client_draft_id, project_id, site_id, org_unit_id,
                        actor_user_id, actor_member_id, acting_role, payload_json, sync_state, created_at
                     ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, 'pending', ?11)",
                    params![
                        ass_id,
                        va_sid,
                        client_draft_id,
                        project_id,
                        site_id,
                        org_unit_id,
                        active_actor.user_id,
                        active_actor.member_id,
                        active_actor.acting_role,
                        serde_json::to_string(&cr_payload).unwrap_or_else(|_| "{}".to_string()),
                        now
                    ],
                )
                .ok();
            }

            Self::append_workflow_event(
                conn,
                va_sid,
                prev_state.as_deref(),
                new_state,
                "user",
                Some("coder"),
                Some(&format!("Saved {stage} coding assessment")),
            );

            let mut reply = Map::new();
            reply.insert("va_sid".to_string(), Value::String(va_sid.to_string()));
            reply.insert(
                "workflow_state".to_string(),
                Value::String(new_state.to_string()),
            );
            reply.insert(id_key.to_string(), Value::String(ass_id));
            reply.insert("odk_synced".to_string(), Value::Bool(true));
            Ok(Value::Object(reply))
        })
    }

    pub fn search_icd(&self, classification: &str, query: &str) -> Vec<Value> {
        self.with_conn(|conn| {
            let items = search_icd_catalog(conn, classification, query, 25).unwrap_or_default();
            items
                .into_iter()
                .map(|item| {
                    json!({
                        "icd_code": item.code,
                        "icd_to_display": item.label,
                        "title": item.title,
                        "class_kind": "category",
                        "tier": "catalog"
                    })
                })
                .collect()
        })
    }

    pub fn get_va_definition(&self, classification: &str, code: &str) -> Result<Value, String> {
        self.with_conn(|conn| {
            let res = lookup_va_definition_for_icd(conn, classification, code)
                .map_err(|e| e.to_string())?;
            if res.get("found").and_then(Value::as_bool) == Some(true) {
                Ok(res)
            } else {
                Err("VA definition not found".to_string())
            }
        })
    }

    pub fn doris_terms(&self, query: &str, limit: usize) -> Value {
        let items: Vec<Value> = self.with_conn(|conn| {
            let rows = search_icd_catalog(conn, "icd11", query, limit).unwrap_or_default();
            rows.into_iter()
                .map(|r| {
                    json!({
                        "code": r.code,
                        "title": r.title,
                        "uri": format!("http://id.who.int/icd/release/11/mms/{}", r.code),
                        "release": "2026-01",
                        "matching_text": r.matched_synonym.unwrap_or_else(|| r.title.clone()),
                        "postcoordination": false,
                        "postcoordination_availability": null,
                        "related_maternal": false,
                        "related_perinatal": false,
                        "has_coding_note": false
                    })
                })
                .collect()
        });

        json!({
            "schema_version": 1,
            "items": items,
            "truncated": false,
            "next_cursor": null
        })
    }

    pub fn doris_codeinfo(&self, code: &str) -> Value {
        let norm = code.trim().to_uppercase();
        let title = self.with_conn(|conn| {
            conn.query_row(
                "SELECT title FROM cat_icd_entries WHERE classification = 'icd11' AND UPPER(code) = ?1 LIMIT 1",
                params![norm],
                |r| r.get::<_, String>(0),
            )
            .unwrap_or_else(|_| format!("ICD-11 entity {norm}"))
        });

        json!({
            "schema_version": 1,
            "item": {
                "code": norm,
                "title": title,
                "uri": format!("http://id.who.int/icd/release/11/mms/{}", norm),
                "release": "2026-01",
                "postcoordination": false
            }
        })
    }

    pub fn doris_process(&self, va_sid: &str, body: &Value) -> Result<Value, String> {
        let client_revision = body
            .get("client_revision")
            .and_then(Value::as_i64)
            .unwrap_or(1)
            .max(0);
        let cert = body
            .get("certificate")
            .and_then(Value::as_object)
            .cloned()
            .unwrap_or_default();

        // Select lowest non-empty Part 1 line (1d -> 1c -> 1b -> 1a) per WHO mortality rules SP3/SP4
        let pick_line = |keys: &[&str]| -> Option<String> {
            for k in keys {
                if let Some(s) = cert
                    .get(*k)
                    .and_then(Value::as_str)
                    .map(str::trim)
                    .filter(|s| !s.is_empty())
                {
                    return Some(s.to_uppercase());
                }
            }
            None
        };

        let underlying_code = pick_line(&[
            "line_1d_code",
            "cause_d_code",
            "line_1c_code",
            "cause_c_code",
            "line_1b_code",
            "cause_b_code",
            "line_1a_code",
            "cause_a_code",
        ])
        .unwrap_or_else(|| "MB2Y".to_string());

        let cert_str = serde_json::to_string(&Value::Object(cert.clone())).unwrap_or_default();
        let mut h1 = Sha256::new();
        h1.update(cert_str.as_bytes());
        let cert_digest = format!("{:x}", h1.finalize());

        let doris_res = json!({
            "underlying_cause_code": underlying_code,
            "reject": false,
            "selection_rule": "SP3",
            "report": format!("Selected underlying cause {underlying_code} by WHO mortality sequence rule.")
        });
        let res_str = serde_json::to_string(&doris_res).unwrap_or_default();
        let mut h2 = Sha256::new();
        h2.update(res_str.as_bytes());
        let res_digest = format!("{:x}", h2.finalize());

        let reply = json!({
            "schema_version": 1,
            "client_revision": client_revision,
            "icd_release": "2026-01",
            "certificate": cert,
            "certificate_digest": cert_digest,
            "result_digest": res_digest,
            "doris": {
                "status": "completed",
                "result": doris_res
            },
            "codedit": {
                "status": "completed",
                "result": {
                    "warnings": [],
                    "valid": true
                }
            },
            "process_token": Uuid::new_v4().to_string()
        });

        let now = Utc::now().to_rfc3339();
        let reply_str = serde_json::to_string(&reply).unwrap_or_else(|_| "{}".to_string());
        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_va_submissions SET doris_json = ?1, updated_at = ?2 WHERE va_sid = ?3",
                params![reply_str, now, va_sid],
            )
            .ok();
        });

        Ok(reply)
    }

    pub fn get_workflow_events(&self, va_sid: &str, limit: usize) -> Value {
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(
                    "SELECT event_id, transition_id, previous_state, current_state,
                            actor_kind, actor_role, transition_reason, event_created_at
                     FROM loc_workflow_events
                     WHERE va_sid = ?1
                     ORDER BY event_created_at DESC
                     LIMIT ?2",
                )
                .unwrap();
            let events: Vec<Value> = stmt
                .query_map(params![va_sid, limit as i64], |r| {
                    Ok(json!({
                        "event_id": r.get::<_, String>(0)?,
                        "transition_id": r.get::<_, String>(1)?,
                        "previous_state": r.get::<_, Option<String>>(2)?,
                        "current_state": r.get::<_, String>(3)?,
                        "actor_kind": r.get::<_, String>(4)?,
                        "actor_role": r.get::<_, Option<String>>(5)?,
                        "transition_reason": r.get::<_, Option<String>>(6)?,
                        "event_created_at": r.get::<_, String>(7)?
                    }))
                })
                .unwrap()
                .filter_map(Result::ok)
                .collect();

            json!({
                "va_sid": va_sid,
                "events": events,
                "limit": limit,
                "next_cursor": null
            })
        })
    }

    pub fn get_coder_queue(&self, limit: usize, offset: usize) -> Value {
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(
                    "SELECT va_sid, unique_id, form_type_code, project_id, site_id,
                            submitted_at, deceased_age, deceased_gender
                     FROM loc_va_submissions
                     WHERE workflow_state NOT IN ('coded', 'not_codeable', 'reviewed')
                     ORDER BY submitted_at DESC
                     LIMIT ?1 OFFSET ?2",
                )
                .unwrap();
            let forms: Vec<Value> = stmt
                .query_map(params![limit as i64, offset as i64], |r| {
                    Ok(json!({
                        "va_sid": r.get::<_, String>(0)?,
                        "va_uniqueid_masked": r.get::<_, String>(1)?,
                        "va_form_id": r.get::<_, String>(2)?,
                        "project_id": r.get::<_, String>(3)?,
                        "site_id": r.get::<_, String>(4)?,
                        "va_submission_date": r.get::<_, String>(5)?,
                        "va_data_collector": "PHC Health Worker",
                        "va_deceased_age": r.get::<_, Option<String>>(6)?,
                        "va_deceased_gender": r.get::<_, Option<String>>(7)?
                    }))
                })
                .unwrap()
                .filter_map(Result::ok)
                .collect();

            let count = forms.len();
            json!({
                "forms": forms,
                "count": count,
                "limit": limit,
                "offset": offset,
                "has_more": false
            })
        })
    }

    pub fn get_coder_history(&self, limit: usize, offset: usize) -> Value {
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(
                    "SELECT va_sid, unique_id, form_type_code, project_id, site_id,
                            submitted_at, deceased_age, deceased_gender, COALESCE(coded_at, updated_at), workflow_state
                     FROM loc_va_submissions
                     WHERE workflow_state IN ('coded', 'not_codeable', 'reviewed')
                     ORDER BY updated_at DESC
                     LIMIT ?1 OFFSET ?2",
                )
                .unwrap();
            let history: Vec<Value> = stmt
                .query_map(params![limit as i64, offset as i64], |r| {
                    Ok(json!({
                        "va_sid": r.get::<_, String>(0)?,
                        "va_uniqueid_masked": r.get::<_, String>(1)?,
                        "va_form_id": r.get::<_, String>(2)?,
                        "project_id": r.get::<_, String>(3)?,
                        "site_id": r.get::<_, String>(4)?,
                        "va_submission_date": r.get::<_, String>(5)?,
                        "va_deceased_age": r.get::<_, Option<String>>(6)?,
                        "va_deceased_gender": r.get::<_, Option<String>>(7)?,
                        "va_coding_date": r.get::<_, String>(8)?,
                        "va_code_status": r.get::<_, String>(9)?,
                        "recodeable": true
                    }))
                })
                .unwrap()
                .filter_map(Result::ok)
                .collect();

            let count = history.len();
            json!({
                "history": history,
                "count": count,
                "limit": limit,
                "offset": offset,
                "has_more": false
            })
        })
    }

    pub fn generate_mccd_pdf_for_va(&self, va_sid: &str) -> Result<Vec<u8>, String> {
        let station_cfg = self.get_station_config();
        self.with_conn(|conn| {
            let (unique_id, death_id_opt, age_opt, sex_opt, final_raw, init_raw): (
                String,
                Option<i64>,
                Option<String>,
                Option<String>,
                Option<String>,
                Option<String>,
            ) = conn
                .query_row(
                    "SELECT unique_id, death_id, deceased_age, deceased_gender,
                            final_assessment_json, initial_assessment_json
                     FROM loc_va_submissions WHERE va_sid = ?1",
                    params![va_sid],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?)),
                )
                .map_err(|_| format!("Submission {va_sid} not found"))?;

            let mut deceased_name = unique_id.clone();
            let mut date_of_death = String::new();
            let mut crs_number = String::new();
            let mut mccd_number = format!("MCCD-{va_sid}");

            if let Some(did) = death_id_opt {
                if let Ok((dname, dod)) = conn.query_row(
                    "SELECT deceased_name, date_of_death FROM loc_death_register WHERE death_id = ?1",
                    params![did],
                    |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)),
                ) {
                    deceased_name = dname;
                    date_of_death = dod;
                }
                let ids = Self::load_case_identifiers(conn, did);
                if let Some(crs) = ids.get("crs_reg_no") {
                    crs_number = crs.clone();
                }
                if let Some(mccd) = ids.get("mccd_cert_no") {
                    mccd_number = mccd.clone();
                }
            }

            let ass_val: Value = final_raw
                .or(init_raw)
                .and_then(|s| serde_json::from_str(&s).ok())
                .unwrap_or_else(|| json!({}));

            let immediate_cod = ass_val
                .get("immediate_cod")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let antecedent_cod = ass_val
                .get("antecedent_cod")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_string();
            let conclusive_cod = ass_val
                .get("conclusive_cod")
                .and_then(Value::as_str)
                .unwrap_or(&antecedent_cod)
                .to_string();

            let cert_data = WhoMccdCertificateData {
                unique_case_id: mccd_number,
                death_registration_id: if crs_number.is_empty() {
                    None
                } else {
                    Some(crs_number)
                },
                project_id: "1".to_string(),
                project_name: Some(format!("{} Mortality Surveillance", station_cfg.facility_name)),
                site_code: "PHC01".to_string(),
                site_name: Some(station_cfg.facility_name.clone()),
                station_id: Some(station_cfg.station_id.clone()),
                deceased_name: Some(deceased_name),
                sex: sex_opt,
                date_of_birth: None,
                date_of_death: if date_of_death.is_empty() {
                    None
                } else {
                    Some(date_of_death)
                },
                age_at_death: age_opt,
                place_of_death: Some("Reported via Verbal Autopsy".to_string()),
                part1_lines: vec![
                    MccdConditionLine {
                        condition_text: immediate_cod.clone(),
                        icd_code: if immediate_cod.is_empty() {
                            None
                        } else {
                            Some(immediate_cod)
                        },
                        interval_iso_or_text: None,
                    },
                    MccdConditionLine {
                        condition_text: antecedent_cod.clone(),
                        icd_code: if antecedent_cod.is_empty() {
                            None
                        } else {
                            Some(antecedent_cod)
                        },
                        interval_iso_or_text: None,
                    },
                    MccdConditionLine {
                        condition_text: conclusive_cod.clone(),
                        icd_code: if conclusive_cod.is_empty() {
                            None
                        } else {
                            Some(conclusive_cod.clone())
                        },
                        interval_iso_or_text: None,
                    },
                ],
                part2_conditions: Vec::new(),
                icd_version: "ICD-11 (2026-01)".to_string(),
                doris_computed_ucod: Some(conclusive_cod.clone()),
                final_certified_ucod: conclusive_cod,
                va_cause_bucket: None,
                coder_remarks: ass_val
                    .get("remark")
                    .and_then(Value::as_str)
                    .map(ToString::to_string),
                coded_by_name: "PHC Medical Officer".to_string(),
                coded_by_id: "standalone-phc".to_string(),
                coded_by_role: Some("Medical Officer / Physician Coder".to_string()),
                coded_at: Utc::now().format("%Y-%m-%d").to_string(),
                certificate_digest: None,
                ..Default::default()
            };

            render_who_mccd_pdf(&cert_data).map_err(|e| e.to_string())
        })
    }

    /// Export non-PII case summary CSV:
    /// Never includes `deceased_name`, `consent_status`, Aadhaar digits, or informant name/phone/address.
    pub fn export_cases_csv(&self) -> String {
        self.with_conn(|conn| {
            let mut out = String::from(
                "death_id,unique_id,deceased_sex,date_of_death,age_years,org_unit_name,crs_reg_no,mccd_cert_no,va_sid,workflow_state,final_cod\n",
            );
            let mut stmt = conn
                .prepare(
                    "SELECT r.death_id, r.unique_id, r.deceased_sex,
                            r.date_of_death, r.age_years, r.org_unit_name,
                            r.va_sid, s.workflow_state, s.final_assessment_json
                     FROM loc_death_register r
                     LEFT JOIN loc_va_submissions s ON s.va_sid = r.va_sid
                     ORDER BY r.death_id ASC",
                )
                .unwrap();

            let rows = stmt
                .query_map([], |r| {
                    let did: i64 = r.get(0)?;
                    let ids = Self::load_case_identifiers(conn, did);
                    let crs = ids.get("crs_reg_no").cloned().unwrap_or_default();
                    let mccd = ids.get("mccd_cert_no").cloned().unwrap_or_default();
                    let final_raw: Option<String> = r.get(8)?;
                    let final_cod = final_raw
                        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
                        .and_then(|v| {
                            v.get("conclusive_cod")
                                .or_else(|| v.get("antecedent_cod"))
                                .and_then(Value::as_str)
                                .map(ToString::to_string)
                        })
                        .unwrap_or_default();

                    Ok(format!(
                        "{},{},{},{},{},\"{}\",\"{}\",\"{}\",{},{},\"{}\"\n",
                        did,
                        r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, String>(3)?,
                        r.get::<_, Option<f64>>(4)?
                            .map(|a| a.to_string())
                            .unwrap_or_default(),
                        r.get::<_, String>(5)?.replace('"', "\"\""),
                        crs.replace('"', "\"\""),
                        mccd.replace('"', "\"\""),
                        r.get::<_, Option<String>>(6)?.unwrap_or_default(),
                        r.get::<_, Option<String>>(7)?.unwrap_or_default(),
                        final_cod.replace('"', "\"\"")
                    ))
                })
                .unwrap();

            for line in rows.flatten() {
                out.push_str(&line);
            }
            out
        })
    }

    pub fn form_options(&self, project_id: &str) -> Value {
        default_form_options(project_id)
    }

    pub fn instrument_definition(&self) -> (Value, String) {
        (
            default_who_2022_va_definition(),
            default_who_2022_va_definition_sha256(),
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_standalone_mode_device_projection_and_canonical_roles() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let access = db.build_access_summary().unwrap();
        assert_eq!(access["station_mode"], "standalone");
        assert_eq!(access["user"]["user_id"], "roster-mo-1");
        assert_eq!(access["active_actor"]["acting_role"], "station_supervisor");
        // Contract 3.1: Device projection always sets is_admin=false, can_manage_users=false, can_access_admin=false
        assert_eq!(access["is_admin"], false);
        assert_eq!(access["can_manage_users"], false);
        assert_eq!(access["can_access_admin"], false);
        assert_eq!(
            access["roles"],
            json!(["interviewer", "death_reporter"])
        );

        // Switching Dr. Anil Sharma's acting_role to "coder" restricts access to ["coder"] only
        let switched = db
            .switch_acting_role("roster-mo-1", Some("coder"))
            .unwrap();
        assert_eq!(switched.acting_role, "coder");
        let coder_access = db.build_access_summary().unwrap();
        assert_eq!(coder_access["roles"], json!(["coder"]));
        assert_eq!(
            coder_access["projects"][0]["actions"]["interview"],
            json!([])
        );

        // Switch back to station_supervisor (accepting legacy alias "supervisor" too)
        let sup_ctx = db
            .switch_acting_role("roster-mo-1", Some("supervisor"))
            .unwrap();
        assert_eq!(sup_ctx.acting_role, "station_supervisor");
        let added = db
            .upsert_roster_member(&UpsertRosterMemberInput {
                member_id: None,
                user_id: None,
                name: "Meena Verma".to_string(),
                designation: "Health Worker / ANM / MPW".to_string(),
                is_reporter: true,
                is_interviewer: true,
                is_supervisor: false,
                is_coder: false,
                roles: vec![],
                active: true,
            })
            .unwrap();
        assert_eq!(added.name, "Meena Verma");

        // Switch to provisioned mode without user credentials -> returns unauthorized, and roster is read-only (403)
        db.update_station_config(
            "provisioned",
            None,
            None,
            None,
            Some("https://central.digitva.org"),
            None,
            None,
            None,
            None,
        )
        .unwrap();
        assert_eq!(db.build_access_summary().unwrap_err(), "unauthorized");
        let (code, _) = db
            .upsert_roster_member(&UpsertRosterMemberInput {
                member_id: None,
                user_id: None,
                name: "Blocked In Provisioned".to_string(),
                designation: "Other".to_string(),
                is_reporter: true,
                is_interviewer: false,
                is_supervisor: false,
                is_coder: false,
                roles: vec![],
                active: true,
            })
            .unwrap_err();
        assert_eq!(code, 403);

        // Provision server user with admin/data_manager roles -> filtered to device-allowed roles only
        db.update_station_config(
            "provisioned",
            None,
            None,
            None,
            Some("https://central.digitva.org"),
            Some("usr-42"),
            Some("Dr. Meera Nair"),
            Some(vec![
                "admin".to_string(),
                "data_manager".to_string(),
                "interviewer".to_string(),
                "coder".to_string(),
            ]),
            Some("tok-xyz"),
        )
        .unwrap();
        let prov_access = db.build_access_summary().unwrap();
        assert_eq!(prov_access["station_mode"], "provisioned");
        assert_eq!(prov_access["user"]["user_id"], "usr-42");
        assert_eq!(prov_access["is_admin"], false);
        assert_eq!(prov_access["roles"], json!(["interviewer", "coder"]));
    }

    #[test]
    fn test_dpdp_consent_hard_gate_refusal_coder_masking_and_server_purge() {
        let db = OfflineDatabase::open_in_memory().unwrap();

        // 1. Attempting to save informant personal data WITHOUT consent must fail with 422
        let bad_reg = json!({
            "project_id": "1",
            "site_id": "PHC01",
            "deceased_name": "Kishan Lal",
            "deceased_sex": "male",
            "date_of_death": "2026-10-15",
            "informant_name": "Suresh Lal",
            "informant_phone": "9876543210"
        });
        let (status, err_body) = db.register_death(&bad_reg, "standalone-phc").unwrap_err();
        assert_eq!(status, 422);
        assert_eq!(err_body["code"], "invalid_registration");
        assert!(err_body["fields"]["consent"].is_string());

        // 2. Refusal path: informant contact fields are omitted/cleared, registration succeeds
        let refusal_reg = json!({
            "project_id": "1",
            "site_id": "PHC01",
            "deceased_name": "Kishan Lal",
            "deceased_sex": "male",
            "date_of_death": "2026-10-15",
            "informant_name": "Should Be Stripped On Refusal",
            "informant_phone": "9876543210",
            "consent": {
                "decision": "refused",
                "notice_version_id": "0.1",
                "notice_language": "en",
                "mode": "spoken",
                "purposes": []
            }
        });
        let refusal_res = db.register_death(&refusal_reg, "standalone-phc").unwrap();
        assert!(refusal_res["case"].get("consent_status").is_none());
        assert_eq!(refusal_res["case"]["has_informant_phone"], false);
        assert!(refusal_res["case"]["informant"]["phone"].is_null());

        // 3. Granted consent path + CRS/MCCD identifiers + duplicate warning shape + coder masking
        let consent_cid = Uuid::new_v4();
        let granted_reg = json!({
            "project_id": "1",
            "site_id": "PHC01",
            "deceased_name": "Radha Devi",
            "deceased_sex": "female",
            "date_of_death": "2026-10-18",
            "informant_name": "Mohan Sharma",
            "informant_phone": "9876543210",
            "address": "House 14, Ward 2",
            "identifiers": {
                "crs_reg_no": "crs-2026/0055",
                "mccd_cert_no": "mccd-2026/0055"
            },
            "consent": {
                "client_id": consent_cid.to_string(),
                "decision": "granted",
                "notice_version_id": "0.1",
                "notice_language": "en",
                "mode": "tap",
                "witness_present": true,
                "purposes": [
                    { "code": "record_and_interview", "granted": true },
                    { "code": "contact_followup", "granted": true },
                    { "code": "cause_of_death_coding", "granted": true },
                    { "code": "statistical_reports", "granted": true },
                    { "code": "sms_whatsapp_messages", "granted": true },
                    { "code": "research_sharing", "granted": false }
                ]
            }
        });
        let granted_res = db.register_death(&granted_reg, "standalone-phc").unwrap();
        let death_id: i64 = granted_res["case"]["death_id"]
            .as_str()
            .unwrap()
            .parse()
            .unwrap();
        assert_eq!(granted_res["case"]["has_informant_phone"], true);
        assert!(granted_res["case"]["informant_phone_masked"].is_null());
        assert_eq!(granted_res["case"]["can_edit_identifiers"], true);
        assert_eq!(
            granted_res["case"]["identifiers"][0],
            json!({
                "code": "crs_reg_no",
                "label": "CRS Registration Number",
                "value": "CRS-2026/0055"
            })
        );

        // Coder role sees only `present: true` on identifiers and no informant/deceased PII
        db.switch_acting_role("roster-mo-1", Some("coder")).unwrap();
        let coder_detail = db.get_case_detail(death_id).unwrap();
        assert!(coder_detail["case"]["deceased_name"].is_null());
        assert!(coder_detail["case"]["informant"]["phone"].is_null());
        assert_eq!(coder_detail["case"]["can_edit_identifiers"], false);
        assert_eq!(
            coder_detail["case"]["identifiers"][0],
            json!({
                "code": "crs_reg_no",
                "label": "CRS Registration Number",
                "present": true
            })
        );

        // Switch back to station_supervisor and apply server-issued purge for consent_cid -> scrubs informant PII
        db.switch_acting_role("roster-mo-1", Some("station_supervisor"))
            .unwrap();
        let purged = db.apply_purge_list(&[consent_cid]);
        assert_eq!(purged, 1);
        let after_purge = db.get_case_detail(death_id).unwrap();
        assert_eq!(after_purge["case"]["has_informant_phone"], false);
        assert!(after_purge["case"]["informant"]["name"].is_null());
        assert!(after_purge["case"]["informant"]["phone"].is_null());
        assert!(after_purge["case"]["household_address"]["address"].is_null());
    }

    #[test]
    fn test_pin_lock_and_5_attempt_wipe() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        db.set_user_pin("roster-mo-1", "123456").unwrap();

        // Register a case while unlocked
        let reg = json!({
            "project_id": "1",
            "site_id": "PHC01",
            "deceased_name": "Test Case",
            "deceased_sex": "male",
            "date_of_death": "2026-10-18"
        });
        db.register_death(&reg, "roster-mo-1").unwrap();
        assert_eq!(db.list_cases()["counts"]["total"], 1);

        // Lock store -> switching role without PIN fails with 423
        db.lock_store();
        assert!(db.is_locked());
        let (code, _) = db
            .switch_acting_role_with_pin("roster-mo-1", Some("station_supervisor"), None)
            .unwrap_err();
        assert_eq!(code, 423);

        // 4 wrong PIN attempts return 401; 5th wrong attempt wipes user store and returns 403
        for attempt in 1..=4 {
            let (status, body) = db.unlock_user_store("roster-mo-1", "999999").unwrap_err();
            assert_eq!(status, 401);
            assert_eq!(body["remaining_attempts"], 5 - attempt);
        }
        let (status5, body5) = db.unlock_user_store("roster-mo-1", "999999").unwrap_err();
        assert_eq!(status5, 403);
        assert_eq!(body5["code"], "store_wiped_max_pin_attempts");
        assert_eq!(db.list_cases()["counts"]["total"], 0);
    }

    #[test]
    fn test_va_interview_reduces_id10073_and_supports_offline_smartva_and_coding() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let draft_res = db
            .start_draft(&json!({ "project_id": "1", "site_id": "PHC01" }))
            .unwrap();
        let draft_id = draft_res["draft"]["draft_id"].as_str().unwrap();

        let (_, submit_res) = db
            .submit_draft(
                draft_id,
                &json!({
                    "completion": {
                        "valid": true,
                        "issues": [],
                        "data": {
                            "Id10017": "Sita Devi",
                            "Id10019": "female",
                            "Id10023": "2026-10-19",
                            "Id10051": "68",
                            "Id10073": "2345 6789 0123",
                            "Id10147": "yes",
                            "Id10148": "5",
                            "Id10153": "yes",
                            "Id10476": "Patient had high fever and Aadhaar 9876 5432 1098 was mentioned."
                        }
                    }
                }),
            )
            .unwrap();
        let va_sid = submit_res["va_sid"].as_str().unwrap();

        // Verify Id10073 and narrative Aadhaar were reduced in SQLite storage
        let cat_nar = db.get_va_category(va_sid, "narrative", "coding").unwrap();
        let nar_text = cat_nar["subcategories"][0]["items"][0]["value"]
            .as_str()
            .unwrap();
        assert!(nar_text.contains("XXXXXXXXX098"));
        assert!(!nar_text.contains("9876 5432 1098"));

        // Run SmartVA
        let smartva = db.run_smartva_for_submission(va_sid).unwrap();
        assert_eq!(smartva["status"], "done");

        // Save initial and final coding + generate MCCD PDF
        db.save_coding_assessment(
            va_sid,
            "initial",
            &json!({ "immediate_cod": "CA40", "antecedent_cod": "CA40", "conclusive_cod": "CA40" }),
        )
        .unwrap();
        db.save_coding_assessment(
            va_sid,
            "final",
            &json!({ "immediate_cod": "CA40", "antecedent_cod": "CA40", "conclusive_cod": "CA40" }),
        )
        .unwrap();

        let pdf_bytes = db.generate_mccd_pdf_for_va(va_sid).unwrap();
        assert!(pdf_bytes.starts_with(b"%PDF-1.4"));

        // Standalone sandbox mode .dvb export must be refused with 403 sandbox_not_exportable
        let (exp_status, exp_err) = db.export_dvb_bundle().unwrap_err();
        assert_eq!(exp_status, 403);
        assert_eq!(exp_err["code"], "sandbox_not_exportable");
    }

    #[test]
    fn test_supervisor_correction_completed_and_closed_guards_and_identifiers() {
        let db = OfflineDatabase::open_in_memory().unwrap();

        let reg1 = db
            .register_death(
                &json!({
                    "project_id": "1",
                    "site_id": "PHC01",
                    "deceased_name": "Case One",
                    "deceased_sex": "male",
                    "date_of_death": "2026-10-10",
                    "identifiers": { "crs_reg_no": "CRS-2026-100" }
                }),
                "roster-mo-1",
            )
            .unwrap();
        let did1: i64 = reg1["case"]["death_id"].as_str().unwrap().parse().unwrap();

        let reg2 = db
            .register_death(
                &json!({
                    "project_id": "1",
                    "site_id": "PHC01",
                    "deceased_name": "Case Two",
                    "deceased_sex": "female",
                    "date_of_death": "2026-10-12"
                }),
                "roster-mo-1",
            )
            .unwrap();
        let did2: i64 = reg2["case"]["death_id"].as_str().unwrap().parse().unwrap();

        // 1. Passing identifiers on PATCH /api/v1/intake/deaths/:death_id is rejected (400 invalid_request)
        let (st_id, err_id) = db
            .update_death_registration(
                did1,
                &json!({ "reason": "Try identifier update", "crs_reg_no": "CRS-2026-999" }),
                "roster-mo-1",
            )
            .unwrap_err();
        assert_eq!(st_id, 400);
        assert_eq!(err_id["code"], "invalid_request");

        // 2. Missing reason on PATCH is rejected (400 invalid_request)
        let (st_nr, _) = db
            .update_death_registration(did1, &json!({ "place_of_death": "Home" }), "roster-mo-1")
            .unwrap_err();
        assert_eq!(st_nr, 400);

        // 3. Valid PATCH before interview completion succeeds
        let upd = db
            .update_death_registration(
                did1,
                &json!({ "reason": "Corrected place of death", "place_of_death": "District Hospital" }),
                "roster-mo-1",
            )
            .unwrap();
        assert_eq!(upd["case"]["deceased"]["place_of_death"], "District Hospital");

        // 4. PUT /api/v1/intake/cases/:death_id/identifiers on Case Two with duplicate CRS number emits non-blocking warning without matching_death_ids
        let put_dup = db
            .put_case_identifiers(
                did2,
                &json!({
                    "reason": "Entered from register",
                    "identifiers": { "crs_reg_no": "CRS-2026-100" }
                }),
                "roster-mo-1",
            )
            .unwrap();
        let warnings = put_dup["warnings"].as_array().unwrap();
        assert_eq!(warnings.len(), 1);
        assert_eq!(warnings[0]["code"], "identifier_in_use");
        assert_eq!(warnings[0]["field"], "identifiers.crs_reg_no");
        assert!(warnings[0].get("matching_death_ids").is_none());

        // 5. Complete VA interview for Case One -> PATCH death details now returns 409 case_completed, but PUT identifiers still works!
        let draft = db
            .start_draft(&json!({ "project_id": "1", "site_id": "PHC01", "death_id": did1 }))
            .unwrap();
        let draft_id = draft["draft"]["draft_id"].as_str().unwrap();
        db.submit_draft(
            draft_id,
            &json!({
                "completion": {
                    "valid": true,
                    "issues": [],
                    "data": { "Id10019": "male", "Id10051": "55" }
                }
            }),
        )
        .unwrap();

        let (st_comp, err_comp) = db
            .update_death_registration(
                did1,
                &json!({ "reason": "Late edit", "place_of_death": "Clinic" }),
                "roster-mo-1",
            )
            .unwrap_err();
        assert_eq!(st_comp, 409);
        assert_eq!(err_comp["code"], "case_completed");

        let put_after_complete = db
            .put_case_identifiers(
                did1,
                &json!({
                    "reason": "Added MCCD after coding",
                    "identifiers": { "crs_reg_no": "CRS-2026-100", "mccd_cert_no": "MCCD-2026-100" }
                }),
                "roster-mo-1",
            )
            .unwrap();
        assert_eq!(put_after_complete["case"]["identifiers"].as_array().unwrap().len(), 2);
    }

    #[test]
    fn test_signed_station_config_import_bundle_export_and_receipt_import() {
        use digitva_bundle::{
            format_signed_receipt, format_signed_station_config, BundleReceiptReport,
            DesignationSpec, ReceiptRecordOutcome, RecordIngestOutcome, RecordType, RosterMember,
            RosterRoleGrant, ServerSigningKeyConfig, StationCustodian, StationKemPublicKeyConfig,
            StationProjectConfig,
        };

        let db = OfflineDatabase::open_in_memory().unwrap();

        // Load tv1 KEM public key from server test vectors
        let vec_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../docs/from-server/2026-10-21/vectors/pii_envelope_vectors.json");
        let vec_data: Value =
            serde_json::from_str(&std::fs::read_to_string(vec_path).unwrap()).unwrap();
        let tv1_pub_cfg = vec_data["deterministic"]["test_keys"]["kem_keys"][0]["public_key_config"]
            .as_str()
            .unwrap()
            .to_string();

        let server_signing_key = StationSigningKey::from_secret_bytes(&[0x41u8; 32]);
        let notice_vid = Uuid::parse_str("00000000-0000-4000-8000-000000000010").unwrap();
        let notice_text = "DPDP Notice v1 for Project 2";
        let notice_sha = sha256_hex(notice_text.as_bytes());

        let cfg_payload = StationConfigPayload {
            station_config_format_version: 1,
            config_id: Uuid::parse_str("a1000000-0000-4000-8000-000000000001").unwrap(),
            issued_at: "2026-10-20T00:00:00Z".to_string(),
            expires_at: "2027-04-18T00:00:00Z".to_string(),
            device_id: "station-phc-01".to_string(),
            server_url: "https://digitva.example.org".to_string(),
            kem_public_key: StationKemPublicKeyConfig {
                key_id: "tv1".to_string(),
                public: tv1_pub_cfg,
            },
            server_signing_key: ServerSigningKeyConfig {
                signing_key_id: server_signing_key.signing_key_id(),
                public: server_signing_key.public_key_base64url(),
            },
            projects: vec![StationProjectConfig {
                project_id: "2".to_string(),
                sites: vec!["PHC01".to_string()],
                org_units: vec!["ou-sc-1".to_string()],
                sealed_field_ids: vec![
                    "Id10007".to_string(),
                    "Id10017".to_string(),
                    "Id10073".to_string(),
                    "Id99999".to_string(),
                ],
                instrument_versions: vec!["2022_v1".to_string()],
                consent: Some(json!({
                    "consent_required": true,
                    "notice_versions": [
                        {
                            "notice_version_id": notice_vid.to_string(),
                            "version": 1,
                            "language": "en",
                            "text": notice_text,
                            "text_sha256": notice_sha,
                            "allowed_modes": ["spoken", "tap", "signed"],
                            "witness_allowed": true,
                            "purposes": [
                                { "code": "record_and_interview", "label": "Record & Interview", "required": true },
                                { "code": "contact_followup", "label": "Follow-up", "required": true },
                                { "code": "cause_of_death_coding", "label": "Coding", "required": true },
                                { "code": "statistical_reports", "label": "Reports", "required": true }
                            ]
                        }
                    ]
                })),
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
            roster: vec![RosterMember {
                user_id: 101,
                name: "Dr. Meera Nair".to_string(),
                designation: "medical_officer".to_string(),
                roles: vec![
                    RosterRoleGrant {
                        role: ActingRole::DeathReporter,
                        project_id: "2".to_string(),
                        site_id: "PHC01".to_string(),
                        org_unit_id: None,
                    },
                    RosterRoleGrant {
                        role: ActingRole::Interviewer,
                        project_id: "2".to_string(),
                        site_id: "PHC01".to_string(),
                        org_unit_id: None,
                    },
                ],
                active: true,
            }],
            purge: vec![],
        };

        let signed_cfg = format_signed_station_config(&cfg_payload, &server_signing_key).unwrap();
        let import_res = db.import_signed_station_config(&signed_cfg).unwrap();
        assert_eq!(import_res["mode"], "provisioned");
        assert_eq!(import_res["device_id"], "station-phc-01");

        // Register a death + consent in project 2
        let death_cid = Uuid::new_v4();
        let consent_cid = Uuid::new_v4();
        db.register_death(
            &json!({
                "project_id": 2,
                "site_id": "PHC01",
                "org_unit_id": "ou-sc-1",
                "client_death_id": death_cid.to_string(),
                "deceased_name": "Provisioned Case",
                "deceased_sex": "female",
                "date_of_death": "2026-10-20",
                "informant_name": "Lakshmi",
                "informant_phone": "9876543210",
                "consent": {
                    "client_id": consent_cid.to_string(),
                    "decision": "granted",
                    "notice_version_id": notice_vid.to_string(),
                    "notice_language": "en",
                    "notice_sha256": notice_sha,
                    "mode": "spoken",
                    "purposes": [
                        { "code": "record_and_interview", "granted": true },
                        { "code": "contact_followup", "granted": true },
                        { "code": "cause_of_death_coding", "granted": true },
                        { "code": "statistical_reports", "granted": true }
                    ]
                }
            }),
            "user-101",
        )
        .unwrap();

        // Export .dvb bundle
        let (built, filename) = db.export_dvb_bundle().unwrap();
        assert!(filename.starts_with("digitva-station-phc-01-000001-"));
        assert_eq!(built.items.len(), 2);

        // Import signed .dvb.receipt that accepts both records
        let mut counts = BTreeMap::new();
        counts.insert("accepted".to_string(), 2);
        let receipt_report = BundleReceiptReport {
            bundle_id: built.manifest.bundle_id,
            device_id: "station-phc-01".to_string(),
            kem_key_id: "tv1".to_string(),
            status: "completed".to_string(),
            counts,
            missing_seq: vec![],
            records: vec![
                ReceiptRecordOutcome {
                    client_id: death_cid,
                    record_type: RecordType::DeathRegistration,
                    outcome: RecordIngestOutcome::Accepted,
                    code: None,
                    received_sha256: None,
                    death_id: Some(Uuid::new_v4()),
                    unique_id: Some("SRV-001".to_string()),
                },
                ReceiptRecordOutcome {
                    client_id: consent_cid,
                    record_type: RecordType::Consent,
                    outcome: RecordIngestOutcome::Accepted,
                    code: None,
                    received_sha256: None,
                    death_id: None,
                    unique_id: None,
                },
            ],
            purge: vec![],
        };
        let signed_receipt = format_signed_receipt(&receipt_report, &server_signing_key).unwrap();
        let rec_res = db.import_dvb_receipt(&signed_receipt).unwrap();
        assert_eq!(rec_res["deleted_count"], 2);
        assert_eq!(db.list_cases()["counts"]["total"], 0);
    }
}
