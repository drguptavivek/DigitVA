//! In-process WHO ICD-11 2.6.0 + DORIS 1.2.0 for the station's `icd11_doris` coding mode
//! (digitva-r7gr, docs/policy/offline-phc-desktop-edition.md).
//!
//! One engine per process, started lazily on a background thread the first time coding needs
//! it (opening a case workspace or calling an ICD-11 route): loading the WHO assemblies takes
//! several seconds and holds about 0.5-1 GB, so it never runs on a request thread and never
//! runs in `icd10` mode. Routes mirror the server's `app/routes/api/doris_clinical.py`; while
//! the engine is starting or cannot start they answer the server's own unavailable contract
//! (`503 {schema_version: 1, error: {code: "WHO_API_UNAVAILABLE", message}}`).

use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::Instant;

use axum::{
    body::Bytes,
    extract::{Path, Query, State},
    http::StatusCode,
    response::Response,
};
use digitva_db::CODING_MODE_ICD11_DORIS;
use digitva_icd11::{
    DEFAULT_ICD11_RELEASE, Icd11Engine, Icd11Error, Icd11RuntimeConfig, SearchOptions,
    expected_expression_uri_with, postcoordination_availability, processor_result_digest,
    strip_who_search_markup, valid_subtree_uris, validate_processor_envelope,
};
use serde_json::{Map, Value, json};

use crate::{AppState, SearchQuery, json_with_csrf};

/// Stands in for the server's `DORIS_WHO_IMAGE_DIGEST` in result digests. Station envelopes are
/// advisory: the server reprocesses an `icd11_doris` certificate with the engine it pins.
pub const WHO_ENGINE_DIGEST: &str = "rust-dll-2.6.0";
const MAX_JSON_BYTES: usize = 32 * 1024;
const CODING_SEARCH_LIMIT: usize = 25;
const PREPARING: &str = "Preparing ICD-11… try again in a few seconds.";
const UNAVAILABLE: &str = "WHO ICD-11 service unavailable.";
const DORIS_DIR: &str = "DORIS_v2.1_1.2.0";

enum EngineState {
    NotStarted,
    Starting,
    Ready(Arc<Icd11Engine>),
    Failed,
}

/// The station's single shared WHO engine and where its bundle lives.
pub struct Icd11Service {
    bundle_dir: Option<PathBuf>,
    data_dir: Option<PathBuf>,
    state: Mutex<EngineState>,
}

impl Icd11Service {
    /// `bundle_dir` holds `ICD-API.dll` + `DigitvaIcd11Bridge.dll`; `data_dir` the 2026-01
    /// index and DORIS rules (default: `<bundle>/data`, then `<bundle>/../data`, then
    /// `<bundle>/../icdapi_bundle/data`, the vendored bootstrapper's layouts).
    pub fn new(bundle_dir: Option<PathBuf>, data_dir: Option<PathBuf>) -> Self {
        Self {
            bundle_dir,
            data_dir,
            state: Mutex::new(EngineState::NotStarted),
        }
    }

    /// `DIGITVA_ICD11_BUNDLE_DIR` / `DIGITVA_ICD11_DATA_DIR`.
    pub fn from_env() -> Self {
        let dir = |key| {
            std::env::var(key)
                .ok()
                .filter(|s: &String| !s.trim().is_empty())
                .map(PathBuf::from)
        };
        Self::new(
            dir("DIGITVA_ICD11_BUNDLE_DIR"),
            dir("DIGITVA_ICD11_DATA_DIR"),
        )
    }

    /// Starts the engine on a background thread unless it was already started. A failed start
    /// stays failed until the station restarts (installing the bundle needs a restart anyway).
    pub fn ensure_started(self: &Arc<Self>) {
        {
            let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner());
            if !matches!(*state, EngineState::NotStarted) {
                return;
            }
            *state = EngineState::Starting;
        }
        let service = Arc::clone(self);
        std::thread::spawn(move || {
            let started = Instant::now();
            // The WHO bridge `chdir`s into the bundle while it starts; the station resolves
            // relative paths (web assets, `../app/static`) against its own working directory.
            let cwd = std::env::current_dir().ok();
            let result = service
                .runtime_config()
                .and_then(|cfg| Icd11Engine::init_global(cfg).map_err(|e| e.to_string()));
            if let Some(cwd) = cwd {
                let _ = std::env::set_current_dir(cwd);
            }
            let next = match result {
                Ok(engine) => {
                    eprintln!(
                        "ICD-11 engine ready in {} ms",
                        started.elapsed().as_millis()
                    );
                    EngineState::Ready(engine)
                }
                Err(detail) => {
                    eprintln!("ICD-11 engine unavailable: {detail}");
                    EngineState::Failed
                }
            };
            *service.state.lock().unwrap_or_else(|e| e.into_inner()) = next;
        });
    }

    /// Never calls `Icd11RuntimeConfig::discover()`: that downloads the bundle when it is
    /// missing, and the station must stay offline. The process-wide engine ignores the config
    /// once one exists, so a missing bundle is refused here, before `init_global`.
    fn runtime_config(&self) -> Result<Icd11RuntimeConfig, String> {
        let bundle_dir = self
            .bundle_dir
            .clone()
            .ok_or("DIGITVA_ICD11_BUNDLE_DIR is not set")?;
        if !bundle_dir.join("ICD-API.dll").is_file()
            || !bundle_dir.join("DigitvaIcd11Bridge.dll").is_file()
        {
            return Err(format!("no WHO ICD-API bundle in {}", bundle_dir.display()));
        }
        let data_dir = match &self.data_dir {
            Some(dir) => Some(dir.clone()),
            None => {
                let parent = bundle_dir.parent().map(PathBuf::from).unwrap_or_default();
                [
                    bundle_dir.join("data"),
                    parent.join("data"),
                    parent.join("icdapi_bundle").join("data"),
                ]
                .into_iter()
                .find(|dir| dir.join(DORIS_DIR).is_dir())
            }
        }
        .filter(|dir| dir.join(DORIS_DIR).is_dir())
        .ok_or("no WHO 2026-01 / DORIS data directory (set DIGITVA_ICD11_DATA_DIR)")?;
        Ok(Icd11RuntimeConfig {
            bundle_dir,
            data_dir,
            bind_url: "http://127.0.0.1:0".to_string(),
            default_release: DEFAULT_ICD11_RELEASE.to_string(),
        })
    }

    /// The ready engine, or the message a caller shows while it is starting or unavailable.
    pub fn engine(&self) -> Result<Arc<Icd11Engine>, &'static str> {
        match &*self.state.lock().unwrap_or_else(|e| e.into_inner()) {
            EngineState::Ready(engine) => Ok(Arc::clone(engine)),
            EngineState::NotStarted | EngineState::Starting => Err(PREPARING),
            EngineState::Failed => Err(UNAVAILABLE),
        }
    }

    /// `not_started` | `starting` | `ready` | `unavailable`.
    pub fn status(&self) -> &'static str {
        match &*self.state.lock().unwrap_or_else(|e| e.into_inner()) {
            EngineState::NotStarted => "not_started",
            EngineState::Starting => "starting",
            EngineState::Ready(_) => "ready",
            EngineState::Failed => "unavailable",
        }
    }
}

/// Whether case `va_sid` is coded in `icd11_doris` (its project's station coding mode).
fn doris_mode(state: &AppState, va_sid: &str) -> bool {
    state.db.coding_mode_for_va(va_sid).as_deref() == Some(CODING_MODE_ICD11_DORIS)
}

/// Starts the engine when a case opens for coding in `icd11_doris`, so it is warm by the time
/// the coder reaches the certificate.
pub(crate) fn warm_for_workspace(state: &AppState, va_sid: &str, mode: &str) {
    if mode != "view" && doris_mode(state, va_sid) {
        state.icd11.ensure_started();
    }
}

/// `GET /api/v1/icd11/status`: `{status, release}`; read-only, starts nothing.
pub(crate) async fn handle_status(State(state): State<AppState>) -> Response {
    let body = json!({ "status": state.icd11.status(), "release": DEFAULT_ICD11_RELEASE });
    json_with_csrf(&state, StatusCode::OK, body)
}

/// The server's DORIS error body: `{schema_version: 1, error: {code, message, fields?}}`.
fn doris_error(
    state: &AppState,
    status: StatusCode,
    code: &str,
    message: &str,
    fields: Option<Value>,
) -> Response {
    let mut error = json!({ "code": code, "message": message });
    if let Some(fields) = fields {
        error["fields"] = fields;
    }
    json_with_csrf(
        state,
        status,
        json!({ "schema_version": 1, "error": error }),
    )
}

fn unavailable(state: &AppState, message: &str) -> Response {
    doris_error(
        state,
        StatusCode::SERVICE_UNAVAILABLE,
        "WHO_API_UNAVAILABLE",
        message,
        None,
    )
}

/// The case exists and the station codes in `icd11_doris` (the server's `_clinical_context`);
/// then the engine is started. `icd10` never reaches the engine.
fn doris_context(state: &AppState, va_sid: &str) -> Result<(), Response> {
    if !state.db.has_va_submission(va_sid) {
        return Err(doris_error(
            state,
            StatusCode::NOT_FOUND,
            "NOT_FOUND",
            "Submission not found.",
            None,
        ));
    }
    if !doris_mode(state, va_sid) {
        return Err(doris_error(
            state,
            StatusCode::CONFLICT,
            "DORIS_NOT_ENABLED",
            "DORIS entry is not enabled for this project.",
            None,
        ));
    }
    state.icd11.ensure_started();
    Ok(())
}

fn ready_engine(state: &AppState) -> Result<Arc<Icd11Engine>, Response> {
    state
        .icd11
        .engine()
        .map_err(|message| unavailable(state, message))
}

/// Runs a blocking engine call (FFI into .NET) off the async runtime.
async fn blocking<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> Option<T> {
    tokio::task::spawn_blocking(f).await.ok()
}

/// A JSON object of at most 32 KB (the server's `_json_object`).
fn json_object(body: &Bytes) -> Option<Map<String, Value>> {
    if body.len() > MAX_JSON_BYTES {
        return None;
    }
    serde_json::from_slice::<Value>(body)
        .ok()?
        .as_object()
        .cloned()
}

fn schema_v1(payload: &Map<String, Value>) -> bool {
    payload.get("schema_version").and_then(Value::as_i64) == Some(1)
}

fn keys_are(payload: &Map<String, Value>, allowed: &[&str]) -> bool {
    payload.keys().all(|key| allowed.contains(&key.as_str()))
}

/// WHO display text: tags stripped, common entities decoded (the server's `_plain`).
fn plain(value: &Value, max_chars: usize) -> String {
    let value = match value {
        Value::Object(obj) => obj
            .get("@value")
            .or_else(|| obj.get("label"))
            .unwrap_or(&Value::Null),
        other => other,
    };
    let text = value.as_str().unwrap_or("");
    let decoded = strip_who_search_markup(text)
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&amp;", "&");
    decoded.trim().chars().take(max_chars).collect()
}

fn first_text<'a>(entity: &'a Value, keys: &[&str]) -> &'a Value {
    keys.iter()
        .map(|key| &entity[*key])
        .find(|value| !value.is_null() && value.as_str() != Some(""))
        .unwrap_or(&Value::Null)
}

/// One `/terms` item per WHO search entity (the server's `search_terms`).
fn term_items(raw: &Value, limit: usize) -> Result<(Vec<Value>, bool), Icd11Error> {
    let entities = raw["destinationEntities"].as_array().ok_or_else(|| {
        Icd11Error::MalformedJson("WHO search response was malformed".to_string())
    })?;
    let mut items = Vec::new();
    for entity in entities {
        let code = first_text(entity, &["theCode", "code"])
            .as_str()
            .unwrap_or("");
        let uri = first_text(entity, &["id", "uri", "@id"])
            .as_str()
            .unwrap_or("");
        let title = plain(first_text(entity, &["title", "titleWithoutCodes"]), 2000);
        if code.is_empty() || uri.is_empty() || title.is_empty() {
            continue;
        }
        let matching = match first_text(entity, &["matchingPVs", "matchingText"]) {
            Value::Array(parts) => Value::String(
                parts
                    .iter()
                    .filter_map(Value::as_str)
                    .collect::<Vec<_>>()
                    .join(" "),
            ),
            other => other.clone(),
        };
        let matching_text = Some(plain(&matching, 2000))
            .filter(|t| !t.is_empty())
            .unwrap_or_else(|| title.clone());
        let (available, availability) =
            postcoordination_availability(&entity["postcoordinationAvailability"]);
        items.push(json!({
            "code": code,
            "title": title,
            "uri": uri,
            "release": DEFAULT_ICD11_RELEASE,
            "matching_text": matching_text,
            "postcoordination": available,
            "postcoordination_availability": availability,
            "related_maternal": entity["hasMaternalChapterLink"] == Value::Bool(true),
            "related_perinatal": entity["hasPerinatalChapterLink"] == Value::Bool(true),
            "has_coding_note": entity["hasCodingNote"] == Value::Bool(true),
        }));
        if items.len() == limit {
            break;
        }
    }
    let chopped = match &raw["resultChopped"] {
        Value::Bool(b) => *b,
        Value::Null => false,
        _ => true,
    };
    let truncated = chopped || entities.len() > items.len();
    Ok((items, truncated))
}

fn who_search(
    engine: &Icd11Engine,
    query: &str,
    subtrees: Option<Vec<String>>,
) -> Result<Value, Icd11Error> {
    let options = SearchOptions {
        subtrees_filter: subtrees,
        use_flexisearch: false,
        flat_results: true,
        highlighting_enabled: true,
        medical_coding_mode: true,
        include_postcoordination: true,
    };
    engine.search(&format!("{}%", query.trim()), &options, None)
}

/// A request the WHO boundary refuses (PII, bad subtree) is the caller's input, not an outage.
fn is_input_error(err: &Icd11Error) -> bool {
    matches!(
        err,
        Icd11Error::PiiBoundaryViolation { .. } | Icd11Error::Certificate(_)
    )
}

/// `POST /api/v1/doris-clinical/terms/:va_sid`.
pub(crate) async fn handle_terms(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    body: Bytes,
) -> Response {
    if let Err(resp) = doris_context(&state, &va_sid) {
        return resp;
    }
    let invalid = || {
        doris_error(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_INPUT",
            "The terminology request is invalid.",
            None,
        )
    };
    let Some(payload) = json_object(&body) else {
        return invalid();
    };
    let query = payload.get("query").and_then(Value::as_str).unwrap_or("");
    let query_len = query.trim().chars().count();
    let limit = match payload.get("limit") {
        None => Some(20),
        Some(v) => v
            .as_u64()
            .filter(|n| (1..=20).contains(n))
            .map(|n| n as usize),
    };
    let subtrees: Option<Option<Vec<String>>> = match payload.get("subtree_uris") {
        None | Some(Value::Null) => Some(None),
        Some(Value::Array(list)) => list
            .iter()
            .map(|v| v.as_str().map(String::from))
            .collect::<Option<Vec<_>>>()
            .filter(|list| valid_subtree_uris(Some(list)))
            .map(Some),
        Some(_) => None,
    };
    let (Some(limit), Some(subtrees)) = (limit, subtrees) else {
        return invalid();
    };
    if !keys_are(
        &payload,
        &["schema_version", "query", "limit", "cursor", "subtree_uris"],
    ) || !schema_v1(&payload)
        || !(2..=80).contains(&query_len)
        || payload.get("cursor").is_some_and(|c| !c.is_null())
    {
        return invalid();
    }
    let engine = match ready_engine(&state) {
        Ok(engine) => engine,
        Err(resp) => return resp,
    };
    let query = query.to_string();
    let result = blocking(move || {
        who_search(&engine, &query, subtrees).and_then(|raw| term_items(&raw, limit))
    })
    .await;
    match result {
        Some(Ok((items, truncated))) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({ "schema_version": 1, "items": items, "truncated": truncated, "next_cursor": null }),
        ),
        Some(Err(err)) if is_input_error(&err) => invalid(),
        _ => unavailable(&state, UNAVAILABLE),
    }
}

/// The server's `search_context_from_entity`: badges for a directly entered stem code.
fn search_context(entity: &Value) -> Result<Map<String, Value>, Icd11Error> {
    let scales = match &entity["postcoordinationScale"] {
        Value::Null => Vec::new(),
        Value::Array(list) => list.clone(),
        _ => {
            return Err(Icd11Error::MalformedJson(
                "WHO postcoordination scale was malformed".to_string(),
            ));
        }
    };
    let required = scales.iter().any(|scale| {
        matches!(&scale["requiredPostcoordination"], Value::Bool(true))
            || scale["requiredPostcoordination"].as_str() == Some("true")
    });
    let truthy = |v: &Value| {
        !matches!(v, Value::Null | Value::Bool(false))
            && v.as_str() != Some("")
            && v.as_array().is_none_or(|a| !a.is_empty())
    };
    let mut out = Map::new();
    out.insert("postcoordination".into(), json!(!scales.is_empty()));
    out.insert(
        "postcoordination_availability".into(),
        json!(if required {
            2
        } else if scales.is_empty() {
            0
        } else {
            1
        }),
    );
    out.insert(
        "related_maternal".into(),
        json!(truthy(&entity["relatedEntitiesInMaternalChapter"])),
    );
    out.insert(
        "related_perinatal".into(),
        json!(truthy(&entity["relatedEntitiesInPerinatalChapter"])),
    );
    out.insert(
        "has_coding_note".into(),
        json!(truthy(&entity["codingNote"])),
    );
    Ok(out)
}

/// `{code, title, uri, release, postcoordination, ...}` for an exact WHO code or expression, or
/// `None` when WHO does not know it (the server's `_codeinfo_item`).
fn codeinfo_item(engine: &Icd11Engine, code: &str) -> Result<Option<Value>, Icd11Error> {
    let Some(info) = engine.codeinfo(code, None)? else {
        return Ok(None);
    };
    if info["code"].as_str() != Some(code) {
        return Ok(None);
    }
    let uri = expected_expression_uri_with(code, DEFAULT_ICD11_RELEASE, |c, r| {
        engine.codeinfo(c, Some(r)).ok().flatten()
    });
    let Some(uri) = uri else { return Ok(None) };
    let Some(stem_path) = info["stemId"]
        .as_str()
        .and_then(|s| s.strip_prefix("http://id.who.int"))
        .filter(|p| p.starts_with('/'))
    else {
        return Ok(None);
    };
    let (status, body) = engine.raw_request("GET", stem_path, None, None)?;
    if !(200..300).contains(&status) {
        return Err(Icd11Error::UpstreamUnavailable {
            status,
            body: String::new(),
        });
    }
    let entity: Value =
        serde_json::from_str(&body).map_err(|e| Icd11Error::MalformedJson(e.to_string()))?;
    if !entity.is_object() {
        return Ok(None);
    }
    let mut title = plain(first_text(&info, &["title", "label"]), 2000);
    if title.is_empty() {
        title = plain(first_text(&entity, &["title", "label"]), 2000);
    }
    if title.is_empty() {
        return Ok(None);
    }
    let mut item = json!({
        "code": code,
        "title": title,
        "uri": uri,
        "release": DEFAULT_ICD11_RELEASE,
        "postcoordination": false,
    });
    if !code.contains('&') && !code.contains('/') {
        item.as_object_mut()
            .unwrap()
            .extend(search_context(&entity)?);
    }
    Ok(Some(item))
}

fn bounded_text(payload: &Map<String, Value>, key: &str, max: usize) -> Option<String> {
    let text = payload.get(key)?.as_str()?.trim();
    (!text.is_empty() && text.chars().count() <= max).then(|| text.to_string())
}

/// `POST /api/v1/doris-clinical/codeinfo/:va_sid`.
pub(crate) async fn handle_codeinfo(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    body: Bytes,
) -> Response {
    if let Err(resp) = doris_context(&state, &va_sid) {
        return resp;
    }
    let payload = json_object(&body)
        .filter(|p| p.len() == 2 && keys_are(p, &["schema_version", "code"]) && schema_v1(p));
    let Some(code) = payload.as_ref().and_then(|p| bounded_text(p, "code", 128)) else {
        return doris_error(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_INPUT",
            "The code request is invalid.",
            None,
        );
    };
    let engine = match ready_engine(&state) {
        Ok(engine) => engine,
        Err(resp) => return resp,
    };
    match blocking(move || codeinfo_item(&engine, &code)).await {
        Some(Ok(Some(item))) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({ "schema_version": 1, "item": item }),
        ),
        Some(Ok(None)) => doris_error(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "CODE_NOT_FOUND",
            "Select a valid ICD-11 code.",
            None,
        ),
        Some(Err(err)) if is_input_error(&err) => doris_error(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "CODE_NOT_FOUND",
            "Select a valid ICD-11 code.",
            None,
        ),
        _ => unavailable(&state, UNAVAILABLE),
    }
}

/// `POST /api/v1/doris-clinical/selection-check/:va_sid`.
pub(crate) async fn handle_selection_check(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    body: Bytes,
) -> Response {
    if let Err(resp) = doris_context(&state, &va_sid) {
        return resp;
    }
    let payload = json_object(&body).filter(|p| {
        p.len() == 3 && keys_are(p, &["schema_version", "code", "uri"]) && schema_v1(p)
    });
    let fields = payload
        .as_ref()
        .and_then(|p| Some((bounded_text(p, "code", 128)?, bounded_text(p, "uri", 2048)?)));
    let Some((code, uri)) = fields else {
        return doris_error(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_INPUT",
            "The selected ICD-11 code is invalid.",
            None,
        );
    };
    let engine = match ready_engine(&state) {
        Ok(engine) => engine,
        Err(resp) => return resp,
    };
    let mismatch = || {
        doris_error(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_SELECTION",
            "The selected code does not match its WHO URI.",
            None,
        )
    };
    match blocking(move || codeinfo_item(&engine, &code)).await {
        Some(Ok(Some(item))) if item["uri"].as_str() == Some(uri.as_str()) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({ "schema_version": 1, "item": item }),
        ),
        Some(Ok(_)) => mismatch(),
        Some(Err(err)) if is_input_error(&err) => mismatch(),
        _ => unavailable(&state, UNAVAILABLE),
    }
}

/// `POST /api/v1/doris-clinical/{postcoordination,postcoordination-options,hierarchy,related,details}/:va_sid`.
/// Not ported to the station yet: the picker shows its own "unavailable" text for these panels
/// and plain code selection still works.
pub(crate) async fn handle_guidance(
    State(state): State<AppState>,
    Path((op, va_sid)): Path<(String, String)>,
) -> Response {
    if !matches!(
        op.as_str(),
        "postcoordination" | "postcoordination-options" | "hierarchy" | "related" | "details"
    ) {
        return json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": "API route not found", "code": "not_found" }),
        );
    }
    if let Err(resp) = doris_context(&state, &va_sid) {
        return resp;
    }
    unavailable(&state, "WHO ICD-11 guidance is unavailable.")
}

/// The opaque proof the station hands back with a processing result: both digests, so a final
/// save can tell a changed certificate from changed results (the server signs the same pair).
fn process_token(processed: &Value) -> String {
    format!(
        "{}.{}",
        processed["certificate_digest"].as_str().unwrap_or(""),
        processed["result_digest"].as_str().unwrap_or("")
    )
}

/// Runs DORIS + CoDEdit on `{schema_version, client_revision, certificate}`.
async fn process(
    engine: Arc<Icd11Engine>,
    payload: Value,
) -> Option<Result<Value, digitva_icd11::DorisCertificateError>> {
    blocking(move || {
        engine
            .process_certificate(&payload, None, WHO_ENGINE_DIGEST)
            .map(|mut processed| {
                processed["process_token"] = Value::String(process_token(&processed));
                processed
            })
    })
    .await
}

/// `POST /api/v1/doris-clinical/process/:va_sid`: processes the current certificate; saves nothing.
pub(crate) async fn handle_process(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    body: Bytes,
) -> Response {
    let Some(payload) = json_object(&body) else {
        return doris_error(
            &state,
            StatusCode::BAD_REQUEST,
            "MALFORMED_JSON",
            "A JSON process request is required.",
            None,
        );
    };
    if !matches!(
        payload.get("role").and_then(Value::as_str),
        Some("coder" | "reviewer")
    ) {
        return doris_error(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_ROLE",
            "Role must be coder or reviewer.",
            None,
        );
    }
    if let Err(resp) = doris_context(&state, &va_sid) {
        return resp;
    }
    let engine = match ready_engine(&state) {
        Ok(engine) => engine,
        Err(resp) => return resp,
    };
    let field = |key: &str| payload.get(key).cloned().unwrap_or(Value::Null);
    let request = json!({
        "schema_version": field("schema_version"),
        "client_revision": field("client_revision"),
        "certificate": field("certificate"),
    });
    match process(engine, request).await {
        Some(Ok(processed)) => json_with_csrf(&state, StatusCode::OK, processed),
        Some(Err(err)) => {
            let fields: Vec<Value> = err
                .fields
                .iter()
                .map(|f| json!({ "path": f.path, "message": f.message }))
                .collect();
            doris_error(
                &state,
                StatusCode::UNPROCESSABLE_ENTITY,
                "INVALID_INPUT",
                "The DORIS certificate is invalid.",
                Some(Value::Array(fields)),
            )
        }
        None => unavailable(&state, UNAVAILABLE),
    }
}

/// `GET /api/v1/icd11/coding-search/:va_sid`: the server's `{icd_code, icd_to_display, title,
/// linearization_uri}` rows from the WHO engine in `icd11_doris`; the local catalogue in `icd10`
/// mode (unchanged) and while the engine is starting or unavailable.
pub(crate) async fn handle_coding_search(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Query(q): Query<SearchQuery>,
) -> Response {
    let query = q.q.unwrap_or_default();
    if doris_mode(&state, &va_sid) {
        state.icd11.ensure_started();
        if let Ok(engine) = state.icd11.engine() {
            if query.trim().chars().count() < 2 {
                return json_with_csrf(&state, StatusCode::OK, json!([]));
            }
            let q = query.clone();
            match blocking(move || who_search(&engine, &q, None)).await {
                Some(Ok(raw)) => {
                    let rows: Vec<Value> = raw["destinationEntities"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|entity| {
                            let code = entity["theCode"].as_str().filter(|c| !c.is_empty())?;
                            let uri = entity["id"].as_str().filter(|u| !u.is_empty())?;
                            let title = plain(&entity["title"], 2000);
                            (!title.is_empty()).then(|| {
                                json!({
                                    "icd_code": code,
                                    "icd_to_display": format!("{code} {title}"),
                                    "title": title,
                                    "linearization_uri": uri,
                                })
                            })
                        })
                        .take(CODING_SEARCH_LIMIT)
                        .collect();
                    return json_with_csrf(&state, StatusCode::OK, Value::Array(rows));
                }
                Some(Err(err)) if is_input_error(&err) => {
                    return json_with_csrf(&state, StatusCode::OK, json!([]));
                }
                _ => {}
            }
        }
    }
    json_with_csrf(
        &state,
        StatusCode::OK,
        Value::Array(state.db.search_icd("icd11", &query)),
    )
}

fn coding_refusal(
    state: &AppState,
    status: StatusCode,
    code: &str,
    message: &str,
    processing: Option<Value>,
) -> Response {
    let mut body = json!({ "error": message, "code": code });
    if let Some(processing) = processing {
        body["processing"] = processing;
    }
    json_with_csrf(state, status, body)
}

/// A final save in `icd11_doris` (coder or reviewer): the server's `verify_doris_submission`
/// done by reprocessing, since the engine is local. Returns the body to save, with the
/// certificate and both envelopes replaced by the engine's own (codes carry their WHO URIs) and
/// the proof fields dropped. Refusals as the server's: 422 `invalid_doris`, 409
/// `DORIS_PROCESS_EXPIRED` / `DORIS_CERTIFICATE_CHANGED` (with `processing`) /
/// `DORIS_PROCESS_MISMATCH`, 422 `final_blocked` for a conclusive code WHO does not know,
/// 503 `who_unavailable`. Other modes pass the body through untouched.
pub(crate) async fn verify_doris_final(state: &AppState, va_sid: &str, body: Value) -> Result<Value, Response> {
    if !doris_mode(state, va_sid) {
        return Ok(body);
    }
    let invalid = |message: &str| {
        coding_refusal(
            state,
            StatusCode::UNPROCESSABLE_ENTITY,
            "invalid_doris",
            message,
            None,
        )
    };
    let Value::Object(mut fields) = body else {
        return Err(invalid("A JSON object is required."));
    };
    let submitted_doris =
        validate_processor_envelope("doris", fields.get("doris_result").unwrap_or(&Value::Null));
    let submitted_codedit = validate_processor_envelope(
        "codedit",
        fields.get("codedit_result").unwrap_or(&Value::Null),
    );
    let (submitted_doris, submitted_codedit) = match (submitted_doris, submitted_codedit) {
        (Ok(d), Ok(c)) => (d, c),
        (Err(message), _) | (_, Err(message)) => return Err(invalid(&message)),
    };
    state.icd11.ensure_started();
    let engine = match state.icd11.engine() {
        Ok(engine) => engine,
        Err(message) => {
            return Err(coding_refusal(
                state,
                StatusCode::SERVICE_UNAVAILABLE,
                "who_unavailable",
                message,
                None,
            ));
        }
    };
    let revision = match fields.get("doris_client_revision") {
        Some(Value::String(s)) => s
            .trim()
            .parse::<i64>()
            .map(Value::from)
            .unwrap_or(Value::Null),
        Some(v @ Value::Number(_)) => v.clone(),
        _ => json!(0),
    };
    let request = json!({
        "schema_version": 1,
        "client_revision": revision,
        "certificate": fields.get("doris_certificate").cloned().unwrap_or(Value::Null),
    });
    let fresh = match process(Arc::clone(&engine), request).await {
        Some(Ok(fresh)) => fresh,
        Some(Err(err)) => {
            let message = err
                .fields
                .first()
                .map(|f| f.message.as_str())
                .unwrap_or("The DORIS certificate is invalid.");
            return Err(invalid(message));
        }
        None => {
            return Err(coding_refusal(
                state,
                StatusCode::SERVICE_UNAVAILABLE,
                "who_unavailable",
                UNAVAILABLE,
                None,
            ));
        }
    };
    let token = fields
        .get("doris_process_token")
        .and_then(Value::as_str)
        .unwrap_or("");
    let submitted_digest = fields
        .get("doris_result_digest")
        .and_then(Value::as_str)
        .unwrap_or("");
    let Some((token_cert, token_result)) = token.split_once('.') else {
        return Err(coding_refusal(
            state,
            StatusCode::CONFLICT,
            "DORIS_PROCESS_EXPIRED",
            "DORIS processing confirmation expired or no longer matches this case. Process the form again.",
            None,
        ));
    };
    if Some(token_cert) != fresh["certificate_digest"].as_str() {
        return Err(coding_refusal(
            state,
            StatusCode::CONFLICT,
            "DORIS_CERTIFICATE_CHANGED",
            "DORIS form changed; reprocessed. Review the result and confirm your final UCOD again.",
            Some(fresh),
        ));
    }
    let claimed = processor_result_digest(
        &submitted_doris,
        &submitted_codedit,
        DEFAULT_ICD11_RELEASE,
        WHO_ENGINE_DIGEST,
    );
    let fresh_digest = fresh["result_digest"].as_str().unwrap_or("");
    if claimed != submitted_digest
        || token_result != submitted_digest
        || submitted_digest != fresh_digest
    {
        return Err(coding_refusal(
            state,
            StatusCode::CONFLICT,
            "DORIS_PROCESS_MISMATCH",
            "DORIS processor results changed. Process the form again.",
            None,
        ));
    }
    let conclusive = fields
        .get("conclusive_cod")
        .and_then(Value::as_str)
        .unwrap_or("")
        .split_whitespace()
        .next()
        .unwrap_or("")
        .to_string();
    if conclusive.is_empty() {
        return Err(coding_refusal(
            state,
            StatusCode::BAD_REQUEST,
            "invalid_request",
            "conclusive_cod is required.",
            None,
        ));
    }
    let blocked = || {
        let message = "The ICD-11 code expression is not valid.";
        json_with_csrf(
            state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": message, "code": "final_blocked", "messages": [message] }),
        )
    };
    match blocking(move || engine.codeinfo(&conclusive, None)).await {
        Some(Ok(Some(info))) if info["code"].as_str().is_some_and(|c| !c.is_empty()) => {}
        Some(Ok(_)) => return Err(blocked()),
        Some(Err(err)) if is_input_error(&err) => return Err(blocked()),
        _ => {
            return Err(coding_refusal(
                state,
                StatusCode::SERVICE_UNAVAILABLE,
                "who_unavailable",
                UNAVAILABLE,
                None,
            ));
        }
    }
    for key in [
        "doris_process_token",
        "doris_result_digest",
        "doris_client_revision",
    ] {
        fields.remove(key);
    }
    fields.insert("doris_certificate".into(), fresh["certificate"].clone());
    fields.insert("doris_result".into(), fresh["doris"].clone());
    fields.insert("codedit_result".into(), fresh["codedit"].clone());
    Ok(Value::Object(fields))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::build_router;
    use axum::body::Body;
    use axum::http::Request;
    use digitva_db::{CODING_MODE_ICD10, OfflineDatabase};
    use std::time::Duration;
    use tower::ServiceExt;

    /// A station with one submitted interview; returns its `va_sid`.
    fn db_with_case() -> (OfflineDatabase, String) {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let draft = db
            .start_draft(&json!({ "project_id": "1", "site_id": "PHC01" }))
            .unwrap();
        let draft_id = draft["draft"]["draft_id"].as_str().unwrap().to_string();
        let data = json!({ "Id10019": "male", "Id10051": "62", "age_group": "adult", "age_adult": "62",
                           "Id10476": "Chest pain then collapse." });
        let (_, submitted) = db
            .submit_draft(
                &draft_id,
                &json!({ "completion": { "valid": true, "issues": [], "data": data } }),
            )
            .unwrap();
        let va_sid = submitted["va_sid"].as_str().unwrap().to_string();
        (db, va_sid)
    }

    struct Client {
        app: axum::Router,
        tok: String,
    }

    impl Client {
        fn new(state: AppState) -> Self {
            let tok = state.launch_token.clone();
            Self {
                app: build_router(state),
                tok,
            }
        }

        async fn call(&self, method: &str, uri: &str, body: Option<Value>) -> (StatusCode, Value) {
            let req = Request::builder()
                .method(method)
                .uri(uri)
                .header("authorization", format!("Bearer {}", self.tok))
                .header("content-type", "application/json")
                .body(
                    body.map(|b| Body::from(b.to_string()))
                        .unwrap_or_else(Body::empty),
                )
                .unwrap();
            let resp = self.app.clone().oneshot(req).await.unwrap();
            let status = resp.status();
            let bytes = axum::body::to_bytes(resp.into_body(), 8 << 20)
                .await
                .unwrap();
            (
                status,
                serde_json::from_slice(&bytes).unwrap_or(Value::Null),
            )
        }

        /// Polls `/icd11/status` until it leaves `starting` (bounded).
        async fn settled_status(&self) -> String {
            for _ in 0..600 {
                let (_, body) = self.call("GET", "/api/v1/icd11/status", None).await;
                let status = body["status"].as_str().unwrap_or("").to_string();
                if status != "starting" && status != "not_started" {
                    return status;
                }
                tokio::time::sleep(Duration::from_millis(250)).await;
            }
            panic!("ICD-11 engine did not settle within 150 s");
        }
    }

    fn terms_body(query: &str) -> Value {
        json!({ "schema_version": 1, "query": query, "limit": 5, "cursor": null })
    }

    #[tokio::test]
    async fn test_doris_routes_answer_the_server_unavailable_contract_when_the_bundle_is_missing() {
        let (db, va_sid) = db_with_case();
        let state = AppState::new(db).with_icd11(Icd11Service::new(
            Some(PathBuf::from("/nonexistent/icdapi")),
            None,
        ));
        let client = Client::new(state);

        let (status, body) = client
            .call(
                "POST",
                "/api/v1/doris-clinical/terms/VA-MISSING",
                Some(terms_body("fever")),
            )
            .await;
        assert_eq!(
            (status, body["error"]["code"].as_str()),
            (StatusCode::NOT_FOUND, Some("NOT_FOUND"))
        );

        let terms = format!("/api/v1/doris-clinical/terms/{va_sid}");
        let (status, body) = client.call("POST", &terms, Some(terms_body("f"))).await;
        assert_eq!(
            (status, body["error"]["code"].as_str()),
            (StatusCode::UNPROCESSABLE_ENTITY, Some("INVALID_INPUT"))
        );

        assert_eq!(client.settled_status().await, "unavailable");
        let process = json!({ "schema_version": 1, "role": "coder", "client_revision": 0, "certificate": {} });
        for (uri, body) in [
            (terms.clone(), terms_body("fever")),
            (
                format!("/api/v1/doris-clinical/codeinfo/{va_sid}"),
                json!({ "schema_version": 1, "code": "BA41.Z" }),
            ),
            (
                format!("/api/v1/doris-clinical/selection-check/{va_sid}"),
                json!({ "schema_version": 1, "code": "BA41.Z", "uri": "http://id.who.int/x" }),
            ),
            (format!("/api/v1/doris-clinical/process/{va_sid}"), process),
            (
                format!("/api/v1/doris-clinical/details/{va_sid}"),
                json!({ "schema_version": 1, "code": "BA41.Z" }),
            ),
        ] {
            let (status, body) = client.call("POST", &uri, Some(body)).await;
            assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE, "{uri}");
            assert_eq!(body["schema_version"], 1, "{uri}");
            assert_eq!(body["error"]["code"], "WHO_API_UNAVAILABLE", "{uri}");
        }

        let unavailable = json!({ "status": "unavailable", "result": null });
        let final_body = json!({
            "conclusive_cod": "BA41.Z", "doris_certificate": {}, "doris_result": unavailable,
            "codedit_result": unavailable, "doris_process_token": "a.b", "doris_result_digest": "b",
        });
        let (status, body) = client
            .call(
                "POST",
                &format!("/api/v1/coding/finalize/{va_sid}"),
                Some(final_body),
            )
            .await;
        assert_eq!(
            (status, body["code"].as_str()),
            (StatusCode::SERVICE_UNAVAILABLE, Some("who_unavailable"))
        );

        // The local catalogue still answers coding search while the engine is down.
        let (status, body) = client
            .call(
                "GET",
                &format!("/api/v1/icd11/coding-search/{va_sid}?q=fever"),
                None,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert!(body.is_array());
    }

    #[tokio::test]
    async fn test_icd10_mode_never_starts_the_engine() {
        let (db, va_sid) = db_with_case();
        db.update_station_settings(None, Some(CODING_MODE_ICD10))
            .unwrap();
        let state = AppState::new(db).with_icd11(Icd11Service::new(
            Some(PathBuf::from("/nonexistent/icdapi")),
            None,
        ));
        let client = Client::new(state);

        let (status, _) = client
            .call(
                "GET",
                &format!("/api/v1/va/{va_sid}/workspace?mode=coding"),
                None,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        let (status, body) = client
            .call(
                "POST",
                &format!("/api/v1/doris-clinical/terms/{va_sid}"),
                Some(terms_body("fever")),
            )
            .await;
        assert_eq!(
            (status, body["error"]["code"].as_str()),
            (StatusCode::CONFLICT, Some("DORIS_NOT_ENABLED"))
        );
        let (status, body) = client
            .call(
                "GET",
                &format!("/api/v1/icd11/coding-search/{va_sid}?q=fever"),
                None,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert!(body.is_array());
        let (status, body) = client
            .call(
                "POST",
                &format!("/api/v1/coding/finalize/{va_sid}"),
                Some(json!({ "conclusive_cod": "A09", "immediate_cod": "A09" })),
            )
            .await;
        assert_eq!(
            (status, body["workflow_state"].as_str()),
            (StatusCode::OK, Some("coded"))
        );

        let (_, body) = client.call("GET", "/api/v1/icd11/status", None).await;
        assert_eq!(body["status"], "not_started");
    }

    fn adult_certificate() -> Value {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../resource/doris_help_examples.json");
        let fixture: Value = serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        let adult = fixture["examples"]
            .as_array()
            .unwrap()
            .iter()
            .find(|e| e["id"] == "adult")
            .unwrap();
        assert_eq!(adult["observed"]["doris"]["code"], "BA41.Z");
        adult["certificate"].clone()
    }

    /// Needs the WHO bundle (`DIGITVA_ICD11_BUNDLE_DIR`, e.g. /tmp/icdapi_portable) and .NET 10;
    /// skipped without it.
    #[tokio::test]
    async fn test_live_engine_search_codeinfo_process_and_final_save() {
        if std::env::var("DIGITVA_ICD11_BUNDLE_DIR").is_err() {
            eprintln!("skipped: DIGITVA_ICD11_BUNDLE_DIR is not set");
            return;
        }
        let (db, va_sid) = db_with_case();
        let client = Client::new(AppState::new(db.clone()).with_icd11(Icd11Service::from_env()));

        // Opening the case starts the engine in the background.
        let (status, workspace) = client
            .call(
                "GET",
                &format!("/api/v1/va/{va_sid}/workspace?mode=coding"),
                None,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(client.settled_status().await, "ready");
        // The server's seed shape: the interview prefill only, no Part I and no ICDVersion.
        let seed = workspace["doris"]["initial_certificate"].clone();
        assert_eq!(seed, json!({ "AdministrativeData": { "Sex": 1, "EstimatedAge": "P62Y" } }));

        let (status, body) = client
            .call(
                "POST",
                &format!("/api/v1/doris-clinical/terms/{va_sid}"),
                Some(terms_body("myocardial infarction")),
            )
            .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        let items = body["items"].as_array().unwrap();
        assert!(!items.is_empty());
        for item in items {
            assert!(
                item["uri"]
                    .as_str()
                    .unwrap()
                    .starts_with("http://id.who.int/icd/release/11/2026-01/mms/"),
                "{item}"
            );
            assert!(!item["code"].as_str().unwrap().is_empty());
            assert_eq!(item["release"], "2026-01");
        }

        let ba41 = "http://id.who.int/icd/release/11/2026-01/mms/1334938734/unspecified";
        let (status, body) = client
            .call(
                "POST",
                &format!("/api/v1/doris-clinical/codeinfo/{va_sid}"),
                Some(json!({ "schema_version": 1, "code": "BA41.Z" })),
            )
            .await;
        assert_eq!(status, StatusCode::OK, "{body}");
        assert_eq!(
            (body["item"]["code"].as_str(), body["item"]["uri"].as_str()),
            (Some("BA41.Z"), Some(ba41))
        );
        assert!(!body["item"]["title"].as_str().unwrap().is_empty());
        let (status, body) = client
            .call(
                "POST",
                &format!("/api/v1/doris-clinical/codeinfo/{va_sid}"),
                Some(json!({ "schema_version": 1, "code": "NOT_A_CODE_999" })),
            )
            .await;
        assert_eq!(
            (status, body["error"]["code"].as_str()),
            (StatusCode::UNPROCESSABLE_ENTITY, Some("CODE_NOT_FOUND"))
        );

        let check = format!("/api/v1/doris-clinical/selection-check/{va_sid}");
        let (status, _) = client
            .call(
                "POST",
                &check,
                Some(json!({ "schema_version": 1, "code": "BA41.Z", "uri": ba41 })),
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        let (status, body) = client.call("POST", &check, Some(json!({ "schema_version": 1, "code": "BA41.Z", "uri": "http://id.who.int/icd/release/11/2026-01/mms/1" }))).await;
        assert_eq!(
            (status, body["error"]["code"].as_str()),
            (StatusCode::UNPROCESSABLE_ENTITY, Some("INVALID_SELECTION"))
        );

        let (status, body) = client
            .call(
                "GET",
                &format!("/api/v1/icd11/coding-search/{va_sid}?q=diabetes"),
                None,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        let first = &body.as_array().unwrap()[0];
        assert!(
            first["linearization_uri"]
                .as_str()
                .unwrap()
                .starts_with("http://id.who.int/icd/release/11/2026-01/mms/"),
            "{first}"
        );
        assert!(
            first["icd_to_display"]
                .as_str()
                .unwrap()
                .starts_with(first["icd_code"].as_str().unwrap())
        );

        // As the editor sends it: the seed unchanged, plus ICDVersion and the coder's causes.
        let adult = adult_certificate();
        let mut certificate = seed;
        for key in ["ICDVersion", "Part1", "Part2"] {
            certificate[key] = adult[key].clone();
        }
        let process = format!("/api/v1/doris-clinical/process/{va_sid}");
        let (status, processed) = client.call("POST", &process, Some(json!({ "schema_version": 1, "role": "coder", "client_revision": 2, "certificate": certificate }))).await;
        assert_eq!(status, StatusCode::OK, "{processed}");
        assert_eq!(
            (
                processed["doris"]["status"].as_str(),
                processed["doris"]["result"]["code"].as_str()
            ),
            (Some("completed"), Some("BA41.Z"))
        );
        assert_eq!(processed["client_revision"], 2);
        let (status, body) = client.call("POST", &process, Some(json!({ "schema_version": 1, "role": "coder", "client_revision": 0, "certificate": { "ICDVersion": "ICD11", "Part1": [] } }))).await;
        assert_eq!(
            (status, body["error"]["code"].as_str()),
            (StatusCode::UNPROCESSABLE_ENTITY, Some("INVALID_INPUT"))
        );
        assert!(body["error"]["fields"].is_array());

        let final_body = |processed: &Value, digest: &str| {
            json!({
                "conclusive_cod": "BA41.Z",
                "doris_certificate": processed["certificate"],
                "doris_result": processed["doris"],
                "codedit_result": processed["codedit"],
                "doris_process_token": processed["process_token"],
                "doris_result_digest": digest,
                "doris_client_revision": processed["client_revision"],
            })
        };
        let finalize = format!("/api/v1/coding/finalize/{va_sid}");
        let (status, body) = client
            .call(
                "POST",
                &finalize,
                Some(final_body(&processed, &"0".repeat(64))),
            )
            .await;
        assert_eq!(
            (status, body["code"].as_str()),
            (StatusCode::CONFLICT, Some("DORIS_PROCESS_MISMATCH"))
        );

        let mut changed = final_body(&processed, processed["result_digest"].as_str().unwrap());
        changed["doris_certificate"]["AdministrativeData"]["EstimatedAge"] = json!("P63Y");
        let (status, body) = client.call("POST", &finalize, Some(changed)).await;
        assert_eq!(
            (status, body["code"].as_str()),
            (StatusCode::CONFLICT, Some("DORIS_CERTIFICATE_CHANGED"))
        );
        assert!(body["processing"]["process_token"].is_string());

        let mut bad_code = final_body(&processed, processed["result_digest"].as_str().unwrap());
        bad_code["conclusive_cod"] = json!("NOT_A_CODE_999");
        let (status, body) = client.call("POST", &finalize, Some(bad_code)).await;
        assert_eq!(
            (status, body["code"].as_str()),
            (StatusCode::UNPROCESSABLE_ENTITY, Some("final_blocked"))
        );

        let (status, body) = client
            .call(
                "POST",
                &finalize,
                Some(final_body(
                    &processed,
                    processed["result_digest"].as_str().unwrap(),
                )),
            )
            .await;
        assert_eq!(
            (status, body["workflow_state"].as_str()),
            (StatusCode::OK, Some("coded")),
            "{body}"
        );

        // The bundle's coding_result carries the engine's certificate (codes with WHO URIs) and results.
        let payload: String = db.with_conn(|conn| {
            conn.query_row(
                "SELECT payload_json FROM loc_coding_results WHERE va_sid = ?1",
                [&va_sid],
                |r| r.get(0),
            )
            .unwrap()
        });
        let saved: Value = serde_json::from_str(&payload).unwrap();
        let final_cod = &saved["final_assessment"];
        assert_eq!(
            final_cod["doris_certificate"]["Part1"][0]["Conditions"][0]["LinearizationURI"],
            ba41
        );
        assert_eq!(final_cod["doris_result"]["result"]["code"], "BA41.Z");
        assert_eq!(final_cod["codedit_result"]["status"], "completed");
        assert!(
            final_cod.get("doris_process_token").is_none()
                && final_cod.get("doris_result_digest").is_none()
        );
    }
}
