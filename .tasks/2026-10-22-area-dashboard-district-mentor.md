# Area dashboard for district offices and mentoring institutions (digitva-qfh8)

Status: approved 2026-10-22 (owner: "extend and simplify"). Decisions: extend /area/ and simplify it; lift the cause-distribution exclusion with n<5 suppression and hide under 20 coded; allow `collaborator` for mentors; mentors with coder/reviewer grants may see staff names. Period basis per (e) recommendation.

## Decision proposed

Do not build a new dashboard. Extend `/area/` (`app/routes/area.py`,
`app/services/area_dashboard_service.py`, `app/routes/api/area.py`, policy
`docs/policy/area-dashboard.md`): it is already grant-scoped, count-only, with an
ltree drill-down, linked from Expo web ("Statistics", `src/web/navTabs.ts:44`) and
the Mentoring screen (`src/web/MentoringScreen.tsx:696`).

## Access (no new auth model)

- District office: existing typical roles at org_unit scope (DPM `data_manager`,
  DEPI `collaborator_pii`, CS `site_pi`); aggregates-without-names via plain
  `collaborator` at org_unit scope (`should_redact_pii`).
- Mentors: reach `/area/` via coder/reviewer/coding_tester/collaborator_pii; root
  = union of unit grants. Gap: `collaborator` is denied for mentors
  (`mentor_institute_service.check_mentor_grant` ~625).
- Counts only; no names, phones, addresses, SIDs. Operational counts never
  suppressed; cause table suppresses causes with n < 5 (or 10) and hides when
  total coded < 20 (`PERCENT_MIN_WHOLE`).

## Additions (per child-unit row unless noted)

1. Deaths reported 7d/30d (`digitva-yeg3.27`).
2. Interviews pending + backlog age (>7d, >30d since registration).
3. SmartVA failed (active result outcome failed).
4. Card: median days death→interview and interview→final COD (selected area).
5. Card: top causes (WHO_2022_VA_2026 buckets) with counts and suppression.
6. Project card: offline stations count and oldest sync.
Cut: SmartVA run counts, reviewed %, coder throughput, data-quality flags,
sync-run status.

Period filter (30d/90d/12m/all) for deaths/submitted/causes; CSV of aggregates
via `/api/v1/area/summary?format=csv`.

## Queries

One grouped query per widget over `child.path <@ MasOrgUnit.path` (GiST).
Medians need one additive migration: index `ix_va_death_register_va_sid`.
Check `va_smartva_results (va_sid, is_active)` index. Top causes reuse
`cod_bucket_mapping_service.aggregate_coded_submissions_by_bucket`. No cache or
new MV unless the summary exceeds ~1 s on staging data.

## Build slices (~4.5 days, tests in tests/services/test_area_dashboard_service.py
and tests/routes/test_area_dashboard_api.py)

0. Policy amendment (area-dashboard.md; organization-model.md if mentors get
   `collaborator`). 1. Deaths 7d/30d + period (closes yeg3.27). 2. Pending +
   backlog. 3. SmartVA failed. 4. Migration + medians. 5. Top causes +
   suppression + CSV. 6. Stations on project card. 7. Optional mentor
   `collaborator`.

## Open owner decisions

a. Lift the 2026-09-30 policy exclusion on cause distribution?
b. Suppression threshold 5 or 10; hide the cause table under 20 coded?
c. Allow `collaborator` (no names) for mentors?
d. Mentors holding coder/reviewer grants see district staff names in the staff
   view today: acceptable?
e. Period basis: registration date for operational columns, date of death for
   causes (recommended)?
f. Stations per unit needs `auth_devices.org_unit_id`: deferred.
g. `yeg3.26` / `yeg3.24` stay on the DM page; `/area/` links to them.
