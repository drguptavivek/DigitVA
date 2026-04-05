---
title: "Route Audit — API v1 Shared Endpoints"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# API v1 Shared Endpoints Audit

**Files:**
- ICD-10: `app/routes/api/icd10.py` (`/api/v1/icd10/`)
- Workflow: `app/routes/api/workflow.py` (`/api/v1/workflow/`)
- NQA: `app/routes/api/nqa.py` (`/api/v1/va/`)
- Social Autopsy: `app/routes/api/so.py` (`/api/v1/va/`)

## ICD-10 API (`/api/v1/icd10/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 1 | GET | `/api/v1/icd10/search` | `@login_required` | Any authenticated | None (global search) | No |

- **Purpose:** Search ICD-10 codes by display text for COD selection.
- **Scope:** No project/site filtering. All authenticated users can search all ICD codes.
- **Risk: None** — ICD-10 codes are reference data, not scoped.

## Workflow Events API (`/api/v1/workflow/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 2 | GET | `/api/v1/workflow/events/<va_sid>` | `@login_required` | Any with form access | `has_va_form_access(submission.va_form_id)` | No |

- **Purpose:** Return workflow event history for a submission.
- **Scope:** Checks `has_va_form_access()` — any role with access to the submission's form can view events.
- **Policy Compliance:** Compliant. Form-level access is the correct scope boundary for read-only workflow history.

## Narrative Quality Assessment API (`/api/v1/va/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 3 | POST | `/api/v1/va/<va_sid>/narrative-qa` | `@login_required` | `coder` or `admin` (demo) | Active coding allocation on this SID | Yes |

- **Purpose:** Save/update NQA scores for a submission during active coding.
- **Scope:** `_require_coding_access()` checks for an active `VaAllocations` row with `allocation_for == coding` matching `va_sid` + `current_user.user_id`.
- **Admin demo:** Admin can bypass allocation check if `va_actiontype == "vademo_start_coding"`.
- **Coder demo:** Regular coders can only save NQA for demo submissions in demo/training projects.
- **Project feature gate:** Checks `project.narrative_qa_enabled` before allowing save.
- **Payload binding:** NQA is bound to the active payload version.

## Social Autopsy API (`/api/v1/va/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 4 | POST | `/api/v1/va/<va_sid>/social-autopsy` | `@login_required` | `coder` or `admin` (demo) | Active coding allocation on this SID | Yes |

- **Purpose:** Save/update Social Autopsy delay analysis for a submission during active coding.
- **Scope:** Same `_require_coding_access()` pattern as NQA.
- **Validation:** Requires all delay-level questions answered. "None" is exclusive within a delay level.
- **Project feature gate:** Checks `project.social_autopsy_enabled`.
- **Payload binding:** Social Autopsy is bound to the active payload version.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | Allocation-based scoping for write operations |
| Coding Workflow State Machine | Compliant | NQA/Social Autopsy are supporting artifacts, not workflow transitions |
| CSRF Protection | Compliant | POST endpoints use session + CSRF |
| Narrative QA Policy | Compliant | Project-level feature gate enforced |
| Social Autopsy Policy | Compliant | Project-level feature gate enforced |

## Findings

1. **NQA and Social Autopsy share identical `_require_coding_access()` functions** (duplicated in both files). This could be extracted to a shared helper to reduce duplication. **Risk: Low** — functional but DRY violation.

2. **ICD-10 search has no rate limiting.** Heavy usage could be a minor performance concern. **Risk: Very Low** — read-only reference data.

3. **Workflow events endpoint uses `has_va_form_access()` without a specific role parameter.** This means any user with *any* role-level access to the form (coder, reviewer, site_pi, data_manager, admin) can view workflow events. This is appropriate for an audit trail view.
