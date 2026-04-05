---
title: "Route Audit — profile Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# profile Blueprint Audit

**File:** `app/routes/profile.py` (page routes)
**API File:** `app/routes/api/profile.py` (JSON API under `/api/v1/profile/`)

## Page Routes (`/profile/`)

| # | Method | Path | Auth | Roles | Scope | Mutates | Rate Limit |
|---|--------|------|------|-------|-------|---------|------------|
| 1 | GET | `/profile/` | `@login_required` | Any authenticated | Self only | No | Default |
| 2 | GET/POST | `/profile/force-password-change` | `@login_required` | Any authenticated | Self only | Yes (password) | 5/min POST |

## API Routes (`/api/v1/profile/`)

| # | Method | Path | Auth | Roles | Scope | Mutates | Rate Limit |
|---|--------|------|------|-------|-------|---------|------------|
| 3 | GET | `/api/v1/profile/` | `@login_required` | Any authenticated | Self only | No | Default |
| 4 | GET | `/api/v1/profile/languages` | `@login_required` | Any authenticated | Self only | No | Default |
| 5 | PATCH | `/api/v1/profile/password` | `@login_required` | Any authenticated | Self only | Yes | 5/min |
| 6 | PATCH | `/api/v1/profile/language` | `@login_required` | Any authenticated | Self only | Yes | Default |
| 7 | PATCH | `/api/v1/profile/timezone` | `@login_required` | Any authenticated | Self only | Yes | Default |

## Route Details

### Page Routes

**1. `GET /profile/` — `view()`**
- Renders profile page. Data loaded client-side via API.

**2. `GET/POST /profile/force-password-change` — `force_password_change()`**
- Enforced by `@app.before_request` when `pw_reset_t_and_c` is False.
- POST validates current password, sets new password, sets `pw_reset_t_and_c = True`.
- Rate limited to 5/min on POST.

### API Routes

**3. `GET /api/v1/profile/` — `get_profile()`**
- Returns user_id, name, email, languages, timezone.

**4. `GET /api/v1/profile/languages` — `get_languages()`**
- Returns available and selected language options.

**5. `PATCH /api/v1/profile/password` — `update_password()`**
- Validates current password. Enforces new != current. Enforces password policy.
- Rate limited to 5/min.

**6. `PATCH /api/v1/profile/language` — `update_language()`**
- Validates language codes against `MasLanguages`.

**7. `PATCH /api/v1/profile/timezone` — `update_timezone()`**
- Validates timezone against `pytz.common_timezones`.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | Self-service only; no cross-user access |
| CSRF Protection | Compliant | Password change form uses CSRF; API mutations use session + CSRF header |
| PII Protection | Compliant | Passwords never logged |

## Findings

- **No issues.** All profile operations are scoped to the current user only. Password changes are rate-limited and validated.
