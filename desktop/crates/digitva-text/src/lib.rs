use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use unicode_normalization::UnicodeNormalization;

/// Digits of a national ID kept in the stored form (owner's choice: 3).
pub const NATIONAL_ID_KEEP_DIGITS: usize = 3;
/// Width of the stored form; a 16-digit VID is stored at the same width.
pub const NATIONAL_ID_STORED_WIDTH: usize = 12;
/// The masking character. Never a digit, so the stored form cannot match.
pub const MASK_CHAR: char = 'X';
/// The field that is national-ID class whatever it holds.
pub const NATIONAL_ID_FIELD: &str = "Id10073";

/// Long-number fields: a match is flagged for review, the value is kept.
pub const FLAG_ONLY_FIELDS: &[&str] = &["Id10070"];

/// Payload keys never swept: ODK and app identifiers (UUIDs, unique ids) and
/// the ABHA fields, whose 14 digits written 2-4-4-4 hold a 4-4-4 run.
pub const SKIP_FIELDS: &[&str] = &[
    "KEY",
    "instanceID",
    "sid",
    "site_individual_id",
    "unique_id",
    "unique_id2",
    "death_register_id",
    "SubmitterID",
    "DeviceID",
    "instanceName",
    "form_def",
    "abha_number",
    "abha_address",
];

/// Volatile ODK / form keys excluded from canonical payload fingerprinting.
pub const VOLATILE_PAYLOAD_KEYS: &[&str] = &[
    "AttachmentsExpected",
    "AttachmentsPresent",
    "DeviceID",
    "Edits",
    "FormVersion",
    "OdkReviewComments",
    "SubmitterID",
    "updatedAt",
    "audit",
    "instanceID",
    "survey_district",
    "survey_state",
    "ageInDays",
    "ageInDays2",
    "ageInDaysNeonate",
    "ageInMonths",
    "ageInMonthsByYear",
    "ageInMonthsRemain",
    "ageInYears",
    "ageInYears2",
    "ageInYearsRemain",
    "finalAgeInYears",
    "isAdult",
    "isAdult1",
    "isAdult2",
    "isChild",
    "isChild1",
    "isChild2",
    "isNeonatal",
    "isNeonatal1",
    "isNeonatal2",
];

/// The 19-field `PII_FIELDS` floor from Contract Section 6.6 (`app/services/pii_field_registry.py`).
pub const PII_FIELDS_FLOOR: &[&str] = &[
    "Id10007",
    "Id10010",
    "Id10010a",
    "Id10010b",
    "Id10010c",
    "Id10017",
    "Id10018",
    "Id10055",
    "Id10057",
    "Id10061",
    "Id10062",
    "Id10070",
    "Id10071",
    "Id10072",
    "Id10073",
    "visit_address",
    "visit_remarks",
    "abha_number",
    "abha_address",
];

/// Personal data keys that must NEVER cross the crate boundary into `digitva-smartva`,
/// `digitva-icd11`, coder views, or station exports (`PII_FIELDS_FLOOR` + register personal columns).
pub const FORBIDDEN_PII_KEYS: &[&str] = &[
    "Id10007",
    "Id10010",
    "Id10010a",
    "Id10010b",
    "Id10010c",
    "Id10017",
    "Id10018",
    "Id10055",
    "Id10057",
    "Id10061",
    "Id10062",
    "Id10070",
    "Id10071",
    "Id10072",
    "Id10073",
    "visit_address",
    "visit_remarks",
    "abha_number",
    "abha_address",
    "deceased_name",
    "father_name",
    "mother_name",
    "informant_name",
    "informant_phone",
    "informant_phone_2",
    "informant_relation",
    "address",
    "address_house_street",
    "address_village_ward",
    "address_landmark",
    "address_pincode",
    "place_of_death",
    "remarks",
    "location",
    "gps",
    "crs_reg_no",
    "mccd_cert_no",
];

const NOT_ANSWERED_WORDS: &[&str] = &["", "na", "n/a", "none", "null"];

/// Base codepoints (`zero`) for Unicode `Decimal_Number` (`Nd`) 10-digit runs.
const UNICODE_DECIMAL_ZERO_BASES: &[u32] = &[
    0x0030, // ASCII
    0x0660, // Arabic-Indic
    0x06F0, // Extended Arabic-Indic
    0x07C0, // NKo
    0x0966, // Devanagari
    0x09E6, // Bengali
    0x0A66, // Gurmukhi
    0x0AE6, // Gujarati
    0x0B66, // Oriya
    0x0BE6, // Tamil
    0x0C66, // Telugu
    0x0CE6, // Kannada
    0x0D66, // Malayalam
    0x0DE6, // Sinhala Lith
    0x0E50, // Thai
    0x0ED0, // Lao
    0x0F20, // Tibetan
    0x1040, // Myanmar
    0x1090, // Myanmar Shan
    0x17E0, // Khmer
    0x1810, // Mongolian
    0x1946, // Limbu
    0x19D0, // New Tai Lue
    0x1A80, // Tai Tham Hora
    0x1A90, // Tai Tham Tham
    0x1B50, // Balinese
    0x1BB0, // Sundanese
    0x1C40, // Lepcha
    0x1C50, // Ol Chiki
    0xA620, // Vai
    0xA8D0, // Saurashtra
    0xA900, // Kayah Li
    0xA9D0, // Javanese
    0xA9F0, // Myanmar Tai Laing
    0xAA50, // Cham
    0xABF0, // Meetei Mayek
    0xFF10, // Fullwidth
    0x104A0, // Osmanya
    0x11066, // Brahmi
    0x110F0, // Sora Sompeng
    0x11136, // Chakma
    0x111D0, // Sharada
    0x112F0, // Khudawadi
    0x11450, // Newa
    0x114D0, // Tirhuta
    0x11650, // Modi
    0x116C0, // Takri
    0x11730, // Ahom
    0x118E0, // Warang Citi
    0x11950, // Dives Akuru
    0x11C50, // Bhaiksuki
    0x11D50, // Masaram Gondi
    0x11DA0, // Gunjala Gondi
    0x11F50, // Kawi
    0x16A60, // Mro
    0x16AC0, // Tangsa
    0x16B50, // Pahawh Hmong
    0x1E140, // Nyiakeng Puachue Hmong
    0x1E2F0, // Wancho
    0x1E4F0, // Nag Mundari
    0x1E950, // Adlam
    0x1FBF0, // Segmented
    0x1D7CE, // Mathematical Bold
    0x1D7D8, // Mathematical Double-Struck
    0x1D7E2, // Mathematical Sans-Serif
    0x1D7EC, // Mathematical Sans-Serif Bold
    0x1D7F6, // Mathematical Monospace
];

/// If `ch` is a Unicode decimal digit (`Nd`), returns its ASCII digit `'0'..='9'`.
#[inline]
pub fn unicode_decimal_to_ascii(ch: char) -> Option<char> {
    let cp = ch as u32;
    if (0x0030..=0x0039).contains(&cp) {
        return Some(ch);
    }
    for &base in UNICODE_DECIMAL_ZERO_BASES {
        if cp >= base && cp < base + 10 {
            return char::from_u32(b'0' as u32 + (cp - base));
        }
    }
    None
}

#[inline]
pub fn is_unicode_decimal(ch: char) -> bool {
    unicode_decimal_to_ascii(ch).is_some()
}

/// Extract all Unicode decimal digits of `text`, in order, folded to ASCII `'0'..='9'`.
pub fn ascii_digits(text: &str) -> String {
    text.chars().filter_map(unicode_decimal_to_ascii).collect()
}

fn masked_digits(digits: &str) -> String {
    let kept = if NATIONAL_ID_KEEP_DIGITS == 0 {
        ""
    } else if digits.len() > NATIONAL_ID_KEEP_DIGITS {
        &digits[digits.len() - NATIONAL_ID_KEEP_DIGITS..]
    } else {
        digits
    };
    let mask_len = NATIONAL_ID_STORED_WIDTH.saturating_sub(kept.len());
    let mut out = String::with_capacity(NATIONAL_ID_STORED_WIDTH);
    for _ in 0..mask_len {
        out.push(MASK_CHAR);
    }
    out.push_str(kept);
    out
}

/// True when `value` is already in the stored form (`XXXXXXXXX123` or `XXXXXXXXXXXX`).
pub fn is_reduced_national_id(value: &str) -> bool {
    if value.len() != NATIONAL_ID_STORED_WIDTH || !value.is_ascii() {
        return false;
    }
    let head_len = NATIONAL_ID_STORED_WIDTH - NATIONAL_ID_KEEP_DIGITS;
    let (head, tail) = value.split_at(head_len);
    if !head.chars().all(|c| c == MASK_CHAR) {
        return false;
    }
    tail.chars().all(|c| c.is_ascii_digit()) || tail.chars().all(|c| c == MASK_CHAR)
}

#[inline]
fn is_national_id_sep(ch: char) -> bool {
    matches!(
        ch,
        ' ' | '-'
            | '\u{00A0}'
            | '\u{2010}'
            | '\u{2011}'
            | '\u{2012}'
            | '\u{2013}'
            | '\u{2014}'
            | '\u{2015}'
            | '\u{2212}'
            | '\u{3000}'
            | '\u{FF0D}'
    )
}

#[inline]
fn is_word_char(ch: char) -> bool {
    ch.is_alphanumeric() || ch == '_' || is_unicode_decimal(ch)
}

/// Scan `chars` starting at `start_idx` for a 12-digit (4-4-4) or 16-digit (4-4-4-4)
/// national ID run with valid left and right token boundaries.
/// Returns `Some(end_idx)` (exclusive char index) if matched.
fn match_national_id_at(chars: &[char], start_idx: usize) -> Option<usize> {
    // Left boundary:
    // (?<![\w\-]) and (?<!\d\.)
    if start_idx > 0 {
        let prev = chars[start_idx - 1];
        if is_word_char(prev) || prev == '-' {
            return None;
        }
        if prev == '.' && start_idx >= 2 && is_unicode_decimal(chars[start_idx - 2]) {
            return None;
        }
    }

    let check_right_boundary = |end_idx: usize| -> bool {
        if end_idx < chars.len() {
            let next = chars[end_idx];
            if is_word_char(next) || next == '-' {
                return false;
            }
            if next == '.' && end_idx + 1 < chars.len() && is_word_char(chars[end_idx + 1]) {
                return false;
            }
        }
        true
    };

    let read_four_digits = |pos: usize| -> Option<usize> {
        if pos + 4 > chars.len() {
            return None;
        }
        for i in 0..4 {
            if !is_unicode_decimal(chars[pos + i]) {
                return None;
            }
        }
        Some(pos + 4)
    };

    let read_sep_and_four = |pos: usize| -> Option<usize> {
        if pos >= chars.len() {
            return None;
        }
        let after_sep = if is_national_id_sep(chars[pos]) {
            pos + 1
        } else {
            pos
        };
        read_four_digits(after_sep)
    };

    let p1 = read_four_digits(start_idx)?;
    let p2 = read_sep_and_four(p1)?;
    let p3 = read_sep_and_four(p2)?;

    // Try optional 4th group (16-digit VID) first (greedy)
    if let Some(p4) = read_sep_and_four(p3) {
        if check_right_boundary(p4) {
            return Some(p4);
        }
    }

    if check_right_boundary(p3) {
        return Some(p3);
    }

    None
}

/// True when `text` holds a 12-digit (Aadhaar) or 16-digit (VID) run,
/// groups of four optionally separated by one space or hyphen.
pub fn looks_like_national_id(text: &str) -> bool {
    let chars: Vec<char> = text.chars().collect();
    for i in 0..chars.len() {
        if match_national_id_at(&chars, i).is_some() {
            return true;
        }
    }
    false
}

/// `(stored form, needs review)` for an `Id10073` answer.
///
/// Blank, null-like words (`na`, `n/a`, `none`, `null`) or punctuation-only strings
/// return `(None, false)`. Otherwise returns `(Some("XXXXXXXXX123"), needs_review)`.
pub fn reduce_national_id_flagged(value: &str) -> (Option<String>, bool) {
    let text = value.trim();
    let lower = text.to_lowercase();
    if NOT_ANSWERED_WORDS.contains(&lower.as_str())
        || !text.chars().any(|c| c.is_alphanumeric() || is_unicode_decimal(c))
    {
        return (None, false);
    }
    if is_reduced_national_id(text) {
        return (Some(text.to_string()), false);
    }
    let normalized: String = text.nfkc().collect();
    let digits = ascii_digits(&normalized);
    let well_formed = (digits.len() == 12 || digits.len() == 16) && looks_like_national_id(text);
    if digits.len() < NATIONAL_ID_KEEP_DIGITS {
        let all_masked: String = std::iter::repeat(MASK_CHAR)
            .take(NATIONAL_ID_STORED_WIDTH)
            .collect();
        return (Some(all_masked), true);
    }
    (Some(masked_digits(&digits)), !well_formed)
}

/// Stored form of an `Id10073` string value.
pub fn reduce_national_id(value: &str) -> Option<String> {
    reduce_national_id_flagged(value).0
}

/// `(stored form, needs review)` for a JSON value (`Value`).
pub fn reduce_national_id_json_flagged(value: &Value) -> (Option<String>, bool) {
    match value {
        Value::Null | Value::Bool(_) => (None, false),
        Value::String(s) => reduce_national_id_flagged(s),
        Value::Number(n) => reduce_national_id_flagged(&n.to_string()),
        _ => (None, false),
    }
}

/// `(text with each national-ID run masked, found)`.
pub fn redact_national_id_digits(text: &str) -> (String, bool) {
    let chars: Vec<char> = text.chars().collect();
    let mut out = String::with_capacity(text.len());
    let mut i = 0;
    let mut found = false;

    while i < chars.len() {
        if let Some(end_idx) = match_national_id_at(&chars, i) {
            let matched: String = chars[i..end_idx].iter().collect();
            let digits = ascii_digits(&matched);
            out.push_str(&masked_digits(&digits));
            found = true;
            i = end_idx;
        } else {
            out.push(chars[i]);
            i += 1;
        }
    }

    (out, found)
}

/// `(payload with national IDs reduced, flagged field ids)`.
///
/// `Id10073` is reduced at any depth; every other string value is swept with
/// `redact_national_id_digits` except `SKIP_FIELDS`; a match in `FLAG_ONLY_FIELDS`
/// is flagged and kept.
pub fn redact_payload_national_ids(payload: &Value) -> (Value, Vec<String>) {
    if !payload.is_object() {
        return (payload.clone(), Vec::new());
    }
    let mut flagged = Vec::new();
    let out = redact_json_value(payload, None, &mut flagged);
    (out, flagged)
}

fn redact_json_value(value: &Value, key: Option<&str>, flagged: &mut Vec<String>) -> Value {
    match value {
        Value::Object(map) => {
            let mut out = Map::with_capacity(map.len());
            for (child_key, child_val) in map {
                let new_val = redact_json_value(child_val, Some(child_key.as_str()), flagged);
                out.insert(child_key.clone(), new_val);
            }
            Value::Object(out)
        }
        Value::Array(arr) => {
            let out: Vec<Value> = arr
                .iter()
                .map(|item| redact_json_value(item, key, flagged))
                .collect();
            Value::Array(out)
        }
        _ => {
            if key == Some(NATIONAL_ID_FIELD) {
                if value.is_null() || value.is_boolean() {
                    return value.clone();
                }
                let (reduced, needs_review) = reduce_national_id_json_flagged(value);
                if needs_review {
                    flagged.push(NATIONAL_ID_FIELD.to_string());
                }
                if let Some(r) = reduced {
                    if value.as_str() == Some(r.as_str()) {
                        return value.clone();
                    }
                    return Value::String(r);
                }
                return value.clone();
            }

            let Some(s) = value.as_str() else {
                return value.clone();
            };

            if let Some(k) = key {
                if SKIP_FIELDS.contains(&k) {
                    return value.clone();
                }
                if FLAG_ONLY_FIELDS.contains(&k) {
                    if looks_like_national_id(s) {
                        flagged.push(k.to_string());
                    }
                    return value.clone();
                }
            }

            let (new_text, found) = redact_national_id_digits(s);
            if found {
                flagged.push(key.unwrap_or("None").to_string());
                return Value::String(new_text);
            }
            value.clone()
        }
    }
}

/// Canonicalize a numeric string if `raw` represents a finite decimal number
/// matching Python's `Decimal(str(value)).normalize()` + `format(..., "f")` rules.
fn canonicalize_decimal_str(raw: &str) -> Option<String> {
    let s = raw.trim();
    if s.is_empty() {
        return None;
    }
    let (neg, rest) = if let Some(r) = s.strip_prefix('-') {
        (true, r)
    } else if let Some(r) = s.strip_prefix('+') {
        (false, r)
    } else {
        (false, s)
    };
    if rest.is_empty() {
        return None;
    }

    // Split optional exponent
    let (mantissa, exp_val): (&str, i64) = if let Some(idx) = rest.find(['e', 'E']) {
        let (m, e_str) = rest.split_at(idx);
        let exp: i64 = e_str[1..].parse().ok()?;
        (m, exp)
    } else {
        (rest, 0)
    };

    let (int_part, frac_part) = if let Some(dot_idx) = mantissa.find('.') {
        let (i, f_with_dot) = mantissa.split_at(dot_idx);
        let f = &f_with_dot[1..];
        if f.contains('.') {
            return None;
        }
        (i, f)
    } else {
        (mantissa, "")
    };

    if int_part.is_empty() && frac_part.is_empty() {
        return None;
    }
    if !int_part.chars().all(|c| c.is_ascii_digit()) || !frac_part.chars().all(|c| c.is_ascii_digit()) {
        return None;
    }

    // Collect all digits and compute decimal point position
    let mut digits = String::with_capacity(int_part.len() + frac_part.len());
    digits.push_str(int_part);
    digits.push_str(frac_part);

    let trimmed_digits = digits.trim_start_matches('0');
    if trimmed_digits.is_empty() {
        return Some("0".to_string());
    }

    let leading_zeros = digits.len() - trimmed_digits.len();
    let point_pos = (int_part.len() as i64) - (leading_zeros as i64) + exp_val;

    let mut rendered = String::new();
    if point_pos <= 0 {
        rendered.push_str("0.");
        for _ in 0..(-point_pos) {
            rendered.push('0');
        }
        rendered.push_str(trimmed_digits);
    } else if (point_pos as usize) >= trimmed_digits.len() {
        rendered.push_str(trimmed_digits);
        for _ in 0..((point_pos as usize) - trimmed_digits.len()) {
            rendered.push('0');
        }
    } else {
        let split = point_pos as usize;
        rendered.push_str(&trimmed_digits[..split]);
        rendered.push('.');
        rendered.push_str(&trimmed_digits[split..]);
    }

    if rendered.contains('.') {
        while rendered.ends_with('0') {
            rendered.pop();
        }
        if rendered.ends_with('.') {
            rendered.pop();
        }
    }

    if rendered.is_empty() || rendered == "0" {
        return Some("0".to_string());
    }

    if neg {
        Some(format!("-{rendered}"))
    } else {
        Some(rendered)
    }
}

fn normalize_scalar_for_fingerprint(value: &Value) -> Value {
    match value {
        Value::Null | Value::Bool(_) => value.clone(),
        Value::Number(n) => {
            let s = n.to_string();
            Value::String(canonicalize_decimal_str(&s).unwrap_or(s))
        }
        Value::String(s) => {
            let stripped = s.trim();
            let lower = stripped.to_lowercase();
            if NOT_ANSWERED_WORDS.contains(&lower.as_str()) {
                return Value::Null;
            }
            if let Some(canon) = canonicalize_decimal_str(stripped) {
                return Value::String(canon);
            }
            Value::String(stripped.to_string())
        }
        _ => value.clone(),
    }
}

fn normalize_value_for_fingerprint(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut out = Map::new();
            for (k, v) in map {
                if !VOLATILE_PAYLOAD_KEYS.contains(&k.as_str()) {
                    out.insert(k.clone(), normalize_value_for_fingerprint(v));
                }
            }
            Value::Object(out)
        }
        Value::Array(arr) => {
            Value::Array(arr.iter().map(normalize_value_for_fingerprint).collect())
        }
        _ => normalize_scalar_for_fingerprint(value),
    }
}

/// Return a stable business-payload representation for change detection.
/// Reduces national IDs (`Id10073` and free-text runs) before stripping volatile keys.
pub fn normalize_payload_for_fingerprint(payload_data: &Value) -> Value {
    let (redacted, _) = redact_payload_national_ids(payload_data);
    normalize_value_for_fingerprint(&redacted)
}

fn write_canonical_json_ascii(value: &Value, buf: &mut String) {
    match value {
        Value::Null => buf.push_str("null"),
        Value::Bool(true) => buf.push_str("true"),
        Value::Bool(false) => buf.push_str("false"),
        Value::Number(n) => buf.push_str(&n.to_string()),
        Value::String(s) => {
            buf.push('"');
            for ch in s.chars() {
                match ch {
                    '"' => buf.push_str("\\\""),
                    '\\' => buf.push_str("\\\\"),
                    '\x08' => buf.push_str("\\b"),
                    '\x0c' => buf.push_str("\\f"),
                    '\n' => buf.push_str("\\n"),
                    '\r' => buf.push_str("\\r"),
                    '\t' => buf.push_str("\\t"),
                    c if (c as u32) < 0x20 => {
                        buf.push_str(&format!("\\u{:04x}", c as u32));
                    }
                    c if (c as u32) <= 0x7e => {
                        buf.push(c);
                    }
                    c => {
                        let cp = c as u32;
                        if cp <= 0xFFFF {
                            buf.push_str(&format!("\\u{:04x}", cp));
                        } else {
                            let u = cp - 0x10000;
                            let high = 0xD800 + ((u >> 10) & 0x3FF);
                            let low = 0xDC00 + (u & 0x3FF);
                            buf.push_str(&format!("\\u{:04x}\\u{:04x}", high, low));
                        }
                    }
                }
            }
            buf.push('"');
        }
        Value::Array(arr) => {
            buf.push('[');
            for (idx, item) in arr.iter().enumerate() {
                if idx > 0 {
                    buf.push(',');
                }
                write_canonical_json_ascii(item, buf);
            }
            buf.push(']');
        }
        Value::Object(map) => {
            buf.push('{');
            let mut sorted: Vec<(&String, &Value)> = map.iter().collect();
            sorted.sort_by(|a, b| a.0.cmp(b.0));
            for (idx, (k, v)) in sorted.iter().enumerate() {
                if idx > 0 {
                    buf.push(',');
                }
                write_canonical_json_ascii(&Value::String((*k).clone()), buf);
                buf.push(':');
                write_canonical_json_ascii(v, buf);
            }
            buf.push('}');
        }
    }
}

/// Compute SHA-256 hex fingerprint matching Python's `canonical_payload_fingerprint`.
pub fn canonical_payload_fingerprint(payload_data: &Value) -> String {
    let normalized = if payload_data.is_null() {
        normalize_payload_for_fingerprint(&Value::Object(Map::new()))
    } else {
        normalize_payload_for_fingerprint(payload_data)
    };
    let mut canonical_json = String::new();
    write_canonical_json_ascii(&normalized, &mut canonical_json);
    let mut hasher = Sha256::new();
    hasher.update(canonical_json.as_bytes());
    format!("{:x}", hasher.finalize())
}

// ============================================================================
// Registration Identifiers (CRS / MCCD / Project-Configured)
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdentifierCharType {
    Digits,
    Letters,
    LettersDigits,
    LettersDigitsHyphenSlash,
}

impl IdentifierCharType {
    pub fn from_code(code: &str) -> Self {
        match code {
            "digits" => Self::Digits,
            "letters" => Self::Letters,
            "letters_digits" => Self::LettersDigits,
            _ => Self::LettersDigitsHyphenSlash,
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Digits => "digits",
            Self::Letters => "letters",
            Self::LettersDigits => "letters_digits",
            Self::LettersDigitsHyphenSlash => "letters_digits_hyphen_slash",
        }
    }

    pub fn allows_char(&self, ch: char) -> bool {
        match self {
            Self::Digits => ch.is_ascii_digit(),
            Self::Letters => ch.is_ascii_uppercase(),
            Self::LettersDigits => ch.is_ascii_uppercase() || ch.is_ascii_digit(),
            Self::LettersDigitsHyphenSlash => {
                ch.is_ascii_uppercase() || ch.is_ascii_digit() || matches!(ch, '-' | '/')
            }
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IdentifierValidationRule {
    pub code: String,
    pub label: String,
    pub char_type: IdentifierCharType,
    pub min_length: usize,
    pub max_length: usize,
    pub pattern: Option<String>,
    #[serde(default)]
    pub example: Option<String>,
}

/// Normalise a registration identifier (`docs/policy/death-registration-identifiers.md`):
/// Unicode NFKC -> trim -> collapse internal whitespace runs to a single ASCII space -> CAPITALS.
/// Blank strings return `None`.
pub fn normalise_identifier(raw: Option<&str>) -> Option<String> {
    let text = raw?;
    let nfkc: String = text.nfkc().collect();
    let collapsed = nfkc.split_whitespace().collect::<Vec<&str>>().join(" ");
    if collapsed.is_empty() {
        return None;
    }
    Some(collapsed.to_uppercase())
}

fn format_identifier_error(rule: &IdentifierValidationRule, fallback: String) -> String {
    if let Some(ex) = &rule.example {
        let trimmed = ex.trim();
        if !trimmed.is_empty() {
            return format!("{} must look like {}.", rule.label, trimmed);
        }
    }
    fallback
}

/// Validate and normalise a registration identifier against `rule` (Contract Section 6.1).
/// Anchored full match on `pattern`; never echoes the raw or normalised value in error messages.
pub fn validate_identifier(
    raw: Option<&str>,
    rule: &IdentifierValidationRule,
) -> Result<Option<String>, String> {
    let Some(norm) = normalise_identifier(raw) else {
        return Ok(None);
    };
    let char_count = norm.chars().count();
    if char_count < rule.min_length || char_count > rule.max_length {
        return Err(format_identifier_error(
            rule,
            format!(
                "{} must be between {} and {} characters.",
                rule.label, rule.min_length, rule.max_length
            ),
        ));
    }
    if !norm.chars().all(|c| rule.char_type.allows_char(c)) {
        return Err(format_identifier_error(
            rule,
            format!(
                "{} contains characters not permitted for type '{}'.",
                rule.label,
                rule.char_type.as_str()
            ),
        ));
    }
    if let Some(pattern_str) = &rule.pattern {
        let trimmed = pattern_str.trim();
        if !trimmed.is_empty() {
            let core = trimmed
                .strip_prefix('^')
                .unwrap_or(trimmed)
                .strip_suffix('$')
                .unwrap_or(trimmed.strip_prefix('^').unwrap_or(trimmed));
            let anchored = format!("(?-u)^(?:{core})$");
            let re = Regex::new(&anchored)
                .map_err(|_| format!("Invalid validation pattern configured for {}.", rule.label))?;
            if !re.is_match(&norm) {
                return Err(format_identifier_error(
                    rule,
                    format!("{} does not match the required format.", rule.label),
                ));
            }
        }
    }
    Ok(Some(norm))
}

/// Normalise a phone number per Contract Section 6.5:
/// Trim, remove spaces, hyphens, and parentheses; if `+91`, `91`, or `0` is followed by
/// 10 ASCII digits, keep the 10 digits. Returns `None` if empty.
pub fn normalise_phone(raw: Option<&str>) -> Option<String> {
    let text = raw?.trim();
    if text.is_empty() {
        return None;
    }
    let mut cleaned = String::with_capacity(text.len());
    for (idx, ch) in text.chars().enumerate() {
        if matches!(ch, ' ' | '-' | '(' | ')' | '\u{00A0}') {
            continue;
        }
        if idx == 0 && ch == '+' {
            cleaned.push('+');
        } else if let Some(d) = unicode_decimal_to_ascii(ch) {
            cleaned.push(d);
        } else {
            cleaned.push(ch);
        }
    }
    if cleaned.is_empty() || cleaned == "+" {
        return None;
    }
    for prefix in ["+91", "91", "0"] {
        if let Some(rest) = cleaned.strip_prefix(prefix) {
            if rest.len() == 10 && rest.chars().all(|c| c.is_ascii_digit()) {
                return Some(rest.to_string());
            }
        }
    }
    if cleaned.len() == 10 && cleaned.chars().all(|c| c.is_ascii_digit()) {
        Some(cleaned)
    } else {
        None
    }
}

/// Filter a flat string map so that only clinical/demographic keys allowed into
/// `digitva-smartva` remain, stripping all PII/identifier keys (`PII_FIELDS_FLOOR` + `extra_sealed`).
pub fn filter_clinical_answers(answers: &BTreeMap<String, String>) -> BTreeMap<String, String> {
    filter_clinical_answers_with_sealed(answers, &[])
}

pub fn filter_clinical_answers_with_sealed(
    answers: &BTreeMap<String, String>,
    extra_sealed: &[String],
) -> BTreeMap<String, String> {
    answers
        .iter()
        .filter(|(k, _)| !is_sealed_or_forbidden_key(k, extra_sealed))
        .map(|(k, v)| (k.clone(), v.clone()))
        .collect()
}

/// Returns `true` if `key` is a personal-data or identifier key forbidden inside
/// `digitva-smartva`, `digitva-icd11`, coder views, or station exports.
pub fn is_forbidden_pii_key(key: &str) -> bool {
    is_sealed_or_forbidden_key(key, &[])
}

pub fn is_sealed_or_forbidden_key(key: &str, extra_sealed: &[String]) -> bool {
    if FORBIDDEN_PII_KEYS.iter().any(|&f| f.eq_ignore_ascii_case(key)) {
        return true;
    }
    if extra_sealed.iter().any(|f| f.eq_ignore_ascii_case(key)) {
        return true;
    }
    let lower = key.to_ascii_lowercase();
    lower.starts_with("informant_")
        || lower.starts_with("address_")
        || lower.contains("phone")
        || lower.contains("aadhaar")
}

// ============================================================================
// RFC 8785 (JCS) Canonical JSON (`offline-bundle-and-transfer.md` Section 7)
// ============================================================================

/// Maximum safe IEEE-754 integer allowed by Bundle Spec Section 7 (`2^53 - 1`).
pub const JCS_MAX_SAFE_INTEGER: i64 = 9_007_199_254_740_991;
pub const JCS_MIN_SAFE_INTEGER: i64 = -9_007_199_254_740_991;

/// Serialize `value` to RFC 8785 (JCS) canonical JSON string with Bundle Spec Section 7 rules:
/// - Object keys sorted by UTF-16 code units
/// - Strings normalised to Unicode NFC **except** values under object key `"answers_json"`,
///   which are passed through byte-exact without NFC normalisation
/// - Numbers must be integers in `[-(2^53 - 1), 2^53 - 1]`; floats/decimals are rejected.
pub fn to_jcs_string(value: &Value) -> Result<String, String> {
    let mut buf = String::new();
    write_jcs_value(value, None, &mut buf)?;
    Ok(buf)
}

/// Serialize `value` to RFC 8785 (JCS) canonical UTF-8 bytes.
pub fn to_jcs_bytes(value: &Value) -> Result<Vec<u8>, String> {
    Ok(to_jcs_string(value)?.into_bytes())
}

fn write_jcs_string(raw: &str, apply_nfc: bool, buf: &mut String) {
    let cow: std::borrow::Cow<'_, str> = if apply_nfc {
        std::borrow::Cow::Owned(raw.nfc().collect::<String>())
    } else {
        std::borrow::Cow::Borrowed(raw)
    };
    buf.push('"');
    for ch in cow.chars() {
        match ch {
            '"' => buf.push_str("\\\""),
            '\\' => buf.push_str("\\\\"),
            '\x08' => buf.push_str("\\b"),
            '\x09' => buf.push_str("\\t"),
            '\x0a' => buf.push_str("\\n"),
            '\x0c' => buf.push_str("\\f"),
            '\x0d' => buf.push_str("\\r"),
            c if (c as u32) < 0x20 => {
                buf.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => buf.push(c),
        }
    }
    buf.push('"');
}

fn write_jcs_value(value: &Value, parent_key: Option<&str>, buf: &mut String) -> Result<(), String> {
    match value {
        Value::Null => {
            buf.push_str("null");
            Ok(())
        }
        Value::Bool(b) => {
            buf.push_str(if *b { "true" } else { "false" });
            Ok(())
        }
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                if (JCS_MIN_SAFE_INTEGER..=JCS_MAX_SAFE_INTEGER).contains(&i) {
                    buf.push_str(&i.to_string());
                    return Ok(());
                }
            } else if let Some(u) = n.as_u64() {
                if u <= (JCS_MAX_SAFE_INTEGER as u64) {
                    buf.push_str(&u.to_string());
                    return Ok(());
                }
            } else if let Some(f) = n.as_f64() {
                if f.is_finite()
                    && f.fract() == 0.0
                    && f >= (JCS_MIN_SAFE_INTEGER as f64)
                    && f <= (JCS_MAX_SAFE_INTEGER as f64)
                {
                    buf.push_str(&(f as i64).to_string());
                    return Ok(());
                }
            }
            Err(format!(
                "JCS integer rule violated: number '{n}' is not an integer in [-(2^53-1), 2^53-1]."
            ))
        }
        Value::String(s) => {
            let apply_nfc = parent_key != Some("answers_json");
            write_jcs_string(s, apply_nfc, buf);
            Ok(())
        }
        Value::Array(arr) => {
            buf.push('[');
            for (idx, item) in arr.iter().enumerate() {
                if idx > 0 {
                    buf.push(',');
                }
                write_jcs_value(item, None, buf)?;
            }
            buf.push(']');
            Ok(())
        }
        Value::Object(map) => {
            buf.push('{');
            let mut entries: Vec<(String, Vec<u16>, &Value)> = map
                .iter()
                .map(|(k, v)| {
                    let nfc_k: String = k.nfc().collect();
                    let utf16: Vec<u16> = nfc_k.encode_utf16().collect();
                    (nfc_k, utf16, v)
                })
                .collect();
            entries.sort_by(|a, b| a.1.cmp(&b.1));
            for (idx, (k, _, v)) in entries.iter().enumerate() {
                if idx > 0 {
                    buf.push(',');
                }
                write_jcs_string(k, false, buf);
                buf.push(':');
                write_jcs_value(v, Some(k.as_str()), buf)?;
            }
            buf.push('}');
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_keeps_the_last_three_digits_at_fixed_width() {
        assert_eq!(NATIONAL_ID_KEEP_DIGITS, 3);
        for typed in [
            "234567890123",
            "2345 6789 0123",
            "2345-6789-0123",
            " 234567890123 ",
        ] {
            assert_eq!(
                reduce_national_id_flagged(typed),
                (Some("XXXXXXXXX123".to_string()), false),
                "failed for {typed}"
            );
        }
    }

    #[test]
    fn test_sixteen_digit_vid_stored_at_same_width() {
        assert_eq!(
            reduce_national_id_flagged("9123 4567 8901 2345"),
            (Some("XXXXXXXXX345".to_string()), false)
        );
    }

    #[test]
    fn test_unicode_digits_are_folded() {
        let devanagari = "२३४५६७८९०१२३";
        let arabic_indic = "٢٣٤٥٦٧٨٩٠١२٣";
        let fullwidth = "２３４５６７８９０１２３";
        for typed in [devanagari, arabic_indic, fullwidth] {
            assert_eq!(
                reduce_national_id_flagged(typed),
                (Some("XXXXXXXXX123".to_string()), false),
                "failed for {typed}"
            );
        }
    }

    #[test]
    fn test_reduction_is_idempotent() {
        let once = reduce_national_id("234567890123").unwrap();
        assert_eq!(once, "XXXXXXXXX123");
        assert_eq!(
            reduce_national_id_flagged(&once),
            (Some(once.clone()), false)
        );
        assert!(!looks_like_national_id(&once));
        let masked = reduce_national_id("dk").unwrap();
        assert_eq!(masked, "XXXXXXXXXXXX");
        assert_eq!(
            reduce_national_id_flagged(&masked),
            (Some(masked), false)
        );
    }

    #[test]
    fn test_junk_is_reduced_conservatively_and_flagged() {
        assert_eq!(
            reduce_national_id_flagged("12345678901"),
            (Some("XXXXXXXXX901".to_string()), true)
        );
        assert_eq!(
            reduce_national_id_flagged("1234567890123"),
            (Some("XXXXXXXXX123".to_string()), true)
        );
        assert_eq!(
            reduce_national_id_flagged("A1B2C3D4"),
            (Some("XXXXXXXXX234".to_string()), true)
        );
        assert_eq!(
            reduce_national_id_flagged("not known"),
            (Some("XXXXXXXXXXXX".to_string()), true)
        );
        assert_eq!(
            reduce_national_id_flagged("12"),
            (Some("XXXXXXXXXXXX".to_string()), true)
        );
    }

    #[test]
    fn test_blank_and_null_like_are_not_answered() {
        for value in ["", "   ", "NA", "n/a", "None", "null", "-", "\"_\"", "..."] {
            assert_eq!(
                reduce_national_id_flagged(value),
                (None, false),
                "failed for {value:?}"
            );
        }
    }

    #[test]
    fn test_looks_like_national_id() {
        for text in [
            "234567890123",
            "id 2345 6789 0123.",
            "2345-6789-0123",
            "9123456789012345",
            "Aadhaar no.234567890123",
            "Aadhaar:234567890123",
        ] {
            assert!(looks_like_national_id(text), "expected match for {text}");
        }

        for text in [
            "9876543210",
            "+91 98765 43210",
            "12345678901",
            "1234567890123",
            "12345678901234",
            "0.123456789012",
            "4.5633123456789012",
            "169512345678.jpg",
            "D1234567890123456789",
            "REG234567890123",
            "1b4e28ba-2fa1-1234-5678-123456789012",
            "XXXXXXXXX123",
            "",
        ] {
            assert!(
                !looks_like_national_id(text),
                "expected NO match for {text}"
            );
        }
    }

    #[test]
    fn test_redact_free_text() {
        let text = "Aadhaar 2345 6789 0123 and VID 9123-4567-8901-2345, phone 9876543210.";
        assert!(looks_like_national_id(text));
        let (new_text, found) = redact_national_id_digits(text);
        assert!(found);
        assert_eq!(
            new_text,
            "Aadhaar XXXXXXXXX123 and VID XXXXXXXXX345, phone 9876543210."
        );
        assert_eq!(redact_national_id_digits(&new_text), (new_text, false));
    }

    #[test]
    fn test_redact_payload_national_ids() {
        let payload = json!({
            "Id10073": "234567890123",
            "Id10476": "The ID 345678901234 was shown.",
            "Id10070": "234567890123",
            "Id10213": "9.9999999999999999",
            "md_im1": "169512345678.jpg",
            "site_individual_id": "234567890123",
            "abha_number": "12-3456-7890-1234",
            "Id10019": "female"
        });
        let (reduced, mut flagged) = redact_payload_national_ids(&payload);
        flagged.sort();
        assert_eq!(reduced["Id10073"], "XXXXXXXXX123");
        assert_eq!(reduced["Id10476"], "The ID XXXXXXXXX234 was shown.");
        assert_eq!(reduced["Id10070"], "234567890123");
        assert_eq!(reduced["Id10213"], "9.9999999999999999");
        assert_eq!(reduced["md_im1"], "169512345678.jpg");
        assert_eq!(reduced["site_individual_id"], "234567890123");
        assert_eq!(reduced["abha_number"], "12-3456-7890-1234");
        assert_eq!(flagged, vec!["Id10070", "Id10476"]);
    }

    #[test]
    fn test_canonical_payload_fingerprint_ignores_masked_national_id_prefix_and_volatile_keys() {
        let full = json!({
            "Id10073": "2345 6789 0123",
            "Id10019": "female",
            "Id10023": "65.0",
            "Id10104": "NA",
            "DeviceID": "device-a",
            "updatedAt": "2026-10-20T00:00:00Z"
        });
        let reduced = json!({
            "Id10073": "XXXXXXXXX123",
            "Id10019": "female",
            "Id10023": 65,
            "Id10104": null,
            "DeviceID": "device-b",
            "updatedAt": "2026-10-21T00:00:00Z"
        });
        assert_eq!(
            canonical_payload_fingerprint(&full),
            canonical_payload_fingerprint(&reduced)
        );
    }

    #[test]
    fn test_normalise_and_validate_registration_identifiers() {
        assert_eq!(
            normalise_identifier(Some("  crs-2026 / 00142  ")),
            Some("CRS-2026 / 00142".to_string())
        );
        assert_eq!(normalise_identifier(Some("   ")), None);

        let crs_rule = IdentifierValidationRule {
            code: "crs_reg_no".to_string(),
            label: "CRS Registration Number".to_string(),
            char_type: IdentifierCharType::LettersDigitsHyphenSlash,
            min_length: 3,
            max_length: 64,
            pattern: Some(r"CRS/[A-Z]{2}/\d{4}/\d{4}".to_string()),
            example: Some("CRS/UP/2026/0091".to_string()),
        };
        assert_eq!(
            validate_identifier(Some("crs/up/2026/0091"), &crs_rule).unwrap(),
            Some("CRS/UP/2026/0091".to_string())
        );
        // Substring match must fail because pattern is anchored (Contract 6.1)
        assert!(validate_identifier(Some("XX-CRS/UP/2026/0091-YY"), &crs_rule).is_err());
        let err = validate_identifier(Some("ab"), &crs_rule).unwrap_err();
        assert!(!err.contains("ab"));
        assert!(err.contains("CRS/UP/2026/0091"));
    }

    #[test]
    fn test_normalise_phone_drops_prefix_when_ten_digits_remain() {
        assert_eq!(
            normalise_phone(Some("+91 98765-43210")),
            Some("9876543210".to_string())
        );
        assert_eq!(
            normalise_phone(Some("91 98765 43210")),
            Some("9876543210".to_string())
        );
        assert_eq!(
            normalise_phone(Some("09876543210")),
            Some("9876543210".to_string())
        );
        assert_eq!(
            normalise_phone(Some("(098) 765-43210")),
            Some("9876543210".to_string())
        );
    }

    #[test]
    fn test_jcs_canonicalization_nfc_answers_json_passthrough_and_integer_rule() {
        // Decomposed 'e' + U+0301 in normal field is NFC-normalised to U+00E9,
        // while inside `answers_json` it stays byte-exact!
        let input = json!({
            "z_key": "e\u{0301}",
            "a_key": 42,
            "answers_json": "{\"raw\":\"e\u{0301}\"}"
        });
        let jcs = to_jcs_string(&input).unwrap();
        assert_eq!(
            jcs,
            "{\"a_key\":42,\"answers_json\":\"{\\\"raw\\\":\\\"e\u{0301}\\\"}\",\"z_key\":\"\u{00e9}\"}"
        );

        // Floats are rejected by JCS integer rule
        let bad_float = json!({ "score": 12.5 });
        assert!(to_jcs_string(&bad_float).is_err());
    }
}
