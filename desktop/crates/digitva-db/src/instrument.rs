//! The composed WHO VA 2022 form definition, served per project exactly as the
//! central server serves it (`app/services/served_form_service.py`).
//!
//! The station embeds the server's `app/data/who-va-2022.composed.json` at build time (every
//! DigitVA module composed in, each module's sections and questions tagged `extensions`). A
//! project's definition is that file minus the items only its disabled modules contribute, with
//! top-level `extensions` = the sorted enabled tags, serialised as Python's
//! `json.dumps(ensure_ascii=False, separators=(",", ":"), sort_keys=True)`; for the same enabled
//! set the bytes, and so the SHA-256, equal the server's (pinned by
//! `tests/fixtures/served_definition_vectors.json`). Which modules and languages a project
//! offers is never decided here: it comes from the project's `form_options` in the signed
//! station config.

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap};
use std::sync::{Arc, Mutex, OnceLock};

/// The one instrument a composed definition exists for.
pub const INSTRUMENT_CODE: &str = "WHO_2022_VA";
/// The base locale: always offered, carries no translation strings (version 0).
pub const BASE_LOCALE: &str = "en";

const COMPOSED_JSON: &str = include_str!("../../../../app/data/who-va-2022.composed.json");

/// One project's slice of the composed definition, as served.
#[derive(Debug)]
pub struct ServedDefinition {
    pub body: Vec<u8>,
    pub sha256: String,
}

/// Why a definition request cannot be served.
#[derive(Debug, PartialEq, Eq)]
pub enum DefinitionError {
    /// A version this station binary does not carry.
    UnknownVersion,
    /// Extension names outside the composed file's tags.
    InvalidExtensions(Vec<String>),
}

fn composed() -> &'static Value {
    static COMPOSED: OnceLock<Value> = OnceLock::new();
    // The file is fixed at build time; the `embedded_definition_parses` test proves it parses.
    COMPOSED.get_or_init(|| serde_json::from_str(COMPOSED_JSON).expect("embedded composed definition"))
}

/// The composed definition's version (`2026081401-503d5dd1bb` style).
pub fn composed_version() -> &'static str {
    composed()["version"].as_str().unwrap_or_default()
}

fn item_tags(item: &Value) -> impl Iterator<Item = &str> {
    item.get("extensions")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
}

/// The extension tags the composed file carries (the server's `_tag_vocabulary`).
pub fn tag_vocabulary() -> &'static BTreeSet<String> {
    static VOCABULARY: OnceLock<BTreeSet<String>> = OnceLock::new();
    VOCABULARY.get_or_init(|| {
        let full = composed();
        ["sections", "questions"]
            .iter()
            .flat_map(|kind| full[*kind].as_array().into_iter().flatten())
            .flat_map(item_tags)
            .map(str::to_string)
            .collect()
    })
}

/// `composed` without the items only disabled extensions contribute, `extensions` tags dropped
/// (the server's `filter_definition`).
pub fn filter_definition(composed: &Value, enabled: &BTreeSet<String>) -> Value {
    let mut out = composed.clone();
    for kind in ["sections", "questions"] {
        let kept: Vec<Value> = composed[kind]
            .as_array()
            .into_iter()
            .flatten()
            .filter(|item| {
                let mut tags = item_tags(item).peekable();
                tags.peek().is_none() || tags.any(|tag| enabled.contains(tag))
            })
            .map(|item| {
                let mut bare = item.clone();
                if let Some(obj) = bare.as_object_mut() {
                    obj.remove("extensions");
                }
                bare
            })
            .collect();
        out[kind] = Value::Array(kept);
    }
    out
}

/// Python `json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)`.
/// Keys sort by code point (Rust `String` order); strings escape as Python does (`"`, `\`, and
/// C0 controls, short forms for `\b \t \n \f \r`, else lowercase `\u00xx`), which is
/// serde_json's escaping. Not RFC 8785: no NFC, no UTF-16 key order. The composed file holds no
/// floats; the shared vector would catch one formatted differently.
pub fn python_canonical_json(value: &Value) -> String {
    let mut out = String::new();
    write_canonical(value, &mut out);
    out
}

fn write_canonical(value: &Value, out: &mut String) {
    match value {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, key) in keys.into_iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                out.push_str(&Value::String(key.clone()).to_string());
                out.push(':');
                write_canonical(&map[key], out);
            }
            out.push('}');
        }
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        scalar => out.push_str(&scalar.to_string()),
    }
}

fn serve(chosen: BTreeSet<String>) -> Arc<ServedDefinition> {
    // At most 2^tags distinct sets; each is built once per process.
    static CACHE: OnceLock<Mutex<HashMap<BTreeSet<String>, Arc<ServedDefinition>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    if let Some(hit) = cache.lock().ok().and_then(|c| c.get(&chosen).cloned()) {
        return hit;
    }
    let mut definition = filter_definition(composed(), &chosen);
    definition["extensions"] = json!(chosen.iter().collect::<Vec<_>>());
    let body = python_canonical_json(&definition).into_bytes();
    let sha256 = format!("{:x}", Sha256::digest(&body));
    let served = Arc::new(ServedDefinition { body, sha256 });
    if let Ok(mut c) = cache.lock() {
        c.insert(chosen, served.clone());
    }
    served
}

/// A project's definition for its `enabled_extensions` (names that are not composed-file tags,
/// such as `digitva_core`, are ignored, as on the server).
pub fn served_definition<'a>(enabled: impl IntoIterator<Item = &'a str>) -> Arc<ServedDefinition> {
    let vocabulary = tag_vocabulary();
    serve(enabled.into_iter().filter(|e| vocabulary.contains(*e)).map(str::to_string).collect())
}

/// The exact slice `(version, extensions)` a draft was filled on (the server's
/// `historical_definition`). Only the version this binary carries can be served.
pub fn definition_slice(version: &str, extensions: &[String]) -> Result<Arc<ServedDefinition>, DefinitionError> {
    if version != composed_version() {
        return Err(DefinitionError::UnknownVersion);
    }
    let unknown: Vec<String> = extensions.iter().filter(|e| !tag_vocabulary().contains(*e)).cloned().collect();
    if !unknown.is_empty() {
        return Err(DefinitionError::InvalidExtensions(unknown));
    }
    Ok(serve(extensions.iter().cloned().collect()))
}

/// The `enabled_extensions` of a form-options body.
pub fn enabled_extensions(form_options: &Value) -> Vec<&str> {
    form_options["enabled_extensions"].as_array().into_iter().flatten().filter_map(Value::as_str).collect()
}

/// Refuses a project's form-options the station cannot serve exactly: an instrument other than
/// the composed one, a version this binary does not carry, or a SHA-256 its own slice does not
/// match. The message is safe to show.
pub fn check_form_options(project_id: &str, form_options: &Value) -> Result<(), String> {
    let version = form_options["instrument_version"].as_str();
    let default_code = form_options["form_types"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|ft| ft["is_default"].as_bool() == Some(true))
        .and_then(|ft| ft["instrument_code"].as_str())
        .unwrap_or(INSTRUMENT_CODE);
    if default_code != INSTRUMENT_CODE || version.is_none() {
        return Err(format!(
            "Project {project_id} uses a form this station app does not carry ({default_code}, no composed version)."
        ));
    }
    let version = version.unwrap_or_default();
    if version != composed_version() {
        return Err(format!(
            "Project {project_id} uses form version {version}; this station app carries {}. Update the station app.",
            composed_version()
        ));
    }
    let served = served_definition(enabled_extensions(form_options));
    if form_options["definition_sha256"].as_str() != Some(served.sha256.as_str()) {
        return Err(format!(
            "Project {project_id}'s form definition does not match this station app's copy of version {version}."
        ));
    }
    Ok(())
}

/// A readable English label for a module (extension tag). The composed file carries no module
/// titles, so the known tags are named here; an unknown tag shows as itself.
pub fn module_label(tag: &str) -> &str {
    match tag {
        "abha" => "ABHA health ID",
        "death_summary" => "Death summary",
        "medical_records" => "Medical records",
        "narration_language" => "Narration language",
        "social_autopsy" => "Social autopsy",
        other => other,
    }
}

/// Form options for the unprovisioned sandbox project "1" (never exported, no server policy):
/// the composed form with the station's chosen `modules` (tags outside the vocabulary are
/// ignored), English only. Shaped as the server derives a body: the always-on `digitva_core`
/// and `doris_support_whova_2022` first, then the chosen tags in vocabulary order.
pub fn sandbox_form_options(project_id: &str, modules: &BTreeSet<String>) -> Value {
    let enabled: Vec<&str> = ["digitva_core", "doris_support_whova_2022"]
        .into_iter()
        .chain(tag_vocabulary().iter().filter(|t| modules.contains(*t)).map(String::as_str))
        .collect();
    let sha = served_definition(enabled.iter().copied()).sha256.clone();
    json!({
        "project_id": project_id,
        "config_version": null,
        "enabled_extensions": enabled,
        "form_types": [{
            "form_type_code": INSTRUMENT_CODE,
            "instrument_code": INSTRUMENT_CODE,
            "title": "WHO 2022 VA Form",
            "is_default": true
        }],
        "intake_note": null,
        "default_locale": BASE_LOCALE,
        "available_locales": [{ "code": BASE_LOCALE, "label": "English", "under_review": false }],
        "translation_versions": { BASE_LOCALE: 0 },
        "narration_languages": [{ "code": "english", "label": "English" }],
        "show_guidance": false,
        "web_intake_mode": "both",
        "instrument_version": composed_version(),
        "definition_sha256": sha
    })
}

/// The base locale's translations body (the server's `export_translations` for "en").
pub fn base_translations(instrument_code: &str) -> Value {
    json!({
        "instrument_code": instrument_code,
        "locale": BASE_LOCALE,
        "version": 0,
        "questions": {},
        "choices": {}
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn vectors() -> Value {
        let path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../tests/fixtures/served_definition_vectors.json");
        serde_json::from_str(&std::fs::read_to_string(&path).expect("read vectors")).expect("vectors parse")
    }

    #[test]
    fn embedded_definition_parses() {
        assert!(!composed_version().is_empty());
        assert!(tag_vocabulary().contains("social_autopsy"));
    }

    #[test]
    fn served_definition_vectors() {
        let data = vectors();
        assert_eq!(data["version"].as_str(), Some(composed_version()));
        let cases = data["cases"].as_array().unwrap();
        assert!(cases.len() >= 4);
        for case in cases {
            let served = served_definition(enabled_extensions(case));
            assert_eq!(served.sha256, case["sha256"].as_str().unwrap(), "case {}", case["name"]);
            assert_eq!(served.body.len() as u64, case["bytes"].as_u64().unwrap(), "case {}", case["name"]);
            let body: Value = serde_json::from_slice(&served.body).unwrap();
            assert_eq!(body["extensions"], case["extensions"], "case {}", case["name"]);
        }
    }

    #[test]
    fn sandbox_selection_equal_to_a_vector_set_yields_its_sha() {
        let data = vectors();
        for case in data["cases"].as_array().unwrap() {
            let chosen: BTreeSet<String> = enabled_extensions(case).into_iter().map(str::to_string).collect();
            let options = sandbox_form_options("1", &chosen);
            assert_eq!(options["definition_sha256"], case["sha256"], "case {}", case["name"]);
            assert!(check_form_options("1", &options).is_ok());
        }
        assert_eq!(
            sandbox_form_options("1", &BTreeSet::new())["enabled_extensions"],
            json!(["digitva_core", "doris_support_whova_2022"])
        );
    }

    #[test]
    fn a_disabled_module_is_absent() {
        let with = served_definition(["social_autopsy"]);
        let without = served_definition(std::iter::empty());
        let tagged_only_by = |tag: &str| {
            composed()["questions"].as_array().unwrap().iter().find(|q| {
                let tags: Vec<&str> = item_tags(q).collect();
                tags == [tag]
            })
        };
        let name = tagged_only_by("social_autopsy").expect("a social autopsy question")["name"].clone();
        let has = |served: &ServedDefinition| {
            let body: Value = serde_json::from_slice(&served.body).unwrap();
            body["questions"].as_array().unwrap().iter().any(|q| q["name"] == name)
        };
        assert!(has(&with));
        assert!(!has(&without));
        let body: Value = serde_json::from_slice(&with.body).unwrap();
        assert!(body["questions"].as_array().unwrap().iter().all(|q| q.get("extensions").is_none()));
    }

    #[test]
    fn canonical_json_matches_python_escaping_and_order() {
        let v = json!({"b": 1, "a": ["q\"\\\n\t\u{1}\u{7f}é"], "\u{e000}": true, "\u{1f600}": null});
        assert_eq!(
            python_canonical_json(&v),
            "{\"a\":[\"q\\\"\\\\\\n\\t\\u0001\u{7f}é\"],\"b\":1,\"\u{e000}\":true,\"\u{1f600}\":null}"
        );
    }

    #[test]
    fn slices_and_refusals() {
        assert_eq!(definition_slice("0000", &[]).unwrap_err(), DefinitionError::UnknownVersion);
        assert!(matches!(
            definition_slice(composed_version(), &["nope".to_string()]),
            Err(DefinitionError::InvalidExtensions(_))
        ));
        let slice = definition_slice(composed_version(), &["social_autopsy".to_string()]).unwrap();
        assert_eq!(slice.sha256, served_definition(["social_autopsy", "digitva_core"]).sha256);

        let mut options = sandbox_form_options("P1", tag_vocabulary());
        assert!(check_form_options("P1", &options).is_ok());
        options["definition_sha256"] = json!("0".repeat(64));
        assert!(check_form_options("P1", &options).unwrap_err().contains("does not match"));
        options["instrument_version"] = json!("2022.1.5-offline");
        assert!(check_form_options("P1", &options).unwrap_err().contains("Update the station app"));
        options["instrument_version"] = Value::Null;
        assert!(check_form_options("P1", &options).is_err());
    }
}
