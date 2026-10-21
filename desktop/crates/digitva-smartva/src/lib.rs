//! DigitVA wrapper around the 100% pure-Rust `smartva-rust` engine (`vendor/smartva-analyze/rust`).
//!
//! Enforces **Rule 6**: SmartVA inputs are constructed exclusively from clinical and demographic
//! answers (`Id10004`..`Id10476`, `sid`) and must never receive names, phones, addresses,
//! Aadhaar, ABHA, or death registration numbers.

pub use smartva_rust::*;

use serde_json::{Map, Value};

const FORBIDDEN_SMARTVA_PII_KEYS: &[&str] = &[
    "name",
    "name2",
    "surname",
    "surname2",
    "deceased_name",
    "informant_name",
    "respondent_name",
    "phone",
    "informant_phone",
    "mobile",
    "address",
    "aadhaar",
    "aadhaar_last3",
    "abha",
    "national_id",
    "identifiers",
    "crs_number",
    "mccd_number",
    "certificate_number",
    "id10007",
    "id10008",
    "id10009",
    "id10010",
    "id10017",
    "id10018",
    "id10061",
    "id10062",
];

/// Verify that a JSON input payload (object or array of objects) contains only clinical/demographic
/// fields and no PII or registration identifiers (Rule 6).
pub fn assert_no_pii_in_smartva_json(json_str: &str) -> Result<(), SmartVaError> {
    let parsed: Value = serde_json::from_str(json_str)
        .map_err(|e| SmartVaError::ExecutionError(format!("Invalid SmartVA JSON: {e}")))?;
    check_value(&parsed)?;
    Ok(())
}

fn is_forbidden_smartva_key(key: &str) -> bool {
    let lower = key.trim().to_ascii_lowercase();
    FORBIDDEN_SMARTVA_PII_KEYS
        .iter()
        .any(|&f| lower == f || lower.ends_with(&format!("-{f}")))
}

/// Strip personal / registration identifier fields from a raw ODK map before constructing
/// a clinical-only SmartVA input (Rule 6).
pub fn strip_pii_from_smartva_map(map: &mut Map<String, Value>) {
    map.retain(|k, _| !is_forbidden_smartva_key(k));
}

fn check_value(v: &Value) -> Result<(), SmartVaError> {
    match v {
        Value::Object(map) => {
            for (k, val) in map {
                if is_forbidden_smartva_key(k) {
                    return Err(SmartVaError::ExecutionError(format!(
                        "Rule 6 violation: SmartVA input must not contain PII or identifier key '{k}'"
                    )));
                }
                check_value(val)?;
            }
            Ok(())
        }
        Value::Array(items) => {
            for item in items {
                check_value(item)?;
            }
            Ok(())
        }
        _ => Ok(()),
    }
}

/// Score clinical-only JSON input through the pure-Rust `SmartVaEngine` after verifying Rule 6.
pub fn score_clinical_json(
    engine: &SmartVaEngine,
    input_json: &str,
    options: &SmartVaRunOptions,
) -> Result<String, SmartVaError> {
    assert_no_pii_in_smartva_json(input_json)?;
    engine.score_json(input_json, options)
}

/// Score clinical-only JSON input and return the structured [`SmartVaCliDirectoryResult`].
pub fn score_clinical_json_result(
    engine: &SmartVaEngine,
    input_json: &str,
    options: &SmartVaRunOptions,
) -> Result<SmartVaCliDirectoryResult, SmartVaError> {
    assert_no_pii_in_smartva_json(input_json)?;
    engine.score_json_result(input_json, options).map(|(r, _)| r)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rule6_smartva_boundary_blocks_pii_and_scores_clinical_json() {
        let engine = SmartVaEngine::new();
        let bad = r#"[{"sid": "va-1", "Id10019": "male", "informant_phone": "9876543210"}]"#;
        let err = score_clinical_json(&engine, bad, &SmartVaRunOptions::default()).unwrap_err();
        assert!(err.to_string().contains("Rule 6 violation"));

        let bad_odk_name = r#"[{"sid": "va-1", "root-Id10017": "Ramesh Kumar"}]"#;
        let err2 =
            score_clinical_json(&engine, bad_odk_name, &SmartVaRunOptions::default()).unwrap_err();
        assert!(err2.to_string().contains("Rule 6 violation"));
    }
}
