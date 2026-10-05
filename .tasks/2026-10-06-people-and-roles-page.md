# People & roles page (digitva-nk1)

- Status: plan, owner decisions pending (2026-10-06)
- Policy: docs/policy/people-and-roles-page.md (status proposed)

## Gap to close first
`va_user_access_grants.created_by_user_id` is written only by the project
user import; the web grant writes (admin toggle and create, DM user+grant
and grant create) leave it null. CLI and seed stay null ("not recorded").

## Proposed defaults for the open decisions
1. Entry point: one `GET /api/v1/projects/<pid>/people-roles` (+ `.csv`) and
   a standalone `/people-roles` page for every grant holder (Area pattern);
   also shown in the admin setup People section for admin/PI.
2. Reactivating a grant does not restamp granted-by: "granted at/by" stay
   the original grant's.
3. Dormant N = 90 days as a code constant; the per-project setting is
   deferred (no migration).
4. Cells of an inactive user or inactive unit are greyed, with the row flag.
5. Code cell for a coder grant above the coding scope level: grey "view
   only" (`ResolvedGrants.codes()` false).
6. Row key: person x location x cadre.
7. An In-charge (site_pi at a unit) sees audit columns as a data manager,
   for their own subtree.
8. Site-project (no tree) rows are listed, with no grid (hollow) cells.
9. Policy flips proposed -> active; access-control-model.md gets the
   "see people in the units you reach plus your reporting line" widening.

## Build (three commits)
1. Granted-by on every web grant write + docs (admin.py, data_management.py).
2. `app/services/people_roles_service.py` (one bounded grant query per
   project, ONE capability mapping, grid from `list_level_cadres`, bulk
   `pii_visible_user_ids` beside `should_redact_pii`), `app/routes/api/
   people_roles.py` (JSON + CSV), tests incl. query-count and redaction.
3. UI: `admin/panels/people_roles.html`, `static/js/admin/people_roles.js`,
   page route, setup-home include; colour + symbol + tooltip cells.
Writers for 1 and 2 touch disjoint files and can run in parallel; 3 follows
2's response shape.
