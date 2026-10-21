use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::Path;

const EMBEDDED_VA_CAUSE_LIST_CSV: &str =
    include_str!("../../../../resource/who_2022_va_cause_list_icd10_icd11.csv");
const EMBEDDED_VOCAB_SEED_CSV: &str =
    include_str!("../../../../resource/icd_search_vocabulary_seed.csv");
const EMBEDDED_VA_DEFINITIONS_JSON: &str =
    include_str!("../../../../resource/va_cause_definitions_who_2022.json");

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VaCauseDefinitionRecord {
    pub va_code: String,
    pub title: String,
    pub definition_html: String,
    #[serde(default)]
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IcdSearchItem {
    pub code: String,
    pub title: String,
    pub label: String,
    pub chapter_code: Option<String>,
    pub chapter_title: Option<String>,
    pub block_code: Option<String>,
    pub block_title: Option<String>,
    pub matched_synonym: Option<String>,
    pub va_code: Option<String>,
    pub va_title: Option<String>,
}

pub fn ensure_catalog_seeded(
    conn: &Connection,
    resource_dir: Option<&Path>,
) -> rusqlite::Result<()> {
    let existing_count: i64 = conn.query_row(
        "SELECT COUNT(*) FROM cat_va_causes",
        [],
        |row| row.get(0),
    )?;
    if existing_count > 0 {
        return Ok(());
    }

    let tx = conn.unchecked_transaction()?;

    // 1. Parse WHO 2022 VA definitions JSON
    let mut def_map: HashMap<String, (String, String)> = HashMap::new();
    if let Ok(defs) = serde_json::from_str::<Vec<VaCauseDefinitionRecord>>(EMBEDDED_VA_DEFINITIONS_JSON) {
        for d in defs {
            def_map.insert(d.va_code, (d.definition_html, d.source));
        }
    }

    // 2. Seed `cat_va_causes` and primary ICD-10 / ICD-11 codes from `who_2022_va_cause_list_icd10_icd11.csv`
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_reader(EMBEDDED_VA_CAUSE_LIST_CSV.as_bytes());

    for result in rdr.records() {
        let Ok(rec) = result else { continue };
        let group = rec.get(0).unwrap_or("").trim();
        let va_code = rec.get(1).unwrap_or("").trim();
        let va_title = rec.get(2).unwrap_or("").trim();
        let icd10_codes = rec.get(3).unwrap_or("").trim();
        let icd11_codes = rec.get(4).unwrap_or("").trim();
        if va_code.is_empty() {
            continue;
        }
        let (def_html, def_source) = def_map
            .get(va_code)
            .cloned()
            .unwrap_or_else(|| (String::new(), "WHO 2022 VA Standard".to_string()));

        tx.execute(
            "INSERT OR REPLACE INTO cat_va_causes (
                va_code, va_group, va_title, icd10_codes, icd11_codes, definition_html, source
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                va_code,
                group,
                va_title,
                icd10_codes,
                icd11_codes,
                def_html,
                def_source
            ],
        )?;

        for code_part in icd10_codes.split([';', ',']) {
            let primary = code_part
                .split('-')
                .next()
                .unwrap_or("")
                .trim()
                .to_uppercase();
            if !primary.is_empty() {
                tx.execute(
                    "INSERT OR IGNORE INTO cat_icd_entries (
                        classification, code, title, chapter_title, va_code, va_title, synonyms
                     ) VALUES ('icd10', ?1, ?2, ?3, ?4, ?5, '')",
                    params![primary, va_title, group, va_code, va_title],
                )?;
            }
        }

        for code_part in icd11_codes.split([';', ',']) {
            let primary = code_part
                .split('-')
                .next()
                .unwrap_or("")
                .trim()
                .to_uppercase();
            if !primary.is_empty() {
                tx.execute(
                    "INSERT OR IGNORE INTO cat_icd_entries (
                        classification, code, title, chapter_title, va_code, va_title, synonyms
                     ) VALUES ('icd11', ?1, ?2, ?3, ?4, ?5, '')",
                    params![primary, va_title, group, va_code, va_title],
                )?;
            }
        }
    }

    // 3. Seed clinician shorthand synonyms from `icd_search_vocabulary_seed.csv`
    let mut vocab_rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .from_reader(EMBEDDED_VOCAB_SEED_CSV.as_bytes());
    let mut syn_accum: HashMap<(String, String), Vec<String>> = HashMap::new();
    for result in vocab_rdr.records() {
        let Ok(rec) = result else { continue };
        let term = rec.get(0).unwrap_or("").trim();
        let classification = rec.get(2).unwrap_or("").trim().to_lowercase();
        let code = rec.get(3).unwrap_or("").trim().to_uppercase();
        if term.is_empty() || code.is_empty() {
            continue;
        }
        syn_accum
            .entry((classification, code))
            .or_default()
            .push(term.to_string());
    }

    for ((classification, code), terms) in syn_accum {
        let joined = terms.join(" ; ");
        let first_title = terms.first().cloned().unwrap_or_else(|| code.clone());
        tx.execute(
            "INSERT INTO cat_icd_entries (
                classification, code, title, chapter_title, va_code, va_title, synonyms
             ) VALUES (?1, ?2, ?3, NULL, NULL, NULL, ?4)
             ON CONFLICT(classification, code) DO UPDATE SET
                synonyms = CASE
                    WHEN cat_icd_entries.synonyms = '' THEN excluded.synonyms
                    ELSE cat_icd_entries.synonyms || ' ; ' || excluded.synonyms
                END",
            params![classification, code, first_title, joined],
        )?;
    }

    // 4. Optional: if `icd11_mms_2026_01_hierarchy.csv` exists in `resource_dir`, load leaf/category codes
    if let Some(dir) = resource_dir {
        let hier_path = dir.join("icd11_mms_2026_01_hierarchy.csv");
        if hier_path.exists() {
            if let Ok(mut hier_rdr) = csv::ReaderBuilder::new().has_headers(true).from_path(&hier_path) {
                for result in hier_rdr.records().take(6000) {
                    let Ok(rec) = result else { continue };
                    let code = rec.get(2).unwrap_or("").trim();
                    let title = rec.get(4).unwrap_or("").trim();
                    let chapter_no = rec.get(7).unwrap_or("").trim();
                    if code.is_empty() || title.is_empty() {
                        continue;
                    }
                    tx.execute(
                        "INSERT INTO cat_icd_entries (
                            classification, code, title, chapter_code, chapter_title, va_code, va_title, synonyms
                         ) VALUES ('icd11', ?1, ?2, ?3, NULL, NULL, NULL, '')
                         ON CONFLICT(classification, code) DO UPDATE SET
                            title = excluded.title,
                            chapter_code = COALESCE(cat_icd_entries.chapter_code, excluded.chapter_code)",
                        params![code, title, chapter_no],
                    )?;
                }
            }
        }
    }

    // Populate FTS5 index
    tx.execute(
        "INSERT INTO cat_icd_fts (rowid, classification, code, title, synonyms, va_title)
         SELECT id, classification, code, title, synonyms, COALESCE(va_title, '')
         FROM cat_icd_entries",
        [],
    )?;

    tx.commit()?;
    Ok(())
}

pub fn search_icd_catalog(
    conn: &Connection,
    classification: &str,
    query: &str,
    limit: usize,
) -> rusqlite::Result<Vec<IcdSearchItem>> {
    let q = query.trim();
    if q.is_empty() {
        let mut stmt = conn.prepare(
            "SELECT code, title, chapter_code, chapter_title, va_code, va_title, synonyms
             FROM cat_icd_entries
             WHERE classification = ?1
             ORDER BY code ASC
             LIMIT ?2",
        )?;
        let rows = stmt
            .query_map(params![classification, limit as i64], map_icd_row(None))?
            .filter_map(Result::ok)
            .collect();
        return Ok(rows);
    }

    let like_pattern = format!("%{}%", q.to_lowercase());
    let prefix_pattern = format!("{}%", q.to_uppercase());
    let mut stmt = conn.prepare(
        "SELECT code, title, chapter_code, chapter_title, va_code, va_title, synonyms
         FROM cat_icd_entries
         WHERE classification = ?1
           AND (UPPER(code) LIKE ?2 OR LOWER(title) LIKE ?3 OR LOWER(synonyms) LIKE ?3 OR LOWER(COALESCE(va_title, '')) LIKE ?3)
         ORDER BY CASE WHEN UPPER(code) = UPPER(?4) THEN 0 WHEN UPPER(code) LIKE ?2 THEN 1 ELSE 2 END, code ASC
         LIMIT ?5",
    )?;
    let rows = stmt
        .query_map(
            params![classification, prefix_pattern, like_pattern, q, limit as i64],
            map_icd_row(Some(q)),
        )?
        .filter_map(Result::ok)
        .collect();
    Ok(rows)
}

fn map_icd_row<'a>(
    query: Option<&'a str>,
) -> impl FnMut(&rusqlite::Row<'_>) -> rusqlite::Result<IcdSearchItem> + 'a {
    let q_lower = query.map(|s| s.to_lowercase());
    move |row: &rusqlite::Row<'_>| {
        let code: String = row.get(0)?;
        let title: String = row.get(1)?;
        let chapter_code: Option<String> = row.get(2)?;
        let chapter_title: Option<String> = row.get(3)?;
        let va_code: Option<String> = row.get(4)?;
        let va_title: Option<String> = row.get(5)?;
        let synonyms: String = row.get(6)?;

        let matched_synonym = q_lower.as_ref().and_then(|ql| {
            synonyms
                .split(';')
                .map(str::trim)
                .find(|s| !s.is_empty() && s.to_lowercase().contains(ql))
                .map(ToString::to_string)
        });

        Ok(IcdSearchItem {
            label: format!("{code} — {title}"),
            code,
            title,
            chapter_code,
            chapter_title,
            block_code: None,
            block_title: None,
            matched_synonym,
            va_code,
            va_title,
        })
    }
}

pub fn lookup_va_definition_for_icd(
    conn: &Connection,
    classification: &str,
    code: &str,
) -> rusqlite::Result<serde_json::Value> {
    let norm_code = code.trim().to_uppercase();
    let entry: Option<(Option<String>, Option<String>, String)> = conn
        .query_row(
            "SELECT va_code, va_title, title FROM cat_icd_entries
             WHERE classification = ?1 AND UPPER(code) = ?2
             LIMIT 1",
            params![classification.to_lowercase(), norm_code],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()?;

    let va_code_opt = entry.and_then(|(vc, _, _)| vc).or_else(|| {
        // Fallback prefix match in cat_va_causes
        let col = if classification.eq_ignore_ascii_case("icd10") {
            "icd10_codes"
        } else {
            "icd11_codes"
        };
        let sql = format!(
            "SELECT va_code FROM cat_va_causes WHERE UPPER({col}) LIKE ?1 LIMIT 1"
        );
        conn.query_row(&sql, params![format!("%{norm_code}%")], |r| r.get(0))
            .optional()
            .ok()
            .flatten()
    });

    if let Some(vc) = va_code_opt {
        if let Some((va_code, va_group, va_title, icd10_codes, icd11_codes, def_html, source)) = conn
            .query_row(
                "SELECT va_code, va_group, va_title, icd10_codes, icd11_codes, definition_html, source
                 FROM cat_va_causes WHERE va_code = ?1",
                params![vc],
                |r| {
                    Ok((
                        r.get::<_, String>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, String>(2)?,
                        r.get::<_, String>(3)?,
                        r.get::<_, String>(4)?,
                        r.get::<_, String>(5)?,
                        r.get::<_, String>(6)?,
                    ))
                },
            )
            .optional()?
        {
            return Ok(serde_json::json!({
                "found": true,
                "icd_code": norm_code,
                "classification": classification,
                "code": norm_code,
                "va_code": va_code,
                "title": va_title,
                "definition_html": def_html,
                "definition": {
                    "va_code": va_code,
                    "va_group": va_group,
                    "title": va_title,
                    "icd10_codes": icd10_codes,
                    "icd11_codes": icd11_codes,
                    "definition_html": def_html,
                    "source": source
                }
            }));
        }
    }

    Ok(serde_json::json!({
        "found": false,
        "classification": classification,
        "code": norm_code,
        "definition": null
    }))
}
