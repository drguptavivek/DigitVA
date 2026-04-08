---
title: OWASP Top 10 (2021) Security Audit — DigitVA
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# OWASP Top 10 (2021) — DigitVA Security Audit

Conducted: 2026-04-07. Scope: full codebase including routes, services, utils, config, docker-compose, templates.

## Summary

| OWASP Category | Verdict | Findings |
|---------------|---------|----------|
| A01 Broken Access Control | Issues Found | 3 |
| A02 Cryptographic Failures | Clean | — |
| A03 Injection | Clean | — |
| A04 Insecure Design | Issues Found | 3 |
| A05 Security Misconfiguration | Issues Found | 4 |
| A06 Vulnerable & Outdated Components | Clean | — |
| A07 Identification & Authentication | Issues Found | 2 |
| A08 Software & Data Integrity | Clean | — |
| A09 Security Logging & Monitoring | Issues Found | 3 |
| A10 Server-Side Request Forgery | Issues Found | 1 |

## Findings Index

| ID | Sev | Category | Title | Status |
|----|-----|----------|-------|--------|
| OW-001 | **HIGH** | A01/A10 | SSRF via unvalidated ODK base URL | Open |
| OW-002 | **MEDIUM** | A01 | Legacy media endpoint — form-level check, not submission-level | Open |
| OW-003 | **MEDIUM** | A01 | Grant mutation has no decorator-level re-validation | Open |
| OW-004 | **MEDIUM** | A05 | Redis exposed on host port 6379 without auth | Open |
| OW-005 | **MEDIUM** | A05 | No explicit Docker internal network isolation | Open |
| OW-006 | **MEDIUM** | A05 | Celery broker/backend unauthenticated | Open |
| OW-007 | **MEDIUM** | A07 | Login brute-force protection is IP-only, not email-keyed | Open |
| OW-008 | **MEDIUM** | A09 | Auth denials not logged — no detection of privilege escalation attempts | Open |
| OW-009 | **MEDIUM** | A09 | Admin grant create/revoke not audit-logged | Open |
| OW-010 | **LOW** | A04 | Allocation endpoint has no rate limit | Open |
| OW-011 | **LOW** | A04 | `odk_project_id` int conversion has no range validation | Open |
| OW-012 | **LOW** | A04 | `demo_retention_minutes` has no upper bound | Open |
| OW-013 | **LOW** | A05 | CSP `unsafe-inline` weakens XSS protection | Ignored |
| OW-014 | **LOW** | A07 | Session not explicitly cleared before `login_user()` | Open |
| OW-015 | **LOW** | A09 | Response bodies partially written to access log — potential PII | Open |

---

## A01: Broken Access Control

### OW-001 — SSRF via unvalidated ODK base URL `[HIGH]`

**Files:** `app/routes/admin.py` (ODK connection create ~line 3040, update ~line 3096)

**Description:**
The ODK connection create and update endpoints accept an arbitrary `base_url` from the request payload and use it directly to make outbound HTTP requests (authentication test, sync). There is no validation that the URL points to a real ODK Central instance and not to:
- Internal network addresses (10.x.x.x, 172.16.x.x, 192.168.x.x)
- Loopback (127.0.0.1, localhost, ::1)
- Cloud metadata services (169.254.169.254 — AWS/GCP/Azure IMDSv1)
- Other internal services (Redis on :6379, Postgres on :5432)

**Exploit scenario:**
Admin sets `base_url = "http://169.254.169.254/latest/meta-data/"`. When a sync is triggered, the app fetches that URL and the response may appear in error messages or logs, leaking cloud credentials.
Alternatively: `base_url = "http://127.0.0.1:6379/"` probes Redis with an HTTP-shaped request.

**Recommendation:**
Add URL validation on both create and update before the value is persisted:

```python
import ipaddress
from urllib.parse import urlparse

def _validate_odk_base_url(raw: str) -> str:
    try:
        parsed = urlparse(raw)
    except Exception:
        raise ValueError("Malformed URL.")
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Only http/https schemes are allowed.")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("Missing hostname.")
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError("Private/loopback/link-local addresses are not allowed.")
    except ValueError as exc:
        if hostname in ("localhost", "metadata.google.internal"):
            raise ValueError("Reserved hostname not allowed.") from exc
    return raw.rstrip("/")
```

Call `_validate_odk_base_url(base_url)` before `conn.base_url = ...` in both handlers.

---

### OW-002 — Legacy media endpoint checks form-level access, not submission-level `[MEDIUM]`

**File:** `app/routes/va_form.py` (legacy `/media/<va_form_id>/<va_filename>` endpoint)

**Description:**
The endpoint calls `current_user.has_va_form_access(va_form_id)` — this grants access to any file in any submission within that form. A coder assigned to form F001 can request files from submissions allocated to other coders in the same form.

**Exploit scenario:**
Coder A is assigned to F001. They know the filename convention for submission audio files and enumerate `GET /media/F001/<other_submission>.mp3`, accessing PII from submissions not assigned to them.

**Recommendation:**
Resolve the `va_sid` from the filename or require it in the route, then verify the caller has access to that specific submission, not just the form.

---

### OW-003 — Grant mutation endpoints have no decorator-level re-validation `[MEDIUM]`

**File:** `app/routes/data_management.py` (grant toggle/create/delete endpoints ~lines 59–89)

**Description:**
Access control for grant mutations relies on `_dm_can_manage_scope()` being called inside the handler body. There is no enforcement at the decorator level. A future refactor that forgets this call silently removes access control with no compiler or linter warning.

**Recommendation:**
Wrap `_dm_can_manage_scope` in a decorator so it is structurally unskippable:

```python
def require_dm_scope_check(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        payload = request.get_json(silent=True) or {}
        try:
            role, scope_type, project_id, site_id = _resolve_scope_from_payload(payload)
        except ValueError as exc:
            return _json_error(str(exc), 400)
        ok, msg = _dm_can_manage_scope(current_user, role, scope_type, project_id, site_id)
        if not ok:
            abort(403)
        return f(*args, **kwargs)
    return wrapper
```

---

## A02: Cryptographic Failures

**Verdict: Clean.**

Verified:
- ODK credentials: PBKDF2-HMAC-SHA256 (260,000 iterations) + Fernet (AES-128-CBC + HMAC-SHA256). Pepper environment-separated. (`app/utils/credential_crypto.py`)
- Passwords: Werkzeug `generate_password_hash` / `check_password_hash` (scrypt or pbkdf2:sha256 with salt).
- Tokens: `itsdangerous.URLSafeTimedSerializer` with purpose-specific salts and expiry. (`app/services/token_service.py`)
- Session cookies: HttpOnly, Secure, SameSite=Lax, signed.
- `SECRET_KEY` and `DATABASE_URL` enforced via `_require_env()`.

---

## A03: Injection

**Verdict: Clean.**

Verified:
- All DB queries use SQLAlchemy ORM parameterized calls — no raw `text()` with user input found.
- `ilike(f"%{sid}%")` patterns are safe — SQLAlchemy passes the entire argument as a bound parameter.
- No `render_template_string()` calls found.
- No `|safe` filter applied to user-supplied data in templates.
- File paths sanitized with `secure_filename()` + `os.path.realpath()` guard.
- No `subprocess` calls with `shell=True` and user-controlled data found.

---

## A04: Insecure Design

### OW-010 — Allocation endpoint has no rate limit `[LOW]`

**File:** `app/routes/api/coding.py` (`POST /api/v1/coding/allocation`)

**Description:**
The submission allocation endpoint is not rate-limited. Rapid repeated calls could cause contention on the submission workflow state machine or exhaust the pool of allocatable submissions.

**Recommendation:** Add `@limiter.limit("30 per minute")`.

---

### OW-011 — `odk_project_id` int conversion has no range validation `[LOW]`

**File:** `app/routes/admin.py` (~line 2959)

**Description:**
`int(odk_project_id)` is called directly on user input without bounding. Extremely large values could cause issues in downstream integer columns.

**Recommendation:**
```python
try:
    odk_project_id_int = int(odk_project_id)
    if not (1 <= odk_project_id_int <= 2_147_483_647):
        raise ValueError
except (ValueError, TypeError):
    return _json_error("Invalid odk_project_id.", 400)
```

---

### OW-012 — `demo_retention_minutes` has no upper bound `[LOW]`

**File:** `app/routes/admin.py` (~line 743)

**Description:**
`max(int(...), 1)` clamps the minimum but not the maximum. An admin could set an arbitrarily large value.

**Recommendation:** `max(1, min(int(payload.get("demo_retention_minutes") or 10), 10_080))` (cap at 7 days).

---

## A05: Security Misconfiguration

### OW-004 — Redis exposed on host port 6379 without authentication `[MEDIUM]`

**File:** `docker-compose.yml`

**Description:**
```yaml
minerva_redis_service:
    image: redis:7
    ports:
      - "6379:6379"
```
Redis is bound to all host interfaces with no password. Anyone who can reach the Docker host on port 6379 can read/write session data, cache entries, and Celery task queues without credentials.

**Recommendation:**
- Remove `ports: ["6379:6379"]` — Redis only needs to be reachable within the Compose network.
- Add `command: redis-server --requirepass ${REDIS_PASSWORD}` and update `REDIS_URL` to include the password.

---

### OW-005 — No explicit Docker internal network isolation `[MEDIUM]`

**File:** `docker-compose.yml`

**Description:**
No `networks:` block is defined. All services share the default bridge network. Depending on host Docker configuration this may allow unexpected inter-container or host communication.

**Recommendation:**
```yaml
networks:
  internal:
    driver: bridge

services:
  minerva_app_service:
    networks: [internal]
  minerva_db_service:
    networks: [internal]
  minerva_redis_service:
    networks: [internal]
```
Expose only the app's HTTP port externally.

---

### OW-006 — Celery broker and result backend unauthenticated `[MEDIUM]`

**File:** `config.py` lines 103–108

**Description:**
Celery uses Redis as broker/backend. If Redis is reachable without auth (OW-004), an attacker can enqueue arbitrary tasks (e.g., trigger ODK syncs for attacker-controlled connections) or read task results containing submission IDs and user data.

**Recommendation:**
Securing Redis with a password (OW-004 fix) is the primary mitigation. Additionally, enforce JSON-only serialization:
```python
"task_serializer": "json",
"accept_content": ["json"],
"result_serializer": "json",
```

---

### OW-013 — CSP `unsafe-inline` weakens XSS protection `[LOW / Ignored]`

**File:** `app/__init__.py` line 94

Per product decision (SEC-008). Recorded for completeness.

---

## A06: Vulnerable and Outdated Components

**Verdict: Clean.**

Key versions from `pyproject.toml`:

| Package | Version |
|---------|---------|
| Flask | ≥ 3.1.0 |
| Werkzeug | ≥ 3.1.0 |
| SQLAlchemy | ≥ 2.0 |
| Flask-WTF | ≥ 1.2.2 |
| Flask-Login | ≥ 0.6.3 |
| cryptography | ≥ 42.0.0 |

All dependencies pinned via `uv.lock`. No known critical CVEs in current set. `pyodk==1.2.1` should be reviewed periodically.

---

## A07: Identification and Authentication Failures

### OW-007 — Login brute-force limit is IP-only `[MEDIUM]`

**File:** `app/routes/va_auth.py` line 14

**Description:**
The existing `10 per minute` POST limit throttles by IP address. A distributed credential-stuffing attack using many IPs bypasses this entirely and can brute-force any single user's account.

**Recommendation:**
Add a secondary per-email limit:

```python
@va_auth.route("/valogin", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", methods=["POST"],
               key_func=lambda: (request.form.get("email") or "").lower().strip())
def va_login():
    ...
```

---

### OW-014 — Session not explicitly cleared before `login_user()` `[LOW]`

**File:** `app/routes/va_auth.py` line 41

**Description:**
Flask-Login performs internal session rotation, but an explicit `session.clear()` before `login_user()` is a defence-in-depth measure against session fixation. Without it, any data set in the session before authentication (e.g., by a middleware or a pre-login request) persists into the authenticated session.

**Recommendation:**
```python
session.clear()          # drop any pre-login session state
session.permanent = True
login_user(user, remember=form.remember_me.data)
```

---

## A08: Software and Data Integrity Failures

**Verdict: Clean.**

Verified:
- Flask-WTF CSRF on all state-changing forms.
- ODK sync payloads validated against model types before persistence.
- No unsafe deserialization (no `yaml.load()` without `Loader`, no `marshal`, no binary serialization of untrusted data).
- Celery task parameters are primitive types (strings, UUIDs) — no arbitrary object deserialization.
- File uploads: `secure_filename()` + content addressed by hash, not original name.

---

## A09: Security Logging and Monitoring Failures

### OW-008 — Auth denials not logged `[MEDIUM]`

**File:** `app/decorators.py` (`role_required` decorator)

**Description:**
When `@role_required` rejects a request (wrong role, inactive user, unauthenticated), no log entry is written. An attacker probing endpoints or attempting privilege escalation leaves no trace in the application logs.

**Recommendation:**
Add a `log.warning(...)` in each rejection branch of `role_required`:

```python
log.warning(
    "Access denied path=%s method=%s user=%s required_roles=%s ip=%s",
    request.path,
    request.method,
    current_user.get_id() if current_user.is_authenticated else "anonymous",
    roles,
    request.remote_addr,
)
```

---

### OW-009 — Admin grant create/revoke not audit-logged `[MEDIUM]`

**File:** `app/routes/admin.py` (grant management endpoints)

**Description:**
User access grants are created and revoked with no persistent audit record. There is no way to answer "who granted user X access to project Y and when?" from logs or the database.

`VaSubmissionsAuditlog` exists for submission events. An equivalent mechanism is absent for grant lifecycle events.

**Recommendation:**
Add a `VaGrantAuditlog` table (or extend the existing audit log) and emit an entry from every grant create/revoke endpoint: actor user ID, target user ID, role, scope, action, timestamp, request IP.

---

### OW-015 — Response bodies partially written to access log `[LOW]`

**File:** `app/logging/va_logger.py`

**Description:**
The request/response logger writes the first few lines of response bodies to the access log. Endpoints that return submission data, user PII, or ICD-10 coding results will have that data in the log file.

**Recommendation:**
Restrict response logging to HTTP status code + content-type + byte count. Remove body logging, or apply an allowlist of safe content-types (e.g., only log body for well-known safe responses like `{"ok": true}`).

---

## A10: Server-Side Request Forgery (SSRF)

### OW-001 (cross-reference)

See **OW-001** under A01. The ODK base URL validation gap is the sole SSRF vector found.

---

## Positive Controls Verified (OWASP scope)

- **A01**: `@role_required` consistently applied; per-user submission scoping enforced.
- **A02**: PBKDF2-260k + Fernet for ODK creds; strong password hashing; signed tokens with expiry.
- **A03**: SQLAlchemy ORM parameterization throughout; no template injection; path-traversal guards.
- **A05**: Flask-Talisman headers (HSTS, nosniff, X-Frame); `_require_env()` prevents silent misconfiguration.
- **A06**: All dependencies recent and pinned.
- **A07**: Email enumeration prevented on all auth endpoints; open-redirect guarded.
- **A08**: CSRF global; no unsafe deserialization; file uploads sanitized and content-addressed.
- **A09**: `VaSubmissionsAuditlog` tracks submission state transitions; PII fields masked in request logs.
