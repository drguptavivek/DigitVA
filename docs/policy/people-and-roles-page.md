---
title: People and Roles Page (Roles Matrix and Access Audit)
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-11
---

# People and Roles Page

A compact view of who holds which role where in a project, and the project's
access audit page. Owner decisions 2026-10-01 (bead `digitva-nk1`), status active since the owner accepted the defaults
below on 2026-10-06. The model
it shows is in [District Reference Model](district-reference-model.md); the
rules it reflects stay in [Organization Model Policy](organization-model.md)
and [Access Control Model](access-control-model.md).

The page is **read-only**. Grants are still created, changed and revoked in
Access Grants and the admin user panel. A per-row link there for users who
may edit is **deferred**: the API carries no edit flag yet, so the page has
no such link.

## Who may open it

Every user with an active grant in the project, at every level. Everyone is
part of one team.

- A user sees the people whose grants sit in **the units their own grants
  reach, plus the people on their reporting line above** (the units on the
  path to the root) **and the project-scope grant holders**. This is a **new
  widening**: today a grant never confers anything above its unit, and the
  units API exposes only the *names and codes* of ancestor units
  (Organization Model Policy, "Ancestors are visible, deliberately"). Listing
  the *people* above is the owner's "one team" decision of 2026-10-01 and is
  recorded here as such.
- A user with a project-scope grant, an admin, and a project PI see the whole
  project.
- **Site rows** (a `project_site` grant of a classical project) are listed
  only to those whole-project viewers and to a viewer who holds a grant at
  that same site; a unit-scoped viewer, or a viewer at another site, does not
  see them. Project-scope rows ("Whole project") stay visible to everyone with
  a grant. The number of units a grant covers below it counts only the units
  the viewer can see.
- **Plain collaborators see initials** (owner, 2026-10-01) instead of full
  names, with cadre, unit and capabilities. "Plain" is what the service
  checks: the viewer is outside the identity tier below and
  `should_redact_pii` is true for them, that is, they hold no
  PII-granting role (`_PII_GRANTING_ROLES`) in any active project. A viewer
  with a PII-granting role (interviewer, coder, coding tester, PII
  collaborator, and the identity tier) sees full names. Grounds: a staff directory is not
  death-linked staff identity, which the Access Control Model defines as who
  collected, coded or reviewed a death. Initials do not hide a person who is
  the only one of their cadre at a unit; the owner accepted that. The
  Access Control Model and Area Dashboard rules against pseudonymous rows
  keep applying to death-linked views.
- **Emails, deactivated users, deactivated grants and global admins** are
  shown to admins, project PIs, data managers, site PIs, interview
  supervisors (in-charges) and reviewers (owner, 2026-10-01), within what each may see.
  Other viewers (interviewers, coders, coding testers, collaborators) see
  name, cadre, unit and capabilities of active people only; the name is full
  for the first three and a PII collaborator, initials for a plain
  collaborator.
- **Audit columns and flags** (below) are shown only to admins, project PIs
  and data managers (data managers within their own grant scope).

## Layout

One row per person per grant location: a unit, a site, or "Whole project".
A person with grants at two units has two rows.

Fixed columns: person (name, email), cadre, unit with its path
(DH01 > CHC01 > PHC01 > SC01), and the number of units the grant covers below
it.

Capability columns. Each is derived from roles by **one mapping in code**;
the page never decides access itself.

| Column | Given by roles |
|---|---|
| Report deaths | `interviewer` and `death_reporter` (both register deaths); `data_manager` does not register deaths (the register routes take `interviewer` and `death_reporter` only) |
| Interview | `interviewer` |
| Supervise | `interview_supervisor` (held by the in-charges until the In-charge role is built), `data_manager`; in an organizational project also the In-charge and the `project_pi` (decision 2026-10-02, see [Access Control Model](access-control-model.md); implementation tracked in digitva-0wc) |
| Code | `coder` |
| Review | `reviewer` |
| Test code | `coding_tester` |
| Manage data | `data_manager` |
| View PII | **per person, not per row**: green for every row of a person who holds a PII-granting role (`_PII_GRANTING_ROLES`: admin, project PI, site PI, data manager, coder, coding tester, reviewer, interviewer, PII collaborator) **in this project** (a global admin everywhere), the same rule as `should_redact_pii` (`app/services/viewer_pii_service.py`) restricted to the project shown (`pii_visible_user_ids(ids, project_id=...)`); a role held only in another project does not turn it on; a person without one (a plain collaborator, an interview supervisor alone) gets no green. The row's own grants only name the roles in the cell's tooltip |
| Read-only view | `collaborator`, `collaborator_pii` |
| Site lead | `site_pi` at `project_site` scope (classical projects). In an organizational project the oversight duty at a unit is the **In-charge** (District, Block or PHC in-charge; decision 2026-10-02, `site_pi` held at `org_unit`, see [Access Control Model](access-control-model.md), "In-charge"; implementation tracked in digitva-0wc) |
| Manage grants | `admin`, `project_pi`; `data_manager` for `coder`, `coding_tester` and `data_manager` grants at its own project or site scope (site projects; `app/routes/data_management.py`). In an organizational project the In-charge (`data_manager` at its own level and below) and the `data_manager` (`data_manager` strictly below its own level; `interviewer`, `death_reporter`, `coder`, `reviewer`, `coding_tester`, `collaborator`, `collaborator_pii` anywhere in its subtree), per [Access Control Model](access-control-model.md), "Who creates which grants" (digitva-0wc stage 6) |

## Cell legend

Colour is never the only signal; every cell also has a symbol and a tooltip
naming the role and the grant.

| Cell | Meaning |
|---|---|
| Green ● | An active grant gives this ability here. |
| Red ○ | The person's cadre **may** be given it at this level (level x cadre grid) but the person does not have it. |
| Grey ◐ | View only: a coder grant above the coding scope level (decision 5 below). |
| Grey ⊘ | Inactive: the grant, the user or the unit is deactivated (decision 4 below). |
| Blank | Not allowed for this cadre at this level, or the column has no grid flag and no grant gives it. |

The red marker uses the grid flags only: *Fill VA* for Interview, *Code VA*
for Code, *Supervise interviews* for Supervise, *Report deaths*
(`can_report_deaths`) for Report deaths. *Code VA*, *Supervise interviews*
and *Report deaths* are enforced when a grant is written (`CADRE_FLAG_BY_ROLE`,
`app/services/org_grant_service.py`); *Fill VA* is informational and an
interviewer grant may carry no cadre. Columns with no grid flag show only
green or blank.

## Filters

- Unit type (level).
- Cascading unit pickers, one per level (DH > CHC > PHC-AAM > SC-AAM); each
  narrows the next.
- Cadre, capability ("only people who can Code"), grant status (active,
  deactivated), name or email search.
- **Mode**:
  - *Granted here*: people whose grant sits at the selected unit.
  - *Can act here*: everyone whose access reaches the selected unit,
    including grants on units above it and project-scope grants. Selecting
    SC01 shows its CHO and also the PHC01 MO, the CHC SMO, the DH staff and
    project-level people.
- A count of people per capability column for the current filter.
- CSV export of the filtered rows, with the same redaction as the screen.

## Audit columns and flags

For admins, project PIs and data managers only.

- Granted at (`grant_created_at`) and granted by.
- Last sign-in.
- Deactivated grants, through the status filter.
- Flags on a row:
  - **Exceeds the grid**: a `coder` or `interview_supervisor` grant whose
    cadre no longer has *Code VA* or *Supervise interviews* at that level.
    Cadre rules are checked only when a grant is written, so a later grid
    edit leaves such grants in place; the page is where they are found.
    Interviewer grants are not flagged (no write-time rule).
  - Unit grant without a cadre.
  - Active grant on a deactivated user or a deactivated unit.
  - Account with no active grant in the project.
  - No sign-in for N days. N is a project setting, default **90** (owner,
    2026-10-01): long enough that a coder between coding
    batches or a staff member on leave is not flagged, short enough to catch
    accounts of people who have moved on within one quarterly review.

### Audit data prerequisites (both built)

- **Granted by is written on every web grant write (`digitva-nk1`, built).**
  The admin grant create and admin-toggle create, the data-manager grant
  create and user-plus-grant create, and the project user import set
  `va_user_access_grants.created_by_user_id` to the acting user on insert.
  **Reactivating a grant does not restamp it**: granted at/by stay the
  original grant's. `flask users grant-admin` and the seed commands leave it
  null, and grants written before this show "not recorded".
- **Web sign-in is recorded (`digitva-ci8`, built).** Owner, 2026-10-01:
  record every web sign-in.
  - Each completed web sign-in writes an `auth_security_events` row,
    `event_type="web_sign_in"` (the name already in use; there is no separate
    `signed_in` event), `detail={"method": ..., "ip": ...}` (method:
    `password`, `passkey` or `factor_reset`). The IP is the
    client address behind the proxy, never a client-supplied header
    (authentication-factors.md section 9). Purpose: correlating sign-ins with
    firewall logs. Nothing is written for a failed sign-in or one stopped
    after the first step.
  - **IP retention: 210 days** (owner, 2026-10-01, final; same as the log
    files). The daily beat task `wipe_sign_in_ips_task`
    (`app/tasks/security_event_tasks.py`) removes `detail.ip` from
    `web_sign_in` events older than that and keeps the event.
  - The nullable `va_users.last_signed_in_at` is set on every completed web
    sign-in and device session opening (one model method,
    `VaUsers.mark_signed_in`), so the page reads one column instead of
    scanning events. It is null for an account that has not signed in since
    the column was added; the page shows "not recorded", not "never".

### Job title (`digitva-04u4`)

Owner, 2026-10-02: each person may have a free-text **job title** (for example
"Chief Medical Officer, Faridabad"), `va_users.job_title`, nullable.

- It is **not personal data**: it is the post people already know the person
  by. Every role that can see the person sees it, a plain collaborator
  included; it is never redacted, and it is never consulted for access. It is
  distinct from the cadre (a standard category validated at grant time) and
  from the role.
- One validator, `user_account_service.clean_job_title`, for every write:
  trimmed, at most 120 characters, no control characters; blank clears it.
- Written by an admin (user create and edit), a data manager, In-charge or
  project PI on the data-manager page (create, and edit by anyone who may
  open the person), a mentoring-institute admin creating staff, and by the
  person in their own profile (web Profile page, `PATCH
  /api/v1/profile/job-title`, cookie session only). The project user import
  and the CLI do not set it.
- Shown wherever staff are listed today: the admin and data-manager user
  lists and details, grant lists (`user_job_title`), the exact email or
  mobile lookup, mentoring-institute staff lists and the profile.

## Performance

One bounded query per project for grants joined to users, units (ltree path)
and cadres, plus one for the grid. "Can act here" resolves ancestors from the
selected unit's path, not per row. No per-row queries.

## Decided 2026-10-06 (owner accepted the defaults)

1. Entry point: one `GET /api/v1/projects/<pid>/people-roles` (and `.csv`)
   and a standalone `/people-roles` page for every grant holder, also shown
   in the admin setup People section for admin and PI.
2. Reactivating a grant does not restamp granted-by or granted-at.
3. Dormant N is 90 days, a code constant; a per-project setting is deferred
   (no migration).
4. Cells of an inactive user or inactive unit are greyed, with the row flag.
5. A coder grant above the coding scope level shows a grey "view only" Code
   cell (`ResolvedGrants.codes()` is false there).
6. Row key: person x location x cadre.
7. An In-charge (`site_pi` at a unit) sees the audit columns as a data
   manager does, for their own subtree.
8. Site-project (no tree) rows are listed, with no grid (hollow) cells.
9. This policy is active, and [Access Control Model](access-control-model.md)
   records the widening: people in the units you reach plus your reporting
   line.

## Decided 2026-10-01

- Data managers' audit view covers only their own grant scope.
- Closed projects are not listed; every resolver already ignores their
  grants.

- Dormant flag default: 90 days.
- `site_pi` is not held at unit scope today (database `role_scope` CHECK).
  Superseded 2026-10-02: in an organizational project the Site lead duty at a
  unit belongs to the **In-charge** of that level, and the project PI covers
  the whole project (see [Access Control Model](access-control-model.md),
  "In-charge"; implementation tracked in digitva-0wc).
- **Headcount excludes mentoring institute staff.** A district's staff
  headcount counts only people whose grants sit in the district's own tree.
  A member of a mentoring institute (`map_mentor_institute_user`, active) is
  never counted there, even though their unit grants fall inside the district's
  subtree. They appear in a separate **Mentors** listing for the district,
  grouped by institute (`mentor_institute_service.mentors_for_unit`). There
  is no headcount service yet; whoever builds it applies this rule.
