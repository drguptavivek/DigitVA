use chrono::Utc;
use digitva_bundle::{sha256_hex, ConsentPurposeGrant};
use rusqlite::{params, Connection, OptionalExtension};
use serde::de::{Deserializer, MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;
use std::fmt;
use uuid::Uuid;

pub const REQUIRED_PURPOSE_CODES: &[&str] = &[
    "record_and_interview",
    "contact_followup",
    "cause_of_death_coding",
    "statistical_reports",
];

pub const OPTIONAL_PURPOSE_CODES: &[&str] = &[
    "sms_whatsapp_messages",
    "research_sharing",
];

pub const DEFAULT_NOTICE_VERSION_ID_EN: &str = "00000000-0000-4000-8000-000000000001";
pub const DEFAULT_NOTICE_VERSION_ID_HI: &str = "00000000-0000-4000-8000-000000000002";

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsentNoticeLocale {
    #[serde(default = "default_notice_version_id")]
    pub notice_version_id: String,
    #[serde(default = "default_version_num")]
    pub version: i64,
    pub notice_version: String,
    pub locale: String,
    pub title: String,
    pub body_markdown: String,
    #[serde(default)]
    pub text_sha256: String,
    pub updated_at: String,
}

fn default_notice_version_id() -> String {
    DEFAULT_NOTICE_VERSION_ID_EN.to_string()
}

fn default_version_num() -> i64 {
    1
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsentPurposeSpec {
    pub code: String,
    #[serde(default)]
    pub label_key: String,
    #[serde(alias = "label")]
    pub default_label: String,
    pub required: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ConsentContacts {
    #[serde(default)]
    pub deletion_email: String,
    #[serde(default)]
    pub deletion_phone: String,
    #[serde(default)]
    pub mentor_institution: String,
    #[serde(default)]
    pub central_team: String,
    #[serde(default)]
    pub dpo: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DistrictContactInfo {
    #[serde(default)]
    pub district_name: String,
    #[serde(default, alias = "name")]
    pub contact_name: String,
    #[serde(default)]
    pub email: String,
    #[serde(default)]
    pub phone: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsentRefusalBehaviour {
    pub omit_fields: Vec<String>,
    pub allow_registration_without_informant_pii: bool,
    pub allow_interview_without_informant_pii: bool,
}

impl Default for ConsentRefusalBehaviour {
    fn default() -> Self {
        Self {
            omit_fields: vec![
                "informant_name".to_string(),
                "informant_phone".to_string(),
                "informant_phone_2".to_string(),
                "address".to_string(),
                "address_house_street".to_string(),
                "address_village_ward".to_string(),
                "address_landmark".to_string(),
                "location".to_string(),
                "Id10007".to_string(),
            ],
            allow_registration_without_informant_pii: true,
            allow_interview_without_informant_pii: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectConsentConfig {
    pub project_id: i64,
    pub consent_required: bool,
    #[serde(default = "default_version_num")]
    pub min_version: i64,
    pub min_notice_version: String,
    pub notices: Vec<ConsentNoticeLocale>,
    pub purposes: Vec<ConsentPurposeSpec>,
    pub allowed_modes: Vec<String>,
    #[serde(default = "default_true")]
    pub witness_allowed: bool,
    #[serde(default)]
    pub witness_required_for_modes: Vec<String>,
    #[serde(default)]
    pub refusal_behaviour: ConsentRefusalBehaviour,
    #[serde(default)]
    pub project_contacts: ConsentContacts,
    #[serde(default)]
    pub district_contacts: BTreeMap<String, DistrictContactInfo>,
}

impl ProjectConsentConfig {
    /// Serialize into the Contract Section 5.2 wire shape (`notice_versions`, `contacts`, `retention`, `refusal_behaviour`),
    /// while also preserving legacy keys (`notices`, `purposes`) for existing callers.
    pub fn to_contract_wire_json(&self) -> Value {
        let purposes_wire: Vec<Value> = self
            .purposes
            .iter()
            .map(|p| {
                serde_json::json!({
                    "code": p.code,
                    "label": p.default_label,
                    "required": p.required
                })
            })
            .collect();
        let allowed_modes: Vec<String> = if self.allowed_modes.is_empty() {
            vec!["spoken".to_string(), "tap".to_string(), "signed".to_string()]
        } else {
            self.allowed_modes
                .iter()
                .filter_map(|m| normalise_consent_mode(m).map(ToString::to_string))
                .collect()
        };
        let covered_fields = self.refusal_behaviour.omit_fields.clone();
        let notice_versions: Vec<Value> = self
            .notices
            .iter()
            .map(|n| {
                let sha = if n.text_sha256.len() == 64 {
                    n.text_sha256.clone()
                } else {
                    sha256_hex(n.body_markdown.as_bytes())
                };
                serde_json::json!({
                    "notice_version_id": n.notice_version_id,
                    "version": n.version,
                    "language": n.locale,
                    "text": n.body_markdown,
                    "text_sha256": sha,
                    "purposes": purposes_wire,
                    "covered_fields": covered_fields,
                    "allowed_modes": allowed_modes,
                    "witness_allowed": self.witness_allowed
                })
            })
            .collect();
        let mut districts = serde_json::Map::new();
        for (k, d) in &self.district_contacts {
            districts.insert(
                k.clone(),
                serde_json::json!({
                    "name": if d.contact_name.is_empty() { &d.district_name } else { &d.contact_name },
                    "email": d.email,
                    "phone": d.phone
                }),
            );
        }
        serde_json::json!({
            "project_id": self.project_id.to_string(),
            "consent_required": self.consent_required,
            "min_version": self.min_version,
            "min_notice_version": self.min_notice_version,
            "notice_versions": notice_versions,
            "notices": self.notices,
            "purposes": self.purposes,
            "allowed_modes": allowed_modes,
            "witness_allowed": self.witness_allowed,
            "contacts": {
                "deletion": {
                    "email": self.project_contacts.deletion_email,
                    "phone": self.project_contacts.deletion_phone
                },
                "mentor_institution": {
                    "name": self.project_contacts.mentor_institution
                },
                "central_team": {
                    "email": self.project_contacts.central_team,
                    "phone": self.project_contacts.deletion_phone
                },
                "dpo": {
                    "name": self.project_contacts.dpo
                },
                "districts": districts
            },
            "retention": {
                "period_days": 1825,
                "expiry_action": "erase"
            },
            "refusal_behaviour": "interview_without_informant_data"
        })
    }
}

fn default_true() -> bool {
    true
}

fn deserialize_purposes<'de, D>(deserializer: D) -> Result<Vec<ConsentPurposeGrant>, D::Error>
where
    D: Deserializer<'de>,
{
    struct PurposesVisitor;

    impl<'de> Visitor<'de> for PurposesVisitor {
        type Value = Vec<ConsentPurposeGrant>;

        fn expecting(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
            formatter.write_str("a list of {code, granted} objects or a map of {code: bool}")
        }

        fn visit_seq<A>(self, mut seq: A) -> Result<Self::Value, A::Error>
        where
            A: SeqAccess<'de>,
        {
            let mut list = Vec::new();
            while let Some(item) = seq.next_element::<ConsentPurposeGrant>()? {
                list.push(item);
            }
            list.sort_by(|a, b| a.code.cmp(&b.code));
            Ok(list)
        }

        fn visit_map<M>(self, mut map: M) -> Result<Self::Value, M::Error>
        where
            M: MapAccess<'de>,
        {
            let mut list = Vec::new();
            while let Some((code, granted)) = map.next_entry::<String, bool>()? {
                list.push(ConsentPurposeGrant { code, granted });
            }
            list.sort_by(|a, b| a.code.cmp(&b.code));
            Ok(list)
        }
    }

    deserializer.deserialize_any(PurposesVisitor)
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsentEnvelopeInput {
    #[serde(default, alias = "consent_id")]
    pub client_id: Option<String>,
    #[serde(default)]
    pub client_draft_id: Option<String>,
    #[serde(default, alias = "notice_version")]
    pub notice_version_id: Option<String>,
    #[serde(default, alias = "locale")]
    pub notice_language: Option<String>,
    #[serde(default)]
    pub notice_sha256: Option<String>,
    #[serde(default = "default_granted_decision", alias = "action_type")]
    pub decision: String, // "granted" | "refused" (normalises "grant" -> "granted", "refusal" -> "refused")
    #[serde(default, deserialize_with = "deserialize_purposes")]
    pub purposes: Vec<ConsentPurposeGrant>,
    #[serde(default = "default_spoken_mode")]
    pub mode: String, // "spoken" | "tap" | "signed" (normalises "tapped" -> "tap")
    #[serde(default)]
    pub witness_present: bool,
    #[serde(default)]
    pub supersedes_client_id: Option<String>,
    #[serde(default)]
    pub recorded_at: Option<String>,
    #[serde(default)]
    pub device_id: Option<String>,
}

fn default_granted_decision() -> String {
    "granted".to_string()
}

fn default_spoken_mode() -> String {
    "spoken".to_string()
}

/// Normalise consent decision (`"grant"` | `"granted"` -> `"granted"`, `"refusal"` | `"refused"` -> `"refused"`).
pub fn normalise_consent_decision(raw: &str) -> Option<&'static str> {
    match raw.trim() {
        "granted" | "grant" => Some("granted"),
        "refused" | "refusal" => Some("refused"),
        _ => None,
    }
}

/// Normalise consent capture mode (`"tapped"` | `"tap"` -> `"tap"`, `"spoken"`, `"signed"`).
pub fn normalise_consent_mode(raw: &str) -> Option<&'static str> {
    match raw.trim() {
        "spoken" => Some("spoken"),
        "tap" | "tapped" => Some("tap"),
        "signed" => Some("signed"),
        _ => None,
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsentRecordRow {
    pub client_id: String,
    pub project_id: i64,
    pub client_death_id: Option<String>,
    pub client_draft_id: Option<String>,
    pub death_id: Option<i64>,
    pub notice_version_id: String,
    pub notice_language: String,
    pub notice_sha256: String,
    pub decision: String, // "granted" | "refused"
    pub purposes: Vec<ConsentPurposeGrant>,
    pub mode: String, // "spoken" | "tap" | "signed"
    pub witness_present: bool,
    pub supersedes_client_id: Option<String>,
    pub all_required_granted: bool,
    pub sms_whatsapp_granted: bool,
    pub research_sharing_granted: bool,
    pub actor_user_id: Option<i64>,
    pub actor_member_id: String,
    pub acting_role: String,
    pub recorded_by: String,
    pub recorded_at: String,
    pub device_id: String,
}

impl ConsentRecordRow {
    pub fn purpose_granted(&self, code: &str) -> bool {
        self.purposes
            .iter()
            .find(|p| p.code == code)
            .map(|p| p.granted)
            .unwrap_or(false)
    }
}

/// Sandbox-only default consent configuration for `project_id == 1` (`PHC-STANDALONE`).
/// Never returned for provisioned projects (`project_id != 1` or `mode == "provisioned"`).
pub fn default_project_consent_config(project_id: i64) -> ProjectConsentConfig {
    let now = Utc::now().to_rfc3339();
    let en_body = concat!(
        "We are sorry for your loss. Before we write down your name, phone number or address, ",
        "please read or listen to how this information is used under the Digital Personal Data ",
        "Protection Act, 2023.\n\n",
        "**Why we ask for your details:**\n",
        "1. To record the death and conduct the Verbal Autopsy interview.\n",
        "2. To contact you if a health worker needs to schedule or follow up on the visit.\n",
        "3. For trained physicians to assign a cause of death (without seeing your name or phone).\n",
        "4. For anonymised public-health and government mortality statistics.\n\n",
        "**Your rights:** You may refuse to share your contact details (the death record and ",
        "interview can still proceed without them), and you may withdraw your consent or ask for ",
        "your contact details to be erased at any time."
    )
    .to_string();
    let hi_body = concat!(
        "आपके दुःख में हम सहभागी हैं। आपका नाम, फ़ोन नंबर या पता लिखने से पहले कृपया जान लें कि ",
        "डिजिटल व्यक्तिगत डेटा संरक्षण अधिनियम (DPDP Act, 2023) के अंतर्गत इस जानकारी का उपयोग कैसे किया जाएगा।\n\n",
        "आप अपनी संपर्क जानकारी देने से मना कर सकते हैं और किसी भी समय अपनी सहमति वापस ले सकते हैं।"
    )
    .to_string();

    let en_sha = sha256_hex(en_body.as_bytes());
    let hi_sha = sha256_hex(hi_body.as_bytes());

    ProjectConsentConfig {
        project_id,
        consent_required: true,
        min_version: 1,
        min_notice_version: "0.1".to_string(),
        notices: vec![
            ConsentNoticeLocale {
                notice_version_id: DEFAULT_NOTICE_VERSION_ID_EN.to_string(),
                version: 1,
                notice_version: "0.1".to_string(),
                locale: "en".to_string(),
                title: "Information and Consent for Recording a Death and Verbal Autopsy Interview"
                    .to_string(),
                body_markdown: en_body,
                text_sha256: en_sha,
                updated_at: now.clone(),
            },
            ConsentNoticeLocale {
                notice_version_id: DEFAULT_NOTICE_VERSION_ID_HI.to_string(),
                version: 1,
                notice_version: "0.1".to_string(),
                locale: "hi".to_string(),
                title: "मृत्यु पंजीकरण और मौखिक शव-परीक्षा (Verbal Autopsy) हेतु सूचना एवं सहमति".to_string(),
                body_markdown: hi_body,
                text_sha256: hi_sha,
                updated_at: now,
            },
        ],
        purposes: vec![
            ConsentPurposeSpec {
                code: "record_and_interview".to_string(),
                label_key: "consent.purpose.record_and_interview".to_string(),
                default_label: "Record the death and conduct the verbal autopsy interview".to_string(),
                required: true,
            },
            ConsentPurposeSpec {
                code: "contact_followup".to_string(),
                label_key: "consent.purpose.contact_followup".to_string(),
                default_label: "Contact me by phone or visit for interview scheduling and follow-up"
                    .to_string(),
                required: true,
            },
            ConsentPurposeSpec {
                code: "cause_of_death_coding".to_string(),
                label_key: "consent.purpose.cause_of_death_coding".to_string(),
                default_label: "Assign cause of death (physicians see clinical answers only, not my contact details)"
                    .to_string(),
                required: true,
            },
            ConsentPurposeSpec {
                code: "statistical_reports".to_string(),
                label_key: "consent.purpose.statistical_reports".to_string(),
                default_label: "Include de-identified data in public-health and government mortality reports"
                    .to_string(),
                required: true,
            },
            ConsentPurposeSpec {
                code: "sms_whatsapp_messages".to_string(),
                label_key: "consent.purpose.sms_whatsapp_messages".to_string(),
                default_label: "Optional: Send appointment or follow-up messages by SMS / WhatsApp"
                    .to_string(),
                required: false,
            },
            ConsentPurposeSpec {
                code: "research_sharing".to_string(),
                label_key: "consent.purpose.research_sharing".to_string(),
                default_label: "Optional: Share de-identified clinical data in approved health research repositories"
                    .to_string(),
                required: false,
            },
        ],
        allowed_modes: vec![
            "spoken".to_string(),
            "tap".to_string(),
            "signed".to_string(),
        ],
        witness_allowed: true,
        witness_required_for_modes: Vec::new(),
        refusal_behaviour: ConsentRefusalBehaviour::default(),
        project_contacts: ConsentContacts {
            deletion_email: "privacy-support@digitva.org".to_string(),
            deletion_phone: "+91-11-26588500".to_string(),
            mentor_institution: "Regional Medical Institute / State Nodal Unit".to_string(),
            central_team: "DigitVA Mortality Surveillance Central Team".to_string(),
            dpo: "Data Protection Officer (dpo@digitva.org)".to_string(),
        },
        district_contacts: BTreeMap::new(),
    }
}

/// Parse a Contract 5.2 consent config JSON object (or `ProjectConsentConfig` JSON) into `ProjectConsentConfig`,
/// verifying `text_sha256` over UTF-8 notice text and checking `refusal_behaviour`.
pub fn parse_contract_consent_config(
    project_id: i64,
    val: &Value,
) -> Result<ProjectConsentConfig, String> {
    if let Some(obj) = val.as_object() {
        if let Some(rb) = obj.get("refusal_behaviour").and_then(Value::as_str) {
            if rb != "interview_without_informant_data" {
                return Err(format!(
                    "Unsupported consent refusal_behaviour '{rb}'; consent settings need an app update."
                ));
            }
        }
        if let Some(versions_arr) = obj.get("notice_versions").and_then(Value::as_array) {
            let consent_required = obj
                .get("consent_required")
                .and_then(Value::as_bool)
                .unwrap_or(true);
            let now = Utc::now().to_rfc3339();
            let mut notices = Vec::new();
            let mut purposes_map: BTreeMap<String, ConsentPurposeSpec> = BTreeMap::new();
            let mut allowed_modes: Vec<String> = Vec::new();
            let mut witness_allowed = true;
            let mut covered_fields: Vec<String> = Vec::new();
            let mut min_version: Option<i64> = None;

            for nv in versions_arr {
                let nv_obj = nv
                    .as_object()
                    .ok_or_else(|| "notice_versions entry must be an object.".to_string())?;
                let notice_version_id = nv_obj
                    .get("notice_version_id")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "notice_version_id is required.".to_string())?
                    .to_string();
                let version = nv_obj
                    .get("version")
                    .and_then(Value::as_i64)
                    .ok_or_else(|| "notice version must be an integer.".to_string())?;
                let language = nv_obj
                    .get("language")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "notice language is required.".to_string())?
                    .to_string();
                let text = nv_obj
                    .get("text")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "notice text is required.".to_string())?
                    .to_string();
                let text_sha256 = nv_obj
                    .get("text_sha256")
                    .and_then(Value::as_str)
                    .ok_or_else(|| "notice text_sha256 is required.".to_string())?
                    .to_string();

                let computed_sha = sha256_hex(text.as_bytes());
                if !computed_sha.eq_ignore_ascii_case(&text_sha256) {
                    return Err(format!(
                        "Consent notice_version_id '{notice_version_id}' text_sha256 mismatch."
                    ));
                }

                min_version = Some(match min_version {
                    Some(cur) => cur.min(version),
                    None => version,
                });

                if let Some(purp_arr) = nv_obj.get("purposes").and_then(Value::as_array) {
                    for p in purp_arr {
                        if let Some(p_obj) = p.as_object() {
                            let code = p_obj
                                .get("code")
                                .and_then(Value::as_str)
                                .unwrap_or("")
                                .to_string();
                            let label = p_obj
                                .get("label")
                                .or_else(|| p_obj.get("default_label"))
                                .and_then(Value::as_str)
                                .unwrap_or(&code)
                                .to_string();
                            let required = p_obj
                                .get("required")
                                .and_then(Value::as_bool)
                                .unwrap_or(false);
                            if !code.is_empty() {
                                purposes_map.insert(
                                    code.clone(),
                                    ConsentPurposeSpec {
                                        label_key: format!("consent.purpose.{code}"),
                                        code,
                                        default_label: label,
                                        required,
                                    },
                                );
                            }
                        }
                    }
                }

                if let Some(modes_arr) = nv_obj.get("allowed_modes").and_then(Value::as_array) {
                    for m in modes_arr.iter().filter_map(Value::as_str) {
                        if let Some(norm) = normalise_consent_mode(m) {
                            if !allowed_modes.iter().any(|existing| existing == norm) {
                                allowed_modes.push(norm.to_string());
                            }
                        }
                    }
                }

                if let Some(wa) = nv_obj.get("witness_allowed").and_then(Value::as_bool) {
                    witness_allowed = wa;
                }

                if let Some(cf_arr) = nv_obj.get("covered_fields").and_then(Value::as_array) {
                    for cf in cf_arr.iter().filter_map(Value::as_str) {
                        if !covered_fields.iter().any(|existing| existing == cf) {
                            covered_fields.push(cf.to_string());
                        }
                    }
                }

                notices.push(ConsentNoticeLocale {
                    notice_version_id,
                    version,
                    notice_version: version.to_string(),
                    locale: language,
                    title: "Respondent Consent Notice".to_string(),
                    body_markdown: text,
                    text_sha256: computed_sha,
                    updated_at: now.clone(),
                });
            }

            if allowed_modes.is_empty() {
                allowed_modes = vec![
                    "spoken".to_string(),
                    "tap".to_string(),
                    "signed".to_string(),
                ];
            }

            let min_ver = min_version.unwrap_or(1);
            let mut rb = ConsentRefusalBehaviour::default();
            if !covered_fields.is_empty() {
                rb.omit_fields = covered_fields;
            }

            return Ok(ProjectConsentConfig {
                project_id,
                consent_required,
                min_version: min_ver,
                min_notice_version: min_ver.to_string(),
                notices,
                purposes: purposes_map.into_values().collect(),
                allowed_modes,
                witness_allowed,
                witness_required_for_modes: Vec::new(),
                refusal_behaviour: rb,
                project_contacts: ConsentContacts::default(),
                district_contacts: BTreeMap::new(),
            });
        }
    }

    serde_json::from_value::<ProjectConsentConfig>(val.clone())
        .map_err(|e| format!("Invalid ProjectConsentConfig JSON: {e}"))
}

/// Load the project consent configuration.
///
/// Contract 5.6 rule:
/// - `default_project_consent_config(1)` is ONLY returned when `project_id == 1` AND the station
///   is in `"standalone"` sandbox mode.
/// - When `project_id != 1` or the station is in `"provisioned"` mode and no consent config has been
///   imported for `project_id`, returns `Err(rusqlite::Error::QueryReturnedNoRows)`.
pub fn get_project_consent_config(
    conn: &Connection,
    project_id: i64,
) -> rusqlite::Result<ProjectConsentConfig> {
    let raw: Option<String> = conn
        .query_row(
            "SELECT config_json FROM consent_configs WHERE project_id = ?1",
            params![project_id],
            |row| row.get(0),
        )
        .optional()?;

    if let Some(json_str) = raw {
        if let Ok(val) = serde_json::from_str::<Value>(&json_str) {
            if let Ok(cfg) = parse_contract_consent_config(project_id, &val) {
                return Ok(cfg);
            }
        }
    }

    let station_mode: String = conn
        .query_row(
            "SELECT mode FROM loc_station_config WHERE id = 1",
            [],
            |r| r.get(0),
        )
        .unwrap_or_else(|_| "standalone".to_string());

    if project_id == 1 && station_mode == "standalone" {
        Ok(default_project_consent_config(1))
    } else {
        Err(rusqlite::Error::QueryReturnedNoRows)
    }
}

pub fn upsert_project_consent_config(
    conn: &Connection,
    config: &ProjectConsentConfig,
) -> rusqlite::Result<()> {
    let json_str = serde_json::to_string(config).unwrap_or_else(|_| "{}".to_string());
    let now = Utc::now().to_rfc3339();
    conn.execute(
        "INSERT INTO consent_configs (
            project_id, consent_required, min_notice_version, config_json, synced_at
         ) VALUES (?1, ?2, ?3, ?4, ?5)
         ON CONFLICT(project_id) DO UPDATE SET
            consent_required = excluded.consent_required,
            min_notice_version = excluded.min_notice_version,
            config_json = excluded.config_json,
            synced_at = excluded.synced_at",
        params![
            config.project_id,
            i32::from(config.consent_required),
            config.min_notice_version,
            json_str,
            now
        ],
    )?;
    Ok(())
}

fn parse_version_int(s: &str) -> Option<i64> {
    s.trim().parse::<i64>().ok()
}

pub fn append_consent_record(
    conn: &Connection,
    project_id: i64,
    client_death_id: Option<&str>,
    death_id: Option<i64>,
    input: &ConsentEnvelopeInput,
    recorded_by: &str,
    default_device_id: &str,
) -> Result<ConsentRecordRow, String> {
    let cfg = get_project_consent_config(conn, project_id)
        .map_err(|_| "Consent configuration has not been loaded for this project.".to_string())?;

    let client_id = input
        .client_id
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| Uuid::new_v4().to_string());

    let decision = normalise_consent_decision(&input.decision)
        .ok_or_else(|| "Invalid consent decision; must be 'granted' or 'refused'.".to_string())?
        .to_string();

    let mode = normalise_consent_mode(&input.mode)
        .ok_or_else(|| {
            format!(
                "Invalid consent mode '{}'; must be 'spoken', 'tap', or 'signed'.",
                input.mode
            )
        })?
        .to_string();

    if !cfg.allowed_modes.is_empty()
        && !cfg
            .allowed_modes
            .iter()
            .any(|m| normalise_consent_mode(m) == Some(mode.as_str()))
    {
        return Err(format!(
            "Consent capture mode '{mode}' is not allowed for this project."
        ));
    }

    if input.witness_present && !cfg.witness_allowed {
        return Err("witness_present cannot be true when witness_allowed is false.".to_string());
    }

    let notice_language = input
        .notice_language
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "en".to_string());

    let raw_nv = input
        .notice_version_id
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| cfg.min_notice_version.clone());

    // Match notice in cfg.notices by notice_version_id or notice_version + language
    let matched_notice = cfg
        .notices
        .iter()
        .find(|n| n.notice_version_id == raw_nv || (n.notice_version == raw_nv && n.locale == notice_language))
        .or_else(|| cfg.notices.iter().find(|n| n.notice_version == raw_nv))
        .or_else(|| cfg.notices.iter().find(|n| n.locale == notice_language))
        .or_else(|| cfg.notices.first());

    // Integer version comparison (Contract 5.2 / 5.6)
    if let Some(req_v) = parse_version_int(&raw_nv) {
        if req_v < cfg.min_version {
            return Err(format!(
                "Consent notice version {} is older than project minimum {}; please re-capture consent.",
                req_v, cfg.min_version
            ));
        }
    } else if raw_nv < cfg.min_notice_version && Uuid::parse_str(&raw_nv).is_err() {
        return Err(format!(
            "Consent notice version '{}' is older than project minimum '{}'; please re-capture consent.",
            raw_nv, cfg.min_notice_version
        ));
    }

    let notice_version_id = if Uuid::parse_str(&raw_nv).is_ok() {
        raw_nv.clone()
    } else if let Some(n) = matched_notice {
        if Uuid::parse_str(&n.notice_version_id).is_ok() {
            n.notice_version_id.clone()
        } else {
            DEFAULT_NOTICE_VERSION_ID_EN.to_string()
        }
    } else {
        DEFAULT_NOTICE_VERSION_ID_EN.to_string()
    };

    let expected_sha = matched_notice
        .map(|n| {
            if !n.text_sha256.is_empty() {
                n.text_sha256.clone()
            } else {
                sha256_hex(n.body_markdown.as_bytes())
            }
        })
        .unwrap_or_else(|| sha256_hex(raw_nv.as_bytes()));

    let notice_sha256 = match input.notice_sha256.as_deref().map(str::trim) {
        Some(provided) if !provided.is_empty() => {
            if provided.len() != 64 || !provided.bytes().all(|b| b.is_ascii_hexdigit()) {
                return Err("Consent notice_sha256 must be 64 hex characters.".to_string());
            }
            if matched_notice.is_some() && !provided.eq_ignore_ascii_case(&expected_sha) {
                return Err("Consent notice_sha256 does not match the served notice text.".to_string());
            }
            provided.to_ascii_lowercase()
        }
        _ => expected_sha,
    };

    // Build canonical sorted purposes list
    let mut purposes_map: BTreeMap<String, bool> = BTreeMap::new();
    for p in &cfg.purposes {
        purposes_map.insert(p.code.clone(), false);
    }
    for pg in &input.purposes {
        purposes_map.insert(pg.code.clone(), pg.granted);
    }
    let purposes: Vec<ConsentPurposeGrant> = purposes_map
        .iter()
        .map(|(code, &granted)| ConsentPurposeGrant {
            code: code.clone(),
            granted,
        })
        .collect();

    let all_required_granted = if decision == "granted" {
        cfg.purposes
            .iter()
            .filter(|p| p.required)
            .all(|p| purposes_map.get(&p.code).copied().unwrap_or(false))
    } else {
        false
    };

    if decision == "granted" && !all_required_granted {
        return Err(
            "All required respondent consent purposes must be granted to store informant personal data, or record a refusal instead."
                .to_string(),
        );
    }

    let sms_whatsapp_granted = all_required_granted
        && purposes_map
            .get("sms_whatsapp_messages")
            .copied()
            .unwrap_or(false);
    let research_sharing_granted = all_required_granted
        && purposes_map
            .get("research_sharing")
            .copied()
            .unwrap_or(false);

    let recorded_at = input
        .recorded_at
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| Utc::now().to_rfc3339());
    let device_id = input
        .device_id
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| default_device_id.to_string());

    let active_actor = crate::roster::get_active_actor(conn);
    let purposes_json = serde_json::to_string(&purposes).unwrap_or_else(|_| "[]".to_string());

    conn.execute(
        "INSERT OR REPLACE INTO consent_records (
            consent_id, project_id, client_death_id, client_draft_id, death_id,
            action_type, notice_version_id, notice_version, locale, notice_sha256,
            mode, witness_present, supersedes_client_id, purposes_json,
            all_required_granted, sms_whatsapp_granted, research_sharing_granted,
            actor_user_id, actor_member_id, acting_role,
            recorded_by, recorded_at, device_id, sync_state
        ) VALUES (
            ?1, ?2, ?3, ?4, ?5,
            ?6, ?7, ?8, ?9, ?10,
            ?11, ?12, ?13, ?14,
            ?15, ?16, ?17,
            ?18, ?19, ?20,
            ?21, ?22, ?23, 'pending'
        )",
        params![
            client_id,
            project_id,
            client_death_id,
            input.client_draft_id,
            death_id,
            decision,
            notice_version_id,
            raw_nv,
            notice_language,
            notice_sha256,
            mode,
            i32::from(input.witness_present),
            input.supersedes_client_id,
            purposes_json,
            i32::from(all_required_granted),
            i32::from(sms_whatsapp_granted),
            i32::from(research_sharing_granted),
            active_actor.user_id,
            active_actor.member_id,
            active_actor.acting_role,
            recorded_by,
            recorded_at,
            device_id,
        ],
    )
    .map_err(|e| format!("Failed to store consent record: {e}"))?;

    Ok(ConsentRecordRow {
        client_id,
        project_id,
        client_death_id: client_death_id.map(ToString::to_string),
        client_draft_id: input.client_draft_id.clone(),
        death_id,
        notice_version_id,
        notice_language,
        notice_sha256,
        decision,
        purposes,
        mode,
        witness_present: input.witness_present,
        supersedes_client_id: input.supersedes_client_id.clone(),
        all_required_granted,
        sms_whatsapp_granted,
        research_sharing_granted,
        actor_user_id: active_actor.user_id,
        actor_member_id: active_actor.member_id,
        acting_role: active_actor.acting_role,
        recorded_by: recorded_by.to_string(),
        recorded_at,
        device_id,
    })
}

pub fn parse_stored_purposes(purposes_str: &str) -> Vec<ConsentPurposeGrant> {
    if let Ok(mut vec) = serde_json::from_str::<Vec<ConsentPurposeGrant>>(purposes_str) {
        vec.sort_by(|a, b| a.code.cmp(&b.code));
        return vec;
    }
    if let Ok(map) = serde_json::from_str::<BTreeMap<String, bool>>(purposes_str) {
        return map
            .into_iter()
            .map(|(code, granted)| ConsentPurposeGrant { code, granted })
            .collect();
    }
    Vec::new()
}

pub fn get_latest_consent_for_case(
    conn: &Connection,
    project_id: i64,
    client_death_id: Option<&str>,
    death_id: Option<i64>,
) -> rusqlite::Result<Option<ConsentRecordRow>> {
    let mut stmt = conn.prepare(
        "SELECT consent_id, project_id, client_death_id, client_draft_id, death_id,
                action_type, notice_version_id, locale, notice_sha256, mode,
                witness_present, supersedes_client_id, purposes_json,
                all_required_granted, sms_whatsapp_granted, research_sharing_granted,
                actor_user_id, actor_member_id, acting_role,
                recorded_by, recorded_at, device_id
         FROM consent_records
         WHERE project_id = ?1
           AND ((?2 IS NOT NULL AND client_death_id = ?2) OR (?3 IS NOT NULL AND death_id = ?3))
         ORDER BY recorded_at DESC, rowid DESC
         LIMIT 1",
    )?;

    stmt.query_row(params![project_id, client_death_id, death_id], |row| {
        let purposes_str: String = row.get(12)?;
        let purposes = parse_stored_purposes(&purposes_str);
        let raw_decision: String = row.get(5)?;
        let decision = normalise_consent_decision(&raw_decision)
            .unwrap_or("refused")
            .to_string();
        let raw_mode: String = row.get(9)?;
        let mode = normalise_consent_mode(&raw_mode)
            .unwrap_or("spoken")
            .to_string();
        Ok(ConsentRecordRow {
            client_id: row.get(0)?,
            project_id: row.get(1)?,
            client_death_id: row.get(2)?,
            client_draft_id: row.get(3)?,
            death_id: row.get(4)?,
            decision,
            notice_version_id: row.get(6)?,
            notice_language: row.get(7)?,
            notice_sha256: row.get(8)?,
            mode,
            witness_present: row.get::<_, i32>(10)? == 1,
            supersedes_client_id: row.get(11)?,
            purposes,
            all_required_granted: row.get::<_, i32>(13)? == 1,
            sms_whatsapp_granted: row.get::<_, i32>(14)? == 1,
            research_sharing_granted: row.get::<_, i32>(15)? == 1,
            actor_user_id: row.get(16)?,
            actor_member_id: row.get(17)?,
            acting_role: row.get(18)?,
            recorded_by: row.get(19)?,
            recorded_at: row.get(20)?,
            device_id: row.get(21)?,
        })
    })
    .optional()
}

pub fn has_non_empty_informant_pii(fields: &[Option<&str>]) -> bool {
    fields
        .iter()
        .any(|f| f.map(|s| !s.trim().is_empty()).unwrap_or(false))
}

/// Hard gate (`digitva-athy`, Contract 5.4–5.6): Saving informant personal data (`informant_name`,
/// `informant_phone`, `informant_phone_2`, `address*`, `location`) MUST fail unless a valid
/// granted `consent_records` row exists for this case, and a consent configuration is loaded for the project.
pub fn assert_informant_consent_before_write(
    conn: &Connection,
    project_id: i64,
    client_death_id: Option<&str>,
    death_id: Option<i64>,
    informant_fields: &[Option<&str>],
) -> Result<String, String> {
    let cfg = get_project_consent_config(conn, project_id)
        .map_err(|_| "Consent configuration has not been loaded for this project.".to_string())?;

    let latest = get_latest_consent_for_case(conn, project_id, client_death_id, death_id)
        .map_err(|e| format!("Failed to read case consent record: {e}"))?;

    let status = match &latest {
        Some(r) if r.decision == "refused" => "refused",
        Some(r) if r.decision == "granted" && r.all_required_granted => "granted",
        _ => {
            if cfg.consent_required {
                "pending"
            } else {
                "not_required"
            }
        }
    };

    if !cfg.consent_required {
        return Ok(status.to_string());
    }

    if !has_non_empty_informant_pii(informant_fields) {
        return Ok(status.to_string());
    }

    let Some(record) = latest else {
        return Err(
            "Respondent consent is required before saving informant name, phone, or address."
                .to_string(),
        );
    };

    if record.decision != "granted" || !record.all_required_granted {
        return Err(
            "Respondent refused or did not grant required consent; clear informant personal data before saving."
                .to_string(),
        );
    }

    Ok("granted".to_string())
}

/// Internal helper used when applying server `purge` lists (`apply_purge_list`):
/// scrubs informant personal data (`informant_name`, `informant_phone`, `informant_phone_2`,
/// `address*`, `location`, `Id10007`) across local tables for `death_id`.
pub(crate) fn purge_informant_pii_for_death_id(
    conn: &Connection,
    death_id: i64,
) -> Result<(), String> {
    let now = Utc::now().to_rfc3339();
    conn.execute(
        "UPDATE loc_death_register
         SET informant_name = NULL,
             informant_phone = NULL,
             informant_phone_2 = NULL,
             informant_relation = NULL,
             address = NULL,
             address_house_street = NULL,
             address_village_ward = NULL,
             address_landmark = NULL,
             location = NULL,
             updated_at = ?1
         WHERE death_id = ?2",
        params![now, death_id],
    )
    .map_err(|e| format!("Failed to purge informant PII on death register: {e}"))?;

    scrub_json_keys_in_table(conn, "loc_va_drafts", "draft_id", "answers_json", death_id)?;
    scrub_json_keys_in_table(
        conn,
        "loc_va_submissions",
        "va_sid",
        "payload_json",
        death_id,
    )?;

    Ok(())
}

fn scrub_json_keys_in_table(
    conn: &Connection,
    table: &str,
    pk_col: &str,
    json_col: &str,
    death_id: i64,
) -> Result<(), String> {
    let sql = format!("SELECT {pk_col}, {json_col} FROM {table} WHERE death_id = ?1");
    let mut stmt = conn.prepare(&sql).map_err(|e| e.to_string())?;
    let rows: Vec<(String, String)> = stmt
        .query_map(params![death_id], |r| Ok((r.get(0)?, r.get(1)?)))
        .map_err(|e| e.to_string())?
        .filter_map(Result::ok)
        .collect();

    let keys_to_scrub = [
        "Id10007",
        "informant_name",
        "informant_phone",
        "informant_phone_2",
        "address",
        "address_house_street",
        "address_village_ward",
        "address_landmark",
        "location",
    ];

    for (pk, raw_json) in rows {
        if let Ok(mut val) = serde_json::from_str::<serde_json::Value>(&raw_json) {
            if let Some(obj) = val.as_object_mut() {
                let mut modified = false;
                for k in keys_to_scrub {
                    if obj.remove(k).is_some() {
                        modified = true;
                    }
                }
                if modified {
                    let updated_str =
                        serde_json::to_string(&val).unwrap_or_else(|_| "{}".to_string());
                    let update_sql =
                        format!("UPDATE {table} SET {json_col} = ?1 WHERE {pk_col} = ?2");
                    conn.execute(&update_sql, params![updated_str, pk])
                        .map_err(|e| e.to_string())?;
                }
            }
        }
    }
    Ok(())
}
