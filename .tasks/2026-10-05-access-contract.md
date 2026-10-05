# Complete access contract on `GET /api/v1/me/access` (digitva-ntct.3)

- Status: design approved 2026-10-05, building
- Priority: P1
- Created: 2026-10-05

## Goal

Owner 2026-10-05: the access body is the one complete, structured statement
of everything a user may do, so a client never needs another route to learn
it and the contract is not revisited per screen. Started from the Expo
session's report (`expo-handoff.md` section 11): `/me/access` lists grant
reach, but the server also requires active forms (interviewer, coder,
reviewer) and web intake switched on, so the app could not tell where a
worker may actually work.

## Rule

Every value is the output of the predicate the server already enforces; no
second copy. Additive: every existing key keeps its name, type and place
(the app's `parseAccessSummary` ignores unknown keys).

One sentence for the whole body: `grants[]` lists every resolved grant with
`active`; every other list (`roles`, `sites[].roles`, `units[].roles`,
`actions`) counts active grants only.

## Shape

```json
{
  "user": {"user_id": "...", "name": "...", "landing_page": "coder", "coding_languages": ["en"]},
  "is_admin": false,
  "account": {
    "privileged": true,
    "second_factor": {"required": true, "configured": true},
    "pii_visible": true,
    "device_access": true,
    "mentor": {"member": false, "admin_of": [{"institute_code": "...", "institute_name": "..."}]}
  },
  "roles": ["coder", "data_manager", "interview_supervisor", "site_pi"],
  "admin_actions": ["view", "triage", "..."],
  "demo_coding": {"available": true, "project_ids": ["DEMO01"]},
  "projects": [{
    "project_id": "TST001", "project_name": "...", "has_tree": true,
    "settings": {"web_intake_mode": "both", "self_coding": false,
                 "coding_scope": {"level_code": "phc", "above_mode": "view_only"}},
    "grants": [{"role": "coder", "scope": "org_unit", "org_unit_id": "...", "unit_name": "...",
                "codes": true, "active": true, "source": "assigned"}],
    "actions": {
      "view":   {"project": false, "site_ids": [], "org_unit_ids": ["..."]},
      "code":   {"project": false, "site_ids": [], "org_unit_ids": ["..."]},
      "interview": [{"site_id": "...", "site_name": "...", "web_intake_mode": "both", "org_units": []}],
      "code_now": false
    },
    "sites": [{"site_id": "...", "site_name": "...", "roles": ["coder"]}],
    "levels": [], "units": []
  }]
}
```

| Field | Source (the server's own check) |
| --- | --- |
| `grants[].active` | `Grant.opens_gate` (`authz/grants.py`) |
| `grants[].source` | new `Grant.source`, set where `resolve_grants` adds the implied interviewer grant |
| `roles` | `role_flags` (`authz/predicates.py`): the screen gates, derived roles included |
| `sites[].roles`, `units[].roles` | active grants, plus derived DM / interview supervisor where `role_flags` derives them; interviewer at a site only where `interviewer_context` lists it |
| `actions.<action>` | new `action_reach(resolved, project_id)` beside `_lens_groups`, iterating `RULES` x lens groups, so a new Action appears with no summary change |
| `actions.interview` | `web_intake_service.interviewer_context` (the intake routes' check) |
| `actions.code_now` | `self_coding_project_ids` |
| `admin_actions` | the admin bypass set in `authz/actions.py` |
| `settings` | `ProjectSettings` from `resolve_grants` (no extra query) |
| `account.privileged`, `second_factor` | `totp_service` (`is_privileged`, `needs_second_factor`, `has_any_factor`) |
| `account.pii_visible` | `not viewer_pii_service.should_redact_pii` |
| `account.device_access` | `device_auth_service.has_device_access`, fed the one `interviewer_context` result |
| `account.mentor` | `mentor_institute_service.administered_institutes`, `member_user_ids` |
| `user.landing_page`, `coding_languages` | `VaUsers.landing_page`, `vacode_language` |

`actions` is reach, not a decision: the server decides each action per case
(lens groups carry active-form / active-pair conditions that resolve only
against a submission), exactly as `units[].roles` is documented today.

Terms are not a field: an unaccepted-terms user gets 403 `terms_required`
from this route, as from every route.

## Owner decisions (ask one at a time)

1. Decided 2026-10-05: `roles` lists explicit roles only; demo-training
   virtual grants stay under `demo_coding`. `role_flags` gains a
   `virtual=` parameter rather than a filtered copy.
2. Decided 2026-10-05 (owner: the response is complete): every grant says
   where it came from, `grants[].source`: `"assigned"` (a grant row) or
   `"self_coding"` (the interviewer grant implied by a coder grant on a
   self-coding project). `Grant` gains the field; grant cache `_FORMAT`
   goes to 3; deploy bumps the authz global version.

## Performance

`interviewer_context` is computed once per request and shared with
`has_device_access`. Everything else reads `resolve_grants` (cached) plus a
fixed number of queries per user (mentor, factor) and per project (as
today). No per-site or per-unit queries.

## Tests

The summary and the routes agree, per source, present before absent: an
interviewer and a coder grant on a project with no active form are listed
`active: false`, absent from `roles`, `sites[].roles`, `actions`, and the
intake and coding routes refuse; activate the form and all flip. One case
each for derived DM (site_pi on a unit), mentor, PII, device access, admin.

## Docs

Baseline in `docs/policy/api-v1.md`; body in `docs/current-state/api-v1.md`;
app contract in `expo-handoff.md` section 11.

## Follow-up (owner 2026-10-05, after the writer started)

A dedicated per-project `self_coding` block instead of the scattered
`settings.self_coding` and `actions.code_now`:

```json
"self_coding": {"enabled": true, "code_now": true}
```

`enabled` is the project setting (`ProjectSettings.self_coding`); `code_now`
is `self_coding_project_ids(user)` (offered "Code this case now"). The
interviewer reach it implies is in `grants[]` with `source: "self_coding"`
and in `actions.interview`. Applied by the main session after the first
writer reports (writers do not take relayed scope).
