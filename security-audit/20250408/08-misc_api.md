---
title: Security Audit — api/workflow.py, api/so.py, api/nqa.py, api/icd10.py, api/profile.py
doc_type: security-report
status: draft
owner: vivek
last_updated: 2026-04-07
---

# Miscellaneous API Routes — Security Audit

## Routes Overview

### `api/workflow.py`

| Method | Path | Auth |
|--------|------|------|
| POST | `/api/v1/workflow/transition` | `@login_required` |
| GET | `/api/v1/workflow/state/<va_sid>` | `@login_required` |

**Note:** `@login_required` rather than `@role_required` — any authenticated user can call
these endpoints. The service layer must validate that the user is allowed to transition the
submission's workflow state.

### `api/so.py` (second opinion)

| Method | Path | Auth |
|--------|------|------|
| POST | `/api/v1/so/request` | coder, admin |
| POST | `/api/v1/so/submit` | coder, admin |
| GET | `/api/v1/so/status/<va_sid>` | coder, admin |

### `api/nqa.py` (NQA)

| Method | Path | Auth |
|--------|------|------|
| Various | `/api/v1/nqa/*` | role_required |

### `api/icd10.py`

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/icd10/search` | `@login_required` |

### `api/profile.py`

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/v1/profile/me` | login_required |
| POST | `/api/v1/profile/update` | login_required |
| POST | `/api/v1/profile/change-password` | login_required |

---

## Potential Finding — `api/workflow.py` uses `@login_required` not `@role_required`

**Severity:** MEDIUM (needs verification)  
**File:** `api/workflow.py`  
**Line:** 14

**Description:**  
Using `@login_required` allows any authenticated user (coder, reviewer, data_manager, admin,
site_pi) to call the workflow transition endpoint. If the service layer does not independently
verify that the caller has permission to perform the specific transition on the specific
submission, a coder could potentially transition a submission they don't own.

**Recommendation:**  
Verify that `WorkflowService.transition()` (or equivalent) validates:
1. The caller owns or is assigned the submission.
2. The requested transition is valid for the caller's role.

If these checks exist in the service layer, this is a non-issue. If not, add explicit role
and ownership checks.

---

## `api/icd10.py` — Unauthenticated search (low risk)

**Severity:** INFO  
**Route:** `GET /api/v1/icd10/search`

**Description:**  
The ICD-10 search endpoint uses `@login_required` which is correct. No sensitive data is
exposed — ICD-10 codes are public. No finding here, confirmed clean.

---

## `api/profile.py` — Password change endpoint

**Severity:** INFO (positive review)

The `change-password` endpoint requires the current password before accepting a new one,
preventing account takeover via CSRF (even though CSRF is also enforced globally).

---

## Positive Controls Verified

- All endpoints require at minimum `@login_required`.
- `api/so.py` and `api/nqa.py` use `@role_required` appropriately.
- `api/icd10.py` returns only public ICD-10 data.
- `api/profile.py` requires current-password verification for password change.
- No raw SQL interpolation found.
