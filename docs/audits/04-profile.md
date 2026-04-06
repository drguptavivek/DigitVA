---
title: "Route Audit — profile Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# profile Blueprint Audit

**Files:**
- Page routes: `app/routes/profile.py` (`/profile/`)
- API routes: `app/routes/api/profile.py` (`/api/v1/profile/`)

## Page Routes (`/profile/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/profile/` | `@login_required` | `@login_required` | Any | Self | No |
| 2 | GET/POST | `/profile/force-password-change` | `@login_required`, `@limiter.limit("5/min", methods=["POST"])` | `@login_required` | Any (guarded by `pw_reset_t_and_c`) | Self | Yes |

## API Routes (`/api/v1/profile/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 3 | GET | `/api/v1/profile/` | `@login_required` | `@login_required` | Any | Self | No |
| 4 | GET | `/api/v1/profile/languages` | `@login_required` | `@login_required` | Any | Self | No |
| 5 | PATCH | `/api/v1/profile/password` | `@login_required`, `@limiter.limit("5/min")` | `@login_required` | Any | Self | Yes |
| 6 | PATCH | `/api/v1/profile/language` | `@login_required` | `@login_required` | Any | Self | Yes |
| 7 | PATCH | `/api/v1/profile/timezone` | `@login_required` | `@login_required` | Any | Self | Yes |

## Route Details

### Page Routes

**1. `GET /profile/` — `view()`**
- Renders profile page. Data loaded client-side via API.

**2. `GET/POST /profile/force-password-change` — `force_password_change()`**
- Guarded by `pw_reset_t_and_c` flag. POST validates current password, sets new password, sets flag.
- CSRF protected by WTForms on POST. Rate limited 5/min.

### API Routes

**3–7. Profile API**
- All use `@login_required`. All mutations are self-scoped (`current_user` only).
- CSRF protected by CSRFProtect on PATCH routes.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Non-compliant | Uses `@login_required` instead of `@role_required` |
| CSRF Protection | Compliant | POST/PATCH routes protected |
| Rate Limiting | Compliant | 5/min on password changes |

## Findings

1. **F1 — All 7 routes use `@login_required` instead of `@role_required()`.** This bypasses the active-status guard — a deactivated user with an unexpired session could still access profile routes. **Severity: Low** — self-scoped operations only, no cross-user impact. Consider `@role_required` with all workflow roles.

2. **F2 — `/force-password-change` has no role restriction beyond `pw_reset_t_and_c` flag.** The route remains manually navigable after reset completion. **Severity: Low** — handler re-renders form but no security impact.
