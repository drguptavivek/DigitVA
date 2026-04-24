---
title: "Route Audit — va_form Blueprint"
doc_type: audit
status: active
owner: engineering
last_updated: 2026-04-24
---

# va_form Blueprint Audit

**Files:** `app/routes/forms/partials.py`, `app/routes/attachments/`
**URL Prefix:** `/vaform`
**Registration:** `app.register_blueprint(va_form, url_prefix="/vaform")`

## Routes

| # | Method | Path | Decorator | Auth | Roles | Scope | Mutates |
|---|--------|------|-----------|------|-------|-------|---------|
| 1 | GET/POST | `/vaform/<va_sid>/<va_partial>` | `@login_required`, `@dynamic_action_authorized(_resolve_renderpartial_action)` | login_required + action authorization | Varies by action | Varies by action | Yes (many sub-partials) |
| 2 | GET | `/vaform/attachment/<storage_name>` | `@action_authorized("attachment_view")` | action authorization | Any role with form access | Central form scope plus route-local allocation/file checks | No |
| 3 | GET | `/vaform/media/<va_form_id>/<va_filename>` | `@action_authorized("attachment_view")` | action authorization | Any role with form access | Central form scope plus route-local allocation/file checks | No |

## Route Details

### 1. `GET/POST /vaform/<va_sid>/<va_partial>` — `renderpartial()`

Main form rendering workhorse. The route lives in `app/routes/forms/partials.py`, remains import-compatible through `app/routes/va_form.py`, and now dispatches into focused handler modules under `app/routes/forms/handlers/`.

`@dynamic_action_authorized(_resolve_renderpartial_action)` resolves the action from `va_partial`, request method, and `action` query parameter. `validate_va_request(...)` still performs the route-specific permission and workflow validation used by the legacy form flow.

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

The implementation lives in `app/routes/attachments/` but remains registered
on the `va_form` blueprint to preserve the public `/vaform/attachment/...`
URL and endpoint names.

**Security contract (auth-first):**
1. Central `attachment_view` action authorization resolves the form scope
2. Format validation (`^[a-f0-9]{32}\.[a-z0-9]{1,5}$`) -> 404
3. DB lookup (`exists_on_odk=True` only) -> 404
4. Allocation-bound roles are checked against the owning submission
5. Path traversal guard -> 404
6. Cache layer with 1-hour TTL

### 3. `GET /vaform/media/<va_form_id>/<va_filename>` — `serve_media()`

Deprecated — kept for backward compatibility. Validates form id, authorizes
`attachment_view`, resolves the owning submission, applies allocation-bound
attachment checks, and sanitizes the filename.

## Scoping Details

### `validate_va_request(...)` Guard

Located at `app/decorators/va_validate_permissions.py`:

- `_validate_vacode()`: Checks coder role, form access, allocation, recode limits
- `_validate_vareview()`: Checks reviewer role, form access, reviewing allocation
- `_validate_vasitepi()`: Checks site_pi role, form access
- `_validate_vadata()`: Checks data_manager or admin, submission access

Admin users bypass all role checks inside these validators. The outer action-authorization layer now adds a centralized policy mapping before this legacy validation runs.

## Policy Compliance

| Policy | Status | Notes |
|--------|--------|-------|
| Auth Decorator RBAC | Compliant | Route 1 uses `@login_required` + action authorization + `validate_va_request(...)`. Routes 2 and 3 use central action authorization |
| Access Control Model | Compliant | Multi-role, multi-scope validation via decorator |
| CSRF Protection | Compliant | POST forms use CSRF |
| Coding Workflow State Machine | Compliant | All state transitions enforced |

## Findings

1. **F1 — `serve_attachment()` manual authentication check.** Resolved. The route now uses central `attachment_view` action authorization and route-local allocation/file checks.

2. **F2 — `renderpartial()` (route 1) uses `@login_required` instead of `@role_required()`.** Intentional multi-role design — the route serves coders, reviewers, DMs, and site PIs. `@dynamic_action_authorized(...)` and `validate_va_request(...)` handle role- and action-specific checks. Acceptable but deviates from the standard pattern. **Severity: Info**.

3. **F3 — `serve_media()` (route 3) is deprecated** but still functional. Should be removed once all attachments have migrated to `storage_name`-based references. **Severity: Low**.
