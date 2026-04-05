---
title: "Route Audit — va_main Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# va_main Blueprint Audit

**File:** `app/routes/va_main.py`
**URL Prefix:** `/` (no prefix)
**Registration:** `app.register_blueprint(va_main)`

## Routes

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 1 | GET | `/` | None | None | None | No |
| 2 | GET | `/index` | None | None | None | No |
| 3 | GET | `/vaindex` | None | None | None | No |

## Route Details

### 1-3. `GET /`, `GET /index`, `GET /vaindex` — `va_index()`
- **Auth:** None (public landing page)
- **Returns:** Rendered `va_frontpages/va_index.html`
- **Notes:** Three URL aliases for the same public landing page.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | N/A | Public page |
| CSRF Protection | N/A | GET, read-only |

## Findings

- **No issues.** Standard public landing page.
