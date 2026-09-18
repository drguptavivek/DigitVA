# Per-unit coding gates

- Status: implemented 2026-09-18, pending test-runner verification (see
  docs/policy/organization-model.md "Per-unit coding gates" and the pytest
  paths below)
- Priority: medium
- Created: 2026-09-18

## Implementation notes (2026-09-18)

- Table: `map_org_unit_coding_gate` (`app/models/mas_organization.py`),
  migration `a40c38e73af4` chained onto `f1c6a9d3e7b5`.
- Resolution: `app.services.org_grant_service.resolve_unit_coding_gates` —
  one ltree query, deepest gated ancestor wins.
- Enforcement: `app/services/coder_workflow_service.py` —
  `_get_excluded_org_units_for_coding` (exclusion path, mirrors
  `_get_excluded_sites_for_coding`) and `_get_site_coding_error` extended
  with an optional `org_unit_id` (reason path), wired into both
  `allocate_random_form` and `allocate_pick_form`.
- Admin UI: `app/routes/admin_organization.py` (`GET`/`PUT`/`DELETE`
  `.../units/<org_unit_id>/coding-gate`) and
  `app/templates/admin/panels/organization.html` (gate button + form on the
  unit tree).
- Not yet run: the pytest paths listed at the end of this file — a
  dedicated test-runner session owns execution in this repo right now.

## Goal

Express the coding gates per organization unit, not only per project-site: a
coding window, an enabled flag and a daily coder limit for one PHC rather than
for the whole site.

## Decision (2026-09-18)

Yes — health-system projects want these per unit. Today they exist only on
`va_project_sites` (`coding_enabled`, `coding_start_date`, `coding_end_date`,
`daily_coder_limit`), which for a tree project is one container row covering
every unit beneath it.

## Context

Organization model phases 1-4
(`docs/current-state/health-system-organization-model.md`). The site gates are
applied in `app/services/coder_workflow_service.py::_get_excluded_sites_for_coding`,
which also carries the coding_tester and PI waivers. Unit scope resolution
lives in `app/services/org_grant_service.py::codeable_unit_ids`.

## Expected Scope

- somewhere to hold the gates per unit. Either columns on `mas_org_unit` or a
  `map_org_unit_coding_gate` table; prefer the mapping table if the gates are
  expected to grow, since `mas_org_unit` is already wide
- decide **inheritance**: does a gate on a CHC apply to the PHCs beneath it,
  or only to deaths routed to the CHC itself? The subtree reading is the more
  useful one and matches how grants work, but it means resolving the nearest
  ancestor that sets a gate
- decide **precedence** against the existing site gate: the stricter of the
  two, or the unit gate overriding the site gate where set
- the daily limit is per coder per unit and must not be double-counted against
  the site limit
- keep the coding_tester and PI waivers behaving as they do for sites
- admin UI on the Organization panel's unit editor
- tests: a closed unit excluded while its siblings stay open; inheritance in
  whichever direction is chosen; the daily limit counted once; waivers intact

## Risks

Touches the allocation path that every coder uses. The site gates and the unit
gates must compose predictably, or a coder is silently blocked with no
explanation on screen.

## Design decisions (2026-09-18)

Settled before implementation so the two gate systems compose predictably.

### Storage — a mapping table, not columns on the unit

`map_org_unit_coding_gate`, one row per gated unit: `org_unit_id` (unique),
`coding_enabled`, `coding_start_date`, `coding_end_date`, `daily_coder_limit`.
`mas_org_unit` is already wide and these gates are expected to grow (a per-cadre
limit has already been floated). **No row means no gate** — absence is not a
closed unit. That keeps the table small: a project gates the few units it needs
to, not all 900.

### Inheritance — nearest ancestor wins

A gate on a CHC applies to every PHC beneath it, unless that PHC sets its own
gate, which then wins for its own subtree. Resolution is the deepest gated
ancestor of the submission's unit, at or above it.

Chosen because it matches how the gate is described out loud ("close coding for
that block") and because it matches grants, which already inherit down the tree.
The alternative — a gate binding only deaths routed to that exact unit — makes
closing a block a 40-row operation and is silently wrong if a new PHC is added
underneath afterwards.

Resolve with one ltree query: the gated ancestors of the units in play, ordered
by depth, deepest first. Not a per-row walk up the tree.

### Precedence against the site gate — the stricter of the two

Both gates apply; neither overrides the other. A unit gate can narrow what the
site allows and can never widen it.

Chosen because the site gate is the existing contract and several projects
depend on it. If a unit gate could open a closed site, then adding a unit tree
to a project would quietly re-open coding somebody had deliberately stopped —
a change in behaviour for existing data, which rule 3 forbids.

Concretely: enabled only if both are enabled; the window is the intersection of
the two windows; the effective daily limit is `min(site, unit)` where a unit
limit is set.

### Daily limit — one count, two ceilings

The limit is not double-counted: the same allocations are counted once and
tested against the site ceiling and the unit ceiling separately. Whichever binds
first blocks. There is no separate unit counter to keep in step.

### Waivers — unchanged

`coding_tester` and PI waive the unit gates exactly as they waive the site
gates today, at the same point in `_get_excluded_sites_for_coding`.

### Explanation on screen — mandatory

`coder_workflow_service` already has a paired reason path beside the exclusion
path (the "Coding for this site opens on ..." messages around lines 359-381).
The unit gates must extend **both**, and the message must name the unit, not the
site — "Coding for Yelahanka PHC ended on ..." Without that a coder sees an
empty queue with a site-level explanation that is not true.

### Not decided yet

Whether an admin closing a level (all District-level units at once) needs its
own bulk action, or whether closing each unit is enough. Defer until the
Organization panel's unit editor exists.

## Follow-up: the eligibility board still shows site gates only

`app/routes/coding.py::_coding_status` renders a per-site eligibility summary
that reasons about `va_project_sites` gates alone. It was left untouched when
the unit gates landed (2026-09-18) — it is display-only, not the allocation
or reason path.

The consequence is worth fixing rather than leaving: a coder can see a board
saying their site is open, then be refused a form because their unit's gate
is closed. The allocation refusal now names the unit correctly, so they are
not left guessing — but the board and the refusal disagree, and the board is
what they look at first.

Not urgent, and deliberately out of scope of the original change to keep the
allocation path minimal. Whoever picks it up: the resolved gate is available
from `org_grant_service.resolve_unit_coding_gates()`, the same call the
exclusion path uses, so the board can show the effective gate rather than the
site's.
