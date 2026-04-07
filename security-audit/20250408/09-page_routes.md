---
title: Security Audit — va_form.py, va_main.py, sitepi.py, profile.py, health.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# Page Routes — Security Audit

## Files Covered

| File | Primary Purpose |
|------|----------------|
| `va_form.py` | VA submission form rendering and file serving |
| `va_main.py` | Public landing pages, project/site index |
| `sitepi.py` | Site PI dashboard and views |
| `profile.py` | User profile page |
| `health.py` | Health-check endpoint |

---

## `va_form.py`

### Routes

| Method | Path | Auth |
|--------|------|------|
| GET | `/form/<form_id>` | `@va_validate_permissions()` |
| GET | `/form/<form_id>/submission/<va_sid>` | `@va_validate_permissions()` |
| POST | `/form/<form_id>/submission/<va_sid>/save` | `@va_validate_permissions()` |
| GET | `/form/<form_id>/submission/<va_sid>/attachment/<filename>` | `@va_validate_permissions()` |

### No security findings

**Path traversal protection verified (lines ~1189–1194):**  
Attachment serving uses `os.path.realpath()` to resolve the absolute path and checks that
it starts with the expected attachment directory. This prevents directory traversal attacks.

```python
real_path = os.path.realpath(attachment_path)
if not real_path.startswith(os.path.realpath(expected_dir)):
    abort(403)
```

**Access control:** `@va_validate_permissions()` decorator validates that the current user
has access to the specific form and submission before serving any content.

**No raw SQL interpolation** found.

---

## `va_main.py`

### Routes

| Method | Path | Auth |
|--------|------|------|
| GET | `/` | Public |
| GET | `/about` | Public |
| GET | `/projects` | `@login_required` |

### No security findings

Public routes serve only static content. Authenticated routes scope project listing to
`current_user`.

---

## `sitepi.py`

### Routes

| Method | Path | Auth |
|--------|------|------|
| GET | `/sitepi/` | `@role_required("site_pi")` |
| GET | `/sitepi/submissions` | `@role_required("site_pi")` |

### No security findings

All routes protected by `@role_required("site_pi")`. Data scoped to the site PI's assigned
sites — no cross-site data leakage.

---

## `profile.py`

### Routes

| Method | Path | Auth |
|--------|------|------|
| GET/POST | `/profile` | `@login_required` |

### No security findings

Profile page only shows and updates the current user's own data.

---

## `health.py`

### SEC-014 — Health endpoint is unauthenticated

**Severity:** INFO  
**Route:** `GET /health`

**Description:**  
The `/health` endpoint is publicly accessible without authentication. It is a standard
operational practice for load-balancer health checks, but depending on what it returns, it
may expose internal service information.

**What to check:** Verify that `/health` does NOT return:
- Database version strings
- Dependency versions
- Internal hostnames or IP addresses
- Service topology

If it returns only `{"status": "ok"}` or similar, this is acceptable and standard.

**Recommendation:** Audit the response payload of `/health` and ensure only operational
status (up/down) is returned without internal system details.

---

## Positive Controls Verified

- File serving has path-traversal guard via `os.path.realpath()` comparison.
- `@va_validate_permissions()` provides submission-level access control.
- `secure_filename()` used on upload filenames.
- No user-controlled data rendered without escaping in templates.
