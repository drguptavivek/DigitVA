---
title: "Route Audit — API v1 Shared Endpoints"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# API v1 Shared Endpoints Audit

**Files:**
- ICD-10: `app/routes/api/icd10.py` (`/api/v1/icd10/`)
- Workflow: `app/routes/api/workflow.py` (`/api/v1/workflow/`)
- NQA: `app/routes/api/nqa.py` (`/api/v1/va/`)
- Social Autopsy: `app/routes/api/so.py` (`/api/v1/va/`)

## ICD-10 API (`/api/v1/icd10/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET | `/api/v1/icd10/search` | `@login_required` | `@login_required` | Any authenticated | None (global) | No |

- **Purpose:** Search ICD-10 codes by display text for COD selection
- **Scope:** No project/site filtering — ICD codes are reference data
- **Notes:** Uses wildcard LIKE query (`%query%`)

## Workflow Events API (`/api/v1/workflow/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 2 | GET | `/api/v1/workflow/events/<va_sid>` | `@login_required` | `@login_required` | Any with form access | `has_va_form_access()` | No |

- **Purpose:** Return workflow event history for a submission
- **Scope:** Checks `has_va_form_access(submission.va_form_id)` — any role with access to the form can view events

## Narrative Quality Assessment API (`/api/v1/va/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 3 | POST | `/api/v1/va/<va_sid>/narrative-qa` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `require_coding_access(va_sid)` + project NQA flag | Yes |

- **Purpose:** Save/update NQA scores during active coding
- **Scope:** `require_coding_access()` checks active coding allocation
- **Feature gate:** Checks `project.narrative_qa_enabled`

## Social Autopsy API (`/api/v1/va/`)

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 4 | POST | `/api/v1/va/<va_sid>/social-autopsy` | `@role_required("coder","admin")` | `@role_required` | coder, admin | `require_coding_access(va_sid)` + project SO flag | Yes |

- **Purpose:** Save/update Social Autopsy delay analysis during active coding
- **Scope:** Same `require_coding_access()` pattern as NQA
- **Feature gate:** Checks `project.social_autopsy_enabled`

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Partial | NQA and SO use `@role_required`. ICD-10 and workflow use `@login_required` |
| Access Control Model | Compliant | Allocation-based scoping for write operations |
| CSRF Protection | Compliant | POST endpoints protected by CSRFProtect |
| Feature Gates | Compliant | Project-level NQA and SO flags enforced |

## Findings

1. **F1 — ICD-10 search uses `@login_required` instead of `@role_required()`.** Any authenticated user can search ICD-10 codes regardless of role. Likely intentional (ICD search needed by coders + reviewers + DMs), but inconsistent with `@role_required` standard. **Severity: Low** — reference data, no scoped access needed.

2. **F2 — Workflow events uses `@login_required` instead of `@role_required()`.** An inline ABAC check (`has_va_form_access`) protects the data, but the route allows any authenticated user to trigger a DB lookup for the submission before the ABAC check rejects them. **Severity: Low** — `@role_required("coder","reviewer","data_manager","admin")` would be more defensive.

3. **F3 — ICD-10 search has no rate limiting.** Wildcard LIKE query could be abused. **Severity: Low** — read-only reference data.

4. **F4 — `_require_coding_access()` was previously duplicated** in nqa.py and so.py. Now consolidated to `app/utils/va_permission/va_permission_11_require_coding_access.py`. **Resolved** in auth standardization commit.
