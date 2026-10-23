---
title: Area Dashboard Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-23
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
- District offices through their usual roles at the district unit (data
  manager, collaborator with or without personal data, site PI); mentoring
  institute staff through their mentor-role unit grants, `collaborator`
  included for a mentor who should see counts without names
  ([Organization Model](organization-model.md), "Mentoring institutes").
- `admin` sees every project whole.
- The page and API require only a signed-in session, not a role: a role list
  would refuse users with no grant instead of showing them an empty page.

## Scope

Resolved per project, as a union over all of the user's roles. A project
"has a tree" when it has an active organization level
(`org_grant_service.projects_with_org_tree`), the same test authorization
uses; the reach is `authz.reachable_unit_ids`:

- A project-scoped or project-site-scoped grant on an **organization** project
  gives the whole tree. The automatic `O###` site is the project
  (`organization-model.md`), so a site grant there is project-wide
  (a project or pair grant in `authz.ResolvedGrants`).
- Otherwise the subtrees of the user's org-unit grants
  (`authz.reachable_unit_ids`), the same viewing scope `authz.can(VIEW)`
  gives each role.
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
  project, and to the site, unit or period start where the count is exactly
  that filter;
- coder: the coding dashboard, from the awaiting-coding count;
- interviewer: web intake, from the submitted count.

No link otherwise. Links carry project, site and unit codes and a date
only, never
subject or staff data. Collaborators also reach the data manager dashboard
and get the data manager's links (owner, 2026-10-09). The link test is the role on the
project, not that role's reach: a data manager on one site of a project the
user sees whole through another role gets a link whose landing page shows
only their site. The target screen enforces its own scope, so this can
show a smaller number, never more data.

Retired submissions, confirmed duplicates and inactive project-sites are
left out of every count, as on the data manager dashboard.

**Simplified for district offices and mentoring institutions** (owner,
2026-10-22, `digitva-qfh8`). The page is one card for the selected area, one
table of that area's child units, the drill-down and the links. Cut, as not
decision-useful to a district officer or a mentor: the coding-progress tiles
and the Site PI KPI tiles (open to review, reviewer finalized, final COD by
coder and by reviewer, changed in ODK after coding: these stay on the data
manager dashboard and the Site PI page), the submitted last 7 and 30 days
columns (the period filter replaces them), web interviews in progress
(replaced by interviews pending), the in coding, in review, coded (coder
finalized) and other columns, and the per-coder throughput table of the
staff view (the data manager's coder statistics keep it). SmartVA run
counts, data-quality flags and sync-run status were never on this page and
are not added.

The page opens at the user's grant roots and drills down one level at a time
(the selected unit's direct children, with a breadcrumb back up). Each row
is the unit's whole subtree, counted once.

### Period

One filter, *Last 30 days*, *Last 90 days*, *Last 12 months* or *All time*
(the default, which keeps the page's earlier meaning). It applies to deaths
reported (by registration date, `created_at`), submitted (by submission
date) and causes of death (by date of death: the case register's date of
death when the submission has a case, else the submission date, since ODK
submissions synced before cases existed have no register row). The backlog
columns are current state and never filtered: interviews pending, awaiting
coding, not codeable, SmartVA failed, final COD and visit notes.

### Table columns

- **Deaths reported**: death-register cases (`VaDeathRegister`, every
  source) registered in the period, live, and also those of the last 7 days
  (the API and CSV carry the last 30 days too, `digitva-yeg3.27`). Confirmed
  duplicates and cancelled cases are left out. An unrouted case counts in
  the Unrouted row. No link: no data manager filter selects death-register
  cases.
- **Interviews pending**: open cases (registered, scheduled, in progress,
  paused, not reachable), live, with how many have waited **over 7 days**
  and **over 30 days** since registration.
- **Submitted**: submissions received in the period (web and ODK alike,
  from the hourly snapshot).
- **Awaiting coding**: screening, attachment sync, SmartVA pending or ready
  (the `awaiting_coding` bucket of `coding_bucket`, snapshot).
- **Final COD**: submissions whose final cause of death holds authority
  ([Final COD Authority](final-cod-authority.md)), live.
- **Not codeable**: marked not codeable by a coder or data manager, or
  consent refused (the `not_codeable` bucket, snapshot).
- **SmartVA failed**: submissions whose active SmartVA result has outcome
  `failed`, live. These need a data manager to rerun or code without SmartVA.
- **Visit notes** (owner, 2026-10-09; built `digitva-96a7`): the nameless
  refusals that carry a visit note ([Web Intake Policy](web-intake.md),
  "Visit note"), live. For a viewer with the data manager's link the count
  links to the record list filtered to them (`visit_note=1` with `org_unit`,
  the subtree, or `site`; the list still applies the viewer's own scope),
  where each record shows its note, minus address and remarks for a viewer
  `should_redact_pii` redacts. The Unrouted row is a count without a link.

**One coded definition.** The table and card show only *Final COD* (the
authority definition). The two-definition layout of 2026-10-09 (a
"Coded (coder finalized)" column beside "Final COD") is superseded by the
2026-10-22 simplification: one number for "coded", so the two can no longer
disagree on the page.

**Unrouted submissions** (no org unit) fall outside every subtree, so child
rows do not sum to the project total. Users with a project-wide scope see an
"Unrouted" row at the project root so the totals reconcile.

### Area card

Above the table, for the selected area: the selected unit's subtree; at the
root the union of the user's grant roots (the whole project, unrouted
included, for a project-wide scope); in sites mode the in-scope sites or the
selected site. It shows the table's numbers for that whole area (not the sum
of the child rows, which leaves out cases on the selected unit itself), and:

- **Median days from death to interview**: the case register's date of
  death to the submission date, over submissions that have a case with a
  date of death; all time.
- **Median days from interview to final COD**: submission time to the time
  the final COD took authority (`effective_at`, else when the authority row
  was written); all time.
- **Top causes of death** (lifts the 2026-09-30 exclusion; owner,
  2026-10-22): coded submissions (a human final COD with an ICD code, the
  base of the COD bucket report) in the area and period, grouped by the
  default reporting scheme's cause groups (`WHO_2022_VA_2026`). Small-cell
  suppression: the table is **hidden when fewer than 20** submissions are
  coded in the area and period (`PERCENT_MIN_WHOLE`), and any cause with
  **fewer than 5** deaths is folded into one *Other (suppressed)* row with
  the causes beyond the top ten and codes the scheme does not map. Shares
  are of the coded total. Suppression is applied in the service, so the
  JSON and CSV never carry a small cell.

### Project card

At the project root, a user whose scope is project-wide also sees the
project's offline stations. A station is an active (not revoked) enrolled
device that has been issued a station config; handsets are not stations.
The card shows how many there are, how many have never sent a bundle, the
latest bundle of the station that has waited longest, and the newest bundle
of any station. A station does not call home, so its bundles, not
`last_seen_at`, are its last contact. Counts and times only. Stations per
unit needs a unit on the device and is
deferred. The card keeps the data manager and coding links.

### CSV export

`/api/v1/area/summary?format=csv` returns the same level, scope and period
as aggregates only: one line per (section, area, measure) with the table
rows, the card and the suppressed cause rows. No person names, no
submission or case ids, no case-level rows. A cell that starts with `=`,
`+`, `-` or `@` is prefixed with `'` so a spreadsheet does not run it.

**Freshness.** Snapshot counts carry the finish time of the last recorded
snapshot refresh (hourly; an ad-hoc refresh records no run, so the time is a
lower bound); live counts say so. The two are labelled separately.

## Staff identity

An optional "By interviewer" view under the table breaks the same area down
per interviewer (`digitva-stc.2`). It is offered at a selected unit or site, and at
the project root for a project-wide scope; a unit-scoped user's root is
several areas, so it has none. The area is exactly the rows': the selected
subtree counted once, or the whole project including unrouted cases.
Confirmed duplicate cases count nowhere.

- **Interviewers**: cases registered (register-first cases, by who
  registered them), interviews started (by who opened the first interview
  on the case), interviews submitted and in progress (by the draft's
  owner), and contact attempts logged in the last 30 days.

The per-coder throughput table was removed on 2026-10-22 (see "What it
shows"); the data manager's coder daily statistics keep it.

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

## Home KPIs

The strip at the top of the home page (owner, 2026-10-12), one row per
project in the user's area, over the same scope `/area/` uses (any grant,
viewing scope):

- **Deaths reported**: cases in the death register, every source, minus
  confirmed duplicates and cancelled cases.
- **Interviews done**: total VA submissions in scope, as `/area/` shows them.
- **Coded**: submissions with a final COD.
- **Interviews %** and **Coded %**: each as a percentage of deaths reported,
  integers rounded half up. Null when deaths reported is under 20 or smaller
  than the count (a share of a small or non-covering denominator misleads).
  Clients print the value as sent and never sum projects into a percentage.

Totals only, no unit or site rows, and no names. Each grant's root units
(or, in sites mode, the active sites in scope) are summed; the unrouted
bucket counts for a project-wide scope. Cached per user for 60 seconds. A grant added or revoked shows in the strip within that minute; the strip carries counts and project names only, so this window is accepted rather than clearing the cache on every grant write.

## Area summary cache

`area_summary` is cached per user, project, unit, site and period for 60
seconds, as Home KPIs are. A grant added or revoked, or a count that moves,
shows within that minute. AreaNotFound and ValueError are never cached.

## Performance

One query per section for the selected level: children are joined to
submissions on ltree containment, as `get_dm_org_unit_stats_from_mv` does.
No query per unit, no scan outside the user's scope. Home KPIs run one
grouped query per measure per project, whatever the unit count.

## Not in scope yet

Data-quality measures (owner, 2026-09-30). Offline stations per unit
(needs `auth_devices.org_unit_id`). The cause-of-death distribution, out of
scope on 2026-09-30, is in the area card since 2026-10-22, suppressed as
above.
