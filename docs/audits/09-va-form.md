---
title: "Route Audit — va_form Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2025-04-05
---

# va_form Blueprint Audit

**File:** `app/routes/va_form.py`
**URL Prefix:** `/vaform`

## Routes

| # | Method | Path | Auth | Roles | Scope | Mutates |
|---|--------|------|------|-------|-------|---------|
| 1 | GET/POST | `/vaform/<va_sid>/<va_partial>` | `@login_required` + `@va_validate_permissions()` | Varies by action | Varies by action | Yes (many sub-partial handlers) |
| 2 | GET | `/vaform/attachment/<storage_name>` | Auth-first (401 if anon) | Any role with form access | Form grants | No |
| 3 | GET | `/vaform/media/<va_form_id>/<va_filename>` | `@login_required` | Any role with form access | Form grants | No |

## Route Details

### 1. `GET/POST /vaform/<va_sid>/<va_partial>` — `renderpartial()`
This is the main form rendering workhorse. The `@va_validate_permissions()` decorator handles role + scope + workflow state validation based on the `action` parameter.

**Action types and their role/scope requirements:**

| Action (`?action=`) | Required Role | Scope Check | Workflow Constraint |
|---------------------|---------------|-------------|---------------------|
| `vacode` | `coder` or `admin` | `has_va_form_access(form.va_form_id, "coder")` | Active allocation or recode window |
| `vareview` | `reviewer` | `has_va_form_access(form.va_form_id, "reviewer")` | Active reviewing allocation |
| `vasitepi` | `site_pi` | `has_va_form_access(form.va_form_id, "site_pi")` | Submission reviewed |
| `vadata` | `data_manager` or `admin` | `has_data_manager_submission_access()` or admin | Read-only |

**Sub-partial handlers (va_partial values):**

| Partial | Action | Mutates | Notes |
|---------|--------|---------|-------|
| `vadmtriage` | `vadata` | Yes | DM not-codeable triage. POST saves `VaDataManagerReview`, transitions workflow to `not_codeable_by_data_manager`, syncs ODK review state |
| `vareviewform` | `vareview` | Yes | Narrative Quality Assessment save. Does NOT release allocation. |
| `workflow_history` | Any (read) | No | Shows `VaSubmissionWorkflowEvent` history |
| `vainitialasses` | `vacode` | Yes | Step 1 COD. Saves `VaInitialAssessments`, transitions to `coder_step1_saved` |
| `vafinalasses` | `vacode` | Yes | Final COD. Saves `VaFinalAssessments`, releases allocation, transitions to `coder_finalized`. Enforces NQA and Social Autopsy completion first. |
| `vausernote` | `vacode` | Yes | Saves user notes |
| `vacoderreview` | `vacode` | Yes | Coder Not Codeable. Saves `VaCoderReview`, releases allocation, transitions to `not_codeable_by_coder`, syncs ODK |
| Any category partial | Any (render) | No | Renders form category data |

### 2. `GET /vaform/attachment/<storage_name>` — `serve_attachment()`
- **Security contract (auth-first):**
  1. Hard 401 if not authenticated (no DB lookup)
  2. Format validation (`^[a-f0-9]{32}\.[a-z0-9]{1,5}$`) → 404
  3. DB lookup (`exists_on_odk=True` only) → 404
  4. Permission check `has_va_form_access(va_form_id)` → 403
  5. Path traversal guard → 404
  6. Cache layer with 1-hour TTL
- **No `@login_required` decorator** — uses `current_user.is_authenticated` directly. This is intentional for the auth-first pattern.

### 3. `GET /vaform/media/<va_form_id>/<va_filename>` — `serve_media()`
- **Deprecated** — kept for backward compatibility
- **Security:** Validates form_id format, checks `has_va_form_access()`, sanitizes filename, path traversal checks

## Scoping Details

### `@va_validate_permissions()` Decorator
Located at `app/decorators/va_validate_permissions.py`. This is the central permission validator for all form operations:

- **`_validate_vacode()`:** Checks `is_coder()`, verifies form access, checks allocation, validates recode limits
- **`_validate_vareview()`:** Checks `is_reviewer()`, verifies form access, checks reviewing allocation
- **`_validate_vasitepi()`:** Checks `is_site_pi()`, verifies form access
- **`_validate_vadata()`:** Checks `is_data_manager()` or admin, verifies submission access

Admin users bypass all role checks inside these validators.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Access Control Model | Compliant | Multi-role, multi-scope validation via decorator |
| Coding Workflow State Machine | Compliant | All state transitions enforced |
| Final COD Authority | Compliant | Final COD creates authority record, deactivates previous |
| CSRF Protection | Compliant | All POST forms use CSRF |
| PII Protection | Partial | Attachment serving is auth-first; but form data rendering includes PII fields visible to authorized users |
| Demo Coding Retention | Compliant | Demo artifacts get `demo_expires_at` timestamps |

## Findings

1. **`serve_attachment()` (route 2) does not use `@login_required`.** It manually checks `current_user.is_authenticated`. This is intentional for the "auth-first" security contract (returns 401 before any DB lookup). **Risk: None** — correct pattern for this use case.

2. **`vadmtriage` POST handler (line 222) has an inline role check `if not current_user.is_data_manager(): abort(403)`** in addition to the decorator. This is defense-in-depth — the decorator already validates via `_validate_vadata()`. **Risk: None** — redundant but safe.

3. **The `renderpartial()` function is very large** (~1000+ lines including partial handlers). The `vafinalasses` and `vainitialasses` handlers contain significant business logic (COD submission, allocation release, workflow transitions) that would be better extracted to service functions. This is a maintainability concern, not a security concern.

4. **`serve_media()` (route 3) is deprecated** but still functional. Should be removed once all attachments have migrated to `storage_name`-based references.
