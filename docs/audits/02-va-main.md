---
title: "Route Audit — va_main Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# va_main Blueprint Audit

**File:** `app/routes/va_main.py`
**URL Prefix:** `/` (no prefix)
**Registration:** `app.register_blueprint(va_main)`

## Routes

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/` | — | None | None | None | No |
| 2 | GET | `/index` | — | None | None | None | No |
| 3 | GET | `/vaindex` | — | None | None | None | No |

## Route Details

### 1–3. `GET /`, `GET /index`, `GET /vaindex` — `va_index()`
- **Decorator:** None
- **Auth:** None (public)
- **Returns:** Landing page HTML
- **Notes:** Three URL aliases for the same handler. All are intentionally public.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | N/A | Public landing page |
| CSRF Protection | N/A | GET, read-only |

## Findings

None. Public landing page is intentional.
