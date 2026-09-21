---
title: Admin And Setup Model
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-09-21
---

# Admin And Setup Model

## Summary

The application includes a complete HTMX-driven admin UI under `/admin` for managing master data, users, access grants, ODK connections, and project configuration.

The admin panel is accessible to authenticated users with the appropriate role. Some panels are admin-only; others are accessible to project PIs for their own project scope.

Shell helpers and initialization services remain available for initial bootstrap and bulk operations, but day-to-day operational setup is now self-service through the web UI.

## Admin Panel Overview

The `/admin` interface provides the following management panels:

- **Access Grants** — manage user-to-project/site/unit role assignments
- **Project Sites** — manage which sites are associated with a project
- **Project Forms** — per-site ODK form mappings (ODK project ID and xmlFormId), with live dropdowns populated from ODK Central via pyODK. A site may map several ODK forms; the config row picks which one is being edited, adds another, or removes one
- **Project PIs** — manage PI assignments scoped to a project
- **Projects** — project master management (create, activate, deactivate)
- **Sites** — site master management (create, activate, deactivate)
- **Users** — user account management (create, reset password, toggle active status, assign coder languages)
- **ODK Connections** — CRUD for ODK Central connections, encrypted credential storage, test connection, and project assignment
- **Languages** — canonical language list management with ODK alias mapping. Shows unmapped language values found in submissions.
- **COD Buckets** — admin editor for imported COD reporting schemes, including hierarchy labels/order and single-target ICD-to-disease remapping by age scope.
- **Attachments** — Attachment Management: per-form attachment state, the Central self-heal switch, per-form repair, the integrity check, the S3 upload sweep and the manual local quarantine (see below)
- **ICD-10 Browser** — admin browser for `mas_icd10_2019_2`, including lazy hierarchy traversal, local policy-field curation, JSON export of curated code-policy rows, XLSX export of editable ICD rows with coding policy and COD manual override status, and a read-only legacy ICD reporting alias table for historical CoD normalization used by COD bucket reporting.
- **ICD-11 Browser** — read-only admin browser for `mas_icd11_mms` (WHO ICD-11 MMS linearization, 2026-01 release): expandable chapter/block/category tree, node details (code, class kind, chapter, residual/leaf flags, coding policy), and a code/title search. Local policy curation happens via the `flask icd11 policy-export`/`policy-import` CLI, not this panel (see docs/policy/icd11-reference-catalog.md).

All state-changing routes in the admin panel enforce CSRF protection via the `X-CSRFToken` request header.

The sync dashboard also includes ODK-backed backfill tooling:

- a project/site/form coverage table that shows ODK data, local data, metadata, and attachment completeness
- a per-form `Backfill` trigger that repairs only missing thin rows and local metadata, attachment, or SmartVA gaps for that form
- a separate per-form `Force-resync` trigger that performs a full redownload for the selected form
- a separate attachment-cache backfill trigger that only repairs missing local attachment files for already stored submissions
- a dedicated legacy-attachment panel that reports `va_submission_attachments`
  rows where `storage_name IS NULL`, split between `audit.csv` rows and actual
  media rows, plus a derived count of already repaired legacy media rows
- a legacy-attachment `Repair` trigger that populates deterministic
  `storage_name` values for legacy non-`audit.csv` media rows and renames the
  local files to their opaque storage tokens
- a global `Site Maintenance` control that starts a fixed 15-minute
  maintenance window, shows all authenticated users a bottom-centered
  maintenance banner, shows non-admin users a countdown, logs non-admin users
  out at cutoff, blocks non-admin login while still allowing admin login, and
  pushes the banner/countdown into already-open pages through a shared status
  poller without requiring a manual refresh

### Admin-Only Panels

The following panels are restricted to application-level admins:

- ODK Connections
- Attachments
- Users
- Sites
- Projects
- Languages
- COD Buckets
- ICD-10 Browser
- ICD-11 Browser

### Project-PI-Accessible Panels

Project PIs can access the following panels, scoped to their own project:

- Access Grants
- Project Sites
- Project Forms
- Project PIs
- Organization

Current grant roles include:

- `admin`
- `project_pi`
- `site_pi`
- `coder`
- `reviewer`
- `data_manager`
- `collaborator`

Current scope rules include:

- `data_manager` may be granted at `project` or `project_site`

## Project Master

Current project master data now includes:

- project identity fields
- active/inactive status
- Narrative Quality Assessment enablement
- coder and reviewer Social Autopsy analysis enablement
- coding intake mode (`random_form_allocation` or `pick_and_choose`)

Current admin behavior:

- the Projects panel can edit `coding_intake_mode`
- new projects default to `random_form_allocation`

### Web-capture readiness

Whether a project can actually collect a VA through the browser form depends
on settings spread over the Projects, Project Sites, Organization, Access
Grants and Field Mapping panels. One read-only assessment answers it, and
`docs/policy/web-intake.md` ("Ready for web capture") is the rule it
implements — nine checks, each `ok`, `warn` or `fail`, with a project ready
when none fails.

- **Endpoint.** `GET /admin/api/projects/<project_id>/web-intake-readiness`,
  open to `admin` and `project_pi`; a project PI reads only the projects they
  manage (403 otherwise), an unknown project is 404. JSON only:
  `{"project_id", "ready", "checks": [{"code", "status", "message",
  "fix_hint"}]}`. Pure reads — it creates no site, web form or grant.
- **Projects panel.** A "Web capture" column carries a badge per row —
  `Ready`, `n issues`, or `Off` when the project's web intake mode is `off` —
  fetched lazily, one request per visible project once the table has
  rendered. Opening an existing project for editing fetches the same
  assessment once more and lists every check with its status, message and fix
  hint under the Web form questionnaire block. Nothing about readiness is
  rendered server-side; the panel is a JSON client of the endpoint.
- **CLI.** `flask web-intake readiness <project_id>` prints the same
  assessment as a table and exits non-zero when the project is not ready, so
  it can gate a deployment script.

## Project Forms Panel

The Project Forms panel manages the mapping between an app project-site pair, a specific ODK Central project and form, and the VA form type used for rendering.

Key behavior:

- the site table renders immediately from local DB state
- ODK project and form dropdowns are populated lazily from ODK Central only
  when an operator opens a site's Configure row
- live ODK dropdown fetches now respect the shared ODK connection guard
  state, so cooldown/failure messages are surfaced inline instead of leaving
  the whole panel blocked
- a **Form Type** dropdown lists all active form types from `mas_form_types` (e.g. `WHO_2022_VA`, `WHO_2022_VA_SOCIAL`); selecting one links that form type to the site mapping
- each project-site pair maps to at most one ODK form and at most one form type
- conversely, one ODK form (connection + `odk_project_id` + `odk_form_id`) maps to at
  most one project-site pair: the form picker shows forms already taken by another pair
  as disabled (`— already mapped to ICMR01/NC02`) and saving one is rejected with `400`.
  A mapping on a deactivated project-site still blocks; delete it instead
- a **Mapping conflicts** block lists ODK forms mapped to more than one project-site,
  with each target's pair status and submission count. Targets on a deactivated pair get
  a **Remove stale mapping** button; two active targets are flagged as needing a manual
  decision. `flask odk-mappings audit [--fix]` reports and repairs the same thing
- the mapping is stored in `map_project_site_odk` (columns: `odk_project_id`, `odk_form_id`, `form_type_id`, `icd_classification`)
- an **ICD Classification** dropdown (`ICD-10` / `ICD-11`) selects which
  catalog coders see in that project-site's coding screens; defaults to
  ICD-10 and is shown as a badge next to the ODK form info. Stored per
  project-site, not globally, so the same form type can be ICD-10 in one
  project-site and ICD-11 in another (see
  docs/planning/icd11-coding-screen-integration-plan.md). As of phases 1-2,
  this setting is stored and exposed here, but the coding-screen search and
  validation dispatch (phase 3 of that plan) still always use ICD-10.
- the table summary shows the configured form type as a badge next to the ODK form info; a warning badge is shown if no form type is selected
- the same Configure row also edits the materialized compatibility `va_forms`
  SmartVA execution settings for that project/site form:
  - HIV
  - malaria
  - HCE
  - freetext
  - country
- saving a mapping now ensures the runtime `va_forms` row exists immediately,
  so SmartVA settings can be persisted before the first sync run
- the connection bar now shows the assigned connection's current cooldown or
  recent failure state so operators can see degraded ODK health before trying
  more live lookups

## Organization Panel

Per-project health-system tree (policy: `docs/policy/organization-model.md`).
Tabs: Units (tree with contact and location data), Levels, Cadres and
permissions (level × cadre grid: can fill / can code VA form), Workers,
ODK form fields, and Export / Import.

- "Seed template" adds District > Taluka (optional) > CHC > PHC > Sub-centre >
  Village with the default cadres; rerunning it keeps existing codes.
- Export: workbook (`/admin/api/organization/<project_id>/export.xlsx`), one
  CSV per sheet, and the ODK choices CSV for cascading unit selects.
- Import: upload the workbook, run the dry run, then apply. Rows are matched
  by code; nothing is deleted.
- ODK form fields: the exact `survey` and `choices` rows for this project's
  tree, shown for the ODK form developer to copy into the XLSForm. Each table
  copies as tab-separated rows, so a paste lands in the right columns in Excel
  or Google Sheets. Field and list names are generated from the level codes and
  must not be renamed.
- The same tab checks a mapped ODK form: pick a project-site and DigitVA reads
  that form's field list from ODK Central and reports each expected
  `org_<level_code>_code` field as present or missing. The ODK project and form
  come from the mapping, not from the request. A missing field does not fail a
  sync — submissions fall back or stay unrouted — so this is a preflight to run
  before data collection.
- Routes live in `app/routes/admin_organization.py`; rules in
  `app/services/organization_service.py` and
  `app/services/org_unit_routing_service.py`.

### Fallback organization unit on a form mapping

The Project Forms panel shows a **Fallback organization unit** picker for
projects that have an organization tree. Submissions of that ODK form whose
payload carries no `org_<level_code>_code` matching a live unit are attributed
to it; left empty, such submissions stay unrouted and appear in the data
manager's unrouted queue. The picker is hidden for projects with no tree.

### Unit-scoped grants in the Access Grants panel

Scope "Unit-level (organization tree)" adds a unit picker and a cadre picker
to the grant form, and unit grants render in their own table with the unit
code, path and cadre.

- The grant covers the chosen unit and everything below it.
- Cadre options are filtered to the cadres defined at that unit's level; for a
  coder grant, to the cadres allowed to code there, and the cadre is required.
- The data-manager grant interface refuses unit scope: it has no unit picker,
  so unit grants are created here. This holds for admins too.
- Rules: `app/services/org_grant_service.py`; policy:
  `docs/policy/organization-model.md`.

## ODK Connections Panel

The ODK Connections panel allows administrators to:

- create a new ODK Central connection (name, base URL, username, password)
- edit or delete existing connections
- test a connection against ODK Central
- assign a connection to one or more projects
- inspect shared connection-health state such as:
  - cooldown active/until
  - recent retryable failure count
  - recent failure message

Credentials (username and password) are stored encrypted in `mas_odk_connections`:

- encrypted using Fernet AES-128
- each credential field has its own per-row salt
- a shared pepper is read from the environment at runtime

Plaintext credentials are never persisted to the database.

Current operational behavior:

- each DB-managed ODK connection also stores shared guard state used by both
  app requests and background workers
- admin connection tests and live ODK lookups fail fast while a connection is
  in cooldown
- the same connection guard is used by sync and ODK write-back flows

## Attachment Management Panel

`/admin/panels/attachments` is the operator view over
[`app/services/attachment_service.py`](../../app/services/attachment_service.py).
The panel computes nothing itself and never shows a path, an object key, a
filename or a submission id — it renders what the service returns.

### What it shows

`GET /admin/api/attachments/overview` (optionally `?project_id=`) returns, in
five bulk `GROUP BY` queries with no filesystem, store or ODK Central access:

- per form, counts by `source_state`, `derivative_state`, `store_state` and
  `local_fallback_state`
- per form, attachment rows belonging to submissions retired from ODK
- per form, rows still awaiting S3 upload (`store_state != 's3'` while
  `ATTACHMENT_STORE=s3`), rendered as an upload-progress bar
- this worker's delivery outcome counters since start (`local`,
  `central_stream`, `central_redirect_followed`, `unavailable`, `error`)
- the source error categories in scope, as counts
- the S3 upload block: how many rows across the scope are still awaiting
  upload, the sweep interval, and the latest `att-s3-upload` run's status,
  uploaded count and finish time — so the cutover can be followed from the
  panel instead of an SSH session

The same figures are available from the CLI as
`flask attachments overview [--project-id X]`.

### Actions

| Action | Endpoint |
|---|---|
| Turn Central self-heal on or off for a project | `PUT /admin/api/projects/<project_id>/attachment-central-fetch` (the existing flag endpoint — the panel reuses it rather than duplicating it) |
| Repair one form's unready attachments | `POST /admin/api/attachments/forms/<form_id>/repair` — creates a `va_sync_runs` row, queues `run_form_attachment_repair`, and returns the run id |
| Check integrity against the store | `POST /admin/api/attachments/integrity-check` — queues `run_attachment_integrity_check`, whose counts land on its own `va_sync_runs` row |
| Upload backlog to S3 now | `POST /admin/api/attachments/s3-upload` — creates a `va_sync_runs` row, queues `run_attachment_s3_upload`, and returns the run id. The same sweep runs on a schedule (`ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES`), so the button only saves the wait |
| Quarantine uploaded local files | `POST /admin/api/attachments/local-quarantine` — queues `run_attachment_local_quarantine`, which moves the local copy of each verified S3-stored row aside. Manual only: this action is never scheduled, and it deletes nothing |

Every action is bounded: a repair takes at most
`ATTACHMENT_PANEL_REPAIR_MAX_SUBMISSIONS` (200) submissions per press and at
most `ATTACHMENT_REPAIR_BATCH_LIMIT` (50) attachment rows per form per batch,
and an upload sweep takes at most `ATTACHMENT_S3_UPLOAD_TASK_LIMIT` (500)
attachment rows. Concurrent upload sweeps are serialised on a Redis key, so a
press during a scheduled sweep records a `success` run rather than uploading
the same rows twice. All five endpoints are `@role_required("admin")` plus
`is_admin()`, and the POSTs carry `X-CSRFToken` like every other admin action.
These runs use their own `triggered_by` values (`att-repair`, `att-integrity`,
`att-s3-upload`, `att-quarantine`) so they do not appear in the sync
dashboard's history.

## Instrument Translations Panel

Admin-only. Lists each instrument locale from `mas_instrument_locales`:
language, locale code, headline coverage (all translatable reference items —
labels, hints, guidance hints, choice labels — informational, decided
2026-09-19 it never gates activation) with a label breakdown (WHO base +
layer question labels) shown alongside it, plus per-extension (layer)
coverage badges carrying the same item/label split, version, the workbook it
was actually imported from
(`source_document`, recorded on the row), the active flag, and an
**Approval** column (below). Importing a questionnaire source is a reviewed
one-time activity, not something the panel gates (decided 2026-09-20): any
readable workbook is accepted for any locale, so there is no separate
"documented source" to compare against and no drift badge. Actions: import a
workbook (xlsx only, 5 MB cap; an optional language name for a locale seeded
here for the first time; `cross-check` is a dry run that reads and reports
without writing), move a locale through its approval lifecycle, activate,
deactivate, edit one string (search by question name or English text, English
reference shown alongside; an edit marks the row `edited`, survives
re-import and bumps the locale version), export JSON, and exchange the
language as **XLIFF 2.0**. All state changes go through JSON routes under
`/admin/api/instrument-translations/` with `X-CSRFToken`.

**Re-importing into an already-approved locale (decided 2026-09-20,
digitva-dqh).** Both the workbook Import button and dropping an XLIFF file
onto an **Import XLIFF** button first check, client-side, whether the target
locale is `approved`; if it is, a `confirm()` dialog states that it is
approved (and active, if so), that proceeding moves it back to `in_review`,
clears its approval and deactivates it, and asks to continue before anything
is sent. Cancelling sends nothing.

`acknowledge_demotion=1` is sent **only when that dialog was shown and
accepted**. It is deliberately not sent when the panel's cached locale list
does not know the locale is approved — stale because it was approved in
another tab, or the form was used before the list loaded. Guessing there would
mean acknowledging a warning nobody saw, so the request goes without the
field, the route refuses it and names the consequence, and the operator
retries having been told. The client dialog is the convenience; the route is
the gate — see "A bulk re-import
demotes an approved locale, after warning" in
[VA Form Project Configuration Policy](../policy/va-form-project-configuration.md).
The import result panel shows the demotion when it happened.

A row whose `source` is `machine` (an LLM draft, never a workbook or a
reviewer — decided 2026-09-20, see "Machine-translated strings are not
served" in `docs/policy/va-form-project-configuration.md`) is highlighted in
the string editor and carries an **Accept** button alongside **Save**:
Accept promotes it to `edited` without retyping
(`POST .../<instrument_code>/<locale>/strings/accept`), which is what makes
it start being served. `export_translations` and coverage both exclude a
`machine` row until then.

**Approval before activation (decided 2026-09-20).** The Approval column
shows a badge for the locale's `lifecycle_state` (Draft, In review,
Approved) and, once approved, who approved it (rendered from
`approved_by_user_id`, the same way a coder's name is rendered from a
`user_id` elsewhere in this application: joined against `va_users.name`).
Buttons move the locale between states: **Send for review**
(`draft` -> `in_review`), **Approve** (`in_review` -> `approved`), and
**Back to draft** (`in_review`/`approved` -> `draft`; `approved` also offers
**Send for review** back to `in_review`) — each posts to
`POST .../<instrument_code>/<locale>/lifecycle` with `{"state": ...}`.
Entering `approved` records the acting admin and the timestamp; leaving it
clears both. The **Activate** button is disabled, with a tooltip, unless the
locale is `approved` — the service refuses the same request server-side
(naming the locale and its current state) and the database CHECK constraint
`ck_mas_instrument_locales_active_requires_approved` is the backstop under
both. **Deactivate** is never disabled: a locale must be deactivated before
it can leave `approved`, so the panel never blocks the one action that makes
that possible.

**Operator note after this upgrade.** The migration that adds this lifecycle
(`a3f7c1d9e6b4`) deactivates every existing locale as a deliberate,
one-time behaviour change — not a no-op backfill (see the migration's own
docstring). After upgrading, **all locales are deactivated pending
approval** until an administrator approves and reactivates each one;
interviewers fall back to English per string in the meantime. Sizing for that
re-approval pass, measured 2026-09-20 against the 80 DigitVA layer
question-label items, counting only what a plain re-import of each language's
own workbook supplies. Machine-translated rows are **not** counted: they exist
in the panel awaiting review and are not served (see "Machine-translated
strings are not served" in
[VA Form Project Configuration Policy](../policy/va-form-project-configuration.md)),
so they are shown here as a separate column — accepting a draft as-is closes
that much of the gap immediately.

| Locale | Short by | Of which a machine draft awaits acceptance | What remains after that |
| --- | --- | --- | --- |
| Hindi | 8 of 80 | 5 | social autopsy section headings ND01 left in English |
| Khasi | 8 of 80 | 0 | all of it — Khasi is deliberately absent from the seed |
| Odia | 9 of 80 | 5 | social autopsy headings |
| Marathi | 14 of 80 | 6 | death summary, one social autopsy heading |
| Bangla, Kannada, Malayalam, Tamil | 39 of 80 each | 5 each | the whole social autopsy layer; their DS workbooks lack it |
| Arabic, French, Portuguese, Spanish, Swahili | 80 of 80 each | 5 each | the WHO multilingual workbook carries no DigitVA layer at all |

These counts are against **question labels only**, which is the panel's
*breakdown* figure, not its headline. Since `digitva-o3s` the headline counts
every translatable string -- 1,435 of them against 556 question labels -- so
hints, guidance notes and choice labels are outside this table's scope but
inside the number the panel leads with. A locale therefore reads lower overall
than this table's gaps alone would suggest.

ABHA is seeded for the seven Indian locales only, since Ayushman Bharat
Health Account is an Indian scheme and other locales' projects do not enable
the `abha` extension. This is sizing information for the admin doing the
re-approval work, not a programmatic gate — coverage still decides nothing
(2026-09-19 decision stands).

**Stale as of digitva-4kj (2026-09-20).** The table above was measured
counting migration `b6d2f4a9c1e7`'s seeded strings as translated. That
migration's rows are unreviewed machine drafts (see "Machine-translated
strings are not served" in `docs/policy/va-form-project-configuration.md`);
coverage now excludes a `machine` row until an administrator edits it or
accepts it as-is, so the "Short by" counts above will have moved back toward
their pre-`b6d2f4a9c1e7` size. Not recomputed here.

The reference a language is translated against is the WHO base workbook plus
the DigitVA layer questions from the committed
`vendor/who-va-2022/src/generated/digitva-layers.reference.json` artifact
(`app/services/instrument_translation_service.py` reads it; production
happens in `tooling/who-va-2022/build-layer-reference.mjs`). Both coverage
figures span the WHO base and the DigitVA layers together: the headline counts
every translatable string (question labels, hints, guidance notes and choice
labels) and the breakdown counts question labels alone. Before `digitva-o3s`
the label figure excluded layer labels, which is why every locale reported 100
percent while a third of its translatable text was untranslated. Each
extension's own coverage is reported alongside, on the same two measures.

A workbook cell that packs English and the target language together
(newline-, `" / "`- or `English (Translation)`-separated) is unpacked on
import (`split_packed` — conventions and the "equal to English is not a
translation" rule are in `docs/policy/va-form-project-configuration.md`,
"Translation sources"). **Operator step:** a language imported before that
splitting logic changed keeps whatever it produced at the time until someone
re-runs the import for that language; an administrator's `edited` correction
is never overwritten by a re-import, but a stale `imported` row is only
corrected on request.

Each language's row carries an **XLIFF** link
(`GET .../<instrument_code>/<locale>/xliff`, served as
`application/xliff+xml` and downloaded as `<INSTRUMENT>-<locale>.xlf`) and an
**Import XLIFF** button that uploads the returned file
(`POST` the same path, `.xlf`/`.xliff` only, 5 MB cap, `X-CSRFToken`). The
card below chooses whether the written rows are marked `imported` — a bulk
hand-back that leaves an administrator's edits standing — or `edited`, which
outranks a later workbook re-import. The result panel reports units read,
written, unchanged, kept edited, empty targets left alone, units the reference
form does not have, and targets over the length cap. XLIFF exchanges the
strings of a language that already exists; a *new* language still starts from
a workbook import. Rules:
`docs/policy/va-form-project-configuration.md` ("Interchange format").

The interviewer's form fetches
`GET /api/v1/instruments/<instrument_code>/translations/<locale>` by version
and revalidates against `translation_versions` in the form-options
payload, so an edit reaches interviewers on their next form. A locale is
offered to a form only when it is servable -- active, or `in_review`
(since 2026-09-21, `digitva-mxn`; `draft` never) -- **and** the project lists
it in `web_intake_available_locales`; "the language I imported is not in the
picker" resolves to one of those two. The predicate is defined once,
`SERVABLE_LOCALE` in `app/services/web_form_instruments.py`. Form-options
entries and `/admin/api/web-form-locales` carry `under_review`; the Projects
panel and the intake picker label such a locale "(under review)", and the
intake page forces its "Show English" toggle on for it (see "English
alongside the translation" in `docs/policy/va-web-form-options.md`).

**New-install operator step, after seeding (not a migration):** for each
row of the "Translation sources" table in
`docs/policy/va-form-project-configuration.md`, run
`flask instrument-translations import WHO_2022_VA <locale> docs/kb/WHO_VA_2022_Docs/<workbook>`
or upload through the panel, then approve and activate. A fresh database
serves `en` only until this is done — even though, since migration
`7134cb5dc7b6` (decided 2026-09-20, digitva-dms), the twelve DigitVA-layer
locales already exist as `draft` and inactive with their `machine`-sourced
strings, so they appear in this panel from the first install rather than
only after someone runs an import.

## Languages Panel

The Languages panel manages the canonical language list and ODK alias mappings used throughout the application.

### Data Model

- **`mas_languages`** — canonical language list with `language_code` (PK), `language_name`, and `is_active` flag
- **`map_language_aliases`** — maps raw ODK field values to canonical codes (e.g., `"bn"` → `"bangla"`, `"Bengali"` → `"bangla"`)

### Key Behavior

- the panel lists all canonical languages with their aliases and submission counts
- admins can create, edit (rename/update aliases), and toggle languages active/inactive
- **unmapped values alert**: the panel detects language values in `va_submissions` that don't match any alias and displays them prominently so the admin can add them
- aliases can be added or removed inline; the language code itself is always kept as an alias
- alias conflicts across languages are prevented (one alias maps to exactly one language)
- deactivated languages are hidden from admin user-language assignment but existing data is preserved

## Users Panel And Language Assignment

The Users panel is the operational place to manage each user's `vacode_language`
selection.

Current behavior:

- admins assign one or more active canonical languages when creating a user
- admins can later edit that language set for existing users
- those assigned languages drive coder and reviewer narration-language filters
- the self-service My Profile page no longer edits coding languages; it only
  handles password and timezone changes

### Sync Integration

- during ODK sync, raw `narr_language` / `language` values are normalized to canonical codes via `_normalize_language()` before storage
- the alias lookup is cached per sync run (cleared at start of each run)
- unknown values (no matching alias) pass through unchanged and appear in the unmapped alert

### API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/api/languages` | List languages (optional `include_inactive`, `include_unmapped`) |
| POST | `/admin/api/languages` | Create new language with aliases |
| PUT | `/admin/api/languages/<code>` | Update name and/or aliases |
| POST | `/admin/api/languages/<code>/toggle` | Toggle active/inactive |
| DELETE | `/admin/api/languages/<code>/aliases/<alias>` | Remove a single alias |

## Current Setup Path

The main operational shell helpers are exposed in:

- [`run.py`](../../run.py)

Important shell operations include:

- `va_db_initialise_researchprojects()`
- `va_db_initialise_researchsites()`
- `va_db_initialise_vaforms()`
- `va_db_initialise_vausers()`
- `va_mapping_icd()`
- `va_mapping_fieldsitepi()`
- `va_mapping_fieldcoder()`
- `va_mapping_choice()`
- `va_mapping_summary()`
- `va_mapping_summaryflip()`
- `va_mapping_info()`
- `va_mapping_flip()`
- `va_data_sync_odkcentral()`

## Form Type Bootstrap

The field-mapping admin panel depends on rows in `mas_form_types`.

Operational baseline:

- seeded languages do not imply seeded form types
- the Languages panel may be populated while the field-mapping panel still shows no form types
- the default `WHO_2022_VA` form type and its mappings are bootstrapped by the seed command, not by the Languages panel

If `/admin/?panel=%2Fadmin%2Fpanels%2Ffield-mapping` shows:

- `No form types registered yet. Click New Form Type to create one.`

the standard recovery path is:

```bash
docker compose exec minerva_app_service uv run flask seed run
```

Current behavior of that command for field mapping bootstrap:

- registers `WHO_2022_VA` in `mas_form_types` if missing
- migrates the default WHO 2022 category, field, and choice mappings from:
  - `resource/mapping/mapping_labels.xlsx`
  - `resource/mapping/mapping_choices.xlsx`
- safely skips languages and the default admin user if they already exist

## Full Initialization Flow

The shell helper `va_initialise_platform()` currently performs:

1. database backup creation — a real `pg_dump` through
   `db_backup_service.create_db_backup()`, recorded in `va_db_backups` and
   written to whichever store `ATTACHMENT_STORE` selects (see
   [backup.md](backup.md))
2. full schema drop and recreate
3. seed project, site, and form master data
4. load ICD codes
5. generate mapping Python modules from spreadsheets
6. perform ODK sync
7. initialize users

This reflects the current one-project-first bootstrap model.

## Mapping Administration

Mapping spreadsheets are stored under:

- `resource/mapping`

The app does not read them dynamically from the UI on every request.

Instead, service functions read the spreadsheets and generate Python modules under:

- `app/utils/va_mapping`

This is currently an operational/admin task, not a user-facing feature.

## User And Access Administration

The admin UI supports:

- creating and deactivating user accounts
- resetting user passwords
- assigning and revoking user access grants scoped to projects and sites

Underlying service functions remain available for shell-based operations:

- `va_user_create`
- `va_form_addform`
- `va_site_addsite`
- `va_researchproject_addproject`

## Operational Consequences

The admin UI makes the platform self-service for:

- adding and managing users
- assigning access grants
- configuring ODK connections and project-site form mappings
- managing project and site master records

Mapping spreadsheet regeneration and full platform initialization remain developer/operator tasks performed through the Flask shell.
