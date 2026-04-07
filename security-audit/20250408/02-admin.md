---
title: Security Audit — admin.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `app/routes/admin.py` — Security Audit

This is the largest route file (~4700+ lines). All routes in this file are guarded by
`@role_required("admin")` at the blueprint level, so broken-access-control findings here
are limited to intra-admin privilege escalation. The main finding is widespread information
disclosure via exception strings in API error responses.

## Routes Overview (by section)

| Section | Prefix | Auth |
|---------|--------|------|
| User management | `/admin/api/users/*` | admin |
| Project/site management | `/admin/api/project-sites/*` | admin |
| Field mapping | `/admin/api/field-mapping/*` | admin |
| ODK sync control | `/admin/api/sync/*` | admin |
| SmartVA management | `/admin/api/smartva/*` | admin |
| Payload backfill | `/admin/api/payload-backfill/*` | admin |
| Progress/stats | `/admin/api/progress/*` | admin |
| Page routes | `/admin/*` | admin |

---

## SEC-001 — Exception strings leaked to API responses

**Severity:** HIGH  
**File:** `admin.py` (23 occurrences) + `api/data_management.py` (10 occurrences)

**Description:**  
Raw Python exception messages are returned directly to the API client via `str(e)` /
`str(exc)`. This exposes:

- Database schema details (table names, column names from SQLAlchemy errors)
- Internal file paths (from OS-level errors)
- Connection string fragments (from Redis/DB connection errors)
- Stack-trace excerpts embedded in exception messages

**Affected lines in `admin.py`:**

| Line | Pattern | HTTP Status |
|------|---------|-------------|
| 1469 | `_json_error(str(exc), 400)` | 400 |
| 2221 | `_json_error(str(e), 409)` | 409 |
| 2273 | `_json_error(str(e), 409)` | 409 |
| 2290 | `_json_error(str(e), 404)` | 404 |
| 2344 | `_json_error(str(e), 409)` | 409 |
| 3042 | `_json_error(str(exc), 500)` | 500 |
| 3105 | `_json_error(str(exc), 500)` | 500 |
| 3185 | `jsonify({"ok": False, "message": str(exc)})` | 200 |
| 3810 | `_json_error(f"Failed to load sync status: {str(e)}", 500)` | 500 |
| 3834 | `_json_error(f"Failed to load sync history: {str(e)}", 500)` | 500 |
| 3863 | `_json_error(f"Failed to trigger sync: {str(e)}", 500)` | 500 |
| 3908 | `_json_error(f"Failed to trigger attachment backfill: {str(e)}", 500)` | 500 |
| 3967 | `_json_error(f"Failed to stop sync: {str(e)}", 500)` | 500 |
| 4023 | `_json_error(f"Could not update schedule: {str(e)}", 503)` | 503 |
| 4130 | `_json_error(f"Failed to load coverage data: {str(e)}", 500)` | 500 |
| 4333 | `_json_error(f"Failed to load backfill stats: {str(e)}", 500)` | 500 |
| 4374 | `_json_error(f"Failed to trigger backfill for form {form_id}: {str(e)}", 500)` | 500 |
| 4401 | `_json_error(f"Failed to trigger SmartVA run: {str(e)}", 500)` | 500 |
| 4426 | `_json_error(f"Failed to trigger Force-resync for form {form_id}: {str(e)}", 500)` | 500 |
| 4477 | `f"Failed to trigger sync for project/site {project_id}/{site_id}: {str(e)}"` | 500 |
| 4586 | `_json_error(f"Failed to load SmartVA stats: {str(e)}", 500)` | 500 |
| 4685 | `_json_error(f"Failed to load revoked stats: {str(e)}", 500)` | 500 |
| 4730 | `_json_error(f"Failed to load progress: {str(e)}", 500)` | 500 |

**Mitigation is partially in place** because these routes require `admin` role — a
compromised admin session is the main threat. However, defence-in-depth and compliance
best practices require that internal details never leave the server boundary.

**Recommendation:**  
Create a helper that logs the full exception server-side and returns a sanitised message:

```python
import logging
log = logging.getLogger(__name__)

def _safe_error(context: str, exc: Exception, status: int):
    log.error("%s: %s", context, exc, exc_info=True)
    return _json_error(f"{context}. See server logs for details.", status)
```

Replace all `_json_error(str(e), ...)` and `_json_error(f"... {str(e)}", ...)` with
`_safe_error("context message", e, status)`.

---

## SEC-012 — No explicit admin-action audit log

**Severity:** LOW  
**Routes:** All `POST/PUT/DELETE` in `/admin/api/*`

**Description:**  
The admin blueprint performs destructive and privileged operations (user creation/deletion,
ODK credential changes, sync triggers, SmartVA resets, field-mapping overrides). These are
not individually audit-logged in a way that lets an operator answer "who did what and when."
The application has `VaSubmissionsAuditlog` for submission-level events, but no equivalent
for admin-panel actions.

**Recommendation:**  
Add an `AdminAuditLog` model (or extend the existing audit log) and emit an entry on every
state-changing admin API call, capturing: `user_id`, `action`, `target_id`, `timestamp`,
`request_ip`.

---

## Positive Controls Verified

- Every route in this blueprint is decorated with `@role_required("admin")`.
- Sort field names are whitelisted against an allowlist dict (`_SORT_FIELDS`) — no SQL
  injection via sort parameters.
- User creation flow hashes passwords before storage; plaintext is never persisted.
- ODK credentials are stored encrypted via `credential_crypto.py` (pepper from env var).
- Pagination parameters are cast to `int` before use in queries.
