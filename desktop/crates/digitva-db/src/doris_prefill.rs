//! Prefill a DORIS death certificate's non-cause fields from the VA interview.
//!
//! A port of the server's `app/services/doris_prefill.py` (`doris_prefill_from_payload`) and
//! the readers it uses from `app/services/who_va_answers.py`, so the station's workspace seeds
//! the DORIS editor exactly as the server's does. Keep the two in step: the fixture
//! `tests/fixtures/doris_prefill_vectors.json` is the Python output for the same payloads.
//! Causes, intervals, `PregnancyContribute`, `PerinatalDescription` and `Surgery.Date` are
//! never prefilled; odd answers are left out, never an error.

use chrono::{Datelike, NaiveDate};
use digitva_icd11::certificate::{MAX_TEXT_LENGTH, drop_inapplicable_sections};
use serde_json::{Map, Value, json};

const UNKNOWN: [&str; 2] = ["dk", "ref"];
const REFUSED_OR_UNKNOWN: [i64; 2] = [88, 99];

// Maternal chain: the first "yes" decides the band (0 at death, 1 within 42 days, 2 from 43
// days to one year). Id10308 is asked only after the six-week answers are no.
const MATERNAL_BANDS: [(&str, i64); 6] = [
    ("Id10305", 0),
    ("Id10312", 0),
    ("Id10314", 1),
    ("Id10306", 1),
    ("Id10334", 1),
    ("Id10308", 2),
];
const MATERNAL_CHAIN: [&str; 8] = [
    "Id10305", "Id10312", "Id10313", "Id10314", "Id10306", "Id10334", "Id10308", "Id10310",
];
const INTENT: [(&str, i64); 3] = [("Id10098", 1), ("Id10099", 2), ("Id10100", 3)];
const INJURY_TYPES: [(&str, &str); 15] = [
    ("Id10079", "Road traffic injury"),
    ("Id10082", "Non-road transport injury"),
    ("Id10083", "Fall"),
    ("Id10084", "Poisoning"),
    ("Id10085", "Drowning"),
    ("Id10086", "Venomous bite or sting"),
    ("Id10087", "Injury by an animal or insect (non-venomous)"),
    ("Id10089", "Burns or fire"),
    ("Id10091", "Firearm injury"),
    ("Id10092", "Stabbed, cut or pierced"),
    ("Id10093", "Strangulation"),
    ("Id10096", "Electrocution"),
    ("Id10094", "Blunt force"),
    ("Id10095", "Force of nature"),
    ("Id10097", "Other injury"),
];

// --- answer readers (who_va_answers.py) -------------------------------------

fn text(payload: &Map<String, Value>, key: &str) -> String {
    match payload.get(key) {
        Some(Value::String(s)) => s.trim().to_string(),
        Some(Value::Number(n)) => match n.as_f64() {
            Some(f) if f.fract() == 0.0 && f.is_finite() && n.is_f64() => format!("{}", f as i64),
            _ => n.to_string(),
        },
        _ => String::new(),
    }
}

fn choice(payload: &Map<String, Value>, key: &str) -> String {
    text(payload, key).to_lowercase()
}

fn number(payload: &Map<String, Value>, key: &str) -> Option<f64> {
    let value = match payload.get(key)? {
        Value::Number(n) => n.as_f64()?,
        Value::String(s) => s.trim().parse::<f64>().ok()?,
        _ => return None,
    };
    value.is_finite().then_some(value)
}

fn whole(payload: &Map<String, Value>, key: &str, low: i64, high: i64) -> Option<i64> {
    let value = number(payload, key)?;
    if value.fract() != 0.0 || value < low as f64 || value > high as f64 {
        return None;
    }
    Some(value as i64)
}

/// The calendar date as recorded (`2025-08-04T00:00:00+05:30` -> 4 Aug).
fn calendar_date(payload: &Map<String, Value>, key: &str) -> Option<NaiveDate> {
    let raw = text(payload, key);
    let bytes = raw.as_bytes();
    if bytes.len() < 10
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || ![0..4, 5..7, 8..10]
            .iter()
            .all(|r| bytes[r.clone()].iter().all(u8::is_ascii_digit))
    {
        return None;
    }
    NaiveDate::from_ymd_opt(
        raw[0..4].parse().ok()?,
        raw[5..7].parse().ok()?,
        raw[8..10].parse().ok()?,
    )
}

/// `(precision, answer key, date)` of the answered date of birth.
fn birth_answer(payload: &Map<String, Value>) -> Option<(&'static str, &'static str, NaiveDate)> {
    match choice(payload, "Id10020").as_str() {
        "yes" => calendar_date(payload, "Id10021").map(|d| ("exact", "Id10021", d)),
        "no" | "ref" => match choice(payload, "dob_precision").as_str() {
            "month_year" => calendar_date(payload, "dob_month_year")
                .map(|d| ("month_year", "dob_month_year", d)),
            "year" => calendar_date(payload, "dob_year").map(|d| ("year", "dob_year", d)),
            _ => None,
        },
        _ => None,
    }
}

/// `(group, unit, answer key)` where the estimated age is answered.
fn age_field(payload: &Map<String, Value>) -> Option<(&'static str, &'static str, String)> {
    match choice(payload, "age_group").as_str() {
        "neonate" => Some(("neonate", "days", "age_neonate_days".to_string())),
        "child" => {
            let unit = match choice(payload, "age_child_unit").as_str() {
                "days" => "days",
                "months" => "months",
                "years" => "years",
                _ => return None,
            };
            Some(("child", unit, format!("age_child_{unit}")))
        }
        "adult" => Some(("adult", "years", "age_adult".to_string())),
        _ => None,
    }
}

fn yes(payload: &Map<String, Value>, key: &str) -> bool {
    choice(payload, key) == "yes"
}

/// yes 1, no 0, dk/ref 9; anything else (blank, unasked) `None`.
fn coded(payload: &Map<String, Value>, key: &str) -> Option<i64> {
    match choice(payload, key).as_str() {
        "yes" => Some(1),
        "no" => Some(0),
        "dk" | "ref" => Some(9),
        _ => None,
    }
}

fn is_unknown(answer: &str) -> bool {
    UNKNOWN.contains(&answer)
}

// --- sections ------------------------------------------------------------------

struct Prefill {
    certificate: Map<String, Value>,
    provenance: Map<String, Value>,
}

impl Prefill {
    fn put(
        &mut self,
        section: &str,
        field: &str,
        value: Value,
        sources: &[&str],
        note: Option<&str>,
    ) {
        let entry = self
            .certificate
            .entry(section.to_string())
            .or_insert_with(|| Value::Object(Map::new()));
        if let Value::Object(map) = entry {
            map.insert(field.to_string(), value);
        }
        let mut record = json!({ "sources": sources });
        if let Some(note) = note {
            record["note"] = json!(note);
        }
        self.provenance.insert(format!("{section}.{field}"), record);
    }
}

fn death(payload: &Map<String, Value>) -> Option<(String, i32)> {
    match choice(payload, "Id10022").as_str() {
        "yes" => ["Id10023", "Id10023_a", "Id10023_b"]
            .iter()
            .find_map(|key| calendar_date(payload, key))
            .map(|d| (d.format("%Y-%m-%d").to_string(), d.year())),
        "no" | "ref" => {
            calendar_date(payload, "Id10024").map(|d| (format!("{:04}", d.year()), d.year()))
        }
        _ => None,
    }
}

fn death_sources(payload: &Map<String, Value>) -> &'static str {
    if choice(payload, "Id10022") == "yes" {
        "Id10023"
    } else {
        "Id10024"
    }
}

fn birth(payload: &Map<String, Value>, death_year: Option<i32>) -> Option<(String, &'static str)> {
    let (precision, key, born) = birth_answer(payload)?;
    let value = match precision {
        // Year-only answers are keyed as 1 January: at age 50 or more, send the year only.
        "exact"
            if (born.month(), born.day()) == (1, 1)
                && death_year.is_some_and(|y| y - born.year() >= 50) =>
        {
            format!("{:04}", born.year())
        }
        "exact" => born.format("%Y-%m-%d").to_string(),
        "month_year" => format!("{:04}-{:02}", born.year(), born.month()),
        _ => format!("{:04}", born.year()),
    };
    Some((value, key))
}

fn estimated_age(payload: &Map<String, Value>) -> Option<(String, String)> {
    let (group, unit, key) = age_field(payload)?;
    if group == "neonate" {
        let days = whole(payload, "age_neonate_days", 0, 27);
        let hours = whole(payload, "age_neonate_hours", 0, 23);
        if let (Some(0), Some(h)) = (days, hours) {
            return Some((format!("PT{h}H"), "age_neonate_hours".to_string()));
        }
        return days.map(|d| (format!("P{d}D"), key));
    }
    let value = whole(payload, &key, 1, if group == "adult" { 150 } else { 999 })?;
    let designator = match unit {
        "days" => "D",
        "months" => "M",
        _ => "Y",
    };
    Some((format!("P{value}{designator}"), key))
}

fn under_one_year(payload: &Map<String, Value>) -> bool {
    if whole(payload, "isNeonatal", 0, 1) == Some(1) {
        return true;
    }
    whole(payload, "isChild", 0, 1) == Some(1)
        && number(payload, "ageInMonthsByYear").is_some_and(|m| m < 12.0)
}

fn fetal(payload: &Map<String, Value>, out: &mut Prefill) {
    let neonate = whole(payload, "isNeonatal", 0, 1) == Some(1);
    let mut stillborn = None;
    if neonate {
        let signs: Vec<&str> = ["Id10104", "Id10109", "Id10110"]
            .into_iter()
            .filter(|key| yes(payload, key))
            .collect();
        if !signs.is_empty() {
            stillborn = Some(0);
            out.put("FetalOrInfantDeath", "Stillborn", json!(0), &signs, None);
        } else {
            stillborn = coded(payload, "Id10114");
            if let Some(code) = stillborn {
                out.put(
                    "FetalOrInfantDeath",
                    "Stillborn",
                    json!(code),
                    &["Id10114"],
                    None,
                );
            }
        }
    }
    if neonate && stillborn != Some(1) {
        // Hours survived; age_neonate_hours counts only on a day-0 age.
        for key in ["age_neonate_hours", "doris_hours_survived"] {
            if let Some(hours) = whole(payload, key, 0, 23) {
                if key != "age_neonate_hours" || whole(payload, "age_neonate_days", 0, 0) == Some(0)
                {
                    out.put(
                        "FetalOrInfantDeath",
                        "DeathWithin24h",
                        json!(hours),
                        &[key],
                        None,
                    );
                    break;
                }
            }
        }
    }
    if let Some(multiple) = coded(payload, "Id10354") {
        out.put(
            "FetalOrInfantDeath",
            "MultiplePregnancy",
            json!(multiple),
            &["Id10354"],
            None,
        );
    }
    if let Some(weight) = whole(payload, "Id10366", 100, 9999) {
        out.put(
            "FetalOrInfantDeath",
            "BirthWeight",
            json!(weight),
            &["Id10366"],
            None,
        );
    }
    if let Some(weeks) = whole(payload, "doris_pregnancy_weeks", 8, 48) {
        out.put(
            "FetalOrInfantDeath",
            "PregnancyWeeks",
            json!(weeks),
            &["doris_pregnancy_weeks"],
            None,
        );
    } else if let Some(months) = number(payload, "Id10367").filter(|m| *m > 0.0 && *m <= 11.0) {
        let converted = (months * 4.345).floor() as i64;
        if (1..=50).contains(&converted) {
            out.put(
                "FetalOrInfantDeath",
                "PregnancyWeeks",
                json!(converted),
                &["Id10367"],
                Some("converted from months"),
            );
        }
    }
    if let Some(mother) = whole(payload, "doris_mother_age", 10, 60) {
        out.put(
            "FetalOrInfantDeath",
            "AgeMother",
            json!(mother),
            &["doris_mother_age"],
            None,
        );
    }
}

fn maternal(payload: &Map<String, Value>, out: &mut Prefill) {
    let answer = |key: &str| choice(payload, key);
    for (key, band) in MATERNAL_BANDS {
        if answer(key) == "yes" {
            out.put("MaternalDeath", "WasPregnant", json!(1), &[key], None);
            out.put(
                "MaternalDeath",
                "TimeFromPregnancy",
                json!(band),
                &[key],
                None,
            );
            return;
        }
    }
    // Died after a delivery with no timing "yes"; Id10308 = no means over a year before.
    if answer("Id10313") == "yes" && answer("Id10308") != "no" {
        out.put("MaternalDeath", "WasPregnant", json!(1), &["Id10313"], None);
        let unknown: Vec<&str> = ["Id10314", "Id10306", "Id10308"]
            .into_iter()
            .filter(|key| is_unknown(&answer(key)))
            .collect();
        if !unknown.is_empty() {
            let sources: Vec<&str> = std::iter::once("Id10313").chain(unknown).collect();
            out.put(
                "MaternalDeath",
                "TimeFromPregnancy",
                json!(9),
                &sources,
                None,
            );
        }
        return;
    }
    if answer("Id10310") == "yes" {
        out.put("MaternalDeath", "WasPregnant", json!(0), &["Id10310"], None);
        return;
    }
    let asked: Vec<&str> = MATERNAL_CHAIN
        .into_iter()
        .filter(|key| !answer(key).is_empty())
        .collect();
    if !asked.is_empty() && asked.iter().all(|key| is_unknown(&answer(key))) {
        out.put("MaternalDeath", "WasPregnant", json!(9), &asked, None);
    }
}

fn manner(payload: &Map<String, Value>, out: &mut Prefill) {
    match choice(payload, "Id10077").as_str() {
        "no" => {
            return out.put(
                "MannerOfDeath",
                "MannerOfDeath",
                json!(0),
                &["Id10077"],
                None,
            );
        }
        "dk" | "ref" => {
            return out.put(
                "MannerOfDeath",
                "MannerOfDeath",
                json!(9),
                &["Id10077"],
                None,
            );
        }
        "yes" => {}
        _ => return,
    }

    let legal_war = match choice(payload, "doris_injury_legal_war").as_str() {
        "legal" => Some(4),
        "war" => Some(5),
        _ => None,
    };
    if let Some(code) = legal_war {
        out.put(
            "MannerOfDeath",
            "MannerOfDeath",
            json!(code),
            &["doris_injury_legal_war"],
            None,
        );
    } else if yes(payload, "Id10095") {
        // Force of nature: the intent questions are skipped.
        out.put(
            "MannerOfDeath",
            "MannerOfDeath",
            json!(1),
            &["Id10095"],
            None,
        );
    } else if let Some((key, code)) = INTENT.into_iter().find(|(key, _)| yes(payload, key)) {
        out.put("MannerOfDeath", "MannerOfDeath", json!(code), &[key], None);
    } else {
        let asked: Vec<&str> = INTENT
            .into_iter()
            .map(|(key, _)| key)
            .filter(|key| !choice(payload, key).is_empty())
            .collect();
        let unknown = asked.iter().any(|key| is_unknown(&choice(payload, key)));
        let sources: Vec<&str> = if asked.is_empty() {
            vec!["Id10077"]
        } else {
            asked
        };
        out.put(
            "MannerOfDeath",
            "MannerOfDeath",
            json!(if unknown { 9 } else { 6 }),
            &sources,
            None,
        );
    }

    if let Some((date, source)) = injury_date(payload) {
        out.put(
            "MannerOfDeath",
            "DateOfExternalCauseOrPoisoning",
            json!(date),
            &[source],
            None,
        );
    }
    if let Some(place) = whole(payload, "doris_injury_place", 0, 9) {
        out.put(
            "MannerOfDeath",
            "PlaceOfOccuranceExternalCause",
            json!(place),
            &["doris_injury_place"],
            None,
        );
    }
    let kinds: Vec<(&str, &str)> = INJURY_TYPES
        .into_iter()
        .filter(|(key, _)| yes(payload, key))
        .collect();
    let description = kinds
        .iter()
        .map(|(_, label)| *label)
        .collect::<Vec<_>>()
        .join("; ");
    if !kinds.is_empty() && description.chars().count() <= MAX_TEXT_LENGTH {
        let sources: Vec<&str> = kinds.iter().map(|(key, _)| *key).collect();
        out.put(
            "MannerOfDeath",
            "DescriptionExternalCause",
            json!(description),
            &sources,
            None,
        );
    }
}

fn injury_date(payload: &Map<String, Value>) -> Option<(String, &'static str)> {
    match choice(payload, "doris_injury_date_known").as_str() {
        "full" => calendar_date(payload, "doris_injury_date")
            .map(|d| (d.format("%Y-%m-%d").to_string(), "doris_injury_date")),
        "month_year" => calendar_date(payload, "doris_injury_month_year").map(|d| {
            (
                format!("{:04}-{:02}", d.year(), d.month()),
                "doris_injury_month_year",
            )
        }),
        _ => None,
    }
}

fn surgery_days(payload: &Map<String, Value>) -> Option<f64> {
    let per_unit = match choice(payload, "doris_surgery_when_unit").as_str() {
        "days" => 1.0,
        "weeks" => 7.0,
        "months" => 30.4375,
        "years" => 365.25,
        _ => return None,
    };
    let amount = whole(payload, "doris_surgery_when", 0, 99999)?;
    if REFUSED_OR_UNKNOWN.contains(&amount) {
        return None;
    }
    Some(amount as f64 * per_unit)
}

fn surgery(payload: &Map<String, Value>, out: &mut Prefill) {
    const DIRECT: &str = "doris_surgery_performed";
    match choice(payload, DIRECT).as_str() {
        "no" => return out.put("Surgery", "WasPerformed", json!(0), &[DIRECT], None),
        "dk" | "ref" => return out.put("Surgery", "WasPerformed", json!(9), &[DIRECT], None),
        "yes" => {
            let both = [DIRECT, "doris_surgery_when"];
            let Some(days) = surgery_days(payload) else {
                if whole(payload, "doris_surgery_when", 88, 99)
                    .is_some_and(|v| REFUSED_OR_UNKNOWN.contains(&v))
                {
                    out.put("Surgery", "WasPerformed", json!(9), &both, None);
                }
                return;
            };
            if days > 28.0 {
                // DORIS asks about the last 4 weeks.
                return out.put("Surgery", "WasPerformed", json!(0), &both, None);
            }
            out.put("Surgery", "WasPerformed", json!(1), &both, None);
            let kind = text(payload, "doris_surgery_type");
            let reason = text(payload, "doris_surgery_reason");
            let described = match (kind.is_empty(), reason.is_empty()) {
                (false, false) => format!("{kind} for {reason}"),
                (false, true) => kind.clone(),
                _ => reason.clone(),
            };
            let sources: Vec<&str> = [
                ("doris_surgery_type", &kind),
                ("doris_surgery_reason", &reason),
            ]
            .into_iter()
            .filter(|(_, value)| !value.is_empty())
            .map(|(key, _)| key)
            .collect();
            if !described.is_empty() && described.chars().count() <= MAX_TEXT_LENGTH {
                out.put("Surgery", "Reason", json!(described), &sources, None);
            }
            return;
        }
        _ => {}
    }
    // No direct answer (ODK cases). Id10340 counts only with a pregnancy event.
    let pregnancy_event = MATERNAL_CHAIN
        .iter()
        .filter(|key| **key != "Id10310")
        .any(|key| yes(payload, key));
    if yes(payload, "Id10340") && pregnancy_event {
        out.put("Surgery", "WasPerformed", json!(1), &["Id10340"], None);
        out.put(
            "Surgery",
            "Reason",
            json!("Hysterectomy"),
            &["Id10340"],
            None,
        );
        return;
    }
    if let Some(within_month) = coded(payload, "Id10426") {
        out.put(
            "Surgery",
            "WasPerformed",
            json!(within_month),
            &["Id10426"],
            None,
        );
    }
}

fn autopsy(payload: &Map<String, Value>, out: &mut Prefill) {
    let Some(requested) = coded(payload, "doris_autopsy_requested") else {
        return;
    };
    out.put(
        "Autopsy",
        "WasRequested",
        json!(requested),
        &["doris_autopsy_requested"],
        None,
    );
    if requested == 1 {
        if let Some(findings) = coded(payload, "doris_autopsy_findings") {
            out.put(
                "Autopsy",
                "Findings",
                json!(findings),
                &["doris_autopsy_findings"],
                None,
            );
        }
    }
}

/// `(partial_certificate, provenance)` for one flat interview payload, as the server's
/// `doris_prefill_from_payload`: only the sections the interview answers (no `ICDVersion`, no
/// Part I), and `"Section.Field" -> {sources, note?}` for each prefilled field.
pub fn doris_prefill_from_payload(payload: &Value) -> (Value, Value) {
    let empty = Map::new();
    let payload = payload.as_object().unwrap_or(&empty);
    let mut out = Prefill {
        certificate: Map::new(),
        provenance: Map::new(),
    };

    let sex = match choice(payload, "Id10019").as_str() {
        "male" => Some(1),
        "female" => Some(2),
        "undetermined" | "other" => Some(9),
        _ => None,
    };
    if let Some(sex) = sex {
        out.put("AdministrativeData", "Sex", json!(sex), &["Id10019"], None);
    }
    let died = death(payload);
    if let Some((value, key)) = birth(payload, died.as_ref().map(|(_, year)| *year)) {
        out.put(
            "AdministrativeData",
            "DateBirth",
            json!(value),
            &[key],
            None,
        );
    }
    if let Some((value, _)) = &died {
        out.put(
            "AdministrativeData",
            "DateDeath",
            json!(value),
            &[death_sources(payload)],
            None,
        );
    }
    // Always (rule V7), even when both dates are known.
    if let Some((value, key)) = estimated_age(payload) {
        out.put(
            "AdministrativeData",
            "EstimatedAge",
            json!(value),
            &[key.as_str()],
            None,
        );
    }

    if under_one_year(payload) {
        fetal(payload, &mut out);
    }
    maternal(payload, &mut out);
    manner(payload, &mut out);
    surgery(payload, &mut out);
    autopsy(payload, &mut out);
    // Never prefill what the certificate rules hide (V1-V6).
    for path in drop_inapplicable_sections(&mut out.certificate) {
        out.provenance.remove(&path);
    }
    (
        Value::Object(out.certificate),
        Value::Object(out.provenance),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The Python builder's output for each payload. Regenerate with
    /// `desktop/crates/digitva-db/tests/fixtures/make_doris_prefill_vectors.py` (see its header).
    #[test]
    fn test_prefill_matches_the_server_builder_vectors() {
        let raw = include_str!("../tests/fixtures/doris_prefill_vectors.json");
        let vectors: Vec<Value> = serde_json::from_str(raw).unwrap();
        assert!(vectors.len() >= 10);
        for case in vectors {
            let (certificate, provenance) = doris_prefill_from_payload(&case["payload"]);
            assert_eq!(
                certificate, case["certificate"],
                "certificate: {}",
                case["name"]
            );
            assert_eq!(
                provenance, case["provenance"],
                "provenance: {}",
                case["name"]
            );
        }
    }
}
