---
title: "Route Audit — health Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# health Blueprint Audit

**File:** `app/routes/health.py`
**URL Prefix:** `/` (no prefix)
**Registration:** `app.register_blueprint(health)`

## Routes

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/health` | `@limiter.exempt` | None | None | None | No |

## Route Details

### 1. `GET /health` — `health_check()`
- **Decorator:** `@limiter.exempt`
- **Auth:** None (public)
- **Returns:** JSON `{"status": "healthy"}`
- **Notes:** Intentionally unauthenticated. Used by load balancers / uptime monitors.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | N/A | Public endpoint, no auth required |
| CSRF Protection | N/A | GET, read-only |
| Rate Limiting | Exempt | Explicitly exempt via `@limiter.exempt` |

## Findings

None.
