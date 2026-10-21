use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub const DEFAULT_INSTRUMENT_CODE: &str = "WHO_2022_VA";
pub const DEFAULT_INSTRUMENT_VERSION: &str = "2022.1.5-offline";

pub fn default_who_2022_va_definition() -> Value {
    json!({
        "instrument_code": DEFAULT_INSTRUMENT_CODE,
        "version": DEFAULT_INSTRUMENT_VERSION,
        "title": "WHO 2022 Verbal Autopsy Instrument",
        "default_locale": "en",
        "sections": [
            {
                "code": "respondent",
                "title": "Respondent & Background",
                "questions": [
                    { "id": "Id10007", "label": "Name of respondent", "type": "text", "required": false },
                    { "id": "Id10008", "label": "Relationship of respondent to deceased", "type": "select_one", "options": ["parent", "child", "spouse", "sibling", "other_relative", "health_worker", "other"] },
                    { "id": "Id10009", "label": "Did the respondent live with the deceased in the period leading to death?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10010", "label": "Interviewer ID / Name", "type": "text", "required": false },
                    { "id": "Id10011", "label": "Time at start of interview", "type": "text", "required": false },
                    { "id": "Id10012", "label": "Date of interview", "type": "date", "required": true },
                    { "id": "Id10013", "label": "Did the respondent give consent?", "type": "select_one", "options": ["yes", "no"], "required": true }
                ]
            },
            {
                "code": "deceased",
                "title": "Information on the Deceased",
                "questions": [
                    { "id": "Id10017", "label": "First or given name(s) of deceased", "type": "text", "required": true },
                    { "id": "Id10018", "label": "Family name / Surname of deceased", "type": "text", "required": false },
                    { "id": "Id10019", "label": "Sex of the deceased", "type": "select_one", "options": ["female", "male", "ambiguous", "dk", "ref"], "required": true },
                    { "id": "Id10020", "label": "Is the date of birth known?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10021", "label": "Date of birth of deceased", "type": "date", "required": false },
                    { "id": "Id10022", "label": "Is the date of death known?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10023", "label": "Date of death of deceased", "type": "date", "required": true },
                    { "id": "Id10051", "label": "Age in completed years (if adult/child)", "type": "integer", "required": false },
                    { "id": "Id10058", "label": "Place of death", "type": "select_one", "options": ["hospital", "other_health_facility", "home", "on_route_to_hospital_or_facility", "other", "dk", "ref"] },
                    { "id": "Id10059", "label": "Marital status of the deceased", "type": "select_one", "options": ["never_married", "married", "widowed", "divorced", "separated", "dk", "ref"] },
                    { "id": "Id10070", "label": "Death registration number (if available)", "type": "text", "required": false },
                    { "id": "Id10073", "label": "National ID (Aadhaar / VID — reduced to last 3 digits at capture)", "type": "text", "required": false }
                ]
            },
            {
                "code": "injury",
                "title": "History of Injury / Accident",
                "questions": [
                    { "id": "Id10077", "label": "Did the deceased suffer from any injury or accident that led to death?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10079", "label": "Was it a road traffic accident?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10082", "label": "Did the deceased die from a fall?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10083", "label": "Did the deceased die from drowning?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10085", "label": "Did the deceased suffer a bite or sting by venomous animal?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10086", "label": "Did the deceased suffer burns?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10089", "label": "Was the injury self-inflicted?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] }
                ]
            },
            {
                "code": "history",
                "title": "Medical History & General Symptoms",
                "questions": [
                    { "id": "Id10104", "label": "Ever diagnosed with tuberculosis?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10105", "label": "Ever diagnosed with HIV/AIDS?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10106", "label": "Ever diagnosed with malaria?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10109", "label": "Ever diagnosed with diabetes?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10110", "label": "Ever diagnosed with hypertension (high blood pressure)?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10111", "label": "Ever diagnosed with heart disease?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10112", "label": "Ever diagnosed with chronic obstructive pulmonary disease (COPD) / asthma?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10113", "label": "Ever diagnosed with cancer?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10115", "label": "Ever diagnosed with stroke?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10120", "label": "For how many days was the deceased ill before death?", "type": "integer", "required": false },
                    { "id": "Id10147", "label": "Did the deceased have a fever?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10148", "label": "Duration of fever (days)", "type": "integer", "required": false },
                    { "id": "Id10153", "label": "Did the deceased have a cough?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10154", "label": "Duration of cough (days)", "type": "integer", "required": false },
                    { "id": "Id10159", "label": "Did the deceased have fast or difficult breathing?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10166", "label": "Did the deceased have chest pain?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10181", "label": "Did the deceased have more frequent loose or liquid stools (diarrhoea)?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10188", "label": "Did the deceased vomit?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10208", "label": "Did the deceased have severe headache?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10209", "label": "Did the deceased have a stiff or painful neck?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10214", "label": "Did the deceased have convulsions?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10219", "label": "Was the deceased unconscious during the illness that led to death?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10223", "label": "Did the deceased have paralysis of one side of the body?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] }
                ]
            },
            {
                "code": "narrative",
                "title": "Open Narrative & Care Seeking",
                "questions": [
                    { "id": "Id10411", "label": "Did the deceased receive any treatment for the illness that led to death?", "type": "select_one", "options": ["yes", "no", "dk", "ref"] },
                    { "id": "Id10476", "label": "Open narrative (describe the illness and events leading to death)", "type": "textarea", "required": false }
                ]
            }
        ]
    })
}

pub fn default_who_2022_va_definition_sha256() -> String {
    let body = serde_json::to_string(&default_who_2022_va_definition()).unwrap_or_default();
    let mut hasher = Sha256::new();
    hasher.update(body.as_bytes());
    format!("{:x}", hasher.finalize())
}

pub fn default_form_options(project_id: &str) -> Value {
    let sha = default_who_2022_va_definition_sha256();
    json!({
        "project_id": project_id,
        "web_intake_mode": "both",
        "instrument_version": DEFAULT_INSTRUMENT_VERSION,
        "definition_sha256": sha,
        "enabled_extensions": ["social_autopsy", "narrative_qa"],
        "form_types": [
            { "instrument_code": DEFAULT_INSTRUMENT_CODE, "is_default": true }
        ],
        "narration_languages": [
            { "code": "en", "label": "English" },
            { "code": "hi", "label": "Hindi (हिन्दी)" }
        ],
        "available_locales": [
            { "code": "en", "label": "English", "under_review": false },
            { "code": "hi", "label": "Hindi (हिन्दी)", "under_review": false }
        ],
        "default_locale": "en",
        "translation_versions": {
            "en": 1,
            "hi": 1
        },
        "intake_note": "Offline PHC Verbal Autopsy Collection & Coding"
    })
}
