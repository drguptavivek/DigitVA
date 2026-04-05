---
title: "Route Audit — reviewing Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# reviewing Blueprint Audit

**Files:**
- Page routes: `app/routes/reviewing.py` (`/reviewing/`)
- API routes: `app/routes/api/reviewing.py` (`/api/v1/reviewing/`)

## Page Routes (`/reviewing/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 1 | GET | `/reviewing/` | `@login_required` | `reviewer` | Form grants + language filter | No |
| 2 | GET | `/reviewing/start/<va_sid>` | `@login_required` | `reviewer` (implicit via service) | Form grants + reviewer-eligible state | Yes (allocates) |
| 3 | GET | `/reviewing/resume` | `@login_required` | `reviewer` | Active reviewing allocation ownership | No |
| 4 | GET | `/reviewing/view/<va_sid>` | `@login_required` | `reviewer` | Form grants + reviewed state | No |

## API Routes (`/api/v1/reviewing/`)

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 5 | GET | `/api/v1/reviewing/allocation` | `@login_required` | `reviewer` | Self allocation | No |
| 6 | POST | `/api/v1/reviewing/allocation/<va_sid>` | `@login_required` | `reviewer` | Form grants + workflow state | Yes |
| 7 | POST | `/api/v1/reviewing/finalize/<va_sid>` | `@login_required` | `reviewer` | Active allocation ownership | Yes |

## Scoping Details

### Reviewer Scoping
- **Form-level:** `current_user.get_reviewer_va_forms()` returns set of `va_form_id` values
- **Language filter:** Dashboard queries filter by `current_user.vacode_language` (same as coder)
- **Workflow gate:** `start_reviewer_coding()` in the service layer enforces that the submission is in `reviewer_eligible` state
- **Allocation ownership:** `resume` and `view` check that the current user owns the active reviewing allocation

### Reviewer Final COD (API route 7)
- `submit_reviewer_final_cod()` service enforces:
  - Active reviewing allocation for this user + submission
  - Submission in `reviewer_coding_in_progress` state
  - Creates reviewer final assessment
  - Transitions workflow to `reviewer_finalized`
  - Creates/upserts final COD authority record (reviewer overrides coder)

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | Reviewer role + form-grant scope |
| Coding Workflow State Machine | Compliant | Reviewer workflow gates enforced at service layer |
| Final COD Authority | Compliant | Reviewer final COD takes precedence over coder final COD |
| CSRF Protection | Compliant | JSON POST endpoints use session + CSRF header |

## Findings

1. **`/reviewing/start/<va_sid>` (route 2) delegates auth entirely to `start_reviewer_coding()` service.** No explicit `is_reviewer()` check at route level. The service does enforce it. **Risk: Low** — consistent with the pattern used in coding blueprint, but slightly inconsistent with `dashboard()` and `resume()` which check at route level.

2. **Reviewer dashboard (route 1) shows ALL submissions matching form access + language, not just reviewer-eligible ones.** This includes submissions in `coder_finalized`, `reviewer_finalized`, etc. This appears intentional for the dashboard overview but may confuse reviewers about which submissions they can actually act on. **Risk: Low** — informational only.
