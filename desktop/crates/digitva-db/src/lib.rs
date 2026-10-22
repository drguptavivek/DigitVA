pub mod catalog;
pub mod consent;
pub mod doris_prefill;
pub mod instrument;
pub mod roster;

use crate::catalog::{ensure_catalog_seeded, lookup_va_definition_for_icd, search_icd_catalog};
use crate::consent::{
    append_consent_record, assert_informant_consent_before_write, get_latest_consent_for_case,
    parse_contract_consent_config, purge_informant_pii_for_death_id, upsert_project_consent_config,
    ConsentEnvelopeInput, ConsentRefusal,
};
use crate::instrument::ServedDefinition;
use crate::roster::{
    get_active_actor, get_roster_snapshot, init_roster_tables_and_seed, normalise_acting_role,
    replace_provisioned_roster, switch_active_actor, update_sandbox_designations,
    upsert_sandbox_roster_member, ActiveActorContext, StationRosterMember, StationRosterSnapshot,
    UpsertRosterMemberInput,
};
use chrono::Utc;
use digitva_bundle::{
    build_bundle, sha256_hex, validate_bundle_record, verify_and_plan_receipt, ActingRole, BuiltBundle,
    BundleRecordEnvelope, BundleRecordPayload, CodingResultKind, CodingResultRecord,
    ConsentDecision, ConsentMode, ConsentPurposeGrant, ConsentRecord, DeathCorrectionRecord,
    DeathRef, DeathRegistrationRecord, RecordIngestOutcome, IdentifiersSetRecord, InterviewCompletion,
    InterviewDraftMeta, InterviewSubmissionRecord, RosterRoleGrant, StationConfigPayload,
    StationProjectConfig, StationSigningKey, VerifiedStationConfig,
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

/// The station app version sent in bundle manifests and the enrolment file (server limit 32 chars).
pub const STATION_APP_VERSION: &str = "0.1.0-offline";

/// Case list page size, as the server's `REPORTED_PAGE_DEFAULT` / `WORKLIST_PAGE_DEFAULT`.
pub const CASE_PAGE_DEFAULT: i64 = 50;
/// Largest case list page, as the server's `REPORTED_PAGE_MAX` / `WORKLIST_PAGE_MAX`.
pub const CASE_PAGE_MAX: i64 = 200;

/// Station coding modes (Settings): ICD-11 with the DORIS certificate (the server's
/// `unmasked_doris` workspace on ICD-11), or ICD-10 (the server's `unmasked_simple` on ICD-10).
pub const CODING_MODE_ICD11_DORIS: &str = "icd11_doris";
pub const CODING_MODE_ICD10: &str = "icd10";
pub const CODING_MODES: [&str; 2] = [CODING_MODE_ICD11_DORIS, CODING_MODE_ICD10];

/// A stored config `coding_mode` (`"icd10"`, `null`) as a known station mode; anything else,
/// `null` included, means the station does not code the project.
fn parse_coding_mode_json(raw: &str) -> Option<String> {
    serde_json::from_str::<Option<String>>(raw)
        .ok()
        .flatten()
        .filter(|m| CODING_MODES.contains(&m.as_str()))
}

/// Death-register values a draft's prefill is built from (`interview_prefill`).
#[derive(Default)]
struct RegisterPrefill<'a> {
    deceased_name: Option<&'a str>,
    deceased_sex: Option<&'a str>,
    date_of_death: Option<&'a str>,
    age_years: Option<f64>,
    date_of_birth: Option<&'a str>,
    date_of_birth_partial: Option<&'a str>,
    place_of_death: Option<&'a str>,
    informant_name: Option<&'a str>,
    father_name: Option<&'a str>,
    mother_name: Option<&'a str>,
    abha_number: Option<&'a str>,
    abha_address: Option<&'a str>,
    /// House/street, village/ward, landmark, address: joined with ", " as the server's
    /// `_case_address`.
    address_parts: [Option<&'a str>; 4],
    /// The unit's ", "-joined path (the register's `org_unit_name`).
    org_path: Option<&'a str>,
}

/// The Id10058 choice for a free-text register place of death (the server's
/// `_who_place_of_death`): exact choice first, then keywords in this order ("on the way to
/// hospital" is en route, "nursing home" a facility). None when nothing matches: the question is
/// then left unasked, never defaulted to `other` (it is a coding input).
fn who_place_of_death(text: &str) -> Option<&'static str> {
    let value = text.to_lowercase().replace('_', " ").split_whitespace().collect::<Vec<_>>().join(" ");
    let exact = [
        ("hospital", "hospital"),
        ("other health facility", "other_health_facility"),
        ("home", "home"),
        ("on route to hospital or facility", "on_route_to_hospital_or_facility"),
        ("other", "other"),
    ];
    if let Some((_, choice)) = exact.iter().find(|(label, _)| *label == value) {
        return Some(choice);
    }
    let keywords: [(&str, &[&str]); 4] = [
        ("on_route_to_hospital_or_facility", &["route", "on the way", "transit", "ambulance"]),
        (
            "other_health_facility",
            &["phc", "chc", "health centre", "health center", "sub centre", "subcentre", "clinic",
              "dispensary", "nursing home", "facility"],
        ),
        ("hospital", &["hospital"]),
        ("home", &["home", "house", "residence"]),
    ];
    keywords
        .iter()
        .find(|(_, words)| words.iter().any(|w| value.contains(w)))
        .map(|(choice, _)| *choice)
}

/// A draft's prefill in the server's shape (`_prefill_from_death`, docs/policy/web-intake.md),
/// which the app's `initialDataFromPrefill` reads: `interviewer` (the acting roster member),
/// `deceased` (only with name, sex and date of death), WHO `answers` and `lockedQuestionNames`.
/// The registered age goes to `age_group` with `age_adult` (12-119, as `ageInYears`) or the
/// child fields (1-11); age 0 and an exact date of birth send none. Id10051 is the WHO yes/no
/// question that opens Id10055/Id10057, answered "yes" only when those are prefilled; it never
/// carries an age.
fn interview_prefill(actor: &ActiveActorContext, reg: &RegisterPrefill) -> Value {
    let present = |v: Option<&str>| v.map(str::trim).filter(|v| !v.is_empty()).map(str::to_string);
    let mut interviewer = Map::new();
    let mut locked: Vec<&str> = vec![];
    if let Some(name) = present(Some(actor.name.as_str())) {
        interviewer.insert("name".to_string(), json!(name));
    }
    if let Some(id) = actor.user_id {
        interviewer.insert("id".to_string(), json!(id.to_string()));
        locked.push("Id10010c");
    }
    let mut answers = Map::new();
    let address: Vec<String> = reg.address_parts.iter().filter_map(|p| present(*p)).collect();
    let address = address.join(", ");
    let org_path = present(reg.org_path).unwrap_or_default();
    let place: Vec<&str> = [org_path.as_str(), address.as_str()].into_iter().filter(|p| !p.is_empty()).collect();
    let place = place.join("; ");
    let residence = if address.is_empty() { org_path.clone() } else { address.clone() };
    if !place.is_empty() {
        answers.insert("Id10057".to_string(), json!(place));
    }
    if !residence.is_empty() {
        answers.insert("Id10055".to_string(), json!(residence));
    }
    if !place.is_empty() || !residence.is_empty() {
        answers.insert("Id10051".to_string(), json!("yes"));
    }
    if let Some(choice) = reg.place_of_death.and_then(who_place_of_death) {
        answers.insert("Id10058".to_string(), json!(choice));
    }
    for (question, value) in [("Id10007", reg.informant_name), ("Id10061", reg.father_name), ("Id10062", reg.mother_name)] {
        if let Some(value) = present(value) {
            answers.insert(question.to_string(), json!(value));
        }
    }
    let mut prefill = Map::new();
    let name = present(reg.deceased_name);
    let date_of_death = present(reg.date_of_death);
    let sex = present(reg.deceased_sex);
    if let (Some(name), Some(date_of_death), Some(sex)) = (name, date_of_death, sex) {
        let words: Vec<&str> = name.split_whitespace().collect();
        let given = if words.len() > 1 { &words[..words.len() - 1] } else { &words[..] };
        let mut deceased = json!({
            "givenNames": given.join(" "),
            "sex": if sex == "male" || sex == "female" { sex.as_str() } else { "undetermined" },
            "dateOfDeath": date_of_death,
        });
        if words.len() > 1 {
            deceased["surname"] = json!(words[words.len() - 1]);
        }
        let age = reg.age_years.filter(|a| a.fract() == 0.0).map(|a| a as i64);
        if let Some(dob) = present(reg.date_of_birth) {
            deceased["dateOfBirth"] = json!(dob);
        } else if let Some(age @ 12..=119) = age {
            deceased["ageInYears"] = json!(age);
            answers.insert("age_group".to_string(), json!("adult"));
            answers.insert("age_adult".to_string(), json!(age));
        } else if let Some(age @ 1..=11) = age {
            for (k, v) in [("Id10020", json!("no")), ("age_group", json!("child")), ("age_child_unit", json!("years")), ("age_child_years", json!(age))] {
                answers.insert(k.to_string(), v);
            }
        }
        if present(reg.date_of_birth).is_none()
            && let Some(partial) = present(reg.date_of_birth_partial)
        {
            answers.insert("Id10020".to_string(), json!("no"));
            if partial.len() == 7 {
                answers.insert("dob_precision".to_string(), json!("month_year"));
                answers.insert("dob_month_year".to_string(), json!(format!("{partial}-01")));
            } else {
                answers.insert("dob_precision".to_string(), json!("year"));
                answers.insert("dob_year".to_string(), json!(format!("{partial}-01-01")));
            }
        }
        prefill.insert("deceased".to_string(), deceased);
        for (question, value) in [("abha_number", reg.abha_number), ("abha_address", reg.abha_address)] {
            if let Some(value) = present(value) {
                answers.insert(question.to_string(), json!(value));
                locked.push(question);
            }
        }
    }
    locked.sort_unstable();
    prefill.insert("interviewer".to_string(), Value::Object(interviewer));
    prefill.insert("answers".to_string(), redact_payload_national_ids(&Value::Object(answers)).0);
    prefill.insert("lockedQuestionNames".to_string(), json!(locked));
    Value::Object(prefill)
}

/// The deceased's age in whole years from a WHO 2022 payload, by the server's precedence
/// (`who_age_normalization.normalize_who_2022_age`): neonate hours/days, then the child or adult
/// branch's days, months or years, then any of them; None when the payload records no age.
/// Id10051 is a yes/no question, never an age.
fn who_age_years(payload: &Value) -> Option<String> {
    let num = |k: &str| -> Option<f64> {
        match payload.get(k)? {
            Value::Number(n) => n.as_f64(),
            Value::String(s) => s.trim().parse().ok(),
            _ => None,
        }
        .filter(|v: &f64| v.is_finite())
    };
    let flag = |k: &str| payload.get(k).is_some_and(|v| matches!(v.to_string().trim_matches('"'), "1" | "1.0" | "true" | "True"));
    let (days, months, years, years2, final_years) =
        (num("ageInDays"), num("ageInMonths"), num("ageInYears"), num("ageInYears2"), num("finalAgeInYears"));
    let from_days = |d: f64| d / 365.25;
    let age = if num("age_neonate_hours").is_some() {
        Some(0.0)
    } else if let Some(d) = num("age_neonate_days") {
        Some(from_days(d))
    } else if flag("isNeonatal") && days.is_some() {
        days.map(from_days)
    } else if flag("isChild") {
        days.map(from_days).or(months.map(|m| m / 12.0)).or(years).or(years2).or(final_years)
    } else if flag("isAdult") && (years.is_some() || years2.is_some() || final_years.is_some()) {
        years.or(years2).or(final_years)
    } else {
        years.or(days.map(from_days)).or(months.map(|m| m / 12.0)).or(years2).or(final_years)
    };
    age.map(|a| (a.floor() as i64).to_string())
}

/// The `interview_outcome` a submission is stored with (the server's `_interview_outcome`):
/// `refused` when consent (Id10013) is no, `completed` when the form reports itself valid, else
/// the interviewer's own pick of `partially_completed` or `respondent_unavailable`. None when the
/// form is invalid and nothing was picked (the server refuses that submit with 422).
fn interview_outcome(data: &Value, completion_valid: bool) -> Option<&'static str> {
    if data["Id10013"].as_str().is_some_and(|c| c.trim().eq_ignore_ascii_case("no")) {
        return Some("refused");
    }
    if completion_valid {
        return Some("completed");
    }
    match data["interview_outcome"].as_str() {
        Some("partially_completed") => Some("partially_completed"),
        Some("respondent_unavailable") => Some("respondent_unavailable"),
        _ => None,
    }
}

/// SQL predicate for submissions whose project the station codes: drops the projects a
/// provisioned config's `coding_mode` locks out (null or unknown). `?1` is 1 when provisioned.
const CODED_PROJECT_FILTER: &str = "project_id NOT IN (
    SELECT project_id FROM loc_project_config
    WHERE ?1 = 1 AND coding_mode_json IS NOT NULL
      AND coding_mode_json NOT IN ('\"icd11_doris\"', '\"icd10\"'))";

/// The raw `limit`, `cursor` and `registered` query values the shared app sends to
/// `GET /intake/deaths` and `GET /intake/cases` (`mobile/digitva-collect/src/api.ts`).
#[derive(Debug, Default, Clone, Deserialize)]
pub struct CaseListQuery {
    pub limit: Option<String>,
    pub cursor: Option<String>,
    pub registered: Option<String>,
}

/// A validated `CaseListQuery`: `limit` clamped, `after` the last `death_id` already shown.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CaseListPage {
    pub limit: i64,
    pub after: Option<i64>,
    pub registered_mine: bool,
}

impl CaseListQuery {
    /// The server's rules (`web_intake_service.reported_deaths_page`, `routes/api/intake.py`
    /// `list_deaths`): blank `limit` is 50, any whole number is clamped to 1..200, other text is
    /// refused; `registered` is blank or `mine`; `cursor` is one this station issued. The error
    /// is a message safe to return with `invalid_request`; it never echoes the value.
    pub fn parse(&self) -> Result<CaseListPage, String> {
        // As the server's `args.get(...) or default`: only an empty value is absent.
        fn given(v: &Option<String>) -> Option<&str> {
            v.as_deref().filter(|s| !s.is_empty()).map(str::trim)
        }
        let limit = match given(&self.limit) {
            None => CASE_PAGE_DEFAULT,
            Some(text) => text
                .parse::<i64>()
                .map_err(|_| "limit must be a whole number.".to_string())?
                .clamp(1, CASE_PAGE_MAX),
        };
        let after = match given(&self.cursor) {
            None => None,
            Some(text) => Some(
                text.parse::<i64>()
                    .ok()
                    .filter(|id| *id > 0)
                    .ok_or_else(|| "Invalid cursor.".to_string())?,
            ),
        };
        let registered_mine = match self.registered.as_deref() {
            None | Some("") => false,
            Some("mine") => true,
            Some(_) => return Err("registered must be mine.".to_string()),
        };
        Ok(CaseListPage { limit, after, registered_mine })
    }
}

fn query_ids(conn: &Connection, sql: &str, args: &[&dyn rusqlite::ToSql]) -> Result<Vec<i64>, String> {
    let mut stmt = conn.prepare(sql).map_err(|e| e.to_string())?;
    let ids = stmt
        .query_map(args, |r| r.get(0))
        .map_err(|e| e.to_string())?
        .collect::<Result<Vec<i64>, _>>()
        .map_err(|e| e.to_string())?;
    Ok(ids)
}

/// `{total, <state>: n}` over the death register, or one actor's registrations; one query.
fn case_state_counts(conn: &Connection, member: Option<&str>) -> Result<Value, String> {
    let row = |r: &rusqlite::Row| Ok((r.get::<_, String>(0)?, r.get::<_, i64>(1)?));
    let pairs = match member {
        Some(member) => conn
            .prepare("SELECT state, COUNT(*) FROM loc_death_register WHERE actor_member_id = ?1 GROUP BY state")
            .and_then(|mut stmt| stmt.query_map(params![member], row)?.collect::<Result<Vec<_>, _>>()),
        None => conn
            .prepare("SELECT state, COUNT(*) FROM loc_death_register GROUP BY state")
            .and_then(|mut stmt| stmt.query_map([], row)?.collect::<Result<Vec<_>, _>>()),
    }
    .map_err(|e| e.to_string())?;
    let mut counts = Map::new();
    counts.insert("total".to_string(), json!(pairs.iter().map(|(_, n)| n).sum::<i64>()));
    for (state, n) in pairs {
        counts.insert(state, json!(n));
    }
    Ok(Value::Object(counts))
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StationConfig {
    pub mode: String, // "standalone" | "provisioned"
    pub station_id: String,
    pub facility_name: String,
    pub facility_code: String,
    pub facility_type: String,
    pub facility_address: String,
    pub district_name: String,
    pub state_name: String,
    pub remote_server_url: Option<String>,
    pub provisioned_user_id: Option<String>,
    pub provisioned_user_name: Option<String>,
    pub provisioned_roles: Vec<String>,
    pub provisioned_token: Option<String>,
    pub updated_at: String,
}

/// A site a roster actor may record under in a provisioned project, with the org units
/// (`(org_unit_id, display path)`) its grants cover there.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GrantTarget {
    pub site_id: String,
    pub site_name: String,
    pub org_units: Vec<(String, String)>,
}

/// Sites and org units `grants` allow in `project` for any of `roles`, in grant order: the
/// same match the bundle's roster check makes, so a record made here passes it.
///
/// A grant without an org unit covers the project's org units mapped to the grant's site by
/// `org_unit_sites`, or every listed org unit when the config predates that map. Labels come from `site_names` / `org_unit_paths`,
/// falling back to the id for configs that predate those keys.
pub fn grant_targets(
    project: &StationProjectConfig,
    grants: &[RosterRoleGrant],
    roles: &[ActingRole],
) -> Vec<GrantTarget> {
    let label = |names: &BTreeMap<String, String>, id: &str| {
        names
            .get(id)
            .filter(|name| !name.trim().is_empty())
            .cloned()
            .unwrap_or_else(|| id.to_string())
    };
    let mut out: Vec<GrantTarget> = Vec::new();
    for grant in grants
        .iter()
        .filter(|g| g.project_id == project.project_id && roles.contains(&g.role))
    {
        let idx = match out.iter().position(|t| t.site_id == grant.site_id) {
            Some(idx) => idx,
            None => {
                out.push(GrantTarget {
                    site_id: grant.site_id.clone(),
                    site_name: label(&project.site_names, &grant.site_id),
                    org_units: Vec::new(),
                });
                out.len() - 1
            }
        };
        let covered: Vec<&String> = match &grant.org_unit_id {
            Some(ou) => vec![ou],
            // `org_unit_sites` absent (older config): every project unit, as before.
            None => project
                .org_units
                .iter()
                .filter(|ou| {
                    project.org_unit_sites.is_empty()
                        || project.org_unit_sites.get(*ou) == Some(&grant.site_id)
                })
                .collect(),
        };
        for ou in covered {
            if !out[idx].org_units.iter().any(|(id, _)| id == ou) {
                out[idx].org_units.push((ou.clone(), label(&project.org_unit_paths, ou)));
            }
        }
    }
    out
}

const ALL_ACTING_ROLES: [ActingRole; 4] = [
    ActingRole::DeathReporter,
    ActingRole::Interviewer,
    ActingRole::StationSupervisor,
    ActingRole::Coder,
];

/// Grant roles that let `acting_role` record a death registration (the bundle requires the
/// grant's role to equal the record's acting role).
/// 422 body for informant details saved without a granted consent; `informant_fields` lists the
/// non-empty fields so the form can point at them. Holds field names only, never values.
fn consent_required_for_informant(refusal: &ConsentRefusal, fields: &[(&str, Option<&str>)]) -> Value {
    let msg = refusal.message.as_str();
    let names: Vec<&str> = fields
        .iter()
        .filter(|(_, v)| v.map(|s| !s.trim().is_empty()).unwrap_or(false))
        .map(|(k, _)| *k)
        .collect();
    json!({
        "error": msg,
        "code": refusal.code.unwrap_or("consent_required_for_informant"),
        "fields": { "consent": msg },
        "informant_fields": names
    })
}

fn registration_roles(acting_role: &str) -> &'static [ActingRole] {
    match normalise_acting_role(acting_role) {
        Some("death_reporter") => &[ActingRole::DeathReporter],
        Some("interviewer") => &[ActingRole::Interviewer],
        _ => &[],
    }
}

/// Grant roles that let `acting_role` record an interview.
fn interview_roles(acting_role: &str) -> &'static [ActingRole] {
    match normalise_acting_role(acting_role) {
        Some("interviewer") => &[ActingRole::Interviewer],
        _ => &[],
    }
}

/// `(site_name, org_unit path)` when `targets` offer `org_unit_id` under `site_id`.
fn target_labels(targets: &[GrantTarget], site_id: &str, org_unit_id: &str) -> Option<(String, String)> {
    targets.iter().filter(|t| t.site_id == site_id).find_map(|t| {
        t.org_units
            .iter()
            .find(|(id, _)| id == org_unit_id)
            .map(|(_, path)| (t.site_name.clone(), path.clone()))
    })
}

/// The sandbox's fixed demo org unit names.
fn sandbox_unit_name(org_unit_id: &str, facility_name: &str) -> String {
    match org_unit_id {
        "ou-phc-1" => facility_name.to_string(),
        "ou-sc-2" => "Sub-Centre 2".to_string(),
        _ => "Sub-Centre 1".to_string(),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdentifierTypeSpec {
    pub id: i64,
    pub project_id: String,
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

            -- One row per project of the imported signed config that carries a form policy:
            -- its form-options body and {locale: translations body}, served as they are.
            CREATE TABLE IF NOT EXISTS loc_project_form_policy (
                project_id TEXT PRIMARY KEY,
                form_options_json TEXT NOT NULL,
                translations_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS consent_configs (
                project_id TEXT PRIMARY KEY,
                consent_required INTEGER NOT NULL DEFAULT 1,
                min_notice_version TEXT NOT NULL DEFAULT '0.1',
                config_json TEXT NOT NULL,
                synced_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS consent_records (
                consent_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
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
                project_id TEXT NOT NULL,
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
                project_id TEXT NOT NULL DEFAULT '1',
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
            -- registered=mine on the case list (list_cases): one actor's deaths, newest first.
            CREATE INDEX IF NOT EXISTS idx_loc_death_register_actor
                ON loc_death_register(actor_member_id, death_id);

            CREATE TABLE IF NOT EXISTS map_death_identifier (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
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
            -- The coding history reads each case's latest result.
            CREATE INDEX IF NOT EXISTS idx_loc_coding_results_va_sid
                ON loc_coding_results (va_sid, created_at);

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

        // Stores made before project ids were strings declared consent_configs.project_id
        // INTEGER PRIMARY KEY (a rowid alias), which refuses "TST001"; rebuild once, keeping rows.
        // The other tables' INTEGER project_id columns store text as-is and are read with CAST.
        let legacy_consent_configs = guard
            .query_row(
                "SELECT type FROM pragma_table_info('consent_configs') WHERE name = 'project_id'",
                [],
                |r| r.get::<_, String>(0),
            )
            .map(|t| t.eq_ignore_ascii_case("INTEGER"))
            .unwrap_or(false);
        if legacy_consent_configs {
            guard.execute_batch(
                "BEGIN;
                 CREATE TABLE consent_configs_text_id (
                     project_id TEXT PRIMARY KEY,
                     consent_required INTEGER NOT NULL DEFAULT 1,
                     min_notice_version TEXT NOT NULL DEFAULT '0.1',
                     config_json TEXT NOT NULL,
                     synced_at TEXT NOT NULL
                 );
                 INSERT INTO consent_configs_text_id
                     SELECT CAST(project_id AS TEXT), consent_required, min_notice_version, config_json, synced_at
                     FROM consent_configs;
                 DROP TABLE consent_configs;
                 ALTER TABLE consent_configs_text_id RENAME TO consent_configs;
                 COMMIT;",
            )?;
        }

        // Draft columns added after the first stations shipped: per-section answers (a save sends
        // only the sections that changed) and the client's draft meta, which holds the definition
        // pin (`instrumentVersion`, `definitionSha256`, `definitionExtensions`).
        for (column, decl) in [
            ("sections_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("meta_json", "TEXT NOT NULL DEFAULT '{}'"),
        ] {
            let present: bool = guard.query_row(
                "SELECT COUNT(*) FROM pragma_table_info('loc_va_drafts') WHERE name = ?1",
                params![column],
                |r| r.get::<_, i64>(0),
            )? > 0;
            if !present {
                guard.execute_batch(&format!("ALTER TABLE loc_va_drafts ADD COLUMN {column} {decl};"))?;
            }
        }

        // Facility details added after the first stations shipped (plain local text, editable).
        for column in ["facility_code", "facility_type", "facility_address"] {
            let present: bool = guard.query_row(
                "SELECT COUNT(*) FROM pragma_table_info('loc_station_config') WHERE name = ?1",
                params![column],
                |r| r.get::<_, i64>(0),
            )? > 0;
            if !present {
                guard.execute_batch(&format!(
                    "ALTER TABLE loc_station_config ADD COLUMN {column} TEXT NOT NULL DEFAULT '';"
                ))?;
            }
        }

        // Station Settings choices (2026-10-21): the local module selection (NULL = every module,
        // so a module a later binary adds starts enabled) and coding mode; and the coding mode each
        // saved coding record was made in.
        for (table, column, decl) in [
            ("loc_station_config", "enabled_modules_json", "TEXT"),
            ("loc_station_config", "coding_mode", "TEXT NOT NULL DEFAULT 'icd11_doris'"),
            ("loc_coding_results", "coding_mode", "TEXT"),
            // Display fields for the coder history, copied at code time so the row still reads
            // after a receipt deletes its interview (nothing else of the interview is kept).
            ("loc_coding_results", "unique_id", "TEXT"),
            ("loc_coding_results", "form_type_code", "TEXT"),
            // The config's per-project `coding_mode` as JSON (`"icd10"`, `null`); SQL NULL when
            // the config carried no key (contract 4.3, 2026-10-22).
            ("loc_project_config", "coding_mode_json", "TEXT"),
        ] {
            let present: bool = guard.query_row(
                "SELECT COUNT(*) FROM pragma_table_info(?1) WHERE name = ?2",
                params![table, column],
                |r| r.get::<_, i64>(0),
            )? > 0;
            if !present {
                guard.execute_batch(&format!("ALTER TABLE {table} ADD COLUMN {column} {decl};"))?;
            }
        }

        let now = Utc::now().to_rfc3339();
        let mut signing_seed = [0u8; 32];
        OsRng.fill_bytes(&mut signing_seed);
        let signing_key = StationSigningKey::from_secret_bytes(&signing_seed);
        let secret_hex = hex::encode(signing_seed);
        // `station_id` is this installation's device id (a UUID, the `device_id` the server
        // registers from the enrolment file); created once here and never regenerated.
        let device_id = Uuid::new_v4().to_string();
        guard.execute(
            "INSERT OR IGNORE INTO loc_station_config (
                id, mode, station_id, facility_name, district_name, state_name,
                station_signing_secret_b64, station_signing_public_b64, station_signing_key_id,
                bundle_seq, updated_at
             ) VALUES (1, 'standalone', ?5, 'Model Primary Health Centre', 'Demo District', 'Demo State', ?1, ?2, ?3, 0, ?4)",
            params![
                secret_hex,
                signing_key.public_key_base64url(),
                signing_key.signing_key_id(),
                now,
                device_id
            ],
        )?;
        // Stations seeded before device ids existed carry this fixed placeholder; it was never
        // exported (standalone mode exports nothing), so it is safe to replace once.
        guard.execute(
            "UPDATE loc_station_config SET station_id = ?1
             WHERE id = 1 AND mode = 'standalone' AND station_id = 'phc-standalone-01'",
            params![device_id],
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

    /// The enrolment file an admin pastes into Project Setup to register this never-online
    /// station: exactly `device_id`, `signing_public_key` (unpadded base64url of the raw
    /// Ed25519 key) and `app_version`. The server derives the key id itself.
    pub fn station_enrolment_file(&self) -> Result<Value, String> {
        self.with_conn(|conn| {
            conn.query_row(
                "SELECT station_id, station_signing_public_b64 FROM loc_station_config WHERE id = 1",
                [],
                |r| Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?)),
            )
            .map_err(|e| e.to_string())
        })
        .and_then(|(device_id, public_key)| {
            let public_key = public_key.ok_or_else(|| "Station signing key is missing.".to_string())?;
            Ok(json!({
                "device_id": device_id,
                "signing_public_key": public_key,
                "app_version": STATION_APP_VERSION,
            }))
        })
    }

    /// Verify and apply a signed `.digitva-station.json` two-line station config file.
    pub fn import_signed_station_config(
        &self,
        raw_two_line_text: &str,
    ) -> Result<Value, (u16, Value)> {
        let current = self.get_station_config();
        type InForce = (Option<String>, Option<String>, Option<String>);
        let (pinned_vk_hex, in_force_config_id, in_force_issued_at): InForce = self
            .with_conn(|conn| {
                conn.query_row(
                    "SELECT server_verifying_key_hex, station_config_id, config_issued_at
                     FROM loc_station_config WHERE id = 1",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .optional()
                .ok()
                .flatten()
            })
            .unwrap_or((None, None, None));

        // A config is issued for one device: the id this station exports in its enrolment
        // file (`station_enrolment_file`), standalone or provisioned alike.
        let expected_device_id = current.station_id.as_str();

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

        // Monotonic: a replayed older config must not bring back a roster member, project or
        // key the server has since removed. Re-importing the config in force is idempotent.
        if let Some(stored_at) = in_force_issued_at.as_deref() {
            let stored = chrono::DateTime::parse_from_rfc3339(stored_at)
                .map(|d| d.with_timezone(&Utc))
                .map_err(|_| {
                    (500, json!({ "error": "Corrupt stored station config time", "code": "db_error" }))
                })?;
            let same_config =
                in_force_config_id.as_deref() == Some(preview.config.config_id.to_string().as_str());
            if preview.issued_at < stored || (preview.issued_at == stored && !same_config) {
                return Err((
                    409,
                    json!({
                        "error": "This station configuration is older than the one in force.",
                        "code": "station_config_superseded"
                    }),
                ));
            }
        }

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
        // The station serves each project's form exactly as the server does, or not at all:
        // refuse a config naming a form version this binary does not carry.
        for proj in &cfg.projects {
            let Some(ref options) = proj.form_options else {
                return Err((
                    422,
                    json!({
                        "error": format!("This station config carries no form policy for project {}; issue a new station config on the server.", proj.project_id),
                        "code": "form_policy_missing"
                    }),
                ));
            };
            instrument::check_form_options(&proj.project_id, options).map_err(|msg| {
                (422, json!({ "error": msg, "code": "instrument_version_unsupported" }))
            })?;
        }
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

            // The config in force carries the whole form policy: what it does not list is gone.
            conn.execute("DELETE FROM loc_project_form_policy", [])
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            for proj in &cfg.projects {
                if let Some(ref options) = proj.form_options {
                    conn.execute(
                        "INSERT INTO loc_project_form_policy (project_id, form_options_json, translations_json)
                         VALUES (?1, ?2, ?3)",
                        params![
                            proj.project_id,
                            options.to_string(),
                            serde_json::to_string(&proj.translations).unwrap_or_else(|_| "{}".to_string())
                        ],
                    )
                    .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
                }
                let sealed_json = serde_json::to_string(&proj.sealed_field_ids)
                    .unwrap_or_else(|_| "[]".to_string());
                let inst_versions_json = serde_json::to_string(&proj.instrument_versions).ok();

                let project_name = proj
                    .project_name
                    .as_deref()
                    .map(str::trim)
                    .filter(|n| !n.is_empty())
                    .unwrap_or(&proj.project_id);
                let coding_mode_json = proj.coding_mode.as_ref().map(|m| json!(m).to_string());
                conn.execute(
                    "INSERT INTO loc_project_config (project_id, project_name, sealed_field_ids_json, va_instrument_json, coding_config_json, updated_at, coding_mode_json)
                     VALUES (?1, ?2, ?3, ?4, NULL, ?5, ?6)
                     ON CONFLICT(project_id) DO UPDATE SET
                        project_name = excluded.project_name,
                        sealed_field_ids_json = excluded.sealed_field_ids_json,
                        va_instrument_json = excluded.va_instrument_json,
                        updated_at = excluded.updated_at,
                        coding_mode_json = excluded.coding_mode_json",
                    params![proj.project_id, project_name, sealed_json, inst_versions_json, now, coding_mode_json],
                )
                .ok();

                if let Some(ref consent_val) = proj.consent {
                    let parsed_consent =
                        parse_contract_consent_config(&proj.project_id, consent_val).map_err(|msg| {
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

    /// Pending sandbox (project "1") records that an export leaves on this computer.
    pub fn count_pending_sandbox_records(&self) -> i64 {
        self.with_conn(|conn| {
            conn.query_row(
                "SELECT (SELECT COUNT(*) FROM loc_death_register WHERE sync_state = 'pending' AND project_id = '1')
                      + (SELECT COUNT(*) FROM loc_va_submissions WHERE sync_state = 'pending' AND project_id = '1')
                      + (SELECT COUNT(*) FROM consent_records WHERE sync_state = 'pending' AND project_id = '1')",
                [],
                |r| r.get(0),
            )
            .unwrap_or(0)
        })
    }

    /// The pending, exportable records as bundle envelopes, plus `{client_id, reason}` for
    /// rows that cannot become one (a consent without its notice version id).
    fn pending_bundle_records(
        &self,
        default_user_id: i64,
    ) -> Result<(Vec<BundleRecordEnvelope>, Vec<Value>), (u16, Value)> {
        let parse_role = |r: Option<&str>, fallback: ActingRole| -> ActingRole {
            match r.and_then(normalise_acting_role) {
                Some("death_reporter") => ActingRole::DeathReporter,
                Some("interviewer") => ActingRole::Interviewer,
                Some("station_supervisor") => ActingRole::StationSupervisor,
                Some("coder") => ActingRole::Coder,
                _ => fallback,
            }
        };

        self.with_conn(|conn| {
            let mut out = Vec::new();
            let mut held_back = Vec::new();

            // Sandbox (project "1") records are never exportable: the queries below skip them.

            // 1. Consent records
            let mut stmt = conn
                .prepare(
                    "SELECT consent_id, CAST(project_id AS TEXT), client_death_id, client_draft_id, action_type,
                            notice_version_id, locale, notice_sha256, mode,
                            witness_present, supersedes_client_id, purposes_json,
                            actor_user_id, acting_role, recorded_at
                     FROM consent_records
                     WHERE sync_state = 'pending' AND project_id != '1'
                     ORDER BY recorded_at ASC",
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            let consent_rows = stmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, Option<String>>(2)?,
                        r.get::<_, Option<String>>(3)?,
                        r.get::<_, String>(4)?,
                        r.get::<_, String>(5)?,
                        r.get::<_, String>(6)?,
                        r.get::<_, String>(7)?,
                        r.get::<_, String>(8)?,
                        r.get::<_, i32>(9)?,
                        r.get::<_, Option<String>>(10)?,
                        r.get::<_, String>(11)?,
                        r.get::<_, Option<i64>>(12)?,
                        r.get::<_, Option<String>>(13)?,
                        r.get::<_, String>(14)?,
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
                // No default notice: a consent without its served notice id cannot travel.
                let Ok(notice_uuid) = Uuid::parse_str(&nv_id) else {
                    held_back.push(json!({
                        "client_id": client_id,
                        "reason": "Consent notice_version_id is not a notice version id."
                    }));
                    continue;
                };
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
                    "SELECT death_id, client_death_id, CAST(project_id AS TEXT), site_id, org_unit_id,
                            deceased_name, deceased_sex, date_of_death, date_of_birth,
                            age_years, place_of_death, informant_name, informant_relation,
                            informant_phone, informant_phone_2, address, address_house_street,
                            address_village_ward, address_landmark, remarks,
                            actor_user_id, acting_role, created_at
                     FROM loc_death_register
                     WHERE sync_state = 'pending' AND project_id != '1'
                     ORDER BY death_id ASC",
                )
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
            let death_rows = dstmt
                .query_map([], |r| {
                    Ok((
                        r.get::<_, i64>(0)?,
                        r.get::<_, Option<String>>(1)?,
                        r.get::<_, String>(2)?,
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
                    get_latest_consent_for_case(conn, &pid, Some(&cdid_str), Some(did))
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
                            payload_json, actor_user_id, acting_role, submitted_at,
                            (SELECT d.meta_json FROM loc_va_drafts d WHERE d.draft_id = s.draft_id)
                     FROM loc_va_submissions s
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
                        r.get::<_, Option<String>>(10)?,
                    ))
                })
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            for row in sub_rows.flatten() {
                let (va_sid, draft_id_opt, did_opt, pid, sid, ouid, pjson, uid, role, sub_at, meta_raw) = row;
                // The definition pin the interview was filled on, as the app recorded it.
                let meta: Value = meta_raw
                    .and_then(|raw| serde_json::from_str(&raw).ok())
                    .unwrap_or_else(|| json!({}));
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
                let latest_consent = get_latest_consent_for_case(
                    conn,
                    &pid,
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
                            instrument_version: meta["instrumentVersion"]
                                .as_str()
                                .filter(|v| !v.is_empty())
                                .unwrap_or(instrument::composed_version())
                                .to_string(),
                            definition_sha256: meta["definitionSha256"].as_str().map(ToString::to_string),
                            definition_extensions: meta.get("definitionExtensions").cloned(),
                            started_at: meta["startedAt"].as_str().unwrap_or(&sub_at).to_string(),
                            completed_at: Some(meta["completedAt"].as_str().unwrap_or(&sub_at).to_string()),
                            device_clock_at: None,
                            interview_outcome: meta["interviewOutcome"].as_str().unwrap_or("completed").to_string(),
                        },
                        completion: InterviewCompletion {
                            valid: meta["completion"]["valid"].as_bool().unwrap_or(true),
                            issues: meta["completion"]["issues"].as_array().cloned().unwrap_or_default(),
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
                            actor_user_id, acting_role, payload_json, created_at, coding_mode
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
                        r.get::<_, Option<String>>(7)?,
                    ))
                })
                .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;

            for row in cr_rows.flatten() {
                let (cid_str, cdraft_str, pid, uid, role, pjson, cat, coding_mode) = row;
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
                        // Station modes are unmasked: never a Step 1, even from an older row.
                        initial: None,
                        final_cod: pval.get("final_assessment").cloned().filter(|v| !v.is_null()),
                        not_codeable: pval.get("not_codeable").cloned().filter(|v| !v.is_null()),
                        coding_mode,
                    }),
                });
            }

            Ok((out, held_back))
        })
    }

    /// Export a signed and encrypted `.dvb` bundle of all pending records in Provisioned mode.
    ///
    /// A record that fails the bundle rules is held back, not dropped: it stays pending and is
    /// returned as `{client_id, reason}` in the third element, so one bad record cannot block
    /// every later export. A registration whose consent is held back is held back with it.
    /// 422 `records_held_back` when every pending record is held back.
    pub fn export_dvb_bundle(&self) -> Result<(BuiltBundle, String, Vec<Value>), (u16, Value)> {
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

        let (records, mut held_back) = self.pending_bundle_records(default_user_id)?;

        // Consents first: a registration may lean only on a consent that travels with it.
        let station = &verified.config;
        let no_consents = BTreeSet::new();
        let granted_consents: BTreeSet<Uuid> = records
            .iter()
            .filter(|rec| match &rec.payload {
                BundleRecordPayload::Consent(c) => {
                    c.decision == ConsentDecision::Granted && c.client_draft_id.is_none()
                }
                _ => false,
            })
            .filter(|rec| validate_bundle_record(station, rec, &no_consents).is_ok())
            .map(|rec| rec.client_id)
            .collect();
        let records: Vec<BundleRecordEnvelope> = records
            .into_iter()
            .filter(|rec| match validate_bundle_record(station, rec, &granted_consents) {
                Ok(_) => true,
                Err(e) => {
                    held_back.push(json!({ "client_id": rec.client_id, "reason": e.to_string() }));
                    false
                }
            })
            .collect();
        if records.is_empty() && !held_back.is_empty() {
            return Err((
                422,
                json!({
                    "error": "No pending record can be sent; every one was held back.",
                    "code": "records_held_back",
                    "records_held_back": held_back
                }),
            ));
        }

        let built = build_bundle(
            &verified,
            &signing_key,
            &cfg.station_id,
            next_seq,
            STATION_APP_VERSION,
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
        Ok((built, filename, held_back))
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

        // 2. Mark `pending_records` as `server_pending`, keeping the server's code
        //    (`doris_pending`, `not_ready`) for the coding history.
        self.with_conn(|conn| {
            for (uuid, code) in &plan.pending_records {
                let cid = uuid.to_string();
                for sql in [
                    "UPDATE consent_records SET sync_state = 'server_pending', sync_error_code = ?1 WHERE consent_id = ?2",
                    "UPDATE loc_death_register SET sync_state = 'server_pending', sync_error_code = ?1 WHERE client_death_id = ?2",
                    "UPDATE loc_va_drafts SET sync_state = 'server_pending', sync_error_code = ?1 WHERE draft_id = ?2",
                    "UPDATE loc_va_submissions SET sync_state = 'server_pending', sync_error_code = ?1 WHERE draft_id = ?2",
                    "UPDATE loc_supervisor_corrections SET sync_state = 'server_pending', sync_error_code = ?1 WHERE client_id = ?2",
                    "UPDATE loc_coding_results SET sync_state = 'server_pending', sync_error_code = ?1 WHERE client_id = ?2",
                ] {
                    conn.execute(sql, params![code, cid]).ok();
                }
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

        // Counts come from the receipt's own outcomes; `deleted_count` is what was removed here.
        let accepted_count = plan
            .report
            .records
            .iter()
            .filter(|r| {
                matches!(
                    r.outcome,
                    RecordIngestOutcome::Accepted
                        | RecordIngestOutcome::Duplicate
                        | RecordIngestOutcome::Superseded
                )
            })
            .count();

        Ok(json!({
            "bundle_id": plan.report.bundle_id.to_string(),
            "device_id": plan.report.device_id,
            "status": plan.report.status,
            "deleted_count": deleted_count,
            "acknowledged_deleted_count": deleted_count,
            "accepted_count": accepted_count,
            "pending_count": plan.pending_records.len(),
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
                        provisioned_roles_json, provisioned_token, updated_at,
                        facility_code, facility_type, facility_address
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
                        facility_code: r.get(11)?,
                        facility_type: r.get(12)?,
                        facility_address: r.get(13)?,
                    })
                },
            )
            .unwrap_or_else(|_| StationConfig {
                mode: "standalone".to_string(),
                station_id: "phc-standalone-01".to_string(),
                facility_name: "Model Primary Health Centre".to_string(),
                facility_code: String::new(),
                facility_type: String::new(),
                facility_address: String::new(),
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

    /// Saves the six plain facility fields (trimmed). Name is required; each field is capped
    /// (200 chars, address 500). Returns a field-level message on failure.
    pub fn update_facility_details(
        &self,
        name: &str,
        code: &str,
        facility_type: &str,
        address: &str,
        district: &str,
        state: &str,
    ) -> Result<StationConfig, String> {
        let (name, code, facility_type, address, district, state) = (
            name.trim(),
            code.trim(),
            facility_type.trim(),
            address.trim(),
            district.trim(),
            state.trim(),
        );
        if name.is_empty() {
            return Err("Facility name is required.".to_string());
        }
        for (label, value, max) in [
            ("Facility name", name, 200),
            ("Facility code", code, 200),
            ("Facility type", facility_type, 200),
            ("Address", address, 500),
            ("District", district, 200),
            ("State", state, 200),
        ] {
            if value.chars().count() > max {
                return Err(format!("{label} must be at most {max} characters."));
            }
        }
        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config
                 SET facility_name = ?1, facility_code = ?2, facility_type = ?3,
                     facility_address = ?4, district_name = ?5, state_name = ?6, updated_at = ?7
                 WHERE id = 1",
                params![name, code, facility_type, address, district, state, Utc::now().to_rfc3339()],
            )
            .map_err(|e| e.to_string())
        })?;
        Ok(self.get_station_config())
    }

    /// The station's own module selection (every module when never set) and coding mode.
    fn local_station_choices(&self) -> (BTreeSet<String>, String) {
        let (modules_raw, coding_mode): (Option<String>, String) = self.with_conn(|conn| {
            conn.query_row(
                "SELECT enabled_modules_json, coding_mode FROM loc_station_config WHERE id = 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .unwrap_or((None, CODING_MODE_ICD11_DORIS.to_string()))
        });
        let modules = match modules_raw.and_then(|raw| serde_json::from_str::<Vec<String>>(&raw).ok()) {
            Some(list) => list.into_iter().filter(|m| instrument::tag_vocabulary().contains(m)).collect(),
            None => instrument::tag_vocabulary().clone(),
        };
        (modules, coding_mode)
    }

    /// The modules the imported config's project policies enable (the union over projects whose
    /// form-options carry `enabled_extensions`), or None when no policy governs modules.
    fn policy_modules(&self) -> Option<BTreeSet<String>> {
        if self.get_station_config().mode != "provisioned" {
            return None;
        }
        let rows: Vec<String> = self.with_conn(|conn| {
            conn.prepare("SELECT form_options_json FROM loc_project_form_policy")
                .and_then(|mut stmt| stmt.query_map([], |r| r.get(0))?.collect())
                .unwrap_or_default()
        });
        let mut carried = false;
        let mut union = BTreeSet::new();
        for options in rows.iter().filter_map(|raw| serde_json::from_str::<Value>(raw).ok()) {
            if options["enabled_extensions"].is_array() {
                carried = true;
                union.extend(
                    instrument::enabled_extensions(&options)
                        .into_iter()
                        .filter(|e| instrument::tag_vocabulary().contains(*e))
                        .map(str::to_string),
                );
            }
        }
        carried.then_some(union)
    }

    /// The signed config's `coding_mode` for `project_id` (contract 4.3): `None` when nothing
    /// locks it (sandbox, standalone, or a config before the key), `Some(None)` when the station
    /// must not code the project, else `Some(Some(mode))`. An unknown mode reads as `null`.
    fn project_coding_lock(&self, project_id: &str) -> Option<Option<String>> {
        if self.get_station_config().mode != "provisioned" {
            return None;
        }
        let raw: Option<String> = self.with_conn(|conn| {
            conn.query_row(
                "SELECT coding_mode_json FROM loc_project_config WHERE project_id = ?1",
                params![project_id],
                |r| r.get(0),
            )
            .optional()
            .ok()
            .flatten()
            .flatten()
        });
        raw.map(|raw| parse_coding_mode_json(&raw))
    }

    /// The mode the station codes `project_id` in (`icd11_doris` or `icd10`), or `None` when the
    /// signed config says the station does not code that project (coding is done on the server).
    pub fn project_coding_mode(&self, project_id: &str) -> Option<String> {
        self.project_coding_lock(project_id)
            .unwrap_or_else(|| Some(self.local_station_choices().1))
    }

    /// `project_coding_mode` for the project of submission `va_sid`; `None` for an unknown case.
    pub fn coding_mode_for_va(&self, va_sid: &str) -> Option<String> {
        let project_id: Option<String> = self.with_conn(|conn| {
            conn.query_row(
                "SELECT project_id FROM loc_va_submissions WHERE va_sid = ?1",
                params![va_sid],
                |r| r.get(0),
            )
            .optional()
            .ok()
            .flatten()
        });
        project_id.and_then(|pid| self.project_coding_mode(&pid))
    }

    /// Err `(409, station_coding_not_enabled)` when the station must not code submission
    /// `va_sid`'s project (its config `coding_mode` is null). An unknown case passes: the
    /// route's own lookup answers 404.
    pub fn check_station_coding(&self, va_sid: &str) -> Result<(), (u16, Value)> {
        if self.has_va_submission(va_sid) && self.coding_mode_for_va(va_sid).is_none() {
            return Err((
                409,
                json!({
                    "error": "Coding for this project is done on the server.",
                    "code": "station_coding_not_enabled"
                }),
            ));
        }
        Ok(())
    }

    /// The config's coding lock Settings shows: the first project (by id) whose config carries
    /// `coding_mode`. `None` when no project's config carries it.
    fn config_coding_lock(&self) -> Option<Option<String>> {
        // ponytail: one shown mode for the station; a station of several projects with different
        // locks codes each in its own (`project_coding_mode`), Settings shows the first.
        self.station_projects()
            .iter()
            .find_map(|(project_id, _)| self.project_coding_lock(project_id))
    }

    /// `GET /station/settings`: every module with whether it is enabled, the coding mode, and
    /// which of the two a project policy governs (read-only in Settings). `coding_mode` is null
    /// when the config locks the station out of coding (the project is coded on the server).
    pub fn station_settings(&self) -> Value {
        let (local_modules, local_coding_mode) = self.local_station_choices();
        let policy = self.policy_modules();
        let enabled = policy.as_ref().unwrap_or(&local_modules);
        let modules: Vec<Value> = instrument::tag_vocabulary()
            .iter()
            .map(|tag| json!({ "code": tag, "label": instrument::module_label(tag), "enabled": enabled.contains(tag) }))
            .collect();
        let lock = self.config_coding_lock();
        json!({
            "modules": modules,
            "modules_locked": policy.is_some(),
            "coding_mode": lock.clone().unwrap_or(Some(local_coding_mode)),
            "coding_mode_locked": lock.is_some(),
            "available_coding_modes": CODING_MODES,
        })
    }

    /// `PUT /station/settings`: saves whichever of the two choices is given. Err `(409,
    /// policy_locked)` when a project policy governs a given field, `(400, validation_error)`
    /// for an unknown module or mode. Nothing is saved unless the whole request is valid.
    pub fn update_station_settings(
        &self,
        enabled_modules: Option<&[String]>,
        coding_mode: Option<&str>,
    ) -> Result<Value, (u16, Value)> {
        let invalid = |msg: String| (400, json!({ "error": msg, "code": "validation_error" }));
        if enabled_modules.is_some() && self.policy_modules().is_some() {
            return Err((
                409,
                json!({ "error": "Interview modules are set by your project's setup file.", "code": "policy_locked" }),
            ));
        }
        if coding_mode.is_some() && self.config_coding_lock().is_some() {
            return Err((
                409,
                json!({ "error": "The coding mode is set by your project's setup file.", "code": "policy_locked" }),
            ));
        }
        if let Some(mode) = coding_mode {
            if !CODING_MODES.contains(&mode) {
                return Err(invalid(format!("Unknown coding mode: {mode}.")));
            }
        }
        let modules_json = match enabled_modules {
            Some(list) => {
                if let Some(bad) = list.iter().find(|m| !instrument::tag_vocabulary().contains(*m)) {
                    return Err(invalid(format!("Unknown module: {bad}.")));
                }
                let chosen: BTreeSet<&String> = list.iter().collect();
                Some(serde_json::to_string(&chosen).unwrap_or_else(|_| "[]".to_string()))
            }
            None => None,
        };
        self.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config
                 SET enabled_modules_json = COALESCE(?1, enabled_modules_json),
                     coding_mode = COALESCE(?2, coding_mode),
                     updated_at = ?3
                 WHERE id = 1",
                params![modules_json, coding_mode, Utc::now().to_rfc3339()],
            )
        })
        .map_err(|e| (500, json!({ "error": e.to_string(), "code": "db_error" })))?;
        Ok(self.station_settings())
    }

    /// `(project_id, project_name)` the station works in: the server's projects from the signed
    /// config once provisioned, otherwise only the sandbox project "1".
    pub fn station_projects(&self) -> Vec<(String, String)> {
        let cfg = self.get_station_config();
        if cfg.mode == "provisioned" {
            let rows: Vec<(String, String)> = self.with_conn(|conn| {
                conn.prepare("SELECT project_id, project_name FROM loc_project_config ORDER BY project_id")
                    .and_then(|mut stmt| stmt.query_map([], |r| Ok((r.get(0)?, r.get(1)?)))?.collect())
                    .unwrap_or_default()
            });
            if !rows.is_empty() {
                return rows;
            }
        }
        vec![("1".to_string(), format!("{} Mortality Surveillance", cfg.facility_name))]
    }

    /// The imported signed config's line 1 while provisioned; None in the sandbox or before any
    /// import. Not re-verified here: it was verified at import, and an expired config must
    /// still label the cases recorded under it.
    fn provisioned_payload(&self) -> Option<StationConfigPayload> {
        if self.get_station_config().mode != "provisioned" {
            return None;
        }
        let raw: Option<String> = self.with_conn(|conn| {
            conn.query_row(
                "SELECT raw_signed_config FROM loc_station_config WHERE id = 1",
                [],
                |r| r.get::<_, Option<String>>(0),
            )
            .optional()
            .ok()
            .flatten()
            .flatten()
        });
        serde_json::from_str(raw?.split('\n').next()?).ok()
    }

    /// Targets `actor` may record under in `project_id` for `roles`; None when the sandbox
    /// demo units apply (project "1", or no signed config imported). A project the config no
    /// longer lists has no targets.
    fn project_targets(
        &self,
        project_id: &str,
        actor: &ActiveActorContext,
        roles: &[ActingRole],
    ) -> Option<Vec<GrantTarget>> {
        if project_id == "1" {
            return None;
        }
        let payload = self.provisioned_payload()?;
        Some(
            payload
                .projects
                .iter()
                .find(|p| p.project_id == project_id)
                .map(|p| grant_targets(p, &actor.roles, roles))
                .unwrap_or_default(),
        )
    }

    /// Every site and org unit the active actor's grants cover in `project_id` (any role);
    /// None when the sandbox demo tree applies.
    pub fn active_actor_targets(&self, project_id: &str) -> Option<Vec<GrantTarget>> {
        let actor = self.get_active_actor_context();
        self.project_targets(project_id, &actor, &ALL_ACTING_ROLES)
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
    /// - A project from the imported signed config offers the sites and org units the active
    ///   actor's roster grants allow (`grant_targets`), labelled from `site_names` /
    ///   `org_unit_paths`; the sandbox project "1" keeps the demo PHC01 tree.
    pub fn build_access_summary(&self) -> Result<Value, String> {
        let cfg = self.get_station_config();
        let active_actor = self.get_active_actor_context();
        let payload = self.provisioned_payload();
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
            "projects": self.station_projects().into_iter().map(|(project_id, project_name)| {
                // A provisioned project offers exactly what the active actor's roster grants
                // allow; the sandbox keeps the demo PHC01 tree below.
                let real = payload.as_ref().filter(|_| project_id != "1").map(|p| {
                    p.projects.iter().find(|proj| proj.project_id == project_id)
                });
                if let Some(proj) = real {
                    let targets = |roles: &[ActingRole]| {
                        proj.map(|proj| grant_targets(proj, &active_actor.roles, roles))
                            .unwrap_or_default()
                    };
                    let action = |t: &GrantTarget| json!({
                        "site_id": t.site_id,
                        "site_name": t.site_name,
                        "web_intake_mode": "both",
                        "org_units": t.org_units.iter().map(|(id, path)| json!({
                            "org_unit_id": id, "unit_code": id, "unit_name": path, "path": id
                        })).collect::<Vec<Value>>()
                    });
                    let all = targets(&ALL_ACTING_ROLES);
                    let mut units: Vec<Value> = Vec::new();
                    for (id, path) in all.iter().flat_map(|t| t.org_units.iter()) {
                        if !units.iter().any(|u| u["org_unit_id"] == id.as_str()) {
                            units.push(json!({
                                "org_unit_id": id, "unit_code": id, "unit_name": path,
                                "level_code": "UNIT", "path": id, "is_active": true,
                                "selectable": true, "roles": roles, "can_code": can_code
                            }));
                        }
                    }
                    return json!({
                        "project_id": project_id,
                        "project_name": project_name,
                        "has_tree": true,
                        "roles": roles,
                        "grants": grants,
                        "sites": all.iter().map(|t| json!({
                            "site_id": t.site_id, "site_name": t.site_name, "roles": roles
                        })).collect::<Vec<Value>>(),
                        "actions": {
                            "interview": targets(interview_roles(&active_actor.acting_role))
                                .iter().map(action).collect::<Vec<Value>>(),
                            "register_death": targets(registration_roles(&active_actor.acting_role))
                                .iter().map(action).collect::<Vec<Value>>()
                        },
                        "units": units,
                        // ponytail: one flat level; the config names each unit's path, not its ancestors' ids.
                        "levels": [{ "level_code": "UNIT", "level_name": "Org unit", "depth": 1 }]
                    });
                }
                json!({
                    "project_id": project_id,
                    "project_name": project_name,
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
                })
            }).collect::<Vec<Value>>()
        }))
    }

    // ========================================================================
    // Registration Identifiers (CRS / MCCD / Project-Configured)
    // ========================================================================

    pub fn list_identifier_types(&self, project_id: &str) -> Vec<IdentifierTypeSpec> {
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(
                    "SELECT id, CAST(project_id AS TEXT), code, label, description, char_type,
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
        project_id: &str,
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
        project_id: &str,
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
        project_id: &str,
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

        // The server's string project id ("TST001"); a number is accepted as its text, and an
        // absent id is the sandbox "1" (never exportable).
        let project_id: String = match obj.get("project_id") {
            Some(Value::String(s)) if !s.trim().is_empty() => s.trim().to_string(),
            Some(Value::Number(n)) => n.to_string(),
            _ => "1".to_string(),
        };

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
        // A provisioned project records only where the actor's roster grants allow, so the
        // bundle's roster check accepts the record; the sandbox keeps the demo units.
        let (site_name, org_unit_name) = match self.project_targets(
            &project_id,
            &active_actor,
            registration_roles(&active_actor.acting_role),
        ) {
            None => (
                station_cfg.facility_name.clone(),
                sandbox_unit_name(org_unit_id, &station_cfg.facility_name),
            ),
            Some(targets) => target_labels(&targets, site_id, org_unit_id).ok_or_else(|| {
                (
                    403,
                    json!({
                        "error": "You are not assigned to record deaths at this site and unit.",
                        "code": "forbidden",
                        "fields": { "org_unit_id": "Choose a unit you are assigned to." }
                    }),
                )
            })?,
        };

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
                        &project_id,
                        Some(&client_death_id),
                        None,
                        &env,
                        actor_name,
                        &station_cfg.station_id,
                    )
                    .map_err(|refusal| {
                        (
                            422,
                            json!({
                                "error": refusal.message,
                                "code": refusal.code.unwrap_or("invalid_registration"),
                                "fields": { "consent": refusal.message }
                            }),
                        )
                    })?;
                }
            }

            // Extract informant personal fields
            let latest_consent =
                get_latest_consent_for_case(conn, &project_id, Some(&client_death_id), None)
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
                &project_id,
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
            .map_err(|refusal| {
                (
                    422,
                    consent_required_for_informant(&refusal, &[
                        ("informant_name", informant_name.as_deref()),
                        ("informant_phone", informant_phone.as_deref()),
                        ("informant_phone_2", informant_phone_2.as_deref()),
                        ("address", address.as_deref()),
                        ("address_house_street", address_house_street.as_deref()),
                        ("address_village_ward", address_village_ward.as_deref()),
                        ("address_landmark", address_landmark.as_deref()),
                        ("location", location.as_deref()),
                    ]),
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
                    site_name,
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
                    &project_id,
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
            let existing: Option<(String, Option<String>, String, String, Option<String>, String, String)> = conn
                .query_row(
                    "SELECT CAST(project_id AS TEXT), client_death_id, status, state, va_sid, site_id, org_unit_id
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
                        &project_id,
                        client_death_id.as_deref(),
                        Some(death_id),
                        &env,
                        actor_name,
                        &station_cfg.station_id,
                    )
                    .map_err(|refusal| {
                        (
                            422,
                            json!({
                                "error": refusal.message,
                                "code": refusal.code.unwrap_or("invalid_death"),
                                "fields": { "consent": refusal.message }
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
                    &project_id,
                    client_death_id.as_deref(),
                    Some(death_id),
                    &incoming_inf,
                )
                .map_err(|refusal| {
                    (
                        422,
                        consent_required_for_informant(
                            &refusal,
                            &inf_keys
                                .iter()
                                .copied()
                                .zip(incoming_inf.iter().copied())
                                .collect::<Vec<_>>(),
                        ),
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
            let row: Option<(String, Option<String>, String, String, String, String)> = conn
                .query_row(
                    "SELECT CAST(project_id AS TEXT), client_death_id, status, state, site_id, org_unit_id
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
                &pid,
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

    /// One page of the station's cases, newest registration first, for `GET /intake/deaths`
    /// and `GET /intake/cases`: `{cases, deaths, counts, next_cursor}`. `counts` is
    /// `{total, <state>: n}` over the whole (filtered) list, not the page. Keyset-paged on
    /// `death_id`; the cursor is opaque to the app. Errors are safe 400 messages
    /// (`CaseListQuery::parse`).
    pub fn list_cases(&self, query: &CaseListQuery) -> Result<Value, String> {
        let page = query.parse()?;
        let mine = if page.registered_mine {
            Some(self.get_active_actor_context().member_id)
        } else {
            None
        };
        self.with_conn(|conn| {
            let fetch = page.limit + 1;
            let ids: Vec<i64> = match (&mine, page.after) {
                (Some(member), Some(after)) => query_ids(
                    conn,
                    "SELECT death_id FROM loc_death_register WHERE actor_member_id = ?1 AND death_id < ?2 ORDER BY death_id DESC LIMIT ?3",
                    params![member, after, fetch],
                ),
                (Some(member), None) => query_ids(
                    conn,
                    "SELECT death_id FROM loc_death_register WHERE actor_member_id = ?1 ORDER BY death_id DESC LIMIT ?2",
                    params![member, fetch],
                ),
                (None, Some(after)) => query_ids(
                    conn,
                    "SELECT death_id FROM loc_death_register WHERE death_id < ?1 ORDER BY death_id DESC LIMIT ?2",
                    params![after, fetch],
                ),
                (None, None) => query_ids(
                    conn,
                    "SELECT death_id FROM loc_death_register ORDER BY death_id DESC LIMIT ?1",
                    params![fetch],
                ),
            }?;
            let has_more = ids.len() as i64 > page.limit;
            let page_ids = &ids[..ids.len().min(page.limit as usize)];

            // ponytail: build_case_row reads each row's draft and identifiers separately
            // (bounded by CASE_PAGE_MAX); batch them if pages grow slow.
            let rows: Vec<Value> = page_ids
                .iter()
                .filter_map(|&id| Self::build_case_row(conn, id).ok())
                .collect();
            let next_cursor = if has_more {
                page_ids.last().map(|id| id.to_string())
            } else {
                None
            };
            Ok(json!({
                "cases": rows,
                "deaths": rows,
                "counts": case_state_counts(conn, mine.as_deref())?,
                "next_cursor": next_cursor
            }))
        })
    }

    /// `{total, <state>: n}` over the whole death register (the KPI strip).
    pub fn case_counts(&self) -> Result<Value, String> {
        self.with_conn(|conn| case_state_counts(conn, None))
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
                        age_years, status, state, CAST(project_id AS TEXT), site_id, site_name,
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
                let project_id: String = r.get(8)?;
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
                    Self::load_case_identifier_items(conn, &project_id, id_num, is_coder);
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
                        remarks, created_at, CAST(project_id AS TEXT), client_death_id
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
                        r.get::<_, String>(17)?,
                        r.get::<_, Option<String>>(18)?,
                    ))
                },
            )
            .map_err(|e| e.to_string())?;

        let latest_consent = if is_coder {
            None
        } else {
            get_latest_consent_for_case(conn, &project_id, client_death_id.as_deref(), Some(death_id))
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
            // A coder never starts an interview: no personal data rides along.
            obj.insert("prefill".to_string(), json!({ "answers": {}, "lockedQuestionNames": [] }));
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
            let prefill = interview_prefill(
                &active_actor,
                &RegisterPrefill {
                    deceased_name: deceased_name.as_str(),
                    deceased_sex: deceased_sex.as_str(),
                    date_of_death: date_of_death.as_str(),
                    age_years: age_years.as_f64(),
                    date_of_birth: dob.as_deref(),
                    date_of_birth_partial: dob_partial.as_deref(),
                    place_of_death: place_of_death.as_deref(),
                    informant_name: inf_name.as_deref(),
                    father_name: father_name.as_deref(),
                    mother_name: mother_name.as_deref(),
                    abha_number: abha_number.as_deref(),
                    abha_address: abha_address.as_deref(),
                    address_parts: [addr_house.as_deref(), addr_village.as_deref(), addr_landmark.as_deref(), addr.as_deref()],
                    org_path: obj.get("org_unit_name").and_then(Value::as_str),
                },
            );
            obj.insert("prefill".to_string(), prefill);
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
        let (site_name, org_unit_name) = match self.project_targets(
            project_id,
            &active_actor,
            interview_roles(&active_actor.acting_role),
        ) {
            None => (
                station_cfg.facility_name.clone(),
                sandbox_unit_name(org_unit_id, &station_cfg.facility_name),
            ),
            Some(targets) => target_labels(&targets, site_id, org_unit_id).ok_or_else(|| {
                "You are not assigned to interview at this site and unit.".to_string()
            })?,
        };

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
                    {
                        let mut prefill = interview_prefill(&active_actor, &RegisterPrefill::default());
                        prefill["answers"]["Id10012"] = json!(&now[..10]);
                        prefill
                    },
                )
            };

            let prefill_str = serde_json::to_string(&prefill).unwrap_or_else(|_| "{}".to_string());
            conn.execute(
                "INSERT INTO loc_va_drafts (
                    draft_id, unique_id, project_id, site_id, site_name,
                    org_unit_id, org_unit_name, death_id, status, current_section,
                    locale, translation_version, answers_json, prefill_json,
                    actor_user_id, actor_member_id, acting_role, sync_state, updated_at, created_at
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?13, ?7, 'in_progress', NULL, 'en', 0, '{}', ?8, ?9, ?10, ?11, 'pending', ?12, ?12)",
                params![
                    draft_id,
                    unique_id,
                    project_id,
                    site_id,
                    site_name,
                    org_unit_id,
                    death_id,
                    prefill_str,
                    active_actor.user_id,
                    active_actor.member_id,
                    active_actor.acting_role,
                    now,
                    org_unit_name
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
                    locale, translation_version, answers_json, prefill_json, updated_at,
                    meta_json, created_at
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
                let meta: Value = serde_json::from_str(&r.get::<_, String>(15)?).unwrap_or_else(|_| json!({}));
                let created_at: String = r.get(16)?;
                // The server's `load_draft_envelope` shape; the definition pin only when recorded.
                let mut envelope = json!({
                    "schemaVersion": meta.get("schemaVersion").cloned().unwrap_or(json!(1)),
                    "formVersion": meta.get("formVersion").cloned().unwrap_or(json!("2022")),
                    "id": draft_id,
                    "instrumentId": meta.get("instrumentId").cloned().unwrap_or(json!("va_who_2022")),
                    "instrumentVersion": meta.get("instrumentVersion").cloned().unwrap_or(json!("")),
                    "locale": r.get::<_, String>(10)?,
                    "translation_version": r.get::<_, i64>(11)?,
                    "currentSection": summary["current_section"].as_str().unwrap_or_default(),
                    "createdAt": meta.get("createdAt").cloned().unwrap_or(json!(created_at)),
                    "updatedAt": meta.get("updatedAt").cloned().unwrap_or(json!(updated_at)),
                    "data": answers
                });
                for key in ["definitionSha256", "definitionExtensions"] {
                    if let Some(v) = meta.get(key) {
                        envelope[key] = v.clone();
                    }
                }
                Ok(json!({
                    "draft": summary,
                    "envelope": envelope,
                    "prefill": prefill
                }))
            },
        )
        .map_err(|e| e.to_string())
    }

    /// `PATCH /intake/drafts/<id>`, the shared app's autosave (the server's `save_draft`):
    /// `{sections: {name: answers}, current_section, meta}`. Each section replaces its saved
    /// answers; the draft's answers are the sections merged. `meta` keeps the app's envelope keys,
    /// the definition pin among them, which the bundle's `interview_submission` carries.
    /// Returns `(status, body)`: 200 `{saved_sections, draft}`, 400/422 for a malformed body,
    /// 404 unknown draft, 409 a submitted one.
    /// ponytail: no `if_updated_at` stale check; one station writes its own drafts.
    pub fn save_draft_sections(&self, draft_id: &str, body: &Value) -> Result<(u16, Value), String> {
        let bad = |status: u16, msg: &str| Ok((status, json!({ "error": msg, "code": "invalid_request" })));
        let empty = serde_json::Map::new();
        let Some(sections) = body.get("sections").map_or(Some(&empty), Value::as_object) else {
            return bad(400, "sections must be an object keyed by section name.");
        };
        let section_name_ok = |n: &str| (1..=64).contains(&n.len()) && n.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_');
        for (name, answers) in sections {
            if !section_name_ok(name) || !answers.is_object() {
                return bad(400, "Each section is an object of answers under a valid section name.");
            }
        }
        let current_section = body.get("current_section").and_then(Value::as_str);
        if current_section.is_some_and(|c| !section_name_ok(c)) {
            return bad(400, "Invalid current section.");
        }
        let meta_in = body.get("meta").and_then(Value::as_object).cloned().unwrap_or_default();
        if let Some(sha) = meta_in.get("definitionSha256") {
            let ok = sha.as_str().is_some_and(|v| v.len() == 64 && v.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f')));
            if !ok {
                return bad(422, "definitionSha256 must be 64 lowercase hex characters.");
            }
        }
        if let Some(names) = meta_in.get("definitionExtensions") {
            let ok = names.as_array().is_some_and(|list| {
                list.len() <= 16
                    && list.iter().all(|n| {
                        n.as_str().is_some_and(|n| {
                            (1..=32).contains(&n.len())
                                && n.as_bytes()[0].is_ascii_lowercase()
                                && n.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
                        })
                    })
            });
            if !ok {
                return bad(422, "definitionExtensions must be a short list of extension names.");
            }
        }
        let locale = meta_in.get("locale");
        if locale.is_some_and(|l| {
            !l.as_str().is_some_and(|l| (2..=16).contains(&l.len()) && l.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-'))
        }) {
            return bad(400, "Invalid locale.");
        }
        let translation_version = meta_in.get("translation_version");
        if translation_version.is_some_and(|v| v.as_u64().is_none()) {
            return bad(400, "Invalid translation version.");
        }
        const META_KEYS: [&str; 9] = [
            "schemaVersion", "formVersion", "instrumentId", "instrumentVersion", "createdAt",
            "updatedAt", "definitionSha256", "definitionExtensions", "currentSection",
        ];
        let now = Utc::now().to_rfc3339();
        self.with_conn(|conn| {
            let row: Option<(String, String, String)> = conn
                .query_row(
                    "SELECT status, sections_json, meta_json FROM loc_va_drafts WHERE draft_id = ?1",
                    params![draft_id],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                )
                .optional()
                .map_err(|e| e.to_string())?;
            let Some((status, sections_raw, meta_raw)) = row else {
                return Ok((404, json!({ "error": "Draft not found.", "code": "not_found" })));
            };
            if status == "submitted" {
                return Ok((409, json!({ "error": "This draft is no longer editable.", "code": "conflict" })));
            }
            let mut stored: serde_json::Map<String, Value> =
                serde_json::from_str(&sections_raw).unwrap_or_default();
            for (name, answers) in sections {
                // Reduce Id10073 and sweep free-text national IDs before writing to local storage.
                stored.insert(name.clone(), redact_payload_national_ids(answers).0);
            }
            let mut names: Vec<&String> = stored.keys().collect();
            names.sort();
            let mut merged = serde_json::Map::new();
            for name in names {
                if let Some(answers) = stored[name].as_object() {
                    merged.extend(answers.iter().map(|(k, v)| (k.clone(), v.clone())));
                }
            }
            let mut meta: serde_json::Map<String, Value> = serde_json::from_str(&meta_raw).unwrap_or_default();
            for key in META_KEYS {
                if let Some(v) = meta_in.get(key) {
                    meta.insert(key.to_string(), v.clone());
                }
            }
            let written = sections.len();
            conn.execute(
                "UPDATE loc_va_drafts
                 SET sections_json = ?1,
                     answers_json = CASE WHEN ?7 > 0 THEN ?2 ELSE answers_json END,
                     meta_json = ?3,
                     current_section = COALESCE(?4, current_section),
                     locale = COALESCE(?5, locale),
                     translation_version = COALESCE(?6, translation_version),
                     updated_at = CASE WHEN ?7 > 0 THEN ?8 ELSE updated_at END
                 WHERE draft_id = ?9",
                params![
                    Value::Object(stored).to_string(),
                    Value::Object(merged).to_string(),
                    Value::Object(meta).to_string(),
                    current_section,
                    locale.and_then(Value::as_str),
                    translation_version.and_then(Value::as_i64),
                    written as i64,
                    now,
                    draft_id
                ],
            )
            .map_err(|e| e.to_string())?;
            let detail = Self::build_draft_response(conn, draft_id)?;
            Ok((200, json!({ "saved_sections": written, "draft": detail["draft"] })))
        })
    }

    pub fn submit_draft(&self, draft_id: &str, body: &Value) -> Result<(u16, Value), String> {
        let now = Utc::now().to_rfc3339();
        let active_actor = self.get_active_actor_context();
        self.with_conn(|conn| {
            let (unique_id, project_id, site_id, org_unit_id, death_id, existing_answers_str, meta_raw, created_at): (
                String,
                String,
                String,
                Option<String>,
                Option<i64>,
                String,
                String,
                String,
            ) = conn
                .query_row(
                    "SELECT unique_id, project_id, site_id, org_unit_id, death_id, answers_json,
                            meta_json, created_at
                     FROM loc_va_drafts WHERE draft_id = ?1",
                    params![draft_id],
                    |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?, r.get(6)?, r.get(7)?)),
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
            let completion = body.get("completion").cloned().unwrap_or_else(|| json!({}));
            let completion_valid = completion.get("valid").and_then(Value::as_bool) == Some(true);
            let Some(outcome) = interview_outcome(&incoming_data, completion_valid) else {
                return Ok((
                    422,
                    json!({
                        "error": "The questionnaire is not valid yet; complete the sections flagged by the form, or record the interview outcome as partially completed or respondent unavailable.",
                        "code": "invalid_interview"
                    }),
                ));
            };
            if let Some(obj) = reduced_payload.as_object_mut() {
                obj.entry("sid".to_string())
                    .or_insert_with(|| Value::String(unique_id.clone()));
                obj.insert("interview_outcome".to_string(), json!(outcome));
            }
            let fingerprint = canonical_payload_fingerprint(&reduced_payload);
            // What the bundle's `interview_submission` carries (`draft.*`, `completion`): the
            // app's own times when it sent them, else the draft's start and this submit.
            let mut meta: Value = serde_json::from_str(&meta_raw).unwrap_or_else(|_| json!({}));
            if !meta.is_object() {
                meta = json!({});
            }
            if meta["startedAt"].as_str().is_none() {
                meta["startedAt"] = meta.get("createdAt").filter(|v| v.is_string()).cloned().unwrap_or(json!(created_at));
            }
            if meta["completedAt"].as_str().is_none() {
                meta["completedAt"] = json!(now);
            }
            meta["interviewOutcome"] = json!(outcome);
            meta["completion"] = json!({
                "valid": completion_valid,
                "issues": completion.get("issues").filter(|v| v.is_array()).cloned().unwrap_or(json!([])),
            });
            conn.execute(
                "UPDATE loc_va_drafts SET meta_json = ?1 WHERE draft_id = ?2",
                params![meta.to_string(), draft_id],
            )
            .map_err(|e| e.to_string())?;

            let deceased_name = reduced_payload
                .get("Id10017")
                .and_then(Value::as_str)
                .map(ToString::to_string);
            let deceased_gender = reduced_payload
                .get("Id10019")
                .and_then(Value::as_str)
                .map(ToString::to_string);
            let deceased_age = who_age_years(&reduced_payload);

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
        // ICD-10 is the server's simple (no DORIS) workspace searching ICD-10.
        let icd10 = self.coding_mode_for_va(va_sid).as_deref() == Some(CODING_MODE_ICD10);
        let (project_mode, icd_classification) =
            if icd10 { ("unmasked_simple", "icd10") } else { ("unmasked_doris", "icd11") };
        self.with_conn(|conn| {
            let row = conn
                .query_row(
                    "SELECT unique_id, project_id, site_id, form_type_code, deceased_age,
                            deceased_gender, workflow_state, smartva_status, smartva_json,
                            initial_assessment_json, final_assessment_json, not_codeable_json,
                            reviewer_initial_json, reviewer_final_json,
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
            let nqa_saved = parse_opt(nqa_raw);
            let sa_saved = parse_opt(sa_raw);

            let is_view = mode == "view";
            let step = if is_view {
                "view"
            } else if !final_ass.is_null() || !nc_ass.is_null() {
                "done"
            } else {
                // Station modes are unmasked only (unmasked_doris, unmasked_simple): no Step 1,
                // as the server's unmasked workspace.
                "final"
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

            // The server's unmasked seed (doris_context_service.workspace_doris): the saved final
            // certificate as it is, else the interview prefill; the editor adds ICDVersion and Part I.
            let doris = if is_view || icd10 {
                Value::Null
            } else {
                let saved_certificate = final_ass
                    .get("doris_certificate")
                    .filter(|c| c.as_object().is_some_and(|m| !m.is_empty()));
                let (certificate, provenance) = match saved_certificate {
                    Some(saved) => (saved.clone(), json!({})),
                    None => {
                        let payload: Value = conn
                            .query_row(
                                "SELECT payload_json FROM loc_va_submissions WHERE va_sid = ?1",
                                params![va_sid],
                                |r| r.get::<_, String>(0),
                            )
                            .ok()
                            .and_then(|raw| serde_json::from_str(&raw).ok())
                            .unwrap_or(Value::Null);
                        doris_prefill::doris_prefill_from_payload(&payload)
                    }
                };
                json!({ "initial_certificate": certificate, "prefill_provenance": provenance })
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
                    "project_mode": project_mode,
                    "icd_classification": icd_classification,
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
                        ("age_years", json!({ "label": "Age in years", "value": who_age_years(&payload).unwrap_or_else(|| "Not recorded".to_string()), "flip": false, "info": true })),
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
        // Read server-side, never from the client body: the mode this coding was made in.
        let coding_mode = self.coding_mode_for_va(va_sid);

        let (col, new_state, id_key) = match stage {
            // Station modes are unmasked only: no coder Step 1 (server: 409 not_masked).
            "initial" => return Err("This project codes in one step; there is no Step 1 to save.".to_string()),
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
                let (history_unique_id, history_form_type): (Option<String>, Option<String>) = conn
                    .query_row(
                        "SELECT unique_id, form_type_code FROM loc_va_submissions WHERE va_sid = ?1",
                        params![va_sid],
                        |r| Ok((r.get(0)?, r.get(1)?)),
                    )
                    .unwrap_or((None, None));
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
                        actor_user_id, actor_member_id, acting_role, payload_json, sync_state, created_at,
                        coding_mode, unique_id, form_type_code
                     ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, 'pending', ?11, ?12, ?13, ?14)",
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
                        now,
                        coding_mode,
                        history_unique_id,
                        history_form_type
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

    /// Whether a VA submission with this `va_sid` exists on the station.
    pub fn has_va_submission(&self, va_sid: &str) -> bool {
        self.with_conn(|conn| {
            conn.query_row("SELECT 1 FROM loc_va_submissions WHERE va_sid = ?1", params![va_sid], |_| Ok(()))
                .optional()
                .ok()
                .flatten()
                .is_some()
        })
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

    /// Cases waiting for a coder, newest first; projects the config locks out of station coding
    /// are left out. `va_data_collector` is the roster member who submitted the interview.
    pub fn get_coder_queue(&self, limit: usize, offset: usize) -> Value {
        let provisioned = self.get_station_config().mode == "provisioned";
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(&format!(
                    "SELECT s.va_sid, s.unique_id, s.form_type_code, s.project_id, s.site_id,
                            s.submitted_at, s.deceased_age, s.deceased_gender,
                            (SELECT m.name FROM loc_station_roster m WHERE m.member_id = s.actor_member_id)
                     FROM loc_va_submissions s
                     WHERE s.workflow_state NOT IN ('coded', 'not_codeable', 'reviewed')
                       AND s.{CODED_PROJECT_FILTER}
                     ORDER BY s.submitted_at DESC
                     LIMIT ?2 OFFSET ?3"
                ))
                .unwrap();
            let forms: Vec<Value> = stmt
                .query_map(params![provisioned, limit as i64, offset as i64], |r| {
                    Ok(json!({
                        "va_sid": r.get::<_, String>(0)?,
                        "va_uniqueid_masked": r.get::<_, String>(1)?,
                        "va_form_id": r.get::<_, String>(2)?,
                        "project_id": r.get::<_, String>(3)?,
                        "site_id": r.get::<_, String>(4)?,
                        "va_submission_date": r.get::<_, String>(5)?,
                        "va_data_collector": r.get::<_, Option<String>>(8)?,
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

    /// Coded cases, newest first, each with the server's answer to its latest coding result
    /// (`server_status`: `pending` while the server holds it, `refused` with `server_code`, null
    /// while not yet sent or once accepted and deleted). Locked-out projects are left out.
    /// A result whose interview a receipt already deleted stays listed from the display fields
    /// on its coding row (case id, form, project, site, coded time, stage) until a later receipt
    /// accepts it and deletes the row; no age, sex or answers are kept.
    pub fn get_coder_history(&self, limit: usize, offset: usize) -> Value {
        let provisioned = self.get_station_config().mode == "provisioned";
        self.with_conn(|conn| {
            let mut stmt = conn
                .prepare(&format!(
                    "SELECT s.va_sid, s.unique_id, s.form_type_code, s.project_id, s.site_id,
                            s.submitted_at, s.deceased_age, s.deceased_gender,
                            COALESCE(s.coded_at, s.updated_at), s.workflow_state,
                            c.sync_state, c.sync_error_code, s.updated_at
                     FROM loc_va_submissions s
                     LEFT JOIN loc_coding_results c ON c.client_id = (
                         SELECT client_id FROM loc_coding_results
                         WHERE va_sid = s.va_sid ORDER BY created_at DESC LIMIT 1)
                     WHERE s.workflow_state IN ('coded', 'not_codeable', 'reviewed')
                       AND s.{CODED_PROJECT_FILTER}
                     UNION ALL
                     SELECT c.va_sid, COALESCE(c.unique_id, c.va_sid), COALESCE(c.form_type_code, ''),
                            c.project_id, COALESCE(c.site_id, ''), '', NULL, NULL,
                            c.created_at,
                            CASE json_extract(c.payload_json, '$.stage')
                                WHEN 'not_codeable' THEN 'not_codeable' ELSE 'coded' END,
                            c.sync_state, c.sync_error_code, c.created_at
                     FROM loc_coding_results c
                     WHERE c.client_id = (
                            SELECT client_id FROM loc_coding_results
                            WHERE va_sid = c.va_sid ORDER BY created_at DESC LIMIT 1)
                       AND NOT EXISTS (SELECT 1 FROM loc_va_submissions s WHERE s.va_sid = c.va_sid)
                       AND c.{CODED_PROJECT_FILTER}
                     ORDER BY 13 DESC
                     LIMIT ?2 OFFSET ?3"
                ))
                .unwrap();
            let history: Vec<Value> = stmt
                .query_map(params![provisioned, limit as i64, offset as i64], |r| {
                    let server_status = match r.get::<_, Option<String>>(10)?.as_deref() {
                        Some("server_pending") => Some("pending"),
                        Some("rejected") => Some("refused"),
                        _ => None,
                    };
                    Ok(json!({
                        "server_status": server_status,
                        "server_code": server_status.and(r.get::<_, Option<String>>(11)?),
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
            // Sandbox defaults; a registered case carries its own project, site and unit path.
            let mut project_id = "1".to_string();
            let mut site_code = "PHC01".to_string();
            let mut site_name = station_cfg.facility_name.clone();
            let mut unit_path: Option<String> = None;

            if let Some(did) = death_id_opt {
                if let Ok((dname, dod, pid, sid, sname, ou_name)) = conn.query_row(
                    "SELECT deceased_name, date_of_death, CAST(project_id AS TEXT), site_id,
                            site_name, org_unit_name
                     FROM loc_death_register WHERE death_id = ?1",
                    params![did],
                    |r| {
                        Ok((
                            r.get::<_, String>(0)?,
                            r.get::<_, String>(1)?,
                            r.get::<_, String>(2)?,
                            r.get::<_, String>(3)?,
                            r.get::<_, String>(4)?,
                            r.get::<_, String>(5)?,
                        ))
                    },
                ) {
                    deceased_name = dname;
                    date_of_death = dod;
                    project_id = pid;
                    site_code = sid;
                    site_name = sname;
                    unit_path =
                        Some(ou_name).filter(|p| !p.trim().is_empty() && project_id != "1");
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
                project_name: (project_id == "1")
                    .then(|| format!("{} Mortality Surveillance", station_cfg.facility_name)),
                project_id,
                site_code,
                site_name: Some(site_name),
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
                place_of_death: Some(match unit_path {
                    Some(path) => format!("Reported via Verbal Autopsy; {path}"),
                    None => "Reported via Verbal Autopsy".to_string(),
                }),
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

    /// The project's stored form policy: `(form-options body, {locale: translations body})`.
    /// The sandbox project "1" has no server policy and gets `instrument::sandbox_form_options`.
    /// Err is `(status, body)`: 404 `form_policy_missing` for a project the imported config
    /// gives no form policy (or no config imported yet).
    fn form_policy(&self, project_id: &str) -> Result<(Value, Value), (u16, Value)> {
        if project_id == "1" {
            let (modules, _) = self.local_station_choices();
            return Ok((instrument::sandbox_form_options(project_id, &modules), json!({})));
        }
        let row: Option<(String, String)> = self.with_conn(|conn| {
            conn.query_row(
                "SELECT form_options_json, translations_json FROM loc_project_form_policy WHERE project_id = ?1",
                params![project_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .ok()
            .flatten()
        });
        let Some((options, translations)) = row else {
            return Err((
                404,
                json!({
                    "error": "This station has no form for this project yet. Import a station config issued by the server.",
                    "code": "form_policy_missing"
                }),
            ));
        };
        let mut options: Value = serde_json::from_str(&options).unwrap_or(Value::Null);
        // A policy without `enabled_extensions` leaves the modules to the station's selection.
        if options.is_object() && !options["enabled_extensions"].is_array() {
            let (modules, _) = self.local_station_choices();
            let local = instrument::sandbox_form_options(project_id, &modules);
            options["enabled_extensions"] = local["enabled_extensions"].clone();
            options["definition_sha256"] = local["definition_sha256"].clone();
        }
        Ok((options, serde_json::from_str(&translations).unwrap_or_else(|_| json!({}))))
    }

    /// `GET /organization/<project>/form-options`: the body the server issued in the config.
    pub fn form_options(&self, project_id: &str) -> Result<Value, (u16, Value)> {
        self.form_policy(project_id).map(|(options, _)| options)
    }

    /// `GET /instruments/<code>/definition?project_id=[&version=&extensions=]`: the project's
    /// slice of the embedded composed definition (the bytes the server serves), or the exact
    /// earlier slice a draft names.
    pub fn instrument_definition(
        &self,
        code: &str,
        project_id: &str,
        slice: Option<(&str, Vec<String>)>,
    ) -> Result<std::sync::Arc<ServedDefinition>, (u16, Value)> {
        let not_found = || (404, json!({ "error": "Definition not found.", "code": "not_found" }));
        let (options, _) = self.form_policy(project_id)?;
        let served_code = options["form_types"]
            .as_array()
            .into_iter()
            .flatten()
            .find(|ft| ft["is_default"].as_bool() == Some(true))
            .and_then(|ft| ft["instrument_code"].as_str())
            .unwrap_or(instrument::INSTRUMENT_CODE);
        if !code.eq_ignore_ascii_case(instrument::INSTRUMENT_CODE) || served_code != instrument::INSTRUMENT_CODE {
            return Err(not_found());
        }
        match slice {
            None => Ok(instrument::served_definition(instrument::enabled_extensions(&options))),
            Some((version, extensions)) => instrument::definition_slice(version, &extensions).map_err(|e| match e {
                instrument::DefinitionError::UnknownVersion => {
                    (404, json!({ "error": "Form version not found.", "code": "version_unknown" }))
                }
                instrument::DefinitionError::InvalidExtensions(_) => (
                    422,
                    json!({ "error": "Unknown extensions for that form version.", "code": "invalid_extensions" }),
                ),
            }),
        }
    }

    /// `GET /instruments/<code>/translations/<locale>[?project_id=]`: the body the server issued
    /// in the config for that locale; "en" is the base body. Without `project_id` (the browser
    /// form's call) any project's copy serves, as the server serves any servable locale.
    pub fn instrument_translations(
        &self,
        code: &str,
        locale: &str,
        project_id: Option<&str>,
    ) -> Result<Value, (u16, Value)> {
        let not_found = || (404, json!({ "error": "Translation not found.", "code": "not_found" }));
        let code = code.trim().to_ascii_uppercase();
        if let Some(pid) = project_id {
            let (options, translations) = self.form_policy(pid).map_err(|_| not_found())?;
            let offered = options["available_locales"]
                .as_array()
                .into_iter()
                .flatten()
                .any(|l| l["code"].as_str() == Some(locale));
            if !offered || code != instrument::INSTRUMENT_CODE {
                return Err(not_found());
            }
            if locale == instrument::BASE_LOCALE {
                return Ok(instrument::base_translations(&code));
            }
            return translations.get(locale).cloned().ok_or_else(not_found);
        }
        if locale == instrument::BASE_LOCALE {
            return Ok(instrument::base_translations(&code));
        }
        let rows: Vec<String> = self.with_conn(|conn| {
            conn.prepare("SELECT translations_json FROM loc_project_form_policy ORDER BY project_id")
                .and_then(|mut stmt| stmt.query_map([], |r| r.get(0))?.collect())
                .unwrap_or_default()
        });
        rows.iter()
            .filter_map(|raw| serde_json::from_str::<Value>(raw).ok())
            .find_map(|t| t.get(locale).filter(|body| body["instrument_code"].as_str() == Some(code.as_str())).cloned())
            .ok_or_else(not_found)
    }

    /// `GET /me/home` from the station's own register (the server's `get_home_blocks` shape:
    /// `{roles, blocks}`, one block per device-projected role, counts only). Station counts are
    /// station-wide: the register here is the station's own.
    pub fn home_blocks(&self) -> Result<Value, String> {
        let summary = self.build_access_summary()?;
        let mut roles: Vec<String> = summary["roles"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(|r| r.as_str().map(ToString::to_string))
            .collect();
        roles.sort();
        let has = |role: &str| roles.iter().any(|r| r == role);
        let (registered, awaiting, drafts, ready, completed) = self.with_conn(|conn| {
            conn.query_row(
                "SELECT
                    (SELECT COUNT(*) FROM loc_death_register WHERE status NOT IN ('duplicate', 'cancelled')),
                    (SELECT COUNT(*) FROM loc_death_register
                      WHERE status NOT IN ('duplicate', 'cancelled') AND va_sid IS NULL),
                    (SELECT COUNT(*) FROM loc_va_drafts WHERE status != 'submitted'),
                    (SELECT COUNT(*) FROM loc_va_submissions
                      WHERE workflow_state NOT IN ('coded', 'not_codeable', 'reviewed')),
                    (SELECT COUNT(*) FROM loc_va_submissions
                      WHERE workflow_state IN ('coded', 'not_codeable', 'reviewed'))",
                [],
                |r| Ok((r.get::<_, i64>(0)?, r.get::<_, i64>(1)?, r.get::<_, i64>(2)?, r.get::<_, i64>(3)?, r.get::<_, i64>(4)?)),
            )
            .map_err(|e| e.to_string())
        })?;
        let mut blocks = serde_json::Map::new();
        if has("death_reporter") {
            blocks.insert("death_reporter".into(), json!({ "registered": registered, "awaiting_interview": awaiting }));
        }
        if has("interviewer") {
            blocks.insert("interviewer".into(), json!({ "drafts_in_progress": drafts, "needing_visit": awaiting }));
        }
        if has("coder") {
            // Every coded case stays recodeable on the station (its coding history marks them so).
            blocks.insert(
                "coder".into(),
                json!({ "ready": ready, "practice": false, "completed": completed, "recodeable": completed }),
            );
        } else if has("coding_tester") {
            blocks.insert("coder".into(), json!({ "ready": ready, "practice": true }));
        }
        if has("reviewer") {
            // The station's reviewing queue is empty (its /reviewing/stats reports 0).
            blocks.insert("reviewer".into(), json!({ "available": 0, "completed": 0 }));
        }
        Ok(json!({ "roles": roles, "blocks": blocks }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_update_facility_details_validates_persists_and_renames_the_sandbox_project() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        assert!(db.update_facility_details("  ", "", "", "", "", "").is_err());
        assert!(db.update_facility_details(&"x".repeat(201), "", "", "", "", "").is_err());
        assert!(db.update_facility_details("A", "", "", &"x".repeat(501), "", "").is_err());
        assert_eq!(db.get_station_config().facility_name, "Model Primary Health Centre");

        let cfg = db
            .update_facility_details(" Rampur PHC ", "RP01", "PHC", "Main Rd", "Rampur", "UP")
            .unwrap();
        assert_eq!(cfg.facility_name, "Rampur PHC");
        let read = db.get_station_config();
        assert_eq!(
            (read.facility_code.as_str(), read.facility_type.as_str(), read.facility_address.as_str()),
            ("RP01", "PHC", "Main Rd")
        );
        assert_eq!((read.district_name.as_str(), read.state_name.as_str()), ("Rampur", "UP"));
        assert_eq!(db.station_projects()[0].1, "Rampur PHC Mortality Surveillance");
    }

    #[test]
    fn test_grant_targets_null_org_unit_grant_is_limited_to_its_sites_units() {
        let grant = |site: &str| RosterRoleGrant {
            role: ActingRole::DeathReporter,
            project_id: "P1".to_string(),
            site_id: site.to_string(),
            org_unit_id: None,
        };
        let mut project = StationProjectConfig {
            project_id: "P1".to_string(),
            project_name: None,
            sites: vec!["A".to_string(), "B".to_string()],
            org_units: vec!["ou-a".to_string(), "ou-b".to_string()],
            site_names: BTreeMap::new(),
            org_unit_paths: BTreeMap::new(),
            org_unit_sites: BTreeMap::from([
                ("ou-a".to_string(), "A".to_string()),
                ("ou-b".to_string(), "B".to_string()),
            ]),
            sealed_field_ids: vec![],
            instrument_versions: vec![],
            consent: None,
            form_options: None,
            translations: BTreeMap::new(),
            coding_mode: None,
        };
        let roles = [ActingRole::DeathReporter];
        let units = |t: &[GrantTarget]| -> Vec<String> {
            t.iter().flat_map(|t| t.org_units.iter().map(|(id, _)| id.clone())).collect()
        };

        let targets = grant_targets(&project, &[grant("A")], &roles);
        assert_eq!(units(&targets), vec!["ou-a"]);

        // Older config without the map: the grant still covers every project unit.
        project.org_unit_sites.clear();
        let targets = grant_targets(&project, &[grant("A")], &roles);
        assert_eq!(units(&targets), vec!["ou-a", "ou-b"]);
    }

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
        assert_eq!(err_body["code"], "consent_required_for_informant");
        assert!(err_body["fields"]["consent"].is_string());
        assert_eq!(err_body["informant_fields"], json!(["informant_name", "informant_phone"]));

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
                "notice_version_id": crate::consent::DEFAULT_NOTICE_VERSION_ID_EN,
                "notice_language": "en",
                "notice_sha256": sandbox_en_notice_sha(),
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
                "notice_version_id": crate::consent::DEFAULT_NOTICE_VERSION_ID_EN,
                "notice_language": "en",
                "notice_sha256": sandbox_en_notice_sha(),
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
        assert_eq!(db.list_cases(&CaseListQuery::default()).unwrap()["counts"]["total"], 1);

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
        assert_eq!(db.list_cases(&CaseListQuery::default()).unwrap()["counts"]["total"], 0);
    }

    fn case_query(limit: Option<&str>, cursor: Option<&str>, registered: Option<&str>) -> CaseListQuery {
        CaseListQuery {
            limit: limit.map(str::to_string),
            cursor: cursor.map(str::to_string),
            registered: registered.map(str::to_string),
        }
    }

    #[test]
    fn test_case_list_query_follows_server_limits() {
        let page = |l: Option<&str>| case_query(l, None, None).parse().map(|p| p.limit);
        assert_eq!(page(None), Ok(CASE_PAGE_DEFAULT));
        assert_eq!(page(Some("")), Ok(CASE_PAGE_DEFAULT));
        assert_eq!(page(Some("10")), Ok(10));
        assert_eq!(page(Some(" 7 ")), Ok(7));
        assert_eq!(page(Some("0")), Ok(1));
        assert_eq!(page(Some("-5")), Ok(1));
        assert_eq!(page(Some("5000")), Ok(CASE_PAGE_MAX));
        assert_eq!(page(Some("ten")), Err("limit must be a whole number.".to_string()));
        assert_eq!(page(Some("  ")), Err("limit must be a whole number.".to_string()));

        let cursor = |c: &str| case_query(None, Some(c), None).parse().map(|p| p.after);
        assert_eq!(cursor(""), Ok(None));
        assert_eq!(cursor("42"), Ok(Some(42)));
        for bad in ["0", "-1", "abc", "1_2"] {
            assert_eq!(cursor(bad), Err("Invalid cursor.".to_string()), "{bad}");
        }

        let mine = |r: &str| case_query(None, None, Some(r)).parse().map(|p| p.registered_mine);
        assert_eq!(mine(""), Ok(false));
        assert_eq!(mine("mine"), Ok(true));
        assert_eq!(mine("all"), Err("registered must be mine.".to_string()));
    }

    #[test]
    fn test_list_cases_pages_with_keyset_cursor_and_registered_mine() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let register = |name: &str| {
            let reg = json!({
                "project_id": "1",
                "site_id": "PHC01",
                "deceased_name": name,
                "deceased_sex": "female",
                "date_of_death": "2026-10-18"
            });
            db.register_death(&reg, "test").unwrap();
        };
        // Empty register: an empty page, no cursor.
        let empty = db.list_cases(&CaseListQuery::default()).unwrap();
        assert_eq!(empty["cases"], json!([]));
        assert!(empty["next_cursor"].is_null());
        assert_eq!(empty["counts"]["total"], 0);

        for n in 0..3 {
            register(&format!("Mine {n}"));
        }
        db.switch_acting_role("roster-hs-1", None).unwrap();
        for n in 0..2 {
            register(&format!("Theirs {n}"));
        }

        let ids = |page: &Value| -> Vec<String> {
            page["cases"]
                .as_array()
                .unwrap()
                .iter()
                .map(|c| c["death_id"].as_str().unwrap().to_string())
                .collect()
        };

        // Whole register, two at a time, newest first; counts cover all five.
        let first = db.list_cases(&case_query(Some("2"), None, None)).unwrap();
        assert_eq!(ids(&first), vec!["5", "4"]);
        assert_eq!(first["deaths"], first["cases"]);
        assert_eq!(first["counts"]["total"], 5);
        assert_eq!(first["next_cursor"], "4");
        let second = db.list_cases(&case_query(Some("2"), Some("4"), None)).unwrap();
        assert_eq!(ids(&second), vec!["3", "2"]);
        let last = db
            .list_cases(&case_query(Some("2"), second["next_cursor"].as_str(), None))
            .unwrap();
        assert_eq!(ids(&last), vec!["1"]);
        assert!(last["next_cursor"].is_null());

        // registered=mine: the active actor's own registrations only.
        let theirs = db.list_cases(&case_query(None, None, Some("mine"))).unwrap();
        assert_eq!(ids(&theirs), vec!["5", "4"]);
        assert_eq!(theirs["counts"]["total"], 2);
        assert!(theirs["next_cursor"].is_null());
        db.switch_acting_role("roster-mo-1", None).unwrap();
        let mine_first = db.list_cases(&case_query(Some("1"), None, Some("mine"))).unwrap();
        assert_eq!(ids(&mine_first), vec!["3"]);
        assert_eq!(mine_first["counts"]["total"], 3);
        let mine_next = db
            .list_cases(&case_query(Some("5"), mine_first["next_cursor"].as_str(), Some("mine")))
            .unwrap();
        assert_eq!(ids(&mine_next), vec!["2", "1"]);

        // Malformed input is refused, never echoed.
        let err = db.list_cases(&case_query(Some("x"), None, None)).unwrap_err();
        assert_eq!(err, "limit must be a whole number.");
        assert_eq!(db.case_counts().unwrap()["total"], 5);
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

        // Station modes are unmasked: no Step 1 is saved, and both modes open on the final step.
        assert!(db
            .save_coding_assessment(
                va_sid,
                "initial",
                &json!({ "immediate_cod": "CA40", "antecedent_cod": "CA40", "conclusive_cod": "CA40" }),
            )
            .is_err());
        // ICD-11 + DORIS by default; ICD-10 is the server's simple workspace on ICD-10.
        let ws = db.get_va_workspace(va_sid, "coding").unwrap();
        assert_eq!((ws["case"]["project_mode"].as_str(), ws["case"]["icd_classification"].as_str()), (Some("unmasked_doris"), Some("icd11")));
        assert_eq!(ws["step"], "final");
        assert!(ws["assessments"]["initial"].is_null());
        assert!(ws["doris"].is_object());
        db.update_station_settings(None, Some(CODING_MODE_ICD10)).unwrap();
        let ws = db.get_va_workspace(va_sid, "coding").unwrap();
        assert_eq!((ws["case"]["project_mode"].as_str(), ws["case"]["icd_classification"].as_str()), (Some("unmasked_simple"), Some("icd10")));
        assert_eq!(ws["step"], "final");
        assert!(ws["doris"].is_null());
        let saved = db
            .save_coding_assessment(
                va_sid,
                "final",
                &json!({ "immediate_cod": "CA40", "antecedent_cod": "CA40", "conclusive_cod": "CA40" }),
            )
            .unwrap();
        // No ODK on the station: the reply makes no ODK claim.
        assert!(saved.get("odk_synced").is_none());
        assert_eq!(db.get_va_workspace(va_sid, "coding").unwrap()["step"], "done");
        let saved_mode: Option<String> = db.with_conn(|conn| {
            conn.query_row("SELECT coding_mode FROM loc_coding_results WHERE va_sid = ?1", params![va_sid], |r| r.get(0))
                .unwrap()
        });
        assert_eq!(saved_mode.as_deref(), Some(CODING_MODE_ICD10));

        let pdf_bytes = db.generate_mccd_pdf_for_va(va_sid).unwrap();
        assert!(pdf_bytes.starts_with(b"%PDF-1.4"));

        // Standalone sandbox mode .dvb export must be refused with 403 sandbox_not_exportable
        let (exp_status, exp_err) = db.export_dvb_bundle().unwrap_err();
        assert_eq!(exp_status, 403);
        assert_eq!(exp_err["code"], "sandbox_not_exportable");
    }

    #[test]
    fn test_doris_seed_is_the_servers_unmasked_shape() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let draft = db.start_draft(&json!({ "project_id": "1", "site_id": "PHC01" })).unwrap();
        let draft_id = draft["draft"]["draft_id"].as_str().unwrap().to_string();
        let data = json!({ "Id10019": "female", "Id10022": "yes", "Id10023": "2026-10-15",
                           "age_group": "adult", "age_adult": "34", "Id10310": "yes", "Id10077": "no" });
        let (_, submitted) = db
            .submit_draft(&draft_id, &json!({ "completion": { "valid": true, "issues": [], "data": data } }))
            .unwrap();
        let va_sid = submitted["va_sid"].as_str().unwrap();

        let ws = db.get_va_workspace(va_sid, "coding").unwrap();
        let keys: Vec<&String> = ws["doris"].as_object().unwrap().keys().collect();
        assert_eq!(keys, vec!["initial_certificate", "prefill_provenance"]);
        assert_eq!(
            ws["doris"]["initial_certificate"],
            json!({
                "AdministrativeData": { "Sex": 2, "DateDeath": "2026-10-15", "EstimatedAge": "P34Y" },
                "MaternalDeath": { "WasPregnant": 0 },
                "MannerOfDeath": { "MannerOfDeath": 0 }
            })
        );
        assert_eq!(ws["doris"]["prefill_provenance"]["AdministrativeData.Sex"], json!({ "sources": ["Id10019"] }));

        // A saved final certificate seeds the editor as it is, with no prefill markers.
        let saved = json!({ "ICDVersion": "ICD11", "AdministrativeData": { "Sex": 2 }, "Part1": [] });
        db.save_coding_assessment(va_sid, "final", &json!({ "conclusive_cod": "BA41.Z", "doris_certificate": saved }))
            .unwrap();
        let ws = db.get_va_workspace(va_sid, "coding").unwrap();
        assert_eq!((&ws["doris"]["initial_certificate"], &ws["doris"]["prefill_provenance"]), (&saved, &json!({})));
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

    const TEST_NOTICE_TEXT: &str = "DPDP Notice v1 for Project TST001";

    fn test_notice_vid() -> Uuid {
        Uuid::parse_str("00000000-0000-4000-8000-000000000010").unwrap()
    }

    fn test_server_signing_key() -> StationSigningKey {
        StationSigningKey::from_secret_bytes(&[0x41u8; 32])
    }

    /// A config for `device_id` in server project TST001, signed by `test_server_signing_key`,
    /// with one active death reporter + interviewer per `roster_user_ids` entry.
    fn signed_test_station_config(
        device_id: &str,
        config_id: &str,
        issued_at: &str,
        roster_user_ids: &[i64],
    ) -> String {
        signed_test_station_config_with(device_id, config_id, issued_at, roster_user_ids, test_form_options())
    }

    /// TST001's form policy as the server issues it: the typical project's modules (social
    /// autopsy disabled), English and Hindi offered, a version and SHA-256 of the embedded
    /// composed definition (`served_definition_vectors.json`, case `typical_project`).
    fn test_form_options() -> Value {
        json!({
            "project_id": "TST001",
            "config_version": "2026-09-30T19:16:47.583260",
            "enabled_extensions": ["digitva_core", "doris_support_whova_2022", "intake_screen", "death_summary",
                                   "medical_records", "geography", "narration_language", "abha"],
            "form_types": [{ "form_type_code": "WHO_2022_VA", "instrument_code": "WHO_2022_VA",
                             "title": "WHO 2022 VA Form", "is_default": true }],
            "intake_note": null,
            "default_locale": "en",
            "available_locales": [{ "code": "en", "label": "English", "under_review": false },
                                  { "code": "hi", "label": "Hindi", "under_review": true }],
            "translation_versions": { "en": 0, "hi": 6, "ta": 2 },
            "narration_languages": [{ "code": "english", "label": "English" }, { "code": "hindi", "label": "Hindi" }],
            "show_guidance": false,
            "web_intake_mode": "both",
            "instrument_version": instrument::composed_version(),
            "definition_sha256": "88184fc7afb460b846ab16a40fc327f07047b02d56fd7a985900515a8df81291"
        })
    }

    fn signed_test_station_config_with(
        device_id: &str,
        config_id: &str,
        issued_at: &str,
        roster_user_ids: &[i64],
        form_options: Value,
    ) -> String {
        signed_test_station_config_consent(device_id, config_id, issued_at, roster_user_ids, form_options, true)
    }

    fn signed_test_station_config_consent(
        device_id: &str,
        config_id: &str,
        issued_at: &str,
        roster_user_ids: &[i64],
        form_options: Value,
        consent_required: bool,
    ) -> String {
        signed_test_station_config_full(
            device_id, config_id, issued_at, roster_user_ids, form_options, consent_required, None,
        )
    }

    /// A signed config whose project carries `coding_mode` (None = the key absent).
    fn signed_test_station_config_coding(device_id: &str, coding_mode: Option<Option<&str>>) -> String {
        signed_test_station_config_full(
            device_id,
            CONFIG_A,
            "2026-10-20T00:00:00Z",
            &[101],
            test_form_options(),
            true,
            coding_mode.map(|m| m.map(str::to_string)),
        )
    }

    fn signed_test_station_config_full(
        device_id: &str,
        config_id: &str,
        issued_at: &str,
        roster_user_ids: &[i64],
        form_options: Value,
        consent_required: bool,
        coding_mode: Option<Option<String>>,
    ) -> String {
        use digitva_bundle::{
            format_signed_station_config, DesignationSpec, RosterMember, RosterRoleGrant,
            ServerSigningKeyConfig, StationConfigPayload, StationCustodian,
            StationKemPublicKeyConfig, StationProjectConfig,
        };
        let vec_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/pii_envelope_vectors.json");
        let vec_data: Value =
            serde_json::from_str(&std::fs::read_to_string(vec_path).unwrap()).unwrap();
        let tv1_pub_cfg = vec_data["deterministic"]["test_keys"]["kem_keys"][0]["public_key_config"]
            .as_str()
            .unwrap()
            .to_string();
        let server_signing_key = test_server_signing_key();
        let grant = |role| RosterRoleGrant {
            role,
            project_id: "TST001".to_string(),
            site_id: "PHC01".to_string(),
            org_unit_id: None,
        };
        let payload = StationConfigPayload {
            station_config_format_version: 1,
            config_id: Uuid::parse_str(config_id).unwrap(),
            issued_at: issued_at.to_string(),
            expires_at: "2027-04-18T00:00:00Z".to_string(),
            device_id: device_id.to_string(),
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
                project_id: "TST001".to_string(),
                project_name: Some("Test Project".to_string()),
                sites: vec!["PHC01".to_string()],
                org_units: vec!["ou-sc-1".to_string()],
                site_names: BTreeMap::new(),
                org_unit_paths: BTreeMap::new(),
                org_unit_sites: BTreeMap::new(),
                sealed_field_ids: vec![
                    "Id10007".to_string(),
                    "Id10017".to_string(),
                    "Id10073".to_string(),
                    "Id99999".to_string(),
                ],
                instrument_versions: vec!["2022_v1".to_string()],
                consent: Some(json!({
                    "consent_required": consent_required,
                    "notice_versions": [
                        {
                            "notice_version_id": test_notice_vid().to_string(),
                            "version": 1,
                            "language": "en",
                            "text": TEST_NOTICE_TEXT,
                            "text_sha256": sha256_hex(TEST_NOTICE_TEXT.as_bytes()),
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
                form_options: Some(form_options).filter(|o| !o.is_null()),
                translations: BTreeMap::from([(
                    "hi".to_string(),
                    json!({ "instrument_code": "WHO_2022_VA", "locale": "hi", "version": 6,
                            "questions": { "Id10007": { "label": "उत्तरदाता का नाम" } }, "choices": {} }),
                )]),
                coding_mode,
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
            roster: roster_user_ids
                .iter()
                .map(|&user_id| RosterMember {
                    user_id,
                    name: format!("Member {user_id}"),
                    designation: "medical_officer".to_string(),
                    roles: vec![grant(ActingRole::DeathReporter), grant(ActingRole::Interviewer)],
                    active: true,
                })
                .collect(),
            purge: vec![],
        };
        format_signed_station_config(&payload, &server_signing_key).unwrap()
    }

    fn active_roster_user_ids(db: &OfflineDatabase) -> Vec<i64> {
        db.get_roster()
            .members
            .iter()
            .filter(|m| m.active && m.source == "provisioned")
            .filter_map(|m| m.user_id)
            .collect()
    }

    /// The served text hash of the sandbox default config's English notice.
    fn sandbox_en_notice_sha() -> String {
        crate::consent::default_project_consent_config("1").notices[0].text_sha256.clone()
    }

    fn granted_consent(consent_cid: Uuid) -> Value {
        json!({
            "client_id": consent_cid.to_string(),
            "decision": "granted",
            "notice_version_id": test_notice_vid().to_string(),
            "notice_language": "en",
            "notice_sha256": sha256_hex(TEST_NOTICE_TEXT.as_bytes()),
            "mode": "spoken",
            "purposes": [
                { "code": "record_and_interview", "granted": true },
                { "code": "contact_followup", "granted": true },
                { "code": "cause_of_death_coding", "granted": true },
                { "code": "statistical_reports", "granted": true }
            ]
        })
    }

    const CONFIG_A: &str = "a1000000-0000-4000-8000-000000000001";
    const CONFIG_B: &str = "a1000000-0000-4000-8000-000000000002";
    const CONFIG_C: &str = "a1000000-0000-4000-8000-000000000003";

    #[test]
    fn test_signed_station_config_import_bundle_export_and_receipt_import() {
        use digitva_bundle::{
            format_signed_receipt, BundleReceiptReport, ReceiptRecordOutcome,
            RecordIngestOutcome, RecordType,
        };

        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        let signed_cfg =
            signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101]);
        let import_res = db.import_signed_station_config(&signed_cfg).unwrap();
        assert_eq!(import_res["mode"], "provisioned");
        assert_eq!(import_res["device_id"], device_id.as_str());

        // The UI learns the server's project id, not the sandbox "1".
        let access = db.build_access_summary().unwrap();
        assert_eq!(access["projects"].as_array().unwrap().len(), 1);
        assert_eq!(access["projects"][0]["project_id"], "TST001");

        // Register a death + consent in the server's string project id
        let death_cid = Uuid::new_v4();
        let consent_cid = Uuid::new_v4();
        let registered = db
            .register_death(
                &json!({
                    "project_id": "TST001",
                    "site_id": "PHC01",
                    "org_unit_id": "ou-sc-1",
                    "client_death_id": death_cid.to_string(),
                    "deceased_name": "Provisioned Case",
                    "deceased_sex": "female",
                    "date_of_death": "2026-10-20",
                    "informant_name": "Lakshmi",
                    "informant_phone": "9876543210",
                    "consent": granted_consent(consent_cid)
                }),
                "user-101",
            )
            .unwrap();
        assert_eq!(registered["case"]["project_id"], "TST001");

        // Export .dvb bundle: every record and the manifest carry the server's id
        let (built, filename, _) = db.export_dvb_bundle().unwrap();
        assert!(filename.starts_with(&format!("digitva-{device_id}-000001-")));
        assert_eq!(built.items.len(), 2);
        assert_eq!(built.manifest.project_ids, vec!["TST001".to_string()]);

        // Import signed .dvb.receipt that accepts both records
        let mut counts = BTreeMap::new();
        counts.insert("accepted".to_string(), 2);
        let receipt_report = BundleReceiptReport {
            bundle_id: built.manifest.bundle_id,
            device_id: device_id.clone(),
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
        let signed_receipt =
            format_signed_receipt(&receipt_report, &test_server_signing_key()).unwrap();
        let rec_res = db.import_dvb_receipt(&signed_receipt).unwrap();
        assert_eq!(rec_res["deleted_count"], 2);
        assert_eq!(db.list_cases(&CaseListQuery::default()).unwrap()["counts"]["total"], 0);
    }

    #[test]
    fn test_provisioned_export_leaves_sandbox_records_behind() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        // Sandbox practice cases recorded before onboarding. No project id is the sandbox
        // "1"; a numeric 1 is the same project.
        for project_id in [Value::Null, json!(1)] {
            let case = db
                .register_death(
                    &json!({
                        "project_id": project_id,
                        "deceased_name": "Sandbox Case",
                        "deceased_sex": "male",
                        "date_of_death": "2026-10-20"
                    }),
                    "user-101",
                )
                .unwrap();
            assert_eq!(case["case"]["project_id"], "1");
        }
        db.import_signed_station_config(&signed_test_station_config(
            &device_id,
            CONFIG_A,
            "2026-10-20T00:00:00Z",
            &[101],
        ))
        .unwrap();
        db.register_death(
            &json!({
                "project_id": "TST001", "site_id": "PHC01", "org_unit_id": "ou-sc-1",
                "client_death_id": Uuid::new_v4().to_string(),
                "deceased_name": "Real Case", "deceased_sex": "female", "date_of_death": "2026-10-20"
            }),
            "user-101",
        )
        .unwrap();
        assert_eq!(db.count_pending_sandbox_records(), 2);
        let (built, _, _) = db.export_dvb_bundle().unwrap();
        assert_eq!(built.items.len(), 1);
        assert_eq!(built.manifest.project_ids, vec!["TST001".to_string()]);
        assert_eq!(db.count_pending_sandbox_records(), 2, "sandbox data stays");
    }

    #[test]
    fn test_informant_fields_need_consent_even_when_project_does_not_require_it() {
        for (consent_required, config_id) in [(false, CONFIG_A), (true, CONFIG_B)] {
            let db = OfflineDatabase::open_in_memory().unwrap();
            let device_id = db.get_station_config().station_id;
            db.import_signed_station_config(&signed_test_station_config_consent(
                &device_id, config_id, "2026-10-20T00:00:00Z", &[101], test_form_options(), consent_required,
            ))
            .unwrap();
            let cdid = Uuid::new_v4().to_string();
            let mut body = json!({
                "project_id": "TST001", "site_id": "PHC01", "org_unit_id": "ou-sc-1",
                "client_death_id": cdid,
                "deceased_name": "Case", "deceased_sex": "female", "date_of_death": "2026-10-20",
                "informant_name": "Lakshmi"
            });
            let (status, err) = db.register_death(&body, "user-101").unwrap_err();
            assert_eq!(status, 422, "consent_required={consent_required}");
            assert_eq!(err["code"], "consent_required_for_informant");
            assert_eq!(err["informant_fields"], json!(["informant_name"]));

            body["consent"] = granted_consent(Uuid::new_v4());
            db.register_death(&body, "user-101").unwrap();
            let (built, _, _) = db.export_dvb_bundle().unwrap();
            assert_eq!(built.items.len(), 2, "death + consent export");
        }
    }

    /// A provisioned TST001 station (roster user 101) whose project consent config is what the
    /// server serves before any notice exists: `notice_versions: []`.
    fn provisioned_db_without_consent_notice() -> OfflineDatabase {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101]))
            .unwrap();
        db.with_conn(|conn| {
            conn.execute(
                "UPDATE consent_configs SET config_json = ?1 WHERE project_id = 'TST001'",
                params![json!({ "consent_required": true, "notice_versions": [], "purposes": [] }).to_string()],
            )
            .unwrap();
        });
        db
    }

    fn tst001_registration(informant_name: Option<&str>) -> Value {
        let mut body = json!({
            "project_id": "TST001", "site_id": "PHC01", "org_unit_id": "ou-sc-1",
            "client_death_id": Uuid::new_v4().to_string(),
            "deceased_name": "Case", "deceased_sex": "female", "date_of_death": "2026-10-20"
        });
        if let Some(name) = informant_name {
            body["informant_name"] = json!(name);
        }
        body
    }

    #[test]
    fn test_no_consent_notice_refuses_consent_and_informant_details_without_fallback() {
        let db = provisioned_db_without_consent_notice();

        // A consent cannot be taken against a notice the project does not have.
        let mut body = tst001_registration(Some("Lakshmi"));
        body["consent"] = granted_consent(Uuid::new_v4());
        let (status, err) = db.register_death(&body, "user-101").unwrap_err();
        assert_eq!((status, err["code"].as_str()), (422, Some(crate::consent::CONSENT_NOTICE_UNAVAILABLE)));
        // Informant details without a consent get the same answer, not "record a consent".
        let (status, err) = db.register_death(&tst001_registration(Some("Lakshmi")), "user-101").unwrap_err();
        assert_eq!((status, err["code"].as_str()), (422, Some(crate::consent::CONSENT_NOTICE_UNAVAILABLE)));
        assert_eq!(err["informant_fields"], json!(["informant_name"]));
        let stored: i64 = db.with_conn(|conn| {
            conn.query_row("SELECT COUNT(*) FROM consent_records", [], |r| r.get(0)).unwrap()
        });
        assert_eq!(stored, 0, "nothing is stored on a fallback notice");

        // Without informant details the registration goes through and exports.
        db.register_death(&tst001_registration(None), "user-101").unwrap();
        let (built, _, held_back) = db.export_dvb_bundle().unwrap();
        assert_eq!((built.items.len(), held_back.len()), (1, 0));
    }

    #[test]
    fn test_consent_must_match_the_served_notice_version() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101]))
            .unwrap();

        let mismatches = [
            ("notice_version_id", json!("1")),
            ("notice_version_id", json!(Uuid::new_v4().to_string())),
            ("notice_language", json!("hi")),
            ("notice_language", Value::Null),
            ("notice_sha256", json!("0".repeat(64))),
            ("notice_sha256", Value::Null),
            ("purposes", json!([{ "code": "record_and_interview", "granted": true },
                               { "code": "contact_followup", "granted": true },
                               { "code": "cause_of_death_coding", "granted": true },
                               { "code": "statistical_reports", "granted": true },
                               { "code": "research_sharing", "granted": true }])),
        ];
        for (key, value) in mismatches {
            let mut body = tst001_registration(Some("Lakshmi"));
            let mut consent = granted_consent(Uuid::new_v4());
            consent[key] = value.clone();
            body["consent"] = consent;
            let (status, err) = db.register_death(&body, "user-101").unwrap_err();
            assert_eq!((status, err["code"].as_str()), (422, Some("invalid_registration")), "{key} = {value}");
        }

        let mut body = tst001_registration(Some("Lakshmi"));
        body["consent"] = granted_consent(Uuid::new_v4());
        db.register_death(&body, "user-101").unwrap();
        let (vid, sha): (String, String) = db.with_conn(|conn| {
            conn.query_row("SELECT notice_version_id, notice_sha256 FROM consent_records", [], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })
            .unwrap()
        });
        assert_eq!((vid, sha), (test_notice_vid().to_string(), sha256_hex(TEST_NOTICE_TEXT.as_bytes())));
        let (built, _, held_back) = db.export_dvb_bundle().unwrap();
        assert_eq!((built.items.len(), held_back.len()), (2, 0));
    }

    #[test]
    fn test_export_holds_back_an_invalid_record_and_sends_the_rest() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101]))
            .unwrap();
        let consent_id = Uuid::new_v4();
        let mut with_informant = tst001_registration(Some("Lakshmi"));
        with_informant["consent"] = granted_consent(consent_id);
        let death_with_informant = with_informant["client_death_id"].as_str().unwrap().to_string();
        db.register_death(&with_informant, "user-101").unwrap();
        let plain = tst001_registration(None);
        db.register_death(&plain, "user-101").unwrap();
        // A consent row written before capture was strict: no served notice behind it.
        db.with_conn(|conn| {
            conn.execute(
                "UPDATE consent_records SET notice_sha256 = ?1, purposes_json = '[]' WHERE consent_id = ?2",
                params!["ab".repeat(32), consent_id.to_string()],
            )
            .unwrap();
        });

        let (built, _, held_back) = db.export_dvb_bundle().unwrap();
        let sent: Vec<String> = built.items.iter().map(|i| i.client_id.to_string()).collect();
        assert_eq!(sent, vec![plain["client_death_id"].as_str().unwrap().to_string()]);
        let held: Vec<(&str, &str)> = held_back
            .iter()
            .map(|h| (h["client_id"].as_str().unwrap(), h["reason"].as_str().unwrap()))
            .collect();
        assert_eq!(held.len(), 2);
        assert_eq!(held[0].0, consent_id.to_string());
        assert!(held[0].1.contains("Consent notice_language, notice_sha256, or purposes invalid"), "{}", held[0].1);
        // Its registration leans on the held-back consent, so it waits with it.
        assert_eq!(held[1].0, death_with_informant);
        assert!(held[1].1.contains("without a granted registration consent"), "{}", held[1].1);
        // Held back is not dropped: both stay pending for a later export.
        let pending: i64 = db.with_conn(|conn| {
            conn.query_row(
                "SELECT (SELECT COUNT(*) FROM consent_records WHERE sync_state = 'pending')
                      + (SELECT COUNT(*) FROM loc_death_register WHERE sync_state = 'pending')",
                [],
                |r| r.get(0),
            )
            .unwrap()
        });
        assert_eq!(pending, 3);
    }

    #[test]
    fn test_export_with_every_record_held_back_is_refused_and_keeps_the_sequence() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101]))
            .unwrap();
        let consent_id = Uuid::new_v4();
        let mut body = tst001_registration(Some("Lakshmi"));
        body["consent"] = granted_consent(consent_id);
        db.register_death(&body, "user-101").unwrap();
        db.with_conn(|conn| {
            conn.execute(
                "UPDATE consent_records SET notice_version_id = '0.1' WHERE consent_id = ?1",
                params![consent_id.to_string()],
            )
            .unwrap();
        });
        let seq_before: i64 = db.with_conn(|conn| {
            conn.query_row("SELECT bundle_seq FROM loc_station_config WHERE id = 1", [], |r| r.get(0)).unwrap()
        });

        let (status, err) = db.export_dvb_bundle().unwrap_err();
        assert_eq!((status, err["code"].as_str()), (422, Some("records_held_back")));
        let held = err["records_held_back"].as_array().unwrap();
        assert_eq!(held.len(), 2);
        assert_eq!(held[0]["client_id"], consent_id.to_string());
        assert_eq!(held[0]["reason"], "Consent notice_version_id is not a notice version id.");
        let seq_after: i64 = db.with_conn(|conn| {
            conn.query_row("SELECT bundle_seq FROM loc_station_config WHERE id = 1", [], |r| r.get(0)).unwrap()
        });
        assert_eq!(seq_after, seq_before);
    }

    #[test]
    fn test_coding_result_never_carries_a_step_one() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101]))
            .unwrap();
        // An older row may still hold a Step 1; the bundle must not carry it.
        let payload = json!({
            "stage": "final",
            "initial_assessment": { "immediate_cod": "CA40" },
            "final_assessment": { "immediate_cod": "CA40" }
        });
        db.with_conn(|conn| {
            conn.execute(
                "INSERT INTO loc_coding_results (client_id, va_sid, client_draft_id, project_id, actor_user_id,
                        acting_role, payload_json, created_at)
                 VALUES (?1, 'va-1', ?2, 'TST001', 101, 'coder', ?3, '2026-10-21T00:00:00Z')",
                params![Uuid::new_v4().to_string(), Uuid::new_v4().to_string(), payload.to_string()],
            )
            .unwrap();
        });
        let (records, _) = db.pending_bundle_records(101).unwrap();
        let coding: Vec<&CodingResultRecord> = records
            .iter()
            .filter_map(|r| match &r.payload {
                BundleRecordPayload::CodingResult(c) => Some(c),
                _ => None,
            })
            .collect();
        assert_eq!(coding.len(), 1);
        assert!(coding[0].final_cod.is_some());
        assert!(coding[0].initial.is_none());
    }

    #[test]
    fn test_station_config_import_refuses_another_device_and_an_older_config() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;

        // A config issued to another device is refused even on a never-provisioned station.
        let other = signed_test_station_config(
            "00000000-0000-4000-8000-000000000000",
            CONFIG_A,
            "2026-10-20T00:00:00Z",
            &[101],
        );
        let (status, err) = db.import_signed_station_config(&other).unwrap_err();
        assert_eq!(status, 422);
        assert_eq!(err["code"], "invalid_station_config");
        assert_eq!(db.get_station_config().mode, "standalone");

        let current = signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101, 102]);
        db.import_signed_station_config(&current).unwrap();
        let mut active = active_roster_user_ids(&db);
        active.sort_unstable();
        assert_eq!(active, vec![101, 102]);

        // Replaying an older config (102 removed) must not take effect, nor one issued at
        // the same moment under another id.
        for (config_id, issued_at) in [(CONFIG_B, "2026-10-19T00:00:00Z"), (CONFIG_B, "2026-10-20T00:00:00Z")] {
            let older = signed_test_station_config(&device_id, config_id, issued_at, &[101]);
            let (status, err) = db.import_signed_station_config(&older).unwrap_err();
            assert_eq!(status, 409);
            assert_eq!(err["code"], "station_config_superseded");
            let mut active = active_roster_user_ids(&db);
            active.sort_unstable();
            assert_eq!(active, vec![101, 102]);
        }

        // Re-importing the config in force is idempotent; a newer one replaces it.
        db.import_signed_station_config(&current).unwrap();
        let newer = signed_test_station_config(&device_id, CONFIG_C, "2026-10-21T00:00:00Z", &[101]);
        db.import_signed_station_config(&newer).unwrap();
        assert_eq!(active_roster_user_ids(&db), vec![101]);
    }

    #[test]
    fn test_server_station_config_fixture_imports_with_its_string_project_id() {
        let fixture_dir =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/station_config");
        let signed = std::fs::read_to_string(fixture_dir.join("station_config.signed")).unwrap();
        let db = OfflineDatabase::open_in_memory().unwrap();
        db.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config SET station_id = '0b8d6c2e-1f3a-4c5b-9d7e-8f9a0b1c2d3e' WHERE id = 1",
                [],
            )
            .unwrap();
        });

        let res = db.import_signed_station_config(&signed).unwrap();
        assert_eq!(res["station_config_id"], "6f1c2b3a-4d5e-4f60-8a71-92b3c4d5e6f7");
        let provisioned: Vec<_> =
            db.get_roster().members.into_iter().filter(|m| m.source == "provisioned").collect();
        assert_eq!(provisioned.len(), 2);
        assert_eq!(provisioned.iter().filter(|m| !m.active).count(), 1);
        assert!(db.with_conn(|conn| crate::consent::get_project_consent_config(conn, "TST001")).is_ok());
        let access = db.build_access_summary().unwrap();
        assert_eq!(access["projects"][0]["project_id"], "TST001");
        // The server fixture carries site_names / org_unit_paths, so units are labelled by name.
        assert_eq!(
            access["projects"][0]["actions"]["register_death"],
            json!([{
                "site_id": "TS01",
                "site_name": "Test PHC Site",
                "web_intake_mode": "both",
                "org_units": [{
                    "org_unit_id": FIXTURE_OU,
                    "unit_code": FIXTURE_OU,
                    "unit_name": "Solan, Kandaghat, PHC Chail",
                    "path": FIXTURE_OU
                }]
            }])
        );
    }

    const FIXTURE_DEVICE_ID: &str = "0b8d6c2e-1f3a-4c5b-9d7e-8f9a0b1c2d3e";
    const FIXTURE_OU: &str = "3c9e1f2a-5b6d-4e7f-8a9b-0c1d2e3f4a5b";
    const FIXTURE_OTHER_OU: &str = "7e1d2c3b-4a59-4687-9a0b-1c2d3e4f5a6b";
    const FIXTURE_OU_PATH: &str = "Test District, Test Block, Test PHC";

    /// The server fixture payload with `site_names` / `org_unit_paths` added and a third
    /// roster member (user 8) granted only another org unit, re-signed with the fixture key.
    fn labelled_fixture_station_config() -> String {
        use digitva_bundle::format_signed_station_config;
        let fixture_dir =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/station_config");
        let mut payload: Value = serde_json::from_str(
            &std::fs::read_to_string(fixture_dir.join("payload.json")).unwrap(),
        )
        .unwrap();
        payload["projects"][0]["site_names"] = json!({ "TS01": "Test Site One" });
        payload["projects"][0]["org_unit_paths"] = json!({ FIXTURE_OU: FIXTURE_OU_PATH });
        let other_grant = |role: &str| json!({
            "role": role, "project_id": "TST001", "site_id": "TS01", "org_unit_id": FIXTURE_OTHER_OU
        });
        payload["roster"].as_array_mut().unwrap().push(json!({
            "user_id": 8,
            "name": "Other Unit Worker",
            "designation": "health_worker",
            "active": true,
            "roles": [other_grant("death_reporter"), other_grant("interviewer")]
        }));
        let typed: StationConfigPayload = serde_json::from_value(payload).unwrap();
        let key = StationSigningKey::from_base64url_secret(
            std::fs::read_to_string(fixture_dir.join("test_server_signing_key")).unwrap().trim(),
        )
        .unwrap();
        format_signed_station_config(&typed, &key).unwrap()
    }

    #[test]
    fn test_provisioned_station_registers_under_granted_site_and_unit_from_signed_config() {
        let db = OfflineDatabase::open_in_memory().unwrap();

        // Sandbox before onboarding: the demo PHC01 tree.
        let sandbox = db.build_access_summary().unwrap();
        let sandbox_reg = &sandbox["projects"][0]["actions"]["register_death"][0];
        assert_eq!(sandbox["projects"][0]["project_id"], "1");
        assert_eq!(sandbox_reg["site_id"], "PHC01");
        assert_eq!(sandbox_reg["org_units"][1]["org_unit_id"], "ou-sc-1");

        db.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config SET station_id = ?1 WHERE id = 1",
                params![FIXTURE_DEVICE_ID],
            )
            .unwrap();
        });
        db.import_signed_station_config(&labelled_fixture_station_config()).unwrap();
        // The server fixture's form policy passed the station's version and SHA-256 check.
        assert_eq!(db.form_options("TST001").unwrap()["definition_sha256"],
                   "88184fc7afb460b846ab16a40fc327f07047b02d56fd7a985900515a8df81291");
        assert_eq!(db.instrument_translations("WHO_2022_VA", "hi", Some("TST001")).unwrap()["version"], 6);

        // Active actor is user 7 acting as death reporter: offered exactly TS01 + its unit.
        let actor = db.get_active_actor_context();
        assert_eq!((actor.member_id.as_str(), actor.acting_role.as_str()), ("user-7", "death_reporter"));
        let access = db.build_access_summary().unwrap();
        let project = &access["projects"][0];
        assert_eq!(project["project_id"], "TST001");
        assert_eq!(
            project["actions"]["register_death"],
            json!([{
                "site_id": "TS01",
                "site_name": "Test Site One",
                "web_intake_mode": "both",
                "org_units": [{
                    "org_unit_id": FIXTURE_OU,
                    "unit_code": FIXTURE_OU,
                    "unit_name": FIXTURE_OU_PATH,
                    "path": FIXTURE_OU
                }]
            }])
        );
        // Interviews need the interviewer acting role.
        assert_eq!(project["actions"]["interview"], json!([]));
        assert_eq!(project["sites"], json!([{ "site_id": "TS01", "site_name": "Test Site One", "roles": project["roles"] }]));
        assert_eq!(project["units"][0]["unit_name"], FIXTURE_OU_PATH);
        assert_eq!(project["units"].as_array().unwrap().len(), 1);

        let registration = |org_unit_id: &str| {
            json!({
                "project_id": "TST001",
                "site_id": "TS01",
                "org_unit_id": org_unit_id,
                "client_death_id": Uuid::new_v4().to_string(),
                "deceased_name": "Fixture Case",
                "deceased_sex": "female",
                "date_of_death": "2026-10-20"
            })
        };
        let case = db.register_death(&registration(FIXTURE_OU), "user-7").unwrap();
        assert_eq!(case["case"]["site_id"], "TS01");
        assert_eq!(case["case"]["site_name"], "Test Site One");
        assert_eq!(case["case"]["org_unit_id"], FIXTURE_OU);
        assert_eq!(case["case"]["org_unit_name"], FIXTURE_OU_PATH);

        // A unit outside user 7's grants is refused before anything is stored.
        let (status, err) = db.register_death(&registration(FIXTURE_OTHER_OU), "user-7").unwrap_err();
        assert_eq!((status, err["code"].as_str()), (403, Some("forbidden")));

        // The bundle's roster check accepts the registration.
        let (built, _, _) = db.export_dvb_bundle().unwrap();
        assert_eq!(built.items.len(), 1);

        // Acting as interviewer opens interviews at the same unit only.
        db.switch_acting_role("user-7", Some("interviewer")).unwrap();
        let interview = &db.build_access_summary().unwrap()["projects"][0]["actions"]["interview"];
        assert_eq!(interview[0]["org_units"][0]["org_unit_id"], FIXTURE_OU);
        assert_eq!(interview.as_array().unwrap().len(), 1);

        // User 8 holds no grant on the fixture unit: not offered, and refused.
        db.switch_acting_role("user-8", Some("death_reporter")).unwrap();
        let other = db.build_access_summary().unwrap();
        assert_eq!(
            other["projects"][0]["actions"]["register_death"][0]["org_units"],
            json!([{
                "org_unit_id": FIXTURE_OTHER_OU,
                "unit_code": FIXTURE_OTHER_OU,
                "unit_name": FIXTURE_OTHER_OU,
                "path": FIXTURE_OTHER_OU
            }])
        );
        let (status, _) = db.register_death(&registration(FIXTURE_OU), "user-8").unwrap_err();
        assert_eq!(status, 403);
        db.switch_acting_role("user-8", Some("interviewer")).unwrap();
        let draft_err = db
            .start_draft(&json!({ "project_id": "TST001", "site_id": "TS01", "org_unit_id": FIXTURE_OU }))
            .unwrap_err();
        assert!(draft_err.contains("not assigned"));
    }

    fn temp_db_path(tag: &str) -> PathBuf {
        std::env::temp_dir().join(format!("digitva-db-test-{tag}-{}.sqlite", Uuid::new_v4()))
    }

    fn remove_db_files(path: &Path) {
        for suffix in ["", "-wal", "-shm"] {
            let _ = std::fs::remove_file(format!("{}{suffix}", path.display()));
        }
    }

    #[test]
    fn test_station_enrolment_file_has_exactly_the_server_keys_and_a_stable_device_id() {
        use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};

        let path = temp_db_path("enrolment");
        let first = OfflineDatabase::open_file(&path, None).unwrap().station_enrolment_file().unwrap();
        let again = OfflineDatabase::open_file(&path, None).unwrap().station_enrolment_file().unwrap();

        let obj = first.as_object().unwrap();
        let mut keys: Vec<&str> = obj.keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(keys, ["app_version", "device_id", "signing_public_key"]);
        assert!(first["app_version"].as_str().unwrap().len() <= 32);
        let device_id = first["device_id"].as_str().unwrap();
        assert!(Uuid::parse_str(device_id).is_ok());
        assert_eq!(first, again, "device id and key are created once per installation");

        let raw: [u8; 32] = URL_SAFE_NO_PAD
            .decode(first["signing_public_key"].as_str().unwrap())
            .unwrap()
            .try_into()
            .unwrap();
        let db = OfflineDatabase::open_file(&path, None).unwrap();
        let stored_key_id: String = db.with_conn(|conn| {
            conn.query_row("SELECT station_signing_key_id FROM loc_station_config WHERE id = 1", [], |r| r.get(0))
                .unwrap()
        });
        assert_eq!(digitva_bundle::compute_signing_key_id(&raw), stored_key_id);
        drop(db);
        remove_db_files(&path);
    }

    #[test]
    fn test_legacy_station_store_gets_a_uuid_device_id_and_text_project_ids() {
        let path = temp_db_path("legacy");
        {
            let conn = Connection::open(&path).unwrap();
            conn.execute_batch(
                "CREATE TABLE consent_configs (
                     project_id INTEGER PRIMARY KEY,
                     consent_required INTEGER NOT NULL DEFAULT 1,
                     min_notice_version TEXT NOT NULL DEFAULT '0.1',
                     config_json TEXT NOT NULL,
                     synced_at TEXT NOT NULL
                 );
                 INSERT INTO consent_configs VALUES (1, 1, '0.1', '{}', '2026-10-01T00:00:00Z');",
            )
            .unwrap();
        }
        let db = OfflineDatabase::open_file(&path, None).unwrap();
        db.with_conn(|conn| {
            conn.execute("UPDATE loc_station_config SET station_id = 'phc-standalone-01' WHERE id = 1", [])
                .unwrap();
        });
        drop(db);

        let db = OfflineDatabase::open_file(&path, None).unwrap();
        assert!(Uuid::parse_str(&db.get_station_config().station_id).is_ok());
        db.with_conn(|conn| {
            let (kind, id): (String, String) = conn
                .query_row(
                    "SELECT (SELECT type FROM pragma_table_info('consent_configs') WHERE name = 'project_id'),
                            project_id FROM consent_configs",
                    [],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .unwrap();
            assert_eq!((kind.as_str(), id.as_str()), ("TEXT", "1"));
        });
        drop(db);
        remove_db_files(&path);
    }

    #[test]
    fn test_imported_config_serves_the_projects_form_modules_and_languages() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        // Before any config: no form for a server project, the sandbox has its own.
        let (status, err) = db.form_options("TST001").unwrap_err();
        assert_eq!((status, err["code"].as_str()), (404, Some("form_policy_missing")));
        let sandbox = db.form_options("1").unwrap();
        assert_eq!(sandbox["available_locales"].as_array().unwrap().len(), 1);
        let sandbox_def = db.instrument_definition("WHO_2022_VA", "1", None).unwrap();
        assert_eq!(sandbox_def.sha256, sandbox["definition_sha256"].as_str().unwrap());

        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(
            &device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101],
        ))
        .unwrap();

        // form-options is the server's body as issued.
        assert_eq!(db.form_options("TST001").unwrap(), test_form_options());

        // The definition's bytes hash to the issued sha; the disabled module is absent.
        let served = db.instrument_definition("WHO_2022_VA", "TST001", None).unwrap();
        assert_eq!(served.sha256, "88184fc7afb460b846ab16a40fc327f07047b02d56fd7a985900515a8df81291");
        assert_eq!(format!("{:x}", sha2::Sha256::digest(&served.body)), served.sha256);
        let body: Value = serde_json::from_slice(&served.body).unwrap();
        assert_eq!(body["extensions"], json!(["abha", "death_summary", "medical_records", "narration_language"]));
        let with_sa = instrument::served_definition(["social_autopsy"]);
        let sa_body: Value = serde_json::from_slice(&with_sa.body).unwrap();
        let names = |b: &Value| -> BTreeSet<String> {
            b["questions"].as_array().unwrap().iter().filter_map(|q| q["name"].as_str().map(String::from)).collect()
        };
        let sa_only: Vec<String> = names(&sa_body).difference(&names(&body)).cloned().collect();
        assert!(!sa_only.is_empty(), "social autopsy questions are absent from the project's form");

        // The exact slice a draft names; an unknown version or extension is refused.
        let slice = db
            .instrument_definition("WHO_2022_VA", "TST001", Some((instrument::composed_version(), vec!["social_autopsy".into()])))
            .unwrap();
        assert_eq!(slice.sha256, with_sa.sha256);
        let (status, err) = db
            .instrument_definition("WHO_2022_VA", "TST001", Some(("2022.1.5-offline", vec![])))
            .unwrap_err();
        assert_eq!((status, err["code"].as_str()), (404, Some("version_unknown")));
        assert_eq!(db.instrument_definition("OTHER", "TST001", None).unwrap_err().0, 404);

        // Languages: only what the project offers.
        let hi = db.instrument_translations("WHO_2022_VA", "hi", Some("TST001")).unwrap();
        assert_eq!(hi["version"], 6);
        assert!(hi["questions"]["Id10007"].is_object());
        assert_eq!(db.instrument_translations("WHO_2022_VA", "hi", None).unwrap(), hi);
        let en = db.instrument_translations("WHO_2022_VA", "en", Some("TST001")).unwrap();
        assert_eq!((en["version"].as_i64(), en["questions"].clone()), (Some(0), json!({})));
        // "ta" is servable on the server but not offered by the project: absent.
        assert_eq!(db.instrument_translations("WHO_2022_VA", "ta", Some("TST001")).unwrap_err().0, 404);
        assert_eq!(db.instrument_translations("WHO_2022_VA", "ta", None).unwrap_err().0, 404);
    }

    #[test]
    fn test_station_settings_default_local_selection_and_policy_lock() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        // Default: every module enabled, ICD-11 + DORIS, nothing locked.
        let settings = db.station_settings();
        let modules = settings["modules"].as_array().unwrap();
        assert_eq!(modules.len(), instrument::tag_vocabulary().len());
        assert!(modules.iter().all(|m| m["enabled"] == true));
        assert_eq!(modules.iter().find(|m| m["code"] == "social_autopsy").unwrap()["label"], "Social autopsy");
        assert_eq!((settings["coding_mode"].as_str(), settings["modules_locked"].as_bool()), (Some("icd11_doris"), Some(false)));
        assert_eq!(settings["coding_mode_locked"], false);
        assert_eq!(settings["available_coding_modes"], json!(["icd11_doris", "icd10"]));
        let all_sha = db.form_options("1").unwrap()["definition_sha256"].clone();

        // The local selection drives the sandbox form: the `typical_project` vector's modules
        // give its sha (the server's bytes).
        let typical: Vec<String> = ["abha", "death_summary", "medical_records", "narration_language"].map(String::from).to_vec();
        db.update_station_settings(Some(&typical), None).unwrap();
        let options = db.form_options("1").unwrap();
        assert_eq!(options["definition_sha256"], "88184fc7afb460b846ab16a40fc327f07047b02d56fd7a985900515a8df81291");
        assert_ne!(options["definition_sha256"], all_sha);
        let served = db.instrument_definition("WHO_2022_VA", "1", None).unwrap();
        assert_eq!(served.sha256, options["definition_sha256"].as_str().unwrap());
        let sa = db.station_settings()["modules"].as_array().unwrap().iter().find(|m| m["code"] == "social_autopsy").cloned().unwrap();
        assert_eq!(sa["enabled"], false);

        // Unknown module or mode: 400, nothing saved.
        let (status, err) = db.update_station_settings(Some(&["nope".to_string()]), Some("icd10")).unwrap_err();
        assert_eq!((status, err["code"].as_str()), (400, Some("validation_error")));
        assert_eq!(db.update_station_settings(None, Some("icd9")).unwrap_err().0, 400);
        assert_eq!(db.station_settings()["coding_mode"], "icd11_doris");

        // An imported project policy governs modules: read-only, its values shown, the local
        // selection refused with 409. The coding mode stays local (the config carries none).
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101]))
            .unwrap();
        db.with_conn(|conn| conn.execute("UPDATE loc_station_config SET enabled_modules_json = '[]' WHERE id = 1", []))
            .unwrap();
        let locked = db.station_settings();
        assert_eq!(locked["modules_locked"], true);
        let enabled: Vec<&str> = locked["modules"].as_array().unwrap().iter()
            .filter(|m| m["enabled"] == true).filter_map(|m| m["code"].as_str()).collect();
        assert_eq!(enabled, ["abha", "death_summary", "medical_records", "narration_language"]);
        let (status, err) = db.update_station_settings(Some(&[]), None).unwrap_err();
        assert_eq!((status, err["code"].as_str()), (409, Some("policy_locked")));
        assert_eq!(db.form_options("TST001").unwrap()["definition_sha256"], "88184fc7afb460b846ab16a40fc327f07047b02d56fd7a985900515a8df81291");
        assert_eq!(db.update_station_settings(None, Some("icd10")).unwrap()["coding_mode"], "icd10");
    }

    #[test]
    fn test_config_naming_a_form_version_the_station_lacks_is_refused() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        let mut options = test_form_options();
        options["instrument_version"] = json!("2099010101-ffffffffff");
        let signed = signed_test_station_config_with(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101], options);
        let (status, err) = db.import_signed_station_config(&signed).unwrap_err();
        assert_eq!((status, err["code"].as_str()), (422, Some("instrument_version_unsupported")));
        assert!(err["error"].as_str().unwrap().contains("2099010101-ffffffffff"));
        assert_eq!(db.get_station_config().mode, "standalone");

        // A config issued before form policies existed is refused with its own code.
        let no_policy = signed_test_station_config_with(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101], Value::Null);
        let (status, err) = db.import_signed_station_config(&no_policy).unwrap_err();
        assert_eq!((status, err["code"].as_str()), (422, Some("form_policy_missing")));

        // A sha that is not this binary's slice is refused alike.
        let mut options = test_form_options();
        options["definition_sha256"] = json!("0".repeat(64));
        let signed = signed_test_station_config_with(&device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101], options);
        assert_eq!(db.import_signed_station_config(&signed).unwrap_err().0, 422);
    }

    #[test]
    fn test_draft_autosave_keeps_the_definition_pin_and_the_bundle_carries_it() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config(
            &device_id, CONFIG_A, "2026-10-20T00:00:00Z", &[101],
        ))
        .unwrap();
        let death_cid = Uuid::new_v4();
        let registered = db
            .register_death(
                &json!({
                    "project_id": "TST001", "site_id": "PHC01", "org_unit_id": "ou-sc-1",
                    "client_death_id": death_cid.to_string(), "deceased_name": "Pinned Case",
                    "deceased_sex": "female", "date_of_death": "2026-10-20",
                    "consent": granted_consent(Uuid::new_v4())
                }),
                "user-101",
            )
            .unwrap();
        let death_id = registered["case"]["death_id"].as_str().unwrap().to_string();
        db.switch_acting_role("user-101", Some("interviewer")).unwrap();
        let started = db
            .start_draft(&json!({ "project_id": "TST001", "site_id": "PHC01", "org_unit_id": "ou-sc-1", "death_id": death_id }))
            .unwrap();
        let draft_id = started["draft"]["draft_id"].as_str().unwrap().to_string();
        // A new draft has no pin and no stub section.
        let fresh = db.get_draft(&draft_id).unwrap();
        assert_eq!(fresh["envelope"]["instrumentVersion"], "");
        assert!(fresh["envelope"].get("definitionSha256").is_none());
        assert_eq!(fresh["envelope"]["translation_version"], 0);

        let sha = "88184fc7afb460b846ab16a40fc327f07047b02d56fd7a985900515a8df81291";
        let pin = json!({
            "instrumentVersion": instrument::composed_version(),
            "definitionSha256": sha,
            "definitionExtensions": ["abha", "death_summary", "medical_records", "narration_language"],
            "locale": "hi",
            "translation_version": 6
        });
        let (status, ack) = db
            .save_draft_sections(&draft_id, &json!({ "sections": { "respondent_backgr": { "Id10007": "R" } }, "current_section": "respondent_backgr", "meta": pin }))
            .unwrap();
        assert_eq!((status, ack["saved_sections"].as_u64()), (200, Some(1)));
        // An emptied section replaces its answers; another section keeps its own.
        db.save_draft_sections(&draft_id, &json!({ "sections": { "info_on_deceased": { "Id10019": "female" } } })).unwrap();
        db.save_draft_sections(&draft_id, &json!({ "sections": { "respondent_backgr": {} } })).unwrap();
        let envelope = db.get_draft(&draft_id).unwrap()["envelope"].clone();
        assert_eq!(envelope["data"], json!({ "Id10019": "female" }));
        assert_eq!(envelope["definitionSha256"], sha);
        assert_eq!(envelope["instrumentVersion"], instrument::composed_version());
        assert_eq!((envelope["locale"].as_str(), envelope["translation_version"].as_i64()), (Some("hi"), Some(6)));
        assert_eq!(envelope["currentSection"], "respondent_backgr");

        let (status, _) = db
            .save_draft_sections(&draft_id, &json!({ "sections": {}, "meta": { "definitionSha256": "XYZ" } }))
            .unwrap();
        assert_eq!(status, 422);

        db.submit_draft(&draft_id, &json!({ "completion": { "valid": true, "issues": [], "data": { "Id10019": "female" } } }))
            .unwrap();
        let (status, _) = db.save_draft_sections(&draft_id, &json!({ "sections": {} })).unwrap();
        assert_eq!(status, 409);
        // The sealed record's draft meta is built from the same row (not decryptable here): the
        // manifest lists the version the interview record names.
        let (built, _, _) = db.export_dvb_bundle().unwrap();
        assert_eq!(built.manifest.instrument_versions, vec![instrument::composed_version().to_string()]);
    }

    #[test]
    fn test_me_home_counts_the_stations_own_register() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let empty = db.home_blocks().unwrap();
        let roles: Vec<&str> = empty["roles"].as_array().unwrap().iter().filter_map(Value::as_str).collect();
        assert!(roles.contains(&"interviewer"), "roles {roles:?}");
        let before = empty["blocks"]["interviewer"]["drafts_in_progress"].as_i64().unwrap();
        db.start_draft(&json!({ "project_id": "1", "site_id": "PHC01" })).unwrap();
        let after = db.home_blocks().unwrap();
        assert_eq!(after["blocks"]["interviewer"]["drafts_in_progress"].as_i64().unwrap(), before + 1);
        if roles.contains(&"death_reporter") {
            let block = &after["blocks"]["death_reporter"];
            assert!(block["registered"].as_i64().unwrap() >= block["awaiting_interview"].as_i64().unwrap());
        }
        if roles.contains(&"coder") {
            assert_eq!(after["blocks"]["coder"]["practice"], false);
        }
    }

    /// A submission row in `project_id`, as `submit_draft` leaves it.
    fn insert_test_submission(db: &OfflineDatabase, va_sid: &str, project_id: &str, workflow_state: &str) {
        db.with_conn(|conn| {
            conn.execute(
                "INSERT INTO loc_va_submissions (va_sid, unique_id, project_id, payload_json,
                    payload_fingerprint, workflow_state, submitted_at, updated_at)
                 VALUES (?1, ?1, ?2, '{}', 'fp', ?3, '2026-10-21T10:00:00Z', '2026-10-21T10:00:00Z')",
                params![va_sid, project_id, workflow_state],
            )
        })
        .unwrap();
    }

    #[test]
    fn test_config_coding_mode_locks_the_station_per_project() {
        for (config, shown, locked) in [
            (Some(Some("icd10")), json!("icd10"), true),
            (Some(Some("icd11_doris")), json!("icd11_doris"), true),
            (Some(None), Value::Null, true),
            (None, json!("icd10"), false),
        ] {
            let db = OfflineDatabase::open_in_memory().unwrap();
            // The local choice differs from the default, so a lock that ignored it would show.
            db.update_station_settings(None, Some("icd10")).unwrap();
            let device_id = db.get_station_config().station_id;
            db.import_signed_station_config(&signed_test_station_config_coding(&device_id, config)).unwrap();

            let settings = db.station_settings();
            assert_eq!(settings["coding_mode"], shown, "{config:?}");
            assert_eq!(settings["coding_mode_locked"], locked, "{config:?}");
            assert_eq!(db.project_coding_mode("TST001"), shown.as_str().map(str::to_string), "{config:?}");
            // The config's project name, not the code.
            assert_eq!(db.station_projects(), vec![("TST001".to_string(), "Test Project".to_string())]);

            let put = db.update_station_settings(None, Some("icd11_doris"));
            if locked {
                let (status, body) = put.unwrap_err();
                assert_eq!((status, body["code"].as_str()), (409, Some("policy_locked")), "{config:?}");
            } else {
                assert_eq!(put.unwrap()["coding_mode"], "icd11_doris");
            }
        }
    }

    #[test]
    fn test_null_coding_mode_hides_and_refuses_the_projects_coding() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config_coding(&device_id, Some(None))).unwrap();
        insert_test_submission(&db, "VA-SERVER", "TST001", "available_for_coding");
        insert_test_submission(&db, "VA-SANDBOX", "1", "available_for_coding");
        insert_test_submission(&db, "VA-SERVER-DONE", "TST001", "coded");

        let (status, body) = db.check_station_coding("VA-SERVER").unwrap_err();
        assert_eq!((status, body["code"].as_str()), (409, Some("station_coding_not_enabled")));
        assert_eq!(body["error"], "Coding for this project is done on the server.");
        assert!(db.check_station_coding("VA-SANDBOX").is_ok());
        assert!(db.check_station_coding("VA-UNKNOWN").is_ok());

        let queue: Vec<String> = db.get_coder_queue(50, 0)["forms"].as_array().unwrap().iter()
            .map(|f| f["va_sid"].as_str().unwrap().to_string()).collect();
        assert_eq!(queue, ["VA-SANDBOX"]);
        assert_eq!(db.get_coder_history(50, 0)["count"], 0);

        // The same cases under an icd10 lock are listed and open in the simple workspace.
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config_coding(&device_id, Some(Some("icd10")))).unwrap();
        insert_test_submission(&db, "VA-SERVER", "TST001", "available_for_coding");
        assert!(db.check_station_coding("VA-SERVER").is_ok());
        assert_eq!(db.get_coder_queue(50, 0)["count"], 1);
        assert_eq!(db.coding_mode_for_va("VA-SERVER").as_deref(), Some("icd10"));
    }

    #[test]
    fn test_receipt_keeps_pending_and_refused_coding_results_with_their_codes() {
        use digitva_bundle::{
            format_signed_receipt, BundleReceiptReport, ReceiptRecordOutcome, RecordIngestOutcome, RecordType,
        };
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config_coding(&device_id, Some(Some("icd11_doris")))).unwrap();
        let ids: Vec<Uuid> = (0..3).map(|_| Uuid::new_v4()).collect();
        for (i, id) in ids.iter().enumerate() {
            let va_sid = format!("VA-{i}");
            insert_test_submission(&db, &va_sid, "TST001", "coded");
            db.with_conn(|conn| {
                conn.execute(
                    "INSERT INTO loc_coding_results (client_id, va_sid, client_draft_id, project_id,
                        payload_json, sync_state, created_at, coding_mode)
                     VALUES (?1, ?2, ?3, 'TST001', '{}', 'pending', '2026-10-21T11:00:00Z', 'icd11_doris')",
                    params![id.to_string(), va_sid, Uuid::new_v4().to_string()],
                )
            })
            .unwrap();
        }
        let outcome = |client_id: Uuid, outcome, code: Option<&str>| ReceiptRecordOutcome {
            client_id,
            record_type: RecordType::CodingResult,
            outcome,
            code: code.map(str::to_string),
            received_sha256: None,
            death_id: None,
            unique_id: None,
        };
        let report = BundleReceiptReport {
            bundle_id: Uuid::new_v4(),
            device_id: device_id.clone(),
            kem_key_id: "tv1".to_string(),
            status: "processed".to_string(),
            counts: BTreeMap::new(),
            missing_seq: vec![],
            records: vec![
                outcome(ids[0], RecordIngestOutcome::Accepted, None),
                outcome(ids[1], RecordIngestOutcome::Pending, Some("doris_pending")),
                outcome(ids[2], RecordIngestOutcome::Rejected, Some("coding_mode_mismatch")),
            ],
            purge: vec![],
        };
        let res = db.import_dvb_receipt(&format_signed_receipt(&report, &test_server_signing_key()).unwrap()).unwrap();
        assert_eq!((res["accepted_count"].as_u64(), res["pending_count"].as_u64(), res["rejected_count"].as_u64()), (Some(1), Some(1), Some(1)));

        let rows: Vec<(String, String, Option<String>)> = db.with_conn(|conn| {
            conn.prepare("SELECT va_sid, sync_state, sync_error_code FROM loc_coding_results ORDER BY va_sid")
                .unwrap()
                .query_map([], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
                .unwrap()
                .collect::<Result<_, _>>()
                .unwrap()
        });
        assert_eq!(rows, vec![
            ("VA-1".to_string(), "server_pending".to_string(), Some("doris_pending".to_string())),
            ("VA-2".to_string(), "rejected".to_string(), Some("coding_mode_mismatch".to_string())),
        ]);
        // Neither is sent again: the export takes only `pending` rows.
        let unsent: i64 = db.with_conn(|conn| conn.query_row(
            "SELECT COUNT(*) FROM loc_coding_results WHERE sync_state = 'pending'", [], |r| r.get(0)).unwrap());
        assert_eq!(unsent, 0);

        let history = db.get_coder_history(50, 0);
        let status: BTreeMap<String, (Value, Value)> = history["history"].as_array().unwrap().iter()
            .map(|h| (h["va_sid"].as_str().unwrap().to_string(), (h["server_status"].clone(), h["server_code"].clone())))
            .collect();
        assert_eq!(status["VA-0"], (Value::Null, Value::Null));
        assert_eq!(status["VA-1"], (json!("pending"), json!("doris_pending")));
        assert_eq!(status["VA-2"], (json!("refused"), json!("coding_mode_mismatch")));

        // A later receipt that accepts the held result removes it.
        let later = BundleReceiptReport {
            records: vec![outcome(ids[1], RecordIngestOutcome::Accepted, None)],
            ..report
        };
        db.import_dvb_receipt(&format_signed_receipt(&later, &test_server_signing_key()).unwrap()).unwrap();
        let left: i64 = db.with_conn(|conn| conn.query_row("SELECT COUNT(*) FROM loc_coding_results", [], |r| r.get(0)).unwrap());
        assert_eq!(left, 1);
    }

    #[test]
    fn test_history_keeps_pending_coding_after_interview_purge_and_counts_from_receipt() {
        use digitva_bundle::{
            format_signed_receipt, BundleReceiptReport, ReceiptRecordOutcome, RecordIngestOutcome, RecordType,
        };
        let db = OfflineDatabase::open_in_memory().unwrap();
        let device_id = db.get_station_config().station_id;
        db.import_signed_station_config(&signed_test_station_config_coding(&device_id, Some(Some("icd11_doris")))).unwrap();
        let (interview_id, coding_id, gone_id) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        insert_test_submission(&db, "VA-1", "TST001", "coded");
        db.with_conn(|conn| {
            conn.execute("UPDATE loc_va_submissions SET draft_id = ?1 WHERE va_sid = 'VA-1'", params![interview_id.to_string()]).unwrap();
            conn.execute(
                "INSERT INTO loc_coding_results (client_id, va_sid, client_draft_id, project_id,
                    payload_json, sync_state, created_at, coding_mode, unique_id, form_type_code)
                 VALUES (?1, 'VA-1', ?2, 'TST001', '{\"stage\":\"final\"}', 'pending',
                    '2026-10-21T11:00:00Z', 'icd11_doris', 'UID-1', 'WHO_2022_VA')",
                params![coding_id.to_string(), interview_id.to_string()],
            ).unwrap();
        });
        let outcome = |client_id: Uuid, record_type, outcome, code: Option<&str>| ReceiptRecordOutcome {
            client_id, record_type, outcome, code: code.map(str::to_string),
            received_sha256: Some(sha256_hex(b"{}")), death_id: None, unique_id: None,
        };
        let receipt = |records| {
            let report = BundleReceiptReport {
                bundle_id: Uuid::new_v4(), device_id: device_id.clone(), kem_key_id: "tv1".to_string(),
                status: "processed".to_string(), counts: BTreeMap::new(), missing_seq: vec![], records, purge: vec![],
            };
            format_signed_receipt(&report, &test_server_signing_key()).unwrap()
        };
        // Interview accepted (deleted here), coding pending, one accepted record already gone.
        let res = db.import_dvb_receipt(&receipt(vec![
            outcome(interview_id, RecordType::InterviewSubmission, RecordIngestOutcome::Accepted, None),
            outcome(gone_id, RecordType::Consent, RecordIngestOutcome::Duplicate, None),
            outcome(coding_id, RecordType::CodingResult, RecordIngestOutcome::Pending, Some("doris_pending")),
        ])).unwrap();
        assert_eq!((res["accepted_count"].as_u64(), res["deleted_count"].as_u64(), res["pending_count"].as_u64()), (Some(2), Some(1), Some(1)));
        let interviews: i64 = db.with_conn(|c| c.query_row("SELECT COUNT(*) FROM loc_va_submissions", [], |r| r.get(0)).unwrap());
        assert_eq!(interviews, 0);

        let history = db.get_coder_history(50, 0);
        let rows = history["history"].as_array().unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(
            (rows[0]["va_uniqueid_masked"].clone(), rows[0]["server_status"].clone(), rows[0]["server_code"].clone(), rows[0]["va_code_status"].clone()),
            (json!("UID-1"), json!("pending"), json!("doris_pending"), json!("coded"))
        );

        db.import_dvb_receipt(&receipt(vec![
            outcome(coding_id, RecordType::CodingResult, RecordIngestOutcome::Accepted, None),
        ])).unwrap();
        assert_eq!(db.get_coder_history(50, 0)["count"], 0);
    }

    #[test]
    fn test_interview_prefill_uses_the_age_fields_and_never_id10051_for_age() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let case = db
            .register_death(
                &json!({
                    "deceased_name": "Ram Kumar Singh",
                    "deceased_sex": "male",
                    "date_of_death": "2026-10-19",
                    "age_years": 68,
                    "place_of_death": "PHC Chail"
                }),
                "user-101",
            )
            .unwrap();
        let death_id = case["case"]["death_id"].as_str().unwrap().to_string();
        let draft = db.start_draft(&json!({ "project_id": "1", "site_id": "PHC01", "death_id": death_id })).unwrap();
        let draft_id = draft["draft"]["draft_id"].as_str().unwrap().to_string();
        let got = db.get_draft(&draft_id).unwrap();
        let prefill = &got["prefill"];
        assert_eq!(prefill["deceased"]["ageInYears"], 68);
        assert_eq!(prefill["deceased"]["givenNames"], "Ram Kumar");
        assert_eq!(prefill["deceased"]["surname"], "Singh");
        assert_eq!(prefill["answers"]["age_group"], "adult");
        assert_eq!(prefill["answers"]["age_adult"], 68);
        assert_eq!(prefill["answers"]["Id10058"], "other_health_facility");
        // Id10051 is the yes/no question that opens the residence questions, not an age.
        assert_eq!(prefill["answers"]["Id10051"] == "yes", prefill["answers"]["Id10055"].is_string());
        assert!(prefill["interviewer"]["name"].is_string());
        // The draft's own answers start empty, as the server's do; the prefill is kept apart.
        assert_eq!(got["envelope"]["data"], json!({}));

        let child = interview_prefill(&db.get_active_actor_context(), &RegisterPrefill {
            deceased_name: Some("Asha"),
            deceased_sex: Some("female"),
            date_of_death: Some("2026-10-19"),
            age_years: Some(4.0),
            address_parts: [None, Some("Ward 3"), None, Some("Main Road")],
            ..RegisterPrefill::default()
        });
        assert_eq!(child["answers"]["Id10055"], "Ward 3, Main Road");
        assert_eq!(child["answers"]["Id10057"], "Ward 3, Main Road");
        assert_eq!(child["answers"]["age_child_years"], 4);
        assert_eq!(child["answers"]["Id10020"], "no");
        assert_eq!(child["answers"]["Id10051"], "yes");
        assert!(child["deceased"].get("surname").is_none());
        let newborn = interview_prefill(&db.get_active_actor_context(), &RegisterPrefill {
            deceased_name: Some("Baby"),
            deceased_sex: Some("male"),
            date_of_death: Some("2026-10-19"),
            age_years: Some(0.0),
            ..RegisterPrefill::default()
        });
        assert_eq!(newborn["answers"], json!({}));

        // At submit the case's age comes from the WHO age fields.
        db.submit_draft(&draft_id, &json!({ "completion": { "valid": true, "issues": [], "data": {
            "Id10013": "yes", "Id10019": "male", "Id10051": "yes", "isAdult": "1", "ageInYears": "68"
        } } })).unwrap();
        let age: Option<String> = db.with_conn(|conn| conn.query_row(
            "SELECT deceased_age FROM loc_va_submissions WHERE draft_id = ?1", params![draft_id], |r| r.get(0)).unwrap());
        assert_eq!(age.as_deref(), Some("68"));
        assert_eq!(who_age_years(&json!({ "isChild": "1", "ageInMonths": "18" })).as_deref(), Some("1"));
        assert_eq!(who_age_years(&json!({ "age_neonate_hours": 5 })).as_deref(), Some("0"));
        assert_eq!(who_age_years(&json!({ "Id10051": "yes" })), None);
    }

    #[test]
    fn test_queue_names_the_collector_and_submission_carries_the_drafts_meta() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let actor = db.get_active_actor_context();
        let draft = db.start_draft(&json!({ "project_id": "1", "site_id": "PHC01" })).unwrap();
        let draft_id = draft["draft"]["draft_id"].as_str().unwrap().to_string();
        db.with_conn(|conn| conn.execute(
            "UPDATE loc_va_drafts SET meta_json = ?1 WHERE draft_id = ?2",
            params![json!({ "startedAt": "2026-10-21T09:00:00+05:30" }).to_string(), draft_id],
        ))
        .unwrap();

        // Invalid and no outcome picked: refused as the server refuses it.
        let (status, body) = db.submit_draft(&draft_id, &json!({ "completion": { "valid": false, "issues": [{ "q": "Id10019" }], "data": {} } })).unwrap();
        assert_eq!((status, body["code"].as_str()), (422, Some("invalid_interview")));

        let issues = json!([{ "q": "Id10120" }]);
        let (status, _) = db.submit_draft(&draft_id, &json!({ "completion": { "valid": false, "issues": issues,
            "data": { "Id10013": "yes", "interview_outcome": "partially_completed" } } })).unwrap();
        assert_eq!(status, 201);
        let row = &db.get_coder_queue(10, 0)["forms"][0];
        assert_eq!(row["va_data_collector"], actor.name.as_str());

        let meta: Value = db.with_conn(|conn| conn.query_row(
            "SELECT meta_json FROM loc_va_drafts WHERE draft_id = ?1", params![draft_id],
            |r| r.get::<_, String>(0)).unwrap()).parse::<Value>().unwrap();
        assert_eq!(meta["startedAt"], "2026-10-21T09:00:00+05:30");
        assert!(meta["completedAt"].is_string());
        assert_eq!(meta["interviewOutcome"], "partially_completed");
        assert_eq!(meta["completion"], json!({ "valid": false, "issues": issues }));
        let payload: Value = db.with_conn(|conn| conn.query_row(
            "SELECT payload_json FROM loc_va_submissions WHERE draft_id = ?1", params![draft_id],
            |r| r.get::<_, String>(0)).unwrap()).parse::<Value>().unwrap();
        assert_eq!(payload["interview_outcome"], "partially_completed");
        assert_eq!(interview_outcome(&json!({ "Id10013": "No" }), true), Some("refused"));
        assert_eq!(interview_outcome(&json!({}), true), Some("completed"));
    }
}
