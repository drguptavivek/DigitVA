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

Counts only. No case lists, no subject data, no names on the first slice.
Links from a count to the screen the user's role already has for that work
come later (`digitva-stc.3`).

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

**Freshness.** Snapshot counts carry the finish time of the last recorded
snapshot refresh (hourly; an ad-hoc refresh records no run, so the time is a
lower bound); live counts say so. The two are labelled separately.

## Staff identity

A per-interviewer or per-coder breakdown is a later slice. When it comes it
is shown only to roles that may see staff identity, decided through
`should_redact_pii`, never a per-screen role test; plain `collaborator` sees
no names (`access-control-model.md`).

## Performance

One query per section for the selected level: children are joined to
submissions on ltree containment, as `get_dm_org_unit_stats_from_mv` does.
No query per unit, no scan outside the user's scope.

## Not in scope yet

Cause-of-death distribution and data-quality measures (owner, 2026-09-30).
