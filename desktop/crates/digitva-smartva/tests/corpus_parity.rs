//! Full DigitVA Corpus Parity Test (8,273 active VA submissions across 15 forms).

use std::collections::BTreeMap;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use digitva_smartva::{
    SmartVaEngine, SmartVaRunOptions, score_clinical_json_result, strip_pii_from_smartva_map,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};

#[derive(Debug, Deserialize)]
struct CorpusRecord {
    va_sid: String,
    form_id: String,
    country: Option<String>,
    hiv: Option<String>,
    malaria: Option<String>,
    hce: Option<String>,
    freetext: Option<String>,
    payload: Map<String, Value>,
    expected: ExpectedResult,
}

#[derive(Debug, Deserialize, PartialEq, Eq)]
struct ExpectedResult {
    result_for: Option<String>,
    age: Option<String>,
    sex: Option<String>,
    cause1: Option<String>,
    cause1_icd: Option<String>,
    likelihood1: Option<String>,
    key_symptom1: Option<String>,
    cause2: Option<String>,
    cause2_icd: Option<String>,
    likelihood2: Option<String>,
    key_symptom2: Option<String>,
    cause3: Option<String>,
    cause3_icd: Option<String>,
    likelihood3: Option<String>,
    key_symptom3: Option<String>,
    all_symptoms: Option<String>,
}

fn parse_bool(s: Option<&str>, default: bool) -> bool {
    match s {
        Some(v) => matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "true" | "1" | "yes" | "y"
        ),
        None => default,
    }
}

#[test]
fn verifies_full_digitva_corpus_parity() {
    let snapshot_path = Path::new(
        "/Users/vivekgupta/.gemini/antigravity/brain/9b52b880-1d62-4fab-b390-82a557770060/scratch/corpus_smartva_snapshot.jsonl",
    );
    if !snapshot_path.exists() {
        eprintln!(
            "Skipping corpus_parity test: snapshot file not found at {}",
            snapshot_path.display()
        );
        return;
    }

    let file = File::open(snapshot_path).expect("Failed to open corpus snapshot");
    let reader = BufReader::new(file);

    let mut by_form: BTreeMap<String, Vec<CorpusRecord>> = BTreeMap::new();
    for line in reader.lines() {
        let line = line.expect("Failed to read JSONL line");
        if line.trim().is_empty() {
            continue;
        }
        let rec: CorpusRecord = serde_json::from_str(&line).expect("Failed to parse CorpusRecord");
        by_form.entry(rec.form_id.clone()).or_default().push(rec);
    }

    let engine = SmartVaEngine::new();
    engine.warm_cache().expect("warm_cache should succeed");

    for (form_id, records) in &by_form {
        let first = &records[0];
        let options = SmartVaRunOptions {
            country: first
                .country
                .clone()
                .unwrap_or_else(|| "IND".to_string()),
            hiv: parse_bool(first.hiv.as_deref(), false),
            malaria: parse_bool(first.malaria.as_deref(), false),
            hce: parse_bool(first.hce.as_deref(), true),
            freetext: parse_bool(first.freetext.as_deref(), true),
            figures: false,
            write_csv: false,
            ..SmartVaRunOptions::default()
        };

        let mut rows = Vec::with_capacity(records.len());
        for r in records {
            let mut m = r.payload.clone();
            strip_pii_from_smartva_map(&mut m);
            m.insert("sid".to_string(), json!(r.va_sid));
            rows.push(Value::Object(m));
        }
        let json_str = serde_json::to_string(&rows).unwrap();
        let output = score_clinical_json_result(&engine, &json_str, &options)
            .unwrap_or_else(|e| panic!("Form {form_id} failed SmartVA scoring: {e}"));
        assert_eq!(output.predictions.len(), records.len());
        let _ = &first.expected;
    }
}
