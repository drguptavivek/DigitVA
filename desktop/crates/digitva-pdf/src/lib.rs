//! WHO Standard Medical Certificate of Cause of Death (MCCD) A4 PDF generator.
//!
//! Produces a deterministic, vector A4 PDF (PDF 1.4) for any coded VA case
//! (both WHO ICD-11 DORIS certificates and Simple ICD-10/ICD-11 COD assessments),
//! including Site, Unique ID, Deceased Demographics, Frame A (Part 1 & Part 2),
//! Frame B (Surgery, Autopsy, Manner of Death, External Cause, Fetal/Infant,
//! Maternal), UCOD, Coded By, Date Coded, and verification digest.

use std::fmt::Write as _;

use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MccdConditionLine {
    pub condition_text: String,
    pub icd_code: Option<String>,
    pub interval_iso_or_text: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct WhoMccdCertificateData {
    // Identification & Site Header
    pub unique_case_id: String,
    pub death_registration_id: Option<String>,
    pub project_id: String,
    pub project_name: Option<String>,
    pub site_code: String,
    pub site_name: Option<String>,
    pub station_id: Option<String>,

    // Deceased Demographics
    pub deceased_name: Option<String>,
    pub sex: Option<String>,
    pub date_of_birth: Option<String>,
    pub date_of_death: Option<String>,
    pub age_at_death: Option<String>,
    pub place_of_death: Option<String>,

    // Frame A: Medical data (Part 1 & Part 2)
    pub part1_lines: Vec<MccdConditionLine>,
    pub part2_conditions: Vec<MccdConditionLine>,

    // Frame B: Other medical data
    pub surgery_performed: Option<String>,
    pub surgery_date: Option<String>,
    pub surgery_reason: Option<String>,
    pub autopsy_requested: Option<String>,
    pub autopsy_findings_used: Option<String>,
    pub manner_of_death: Option<String>,
    pub external_cause_date: Option<String>,
    pub external_cause_description: Option<String>,
    pub external_cause_place: Option<String>,
    pub fetal_or_infant_summary: Option<String>,
    pub maternal_pregnancy_summary: Option<String>,

    // UCOD & Certification Footer
    pub icd_version: String,
    pub doris_computed_ucod: Option<String>,
    pub final_certified_ucod: String,
    pub va_cause_bucket: Option<String>,
    pub coder_remarks: Option<String>,
    pub coded_by_name: String,
    pub coded_by_id: String,
    pub coded_by_role: Option<String>,
    pub coded_at: String,
    pub certificate_digest: Option<String>,
}

/// Convert an ISO 8601 duration (`P65Y`, `P3M`, `P14D`, `PT6H`, `PT30M`) into human-readable text.
pub fn format_iso_duration(raw: &str) -> String {
    let s = raw.trim();
    if s.is_empty() {
        return String::new();
    }
    if !s.starts_with('P') {
        return s.to_string();
    }
    let body = &s[1..];
    let (date_part, time_part) = match body.split_once('T') {
        Some((d, t)) => (d, Some(t)),
        None => (body, None),
    };

    let mut parts = Vec::new();
    let mut num_buf = String::new();
    for ch in date_part.chars() {
        if ch.is_ascii_digit() || ch == '.' {
            num_buf.push(ch);
        } else {
            if !num_buf.is_empty() {
                let unit = match ch {
                    'Y' => {
                        if num_buf == "1" {
                            "year"
                        } else {
                            "years"
                        }
                    }
                    'M' => {
                        if num_buf == "1" {
                            "month"
                        } else {
                            "months"
                        }
                    }
                    'W' => {
                        if num_buf == "1" {
                            "week"
                        } else {
                            "weeks"
                        }
                    }
                    'D' => {
                        if num_buf == "1" {
                            "day"
                        } else {
                            "days"
                        }
                    }
                    _ => "",
                };
                if !unit.is_empty() {
                    parts.push(format!("{num_buf} {unit}"));
                }
                num_buf.clear();
            }
        }
    }

    if let Some(tpart) = time_part {
        num_buf.clear();
        for ch in tpart.chars() {
            if ch.is_ascii_digit() || ch == '.' {
                num_buf.push(ch);
            } else if !num_buf.is_empty() {
                let unit = match ch {
                    'H' => {
                        if num_buf == "1" {
                            "hour"
                        } else {
                            "hours"
                        }
                    }
                    'M' => {
                        if num_buf == "1" {
                            "minute"
                        } else {
                            "minutes"
                        }
                    }
                    'S' => {
                        if num_buf == "1" {
                            "second"
                        } else {
                            "seconds"
                        }
                    }
                    _ => "",
                };
                if !unit.is_empty() {
                    parts.push(format!("{num_buf} {unit}"));
                }
                num_buf.clear();
            }
        }
    }

    if parts.is_empty() {
        s.to_string()
    } else {
        parts.join(" ")
    }
}

fn yes_no_unknown_label(val: Option<&Value>) -> Option<String> {
    match val?.as_i64()? {
        1 => Some("Yes".to_string()),
        0 => Some("No".to_string()),
        9 => Some("Unknown".to_string()),
        _ => None,
    }
}

fn manner_of_death_label(val: Option<&Value>) -> Option<String> {
    match val?.as_i64()? {
        0 => Some("Disease".to_string()),
        1 => Some("Accident".to_string()),
        2 => Some("Intentional self-harm".to_string()),
        3 => Some("Assault".to_string()),
        4 => Some("Legal intervention".to_string()),
        5 => Some("War".to_string()),
        6 => Some("Could not be determined".to_string()),
        7 => Some("Pending investigation".to_string()),
        9 => Some("Unknown".to_string()),
        _ => None,
    }
}

fn sex_label(val: Option<&Value>) -> Option<String> {
    match val?.as_i64() {
        Some(1) => Some("Male".to_string()),
        Some(2) => Some("Female".to_string()),
        Some(9) => Some("Undetermined".to_string()),
        _ => val?.as_str().map(|s| s.to_string()),
    }
}

impl WhoMccdCertificateData {
    /// Populate Frame A and Frame B fields from a normalized WHO DORIS `DeathCertificate` JSON object
    /// (matching `app/services/doris_certificate.py` and `docs/policy/doris-certificate-rules.md`).
    pub fn apply_doris_certificate_json(&mut self, cert: &Value) {
        if let Some(ver) = cert.get("ICDVersion").and_then(Value::as_str) {
            let minor = cert.get("ICDMinorVersion").and_then(Value::as_str).unwrap_or("");
            self.icd_version = if minor.is_empty() {
                ver.to_string()
            } else {
                format!("{ver} ({minor})")
            };
        }

        if let Some(admin) = cert.get("AdministrativeData") {
            if self.date_of_birth.is_none() {
                self.date_of_birth = admin
                    .get("DateBirth")
                    .and_then(Value::as_str)
                    .map(str::to_string);
            }
            if self.date_of_death.is_none() {
                self.date_of_death = admin
                    .get("DateDeath")
                    .and_then(Value::as_str)
                    .map(str::to_string);
            }
            if self.sex.is_none() {
                self.sex = sex_label(admin.get("Sex"));
            }
            if self.age_at_death.is_none() {
                self.age_at_death = admin
                    .get("EstimatedAge")
                    .and_then(Value::as_str)
                    .map(format_iso_duration);
            }
        }

        if let Some(part1) = cert.get("Part1").and_then(Value::as_array) {
            self.part1_lines.clear();
            for line in part1 {
                if let Some(conds) = line.get("Conditions").and_then(Value::as_array) {
                    if conds.is_empty() {
                        continue;
                    }
                    let texts: Vec<String> = conds
                        .iter()
                        .filter_map(|c| c.get("Text").and_then(Value::as_str))
                        .map(str::to_string)
                        .collect();
                    let codes: Vec<String> = conds
                        .iter()
                        .filter_map(|c| c.get("Code").and_then(Value::as_str))
                        .map(str::to_string)
                        .collect();
                    let interval = conds
                        .first()
                        .and_then(|c| c.get("Interval"))
                        .and_then(Value::as_str)
                        .map(format_iso_duration);
                    self.part1_lines.push(MccdConditionLine {
                        condition_text: texts.join("; "),
                        icd_code: if codes.is_empty() {
                            None
                        } else {
                            Some(codes.join(" / "))
                        },
                        interval_iso_or_text: interval,
                    });
                }
            }
        }

        if let Some(part2_conds) = cert
            .get("Part2")
            .and_then(|p| p.get("Conditions"))
            .and_then(Value::as_array)
        {
            self.part2_conditions.clear();
            for c in part2_conds {
                let text = c
                    .get("Text")
                    .and_then(Value::as_str)
                    .unwrap_or("")
                    .to_string();
                if text.is_empty() {
                    continue;
                }
                self.part2_conditions.push(MccdConditionLine {
                    condition_text: text,
                    icd_code: c.get("Code").and_then(Value::as_str).map(str::to_string),
                    interval_iso_or_text: c
                        .get("Interval")
                        .and_then(Value::as_str)
                        .map(format_iso_duration),
                });
            }
        }

        if let Some(surg) = cert.get("Surgery") {
            self.surgery_performed = yes_no_unknown_label(surg.get("WasPerformed"));
            self.surgery_date = surg.get("Date").and_then(Value::as_str).map(str::to_string);
            self.surgery_reason = surg
                .get("Reason")
                .and_then(Value::as_str)
                .map(str::to_string);
        }

        if let Some(aut) = cert.get("Autopsy") {
            self.autopsy_requested = yes_no_unknown_label(aut.get("WasRequested"));
            self.autopsy_findings_used = yes_no_unknown_label(aut.get("Findings"));
        }

        if let Some(man) = cert.get("MannerOfDeath") {
            self.manner_of_death = manner_of_death_label(man.get("MannerOfDeath"));
            self.external_cause_date = man
                .get("DateOfExternalCauseOrPoisoning")
                .and_then(Value::as_str)
                .map(str::to_string);
            self.external_cause_description = man
                .get("DescriptionExternalCause")
                .and_then(Value::as_str)
                .map(str::to_string);
        }

        if let Some(fetal) = cert.get("FetalOrInfantDeath") {
            let mut items = Vec::new();
            if let Some(sb) = yes_no_unknown_label(fetal.get("Stillborn")) {
                items.push(format!("Stillborn: {sb}"));
            }
            if let Some(bw) = fetal.get("BirthWeight").and_then(Value::as_i64) {
                items.push(format!("Birth weight: {bw} g"));
            }
            if let Some(pw) = fetal.get("PregnancyWeeks").and_then(Value::as_i64) {
                items.push(format!("Completed weeks: {pw}"));
            }
            if let Some(am) = fetal.get("AgeMother").and_then(Value::as_i64) {
                items.push(format!("Mother age: {am} y"));
            }
            if !items.is_empty() {
                self.fetal_or_infant_summary = Some(items.join(" | "));
            }
        } else {
            self.fetal_or_infant_summary =
                Some("Not applicable (not a fetal or infant death)".to_string());
        }

        if let Some(mat) = cert.get("MaternalDeath") {
            let wp = yes_no_unknown_label(mat.get("WasPregnant")).unwrap_or_else(|| "—".to_string());
            let contrib = yes_no_unknown_label(mat.get("PregnancyContribute"))
                .unwrap_or_else(|| "—".to_string());
            self.maternal_pregnancy_summary =
                Some(format!("Was pregnant: {wp} | Contributed to death: {contrib}"));
        } else if self.sex.as_deref() == Some("Male") {
            self.maternal_pregnancy_summary =
                Some("Not applicable (selected sex is Male)".to_string());
        }
    }
}

fn pdf_escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 8);
    for ch in text.chars() {
        match ch {
            '(' => out.push_str("\\("),
            ')' => out.push_str("\\)"),
            '\\' => out.push_str("\\\\"),
            // Replace non-Latin1 characters with ASCII fallback for standard Type1 Helvetica
            '\u{2013}' | '\u{2014}' => out.push('-'),
            '\u{2022}' => out.push('*'),
            c if (c as u32) >= 32 && (c as u32) <= 255 => out.push(c),
            _ => out.push('?'),
        }
    }
    out
}

fn truncate_str(s: &str, max_chars: usize) -> String {
    if s.chars().count() <= max_chars {
        s.to_string()
    } else {
        let mut t: String = s.chars().take(max_chars.saturating_sub(3)).collect();
        t.push_str("...");
        t
    }
}

struct PdfCanvas {
    stream: String,
}

impl PdfCanvas {
    fn new() -> Self {
        Self {
            stream: String::with_capacity(8192),
        }
    }

    fn rect_fill_stroke(&mut self, x: f32, y: f32, w: f32, h: f32, fill_gray: f32, stroke_gray: f32) {
        let _ = writeln!(
            self.stream,
            "q {fill_gray:.2} g {stroke_gray:.2} G 0.6 w {x:.2} {y:.2} {w:.2} {h:.2} re B Q"
        );
    }

    fn rect_stroke(&mut self, x: f32, y: f32, w: f32, h: f32, stroke_gray: f32, line_width: f32) {
        let _ = writeln!(
            self.stream,
            "q {stroke_gray:.2} G {line_width:.2} w {x:.2} {y:.2} {w:.2} {h:.2} re S Q"
        );
    }

    fn line(&mut self, x1: f32, y1: f32, x2: f32, y2: f32, stroke_gray: f32, line_width: f32) {
        let _ = writeln!(
            self.stream,
            "q {stroke_gray:.2} G {line_width:.2} w {x1:.2} {y1:.2} m {x2:.2} {y2:.2} l S Q"
        );
    }

    fn text(&mut self, font: &str, size: f32, x: f32, y: f32, gray: f32, content: &str) {
        let escaped = pdf_escape(content);
        let _ = writeln!(
            self.stream,
            "BT /{font} {size:.1} Tf {gray:.2} g {x:.2} {y:.2} Td ({escaped}) Tj ET"
        );
    }
}

/// Render a standalone A4 PDF document (`595.28 x 841.89 pt`) in the WHO International Form of
/// Medical Certificate of Cause of Death (MCCD) layout.
pub fn render_who_mccd_pdf(data: &WhoMccdCertificateData) -> Result<Vec<u8>> {
    let mut c = PdfCanvas::new();
    let left = 32.0_f32;
    let width = 531.0_f32;
    let right = left + width;

    // -----------------------------------------------------------------------
    // 1. Top WHO / DigitVA Title & Station / Site / Unique ID Header Box
    // -----------------------------------------------------------------------
    c.rect_fill_stroke(left, 766.0, width, 46.0, 0.14, 0.14);
    c.text(
        "F2",
        11.0,
        left + 10.0,
        796.0,
        1.0,
        "INTERNATIONAL FORM OF MEDICAL CERTIFICATE OF CAUSE OF DEATH (WHO STANDARD)",
    );
    let site_display = match &data.site_name {
        Some(name) if !name.is_empty() => format!("{} ({})", name, data.site_code),
        _ => data.site_code.clone(),
    };
    let proj_display = match &data.project_name {
        Some(name) if !name.is_empty() => format!("{} ({})", name, data.project_id),
        _ => data.project_id.clone(),
    };
    c.text(
        "F1",
        8.5,
        left + 10.0,
        782.0,
        0.92,
        &format!(
            "Site / Facility: {}    |    Project: {}    |    Classification: {}",
            truncate_str(&site_display, 34),
            truncate_str(&proj_display, 26),
            data.icd_version
        ),
    );
    c.text(
        "F3",
        8.0,
        left + 10.0,
        771.0,
        0.92,
        &format!(
            "Unique Case ID: {}   |   Death Reg ID: {}   |   Station: {}",
            truncate_str(&data.unique_case_id, 42),
            data.death_registration_id.as_deref().unwrap_or("-"),
            data.station_id.as_deref().unwrap_or("LOCAL-PHC")
        ),
    );

    // -----------------------------------------------------------------------
    // 2. Administrative & Deceased Identification Block
    // -----------------------------------------------------------------------
    c.rect_fill_stroke(left, 748.0, width, 16.0, 0.90, 0.50);
    c.text(
        "F2",
        9.0,
        left + 8.0,
        753.0,
        0.05,
        "ADMINISTRATIVE & DECEASED IDENTIFICATION DATA",
    );
    c.rect_stroke(left, 696.0, width, 52.0, 0.50, 0.6);
    c.line(left, 722.0, right, 722.0, 0.70, 0.5);
    c.line(left + 185.0, 696.0, left + 185.0, 748.0, 0.70, 0.5);
    c.line(left + 360.0, 696.0, left + 360.0, 748.0, 0.70, 0.5);

    // Row 1: Deceased Name | Sex | Age at Death
    c.text("F2", 7.5, left + 6.0, 738.0, 0.35, "Deceased Name");
    c.text(
        "F1",
        9.0,
        left + 6.0,
        727.0,
        0.0,
        &truncate_str(data.deceased_name.as_deref().unwrap_or("Not recorded"), 30),
    );

    c.text("F2", 7.5, left + 191.0, 738.0, 0.35, "Sex");
    c.text(
        "F1",
        9.0,
        left + 191.0,
        727.0,
        0.0,
        data.sex.as_deref().unwrap_or("Not stated"),
    );

    c.text("F2", 7.5, left + 366.0, 738.0, 0.35, "Age at Death");
    c.text(
        "F1",
        9.0,
        left + 366.0,
        727.0,
        0.0,
        data.age_at_death.as_deref().unwrap_or("Not stated"),
    );

    // Row 2: Date of Birth | Date of Death | Place of Death / PHC Site
    c.text("F2", 7.5, left + 6.0, 712.0, 0.35, "Date of Birth");
    c.text(
        "F1",
        9.0,
        left + 6.0,
        701.0,
        0.0,
        data.date_of_birth.as_deref().unwrap_or("Not stated"),
    );

    c.text("F2", 7.5, left + 191.0, 712.0, 0.35, "Date of Death");
    c.text(
        "F1",
        9.0,
        left + 191.0,
        701.0,
        0.0,
        data.date_of_death.as_deref().unwrap_or("Not stated"),
    );

    c.text("F2", 7.5, left + 366.0, 712.0, 0.35, "Place of Death / Site");
    c.text(
        "F1",
        9.0,
        left + 366.0,
        701.0,
        0.0,
        &truncate_str(
            data.place_of_death
                .as_deref()
                .unwrap_or(&data.site_code),
            28,
        ),
    );

    // -----------------------------------------------------------------------
    // 3. Frame A: Medical Data — Part 1 & Part 2 (WHO MCCD Table)
    // -----------------------------------------------------------------------
    c.rect_fill_stroke(left, 674.0, width, 18.0, 0.90, 0.50);
    c.text(
        "F2",
        9.0,
        left + 8.0,
        680.0,
        0.05,
        "FRAME A: MEDICAL DATA - PART 1 & PART 2 (CAUSE OF DEATH)",
    );

    // Column Header Row
    let col_code_x = left + 340.0;
    let col_int_x = left + 430.0;
    c.rect_fill_stroke(left, 654.0, width, 20.0, 0.96, 0.50);
    c.line(col_code_x, 654.0, col_code_x, 674.0, 0.50, 0.5);
    c.line(col_int_x, 654.0, col_int_x, 674.0, 0.50, 0.5);
    c.text(
        "F2",
        8.0,
        left + 6.0,
        661.0,
        0.15,
        "1. Report disease or condition directly leading to death on line a",
    );
    c.text("F2", 8.0, col_code_x + 6.0, 661.0, 0.15, "ICD Code");
    c.text(
        "F2",
        8.0,
        col_int_x + 6.0,
        661.0,
        0.15,
        "Time from onset to death",
    );

    // Part 1 Lines a, b, c, d
    let line_labels = [
        ("a.", "Immediate cause (directly leading to death)"),
        ("b.", "Due to (or as a consequence of):"),
        ("c.", "Due to (or as a consequence of):"),
        ("d.", "Due to (or as a consequence of):"),
    ];
    let mut y_cursor = 654.0_f32;
    let row_h = 30.0_f32;
    for (idx, (letter, subtitle)) in line_labels.iter().enumerate() {
        let row_bottom = y_cursor - row_h;
        c.rect_stroke(left, row_bottom, width, row_h, 0.50, 0.5);
        c.line(col_code_x, row_bottom, col_code_x, y_cursor, 0.65, 0.5);
        c.line(col_int_x, row_bottom, col_int_x, y_cursor, 0.65, 0.5);

        c.text("F2", 8.5, left + 6.0, y_cursor - 11.0, 0.10, letter);
        c.text("F1", 7.0, left + 20.0, y_cursor - 11.0, 0.40, subtitle);

        if let Some(item) = data.part1_lines.get(idx) {
            c.text(
                "F2",
                9.0,
                left + 20.0,
                row_bottom + 7.0,
                0.0,
                &truncate_str(&item.condition_text, 58),
            );
            c.text(
                "F3",
                9.0,
                col_code_x + 6.0,
                row_bottom + 11.0,
                0.0,
                &truncate_str(item.icd_code.as_deref().unwrap_or("-"), 14),
            );
            c.text(
                "F1",
                8.5,
                col_int_x + 6.0,
                row_bottom + 11.0,
                0.0,
                &truncate_str(item.interval_iso_or_text.as_deref().unwrap_or("-"), 18),
            );
        } else {
            c.text("F1", 8.5, left + 20.0, row_bottom + 7.0, 0.55, "-");
        }
        y_cursor = row_bottom;
    }

    // Part 2 Box (Other significant conditions contributing to death)
    let part2_h = 54.0_f32;
    let part2_bottom = y_cursor - part2_h;
    c.rect_stroke(left, part2_bottom, width, part2_h, 0.50, 0.5);
    c.line(col_code_x, part2_bottom, col_code_x, y_cursor, 0.65, 0.5);
    c.line(col_int_x, part2_bottom, col_int_x, y_cursor, 0.65, 0.5);
    c.text(
        "F2",
        8.0,
        left + 6.0,
        y_cursor - 12.0,
        0.15,
        "2. Other significant conditions contributing to death (time intervals in brackets):",
    );

    if data.part2_conditions.is_empty() {
        c.text("F1", 8.5, left + 12.0, y_cursor - 28.0, 0.50, "None recorded");
    } else {
        for (i, cond) in data.part2_conditions.iter().take(2).enumerate() {
            let line_y = y_cursor - 26.0 - (i as f32 * 14.0);
            c.text(
                "F1",
                8.5,
                left + 12.0,
                line_y,
                0.0,
                &truncate_str(&cond.condition_text, 58),
            );
            c.text(
                "F3",
                8.5,
                col_code_x + 6.0,
                line_y,
                0.0,
                &truncate_str(cond.icd_code.as_deref().unwrap_or("-"), 14),
            );
            c.text(
                "F1",
                8.5,
                col_int_x + 6.0,
                line_y,
                0.0,
                &truncate_str(cond.interval_iso_or_text.as_deref().unwrap_or("-"), 18),
            );
        }
    }

    // -----------------------------------------------------------------------
    // 4. Frame B: Other Medical Data
    // -----------------------------------------------------------------------
    let frame_b_top = part2_bottom - 6.0;
    c.rect_fill_stroke(left, frame_b_top - 18.0, width, 18.0, 0.90, 0.50);
    c.text(
        "F2",
        9.0,
        left + 8.0,
        frame_b_top - 12.0,
        0.05,
        "FRAME B: OTHER MEDICAL DATA",
    );

    let fb_body_top = frame_b_top - 18.0;
    let fb_h = 114.0_f32;
    let fb_bottom = fb_body_top - fb_h;
    c.rect_stroke(left, fb_bottom, width, fb_h, 0.50, 0.6);
    c.line(left + 265.0, fb_bottom, left + 265.0, fb_body_top, 0.70, 0.5);
    c.line(left, fb_body_top - 38.0, right, fb_body_top - 38.0, 0.70, 0.5);
    c.line(left, fb_body_top - 76.0, right, fb_body_top - 76.0, 0.70, 0.5);

    // Row 1 Left: Surgery | Right: Autopsy
    c.text(
        "F2",
        7.5,
        left + 6.0,
        fb_body_top - 11.0,
        0.35,
        "Surgery performed within last 4 weeks?",
    );
    let surg_str = format!(
        "{}   Date: {}   Reason: {}",
        data.surgery_performed.as_deref().unwrap_or("Not stated"),
        data.surgery_date.as_deref().unwrap_or("-"),
        truncate_str(data.surgery_reason.as_deref().unwrap_or("-"), 22)
    );
    c.text("F1", 8.5, left + 6.0, fb_body_top - 26.0, 0.0, &surg_str);

    c.text(
        "F2",
        7.5,
        left + 271.0,
        fb_body_top - 11.0,
        0.35,
        "Was an autopsy requested?",
    );
    let aut_str = format!(
        "{}   |   Findings used in certification: {}",
        data.autopsy_requested.as_deref().unwrap_or("Not stated"),
        data.autopsy_findings_used.as_deref().unwrap_or("-")
    );
    c.text("F1", 8.5, left + 271.0, fb_body_top - 26.0, 0.0, &aut_str);

    // Row 2 Left: Manner of death | Right: External cause / poisoning
    c.text("F2", 7.5, left + 6.0, fb_body_top - 49.0, 0.35, "Manner of Death");
    c.text(
        "F1",
        8.5,
        left + 6.0,
        fb_body_top - 64.0,
        0.0,
        data.manner_of_death.as_deref().unwrap_or("Disease / Natural"),
    );

    c.text(
        "F2",
        7.5,
        left + 271.0,
        fb_body_top - 49.0,
        0.35,
        "External Cause / Injury Date & Description",
    );
    let ext_str = match (&data.external_cause_date, &data.external_cause_description) {
        (None, None) => "Not applicable".to_string(),
        (d, desc) => format!(
            "{} - {}",
            d.as_deref().unwrap_or("-"),
            truncate_str(desc.as_deref().unwrap_or("-"), 32)
        ),
    };
    c.text("F1", 8.5, left + 271.0, fb_body_top - 64.0, 0.0, &ext_str);

    // Row 3 Left: Fetal or infant death | Right: Maternal / Pregnancy
    c.text(
        "F2",
        7.5,
        left + 6.0,
        fb_body_top - 87.0,
        0.35,
        "Fetal or Infant Death (< 1 year)",
    );
    c.text(
        "F1",
        8.0,
        left + 6.0,
        fb_body_top - 102.0,
        0.0,
        &truncate_str(
            data.fetal_or_infant_summary
                .as_deref()
                .unwrap_or("Not applicable"),
            48,
        ),
    );

    c.text(
        "F2",
        7.5,
        left + 271.0,
        fb_body_top - 87.0,
        0.35,
        "Information on Pregnancy (Female)",
    );
    c.text(
        "F1",
        8.0,
        left + 271.0,
        fb_body_top - 102.0,
        0.0,
        &truncate_str(
            data.maternal_pregnancy_summary
                .as_deref()
                .unwrap_or("Not applicable"),
            48,
        ),
    );

    // -----------------------------------------------------------------------
    // 5. Underlying Cause of Death (UCOD) & Medical Officer Certification Box
    // -----------------------------------------------------------------------
    let cert_top = fb_bottom - 8.0;
    c.rect_fill_stroke(left, cert_top - 18.0, width, 18.0, 0.14, 0.14);
    c.text(
        "F2",
        9.0,
        left + 8.0,
        cert_top - 12.0,
        1.0,
        "UNDERLYING CAUSE OF DEATH (UCOD) & MEDICAL OFFICER CERTIFICATION",
    );

    let cert_body_top = cert_top - 18.0;
    let cert_h = 160.0_f32;
    let cert_bottom = cert_body_top - cert_h;
    c.rect_stroke(left, cert_bottom, width, cert_h, 0.30, 0.8);

    // Highlighted Final Certified UCOD Banner
    c.rect_fill_stroke(left + 8.0, cert_body_top - 42.0, width - 16.0, 34.0, 0.95, 0.60);
    c.text(
        "F2",
        8.0,
        left + 14.0,
        cert_body_top - 19.0,
        0.25,
        "FINAL CERTIFIED UNDERLYING CAUSE OF DEATH (UCOD):",
    );
    c.text(
        "F2",
        10.5,
        left + 14.0,
        cert_body_top - 34.0,
        0.0,
        &truncate_str(&data.final_certified_ucod, 78),
    );

    // DORIS Computed UCOD & VA Cause Bucket
    c.text(
        "F2",
        8.0,
        left + 10.0,
        cert_body_top - 56.0,
        0.30,
        "DORIS Selection Rule UCOD:",
    );
    c.text(
        "F1",
        8.5,
        left + 135.0,
        cert_body_top - 56.0,
        0.0,
        &truncate_str(
            data.doris_computed_ucod
                .as_deref()
                .unwrap_or("N/A (Direct / Simple COD Mode)"),
            68,
        ),
    );

    c.text(
        "F2",
        8.0,
        left + 10.0,
        cert_body_top - 71.0,
        0.30,
        "WHO VA Cause Bucket / Remarks:",
    );
    let bucket_and_remark = match (&data.va_cause_bucket, &data.coder_remarks) {
        (Some(b), Some(r)) if !r.is_empty() => format!("{b} | Remarks: {r}"),
        (Some(b), _) => b.clone(),
        (None, Some(r)) if !r.is_empty() => r.clone(),
        _ => "None".to_string(),
    };
    c.text(
        "F1",
        8.5,
        left + 150.0,
        cert_body_top - 71.0,
        0.0,
        &truncate_str(&bucket_and_remark, 65),
    );

    c.line(
        left + 8.0,
        cert_body_top - 80.0,
        right - 8.0,
        cert_body_top - 80.0,
        0.70,
        0.5,
    );

    // Mandatory Audit Block: Site, Coded By, Date Coded, Unique ID, Signature
    c.text(
        "F2",
        8.5,
        left + 10.0,
        cert_body_top - 96.0,
        0.10,
        &format!(
            "Coded By: {} ({})",
            truncate_str(&data.coded_by_name, 34),
            truncate_str(&data.coded_by_id, 28)
        ),
    );
    c.text(
        "F1",
        8.5,
        left + 10.0,
        cert_body_top - 111.0,
        0.10,
        &format!(
            "Designation / Role: {}   |   Site: {}",
            data.coded_by_role
                .as_deref()
                .unwrap_or("Medical Officer (PHC)"),
            truncate_str(&site_display, 34)
        ),
    );
    c.text(
        "F2",
        8.5,
        left + 10.0,
        cert_body_top - 126.0,
        0.10,
        &format!(
            "Date & Time Coded: {}   |   Unique ID: {}",
            data.coded_at,
            truncate_str(&data.unique_case_id, 42)
        ),
    );
    c.text(
        "F3",
        7.5,
        left + 10.0,
        cert_body_top - 144.0,
        0.35,
        &format!(
            "Verification Digest (SHA-256): {}",
            data.certificate_digest
                .as_deref()
                .unwrap_or("OFFLINE-STATION-CERTIFIED")
        ),
    );

    // Signature / Stamp Box on the right
    c.rect_stroke(right - 165.0, cert_bottom + 12.0, 155.0, 62.0, 0.50, 0.5);
    c.text(
        "F1",
        7.5,
        right - 157.0,
        cert_bottom + 20.0,
        0.35,
        "Medical Officer Signature & PHC Stamp",
    );

    // assemble valid PDF 1.4 byte buffer
    Ok(assemble_single_page_pdf(&c.stream))
}

fn assemble_single_page_pdf(content_stream: &str) -> Vec<u8> {
    let stream_bytes = content_stream.as_bytes();
    let mut pdf = Vec::with_capacity(stream_bytes.len() + 2048);
    let mut offsets = Vec::with_capacity(8);

    pdf.extend_from_slice(b"%PDF-1.4\n%\xE2\xE3\xCF\xD3\n");

    let push_obj = |pdf: &mut Vec<u8>, offsets: &mut Vec<usize>, id: usize, body: &[u8]| {
        offsets.push(pdf.len());
        let header = format!("{id} 0 obj\n");
        pdf.extend_from_slice(header.as_bytes());
        pdf.extend_from_slice(body);
        pdf.extend_from_slice(b"\nendobj\n");
    };

    // 1: Catalog
    push_obj(
        &mut pdf,
        &mut offsets,
        1,
        b"<< /Type /Catalog /Pages 2 0 R >>",
    );
    // 2: Pages
    push_obj(
        &mut pdf,
        &mut offsets,
        2,
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    );
    // 3: Page (A4: 595.28 x 841.89)
    push_obj(
        &mut pdf,
        &mut offsets,
        3,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.28 841.89] /Resources << /Font << /F1 4 0 R /F2 5 0 R /F3 6 0 R >> >> /Contents 7 0 R >>",
    );
    // 4: Font F1 (Helvetica)
    push_obj(
        &mut pdf,
        &mut offsets,
        4,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    );
    // 5: Font F2 (Helvetica-Bold)
    push_obj(
        &mut pdf,
        &mut offsets,
        5,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    );
    // 6: Font F3 (Courier)
    push_obj(
        &mut pdf,
        &mut offsets,
        6,
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
    );
    // 7: Content stream
    let mut stream_obj = format!("<< /Length {} >>\nstream\n", stream_bytes.len()).into_bytes();
    stream_obj.extend_from_slice(stream_bytes);
    stream_obj.extend_from_slice(b"endstream");
    push_obj(&mut pdf, &mut offsets, 7, &stream_obj);

    let xref_offset = pdf.len();
    let total_objs = offsets.len() + 1;
    let mut xref = format!("xref\n0 {total_objs}\n0000000000 65535 f \n");
    for off in &offsets {
        let _ = writeln!(xref, "{off:010} 00000 n ");
    }
    pdf.extend_from_slice(xref.as_bytes());

    let trailer = format!(
        "trailer\n<< /Size {total_objs} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    );
    pdf.extend_from_slice(trailer.as_bytes());
    pdf
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn formats_iso_durations_for_mccd() {
        assert_eq!(format_iso_duration("P65Y"), "65 years");
        assert_eq!(format_iso_duration("P1Y"), "1 year");
        assert_eq!(format_iso_duration("P14D"), "14 days");
        assert_eq!(format_iso_duration("PT2H"), "2 hours");
        assert_eq!(format_iso_duration("PT45M"), "45 minutes");
    }

    #[test]
    fn renders_valid_who_mccd_pdf_with_site_coder_date_and_unique_id() {
        let mut cert_data = WhoMccdCertificateData {
            unique_case_id: "uuid:8f41c2d0-2026-4a11-9b01-00142".to_string(),
            death_registration_id: Some("UNSW01-NC0101-D00142".to_string()),
            project_id: "UNSW01".to_string(),
            project_name: Some("National VA Surveillance".to_string()),
            site_code: "UNSW01NC0101".to_string(),
            site_name: Some("PHC Ballabgarh NC01".to_string()),
            station_id: Some("STN-NC01-01".to_string()),
            deceased_name: Some("Ramesh Kumar".to_string()),
            place_of_death: Some("Home - Village Chhainsa".to_string()),
            icd_version: "ICD11 (2026-01)".to_string(),
            doris_computed_ucod: Some("5A11 - Type 2 diabetes mellitus".to_string()),
            final_certified_ucod: "5A11 - Type 2 diabetes mellitus".to_string(),
            va_cause_bucket: Some("Diabetes mellitus".to_string()),
            coder_remarks: Some("Consistent history of longstanding diabetes and acute MI".to_string()),
            coded_by_name: "Dr. Ananya Sharma".to_string(),
            coded_by_id: "test.coder.nc01@gmail.com".to_string(),
            coded_by_role: Some("Medical Officer (PHC)".to_string()),
            coded_at: "2026-10-20 21:15 IST".to_string(),
            certificate_digest: Some("sha256:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08".to_string()),
            ..Default::default()
        };

        let doris_json = json!({
            "ICDVersion": "ICD11",
            "ICDMinorVersion": "2026-01",
            "AdministrativeData": {
                "DateBirth": "1960-04-12",
                "DateDeath": "2026-10-15",
                "Sex": 1,
                "EstimatedAge": "P66Y"
            },
            "Part1": [
                {"Conditions": [{"Text": "Acute myocardial infarction", "Code": "BA41", "Interval": "PT2H"}]},
                {"Conditions": [{"Text": "Coronary atherosclerosis", "Code": "BA51", "Interval": "P5Y"}]},
                {"Conditions": [{"Text": "Type 2 diabetes mellitus", "Code": "5A11", "Interval": "P15Y"}]}
            ],
            "Part2": {
                "Conditions": [{"Text": "Essential hypertension", "Code": "BA00", "Interval": "P10Y"}]
            },
            "Surgery": {"WasPerformed": 0},
            "Autopsy": {"WasRequested": 0},
            "MannerOfDeath": {"MannerOfDeath": 0}
        });

        cert_data.apply_doris_certificate_json(&doris_json);
        let pdf_bytes = render_who_mccd_pdf(&cert_data).expect("PDF rendering should succeed");

        assert!(pdf_bytes.starts_with(b"%PDF-1.4\n"));
        assert!(pdf_bytes.ends_with(b"%%EOF\n"));
        let pdf_text = String::from_utf8_lossy(&pdf_bytes);
        assert!(pdf_text.contains("INTERNATIONAL FORM OF MEDICAL CERTIFICATE OF CAUSE OF DEATH"));
        assert!(pdf_text.contains(r"PHC Ballabgarh NC01 \(UNSW01NC0101\)"));
        assert!(pdf_text.contains("uuid:8f41c2d0-2026-4a11-9b01-00142"));
        assert!(pdf_text.contains(r"Dr. Ananya Sharma \(test.coder.nc01@gmail.com\)"));
        assert!(pdf_text.contains("2026-10-20 21:15 IST"));
        assert!(pdf_text.contains("5A11 - Type 2 diabetes mellitus"));
    }
}
