//! A deterministic sample bundle (`tests/fixtures/bundles/sample_bundle.dvb`,
//! bundle spec section 7 vector 3; the start of digitva-gb8w.6). Built with
//! `build_bundle_deterministic` from the server's signed station config
//! fixture, the published test KEM key `tv1` and the test station key seed
//! `[0x52; 32]`; `tests/test_bundle_fixture.py` opens it with the server's
//! ingest parser. Regenerate after an intended format change with
//! `DIGITVA_WRITE_BUNDLE_FIXTURE=1 cargo test -p digitva-bundle --test bundle_fixture`.

use chrono::{TimeZone, Utc};
use digitva_bundle::{
    build_bundle_deterministic, sha256_hex, verify_and_plan_receipt, ActingRole, BundleRecordEnvelope, BundleRecordPayload,
    ConsentDecision, ConsentMode, ConsentPurposeGrant, ConsentRecord, DeathRef, DeathRegistrationRecord,
    DeterministicBundleRandomness, InterviewCompletion, InterviewDraftMeta, InterviewSubmissionRecord,
    BundleError, StationSigningKey, VerifiedStationConfig,
};
use serde_json::json;
use std::collections::BTreeMap;
use std::path::PathBuf;
use uuid::Uuid;

const DEVICE_ID: &str = "0b8d6c2e-1f3a-4c5b-9d7e-8f9a0b1c2d3e";
const ORG_UNIT: &str = "3c9e1f2a-5b6d-4e7f-8a9b-0c1d2e3f4a5b";

fn repo_file(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..").join(relative)
}

fn id(n: u8) -> Uuid {
    Uuid::parse_str(&format!("5e1f0c3a-0000-4000-8000-0000000000{n:02x}")).unwrap()
}

fn envelope(client_id: Uuid, payload: BundleRecordPayload) -> BundleRecordEnvelope {
    BundleRecordEnvelope {
        client_id,
        project_id: "TST001".to_string(),
        actor_user_id: 7,
        acting_role: ActingRole::Interviewer,
        recorded_at: "2026-10-21T15:05:00+05:30".to_string(),
        payload,
    }
}

fn sample_bundle() -> Vec<u8> {
    let text = std::fs::read_to_string(repo_file("tests/fixtures/station_config/station_config.signed")).unwrap();
    let config = VerifiedStationConfig::parse_and_verify(&text, DEVICE_ID, None).expect("station config");
    let station_key = StationSigningKey::from_secret_bytes(&[0x52u8; 32]);
    let (death, consent, interview) = (id(1), id(2), id(3));

    let mut fields = BTreeMap::new();
    fields.insert("deceased_name".to_string(), json!("Ram Lal"));
    fields.insert("deceased_sex".to_string(), json!("male"));
    fields.insert("date_of_death".to_string(), json!("2026-10-18"));
    fields.insert("age_years".to_string(), json!(70));
    fields.insert("informant_name".to_string(), json!("Sita Devi"));
    fields.insert("informant_phone".to_string(), json!("9876500000"));
    let answers_json = r#"{"Id10013":"yes","Id10017":"Ram","Id10073":"XXXXXXXXX123"}"#.to_string();
    let records = vec![
        envelope(death, BundleRecordPayload::DeathRegistration(DeathRegistrationRecord {
            site_id: "TS01".to_string(),
            org_unit_id: Some(ORG_UNIT.to_string()),
            fields,
            identifiers: None,
            consent_client_id: Some(consent),
        })),
        envelope(consent, BundleRecordPayload::Consent(ConsentRecord {
            death_ref: DeathRef::client_death(death),
            client_draft_id: None,
            notice_version_id: Uuid::parse_str("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d").unwrap(),
            notice_language: "hi".to_string(),
            notice_sha256: "f9e7f8bfa6527fc40a4b97b5e8ad528c39240ba732ce4126dd1ae0e63e89154c".to_string(),
            decision: ConsentDecision::Granted,
            purposes: vec![ConsentPurposeGrant { code: "record_interview".to_string(), granted: true }],
            mode: ConsentMode::Tap,
            witness_present: false,
            supersedes_client_id: None,
        })),
        envelope(interview, BundleRecordPayload::InterviewSubmission(InterviewSubmissionRecord {
            site_id: "TS01".to_string(),
            org_unit_id: Some(ORG_UNIT.to_string()),
            death_ref: DeathRef::client_death(death),
            draft: InterviewDraftMeta {
                instrument_version: "2023072701".to_string(),
                definition_sha256: Some("0".repeat(64)),
                definition_extensions: None,
                started_at: "2026-10-21T14:00:00+05:30".to_string(),
                completed_at: Some("2026-10-21T14:40:00+05:30".to_string()),
                device_clock_at: None,
                interview_outcome: "completed".to_string(),
            },
            completion: InterviewCompletion { valid: true, issues: vec![] },
            answers_sha256: sha256_hex(answers_json.as_bytes()),
            answers_json,
            consent_client_id: Some(consent),
        })),
    ];
    let mut record_nonces = BTreeMap::new();
    for (n, client_id) in [death, consent, interview].into_iter().enumerate() {
        record_nonces.insert(client_id, [0x60 + n as u8; 12]);
    }
    let randomness = DeterministicBundleRandomness {
        bundle_id: Uuid::parse_str("b0000000-0000-4000-8000-000000000001").unwrap(),
        dek: [0x11; 32],
        mlkem_m: [0x22; 32],
        x25519_eph_scalar: [0x33; 32],
        wrap_nonce: [0x44; 12],
        record_nonces,
    };
    let now = Utc.with_ymd_and_hms(2026, 10, 21, 10, 0, 0).unwrap();
    build_bundle_deterministic(&config, &station_key, DEVICE_ID, 1, "0.1.0", now, &records, &randomness)
        .expect("bundle")
        .bytes
}

#[test]
fn sample_bundle_matches_the_fixture_byte_for_byte() {
    let bytes = sample_bundle();
    assert_eq!(bytes, sample_bundle(), "deterministic");
    let path = repo_file("tests/fixtures/bundles/sample_bundle.dvb");
    if std::env::var_os("DIGITVA_WRITE_BUNDLE_FIXTURE").is_some() {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, &bytes).unwrap();
    }
    let fixture = std::fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    assert_eq!(bytes, fixture, "the writer changed: regenerate the fixture and re-run tests/test_bundle_fixture.py");
}

/// The server's signed receipt for the sample (`tests/fixtures/bundles/sample_receipt.dvr`,
/// regenerated by `tests/test_bundle_fixture.py`) verifies under the server key the
/// station pinned from its config, and plans the deletion of every record.
#[test]
fn server_receipt_verifies_and_plans_deletion() {
    let receipt = std::fs::read_to_string(repo_file("tests/fixtures/bundles/sample_receipt.dvr")).unwrap();
    let text = std::fs::read_to_string(repo_file("tests/fixtures/station_config/station_config.signed")).unwrap();
    let config = VerifiedStationConfig::parse_and_verify(&text, DEVICE_ID, None).unwrap();
    let answers_json = r#"{"Id10013":"yes","Id10017":"Ram","Id10073":"XXXXXXXXX123"}"#;
    let mut hashes = BTreeMap::new();
    hashes.insert(id(3), sha256_hex(answers_json.as_bytes()));
    let plan = verify_and_plan_receipt(&receipt, DEVICE_ID, &config.server_verifying_key, &hashes).expect("receipt");
    assert_eq!(plan.deletable_client_ids, vec![id(1), id(2), id(3)]);
    assert!(plan.purge_client_ids.is_empty());
    assert!(plan.hash_mismatched_interviews.is_empty());
    let other = StationSigningKey::from_secret_bytes(&[7u8; 32]);
    assert!(matches!(
        verify_and_plan_receipt(&receipt, DEVICE_ID, &other.public_key_bytes(), &hashes),
        Err(BundleError::ReceiptInvalid(_))
    ));
}
