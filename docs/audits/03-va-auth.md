---
title: "Route Audit — va_auth Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# va_auth Blueprint Audit

**File:** `app/routes/va_auth.py`
**URL Prefix:** `/vaauth`
**Registration:** `app.register_blueprint(va_auth, url_prefix="/vaauth")`

## Routes

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET/POST | `/vaauth/valogin` | `@limiter.limit("10/min", methods=["POST"])` | None | None | None | Yes (session) |
| 2 | GET | `/vaauth/valogout` | — | Inline | None | None | Yes (logout) |

## Route Details

### 1. `GET/POST /vaauth/valogin` — `va_login()`
- **Decorator:** `@limiter.limit("10/min", methods=["POST"])`
- **Auth:** None (public by design — this IS the login page)
- **CSRF:** Protected by WTForms `hidden_tag()` in template
- **Security:** Validates email + password, open-redirect protection on `next` param, sets `session.permanent = True`
- **Returns:** Login form (GET) or processes login (POST)

### 2. `GET /vaauth/valogout` — `va_logout()`
- **Decorator:** None
- **Auth:** Inline `is_anonymous` check — logs out then redirects to login
- **Returns:** Redirect to `/valogin`

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | N/A | Login/logout are pre-auth routes |
| CSRF Protection | Partial | Login POST has CSRF. Logout is GET with no CSRF |
| Rate Limiting | Compliant | 10/min on POST login |

## Findings

1. **F1 — `/valogout` is a GET-based state-changing route.** Logout destroys the session but is served on GET. A CSRF attack could force-logout a user. **Severity: Low** — annoying but not a security vulnerability.

2. **F2 — `/valogout` uses inline auth instead of `@role_required`.** Functionally correct but inconsistent with project convention. Low severity since logout should work for all authenticated users.
