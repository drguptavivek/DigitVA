//! DigitVA wrapper around the 100% pure-Rust `smartva-rust` engine (`vendor/smartva-analyze/rust`).
//!
//! Enforces **Rule 6**: SmartVA inputs are constructed exclusively from clinical and demographic
//! answers (`Id10004`..`Id10476`, `sid`) and must never receive names, phones, addresses,
//! Aadhaar, ABHA, or death registration numbers.

pub use smartva_rust::*;

use serde_json::{Map, Value};

/// The 19-field `PII_FIELDS` floor from Contract Section 6.6 plus register personal fields.
const FORBIDDEN_SMARTVA_PII_KEYS: &[&str] = &[
    // 19 sealed payload fields (`PII_FIELDS` floor, Contract 6.6)
    "id10007",
    "id10010",
    "id10010a",
    "id10010b",
    "id10010c",
    "id10017",
    "id10018",
    "id10055",
    "id10057",
    "id10061",
    "id10062",
    "id10070",
    "id10071",
    "id10072",
    "id10073",
    "visit_address",
    "visit_remarks",
    "abha_number",
    "abha_address",
    // Register & legacy personal keys
    "name",
    "name2",
    "surname",
    "surname2",
    "deceased_name",
    "father_name",
    "mother_name",
    "informant_name",
    "respondent_name",
    "phone",
    "informant_phone",
    "informant_phone_2",
    "mobile",
    "address",
    "address_house_street",
    "address_village_ward",
    "address_landmark",
    "location",
    "aadhaar",
    "aadhaar_last3",
    "abha",
    "national_id",
    "identifiers",
    "crs_number",
    "mccd_number",
    "certificate_number",
    "crs_reg_no",
    "mccd_cert_no",
];

/// Verify that a JSON input payload (object or array of objects) contains only clinical/demographic
/// fields and no PII or registration identifiers (Rule 6 / Contract 6.6).
pub fn assert_no_pii_in_smartva_json(json_str: &str) -> Result<(), SmartVaError> {
    assert_no_pii_in_smartva_json_with_sealed(json_str, &[])
}

pub fn assert_no_pii_in_smartva_json_with_sealed(
    json_str: &str,
    extra_sealed_fields: &[String],
) -> Result<(), SmartVaError> {
    let parsed: Value = serde_json::from_str(json_str)
        .map_err(|e| SmartVaError::ExecutionError(format!("Invalid SmartVA JSON: {e}")))?;
    check_value(&parsed, extra_sealed_fields)?;
    Ok(())
}

fn is_forbidden_smartva_key(key: &str, extra_sealed_fields: &[String]) -> bool {
    let lower = key.trim().to_ascii_lowercase();
    if FORBIDDEN_SMARTVA_PII_KEYS
        .iter()
        .any(|&f| lower == f || lower.ends_with(&format!("-{f}")))
    {
        return true;
    }
    extra_sealed_fields.iter().any(|f| {
        let fl = f.trim().to_ascii_lowercase();
        !fl.is_empty() && (lower == fl || lower.ends_with(&format!("-{fl}")))
    })
}

/// Strip personal / registration identifier fields from a raw ODK map before constructing
/// a clinical-only SmartVA input (Rule 6 / Contract 6.6).
pub fn strip_pii_from_smartva_map(map: &mut Map<String, Value>) {
    strip_pii_from_smartva_map_with_sealed(map, &[]);
}

/// Strip the 19-field `PII_FIELDS` floor unioned with `extra_sealed_fields` (`projects[].sealed_field_ids`),
/// and normalise any integer-valued JSON float (`0.0`, `3.0`, `30.0`) to an integer number.
pub fn strip_pii_from_smartva_map_with_sealed(
    map: &mut Map<String, Value>,
    extra_sealed_fields: &[String],
) {
    map.retain(|k, _| !is_forbidden_smartva_key(k, extra_sealed_fields));
    for val in map.values_mut() {
        normalise_integer_floats(val);
    }
}

fn normalise_integer_floats(v: &mut Value) {
    match v {
        Value::Number(n) => {
            if n.as_i64().is_none() && n.as_u64().is_none() {
                if let Some(f) = n.as_f64() {
                    if f.is_finite()
                        && f.fract() == 0.0
                        && (-9_007_199_254_740_991.0..=9_007_199_254_740_991.0).contains(&f)
                    {
                        *v = Value::Number((f as i64).into());
                    }
                }
            }
        }
        Value::Array(arr) => {
            for item in arr {
                normalise_integer_floats(item);
            }
        }
        Value::Object(obj) => {
            for val in obj.values_mut() {
                normalise_integer_floats(val);
            }
        }
        _ => {}
    }
}

fn check_value(v: &Value, extra_sealed_fields: &[String]) -> Result<(), SmartVaError> {
    match v {
        Value::Object(map) => {
            for (k, val) in map {
                if is_forbidden_smartva_key(k, extra_sealed_fields) {
                    return Err(SmartVaError::ExecutionError(format!(
                        "Rule 6 violation: SmartVA input must not contain PII or identifier key '{k}'"
                    )));
                }
                check_value(val, extra_sealed_fields)?;
            }
            Ok(())
        }
        Value::Array(items) => {
            for item in items {
                check_value(item, extra_sealed_fields)?;
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
