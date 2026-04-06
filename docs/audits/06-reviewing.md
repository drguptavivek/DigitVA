---
title: "Route Audit — reviewing Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# reviewing Blueprint Audit

**Files:**
- Page routes: `app/routes/reviewing.py` (`/reviewing/`)
- API routes: `app/routes/api/reviewing.py` (`/api/v1/reviewing/`)

## Page Routes (`/reviewing/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/reviewing/` | `@role_required("reviewer")` | `@role_required` | reviewer | `get_reviewer_va_forms()` | No |
| 2 | GET | `/reviewing/start/<va_sid>` | `@role_required("reviewer")` | `@role_required` | reviewer | `start_reviewer_coding()` | Yes (allocates) |
| 3 | GET | `/reviewing/resume` | `@role_required("reviewer")` | `@role_required` | reviewer | `va_permission_ensureanyallocation("reviewing")` | No |
| 4 | GET | `/reviewing/view/<va_sid>` | `@role_required("reviewer")` | `@role_required` | reviewer | `has_va_form_access()` + `va_permission_ensurereviewed()` | No |

## API Routes (`/api/v1/reviewing/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 5 | GET | `/api/v1/reviewing/allocation` | `@role_required("reviewer")` | `@role_required` | reviewer | Own active allocation | No |
| 6 | POST | `/api/v1/reviewing/allocation/<va_sid>` | `@role_required("reviewer")` | `@role_required` | reviewer | `start_reviewer_coding()` | Yes |
| 7 | POST | `/api/v1/reviewing/finalize/<va_sid>` | `@role_required("reviewer")` | `@role_required` | reviewer | `submit_reviewer_final_cod()` | Yes |

## Scoping Details

- **Form-level:** `current_user.get_reviewer_va_forms()` returns form IDs the user has reviewer grants for
- **Language filter:** Submissions filtered by `current_user.vacode_language`
- **Allocation check:** Active allocation ownership verified before viewing/resuming
- **Workflow state:** `va_permission_ensurereviewed()` validates submission state
- **Final COD authority:** Reviewer final COD takes precedence over coder final COD

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Compliant | All 7 routes use `@role_required("reviewer")` |
| Access Control Model | Compliant | Reviewer role + form-grant scope |
| CSRF Protection | Compliant | POST routes protected by CSRFProtect |

## Findings

None. Clean auth, ABAC, and CSRF coverage.
