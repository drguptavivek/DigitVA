---
title: "Route Audit — va_auth Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# va_auth Blueprint Audit

**File:** `app/routes/va_auth.py`
**URL Prefix:** `/vaauth`
**Registration:** `app.register_blueprint(va_auth, url_prefix="/vaauth")`

## Routes

| # | Method | Path | Auth | Roles | Scope | Mutates | Rate Limit |
|---|--------|------|------|-------|-------|---------|------------|
| 1 | GET/POST | `/vaauth/valogin` | None (creates session) | None | None | Yes (login) | 10/min POST |
| 2 | GET | `/vaauth/valogout` | None | None | None | Yes (logout) | Default |

## Route Details

### 1. `GET/POST /vaauth/valogin` — `va_login()`
- **Auth:** None (this *is* the auth entry point)
- **Rate Limit:** POST limited to 10/min via `@limiter.limit("10 per minute", methods=["POST"])`
- **Security:**
  - Validates email + password against `VaUsers`
  - Sets `session.permanent = True` for session persistence
  - Redirects already-authenticated users to `landing_url()`
  - Validates `next` parameter to prevent open redirect (`urlparse(next_page).netloc != ''`)
- **Mutations:** Creates Flask-Login session

### 2. `GET /vaauth/valogout` — `va_logout()`
- **Auth:** None (works for anonymous too — redirects to index)
- **Mutations:** Destroys session via `logout_user()`

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | Login/logout are pre-auth endpoints |
| CSRF Protection | Covered | Flask-WTF CSRF on POST login form |
| Rate Limiting | Compliant | 10/min on POST; login brute-force mitigation |
| PII Protection | Compliant | Password never logged or flashed |

## Findings

- **No issues.** Login rate limiting is in place. Open-redirect protection on `next` parameter is implemented.
