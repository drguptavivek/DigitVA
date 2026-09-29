---
title: Area Dashboard Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-30
---

# Area Dashboard Policy

## Purpose

Every person working on a project (interviewer, coder, reviewer, site PI,
data manager, project PI, collaborator) sees how collection and coding are
going in the part of the project they hold a grant for: a district user
their district, a PHC user their PHC, a project-level user the whole
project. The same page opened at the project root is the project's
operational dashboard for project PIs and data managers; there is no
separate project dashboard build. Bead `digitva-stc`.

## Who sees it

- Any user with at least one active grant, of any role, on an active project.
  A user with no grant sees an empty page, not an error.
- `admin` sees every project whole.
- The page and API require only a signed-in session, not a role: a role list
  would refuse users with no grant instead of showing them an empty page.

## Scope

Resolved per project, as a union over all of the user's roles. A project
"has a tree" when it has an active organization level, the same test the
coding scope uses (`submission_within_org_scope`):

- A project-scoped or project-site-scoped grant on an **organization** project
  gives the whole tree. The automatic `O###` site is the project
  (`organization-model.md`), so a site grant there is project-wide
  (`org_grant_service.project_wide_grant_exists`).
- Otherwise the subtrees of the user's org-unit grants
  (`org_grant_service.scope_unit_ids_for_roles`), which is the same viewing
  scope `viewable_unit_ids` already gives each role.
- A **sites-mode** project (no tree) is shown per site: every site for a
  project grant, the granted sites for site grants.

Viewing scope, never coding scope: an area count never implies the right to
code or open a case there.

## What it shows

Counts only. No case lists and no subject data; staff names only in the
per-staff view below, to viewers allowed staff identity.
A count links to the screen the user's role already has for that work, only
when the user holds that role on the project and that screen admits them
(`digitva-stc.3`):

- data manager (and admin): the data manager dashboard, filtered to the
  project, and to the site or workflow state where the count is exactly
  that filter;
- coder: the coding dashboard, from the awaiting-or-in-coding count;
- interviewer: web intake, from the submitted count.

No link otherwise. Links carry project, site and workflow codes only, never
subject or staff data. Collaborators also reach the data manager dashboard
but get no link yet (open owner decision). The link test is the role on the
project, not that role's reach: a data manager on one site of a project the
user sees whole through another role gets a link whose landing page shows
only their site. The target screen enforces its own scope, so this can
show a smaller number, never more data.

Retired submissions and inactive project-sites are left out, as on the data
manager dashboard.

The page opens at the user's grant roots and drills down one level at a time
(the selected unit's direct children, with a breadcrumb back up). Each row
is the unit's whole subtree, counted once.

- **Collection progress**: submissions received (web and ODK alike, from the
  submission analytics snapshot) in total and in the last 7 and 30 days,
  and web interviews in progress (open drafts, live).
- **Coding progress**: submissions by coding stage, bucketed from
  `workflow_state` in one mapping (`coding_bucket` in
  `app/services/workflow/definition.py`): awaiting coding (screening,
  attachment sync, SmartVA pending, ready), in coding, in review (reviewer
  coding in progress), coded, not codeable (including consent refused),
  other (no workflow row). The data manager's "coded" filter counts reviewer
  coding in progress as coded; this page shows it as in review.

Collection counts do not use the death-register status. The interviewer
worklist (`digitva-vzk`, `web-intake.md`) replaces it with case states; case
outcomes (started, incomplete, refused) join this page when those exist.

**Unrouted submissions** (no org unit) fall outside every subtree, so child
rows do not sum to the project total. Users with a project-wide scope see an
"Unrouted" row at the project root so the totals reconcile.

### Project cards

At the project root, a user whose scope is project-wide (admin, project PI,
a project grant, or a site grant on an organization project, and a project
grant on a sites-mode project) also sees the project's operational card: the
Site PI KPIs computed once over the whole project's active sites
(`sitepi_reporting_service.get_project_workflow_kpis`). It shows submitted,
coded (a final cause of death holds authority, `final-cod-authority.md`),
not codeable, awaiting or in coding, coded and open to review, reviewer
finalized, changed in ODK after coding, and final COD by coder and by
reviewer; coded and not codeable also as a share of submitted. The card is
live. Its definitions are the Site PI's, so its coded and not codeable
differ from the table's coding buckets (the table counts coder-finalized as
coded and consent refused as not codeable; the card uses authority rows and
the two not-codeable states). No staff or subject identity. No coding
turnaround yet: the data holds no cheap submission-to-final-COD pair on this
path. Unit-scoped users see no card.

**Freshness.** Snapshot counts carry the finish time of the last recorded
snapshot refresh (hourly; an ad-hoc refresh records no run, so the time is a
lower bound); live counts say so. The two are labelled separately.

## Staff identity

An optional "By staff" view under the table breaks the same area down per
person (`digitva-stc.2`). It is offered at a selected unit or site, and at
the project root for a project-wide scope; a unit-scoped user's root is
several areas, so it has none. The area is exactly the rows': the selected
subtree counted once, or the whole project including unrouted cases.
Confirmed duplicate cases count nowhere.

- **Interviewers**: cases registered (register-first cases, by who
  registered them), interviews started (by who opened the first interview
  on the case), interviews submitted and in progress (by the draft's
  owner), and contact attempts logged in the last 30 days.
- **Coders**: submissions coded and marked not codeable at first pass, in
  the last 7 and 30 days, by the coder who did it (the same attribution as
  the data manager's coder daily statistics). Retired submissions and
  inactive project-sites are left out, as in the coding columns.

Who sees names is decided only by `should_redact_pii`, never a per-screen
role test (`access-control-model.md`). A viewer it redacts, such as a plain
`collaborator`, gets no per-staff rows and a line saying so: not
pseudonyms. "Coder 1" with its own throughput still singles out one person
to anyone who knows the team, which is why the data manager's coder daily
statistics also drop the rows rather than rename them. The decision is the
helper's, per user: a user whose other active grant (on any active project)
unlocks personal data sees names here too, as on every other screen.

Counts are live and capped at 500 people per list; a longer list says it is
cut. No per-person case lists.

## Performance

One query per section for the selected level: children are joined to
submissions on ltree containment, as `get_dm_org_unit_stats_from_mv` does.
No query per unit, no scan outside the user's scope.

## Not in scope yet

Cause-of-death distribution and data-quality measures (owner, 2026-09-30).
