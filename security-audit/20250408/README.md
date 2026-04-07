---
title: Security Audit — DigitVA Flask Application
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# Security Audit — DigitVA (2026-04-07)

Scope: all route files, app factory, and config.

## Files Audited

| File | Document |
|------|----------|
| `app/routes/va_auth.py` | [01-va_auth.md](01-va_auth.md) |
| `app/routes/admin.py` | [02-admin.md](02-admin.md) |
| `app/routes/data_management.py` | [03-data_management.md](03-data_management.md) |
| `app/routes/api/data_management.py` | [03-data_management.md](03-data_management.md) |
| `app/routes/coding.py` + `api/coding.py` | [04-coding.md](04-coding.md) |
| `app/routes/reviewing.py` + `api/reviewing.py` | [05-reviewing.md](05-reviewing.md) |
| `app/routes/api/analytics.py` | [06-analytics.md](06-analytics.md) |
| `app/routes/api/dm_kpi/*` | [07-dm_kpi.md](07-dm_kpi.md) |
| `app/routes/api/workflow.py` + `api/so.py` + `api/nqa.py` + `api/icd10.py` + `api/profile.py` | [08-misc_api.md](08-misc_api.md) |
| `app/routes/va_form.py` + `va_main.py` + `sitepi.py` + `profile.py` + `health.py` | [09-page_routes.md](09-page_routes.md) |
| `config.py` + `app/__init__.py` | [10-config_and_app.md](10-config_and_app.md) |

## Summary of Findings

| ID | Severity | Title | Route File | Status |
|----|----------|-------|------------|--------|
| SEC-001 | **HIGH** | Exception strings leaked to API responses | admin.py, api/data_management.py | **Fixed** |
| SEC-002 | **HIGH** | Hardcoded SECRET\_KEY fallback | config.py | **Fixed** |
| SEC-003 | **HIGH** | Hardcoded DB URL fallback exposes credentials | config.py | **Fixed** |
| SEC-004 | **MEDIUM** | `reset-password` rate limit too permissive | va_auth.py | **Fixed** |
| SEC-005 | **MEDIUM** | `verify-email` rate limit too permissive | va_auth.py | **Fixed** |
| SEC-006 | **MEDIUM** | HTML injected into flash message | va_auth.py | **Fixed** |
| SEC-007 | **MEDIUM** | `/api/v1/coding/debug-stats` exposes user PII + scope | api/coding.py | **Fixed** |
| SEC-008 | **MEDIUM** | `unsafe-inline` in CSP script-src | app/\_\_init\_\_.py | Open |
| SEC-009 | **MEDIUM** | KPI scope endpoint returns raw exception string | api/dm_kpi/dm_kpi_scope.py | **Fixed** |
| SEC-010 | **LOW** | `REMEMBER_COOKIE_DURATION` too short for "remember me" | config.py | **Fixed** |
| SEC-011 | **LOW** | Cache invalidation failures are silently swallowed | api/analytics.py | Open |
| SEC-012 | **LOW** | No explicit admin-action audit logging in admin routes | admin.py | Open |
| SEC-013 | **INFO** | `valogout` has no CSRF protection | va_auth.py | **Fixed** |
| SEC-014 | **INFO** | `health.py` endpoint is unauthenticated | health.py | Review |

## Positive Controls Verified

- Global CSRF protection (Flask-WTF, `X-CSRFToken` header)
- `@role_required` on every state-changing route
- SQLAlchemy ORM parameterized queries — no raw SQL interpolation found
- Flask-Talisman security headers (HSTS, X-Frame, nosniff, XSS protection)
- Session cookies: HttpOnly, Secure, SameSite=Lax, signed
- Rate limiting on all auth endpoints
- `os.path.realpath()` path-traversal guard on file serving
- Email enumeration prevented on forgot-password and resend-verification
- Open-redirect protection on `next` parameter (netloc check)
- `secure_filename()` on file uploads

## Remediation Priority

1. **Immediate** — SEC-001: strip `str(e)` from all API error responses
2. **Immediate** — SEC-002: fail hard if `SECRET_KEY` env var is absent
3. **Short-term** — SEC-003: remove hardcoded DB URL fallback with credentials
4. **Short-term** — SEC-004/005: tighten token-endpoint rate limits
5. **Short-term** — SEC-007: make debug-stats admin-only or remove
6. **Medium-term** — SEC-006: refactor HTML flash messages to use template macros
7. **Medium-term** — SEC-008: adopt nonce-based CSP
8. **Backlog** — SEC-009/010/011/012/014
