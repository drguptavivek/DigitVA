---
title: Auth Decorator and RBAC Gating Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-19
---

# Auth Decorator and RBAC Gating Policy

## Core Rule

All Flask routes must be gated by `@role_required(*roles)`. This decorator
subsumes `@login_required` and replaces all previous ad-hoc auth helper
patterns across every blueprint.

---

## 1. Access Control Layers

DigitVA uses a 4-layer access control model. This policy governs **Layer 2
(RBAC)**. The other layers are out of scope but documented here for clarity.

| Layer | Mechanism | Scope | Example |
|---|---|---|---|
| **1. Authentication** | flask-login `current_user` (handled by `@role_required`) | Is this a valid logged-in user? | Anonymous → redirect to login |
| **2. RBAC role gate** | `@role_required(*roles)` | Does this user hold one of the required roles? | Coder cannot access admin routes |
| **3. ABAC scope gate** | Inline: `has_va_form_access()`, `has_data_manager_submission_access()` | Does this user's grant scope cover this specific resource? | DM for UNSW01 cannot see ICMR01 data |
| **4. Workflow state** | `@va_validate_permissions()` + service-layer checks | Is this submission in the right state for this action? | Cannot review a submission that hasn't been coded |

### What each layer does NOT do

- Layer 2 (RBAC) does **not** check which projects/sites/forms a user can access — that's Layer 3 (ABAC).
- Layer 3 (ABAC) does **not** check allocation state or workflow transitions — that's Layer 4 (Workflow).
- Layer 4 (Workflow) does **not** gate by role — it assumes Layer 2 already passed.

---

## 2. RBAC Role Definitions

Roles are defined in `VaAccessRoles` enum (`app/models/va_selectives.py`).
Being in that enum makes a role **grantable**; it does not make it **routable**.
A role is routable only when `_ROLE_METHODS` carries an explicit predicate for
it (see below), and `docs/policy/access-control-model.md` is the reference for
what each role may reach.

| Role | Enum value | Scope types | Access meaning |
|---|---|---|---|
| `admin` | `admin` | `global` | Full system access, bypasses all ABAC checks |
| `project_pi` | `project_pi` | `project` | Manages a project (users, settings) |
| `site_pi` | `site_pi` | `project_site` | Views data for their assigned sites |
| `coder` | `coder` | `project`, `project_site` | Codes VA forms within assigned scope |
| `reviewer` | `reviewer` | `project`, `project_site` | Reviews coded forms within assigned scope |
| `data_manager` | `data_manager` | `project`, `project_site` | Manages data pipeline within assigned scope |
| `collaborator` | `collaborator` | `project`, `project_site`, `org_unit` | Read-only viewer, personal data redacted |
| `collaborator_pii` | `collaborator_pii` | `project`, `project_site`, `org_unit` | Same reach as `collaborator`; personal data not redacted |
| `coding_tester` | `coding_tester` | `project`, `project_site` | Exercises coding routes without affecting real workflow counts |
| `interviewer` | `interviewer` | `project_site` | Web intake — records submissions for their site |

### Admin bypass

Admin users bypass ABAC checks via `va_hasrole()` in
`va_validate_permissions.py`. This is intentional and preserved.

---

## 3. `@role_required()` Decorator Specification

### Location
`app/decorators/role_required.py`

### Signature
```python
def role_required(*roles):
    """Gate route by role. OR semantics — user must have at least one."""
```

Supported role strings are exactly the keys of `_ROLE_METHODS`: `"admin"`,
`"coder"`, `"coding_tester"`, `"reviewer"`, `"data_manager"`, `"site_pi"`,
`"project_pi"`, `"interviewer"`.

### Role-name validation (at decoration time)

`role_required()` checks its arguments against `_ROLE_METHODS` when the
decorator is applied — that is, at import — and raises `ValueError` naming the
unknown role(s) and listing the valid set. A bare `role_required()` with no
arguments is rejected the same way.

**Why this is not a runtime check.** The role check is an `any()` over the
listed roles. Unknown names used to be filtered out before that `any()`, so a
route decorated only with names absent from `_ROLE_METHODS` evaluated `any()`
over an empty generator: **403 for every user, including admins**, with the
bogus names printed in the log line as if they were real. It failed closed,
which is the right direction, but silently — a typo was indistinguishable from
a deliberately locked-down route. Validating at import converts that into a
startup failure. This was hit twice independently on 2026-09-19.

**`_ROLE_METHODS` must never be derived from `VaAccessRoles`.** A role may be
grantable without being routable, and the gap is deliberate: a role becomes
reachable over HTTP only when someone writes a predicate for it and thinks about
what that opens. Auto-populating the dict from the enum — as a comprehension, a
`dict()` call, or any other generated form — would turn every present and future
enum member into a live gate, silently widening access behind what looks like a
fix for the unknown-role error. The correct response to that error is always to
add the predicate deliberately, or to correct the name.

PII visibility is **not** decided here. `collaborator` and `collaborator_pii`
have identical reach, so a route gating on one gates on the other; whether
personal data is redacted is decided downstream by
`viewer_pii_service.should_redact_pii`. Do not infer redaction from route access.

Tests: `tests/test_role_required_validation.py` covers the raise, the positive
controls (a valid role still admits its holder and still refuses a non-holder),
that the raise happens at decoration rather than first request, that every role
name at an existing `role_required(...)` call site is accepted, and — as an
`ast` check on the source — that `_ROLE_METHODS` remains a dict literal with
written-out string keys.

### The guard marker and the route-coverage test

`role_required` stamps the wrapper it returns with `ROLE_MARKER_ATTR`
(`__digitva_roles__`), holding the tuple of roles it gates on. The attribute has
no runtime effect; it exists so a test can prove a route is guarded.

`tests/test_route_auth_coverage.py` walks `app.url_map` at runtime — not an
`ast` sweep, because only the runtime map sees dynamically registered
blueprints — resolves each endpoint to its view function, walks the
`__wrapped__` chain, and fails on any endpoint whose chain carries neither the
marker nor Flask-Login's `login_required`. This closes the class of bug the
role-name validation cannot touch: a mistyped role fails at import, a **missing**
decorator fails open.

**`__wrapped__` is not an auth signal.** Every `functools.wraps` decorator sets
it; on this app 322 of 334 rules carry it, including routes with no auth
decorator at all. For the same reason `login_required` cannot be detected by
`__module__` or `__qualname__` — `wraps` overwrites both with the decorated
view's — so it is matched on its wrapper's `__code__`, which `wraps` never
rewrites.

Two explicit allowlists live in that module, each entry carrying its reason:
`PUBLIC_BY_DESIGN` (login, logout, health, static, the account-recovery flows,
the maintenance banner) and `UNGUARDED_DECISION_PENDING` (the landing page, the
WHO document endpoint, and the four `help` routes). An entry on the pending list
must eventually be decorated or moved to `PUBLIC_BY_DESIGN`; separate tests fail
if an allowlisted endpoint disappears from `url_map` or later becomes guarded,
so neither list can drift.

`API_PATH_PREFIXES` is the module constant behind the JSON-vs-HTML decision, and
the same test file asserts that every registered rule that looks like an API
route matches one of its prefixes. A new API blueprint at an unlisted prefix
would answer an expired session with an HTML redirect, so `base.js` never shows
the session-expired modal and the tab simply stops refreshing.

### Behavior

The decorator performs these checks in order:

1. **Authentication check**: `current_user.is_authenticated` — if false, respond with 401
2. **Active-status check**: `current_user.user_status == VaStatuses.active` — if false, `logout_user()` + respond with 401
3. **Role check**: At least one role matches via `_ROLE_METHODS[role](current_user)` — if none match, respond with 403

### HTTP status codes (MUST match frontend expectations)

| Condition | Status code | API routes (`/api/` or `/admin/api/`) | Web routes |
|---|---|---|---|
| Not authenticated | **401** | `{"error": "Authentication required."}` | Redirect to `va_auth.va_login` |
| User deactivated | **401** | `{"error": "Authentication required."}` | `logout_user()` + redirect to login |
| Wrong role | **403** | `{"error": "{role} access is required."}` | Flash message + `abort(403)` |

**Why this matters:** `app/static/js/base.js` intercepts fetch/HTMX responses
with status **401** to show a "Session Expired" modal and block further API
calls (including polling). Status **403** does not trigger the modal. Using the
wrong status code causes either silent failures (polling continues after
deactivation) or false session-expired modals (wrong-role errors trigger
logout).

### Composability

- `@role_required()` internally handles `@login_required` behavior — do not stack both.
- May be combined with `@va_validate_permissions()` for routes needing both RBAC and workflow validation.
- May be combined with `@limiter.limit()` for rate-limited routes.

---

## 4. ABAC Scope Model (existing, unchanged)

### Grant storage

`VaUserAccessGrants` stores one row per user-role-scope combination:

| Column | Values |
|---|---|
| `user_id` | FK to `VaUsers` |
| `role` | `VaAccessRoles` enum |
| `scope_type` | `global` / `project` / `project_site` |
| `project_id` | Set when `scope_type` is `project` or `project_site` |
| `project_site_id` | Set when `scope_type` is `project_site` |
| `grant_status` | `active` / `inactive` |

### ABAC check methods (on `VaUsers` model)

| Method | ABAC check | Layer |
|---|---|---|
| `has_va_form_access(form_id, role)` | User's grants cover this form's project/site for this role | Form-level |
| `has_data_manager_submission_access(project_id, site_id)` | DM's grants cover this project or project-site pair | Submission-level |
| `has_data_manager_form_access(form_id)` | Resolves form → (project, site) → checks submission access | Form-level |
| `get_coder_va_forms()` | Set of form IDs user can code | Role+scope |
| `get_reviewer_va_forms()` | Set of form IDs user can review | Role+scope |
| `get_site_pi_sites(project_id)` | Set of site IDs PI can view | Role+scope |
| `get_data_manager_projects()` | Set of project IDs DM can manage | Role+scope |
| `get_data_manager_project_sites()` | Set of (project, site) pairs DM can manage | Role+scope |

These methods are called inline in route handlers and inside service functions
as defense-in-depth. They are NOT replaced by `@role_required()`.

---

## 5. Session Expiry and Forced Logout

### Session lifetime

- 30 minutes (`PERMANENT_SESSION_LIFETIME` in `config.py`)
- Backend: SQLAlchemy (`va_sessions` table)
- Flask-login: Stores `_user_id` in session; `load_user()` does a fresh DB lookup per request

### Frontend interceptor (`app/static/js/base.js`)

- **Fetch interceptor**: Wraps `window.fetch` — detects 401 responses on API calls → shows "Session Expired" modal → blocks all subsequent API requests
- **HTMX interceptor** (`htmx:beforeSwap`): Detects 401 on HTMX responses → shows modal → prevents swap
- **Interval cleanup**: Stops sync dashboard polling intervals (`_syncDashboardIntervals`) on session expiry
- **Login URL**: `_loginUrl = '/vaauth/valogin'` — must stay in sync with the actual login route

### How `@role_required()` integrates with forced logout

When `@role_required()` detects a deactivated user (`user_status != active`):
1. Calls `logout_user()` to clear the flask-login session server-side
2. Returns 401 — triggers the base.js modal on the next polling/AJAX request
3. For web routes, redirects to the login page

This ensures admin-deactivated users are locked out immediately on their next
request, without waiting for the 30-minute cookie expiry.

---

## 6. Blueprint Migration (completed 2026-04-05)

### Web blueprints

| Blueprint | Routes | Old pattern | New pattern |
|---|---|---|---|
| `coding` | 7 | `@login_required` + inline `is_coder()` | `@role_required("coder", "admin")` |
| `reviewing` | 4 | `@login_required` + inline `is_reviewer()` | `@role_required("reviewer")` |
| `sitepi` | 2 | `@login_required` + inline check (one returned HTTP 200 on deny) | `@role_required("site_pi")` + 200→403 fix |
| `data_management` | ~28 | `@login_required` + inline `is_data_manager()` | `@role_required("data_manager")` |
| `va_form` | 3 | `@login_required` + `@va_validate_permissions()` | Kept as-is; inline `is_data_manager()` defense-in-depth retained with comment |

### API blueprints

| Blueprint | Routes | Old pattern | New pattern |
|---|---|---|---|
| `api.coding` | ~7 | `@login_required` + inline role check | `@role_required(...)` |
| `api.reviewing` | ~3 | `@login_required` + inline `is_reviewer()` | `@role_required("reviewer")` |
| `api.data_management` | ~17 | `@login_required` + `_require_data_manager()` helper | `@role_required("data_manager")` |
| `api.analytics` | ~7 | `@login_required` + `_require_data_manager()` helper | `@role_required("data_manager")` |
| `api.nqa` | 1 | `@login_required` + `_require_coding_access()` | `@role_required("coder", "admin")` + shared util |
| `api.so` | 1 | `@login_required` + `_require_coding_access()` | `@role_required("coder", "admin")` + shared util |

### Admin blueprint

| Route type | Old pattern | New pattern |
|---|---|---|
| Admin API (`/admin/api/`) | `@require_api_role()` + `_request_user()` | `@role_required(...)` + `current_user` |
| Admin UI panels | `_require_admin_ui_access()` + `_request_user()` | `@role_required(...)` + `current_user` |
| Field mapping panel (was unguarded) | No decorator | `@role_required("admin")` |

---

## 7. Code Eliminated

| What | Where | Replaced by |
|---|---|---|
| `_request_user()` | `app/routes/admin.py` | flask-login `current_user` |
| `require_api_role()` | `app/routes/admin.py` | `@role_required()` |
| `_require_admin_ui_access()` | `app/routes/admin.py` | `@role_required()` |
| `_require_admin_api_access()` | `app/routes/admin.py` | `@role_required()` |
| `_require_data_manager()` | `app/routes/api/data_management.py` | `@role_required("data_manager")` |
| `_require_data_manager_or_admin()` | `app/routes/api/data_management.py` | `@role_required("data_manager", "admin")` |
| `_require_data_manager()` | `app/routes/api/analytics.py` | `@role_required("data_manager")` |
| `_require_coding_access()` (two copies) | `api/nqa.py`, `api/so.py` | `app/utils/va_permission/va_permission_11_require_coding_access.py` |
| `user` param on `_current_user_can_manage_project` | `app/routes/admin.py` | Simplified to `(project_id)` using `current_user` |

---

## 8. Audit Findings Addressed

| Finding | Blueprint | Fix |
|---|---|---|
| `_require_coding_access()` duplicated | nqa.py, so.py | Consolidated to shared util |
| `_require_data_manager()` duplicated | data_management API, analytics API | Replaced with decorator |
| `/sitepi/data` returned HTTP 200 on deny | sitepi | `va_permission_abortwithflash` + 403 |
| `/coding/pick` lacked route-level role check | coding | Added `@role_required("coder")` |
| `/reviewing/start` lacked route-level role check | reviewing | Added `@role_required("reviewer")` |
| `admin_panel_project_forms()` had no decorator | admin | Added `@role_required("admin")` |
| Field mapping panel routes had no decorator | admin | Added `@role_required("admin")` |
| `_project_access_filter()` called `_request_user()` | admin | Replaced with `current_user` |
| `_request_user()` bypassed flask-login | admin | Removed entirely |
| `base.js` login URL pointed to wrong route | base.js | Fixed `/auth/login` → `/vaauth/valogin` |
| vadmtriage defense-in-depth check was undocumented | va_form | Added inline comment |

---

## References

- `app/decorators/role_required.py` — decorator implementation
- `app/decorators/va_validate_permissions.py` — existing workflow validator (unchanged)
- `app/utils/va_permission/va_permission_11_require_coding_access.py` — shared coding access util
- `app/static/js/base.js` — frontend 401/403 interceptor
- `app/models/va_users.py` — role methods and ABAC checks
- `app/models/va_user_access_grants.py` — grant model
- `app/models/va_selectives.py` — `VaAccessRoles` and `VaAccessScopeTypes` enums
- `docs/policy/access-control-model.md` — broader access control policy
- `config.py` — `PERMANENT_SESSION_LIFETIME`
