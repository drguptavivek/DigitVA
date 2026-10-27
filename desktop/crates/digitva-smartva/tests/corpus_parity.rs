//! Parity of the Rust SmartVA engine against the reference Python SmartVA-Analyze.
//!
//! `tests/fixtures/corpus_inputs.json` holds a small synthetic corpus (see `fixtures/README.md`);
//! `tests/fixtures/corpus_expected.json` holds the Python reference output for it (cause,
//! likelihood label, rejected SIDs). Regenerate with `tests/fixtures/regenerate_expected.py`.
//!
//! Tolerance: causes and likelihood labels ("Likely", "Possible", ...) are categorical, so they
//! must match exactly; there is no numeric tolerance. A missing fixture fails the test.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::PathBuf;

use digitva_smartva::{
    SmartVaEngine, SmartVaRunOptions, score_clinical_json_result, strip_pii_from_smartva_map,
};
use serde::Deserialize;
use serde_json::{Map, Value};

#[derive(Deserialize)]
struct Inputs {
    options: Options,
    rows: Vec<Map<String, Value>>,
}

#[derive(Deserialize)]
struct Options {
    country: String,
    hiv: bool,
    malaria: bool,
    hce: bool,
    freetext: bool,
}

#[derive(Deserialize)]
struct Expected {
    smartva_version: String,
    records: BTreeMap<String, BTreeMap<String, Option<String>>>,
    rejected: BTreeSet<String>,
}

fn fixture<T: for<'de> Deserialize<'de>>(name: &str) -> T {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures").join(name);
    let text = fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("missing fixture {}: {e}", path.display()));
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("bad fixture {}: {e}", path.display()))
}

/// Same extraction as the server's `_SMARTVA_REPORT_REJECTION_RE`: `SID: <sid> (row N) <reason>`.
fn rejected_sids(report: &str) -> BTreeSet<String> {
    report
        .lines()
        .filter_map(|l| {
            let rest = l.trim().strip_prefix("SID:")?.trim_start();
            let (sid, tail) = rest.split_once(char::is_whitespace)?;
            tail.trim_start().starts_with("(row ").then(|| sid.to_string())
        })
        .collect()
}

#[test]
fn rust_engine_matches_python_reference_on_fixture_corpus() {
    let inputs: Inputs = fixture("corpus_inputs.json");
    let expected: Expected = fixture("corpus_expected.json");
    assert!(!expected.records.is_empty(), "expected snapshot has no records");
    assert!(!expected.rejected.is_empty(), "expected snapshot has no rejected SIDs");

    let o = &inputs.options;
    let options = SmartVaRunOptions {
        country: o.country.clone(),
        hiv: o.hiv,
        malaria: o.malaria,
        hce: o.hce,
        freetext: o.freetext,
        figures: false,
        write_csv: false,
        ..SmartVaRunOptions::default()
    };
    let rows: Vec<Value> = inputs
        .rows
        .into_iter()
        .map(|mut m| {
            strip_pii_from_smartva_map(&mut m);
            Value::Object(m)
        })
        .collect();

    let engine = SmartVaEngine::new();
    let out = score_clinical_json_result(&engine, &serde_json::to_string(&rows).unwrap(), &options)
        .expect("scoring failed");

    let got_rejected = rejected_sids(&out.report_text);
    let got: BTreeMap<_, _> = out.predictions.iter().map(|p| (p.sid.trim().to_string(), p)).collect();

    let mut mismatches = Vec::new();
    if got_rejected != expected.rejected {
        mismatches.push(format!("rejected: rust {got_rejected:?} vs python {:?}", expected.rejected));
    }
    let got_sids: BTreeSet<_> = got.keys().cloned().collect();
    let want_sids: BTreeSet<_> = expected.records.keys().cloned().collect();
    if got_sids != want_sids {
        mismatches.push(format!("scored sids: rust {got_sids:?} vs python {want_sids:?}"));
    }
    for (sid, want) in &expected.records {
        let Some(p) = got.get(sid) else { continue };
        let have: [(&str, &Option<String>); 6] = [
            ("cause1", &p.cause1), ("likelihood1", &p.likelihood1),
            ("cause2", &p.cause2), ("likelihood2", &p.likelihood2),
            ("cause3", &p.cause3), ("likelihood3", &p.likelihood3),
        ];
        for (field, val) in have {
            let val = val.as_deref().map(str::trim).filter(|s| !s.is_empty());
            if val != want[field].as_deref() {
                mismatches.push(format!("{sid}.{field}: rust {val:?} vs python {:?}", want[field]));
            }
        }
    }
    assert!(
        mismatches.is_empty(),
        "Rust diverges from Python SmartVA {}:\n{}",
        expected.smartva_version,
        mismatches.join("\n")
    );
}
