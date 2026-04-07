---
title: Security Audit — coding.py + api/coding.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# `app/routes/coding.py` + `app/routes/api/coding.py` — Security Audit

## Routes Overview

### Page routes (`coding.py`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/coding/` | coder, admin |
| GET | `/coding/form/<form_id>` | coder, admin |
| GET | `/coding/pick` | coder, admin |
| POST | `/coding/pick` | coder |
| POST | `/coding/unpick` | coder |
| GET | `/coding/admin-demo` | admin |
| GET | `/coding/form/<form_id>/submission/<va_sid>` | coder, admin |

### API routes (`api/coding.py`)

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/coding/next` | coder, admin |
| GET | `/api/v1/coding/next/<form_id>` | coder, admin |
| POST | `/api/v1/coding/release` | coder |
| POST | `/api/v1/coding/mark-unavailable` | admin |
| POST | `/api/v1/coding/mark-available` | admin |
| GET | `/api/v1/coding/pick-mode-forms` | coder, admin |
| GET | `/api/v1/coding/progress` | coder, admin |
| GET | `/api/v1/coding/projects` | coder, admin |
| GET | `/api/v1/coding/debug-stats` | coder, admin |

---

## SEC-007 — `/api/v1/coding/debug-stats` exposes user PII and full scope

**Severity:** MEDIUM  
**Route:** `GET /api/v1/coding/debug-stats`  
**Lines:** 240–360 (`api/coding.py`)

**Description:**  
The endpoint is intended as a diagnostics tool but is accessible to any user with the
`coder` role (not just admins). It returns:

- `current_user.email` — PII
- All `form_id` values in the coder's scope (could be used to enumerate form access)
- Internal workflow state counts
- Language filter configuration

```python
return jsonify({
    "user": {
        "user_id": str(current_user.user_id),
        "email": current_user.email,   # ← PII in API response
        "is_admin": bool(current_user.is_admin()),
    },
    "coder_scope": {
        "form_ids": form_ids,          # ← full scope enumeration
        ...
    },
    ...
})
```

A coder should not need their own email returned in a JSON response. The full `form_ids`
list exposes the coder's exact assignment scope.

**Recommendation:**  
Either:
1. Restrict this endpoint to `admin` only (`@role_required("admin")`), or  
2. Remove `email` from the response and limit `form_ids` to counts only for coders, or  
3. Remove the endpoint entirely once it is no longer needed for debugging.

---

## No additional findings

- All page and API routes consistently use `@role_required`.
- Submission access in `/coding/form/<form_id>/submission/<va_sid>` is validated through
  `@va_validate_permissions()` which checks form ownership before serving.
- The `pick`/`unpick` workflow is scoped to `current_user` — no IDOR risk.
- Sort and filter inputs are whitelisted.

---

## Positive Controls Verified

- `@role_required` on every route (coder, admin as appropriate).
- `/api/v1/coding/next` allocates a submission scoped to the requesting coder's form
  access list — no cross-coder IDOR.
- `mark-unavailable` / `mark-available` restricted to `admin` only (lines 156, 167).
- No raw SQL interpolation found.
