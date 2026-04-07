---
title: Security Audit — Remediation Plan
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# Remediation Plan

## Priority 1 — Immediate (before next release)

### SEC-001: Strip `str(e)` from all API error responses

**Files:** `admin.py` (23 sites), `api/data_management.py` (17 sites), `data_management.py` (1 site), `api/dm_kpi/dm_kpi_scope.py` (1 site)  
**Effort:** ~2 hours

**Action:**  
Add a shared helper (e.g., in `app/utils/api_helpers.py`):

```python
import logging
log = logging.getLogger(__name__)

def safe_api_error(context: str, exc: Exception, status: int):
    """Log full exception server-side; return a generic message to the client."""
    log.error("[API Error] %s: %s", context, exc, exc_info=True)
    from flask import jsonify
    return jsonify({"error": f"{context}. Check server logs for details."}), status
```

Then do a global search-and-replace:
- `_json_error(str(e), N)` → `safe_api_error("context", e, N)`
- `_json_error(f"... {str(e)}", N)` → `safe_api_error("context", e, N)`
- `jsonify({"error": str(exc)})` → `safe_api_error("context", exc, N)`

---

### SEC-002: Remove `SECRET_KEY` hardcoded fallback

**File:** `config.py` line 26  
**Effort:** 5 minutes

```python
# Before
SECRET_KEY = os.environ.get("SECRET_KEY") or "5Ag92#2g]oLIHEk"

# After
SECRET_KEY = _require_env("SECRET_KEY")
```

Verify `.env` has `SECRET_KEY` set. Check Docker Compose environment block.

---

### SEC-003: Remove hardcoded DB URL fallback

**File:** `config.py` lines 45–48  
**Effort:** 5 minutes

```python
# Before
SQLALCHEMY_DATABASE_URI = (
    os.environ.get("DATABASE_URL")
    or "postgresql://minerva:minerva@localhost:5432/minerva"
)

# After
SQLALCHEMY_DATABASE_URI = _require_env("DATABASE_URL")
```

Add `DATABASE_URL` to `.env.example` for developer documentation.

---

## Priority 2 — Short-term (within 2 weeks)

### SEC-004/005: Tighten token-endpoint rate limits

**File:** `va_auth.py` lines 88, 140  
**Effort:** 10 minutes

```python
# reset-password — apply to POST only at a tighter rate
@limiter.limit("5 per minute", methods=["POST"])

# verify-email — GET only but lower the cap
@limiter.limit("3 per minute")
```

---

### SEC-007: Restrict or remove `/api/v1/coding/debug-stats`

**File:** `api/coding.py` line 241  
**Effort:** 15 minutes

Option A — restrict to admin:
```python
@role_required("admin")  # was: @role_required("coder", "admin")
```

Option B — remove `email` from response and summarise form_ids:
```python
"user": {
    "user_id": str(current_user.user_id),
    "is_admin": bool(current_user.is_admin()),
    # email removed
},
"coder_scope": {
    "form_count": len(form_ids),  # count only, not full list
    ...
}
```

---

### SEC-009: Fix `dm_kpi_scope.py` raw exception return

**File:** `api/dm_kpi/dm_kpi_scope.py` line 190  
**Effort:** 5 minutes

```python
# Before
kpi_result = {"status": "error", "reason": str(exc)}

# After
log.error("KPI scope error: %s", exc, exc_info=True)
kpi_result = {"status": "error", "reason": "Could not load scope data."}
```

---

## Priority 3 — Medium-term (within 1 month)

### SEC-006: Refactor HTML flash message

**File:** `va_auth.py` lines 32–38  
**Effort:** 30 minutes

Move HTML generation to the template level. The flash call becomes:

```python
flash("email_not_verified", "warning")
```

In `va_login.html`:
```html
{% if category == 'warning' and message == 'email_not_verified' %}
  Please verify your email address.
  <a href="{{ url_for('va_auth.resend_verification') }}">Resend verification email</a>.
{% endif %}
```

---

### SEC-008: Move toward nonce-based CSP

**File:** `app/__init__.py` line 94  
**Effort:** 2–4 hours

1. Audit all inline `<script>` blocks in templates and move to external JS files.
2. Once all inline scripts are eliminated, remove `unsafe-inline` from `script-src`.
3. If any inline scripts remain, implement nonce-based CSP via Flask-Talisman.

---

## Priority 4 — Backlog

### SEC-010: Fix `REMEMBER_COOKIE_DURATION`

Decide: is "remember me" a supported feature? If yes, set to `timedelta(days=30)`. If no,
remove the checkbox from the login form.

### SEC-011: Harden cache invalidation

Add a user-level cache version counter that is incremented atomically on permission change.
All cache keys include this counter, making manual key enumeration unnecessary.

### SEC-012: Add admin action audit log

Create a lightweight `AdminActionLog` table or extend `VaSubmissionsAuditlog` to capture
admin-panel state changes: `user_id`, `action`, `target_type`, `target_id`, `ip`, `ts`.
Emit entries from all POST/PUT/DELETE handlers in `admin.py`.

### SEC-014: Audit `/health` endpoint response payload

Ensure `/health` returns only:
```json
{"status": "ok"}
```
No versions, no hostnames, no DB connection strings.

---

## Verification Checklist

After each fix, verify:

- [ ] SEC-001: `grep -r "str(e)\|str(exc)" app/routes/` returns zero results in API response callsites
- [ ] SEC-002: `grep "5Ag92" config.py` returns no results
- [ ] SEC-003: `grep "minerva:minerva" config.py` returns no results
- [ ] SEC-004/005: Rate limit changes in va_auth.py match above
- [ ] SEC-007: `debug-stats` accessible only to admin (test with coder session → expect 403)
- [ ] SEC-008: `unsafe-inline` removed from CSP (verify with browser DevTools → Network → response headers)
