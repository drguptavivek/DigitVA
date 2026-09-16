---
title: ICD-11 Coding via Self-Hosted WHO ICD API and Embedded Coding Tool
doc_type: planning
status: proposed
owner: engineering
last_updated: 2026-09-16
---

# ICD-11 Coding via Self-Hosted WHO ICD API and Embedded Coding Tool

## Problem

DigitVA codes causes of death in ICD-10 2019 only. The catalog lives in
`mas_icd10_2019_2`, coding-time lookup goes through the `/api/v1/icd10/*`
routes, and the coder panels link to the WHO ICD-10 browser and to the
ICD-10-only PDF extract in `app/static/WHO_2022_VA_CODES.pdf`.

WHO's 2026 manual for physician reviewers now publishes the WHO 2022 VA target
list with ICD-11 correspondences. The repository keeps that table as reference
data in
`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md`.
Nothing in the application can search, validate, store or bucket ICD-11 codes.

## Goal

1. Let physician coders assign ICD-11 MMS stem codes alongside ICD-10, without
   a WHO developer account and without a runtime dependency on WHO servers.
2. Keep authorization, CSRF and VA allowability enforcement on the server, in
   the same shape as the ICD-10 routes, so server-rendered pages, HTMX and a
   future React client share one contract.
3. Map ICD-11 selections to WHO VA buckets using only the ranges WHO published
   in the 2026 annex.

## Non-Goals (this phase)

- Replacing ICD-10 coding or changing existing ICD-10 policy or bucket behaviour.
  ICD-10 stays mandatory; ICD-11 is additive and optional until policy says
  otherwise.
- Postcoordination clusters (stem code plus extension codes). Stem codes only.
- ICD-11 in languages other than English.
- Publishing a DigitVA-authored crosswalk between ICD-10 and ICD-11 (see the
  licence note below).

## Source Material and What Was Verified

The WHO documentation pages could not be opened from the environment used to
prepare this plan, so facts are marked by how they were established:

- **Verified from the package source**: the Embedded Coding Tool (ECT) npm
  package `@whoicd/icd11ect` 1.8.0 (published 2026-03-20) was downloaded and its
  bundle inspected for settings defaults, callbacks, handler methods and the
  shape of the selection object. The bundled ICD-11 Terms of Use were read.
- **Verified from Docker Hub metadata**: image `whoicd/icd-api` tags, dates,
  architectures and sizes.
- **From search snippets of the WHO pages**: container environment variables,
  default release, tool paths, service ports, and the statement that ICD-10 is
  not supported in the container. These should be re-read on the WHO pages
  before implementation:
  - `https://icd.who.int/docs/icd-api/ICDAPI-DockerContainer/`
  - `https://icd.who.int/docs/icd-api/ICDAPI-LocalDeployment/`
  - `https://icd.who.int/docs/icd-api/icd11ect-1.8/EmbeddedCodingTool/`

## Components

| Component | Version | Notes |
|---|---|---|
| WHO ICD API container `whoicd/icd-api` | 2.6.0 (March 2026, tag also `latest`) | linux amd64 and arm64, about 192 MB compressed, ICD-11 only |
| Embedded Coding Tool `@whoicd/icd11ect` | 1.8.0 (March 2026) | React-based UMD bundle `index.js` (about 750 KB) plus `style.css`; exports global `ECT` |
| Default content in the container | ICD-11 release 2026-01, English | other releases and languages selected with the `include` variable |

### WHO ICD API container

- Basic run: `docker run -p 80:80 -e acceptLicense=true -e saveAnalytics=false whoicd/icd-api`.
- `acceptLicense=true` is mandatory. `saveAnalytics=true` would send anonymised
  search analytics to WHO; DigitVA sets it to `false`.
- `include` selects release and language, for example `include=2026-01_en`.
  Several values may be comma separated. Each extra release or language raises
  memory use. WHO publishes no memory figure on the pages reached, so the
  footprint must be measured in staging before sizing production.
- The local API needs no OAuth2. It also serves the ICD-11 Coding Tool at
  `/ct11` and the ICD-11 Browser at `/browse11` (newer builds use `/ct` and
  `/browse`).
- ICD-10 is not available in the container; ICD-10 stays on the existing local
  catalog.
- Alternatives exist as a Windows service installer and a Linux systemd package
  (x64 binaries, port 8382, settings in `appsettings.json`). The container fits
  the existing compose stack better and is the recommended option.
- REST paths the app will use, to be confirmed against the API v2 documentation:
  linearization root `/icd/release/11/{release}/mms`, entity by id, children by
  `child` URIs, search under the linearization, and `codeinfo/{code}`. Requests
  carry `API-Version: v2`, `Accept: application/json` and `Accept-Language: en`.
  The ECT bundle uses `POST` for its searches.

### Embedded Coding Tool 1.8

- Markup: an `<input class="ctw-input" data-ctw-ino="1">` search box and a
  `<div class="ctw-window" data-ctw-ino="1">` results window. The `data-ctw-ino`
  value is the instance number passed to callbacks and handler methods.
- Configuration: `ECT.Handler.configure(settings, callbacks)`.
- Defaults read from the 1.8.0 bundle: `apiServerUrl` empty and required,
  `apiSecured` false, `source` (alias `icdLinearization`) `mms`, `minorVersion`
  (alias `icdMinorVersion`) empty meaning latest loaded release, `language` en,
  `sourceApp` empty, `autoBind` true, `enableKeyboard` true, `hierarchyResizable`
  true, `otherPostcoordination` true. Filtering and layout settings include
  `chaptersFilter`, `subtreesFilter`, `chaptersAvailable`, `wordsAvailable`,
  `flexisearchAvailable`, `searchByCodeOrURI`, `hierarchyTitle`, `height`,
  `enableSelectButton`, `popupMode`, `simplifiedMode`, `disableHierarchy`, and
  the browser variants `browserSearchAvailable`,
  `browserAdvancedSearchAvailable`, `browserHierarchyAvailable`, `browserURI`
  and `browserHierarchyRootURIs`.
- Callbacks: `selectedEntityFunction`, `getNewTokenFunction` (only for the
  WHO-hosted secured API, unused here), `searchStartedFunction`,
  `searchEndedFunction`, plus browser open, close and selection callbacks.
- Selection object fields: `iNo`, `uri`, `linearizationUri`, `foundationUri`,
  `code`, `title`, `bestMatchText`, `selectedText`.
- Handler methods: `configure`, `bind`, `clear`, `search`, `refresh`,
  `setLanguage`, `overwriteConfiguration`, `overwriteSettings`.
- The ECT runs in the coder's browser and calls `apiServerUrl` directly. It also
  posts client analytics (search text, selected code and URI, `sourceApp`) to
  `{apiServerUrl}/analytics/clientanalytics`. With a local container that data
  stays inside DigitVA's network.
- Delivery: vendor the three package files (`index.js`, `style.css`,
  `license.pdf`) under `app/static/vendor/icd11ect/1.8.0/` rather than loading
  from WHO's CDN, so versions are pinned and coders on restricted networks are
  not blocked. The licence permits embedding but not modifying the bundle.

### Licence Constraints (ICD-11 Terms of Use and License Agreement)

- ICD-11 content is licensed CC BY-ND 3.0 IGO. Reproductions must keep the
  ICD-11 codes and URIs and carry WHO attribution. DigitVA stores codes, URIs
  and titles unchanged and shows the attribution string in the coding UI.
- The ICD-11 software (local API, ECT) may be integrated into applications for
  commercial or non-commercial use, must not be sold as a standalone product,
  and must not be modified, adapted or reverse engineered.
- Adding data fields to ICD-11 concepts is permitted when the additions are
  clearly identified as such. DigitVA's local policy fields (selectability, sex
  and age restrictions) fall under this and are documented as DigitVA additions.
- Mappings or crosswalks between other classifications and ICD-11 are not
  covered by the ICD-11 licence and need a separate written agreement with WHO.
  DigitVA therefore uses only the WHO-published annex ranges for VA buckets and
  does not publish its own ICD-10 to ICD-11 crosswalk. The public health lead
  should confirm this reading before any mapping leaves the project.

## Proposed Design

### 1. Infrastructure

- Add `icd_api_service` to `docker-compose.yml`: image `whoicd/icd-api:2.6.0`
  (pinned, never `latest`), environment `acceptLicense=true`,
  `saveAnalytics=false`, `include=2026-01_en`, internal compose network only,
  no published host port, a memory limit set after measurement, and a health
  check against the linearization root.
- Browser reachability: the ECT needs the API from the coder's browser, and the
  local API has no authentication of its own. Expose it under the application
  origin at `/icd-api/` through the reverse proxy, guarded by an `auth_request`
  subrequest against a lightweight Flask session-check route. Fallback if the
  proxy cannot do that: a thin Flask streaming proxy restricted to logged-in
  coders. In both cases the container stays off the public internet.
- Egress: confirm in staging that the container makes no outbound calls with
  `saveAnalytics=false`, and that the ECT's analytics posts land only on the
  local service.
- Release upgrades: a new `include` value is a new master snapshot (see data
  model), never an in-place rewrite of the existing release rows.

### 2. Data Model (additive, migration-planned)

- `mas_icd11_mms`: one row per linearization entity for a given release.
  Columns: `release`, `entity_id` (foundation numeric id), `code` (null for
  blocks and other uncoded nodes), `linearization_uri`, `foundation_uri`,
  `title`, `parent_entity_id`, `chapter_code`, `depth`, `is_leaf`,
  `class_kind`, `is_residual` (codes ending in Y or Z), plus DigitVA policy
  fields mirroring the ICD-10 catalog: `is_coding_selectable`,
  `sex_selectable`, `age_group_selectable`, `restriction_note`, `is_active`.
  Unique on (`release`, `entity_id`). Policy fields are documented as local
  additions per the licence.
- Coder review and final assessment models gain ICD-11 counterparts for each
  ICD-10 cause field (code plus linearization URI, so the release is
  recoverable). Exact columns follow the current review model and the final COD
  authority policy; nullable, so existing rows are untouched.
- VA buckets: extend the existing COD bucket scheme model with an ICD-11 scheme
  if it is classification-neutral; otherwise add `map_icd11_va_bucket`
  (`release`, `va_code`, `entity_id`, `code`, `source`). The source for this
  phase is the 2026 WHO annex only.
- Every schema change ships with an Alembic migration; fresh-schema seeding
  follows the ICD-10 catalog policy pattern (checked-in generated CSV loaded
  during migration, idempotent re-import, missing rows marked inactive, never
  deleted).

### 3. Master Load (Celery task)

- Walk the linearization from the local API: root, then children via `child`
  URIs, breadth first, in batches. Upsert on (`release`, `entity_id`), mark rows
  absent from the source inactive, preserve local policy fields on rerun.
- Stream and batch; never hold the whole tree in memory. Log counts only, no
  request payload dumps.
- Freeze the result as a generated CSV under
  `docs/icd-causegrp-mappings/migration-artifacts/icd11-2026-01-base-<date>/`
  so migrations can seed without a running API, matching the ICD-10 artifact
  layout.

### 4. Coding UI

- In the assessment panels, add an ECT block next to the ICD-10 controls.
  Configure `apiServerUrl` to the same-origin `/icd-api` path, `apiSecured`
  false, `language` en, `sourceApp` `DigitVA`, `autoBind` false with an explicit
  `ECT.Handler.bind(iNo)` after each HTMX swap, `chaptersFilter` limited to the
  chapters VA coding uses (exclude at least the functioning chapter, extension
  codes and traditional medicine; confirm the list with the clinical lead), and
  `enableSelectButton` on.
- On `selectedEntityFunction`, send `code`, `uri` and `foundationUri` to a
  Flask API route (`/api/v1/icd11/select` or the existing assessment submit)
  with the `X-CSRFToken` header. The server validates the entity against
  `mas_icd11_mms` and the submission's age and sex policy, then stores it.
  The browser widget never becomes the source of truth.
- Keep a server-side `/api/v1/icd11/search` with the same contract style as the
  ICD-10 search, backed by the local API, for clients that do not embed the ECT.
- Show the WHO attribution string and link to the local `/browse11` for
  browsing.

### 5. VA Bucket Assignment for ICD-11

- Expand each annex range (for example `1A60-1A9Z`) using the linearization
  order from `mas_icd11_mms`, not string comparison, so residual `.Y` and `.Z`
  codes and dotted endpoints such as `1A40.Z` resolve correctly.
- Keep an explicit override table for the irregular tokens listed in the
  reference document (for example `5C52.Y-5C52-Z`, `3A00-3A4.Z`, the
  duplicated `DB96`), each with a recorded decision.
- Report coverage: every coded leaf maps to exactly one VA bucket, is
  deliberately unmapped, or is flagged as overlapping (`PJ20-PJ2Z` appears in
  two buckets in the annex). Overlaps are a clinical decision, recorded in a
  policy doc before rollout.

### 6. Rollout Phases

1. **Spike (staging only)**: run the container, measure RAM and start-up time,
   confirm the REST paths, prove the ECT works behind the authenticated proxy,
   check egress.
2. **Catalog**: `mas_icd11_mms` migration, load task, frozen seed CSV, read-only
   admin browser panel.
3. **Coding**: ICD-11 fields on the review models, ECT in the panels, server
   validation, behind a per-project feature flag.
4. **Buckets and reporting**: range expansion, coverage report, ICD-11 columns
   in exports; an ICD-11 allowability policy under `docs/policy` is written and
   agreed before production enablement.

## Risks and Open Questions

- Memory footprint of the container is unmeasured.
- ECT 1.8 behaviour changes over 1.7 are unconfirmed; the package ships no
  TypeScript types (`index.d.ts` is a stub).
- Authenticated proxying of a browser-called API adds a moving part to the
  reverse proxy; the Flask fallback costs request throughput.
- Release upgrades (2026-01 to later) need a snapshot and re-validation
  strategy for already-coded records.
- Stem-code-only coding limits specificity for some causes; postcoordination is
  deferred, not rejected.
- Whether to require ICD-11 at all, and for which projects, is a policy decision
  for the public health lead, not an engineering default.

## Verification Approach

- Unit tests for range expansion, override handling and policy filtering.
- Load-task tests against recorded API fixtures, so CI needs no running
  container.
- Route tests for the ICD-11 select and search endpoints, including CSRF and
  authorization failures.
- Manual staging checks: container sizing, egress, ECT round trip from search
  to stored record, HTMX rebinding after panel swaps.

## References

- WHO VA cause list with ICD-10 and ICD-11 codes:
  `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md`
- ICD-10 catalog policy: `docs/policy/icd10-reference-catalog.md`
- ICD-10 coding allowability policy: `docs/policy/who-2022-icd10-coding-allowability.md`
- Migration artifacts layout: `docs/icd-causegrp-mappings/migration-artifacts/README.md`
- Follow-up task: `.tasks/who-2026-annex-icd10-icd11-review.md`
- Docker Hub image: `https://hub.docker.com/r/whoicd/icd-api`
- npm package: `https://www.npmjs.com/package/@whoicd/icd11ect`
- ICD-11 Terms of Use and License Agreement: `https://icd.who.int/en/docs/icd11-license.pdf`
