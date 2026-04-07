---
title: Security Audit — data_management.py + api/data_management.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `app/routes/data_management.py` + `app/routes/api/data_management.py` — Security Audit

## Routes Overview

### Page routes (`data_management.py`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/dm/dashboard` | data_manager, admin |
| GET | `/dm/submissions` | data_manager, admin |
| GET | `/dm/submission/<va_sid>` | data_manager, admin |
| GET | `/dm/kpi` | data_manager, admin |
| GET | `/dm/users` | data_manager, admin |
| GET | `/dm/user/<user_id>` | data_manager, admin |
| GET | `/dm/settings` | data_manager, admin |
| GET | `/dm/smartva` | data_manager, admin |
| GET | `/dm/reports` | data_manager, admin |
| GET/POST | `/dm/users/grant` | data_manager, admin |
| GET/POST | `/dm/users/revoke` | data_manager, admin |
| GET/POST | `/dm/users/update` | data_manager, admin |
| GET | `/dm/reports/export` | data_manager, admin |
| GET | `/dm/reports/submission/<va_sid>` | data_manager, admin |

### API routes (`api/data_management.py`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/dm/users` | data_manager, admin |
| GET | `/api/v1/dm/user/<user_id>` | data_manager, admin |
| POST | `/api/v1/dm/users/grant` | data_manager, admin |
| POST | `/api/v1/dm/users/revoke` | data_manager, admin |
| POST | `/api/v1/dm/users/update` | data_manager, admin |
| GET | `/api/v1/dm/submissions` | data_manager, admin |
| GET | `/api/v1/dm/submission/<va_sid>` | data_manager, admin |

---

## SEC-001 (shared) — Exception strings leaked in API responses

**Severity:** HIGH  
**File:** `api/data_management.py`

**Affected lines:**

| Line | Pattern | HTTP Status |
|------|---------|-------------|
| 300 | `jsonify({"error": str(exc)})` | 403 |
| 302 | `jsonify({"error": str(exc)})` | 404 |
| 329 | `jsonify({"error": str(exc)})` | 500 |
| 424 | `jsonify({"error": str(exc)})` | 500 |
| 524 | `jsonify({"error": str(exc)})` | 500 |
| 541 | `jsonify({"error": str(exc)})` | 403 |
| 543 | `jsonify({"error": str(exc)})` | 400 |
| 547 | `jsonify({"error": str(exc)})` | 500 |
| 574 | `jsonify({"error": str(exc)})` | 403 |
| 576 | `jsonify({"error": str(exc)})` | 400 |
| 580 | `jsonify({"error": str(exc)})` | 500 |
| 592 | `jsonify({"error": str(exc)})` | 403 |
| 594 | `jsonify({"error": str(exc)})` | 400 |
| 598 | `jsonify({"error": str(exc)})` | 500 |
| 615 | `jsonify({"error": str(exc)})` | 403 |
| 617 | `jsonify({"error": str(exc)})` | 400 |
| 621 | `jsonify({"error": str(exc)})` | 500 |

Unlike `admin.py`, the `api/data_management.py` routes are accessible to `data_manager`
role users, not just admins. This elevates the risk: a malicious or compromised data manager
account can use these error messages to probe the internal schema.

Also in `data_management.py` (page routes), line 625:

```python
return _json_error(str(exc), 400)
```

**Recommendation:** Same as SEC-001 in `02-admin.md` — log server-side, return generic
message. For 403/404 these could be domain-level exceptions (PermissionError,
LookupError); capture their human-readable `args[0]` rather than `str(exc)` which may
include internals, or define typed application exceptions with safe message strings.

---

## No additional findings

All page routes use `@role_required("data_manager", "admin")` consistently. No unprotected
routes were found. Submission access is further gated by the DM's project/site scope
(enforced in service layer). No raw SQL interpolation found.

---

## Positive Controls Verified

- `@role_required("data_manager", "admin")` on every route.
- Submission retrieval scoped to `current_user`'s project/site grants — no global listing.
- `VaSubmissionsAuditlog` entries emitted on user grant/revoke actions.
- Export route (`/dm/reports/export`) enforces scope before generating CSV.
- No file-system path parameters accepted from user input in page routes.
