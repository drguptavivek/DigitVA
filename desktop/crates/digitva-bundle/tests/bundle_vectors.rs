//! The bundle conformance vectors (`tests/fixtures/bundles/vectors/`, digitva-gb8w.6;
//! scenario table in `tests/bundle_vectors.py`, regenerated with
//! `DIGITVA_WRITE_BUNDLE_VECTORS=1 python -m pytest tests/test_bundle_vectors.py`).
//! Every vector is checked here with this crate's verifier against the
//! `container` facts in `expected.json` (signature, body hash, record types),
//! the same facts `tests/test_bundle_vectors.py` checks with the server's
//! parser. The station writer is held to the same reader: its own sample bundle
//! passes, a tampered copy fails, and it refuses (typed error, nothing written)
//! what the server would reject per record: informant data without consent, an
//! expired or foreign station config, an oversize record, too many records.

use chrono::{TimeZone, Utc};
use digitva_bundle::{
    build_bundle_deterministic, compute_signing_key_id, sha256_hex, verify_ed25519_signature_line, ActingRole,
    BundleError, BundleRecordEnvelope, BundleRecordPayload, DeathRegistrationRecord, DeathRef,
    DeterministicBundleRandomness, InterviewCompletion, InterviewDraftMeta, InterviewSubmissionRecord,
    StationSigningKey, VerifiedStationConfig, BUNDLE_MAX_RECORDS,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::PathBuf;
use uuid::Uuid;

const DEVICE_ID: &str = "0b8d6c2e-1f3a-4c5b-9d7e-8f9a0b1c2d3e";
const ORG_UNIT: &str = "3c9e1f2a-5b6d-4e7f-8a9b-0c1d2e3f4a5b";
const DOMAIN: &[u8] = b"digitva-bundle-v1\x00";

fn repo_file(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..").join(relative)
}

/// The station key and the second key the unknown-signing-key vector is signed with.
fn keys() -> Vec<StationSigningKey> {
    vec![StationSigningKey::from_secret_bytes(&[0x52; 32]), StationSigningKey::from_secret_bytes(&[0x53; 32])]
}

/// What a verifier learns of one bundle file.
struct Opened {
    manifest: Value,
    signature_ok: bool,
    body_hash_ok: bool,
    record_types: Vec<String>,
}

/// Parse and verify *bytes* the way the server's ingest does before decryption
/// (bundle spec 5.2): the signature under the key `signing_key_id` names.
fn open(bytes: &[u8]) -> Opened {
    assert!(bytes.ends_with(b"\n") && !bytes.contains(&b'\r'), "UTF-8 lines ending in LF");
    let mut parts = bytes.splitn(3, |b| *b == b'\n');
    let (line1, line2, body) = (parts.next().unwrap(), parts.next().unwrap(), parts.next().unwrap());
    let manifest: Value = serde_json::from_slice(line1).expect("manifest");
    let key_id = manifest["signing_key_id"].as_str().expect("signing_key_id");
    let public = keys()
        .iter()
        .map(|k| k.public_key_bytes())
        .find(|p| compute_signing_key_id(p) == key_id)
        .expect("a test key");
    let signature_ok =
        verify_ed25519_signature_line(&public, DOMAIN, line1, std::str::from_utf8(line2).unwrap()).is_ok();
    let record_types = body
        .split(|b| *b == b'\n')
        .filter(|l| !l.is_empty())
        .map(|l| serde_json::from_slice::<Value>(l).unwrap()["record_type"].as_str().unwrap().to_string())
        .collect();
    let body_hash_ok = manifest["body_sha256"].as_str() == Some(sha256_hex(body).as_str());
    Opened { manifest, signature_ok, body_hash_ok, record_types }
}

fn expected() -> Value {
    let text = std::fs::read_to_string(repo_file("tests/fixtures/bundles/vectors/expected.json")).unwrap();
    serde_json::from_str(&text).unwrap()
}

fn vector(file: &str) -> Vec<u8> {
    let path = repo_file(&format!("tests/fixtures/bundles/vectors/{file}"));
    std::fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()))
}

#[test]
fn every_vector_is_what_expected_json_says() {
    let mut checked = 0;
    for (name, entry) in expected().as_object().unwrap() {
        let (Some(files), Some(container)) = (entry["files"].as_array(), entry["container"].as_array()) else {
            continue; // synthetic (generated at test time)
        };
        for (file, want) in files.iter().zip(container) {
            let opened = open(&vector(file.as_str().unwrap()));
            let m = &opened.manifest;
            assert_eq!(opened.signature_ok, want["signature_ok"].as_bool().unwrap(), "{name}: {file} signature");
            assert_eq!(opened.body_hash_ok, want["body_hash_ok"].as_bool().unwrap(), "{name}: {file} body hash");
            assert_eq!(json!(opened.record_types), want["record_types"], "{name}: {file} record types");
            assert_eq!(m["device_id"], DEVICE_ID, "{name}");
            assert_eq!(m["station_config_id"], "6f1c2b3a-4d5e-4f60-8a71-92b3c4d5e6f7", "{name}");
            assert_eq!(m["project_ids"], json!(["TST001"]), "{name}");
            checked += 1;
        }
    }
    assert!(checked >= 20, "only {checked} vectors checked");
}

/// The replay vectors: the same bytes twice; one `bundle_id` with other bytes;
/// the same records in a later bundle (new id, next sequence number).
#[test]
fn replay_vectors_carry_the_ids_the_scenarios_claim() {
    assert_eq!(vector("replayed.dvb"), vector("replayed.2.dvb"));
    let (a, b) = (open(&vector("replayed_other_bytes.dvb")), open(&vector("replayed_other_bytes.2.dvb")));
    assert_eq!(a.manifest["bundle_id"], b.manifest["bundle_id"]);
    assert_ne!(vector("replayed_other_bytes.dvb"), vector("replayed_other_bytes.2.dvb"));
    let (first, later) = (open(&vector("same_records_later_bundle.dvb")), open(&vector("same_records_later_bundle.2.dvb")));
    assert_ne!(first.manifest["bundle_id"], later.manifest["bundle_id"]);
    assert_eq!((first.manifest["bundle_seq"].as_u64(), later.manifest["bundle_seq"].as_u64()), (Some(1), Some(2)));
}

/// The coder vectors: one result per station mode, the case first in its own bundle.
#[test]
fn coder_vectors_hold_a_coding_result_each() {
    for name in ["coder_icd11_doris", "coder_icd10", "coder_mode_mismatch"] {
        assert_eq!(open(&vector(&format!("{name}.dvb"))).record_types, ["death_registration", "interview_submission"]);
        let result = open(&vector(&format!("{name}.2.dvb")));
        assert_eq!((result.record_types, result.manifest["bundle_seq"].as_u64()), (vec!["coding_result".to_string()], Some(2)));
    }
}

// ── the station writer against the same reader ─────────────────────────────

/// The Rust-written sample bundle (`bundle_fixture.rs`) verifies, a flipped
/// body byte breaks the body hash, a changed manifest breaks the signature.
#[test]
fn the_writers_sample_verifies_and_its_tampered_copies_do_not() {
    let sample = std::fs::read(repo_file("tests/fixtures/bundles/sample_bundle.dvb")).unwrap();
    let ok = open(&sample);
    assert!(ok.signature_ok && ok.body_hash_ok);
    assert_eq!(ok.record_types, ["death_registration", "consent", "interview_submission"]);

    let mut body_flipped = sample.clone();
    let at = body_flipped.len() - 5; // inside the last record's ciphertext
    body_flipped[at] = if body_flipped[at] == b'A' { b'B' } else { b'A' };
    let flipped = open(&body_flipped);
    assert!(flipped.signature_ok && !flipped.body_hash_ok);

    let text = String::from_utf8(sample).unwrap().replacen("\"app_version\":\"0.1.0\"", "\"app_version\":\"9.9.9\"", 1);
    let changed = open(text.as_bytes());
    assert!(!changed.signature_ok, "a manifest changed after signing must not verify");
}

fn config() -> VerifiedStationConfig {
    let text = std::fs::read_to_string(repo_file("tests/fixtures/station_config/station_config.signed")).unwrap();
    VerifiedStationConfig::parse_and_verify(&text, DEVICE_ID, None).expect("station config")
}

fn envelope(payload: BundleRecordPayload) -> BundleRecordEnvelope {
    BundleRecordEnvelope {
        client_id: Uuid::new_v4(),
        project_id: "TST001".to_string(),
        actor_user_id: 7,
        acting_role: ActingRole::Interviewer,
        recorded_at: "2026-10-21T15:05:00+05:30".to_string(),
        payload,
    }
}

fn registration(fields: &[(&str, Value)]) -> BundleRecordEnvelope {
    envelope(BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
        site_id: "TS01".to_string(),
        org_unit_id: Some(ORG_UNIT.to_string()),
        fields: fields.iter().map(|(k, v)| (k.to_string(), v.clone())).collect::<BTreeMap<_, _>>(),
        identifiers: None,
        consent_client_id: None,
    }))
}

fn interview(answers_json: String) -> BundleRecordEnvelope {
    envelope(BundleRecordPayload::InterviewSubmission(InterviewSubmissionRecord {
        site_id: "TS01".to_string(),
        org_unit_id: Some(ORG_UNIT.to_string()),
        death_ref: DeathRef::client_death(Uuid::new_v4()),
        draft: InterviewDraftMeta {
            instrument_version: "2023072701".to_string(),
            definition_sha256: None,
            definition_extensions: None,
            started_at: "2026-10-21T14:00:00+05:30".to_string(),
            completed_at: None,
            device_clock_at: None,
            interview_outcome: "completed".to_string(),
        },
        completion: InterviewCompletion { valid: true, issues: vec![] },
        answers_sha256: sha256_hex(answers_json.as_bytes()),
        answers_json,
        consent_client_id: None,
    }))
}

fn write(
    config: &VerifiedStationConfig,
    device_id: &str,
    now: chrono::DateTime<Utc>,
    records: &[BundleRecordEnvelope],
) -> Result<Vec<u8>, BundleError> {
    let randomness = DeterministicBundleRandomness {
        bundle_id: Uuid::new_v4(),
        dek: [0x11; 32],
        mlkem_m: [0x22; 32],
        x25519_eph_scalar: [0x33; 32],
        wrap_nonce: [0x44; 12],
        record_nonces: records.iter().map(|r| (r.client_id, [0x60; 12])).collect(),
    };
    let key = StationSigningKey::from_secret_bytes(&[0x52; 32]);
    build_bundle_deterministic(config, &key, device_id, 1, "0.1.0", now, records, &randomness).map(|b| b.bytes)
}

fn on_21_oct() -> chrono::DateTime<Utc> {
    Utc.with_ymd_and_hms(2026, 10, 21, 10, 0, 0).unwrap()
}

/// Offline always needs consent for informant data (contract decision 4): the
/// writer refuses what the server would reject `consent_required`.
#[test]
fn the_writer_refuses_informant_data_without_consent() {
    let records = [registration(&[("deceased_name", json!("Ram Lal")), ("informant_name", json!("Sita Devi"))])];
    let err = write(&config(), DEVICE_ID, on_21_oct(), &records).unwrap_err();
    assert!(matches!(err, BundleError::ConsentRequired { .. }), "{err:?}");
    // The same registration without informant data is written.
    let clean = [registration(&[("deceased_name", json!("Ram Lal"))])];
    assert!(open(&write(&config(), DEVICE_ID, on_21_oct(), &clean).unwrap()).signature_ok);
}

/// The writer refuses an expired config before writing, by the rule the
/// server applies to `created_at` (vector `expired_station_config`,
/// `station_config_expired`).
#[test]
fn the_writer_refuses_an_expired_or_foreign_station_config() {
    let records = [registration(&[("deceased_name", json!("Ram Lal"))])];
    let after_expiry = Utc.with_ymd_and_hms(2027, 4, 20, 0, 0, 0).unwrap(); // config expires 2027-04-19T09:30Z
    let err = write(&config(), DEVICE_ID, after_expiry, &records).unwrap_err();
    assert!(matches!(err, BundleError::StationConfigExpired { .. }), "{err:?}");
    let other = "11111111-2222-4333-8444-555555555555";
    let err = write(&config(), other, on_21_oct(), &records).unwrap_err();
    assert!(matches!(err, BundleError::StationConfigDeviceMismatch { .. }), "{err:?}");
}

/// The limits the server answers 413: the writer stops at its own (stricter
/// per-record) bounds before any ciphertext exists.
#[test]
fn the_writer_refuses_an_oversize_record_and_too_many_records() {
    let huge = format!("{{\"Id10017\":\"{}\"}}", "x".repeat(1024 * 1024));
    let err = write(&config(), DEVICE_ID, on_21_oct(), &[interview(huge)]).unwrap_err();
    assert!(matches!(err, BundleError::SizeLimitExceeded(_)), "{err:?}");
    let many: Vec<_> = (0..=BUNDLE_MAX_RECORDS).map(|_| registration(&[("deceased_name", json!("Ram Lal"))])).collect();
    let err = write(&config(), DEVICE_ID, on_21_oct(), &many).unwrap_err();
    assert!(matches!(err, BundleError::RecordCountOutOfRange(n) if n == BUNDLE_MAX_RECORDS + 1), "{err:?}");
}
