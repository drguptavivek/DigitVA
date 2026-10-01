---
title: People and Roles Page (Roles Matrix and Access Audit)
doc_type: policy
status: proposed
owner: engineering
last_updated: 2026-10-01
---

# People and Roles Page

A compact view of who holds which role where in a project, and the project's
access audit page. Owner decisions 2026-10-01 (bead `digitva-nk1`). The model
it shows is in [District Reference Model](district-reference-model.md); the
rules it reflects stay in [Organization Model Policy](organization-model.md)
and [Access Control Model](access-control-model.md).

The page is **read-only**. Grants are still created, changed and revoked in
Access Grants and the admin user panel; each row links there for users who
may edit.

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
- **Plain collaborators see initials** (owner, 2026-10-01) instead of full
  names, with cadre, unit and capabilities. Grounds: a staff directory is not
  death-linked staff identity, which the Access Control Model defines as who
  collected, coded or reviewed a death. Initials do not hide a person who is
  the only one of their cadre at a unit; the owner accepted that. The
  Access Control Model and Area Dashboard rules against pseudonymous rows
  keep applying to death-linked views.
- **Emails, deactivated users, deactivated grants and global admins** are
  shown to admins, project PIs, data managers, site PIs, interview
  supervisors and reviewers (owner, 2026-10-01), within what each may see.
  Other viewers (interviewers, coders, coding testers, plain and PII
  collaborators) see name, cadre, unit and capabilities of active people
  only.
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
| Report deaths | `interviewer` (and `death_reporter` once it exists); `data_manager` does not register deaths (`app/routes/intake.py`, register routes are interviewer-only) |
| Interview | `interviewer` |
| Supervise | `interview_supervisor`, `data_manager` |
| Code | `coder` |
| Review | `reviewer` |
| Test code | `coding_tester` |
| Manage data | `data_manager` |
| Sees personal details | **per person, not per row**: shown once on the person, true unless all their active grants, across every active project, are plain `collaborator` (`should_redact_pii`, `app/services/viewer_pii_service.py`) |
| Read-only view | `collaborator`, `collaborator_pii` |
| Site lead | `site_pi`. At unit scope it gives **nothing today**: the site PI dashboards and the coder-gate waiver read `project_site` grants only (`VaUsers.get_site_pi_sites`); the cell shows a warning for a unit-scoped `site_pi` until that gap (`digitva-djd`) is closed |
| Manage grants | `admin`, `project_pi`; `data_manager` for `coder`, `coding_tester` and `data_manager` grants at project or site scope only (`app/routes/data_management.py`) |

## Cell legend

Colour is never the only signal; every cell also has a symbol and a tooltip
naming the role and the grant.

| Cell | Meaning |
|---|---|
| Green ● | An active grant gives this ability here. |
| Red ○ | The person's cadre **may** be given it at this level (level x cadre grid) but the person does not have it. |
| Blank | Not allowed for this cadre at this level, or the column has no grid flag and no grant gives it. |

The red marker uses the grid flags only: *Fill VA* for Interview, *Code VA*
for Code, *Supervise interviews* for Supervise (Report deaths gets its own
flag with `death_reporter`). Only *Code VA* and *Supervise interviews* are
enforced when a grant is written (`CADRE_FLAG_BY_ROLE`,
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

### Gaps to close before the audit columns work

- **Granted by is recorded only on the project user import.**
  `project_user_import_service` sets `va_user_access_grants.created_by_user_id`;
  the admin grant routes, the data-manager routes, `flask users grant-admin`
  and the seed commands do not (most of them write the actor to the
  `grants.log` file instead; the CLI writes nothing). Every write path must
  set the column; older grants show "not recorded". The model comment in
  `app/models/va_user_access_grants.py` and
  `docs/current-state/data-model.md` saying the column is unused are stale.
- **Web sign-in is not recorded.** Device sign-in is (`device_session_opened`
  security event, `auth_device_sessions.last_seen_at`); a web sign-in leaves
  only a session value. Owner, 2026-10-01: **record every web sign-in.**
  - Each completed web sign-in writes an `auth_security_events` row,
    `event_type="signed_in"`, `detail={"method": ...}` (password, password
    plus second factor, passkey, or factor-reset link) and the client IP
    address (owner, 2026-10-01), taken from the trusted proxy header, never a
    client-supplied one. Purpose: correlating sign-ins with firewall logs. The
    IP is kept for **210 days** (owner, 2026-10-01: the same period as the
    application log files), then wiped from the event; the event itself
    stays.
  - A nullable `va_users.last_signed_in_at` (additive migration) is set on
    every completed web sign-in and device session opening, so the page reads
    one column instead of scanning events.
  - Until both exist the column and the dormant flag are hidden.

## Performance

One bounded query per project for grants joined to users, units (ltree path)
and cadres, plus one for the grid. "Can act here" resolves ancestors from the
selected unit's path, not per row. No per-row queries.

## Decided 2026-10-01

- Data managers' audit view covers only their own grant scope.
- Closed projects are not listed; every resolver already ignores their
  grants.

- Dormant flag default: 90 days.
- A unit-scoped `site_pi` covers every site and form under that unit
  (`digitva-djd`); until that is built the Site lead cell shows the warning.
