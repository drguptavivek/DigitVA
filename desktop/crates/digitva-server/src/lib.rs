use axum::{
    body::Bytes,
    extract::{DefaultBodyLimit, Path, Query, Request, State},
    http::{header, HeaderMap, HeaderValue, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, patch, post, put},
    Json, Router,
};
use digitva_db::consent::{
    get_project_consent_config, upsert_project_consent_config, ProjectConsentConfig,
};
use digitva_db::roster::UpsertRosterMemberInput;
use digitva_db::{CaseListQuery, OfflineDatabase};
use rand::rngs::OsRng;
use rand::RngCore;
use serde::Deserialize;
use serde_json::{json, Value};
use subtle::ConstantTimeEq;
use std::sync::Arc;

mod icd11;
pub use icd11::Icd11Service;

#[derive(Clone)]
pub struct AppState {
    pub db: OfflineDatabase,
    pub csrf_token: String,
    pub launch_token: String,
    pub web_dist_dir: Option<std::path::PathBuf>,
    /// The lazily started WHO ICD-11 + DORIS engine (`icd11_doris` coding).
    pub icd11: Arc<Icd11Service>,
}

impl AppState {
    pub fn new(db: OfflineDatabase) -> Self {
        let mut launch_bytes = [0u8; 32];
        OsRng.fill_bytes(&mut launch_bytes);
        let mut csrf_bytes = [0u8; 16];
        OsRng.fill_bytes(&mut csrf_bytes);
        Self {
            db,
            csrf_token: hex::encode(csrf_bytes),
            launch_token: hex::encode(launch_bytes),
            web_dist_dir: None,
            icd11: Arc::new(Icd11Service::from_env()),
        }
    }

    pub fn with_launch_token(db: OfflineDatabase, launch_token: impl Into<String>) -> Self {
        let mut csrf_bytes = [0u8; 16];
        OsRng.fill_bytes(&mut csrf_bytes);
        Self {
            db,
            csrf_token: hex::encode(csrf_bytes),
            launch_token: launch_token.into(),
            web_dist_dir: None,
            icd11: Arc::new(Icd11Service::from_env()),
        }
    }

    pub fn with_web_dist_dir(mut self, dir: Option<std::path::PathBuf>) -> Self {
        self.web_dist_dir = dir;
        self
    }

    /// Replaces the engine config read from the environment (tests, embedding apps).
    pub fn with_icd11(mut self, service: Icd11Service) -> Self {
        self.icd11 = Arc::new(service);
        self
    }
}

fn is_allowed_host(host: &str) -> bool {
    let h = host.trim().to_ascii_lowercase();
    if h == "127.0.0.1" || h == "localhost" {
        return true;
    }
    if let Some(port_str) = h
        .strip_prefix("127.0.0.1:")
        .or_else(|| h.strip_prefix("localhost:"))
    {
        return !port_str.is_empty() && port_str.chars().all(|c| c.is_ascii_digit());
    }
    false
}

fn is_allowed_origin(origin: &str) -> bool {
    let o = origin.trim().to_ascii_lowercase();
    if o == "tauri://localhost"
        || o == "https://tauri.localhost"
        || o == "http://127.0.0.1"
        || o == "http://localhost"
    {
        return true;
    }
    if let Some(port_str) = o
        .strip_prefix("http://127.0.0.1:")
        .or_else(|| o.strip_prefix("http://localhost:"))
    {
        return !port_str.is_empty() && port_str.chars().all(|c| c.is_ascii_digit());
    }
    false
}

fn extract_provided_launch_token(headers: &HeaderMap) -> Option<&str> {
    if let Some(val) = headers
        .get("x-digitva-launch-token")
        .and_then(|v| v.to_str().ok())
    {
        let trimmed = val.trim();
        if !trimmed.is_empty() {
            return Some(trimmed);
        }
    }
    if let Some(auth) = headers
        .get(header::AUTHORIZATION)
        .and_then(|v| v.to_str().ok())
    {
        let trimmed = auth.trim();
        if let Some(rest) = trimmed
            .strip_prefix("Bearer ")
            .or_else(|| trimmed.strip_prefix("bearer "))
        {
            let tok = rest.trim();
            if !tok.is_empty() {
                return Some(tok);
            }
        }
    }
    None
}

fn constant_time_str_eq(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

async fn verify_local_request_middleware(
    State(state): State<AppState>,
    req: Request,
    next: Next,
) -> Response {
    let headers = req.headers();

    // 1. Validate Host header if present (DNS-rebinding protection)
    if let Some(host_val) = headers.get(header::HOST) {
        let Ok(host_str) = host_val.to_str() else {
            return json_with_csrf(
                &state,
                StatusCode::FORBIDDEN,
                json!({ "error": "Invalid Host header", "code": "forbidden_host" }),
            );
        };
        if !is_allowed_host(host_str) {
            return json_with_csrf(
                &state,
                StatusCode::FORBIDDEN,
                json!({ "error": "Host header not permitted on loopback server", "code": "forbidden_host" }),
            );
        }
    }

    // 2. Validate Origin header if present (Cross-origin browser request protection; no permissive CORS)
    if let Some(origin_val) = headers.get(header::ORIGIN) {
        let Ok(origin_str) = origin_val.to_str() else {
            return json_with_csrf(
                &state,
                StatusCode::FORBIDDEN,
                json!({ "error": "Invalid Origin header", "code": "forbidden_origin" }),
            );
        };
        if !is_allowed_origin(origin_str) {
            return json_with_csrf(
                &state,
                StatusCode::FORBIDDEN,
                json!({ "error": "Origin not permitted on loopback server", "code": "forbidden_origin" }),
            );
        }
    }

    // 3. Require per-launch bearer token on all /api/v1/* endpoints (including GETs)
    if req.uri().path().starts_with("/api/v1/") {
        let Some(provided) = extract_provided_launch_token(headers) else {
            return json_with_csrf(
                &state,
                StatusCode::UNAUTHORIZED,
                json!({ "error": "Missing per-launch bearer token", "code": "invalid_launch_token" }),
            );
        };
        if !constant_time_str_eq(provided, &state.launch_token) {
            return json_with_csrf(
                &state,
                StatusCode::UNAUTHORIZED,
                json!({ "error": "Invalid per-launch bearer token", "code": "invalid_launch_token" }),
            );
        }
    }

    state.db.record_activity();
    let mut resp = next.run(req).await;
    let resp_headers = resp.headers_mut();
    resp_headers.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-store"),
    );
    if !resp_headers.contains_key("x-csrftoken") {
        if let Ok(hv) = HeaderValue::from_str(&state.csrf_token) {
            resp_headers.insert(header::HeaderName::from_static("x-csrftoken"), hv);
        }
    }
    resp
}

/// Largest signed station config the import accepts: it carries every offered locale's
/// translations (about 100-220 KB each), so a project offering every language passes 2 MB.
const STATION_CONFIG_MAX_BYTES: usize = 16 * 1024 * 1024;

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .route("/api/v1/health", get(handle_health))
        .route(
            "/api/v1/station/config",
            get(handle_get_station_config)
                .put(handle_put_station_config)
                .post(handle_import_signed_station_config)
                .layer(DefaultBodyLimit::max(STATION_CONFIG_MAX_BYTES)),
        )
        .route(
            "/api/v1/station/config/signed",
            post(handle_import_signed_station_config)
                .layer(DefaultBodyLimit::max(STATION_CONFIG_MAX_BYTES)),
        )
        .route(
            "/api/v1/station/enrolment-file",
            get(handle_station_enrolment_file),
        )
        .route(
            "/api/v1/station/bundle/export",
            post(handle_export_dvb_bundle),
        )
        .route(
            "/api/v1/station/bundles/export",
            post(handle_export_dvb_bundle_json),
        )
        .route(
            "/api/v1/station/bundle/receipt",
            post(handle_import_dvb_receipt),
        )
        .route(
            "/api/v1/station/bundles/receipt",
            post(handle_import_dvb_receipt),
        )
        .route(
            "/api/v1/station/facility",
            get(handle_get_facility).put(handle_put_facility),
        )
        .route(
            "/api/v1/station/settings",
            get(handle_get_station_settings).put(handle_put_station_settings),
        )
        .route("/api/v1/station/lock", post(handle_lock_station))
        .route("/api/v1/station/unlock", post(handle_unlock_station))
        .route(
            "/api/v1/station/roster",
            get(handle_get_station_roster).post(handle_upsert_roster_member),
        )
        .route(
            "/api/v1/station/designations",
            put(handle_put_station_designations),
        )
        .route("/api/v1/station/acting-role", post(handle_switch_acting_role))
        .route("/api/v1/me/access", get(handle_me_access))
        .route("/api/v1/me/home", get(handle_me_home))
        .route("/api/v1/me/kpis", get(handle_me_kpis))
        .route("/api/v1/me/notifications", get(handle_me_notifications))
        .route("/api/v1/profile/", get(handle_profile_nudge))
        .route("/api/v1/profile", get(handle_profile_nudge))
        .route(
            "/api/v1/profile/nudge/dismiss",
            post(handle_profile_nudge_dismiss),
        )
        .route("/api/v1/organization/me", get(handle_organization_me))
        .route(
            "/api/v1/organization/units/:org_unit_id/people",
            get(handle_organization_unit_people),
        )
        .route(
            "/api/v1/organization/:project_id/form-options",
            get(handle_form_options),
        )
        .route(
            "/api/v1/instruments/:code/definition",
            get(handle_instrument_definition),
        )
        .route(
            "/api/v1/instruments/:code/translations/:locale",
            get(handle_instrument_translations),
        )
        // Consent & Registration Identifier endpoints
        .route(
            "/api/v1/intake/consent-config",
            get(handle_get_consent_config).put(handle_put_consent_config),
        )
        .route(
            "/api/v1/intake/identifier-types",
            get(handle_get_identifier_types),
        )
        // Intake Death Registration, Cases & Supervisor Corrections (NO /api/v1/intake/supervision/* or consent-withdraw)
        .route(
            "/api/v1/intake/deaths",
            get(handle_list_deaths).post(handle_register_death),
        )
        .route("/api/v1/intake/deaths/:death_id", patch(handle_patch_death))
        .route("/api/v1/intake/cases", get(handle_list_cases))
        .route("/api/v1/intake/cases/:death_id", get(handle_get_case_detail))
        .route(
            "/api/v1/intake/cases/:death_id/identifiers",
            put(handle_put_case_identifiers),
        )
        .route(
            "/api/v1/intake/cases/:death_id/attempts",
            post(handle_log_contact_attempt),
        )
        .route(
            "/api/v1/intake/cases/:death_id/visit",
            post(handle_set_case_visit),
        )
        // VA Interview Drafts & Submissions
        .route(
            "/api/v1/intake/drafts",
            get(handle_list_drafts).post(handle_start_draft),
        )
        .route(
            "/api/v1/intake/drafts/:draft_id",
            get(handle_get_draft)
                .put(handle_save_draft)
                .patch(handle_save_draft_sections),
        )
        .route(
            "/api/v1/intake/drafts/:draft_id/submit",
            post(handle_submit_draft),
        )
        // Offline Coding & Reviewing Workspace
        .route("/api/v1/va/:va_sid/workspace", get(handle_va_workspace))
        .route("/api/v1/va/:va_sid/categories/:code", get(handle_va_category))
        .route(
            "/api/v1/va/:va_sid/note",
            get(handle_get_va_note).put(handle_save_va_note),
        )
        .route(
            "/api/v1/va/:va_sid/narrative-qa",
            post(handle_save_narrative_qa),
        )
        .route(
            "/api/v1/va/:va_sid/social-autopsy",
            post(handle_save_social_autopsy),
        )
        .route("/api/v1/coding/projects", get(handle_coding_projects))
        .route("/api/v1/coding/stats", get(handle_coding_stats))
        .route("/api/v1/coding/available", get(handle_coding_available))
        .route("/api/v1/coding/history", get(handle_coding_history))
        .route(
            "/api/v1/coding/allocation",
            get(handle_coding_allocation).post(handle_allocate_coding),
        )
        .route("/api/v1/coding/allocation/release", post(handle_release_coding))
        .route(
            "/api/v1/coding/submissions/:va_sid/code-now",
            post(handle_code_now),
        )
        .route(
            "/api/v1/coding/submissions/:va_sid/smartva",
            post(handle_run_smartva),
        )
        .route("/api/v1/coding/recode/:va_sid", post(handle_code_now))
        .route(
            "/api/v1/coding/initial/:va_sid",
            post(handle_save_initial_coding),
        )
        .route(
            "/api/v1/coding/finalize/:va_sid",
            post(handle_save_final_coding),
        )
        .route(
            "/api/v1/coding/not-codeable/:va_sid",
            post(handle_save_not_codeable),
        )
        .route("/api/v1/reviewing/projects", get(handle_reviewing_projects))
        .route("/api/v1/reviewing/stats", get(handle_reviewing_stats))
        .route("/api/v1/reviewing/available", get(handle_reviewing_available))
        .route("/api/v1/reviewing/history", get(handle_reviewing_history))
        .route("/api/v1/reviewing/allocation", get(handle_coding_allocation))
        .route("/api/v1/reviewing/allocation/:va_sid", post(handle_code_now))
        .route(
            "/api/v1/reviewing/allocation/release",
            post(handle_release_coding),
        )
        .route(
            "/api/v1/reviewing/initial/:va_sid",
            post(handle_save_reviewer_initial),
        )
        .route(
            "/api/v1/reviewing/finalize/:va_sid",
            post(handle_save_reviewer_final),
        )
        // ICD-10 / ICD-11 FTS5 Search, VA Cause Definitions & Workflow Events
        .route(
            "/api/v1/icd10/2019-2/coding-search/:va_sid",
            get(handle_icd10_search),
        )
        .route("/api/v1/icd11/coding-search/:va_sid", get(icd11::handle_coding_search))
        .route("/api/v1/icd11/status", get(icd11::handle_status))
        // ICD-11 + DORIS on the in-process WHO engine (server: app/routes/api/doris_clinical.py)
        .route("/api/v1/doris-clinical/terms/:va_sid", post(icd11::handle_terms))
        .route("/api/v1/doris-clinical/codeinfo/:va_sid", post(icd11::handle_codeinfo))
        .route(
            "/api/v1/doris-clinical/selection-check/:va_sid",
            post(icd11::handle_selection_check),
        )
        .route("/api/v1/doris-clinical/process/:va_sid", post(icd11::handle_process))
        .route("/api/v1/doris-clinical/:op/:va_sid", post(icd11::handle_guidance))
        .route("/api/v1/va-definitions/for-icd", get(handle_va_definition))
        .route("/api/v1/workflow/events/:va_sid", get(handle_workflow_events))
        // WHO MCCD A4 PDF Certificate & Line-List CSV Export
        .route(
            "/api/v1/cases/:va_sid/certificate.pdf",
            get(handle_certificate_pdf),
        )
        .route("/api/v1/cases/export.csv", get(handle_export_csv))
        .fallback(get(handle_static_web))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            verify_local_request_middleware,
        ))
        .with_state(state)
}

fn inject_launch_token_into_html(html: &str, launch_token: &str) -> String {
    let script = format!(
        "<script>window.__DIGITVA_LAUNCH_TOKEN__={:?};</script>",
        launch_token
    );
    if let Some(idx) = html.find("</head>") {
        let mut out = String::with_capacity(html.len() + script.len());
        out.push_str(&html[..idx]);
        out.push_str(&script);
        out.push_str(&html[idx..]);
        out
    } else {
        format!("{script}{html}")
    }
}

fn content_type_for_path(path: &std::path::Path) -> &'static str {
    match path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase()
        .as_str()
    {
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "application/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" | "map" => "application/json; charset=utf-8",
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        "woff" => "font/woff",
        "ttf" => "font/ttf",
        _ => "application/octet-stream",
    }
}

async fn handle_static_web(State(state): State<AppState>, req: Request) -> Response {
    let uri_path = req.uri().path();
    if uri_path.starts_with("/api/") {
        return json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": "API route not found", "code": "not_found" }),
        );
    }
    let Some(dist_dir) = state.web_dist_dir.as_ref() else {
        return json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": "Not found", "code": "not_found" }),
        );
    };
    if uri_path == "/" {
        let mut headers = HeaderMap::new();
        headers.insert(header::LOCATION, HeaderValue::from_static("/app/"));
        headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
        return (StatusCode::FOUND, headers).into_response();
    }
    let raw_rel = uri_path.trim_start_matches('/');
    if raw_rel.contains("..") || raw_rel.contains('\\') {
        return (StatusCode::BAD_REQUEST, "Invalid path").into_response();
    }
    if let Some(static_rel) = raw_rel.strip_prefix("static/") {
        for base in [
            std::path::PathBuf::from("../app/static"),
            std::path::PathBuf::from("./app/static"),
            dist_dir.join("static"),
        ] {
            let static_cand = base.join(static_rel);
            if static_cand.is_file() {
                if let Ok(bytes) = std::fs::read(&static_cand) {
                    let mime = content_type_for_path(&static_cand);
                    let mut headers = HeaderMap::new();
                    headers.insert(header::CONTENT_TYPE, HeaderValue::from_static(mime));
                    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
                    return (StatusCode::OK, headers, bytes).into_response();
                }
            }
        }
        return (StatusCode::NOT_FOUND, "Static asset not found").into_response();
    }
    let rel = raw_rel
        .strip_prefix("app/")
        .unwrap_or_else(|| if raw_rel == "app" { "" } else { raw_rel });
    let candidate = if rel.is_empty() {
        dist_dir.join("index.html")
    } else {
        let direct = dist_dir.join(rel);
        if direct.is_file() {
            direct
        } else if rel.starts_with("_expo/")
            || rel.starts_with("assets/")
            || std::path::Path::new(rel).extension().is_some()
        {
            return (StatusCode::NOT_FOUND, "Asset not found").into_response();
        } else {
            let html_cand = dist_dir.join(format!("{rel}.html"));
            if html_cand.is_file() {
                html_cand
            } else {
                let index_cand = dist_dir.join(rel).join("index.html");
                if index_cand.is_file() {
                    index_cand
                } else {
                    dist_dir.join("index.html")
                }
            }
        }
    };

    let Ok(bytes) = std::fs::read(&candidate) else {
        return (StatusCode::NOT_FOUND, "Static bundle not found").into_response();
    };
    let mime = content_type_for_path(&candidate);
    let mut headers = HeaderMap::new();
    headers.insert(header::CONTENT_TYPE, HeaderValue::from_static(mime));
    headers.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    if mime.starts_with("text/html") {
        let html = String::from_utf8_lossy(&bytes);
        let injected = inject_launch_token_into_html(&html, &state.launch_token);
        return (StatusCode::OK, headers, injected).into_response();
    }
    (StatusCode::OK, headers, bytes).into_response()
}

pub(crate) fn json_with_csrf(state: &AppState, status: StatusCode, body: Value) -> Response {
    let mut headers = HeaderMap::new();
    headers.insert(
        header::HeaderName::from_static("x-csrftoken"),
        HeaderValue::from_str(&state.csrf_token).unwrap(),
    );
    headers.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-store"),
    );
    (status, headers, Json(body)).into_response()
}

async fn handle_health(State(state): State<AppState>) -> Response {
    let cfg = state.db.get_station_config();
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "status": "ok",
            "mode": cfg.mode,
            "station_id": cfg.station_id,
            "facility_name": cfg.facility_name,
            "locked": state.db.is_locked(),
            "icd11": state.icd11.status()
        }),
    )
}

async fn handle_get_station_config(State(state): State<AppState>) -> Response {
    let cfg = state.db.get_station_config();
    json_with_csrf(&state, StatusCode::OK, json!(cfg))
}

async fn handle_put_station_config(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Response {
    let mode = body
        .get("mode")
        .and_then(Value::as_str)
        .unwrap_or("standalone");
    let facility_name = body.get("facility_name").and_then(Value::as_str);
    let district_name = body.get("district_name").and_then(Value::as_str);
    let state_name = body.get("state_name").and_then(Value::as_str);
    let remote_server_url = body.get("remote_server_url").and_then(Value::as_str);
    let provisioned_user_id = body.get("provisioned_user_id").and_then(Value::as_str);
    let provisioned_user_name = body.get("provisioned_user_name").and_then(Value::as_str);
    let provisioned_token = body.get("provisioned_token").and_then(Value::as_str);
    let provisioned_roles = body
        .get("provisioned_roles")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect::<Vec<String>>()
        });

    match state.db.update_station_config(
        mode,
        facility_name,
        district_name,
        state_name,
        remote_server_url,
        provisioned_user_id,
        provisioned_user_name,
        provisioned_roles,
        provisioned_token,
    ) {
        Ok(cfg) => json_with_csrf(&state, StatusCode::OK, json!(cfg)),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": msg, "code": "validation_error" }),
        ),
    }
}

async fn handle_import_signed_station_config(
    State(state): State<AppState>,
    body: Bytes,
) -> Response {
    let text = String::from_utf8_lossy(&body).to_string();
    let raw_two_line = if let Ok(val) = serde_json::from_str::<Value>(&text) {
        val.get("signed_config")
            .or_else(|| val.get("station_config"))
            .or_else(|| val.get("raw"))
            .and_then(Value::as_str)
            .map(ToString::to_string)
            .unwrap_or(text)
    } else {
        text
    };

    match state.db.import_signed_station_config(&raw_two_line) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            err_val,
        ),
    }
}

/// The never-online enrolment file (`OfflineDatabase::station_enrolment_file`), served as a
/// download. It holds only the device id and public key, nothing secret.
async fn handle_station_enrolment_file(State(state): State<AppState>) -> Response {
    let file = match state.db.station_enrolment_file() {
        Ok(file) => file,
        Err(msg) => {
            eprintln!("station enrolment file failed: {msg}");
            return json_with_csrf(
                &state,
                StatusCode::INTERNAL_SERVER_ERROR,
                json!({ "error": "Could not read the station signing key.", "code": "signing_key_error" }),
            );
        }
    };
    let mut resp = json_with_csrf(&state, StatusCode::OK, file);
    resp.headers_mut().insert(
        header::CONTENT_DISPOSITION,
        HeaderValue::from_static("attachment; filename=\"digitva-station-enrolment.json\""),
    );
    resp
}

async fn handle_export_dvb_bundle_json(State(state): State<AppState>) -> Response {
    use base64::{engine::general_purpose::STANDARD, Engine as _};
    match state.db.export_dvb_bundle() {
        Ok((built, filename, held_back)) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({
                "bundle_id": built.manifest.bundle_id.to_string(),
                "bundle_seq": built.manifest.bundle_seq,
                "filename": filename,
                "record_count": built.items.len(),
                "records_held_back": held_back,
                "sandbox_records_excluded": state.db.count_pending_sandbox_records(),
                "bundle_bytes_b64": STANDARD.encode(&built.bytes)
            }),
        ),
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::FORBIDDEN),
            err_val,
        ),
    }
}

async fn handle_export_dvb_bundle(State(state): State<AppState>) -> Response {
    match state.db.export_dvb_bundle() {
        Ok((built, filename, held_back)) => {
            let mut headers = HeaderMap::new();
            headers.insert(
                header::CONTENT_TYPE,
                HeaderValue::from_static("application/octet-stream"),
            );
            headers.insert(
                header::CONTENT_DISPOSITION,
                HeaderValue::from_str(&format!("attachment; filename=\"{filename}\"")).unwrap(),
            );
            headers.insert(
                header::HeaderName::from_static("x-bundle-id"),
                HeaderValue::from_str(&built.manifest.bundle_id.to_string()).unwrap(),
            );
            headers.insert(
                header::HeaderName::from_static("x-bundle-seq"),
                HeaderValue::from_str(&built.manifest.bundle_seq.to_string()).unwrap(),
            );
            headers.insert(
                header::HeaderName::from_static("x-bundle-record-count"),
                HeaderValue::from_str(&built.items.len().to_string()).unwrap(),
            );
            headers.insert(
                header::HeaderName::from_static("x-bundle-records-held-back"),
                HeaderValue::from_str(&held_back.len().to_string()).unwrap(),
            );
            headers.insert(
                header::CACHE_CONTROL,
                HeaderValue::from_static("no-store"),
            );
            (StatusCode::OK, headers, built.bytes).into_response()
        }
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::FORBIDDEN),
            err_val,
        ),
    }
}

async fn handle_import_dvb_receipt(State(state): State<AppState>, body: Bytes) -> Response {
    let text = String::from_utf8_lossy(&body).to_string();
    let raw_two_line = if let Ok(val) = serde_json::from_str::<Value>(&text) {
        val.get("signed_receipt")
            .or_else(|| val.get("receipt"))
            .or_else(|| val.get("raw"))
            .and_then(Value::as_str)
            .map(ToString::to_string)
            .unwrap_or(text)
    } else {
        text
    };

    match state.db.import_dvb_receipt(&raw_two_line) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            err_val,
        ),
    }
}

fn facility_json(cfg: &digitva_db::StationConfig) -> Value {
    json!({
        "name": cfg.facility_name,
        "code": cfg.facility_code,
        "type": cfg.facility_type,
        "address": cfg.facility_address,
        "district": cfg.district_name,
        "state": cfg.state_name,
    })
}

async fn handle_get_facility(State(state): State<AppState>) -> Response {
    json_with_csrf(&state, StatusCode::OK, facility_json(&state.db.get_station_config()))
}

async fn handle_put_facility(
    State(state): State<AppState>,
    body: Result<Json<Value>, axum::extract::rejection::JsonRejection>,
) -> Response {
    let bad = |msg: &str| {
        json_with_csrf(
            &state,
            StatusCode::BAD_REQUEST,
            json!({ "error": msg, "code": "validation_error" }),
        )
    };
    let Ok(Json(body)) = body else {
        return bad("Request body must be a JSON object.");
    };
    // Absent or non-string fields count as empty, so a missing name fails the required check.
    let field = |k: &str| body.get(k).and_then(Value::as_str).unwrap_or("");
    match state.db.update_facility_details(
        field("name"),
        field("code"),
        field("type"),
        field("address"),
        field("district"),
        field("state"),
    ) {
        Ok(cfg) => json_with_csrf(&state, StatusCode::OK, facility_json(&cfg)),
        Err(msg) => bad(&msg),
    }
}

async fn handle_get_station_settings(State(state): State<AppState>) -> Response {
    json_with_csrf(&state, StatusCode::OK, state.db.station_settings())
}

/// `{enabled_modules?: [tag], coding_mode?: "icd11_doris"|"icd10"}`: at least one field.
async fn handle_put_station_settings(
    State(state): State<AppState>,
    body: Result<Json<Value>, axum::extract::rejection::JsonRejection>,
) -> Response {
    let bad = |msg: &str| {
        json_with_csrf(
            &state,
            StatusCode::BAD_REQUEST,
            json!({ "error": msg, "code": "validation_error" }),
        )
    };
    let Ok(Json(body)) = body else {
        return bad("Request body must be a JSON object.");
    };
    let modules: Option<Vec<String>> = match body.get("enabled_modules") {
        None => None,
        Some(Value::Array(items)) => {
            let names: Option<Vec<String>> = items.iter().map(|v| v.as_str().map(str::to_string)).collect();
            match names {
                Some(names) => Some(names),
                None => return bad("enabled_modules must be a list of module codes."),
            }
        }
        Some(_) => return bad("enabled_modules must be a list of module codes."),
    };
    let coding_mode = match body.get("coding_mode") {
        None => None,
        Some(Value::String(mode)) => Some(mode.as_str()),
        Some(_) => return bad("coding_mode must be a string."),
    };
    if modules.is_none() && coding_mode.is_none() {
        return bad("Send enabled_modules or coding_mode.");
    }
    match state.db.update_station_settings(modules.as_deref(), coding_mode) {
        Ok(settings) => json_with_csrf(&state, StatusCode::OK, settings),
        Err((code, err)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::BAD_REQUEST),
            err,
        ),
    }
}

async fn handle_lock_station(State(state): State<AppState>) -> Response {
    state.db.lock_store();
    json_with_csrf(&state, StatusCode::OK, json!({ "locked": true }))
}

async fn handle_unlock_station(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Response {
    let member_id = body
        .get("member_id")
        .and_then(Value::as_str)
        .unwrap_or("roster-mo-1");
    let pin = body.get("pin").and_then(Value::as_str).unwrap_or("");
    match state.db.unlock_user_store(member_id, pin) {
        Ok(()) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({
                "locked": false,
                "member_id": member_id
            }),
        ),
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNAUTHORIZED),
            err_val,
        ),
    }
}

async fn handle_get_station_roster(State(state): State<AppState>) -> Response {
    let snapshot = state.db.get_roster();
    json_with_csrf(&state, StatusCode::OK, json!(snapshot))
}

async fn handle_upsert_roster_member(
    State(state): State<AppState>,
    Json(input): Json<UpsertRosterMemberInput>,
) -> Response {
    match state.db.upsert_roster_member(&input) {
        Ok(member) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({
                "member": member,
                "roster": state.db.get_roster()
            }),
        ),
        Err((code, msg)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            json!({
                "error": msg,
                "code": if code == 403 { "roster_read_only_when_provisioned" } else { "validation_error" }
            }),
        ),
    }
}

async fn handle_put_station_designations(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Response {
    let designations: Vec<String> = body
        .get("designations")
        .and_then(Value::as_array)
        .map(|arr| {
            arr.iter()
                .filter_map(Value::as_str)
                .map(ToString::to_string)
                .collect()
        })
        .unwrap_or_default();

    match state.db.update_designations(&designations) {
        Ok(updated) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({
                "designations": updated,
                "roster": state.db.get_roster()
            }),
        ),
        Err((code, msg)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            json!({
                "error": msg,
                "code": if code == 403 { "roster_read_only_when_provisioned" } else { "validation_error" }
            }),
        ),
    }
}

async fn handle_switch_acting_role(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Response {
    let member_id = body
        .get("member_id")
        .and_then(Value::as_str)
        .unwrap_or("roster-mo-1");
    let acting_role = body.get("acting_role").and_then(Value::as_str);
    let pin = body.get("pin").and_then(Value::as_str);

    match state
        .db
        .switch_acting_role_with_pin(member_id, acting_role, pin)
    {
        Ok(actor) => {
            let access = state.db.build_access_summary().unwrap_or_else(|_| json!(null));
            json_with_csrf(
                &state,
                StatusCode::OK,
                json!({
                    "active_actor": actor,
                    "access": access,
                    "roster": state.db.get_roster()
                }),
            )
        }
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            err_val,
        ),
    }
}

async fn handle_me_access(State(state): State<AppState>) -> Response {
    match state.db.build_access_summary() {
        Ok(summary) => json_with_csrf(&state, StatusCode::OK, summary),
        Err(_) => json_with_csrf(
            &state,
            StatusCode::UNAUTHORIZED,
            json!({ "error": "Authentication required", "code": "unauthorized" }),
        ),
    }
}

/// 409 `station_coding_not_enabled` when the signed config says the station does not code this
/// case's project (contract 4.3); None when coding may go on.
fn coding_gate(state: &AppState, va_sid: &str) -> Option<Response> {
    state.db.check_station_coding(va_sid).err().map(|err| db_result(state, Err(err)))
}

fn db_result(state: &AppState, result: Result<Value, (u16, Value)>) -> Response {
    match result {
        Ok(body) => json_with_csrf(state, StatusCode::OK, body),
        Err((code, body)) => json_with_csrf(
            state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::NOT_FOUND),
            body,
        ),
    }
}

async fn handle_form_options(
    State(state): State<AppState>,
    Path(project_id): Path<String>,
) -> Response {
    db_result(&state, state.db.form_options(project_id.trim()))
}

#[derive(Deserialize)]
struct DefinitionQuery {
    project_id: Option<String>,
    version: Option<String>,
    extensions: Option<String>,
}

/// The server's `instrument_definition`: `project_id` required; `version` and `extensions`
/// together name an exact earlier slice. The body's SHA-256 is the strong ETag and
/// `X-Definition-SHA256`; `If-None-Match` with it gets a bodiless 304.
async fn handle_instrument_definition(
    State(state): State<AppState>,
    Path(code): Path<String>,
    Query(q): Query<DefinitionQuery>,
    req_headers: HeaderMap,
) -> Response {
    let project_id = q.project_id.as_deref().map(str::trim).unwrap_or_default();
    if project_id.is_empty() {
        return json_with_csrf(
            &state,
            StatusCode::BAD_REQUEST,
            json!({ "error": "project_id is required.", "code": "invalid_request" }),
        );
    }
    let version = q.version.as_deref().map(str::trim).filter(|v| !v.is_empty());
    if version.is_some() != q.extensions.is_some() {
        return json_with_csrf(
            &state,
            StatusCode::BAD_REQUEST,
            json!({ "error": "version and extensions are given together.", "code": "invalid_request" }),
        );
    }
    let slice = version.map(|v| {
        let names = q.extensions.as_deref().unwrap_or_default();
        (v, names.split(',').map(str::trim).filter(|n| !n.is_empty()).map(ToString::to_string).collect())
    });
    let served = match state.db.instrument_definition(code.trim(), project_id, slice) {
        Ok(served) => served,
        Err(err) => return db_result(&state, Err(err)),
    };
    let etag = format!("\"{}\"", served.sha256);
    let mut headers = HeaderMap::new();
    headers.insert(
        header::HeaderName::from_static("x-csrftoken"),
        HeaderValue::from_str(&state.csrf_token).unwrap(),
    );
    headers.insert(
        header::HeaderName::from_static("x-definition-sha256"),
        HeaderValue::from_str(&served.sha256).unwrap(),
    );
    headers.insert(header::ETAG, HeaderValue::from_str(&etag).unwrap());
    let revalidated = req_headers
        .get(header::IF_NONE_MATCH)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|v| v.split(',').any(|tag| tag.trim().trim_start_matches("W/") == etag));
    if revalidated {
        return (StatusCode::NOT_MODIFIED, headers).into_response();
    }
    headers.insert(header::CONTENT_TYPE, HeaderValue::from_static("application/json"));
    (StatusCode::OK, headers, served.body.clone()).into_response()
}

async fn handle_instrument_translations(
    State(state): State<AppState>,
    Path((code, locale)): Path<(String, String)>,
    Query(q): Query<DefinitionQuery>,
) -> Response {
    let project_id = q.project_id.as_deref().map(str::trim).filter(|p| !p.is_empty());
    db_result(&state, state.db.instrument_translations(&code, locale.trim(), project_id))
}

async fn handle_me_home(State(state): State<AppState>) -> Response {
    match state.db.home_blocks() {
        Ok(body) => json_with_csrf(&state, StatusCode::OK, body),
        Err(_) => json_with_csrf(
            &state,
            StatusCode::UNAUTHORIZED,
            json!({ "error": "Authentication required", "code": "unauthorized" }),
        ),
    }
}

#[derive(Deserialize)]
struct ProjectQuery {
    project_id: Option<String>,
}

impl ProjectQuery {
    /// The requested project, or the sandbox "1" when absent or blank.
    fn project_id(&self) -> &str {
        self.project_id.as_deref().map(str::trim).filter(|s| !s.is_empty()).unwrap_or("1")
    }
}

async fn handle_get_consent_config(
    State(state): State<AppState>,
    Query(q): Query<ProjectQuery>,
) -> Response {
    match state.db.with_conn(|conn| get_project_consent_config(conn, q.project_id())) {
        Ok(cfg) => json_with_csrf(&state, StatusCode::OK, cfg.to_contract_wire_json()),
        Err(_) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({
                "error": "Consent configuration has not been loaded for this project.",
                "code": "consent_config_not_loaded"
            }),
        ),
    }
}

async fn handle_put_consent_config(
    State(state): State<AppState>,
    Json(cfg): Json<ProjectConsentConfig>,
) -> Response {
    state
        .db
        .with_conn(|conn| upsert_project_consent_config(conn, &cfg).unwrap());
    json_with_csrf(&state, StatusCode::OK, json!(cfg))
}

async fn handle_get_identifier_types(
    State(state): State<AppState>,
    Query(q): Query<ProjectQuery>,
) -> Response {
    let types = state.db.list_identifier_types(q.project_id());
    json_with_csrf(&state, StatusCode::OK, json!({ "identifier_types": types }))
}

/// The station's case page or a 400 `invalid_request` for a malformed `limit`, `cursor` or
/// `registered` (the server's `GET /intake/deaths` and `/intake/cases` rules).
fn list_cases_or_400(state: &AppState, q: &CaseListQuery) -> Result<Value, Response> {
    state.db.list_cases(q).map_err(|msg| {
        json_with_csrf(
            state,
            StatusCode::BAD_REQUEST,
            json!({ "error": msg, "code": "invalid_request" }),
        )
    })
}

async fn handle_list_deaths(
    State(state): State<AppState>,
    Query(q): Query<CaseListQuery>,
) -> Response {
    match list_cases_or_400(&state, &q) {
        Ok(page) => json_with_csrf(
            &state,
            StatusCode::OK,
            json!({
                "deaths": page["deaths"],
                "next_cursor": page["next_cursor"]
            }),
        ),
        Err(refusal) => refusal,
    }
}

async fn handle_register_death(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Response {
    let actor = state.db.get_active_actor_context().audit_actor_label();
    match state.db.register_death(&body, &actor) {
        Ok(res) => json_with_csrf(&state, StatusCode::CREATED, res),
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            err_val,
        ),
    }
}

async fn handle_patch_death(
    State(state): State<AppState>,
    Path(death_id): Path<i64>,
    Json(body): Json<Value>,
) -> Response {
    let actor = state.db.get_active_actor_context().audit_actor_label();
    match state
        .db
        .update_death_registration(death_id, &body, &actor)
    {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            err_val,
        ),
    }
}

async fn handle_list_cases(
    State(state): State<AppState>,
    Query(q): Query<CaseListQuery>,
) -> Response {
    match list_cases_or_400(&state, &q) {
        Ok(page) => json_with_csrf(&state, StatusCode::OK, page),
        Err(refusal) => refusal,
    }
}

async fn handle_get_case_detail(
    State(state): State<AppState>,
    Path(death_id): Path<i64>,
) -> Response {
    match state.db.get_case_detail(death_id) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_put_case_identifiers(
    State(state): State<AppState>,
    Path(death_id): Path<i64>,
    Json(body): Json<Value>,
) -> Response {
    let actor = state.db.get_active_actor_context().audit_actor_label();
    match state.db.put_case_identifiers(death_id, &body, &actor) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err((code, err_val)) => json_with_csrf(
            &state,
            StatusCode::from_u16(code).unwrap_or(StatusCode::UNPROCESSABLE_ENTITY),
            err_val,
        ),
    }
}

async fn handle_log_contact_attempt(
    State(state): State<AppState>,
    Path(death_id): Path<i64>,
    Json(body): Json<Value>,
) -> Response {
    let actor = state.db.get_active_actor_context().audit_actor_label();
    let outcome = body
        .get("outcome")
        .and_then(Value::as_str)
        .unwrap_or("reached");
    let next_visit = body.get("next_visit_at").and_then(Value::as_str);
    match state
        .db
        .log_contact_attempt(death_id, outcome, next_visit, &actor)
    {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_set_case_visit(
    State(state): State<AppState>,
    Path(death_id): Path<i64>,
    Json(body): Json<Value>,
) -> Response {
    let next_visit = body.get("next_visit_at").and_then(Value::as_str);
    match state.db.set_case_visit(death_id, next_visit) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_list_drafts(State(state): State<AppState>) -> Response {
    json_with_csrf(&state, StatusCode::OK, state.db.list_drafts())
}

async fn handle_start_draft(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Response {
    match state.db.start_draft(&body) {
        Ok(res) => json_with_csrf(&state, StatusCode::CREATED, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": msg, "code": "validation_error" }),
        ),
    }
}

async fn handle_get_draft(
    State(state): State<AppState>,
    Path(draft_id): Path<String>,
) -> Response {
    match state.db.get_draft(&draft_id) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_save_draft(
    State(state): State<AppState>,
    Path(draft_id): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    match state.db.save_draft(&draft_id, &body) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_save_draft_sections(
    State(state): State<AppState>,
    Path(draft_id): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    match state.db.save_draft_sections(&draft_id, &body) {
        Ok((code, res)) => json_with_csrf(&state, StatusCode::from_u16(code).unwrap_or(StatusCode::OK), res),
        Err(_) => json_with_csrf(
            &state,
            StatusCode::INTERNAL_SERVER_ERROR,
            json!({ "error": "The draft could not be saved.", "code": "db_error" }),
        ),
    }
}

async fn handle_submit_draft(
    State(state): State<AppState>,
    Path(draft_id): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    match state.db.submit_draft(&draft_id, &body) {
        Ok((status_code, res)) => json_with_csrf(
            &state,
            StatusCode::from_u16(status_code).unwrap_or(StatusCode::CREATED),
            res,
        ),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": msg, "code": "validation_error" }),
        ),
    }
}

#[derive(Deserialize)]
struct ModeQuery {
    mode: Option<String>,
}

async fn handle_va_workspace(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Query(q): Query<ModeQuery>,
) -> Response {
    let mode = q.mode.as_deref().unwrap_or("coding");
    if mode != "view"
        && let Some(refused) = coding_gate(&state, &va_sid)
    {
        return refused;
    }
    icd11::warm_for_workspace(&state, &va_sid, mode);
    match state.db.get_va_workspace(&va_sid, mode) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_va_category(
    State(state): State<AppState>,
    Path((va_sid, code)): Path<(String, String)>,
    Query(q): Query<ModeQuery>,
) -> Response {
    let mode = q.mode.as_deref().unwrap_or("coding");
    match state.db.get_va_category(&va_sid, &code, mode) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_get_va_note(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
) -> Response {
    match state.db.get_va_note(&va_sid) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_save_va_note(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    let content = body.get("content").and_then(Value::as_str);
    match state.db.save_va_note(&va_sid, content) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_save_narrative_qa(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    match state.db.save_narrative_qa(&va_sid, &body) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_save_social_autopsy(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    match state.db.save_social_autopsy(&va_sid, &body) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

/// `project_options` and the first project id, from `OfflineDatabase::station_projects`.
fn project_options(state: &AppState) -> (Vec<Value>, String) {
    let projects = state.db.station_projects();
    let first = projects.first().map(|(id, _)| id.clone()).unwrap_or_else(|| "1".to_string());
    let options = projects
        .into_iter()
        .map(|(project_id, project_name)| json!({ "project_id": project_id, "project_name": project_name }))
        .collect();
    (options, first)
}

/// The projects the station codes; a project whose config `coding_mode` is null is coded on the
/// server and is not offered. `station_coding_disabled` is true when no project is left, so the
/// queue says coding is done on the server.
async fn handle_coding_projects(State(state): State<AppState>) -> Response {
    let (mut options, _) = project_options(&state);
    options.retain(|o| o["project_id"].as_str().is_some_and(|id| state.db.project_coding_mode(id).is_some()));
    let first = options.first().map_or(Value::Null, |o| o["project_id"].clone());
    let ids: Vec<Value> = options.iter().map(|o| o["project_id"].clone()).collect();
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "projects": ids,
            "project_options": options,
            "last_project_id": first,
            "station_coding_disabled": options.is_empty(),
        }),
    )
}

async fn handle_reviewing_projects(State(state): State<AppState>) -> Response {
    let (options, first) = project_options(&state);
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({ "project_options": options, "last_project_id": first }),
    )
}

async fn handle_coding_stats(State(state): State<AppState>) -> Response {
    let avail = state.db.get_coder_queue(50, 0);
    let hist = state.db.get_coder_history(50, 0);
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "available": avail["count"],
            "completed": hist["count"],
            "allocated": 0
        }),
    )
}

#[derive(Deserialize)]
struct PagingQuery {
    limit: Option<usize>,
    offset: Option<usize>,
}

async fn handle_coding_available(
    State(state): State<AppState>,
    Query(q): Query<PagingQuery>,
) -> Response {
    let limit = q.limit.unwrap_or(20);
    let offset = q.offset.unwrap_or(0);
    json_with_csrf(&state, StatusCode::OK, state.db.get_coder_queue(limit, offset))
}

async fn handle_coding_history(
    State(state): State<AppState>,
    Query(q): Query<PagingQuery>,
) -> Response {
    let limit = q.limit.unwrap_or(20);
    let offset = q.offset.unwrap_or(0);
    json_with_csrf(&state, StatusCode::OK, state.db.get_coder_history(limit, offset))
}

async fn handle_coding_allocation(State(state): State<AppState>) -> Response {
    json_with_csrf(&state, StatusCode::OK, json!({ "allocation": null }))
}

async fn handle_allocate_coding(
    State(state): State<AppState>,
    Json(body): Json<Value>,
) -> Response {
    let va_sid = body
        .get("va_sid")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    if let Some(refused) = coding_gate(&state, &va_sid) {
        return refused;
    }
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "va_sid": va_sid,
            "actiontype": "coding",
            "workflow_state": "coding_in_progress"
        }),
    )
}

async fn handle_release_coding(State(state): State<AppState>) -> Response {
    json_with_csrf(&state, StatusCode::OK, json!({ "released": true }))
}

async fn handle_code_now(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
) -> Response {
    if let Some(refused) = coding_gate(&state, &va_sid) {
        return refused;
    }
    let _ = state.db.run_smartva_for_submission(&va_sid);
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "va_sid": va_sid,
            "actiontype": "coding",
            "workflow_state": "coding_in_progress"
        }),
    )
}

async fn handle_run_smartva(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
) -> Response {
    match state.db.run_smartva_for_submission(&va_sid) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_save_initial_coding(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
) -> Response {
    if let Some(refused) = coding_gate(&state, &va_sid) {
        return refused;
    }
    // Station workspaces are unmasked only, so there is no Step 1 to save (server: 409 not_masked).
    json_with_csrf(
        &state,
        StatusCode::CONFLICT,
        json!({ "error": "This project codes in one step; there is no Step 1 to save.", "code": "not_masked" }),
    )
}

async fn handle_save_final_coding(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    if let Some(refused) = coding_gate(&state, &va_sid) {
        return refused;
    }
    let body = match icd11::verify_doris_final(&state, &va_sid, body).await {
        Ok(body) => body,
        Err(resp) => return resp,
    };
    match state.db.save_coding_assessment(&va_sid, "final", &body) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": msg, "code": "validation_error" }),
        ),
    }
}

async fn handle_save_not_codeable(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    if let Some(refused) = coding_gate(&state, &va_sid) {
        return refused;
    }
    match state.db.save_coding_assessment(&va_sid, "not_codeable", &body) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": msg, "code": "validation_error" }),
        ),
    }
}

async fn handle_reviewing_stats(State(state): State<AppState>) -> Response {
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "in_scope": 0,
            "completed": 0,
            "available": 0,
            "allocation": null
        }),
    )
}

async fn handle_reviewing_available(
    State(state): State<AppState>,
    Query(q): Query<PagingQuery>,
) -> Response {
    let limit = q.limit.unwrap_or(20);
    let offset = q.offset.unwrap_or(0);
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "cases": [],
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_more": false
        }),
    )
}

async fn handle_reviewing_history(
    State(state): State<AppState>,
    Query(q): Query<PagingQuery>,
) -> Response {
    let limit = q.limit.unwrap_or(20);
    let offset = q.offset.unwrap_or(0);
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "history": [],
            "count": 0,
            "limit": limit,
            "offset": offset,
            "has_more": false
        }),
    )
}

async fn handle_save_reviewer_initial(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    match state
        .db
        .save_coding_assessment(&va_sid, "reviewer_initial", &body)
    {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": msg, "code": "validation_error" }),
        ),
    }
}

async fn handle_save_reviewer_final(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Json(body): Json<Value>,
) -> Response {
    let body = match icd11::verify_doris_final(&state, &va_sid, body).await {
        Ok(body) => body,
        Err(resp) => return resp,
    };
    match state
        .db
        .save_coding_assessment(&va_sid, "reviewer_final", &body)
    {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::UNPROCESSABLE_ENTITY,
            json!({ "error": msg, "code": "validation_error" }),
        ),
    }
}

#[derive(Deserialize)]
pub(crate) struct SearchQuery {
    pub(crate) q: Option<String>,
}

async fn handle_icd10_search(
    State(state): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Response {
    let query = q.q.as_deref().unwrap_or("");
    let items = state.db.search_icd("icd10", query);
    json_with_csrf(&state, StatusCode::OK, Value::Array(items))
}

#[derive(Deserialize)]
struct VaDefQuery {
    classification: Option<String>,
    code: Option<String>,
}

async fn handle_va_definition(
    State(state): State<AppState>,
    Query(q): Query<VaDefQuery>,
) -> Response {
    let cls = q.classification.as_deref().unwrap_or("icd11");
    let code = q.code.as_deref().unwrap_or("");
    match state.db.get_va_definition(cls, code) {
        Ok(res) => json_with_csrf(&state, StatusCode::OK, res),
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

#[derive(Deserialize)]
struct EventsQuery {
    limit: Option<usize>,
}

async fn handle_workflow_events(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
    Query(q): Query<EventsQuery>,
) -> Response {
    let limit = q.limit.unwrap_or(50);
    json_with_csrf(
        &state,
        StatusCode::OK,
        state.db.get_workflow_events(&va_sid, limit),
    )
}

async fn handle_certificate_pdf(
    State(state): State<AppState>,
    Path(va_sid): Path<String>,
) -> Response {
    match state.db.generate_mccd_pdf_for_va(&va_sid) {
        Ok(bytes) => {
            let mut headers = HeaderMap::new();
            headers.insert(
                header::CONTENT_TYPE,
                HeaderValue::from_static("application/pdf"),
            );
            headers.insert(
                header::CONTENT_DISPOSITION,
                HeaderValue::from_str(&format!("attachment; filename=\"MCCD-{va_sid}.pdf\""))
                    .unwrap(),
            );
            headers.insert(
                header::CACHE_CONTROL,
                HeaderValue::from_static("no-store"),
            );
            (StatusCode::OK, headers, bytes).into_response()
        }
        Err(msg) => json_with_csrf(
            &state,
            StatusCode::NOT_FOUND,
            json!({ "error": msg, "code": "not_found" }),
        ),
    }
}

async fn handle_export_csv(State(state): State<AppState>) -> Response {
    let csv_text = state.db.export_cases_csv();
    let mut headers = HeaderMap::new();
    headers.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("text/csv; charset=utf-8"),
    );
    headers.insert(
        header::CONTENT_DISPOSITION,
        HeaderValue::from_static("attachment; filename=\"digitva-phc-cases.csv\""),
    );
    headers.insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("no-store"),
    );
    (StatusCode::OK, headers, csv_text).into_response()
}

fn roster_member_role_labels(m: &digitva_db::roster::StationRosterMember) -> Vec<String> {
    let mut labels = Vec::new();
    if m.is_reporter {
        labels.push("Death Reporter".to_string());
    }
    if m.is_interviewer {
        labels.push("Interviewer".to_string());
    }
    if m.is_supervisor {
        labels.push("Station Supervisor".to_string());
    }
    if m.is_coder {
        labels.push("Coder".to_string());
    }
    labels
}

/// Active roster members holding a grant in `project_id` that covers `org_unit_id` (a grant
/// without an org unit covers every unit of the project).
fn unit_people(
    members: &[digitva_db::roster::StationRosterMember],
    project_id: &str,
    org_unit_id: &str,
) -> Vec<Value> {
    members
        .iter()
        .filter(|m| {
            m.active
                && m.roles.iter().any(|g| {
                    g.project_id == project_id
                        && g.org_unit_id.as_deref().is_none_or(|id| id == org_unit_id)
                })
        })
        .map(|m| {
            json!({
                "name": m.name,
                "cadre": m.designation,
                "roles": roster_member_role_labels(m)
            })
        })
        .collect()
}

async fn handle_organization_me(State(state): State<AppState>) -> Response {
    let cfg = state.db.get_station_config();
    let roster = state.db.get_roster();
    let active_members: Vec<Value> = roster
        .members
        .iter()
        .filter(|m| m.active)
        .map(|m| {
            json!({
                "name": m.name,
                "cadre": m.designation,
                "roles": roster_member_role_labels(m)
            })
        })
        .collect();

    let sc_people_count = roster
        .members
        .iter()
        .filter(|m| m.active && (m.is_reporter || m.is_interviewer))
        .count();

    let district_people: Vec<Value> = if let Some(cust) = roster.custodian.as_ref() {
        vec![json!({
            "name": cust.name,
            "cadre": cust.designation,
            "roles": ["Station Custodian"]
        })]
    } else {
        Vec::new()
    };

    let active_cadre = roster.active_actor.designation.clone();
    let (project_id, project_name) = state.db.station_projects().swap_remove(0);

    // A provisioned project shows the active actor's granted units, labelled by their paths.
    // ponytail: flat list, no above/below; the config names unit paths, not ancestor ids.
    if let Some(targets) = state.db.active_actor_targets(&project_id) {
        let units: Vec<&(String, String)> = targets.iter().flat_map(|t| t.org_units.iter()).collect();
        return json_with_csrf(
            &state,
            StatusCode::OK,
            json!({
                "projects": [{
                    "project_id": project_id,
                    "project_name": project_name,
                    "my_units": units.iter().map(|(id, path)| json!({
                        "org_unit_id": id, "unit_name": path, "level_name": "Org unit",
                        "cadres": [active_cadre]
                    })).collect::<Vec<Value>>(),
                    "above": [],
                    "my_level": units.iter().map(|(id, path)| json!({
                        "org_unit_id": id, "unit_name": path, "parent_org_unit_id": null,
                        "people": unit_people(&roster.members, &project_id, id)
                    })).collect::<Vec<Value>>(),
                    "below": []
                }]
            }),
        );
    }

    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "projects": [
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "my_units": [
                        {
                            "org_unit_id": "ou-phc-1",
                            "unit_name": cfg.facility_name,
                            "level_name": "Primary Health Centre",
                            "cadres": [active_cadre]
                        }
                    ],
                    "above": [
                        {
                            "org_unit_id": "ou-state-1",
                            "unit_name": cfg.state_name,
                            "level_name": "State",
                            "parent_org_unit_id": null,
                            "people": []
                        },
                        {
                            "org_unit_id": "ou-district-1",
                            "unit_name": cfg.district_name,
                            "level_name": "District",
                            "parent_org_unit_id": "ou-state-1",
                            "people": district_people
                        }
                    ],
                    "my_level": [
                        {
                            "org_unit_id": "ou-phc-1",
                            "unit_name": cfg.facility_name,
                            "parent_org_unit_id": "ou-district-1",
                            "people": active_members
                        }
                    ],
                    "below": [
                        {
                            "org_unit_id": "ou-sc-1",
                            "unit_name": "Sub-Centre 1",
                            "level_name": "Sub-Centre",
                            "parent_org_unit_id": "ou-phc-1",
                            "people_count": sc_people_count,
                            "has_children": false
                        },
                        {
                            "org_unit_id": "ou-sc-2",
                            "unit_name": "Sub-Centre 2",
                            "level_name": "Sub-Centre",
                            "parent_org_unit_id": "ou-phc-1",
                            "people_count": sc_people_count,
                            "has_children": false
                        }
                    ]
                }
            ]
        }),
    )
}

async fn handle_organization_unit_people(
    State(state): State<AppState>,
    Path(org_unit_id): Path<String>,
) -> Response {
    let cfg = state.db.get_station_config();
    let roster = state.db.get_roster();
    match org_unit_id.as_str() {
        "ou-sc-1" | "ou-sc-2" => {
            let unit_name = if org_unit_id == "ou-sc-1" {
                "Sub-Centre 1"
            } else {
                "Sub-Centre 2"
            };
            let people: Vec<Value> = roster
                .members
                .iter()
                .filter(|m| m.active && (m.is_reporter || m.is_interviewer))
                .map(|m| {
                    json!({
                        "name": m.name,
                        "cadre": m.designation,
                        "roles": roster_member_role_labels(m)
                    })
                })
                .collect();
            json_with_csrf(
                &state,
                StatusCode::OK,
                json!({
                    "unit": {
                        "org_unit_id": org_unit_id,
                        "unit_name": unit_name,
                        "level_name": "Sub-Centre"
                    },
                    "people": people,
                    "children": []
                }),
            )
        }
        "ou-phc-1" => {
            let people: Vec<Value> = roster
                .members
                .iter()
                .filter(|m| m.active)
                .map(|m| {
                    json!({
                        "name": m.name,
                        "cadre": m.designation,
                        "roles": roster_member_role_labels(m)
                    })
                })
                .collect();
            json_with_csrf(
                &state,
                StatusCode::OK,
                json!({
                    "unit": {
                        "org_unit_id": "ou-phc-1",
                        "unit_name": cfg.facility_name,
                        "level_name": "Primary Health Centre"
                    },
                    "people": people,
                    "children": []
                }),
            )
        }
        _ => {
            // A provisioned unit is served only when the active actor's grants cover it.
            let found = state.db.station_projects().into_iter().find_map(|(project_id, _)| {
                state.db.active_actor_targets(&project_id)?.into_iter().find_map(|t| {
                    t.org_units
                        .into_iter()
                        .find(|(id, _)| *id == org_unit_id)
                        .map(|(_, path)| (project_id.clone(), path))
                })
            });
            match found {
                Some((project_id, path)) => json_with_csrf(
                    &state,
                    StatusCode::OK,
                    json!({
                        "unit": {
                            "org_unit_id": org_unit_id,
                            "unit_name": path,
                            "level_name": "Org unit"
                        },
                        "people": unit_people(&roster.members, &project_id, &org_unit_id),
                        "children": []
                    }),
                ),
                None => json_with_csrf(
                    &state,
                    StatusCode::NOT_FOUND,
                    json!({ "error": "Organization unit not found", "code": "not_found" }),
                ),
            }
        }
    }
}

async fn handle_me_kpis(State(state): State<AppState>) -> Response {
    // Whole-register counts, not one page of rows.
    let counts = state.db.case_counts().unwrap_or(Value::Null);
    let count_of = |key: &str| counts.get(key).and_then(Value::as_u64).unwrap_or(0) as usize;
    let deaths_reported = count_of("total");
    let interviews_done = count_of("completed");
    let hist = state.db.get_coder_history(500, 0);
    let coded = hist
        .get("count")
        .and_then(Value::as_u64)
        .unwrap_or(0) as usize;
    let (interviews_pct, coded_pct) = if deaths_reported > 0 {
        (
            Some(((interviews_done * 100) / deaths_reported) as u64),
            Some(((coded * 100) / deaths_reported) as u64),
        )
    } else {
        (None, None)
    };
    let (project_id, project_name) = state.db.station_projects().swap_remove(0);
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "projects": [
                {
                    "project_id": project_id,
                    "project_name": project_name,
                    "deaths_reported": deaths_reported,
                    "interviews_done": interviews_done,
                    "coded": coded,
                    "interviews_pct": interviews_pct,
                    "coded_pct": coded_pct
                }
            ]
        }),
    )
}

async fn handle_me_notifications(State(state): State<AppState>) -> Response {
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "notifications": [],
            "next_cursor": 0
        }),
    )
}

async fn handle_profile_nudge(State(state): State<AppState>) -> Response {
    json_with_csrf(
        &state,
        StatusCode::OK,
        json!({
            "profile_nudge": false,
            "missing_profile_fields": []
        }),
    )
}

async fn handle_profile_nudge_dismiss(State(state): State<AppState>) -> Response {
    json_with_csrf(&state, StatusCode::OK, json!({ "profile_nudge": false }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::body::Body;
    use axum::http::Request;
    use tower::ServiceExt;

    #[tokio::test]
    async fn test_api_launch_token_host_origin_and_removed_routes() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        let state = AppState::new(db);
        let tok = state.launch_token.clone();
        let app = build_router(state);

        // 1. Missing per-launch token -> 401
        let unauth_resp = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/me/access")
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(unauth_resp.status(), StatusCode::UNAUTHORIZED);

        // 2. Evil Host header -> 403
        let bad_host_resp = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/me/access")
                    .header("host", "evil.example.com")
                    .header("authorization", format!("Bearer {tok}"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(bad_host_resp.status(), StatusCode::FORBIDDEN);

        // 3. Evil Origin header -> 403
        let bad_origin_resp = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/me/access")
                    .header("origin", "https://evil.example.com")
                    .header("authorization", format!("Bearer {tok}"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(bad_origin_resp.status(), StatusCode::FORBIDDEN);

        // 4. Valid launch token + localhost Origin -> 200 + Cache-Control: no-store + no Access-Control-Allow-Origin
        let resp = app
            .clone()
            .oneshot(
                Request::builder()
                    .uri("/api/v1/me/access")
                    .header("host", "127.0.0.1:18420")
                    .header("origin", "tauri://localhost")
                    .header("authorization", format!("Bearer {tok}"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        assert!(resp.headers().contains_key("x-csrftoken"));
        assert_eq!(resp.headers().get("cache-control").unwrap(), "no-store");
        assert!(!resp
            .headers()
            .contains_key("access-control-allow-origin"));

        // 5. Removed routes return 404
        for removed_uri in [
            "/api/v1/intake/supervision/cases",
            "/api/v1/intake/cases/1/consent-withdraw",
        ] {
            let r = app
                .clone()
                .oneshot(
                    Request::builder()
                        .uri(removed_uri)
                        .header("authorization", format!("Bearer {tok}"))
                        .body(Body::empty())
                        .unwrap(),
                )
                .await
                .unwrap();
            assert_eq!(r.status(), StatusCode::NOT_FOUND, "Route {removed_uri} must be 404");
        }

        // 6. POST /api/v1/intake/deaths with DPDP consent and CRS/MCCD identifiers
        let reg_body = json!({
            "project_id": "1",
            "site_id": "PHC01",
            "deceased_name": "Rameshwar Prasad",
            "deceased_sex": "male",
            "date_of_death": "2026-10-19",
            "age_years": "72",
            "informant_name": "Anil Prasad",
            "informant_phone": "9876543210",
            "identifiers": {
                "crs_reg_no": "crs/2026/991",
                "mccd_cert_no": "mccd/2026/991"
            },
            "consent": {
                "decision": "granted",
                "notice_version_id": digitva_db::consent::DEFAULT_NOTICE_VERSION_ID_EN,
                "notice_language": "en",
                "notice_sha256": digitva_db::consent::default_project_consent_config("1").notices[0].text_sha256,
                "mode": "spoken",
                "purposes": [
                    { "code": "record_and_interview", "granted": true },
                    { "code": "contact_followup", "granted": true },
                    { "code": "cause_of_death_coding", "granted": true },
                    { "code": "statistical_reports", "granted": true }
                ]
            }
        });
        let reg_resp = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/intake/deaths")
                    .header("content-type", "application/json")
                    .header("x-digitva-launch-token", &tok)
                    .body(Body::from(serde_json::to_vec(&reg_body).unwrap()))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(reg_resp.status(), StatusCode::CREATED);
    }

    #[tokio::test]
    async fn test_station_facility_get_put_token_and_validation() {
        let state = AppState::new(OfflineDatabase::open_in_memory().unwrap());
        let tok = state.launch_token.clone();
        let app = build_router(state);
        let req = |method: &str, token: Option<&str>, body: &str| {
            let mut b = Request::builder()
                .method(method)
                .uri("/api/v1/station/facility")
                .header("content-type", "application/json");
            if let Some(t) = token {
                b = b.header("authorization", format!("Bearer {t}"));
            }
            b.body(Body::from(body.to_string())).unwrap()
        };
        let json_of = |resp: Response| async move {
            let bytes = axum::body::to_bytes(resp.into_body(), 1 << 16).await.unwrap();
            serde_json::from_slice::<Value>(&bytes).unwrap()
        };

        let refused = app.clone().oneshot(req("GET", None, "")).await.unwrap();
        assert_eq!(refused.status(), StatusCode::UNAUTHORIZED);
        let refused = app.clone().oneshot(req("PUT", None, "{}")).await.unwrap();
        assert_eq!(refused.status(), StatusCode::UNAUTHORIZED);

        let got = app.clone().oneshot(req("GET", Some(&tok), "")).await.unwrap();
        assert_eq!(got.status(), StatusCode::OK);
        assert_eq!(json_of(got).await["name"], "Model Primary Health Centre");

        let put = app
            .clone()
            .oneshot(req(
                "PUT",
                Some(&tok),
                r#"{"name":"Rampur PHC","code":"RP01","type":"PHC","address":"Main Rd","district":"Rampur","state":"UP"}"#,
            ))
            .await
            .unwrap();
        assert_eq!(put.status(), StatusCode::OK);
        assert_eq!(json_of(put).await["code"], "RP01");
        let got = app.clone().oneshot(req("GET", Some(&tok), "")).await.unwrap();
        assert_eq!(json_of(got).await["name"], "Rampur PHC");

        let empty_name = app.clone().oneshot(req("PUT", Some(&tok), r#"{"name":" "}"#)).await.unwrap();
        assert_eq!(empty_name.status(), StatusCode::BAD_REQUEST);
        assert_eq!(json_of(empty_name).await["error"], "Facility name is required.");
        let garbage = app.clone().oneshot(req("PUT", Some(&tok), "not json")).await.unwrap();
        assert_eq!(garbage.status(), StatusCode::BAD_REQUEST);
    }

    #[tokio::test]
    async fn test_station_settings_get_put_validation_and_policy_lock() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        db.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config SET station_id = '0b8d6c2e-1f3a-4c5b-9d7e-8f9a0b1c2d3e' WHERE id = 1",
                [],
            )
        })
        .unwrap();
        let state = AppState::new(db);
        let tok = state.launch_token.clone();
        let app = build_router(state.clone());
        let req = |method: &str, token: Option<&str>, body: &str| {
            let mut b = Request::builder()
                .method(method)
                .uri("/api/v1/station/settings")
                .header("content-type", "application/json");
            if let Some(t) = token {
                b = b.header("authorization", format!("Bearer {t}"));
            }
            b.body(Body::from(body.to_string())).unwrap()
        };
        let json_of = |resp: Response| async move {
            let bytes = axum::body::to_bytes(resp.into_body(), 1 << 16).await.unwrap();
            serde_json::from_slice::<Value>(&bytes).unwrap()
        };

        assert_eq!(app.clone().oneshot(req("GET", None, "")).await.unwrap().status(), StatusCode::UNAUTHORIZED);
        assert_eq!(app.clone().oneshot(req("PUT", None, "{}")).await.unwrap().status(), StatusCode::UNAUTHORIZED);

        let got = json_of(app.clone().oneshot(req("GET", Some(&tok), "")).await.unwrap()).await;
        assert_eq!(got["coding_mode"], "icd11_doris");
        assert_eq!(got["modules_locked"], false);
        assert!(got["modules"].as_array().unwrap().iter().all(|m| m["enabled"] == true));

        let put = app
            .clone()
            .oneshot(req("PUT", Some(&tok), r#"{"enabled_modules":["social_autopsy"],"coding_mode":"icd10"}"#))
            .await
            .unwrap();
        assert_eq!(put.status(), StatusCode::OK);
        let put = json_of(put).await;
        assert_eq!(put["coding_mode"], "icd10");
        let on: Vec<&str> = put["modules"].as_array().unwrap().iter()
            .filter(|m| m["enabled"] == true).filter_map(|m| m["code"].as_str()).collect();
        assert_eq!(on, ["social_autopsy"]);

        for bad in [r#"{"enabled_modules":["nope"]}"#, r#"{"coding_mode":"icd9"}"#, r#"{"enabled_modules":"abha"}"#, "{}", "not json"] {
            let resp = app.clone().oneshot(req("PUT", Some(&tok), bad)).await.unwrap();
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST, "{bad}");
        }

        let signed = std::fs::read_to_string(
            std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .join("../../../tests/fixtures/station_config/station_config.signed"),
        )
        .unwrap();
        state.db.import_signed_station_config(&signed).unwrap();
        let locked = json_of(app.clone().oneshot(req("GET", Some(&tok), "")).await.unwrap()).await;
        assert_eq!(locked["modules_locked"], true);
        let resp = app.clone().oneshot(req("PUT", Some(&tok), r#"{"enabled_modules":[]}"#)).await.unwrap();
        assert_eq!(resp.status(), StatusCode::CONFLICT);
        assert_eq!(json_of(resp).await["code"], "policy_locked");
        // The fixture's TST001 carries `coding_mode: "icd11_doris"`: it wins over the local icd10.
        assert_eq!((locked["coding_mode"].as_str(), locked["coding_mode_locked"].as_bool()), (Some("icd11_doris"), Some(true)));
        let resp = app.clone().oneshot(req("PUT", Some(&tok), r#"{"coding_mode":"icd10"}"#)).await.unwrap();
        assert_eq!(resp.status(), StatusCode::CONFLICT);
        assert_eq!(json_of(resp).await["code"], "policy_locked");
    }

    /// The server fixture config re-signed with TST001's `coding_mode` set to null.
    fn fixture_config_without_station_coding() -> String {
        let dir = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../tests/fixtures/station_config");
        let signed = std::fs::read_to_string(dir.join("station_config.signed")).unwrap();
        let mut payload: digitva_bundle::StationConfigPayload =
            serde_json::from_str(signed.split('\n').next().unwrap()).unwrap();
        payload.projects[0].coding_mode = Some(None);
        let key = digitva_bundle::StationSigningKey::from_base64url_secret(
            std::fs::read_to_string(dir.join("test_server_signing_key")).unwrap().trim(),
        )
        .unwrap();
        digitva_bundle::format_signed_station_config(&payload, &key).unwrap()
    }

    #[tokio::test]
    async fn test_null_config_coding_mode_refuses_coding_routes() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        db.with_conn(|conn| {
            conn.execute(
                "UPDATE loc_station_config SET station_id = '0b8d6c2e-1f3a-4c5b-9d7e-8f9a0b1c2d3e' WHERE id = 1",
                [],
            )
        })
        .unwrap();
        db.import_signed_station_config(&fixture_config_without_station_coding()).unwrap();
        db.with_conn(|conn| {
            conn.execute(
                "INSERT INTO loc_va_submissions (va_sid, unique_id, project_id, payload_json, payload_fingerprint,
                    submitted_at, updated_at)
                 VALUES ('VA-1', 'VA-1', 'TST001', '{}', 'fp', '2026-10-21T10:00:00Z', '2026-10-21T10:00:00Z')",
                [],
            )
        })
        .unwrap();
        let state = AppState::new(db);
        let tok = state.launch_token.clone();
        let app = build_router(state);
        let call = |method: &str, uri: &str, body: &str| {
            Request::builder()
                .method(method)
                .uri(uri)
                .header("content-type", "application/json")
                .header("authorization", format!("Bearer {tok}"))
                .body(Body::from(body.to_string()))
                .unwrap()
        };
        let json_of = |resp: Response| async move {
            let bytes = axum::body::to_bytes(resp.into_body(), 1 << 16).await.unwrap();
            serde_json::from_slice::<Value>(&bytes).unwrap()
        };

        let settings = json_of(app.clone().oneshot(call("GET", "/api/v1/station/settings", "")).await.unwrap()).await;
        assert_eq!((settings["coding_mode"].clone(), settings["coding_mode_locked"].clone()), (Value::Null, json!(true)));
        let projects = json_of(app.clone().oneshot(call("GET", "/api/v1/coding/projects", "")).await.unwrap()).await;
        assert_eq!((projects["project_options"].clone(), projects["station_coding_disabled"].clone()), (json!([]), json!(true)));
        let queue = json_of(app.clone().oneshot(call("GET", "/api/v1/coding/available", "")).await.unwrap()).await;
        assert_eq!(queue["count"], 0);

        for (method, uri) in [
            ("GET", "/api/v1/va/VA-1/workspace"),
            ("POST", "/api/v1/coding/submissions/VA-1/code-now"),
            ("POST", "/api/v1/coding/finalize/VA-1"),
            ("POST", "/api/v1/coding/not-codeable/VA-1"),
        ] {
            let resp = app.clone().oneshot(call(method, uri, "{}")).await.unwrap();
            assert_eq!(resp.status(), StatusCode::CONFLICT, "{uri}");
            assert_eq!(json_of(resp).await["code"], "station_coding_not_enabled", "{uri}");
        }
        // Viewing the case stays open.
        let view = app.clone().oneshot(call("GET", "/api/v1/va/VA-1/workspace?mode=view", "")).await.unwrap();
        assert_eq!(view.status(), StatusCode::OK);
    }

    #[tokio::test]
    async fn test_station_enrolment_file_needs_the_launch_token_and_has_exactly_the_server_keys() {
        let state = AppState::new(OfflineDatabase::open_in_memory().unwrap());
        let tok = state.launch_token.clone();
        let app = build_router(state);
        let req = |token: Option<&str>| {
            let mut b = Request::builder().uri("/api/v1/station/enrolment-file");
            if let Some(t) = token {
                b = b.header("authorization", format!("Bearer {t}"));
            }
            b.body(Body::empty()).unwrap()
        };

        let refused = app.clone().oneshot(req(None)).await.unwrap();
        assert_eq!(refused.status(), StatusCode::UNAUTHORIZED);

        let resp = app.clone().oneshot(req(Some(&tok))).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        assert!(resp.headers()["content-disposition"].to_str().unwrap().starts_with("attachment"));
        let bytes = axum::body::to_bytes(resp.into_body(), 1 << 16).await.unwrap();
        let file: Value = serde_json::from_slice(&bytes).unwrap();
        let mut keys: Vec<&str> = file.as_object().unwrap().keys().map(String::as_str).collect();
        keys.sort_unstable();
        assert_eq!(keys, ["app_version", "device_id", "signing_public_key"]);
    }

    #[tokio::test]
    async fn test_case_lists_honour_limit_cursor_and_registered() {
        let db = OfflineDatabase::open_in_memory().unwrap();
        for n in 0..3 {
            let reg = json!({
                "project_id": "1",
                "site_id": "PHC01",
                "deceased_name": format!("Case {n}"),
                "deceased_sex": "male",
                "date_of_death": "2026-10-18"
            });
            db.register_death(&reg, "test").unwrap();
        }
        let state = AppState::new(db);
        let tok = state.launch_token.clone();
        let app = build_router(state);
        let get = |uri: &str| {
            Request::builder()
                .uri(uri)
                .header("host", "127.0.0.1:18420")
                .header("authorization", format!("Bearer {tok}"))
                .body(Body::empty())
                .unwrap()
        };
        let body = |resp: Response| async move {
            let bytes = axum::body::to_bytes(resp.into_body(), 1 << 20).await.unwrap();
            serde_json::from_slice::<Value>(&bytes).unwrap()
        };

        let resp = app.clone().oneshot(get("/api/v1/intake/deaths?limit=2&registered=mine")).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let page = body(resp).await;
        assert_eq!(page["deaths"].as_array().unwrap().len(), 2);
        assert_eq!(page["next_cursor"], "2");
        assert!(page.get("cases").is_none());

        let resp = app.clone().oneshot(get("/api/v1/intake/cases?limit=2&cursor=2")).await.unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        let page = body(resp).await;
        assert_eq!(page["cases"].as_array().unwrap().len(), 1);
        assert!(page["next_cursor"].is_null());
        assert_eq!(page["counts"]["total"], 3);

        for bad in [
            "/api/v1/intake/deaths?limit=abc",
            "/api/v1/intake/deaths?registered=all",
            "/api/v1/intake/cases?cursor=not-a-cursor",
        ] {
            let resp = app.clone().oneshot(get(bad)).await.unwrap();
            assert_eq!(resp.status(), StatusCode::BAD_REQUEST, "{bad}");
            let refusal = body(resp).await;
            assert_eq!(refusal["code"], "invalid_request", "{bad}");
            assert!(!refusal["error"].as_str().unwrap().contains("not-a-cursor"));
        }
    }

    #[tokio::test]
    async fn test_form_routes_definition_etag_home_and_draft_autosave() {
        let state = AppState::new(OfflineDatabase::open_in_memory().unwrap());
        let tok = state.launch_token.clone();
        let app = build_router(state);
        let req = |method: &str, uri: &str, extra: Option<(&str, String)>, body: Option<Value>| {
            let mut b = Request::builder()
                .method(method)
                .uri(uri)
                .header("host", "127.0.0.1:18420")
                .header("authorization", format!("Bearer {tok}"));
            if let Some((name, value)) = extra {
                b = b.header(name, value);
            }
            match body {
                Some(v) => b.header("content-type", "application/json").body(Body::from(v.to_string())).unwrap(),
                None => b.body(Body::empty()).unwrap(),
            }
        };
        let json_of = |resp: Response| async move {
            let bytes = axum::body::to_bytes(resp.into_body(), 4 << 20).await.unwrap();
            serde_json::from_slice::<Value>(&bytes).unwrap()
        };

        // A server project before any config: a clear refusal, not a stub form.
        let resp = app.clone().oneshot(req("GET", "/api/v1/organization/TST001/form-options", None, None)).await.unwrap();
        assert_eq!(resp.status(), StatusCode::NOT_FOUND);
        assert_eq!(json_of(resp).await["code"], "form_policy_missing");

        let options = json_of(app.clone().oneshot(req("GET", "/api/v1/organization/1/form-options", None, None)).await.unwrap()).await;
        let sha = options["definition_sha256"].as_str().unwrap().to_string();
        let resp = app.clone().oneshot(req("GET", "/api/v1/instruments/WHO_2022_VA/definition", None, None)).await.unwrap();
        assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
        let resp = app
            .clone()
            .oneshot(req("GET", "/api/v1/instruments/WHO_2022_VA/definition?project_id=1", None, None))
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(resp.headers()["x-definition-sha256"], sha.as_str());
        let bytes = axum::body::to_bytes(resp.into_body(), 4 << 20).await.unwrap();
        assert_eq!(digitva_bundle::sha256_hex(&bytes), sha);
        let resp = app
            .clone()
            .oneshot(req(
                "GET",
                "/api/v1/instruments/WHO_2022_VA/definition?project_id=1",
                Some(("if-none-match", format!("\"{sha}\""))),
                None,
            ))
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::NOT_MODIFIED);

        let home = json_of(app.clone().oneshot(req("GET", "/api/v1/me/home", None, None)).await.unwrap()).await;
        assert!(home["roles"].is_array());
        assert!(home["blocks"].is_object());

        let started = json_of(
            app.clone()
                .oneshot(req("POST", "/api/v1/intake/drafts", None, Some(json!({ "project_id": "1", "site_id": "PHC01" }))))
                .await
                .unwrap(),
        )
        .await;
        let draft_id = started["draft"]["draft_id"].as_str().unwrap().to_string();
        let resp = app
            .clone()
            .oneshot(req(
                "PATCH",
                &format!("/api/v1/intake/drafts/{draft_id}"),
                None,
                Some(json!({ "sections": { "s1": { "Id10007": "R" } }, "meta": { "definitionSha256": sha } })),
            ))
            .await
            .unwrap();
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(json_of(resp).await["saved_sections"], 1);

        // A config of several MB (every locale's translations) reaches the verifier, not a 413.
        let big = "x".repeat(3 << 20);
        let resp = app
            .clone()
            .oneshot(
                Request::builder()
                    .method("POST")
                    .uri("/api/v1/station/config/signed")
                    .header("host", "127.0.0.1:18420")
                    .header("authorization", format!("Bearer {tok}"))
                    .body(Body::from(big))
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_ne!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
        assert!(resp.status().is_client_error(), "{}", resp.status());
    }
}
