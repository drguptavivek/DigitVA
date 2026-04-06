---
title: "Route Audit — va_form Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-05
---

# va_form Blueprint Audit

**File:** `app/routes/va_form.py`
**URL Prefix:** `/vaform`
**Registration:** `app.register_blueprint(va_form, url_prefix="/vaform")`

## Routes

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET/POST | `/vaform/<va_sid>/<va_partial>` | `@login_required`, `@va_validate_permissions()` | login_required + va_validate_permissions | Varies by action | Varies by action | Yes (many sub-partials) |
| 2 | GET | `/vaform/attachment/<storage_name>` | None | Manual `is_authenticated` | Any role with form access | `has_va_form_access()` | No |
| 3 | GET | `/vaform/media/<va_form_id>/<va_filename>` | `@login_required` | `@login_required` | Any role with form access | `has_va_form_access()` | No |

## Route Details

### 1. `GET/POST /vaform/<va_sid>/<va_partial>` — `renderpartial()`

Main form rendering workhorse. `@va_validate_permissions()` handles role + scope + workflow state validation based on `action` parameter.

**Action types and their role/scope requirements:**

| Action (`?action=`) | Required Role | Scope Check | Workflow Constraint |
|---------------------|---------------|-------------|---------------------|
| `vacode` | coder or admin | `has_va_form_access(form.va_form_id, "coder")` | Active allocation or recode window |
| `vareview` | reviewer | `has_va_form_access(form.va_form_id, "reviewer")` | Active reviewing allocation |
| `vasitepi` | site_pi | `has_va_form_access(form.va_form_id, "site_pi")` | Submission reviewed |
| `vadata` | data_manager or admin | `has_data_manager_submission_access()` or admin | Read-only |

**Sub-partial handlers:**

| Partial | Action | Mutates | Notes |
|---------|--------|---------|-------|
| `vadmtriage` | `vadata` | Yes | DM triage. Defense-in-depth `is_data_manager()` check with inline comment |
| `vareviewform` | `vareview` | Yes | NQA save. Does not release allocation |
| `workflow_history` | Any (read) | No | Shows workflow event history |
| `vainitialasses` | `vacode` | Yes | Step 1 COD. Transitions to `coder_step1_saved` |
| `vafinalasses` | `vacode` | Yes | Final COD. Releases allocation, transitions to `coder_finalized` |
| `vausernote` | `vacode` | Yes | Saves user notes |
| `vacoderreview` | `vacode` | Yes | Not Codeable. Releases allocation |

### 2. `GET /vaform/attachment/<storage_name>` — `serve_attachment()`

**Security contract (auth-first):**
1. Hard 401 if not authenticated (no DB lookup)
2. Format validation (`^[a-f0-9]{32}\.[a-z0-9]{1,5}$`) → 404
3. DB lookup (`exists_on_odk=True` only) → 404
4. Permission check `has_va_form_access(va_form_id)` → 403
5. Path traversal guard → 404
6. Cache layer with 1-hour TTL

### 3. `GET /vaform/media/<va_form_id>/<va_filename>` — `serve_media()`

Deprecated — kept for backward compatibility. Validates form_id, checks `has_va_form_access()`, sanitizes filename.

## Scoping Details

### `@va_validate_permissions()` Decorator

Located at `app/decorators/va_validate_permissions.py`:

- `_validate_vacode()`: Checks coder role, form access, allocation, recode limits
- `_validate_vareview()`: Checks reviewer role, form access, reviewing allocation
- `_validate_vasitepi()`: Checks site_pi role, form access
- `_validate_vadata()`: Checks data_manager or admin, submission access

Admin users bypass all role checks inside these validators.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Partial | Route 1 uses `@login_required` + `@va_validate_permissions`. Route 2 uses manual check. Route 3 uses `@login_required` |
| Access Control Model | Compliant | Multi-role, multi-scope validation via decorator |
| CSRF Protection | Compliant | POST forms use CSRF |
| Coding Workflow State Machine | Compliant | All state transitions enforced |

## Findings

1. **F1 — `serve_attachment()` (route 2) uses manual `is_authenticated` check instead of `@role_required()`.** Skips the active-status gate (`user_status != active` does not trigger logout). ABAC check (`has_va_form_access`) is present and correct. **Severity: Medium** — a deactivated user could still access attachments until session expires.

2. **F2 — `renderpartial()` (route 1) uses `@login_required` instead of `@role_required()`.** Intentional multi-role design — the route serves coders, reviewers, DMs, and site PIs. `@va_validate_permissions()` handles role-specific checks. Acceptable but deviates from the standard pattern. **Severity: Info**.

3. **F3 — `serve_media()` (route 3) is deprecated** but still functional. Should be removed once all attachments have migrated to `storage_name`-based references. **Severity: Low**.
