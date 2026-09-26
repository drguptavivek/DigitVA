# Handoff

## DORIS implementation (2026-09-26)

`digitva-ddv.1` implements the approved public DORIS/CoDEdit Help proof and
clinical coder/reviewer flow. The dedicated public Flask service is routed
through the same-origin ingress on local port 8052; the clinical app remains
separate. The Help proof uses six synthetic certificates, requires CSRF on
application POSTs, and stores no records. Five concurrent Process requests
completed while clinical health requests remained responsive in local load
validation. Production host routing to the ingress remains a release setting.

Projects default to masked/simple. An additive migration adds unmasked/simple
and unmasked/DORIS ICD-11 settings plus final-assessment payload columns.
Clinical DORIS edits clear processor results and the selected UCOD. A signed
Process proof binds certificate and output digests to the case and allocation;
final save verifies the proof and persists only the final certificate, DORIS
and CoDEdit outputs, and the independently selected human UCOD. Changed
certificate submission returns 409 with fresh processing and requires
reconfirmation; no row is saved on that request. Coder and reviewer results
remain separate. Final-save writes lock the submission row and the migration
enforces one active final per role, submission and non-null payload version.
The local development database had zero duplicate active keys at this
checkpoint; deployment databases need the same pre-migration check. See
`docs/policy/doris-cod-workflow.md` and
`docs/current-state/doris-cod-workflow.md`.

The final full Docker test suite on `minerva_test_pii` passed: 2,241 tests and
321 subtests, with seven existing schema-drift warnings. Browser smoke through
the ingress processed an adult synthetic certificate and rendered DORIS,
CoDEdit, rule table and diagrams. `digitva-ddv.2` tracks production hostname,
TLS cookie, deployed image and log-privacy checks. The section below records
the earlier planning checkpoint and is superseded by this implementation.

## DORIS planning review corrections (2026-09-26)

`digitva-ddv.1` remains a planning task; no DORIS application code has been
implemented. The public Help proof is now specified as plain JavaScript with
vendored ECT/Mermaid, with its normalized terminology and processing JSON
contracts frozen in phase-0 tests before UI work. The plans set a five-line
DigitVA cap, one interval per editor line, omission of unknown fetal/infant
measurements, server-verified code/URI pairs, independent processor statuses,
and confirmation on clinical final save. The public Help page and APIs are
planned for a dedicated same-origin service with CSRF on application POSTs
and capacity for five simultaneous training submissions, independent of the
main clinical Flask request threads. Query-bearing URLs must be absent from
access logs. An edit to clinical DORIS lines clears the computed result and
selected final UCOD; Save stays disabled until reprocessing and reconfirmation.
No draft or process response is saved. Final save compares the submitted
certificate with a signed token from processing and returns a reprocessed
result for reconfirmation if they differ; only final certificate, DORIS and
CoDEdit outputs, and human UCOD are persisted. Reviewer process/final routes
belong to the later clinical work. The sixth fixture's two intervals on one line need
re-baselining, and multi-issue CoDEdit encoding remains an evidence gate.
See `docs/planning/project-cod-masking-doris-plan.md`,
`docs/planning/coder-web-and-api-contracts.md` and
`docs/kb/doris-certificate-ui-contract.md`. Unrelated untracked KB archives
and the manuscript presentation were preserved.

## Proposed DORIS Help proof and unmasked COD plan (2026-09-26)

`digitva-ddv.1` is planning only. The owner requested a public, non-persisting
DORIS/CoDEdit/WHO ECT Help-page proof against the pinned local ICD API image before
project settings or VA coding workflow changes. The read-only API study found
that DORIS POST accepts one certificate object; HTTP 200 may still mean
`reject=true`; computed `code`/`uri` may be clusters; and mismatched input
code/URI can be recoded with a warning. Both GET and POST exist; the plan
chooses structured POST for the Help proof and clinical integration. The
proposed three valid
project modes, output shape, security boundaries, migration and validation
gates are in `docs/planning/project-cod-masking-doris-plan.md`, with API
knowledge in `docs/kb/doris-icd-api-and-va.md`. No application
code or migration has been started for this plan. The new Beads issue remains
open and unclaimed pending plan review.

Six invented Help certificates are prepared in `resource/doris_help_examples.json`
(adult, neonatal death, child, maternal, stillbirth, mixed tuberculosis
codes), with their local DORIS and CoDEdit observations documented in
`docs/kb/doris-icd-api-and-va.md`. They are data
for the planned Help proof, not a live page or clinical assessment records.

The owner broadened the architecture plan to the entire coder journey from
opening a form, with JSON API contracts alongside the existing HTMX
contract and React proposed for the coder web client. See
`docs/planning/coder-api-first-workflow-plan.md` and
`docs/planning/coder-web-and-api-contracts.md`. The owner clarified that
DigitVA should implement the DORIS **interaction** itself, including an
editable certificate, conditional questions and ICD-11 code search in each
condition, using WHO's web page as a behavioral reference and WHO APIs as
the terminology, CoDEdit and DORIS engines. The public Help proof must load
and edit six synthetic examples, permit a blank start, and process the
current certificate through the local ICD API. The clinical form later
reuses this contract; WHO web embedding is not a blocker. WHO's separate
vanilla-JS DORIS API sample derives a rule
table, Mermaid flow and sequence views from `tabularReport`; its parser and
generators produced nonempty diagrams for all six synthetic examples
against the pinned 2026-01 image. The Help plan now includes these views,
with safe rendering and raw-report fallback. The sample is not an embeddable
certificate form and has no declared repository license, so its source has
not been copied. A fresh WHO web tab was traced with synthetic input:
term typing sent MMS `search`, code prefix typing sent `codeinfo`, selection
made a removable chip, and pregnancy follow-ups changed with sex and
pregnancy answer. WHO's page sent `1B12.2&XA0G74` as one condition and
`1B10.Z` as another on the same line; the sixth local synthetic fixture
tests that exact structure. Its web wrapper DORIS/CoDEdit routes differ
from the direct local ICD API chosen for DigitVA. The KB records the
observed request fields and UI limits in
`docs/kb/doris-web-behavior-and-api-trace.md`; the cross-platform UI/API
contract is in `docs/kb/doris-certificate-ui-contract.md`.
No application code has been changed for this revised plan.

## WHO ICD-11 ECT production assessment integration (2026-09-26)

`digitva-0kj`: coder and reviewer ICD-11 COD fields use WHO ECT 1.8 through
an authenticated same-origin proxy to the local ICD API. The selected complete
code expression is checked against WHO codeinfo and DigitVA's local coding
policy. New ICD-11 coder/reviewer initial/final rows store nullable JSONB
provenance (code, canonical title, selected text, release, WHO URIs) via
additive migration `d9e0f1a2b3c4`; ICD-10 and historical rows stay NULL.
The locally vendored WHO ECT assets are unchanged. See
`docs/policy/icd11-ect-production.md`.
Focused combined Docker validation: 74 passed; coder/reviewer route subset:
29 passed. The final full suite on dedicated `minerva_test_ect_full` passed:
2,173 tests and 295 subtests, with seven schema comparison warnings. An
earlier run's ODK mapping assertion passed on rerun; the public ICD help route
auth allowlist was updated.

## SmartVA ICD-11 display (2026-09-26)

`digitva-p11` is implemented and locally verified. The three SmartVA Analysis views label SmartVA's original
ICD-10 codes and show WHO 10-to-11 crosswalk expressions for primary,
secondary, and tertiary causes. Missing mappings show `unavailable`; no
stored result or coding choice changes. The tertiary ICD-10 badge typo is
fixed. Focused Docker pytest: 1 passed; Ruff on the new service/test passed;
template compilation and read-only quality audit passed. This change is
committed with the concurrent ICD-11 ECT work after combined validation.

## Local WHO ICD-11 API evaluation (2026-09-26)

`digitva-6ix`: optional `icd_api_service` added to `docker-compose.yml` and
started locally at `127.0.0.1:8382`. WHO image 2.6.0 is digest-pinned;
MMS 2026-01 English and DORIS are enabled; analytics is off. `/ct`, `/browse`,
Swagger and the MMS API responded successfully, and Swagger lists the DORIS
endpoint. Current container memory was about 583 MiB. See
`docs/policy/icd11-local-api-runtime.md`. The service is not connected to the
DigitVA picker yet. The container and ECT demo changes are scoped separately
from the public browser and other shared-tree work; preserve those other edits.

`digitva-cca`: WHO ECT 1.8 assets are vendored under
`app/static/vendor/icd11ect/1.8/`, and `/help/icd-codes/search-demo` now has a
read-only WHO Coding Tool comparison with a page-scoped connection to the local
API. Browser smoke exercised `diabetic nephropathy` term search, entity
selection with code/URIs/selected text, the local DigitVA policy preview, and
the existing DigitVA search. The production COD picker and save path are not
connected to ECT. Focused Docker tests for the demo and its search API passed
in dedicated `minerva_test_ect` (14 passed); Ruff and `git diff --check` passed.

Updated 2026-09-26 (ninth pass, sixth landing plus public browser work).
Baseline `main` is **`6611a53`**, pushed to `origin/main`; migration head at
that checkpoint was **`a5f7c3d92b18`**
(chain `c4e7b1d8f2a9 → d8a1f4c7b2e6 snapshots → f2b7c9e4a1d8 diarrhoea →
fdb562cccac4 vocabulary sort_order + seed repair → a5f7c3d92b18 decisions
15-17 + stillbirth vocabulary`). Full suite at that checkpoint:
**2128 passed, 283 subtests, 0 failed**. Parts 5-6 were committed and pushed
together. The browser, mapping guidance, and vocabulary work is committed
locally as `97dabba`; the ECT/API work is in a separate local commit. Neither
commit has been pushed.

The work includes completed beads `digitva-1u5`, `digitva-oeu`,
`digitva-yds.1`, and `digitva-yds.2`. It includes migration
`b7e2a9c4d6f1_reconcile_tuberculosis_vocabulary.py`; dev is at that head. The
public `/help/icd10-codes` page reuses the admin ICD-10 pane browser in
read-only mode, with safe filtered data, selectability, sex/age and policy
details, VA mapping origin/reason, and filtered CSV. Public pane counts reflect
policy/origin filters; the age filter includes Infant, and failed searches or
malformed successful JSON responses show an error.

`digitva-yds.2` now reuses the admin ICD-11 variable-depth pane browser in
read-only mode at `/help/icd11-codes`; the old HTML and CSV URLs remain working
aliases. It retains public selectability, sex/age and policy details, mapping
origin/reason, filters, search/deep links, and filtered CSV. The hidden
`origin=digitva` alias survives pane loads, other filter changes, and search;
Clear Filters removes it. Direct WHO codes now get a plain reason in the
mapping list, browser detail, compare view, and CSV. Verification after these
fixes: focused public/service/admin tests **114 passed, 30 subtests**; Ruff and
`git diff --check` passed (the latter reports CRLF normalization warnings in
pre-existing ICD-11 reference text files); anonymous browser smoke covered the
alias, search, filter clearing, and a direct-WHO detail. The final read-only
quality audit found no remaining material findings. The full suite has not been
rerun after these changes. Preserve the pre-existing untracked ZIP/PPTX
references and the later observed `MorbidityTabulationList_en.zip` plus its
extracted folder; none are part of these commits.

## Landed 2026-09-25 (ninth pass, part 6)

* **Coding search overhaul** (`digitva-3t2`, `digitva-wqc`, `digitva-1ht`,
  closed). Migration `fdb562cccac4`: `mas_icd_search_terms.sort_order`
  (lower first, admin-editable, in the CSV export); seed rewritten to 380
  links, **every target coding-selectable** (verified against dev); +104
  inserted, **43 retired keys deactivated** (never deleted; exact
  downgrade). Behaviour:
  - vocabulary matches while typing (prefix, >= 3 chars, 10-code cap;
    "MI"/"TB" stay exact);
  - "focused" = query starts ANY title word (`gastroen` → A09,
    `myoc` → I21), not only the title start;
  - ICD boilerplate ignored for matching/ranking only (`core_title`:
    Other, unspecified, NOS, NEC, not confirmed, …); display unchanged;
  - typo fallback only when a search finds nothing (`dysentry` → A09,
    pg_trgm `<%` on the existing GIN indexes, same policy filters);
  - `_result_tier` de-duplicated into one shared helper.
  Owner vocabulary decisions: S/T injuries are never selectable, so
  injury/allergy terms fan out to external causes in `sort_order`
  (head injury → V89.2, W19, Y09, W20, X59; anaphylaxis → Y57, Y59, X23,
  X29, X59); **TB/Kochs/pulmonary TB/consumption → A16 / 1B10.Z only**
  (VA cannot know bacteriological confirmation; A15/A16/1B10.x share the
  Pulmonary tuberculosis bucket); **RTA-type terms → V89.2** (V89 buckets as
  Other transport); CCF → I50.0, heart failure → I50.9, HHD → I11.9,
  ALD → K70.9. Review findings fixed (ICD-11 `limit` contract, CSV export
  missing sort_order, docstring).
* **Help**: `/help/icd-codes` rewritten as "ICD Codes, VA Causes & Search"
  (ICD-10 + ICD-11, VA causes, how the search works, selectability).
  Help sidebar no longer pushes content ~2,600 px down below 992 px — it
  folds behind a Topics toggle (`digitva-gdc`, closed; verified 375 / 768 /
  1280 px).
* **Owner decisions 15-18** recorded in
  `docs/policy/icd10-to-icd11-transition.md` section 6 (policy first):
  15 three-character `V01`-`V89` + `Y85` not selectable (WHO footnote f
  splits road traffic only at the 4th character); 16 saved `V10`-`V82` and
  `V87` re-bucket to Road traffic (WHO's ICD-10 "assume traffic" rule;
  nobody re-coded); 17 ICD-11 `PA22`-`PA29`, `PA2E`, `PA2F`, `PA2Y`, `PA2Z` →
  Road traffic (supersedes decision 3 for those); 18 ICD-11 `KD3B`/`KD3B.Z`
  not selectable, "stillbirth" → `KD3B.1` fresh first; ICD-10 `P95` stays
  one code (not differentiable; no invented codes). Also recorded in
  `docs/policy/who-2022-icd10-coding-allowability.md`.

### Landed later in part 6 (uncommitted, verified on dev)

* **ICD-11 mapping-state page** (`digitva-x67`, closed):
  `/help/va-code-mappings/unmapped` gained Origin and Policy-review filters
  (CSV too; filtered CSV streams, file cache only for unfiltered);
  **block-aligned paging** — a block is never split across pages (checked:
  18,505 codes → 98 pages, 0 split blocks; an 860-code block gets its own
  page); one click on a chapter/block expander opens or closes its whole
  subtree (opt-in `expand_subtree` in `tree_table.js`; main session fixed
  a Wunderbaum `visit()` misuse that left the clicked chapter collapsed).
  The flat mapping list keeps plain paging (not in chapter/block order).
* **Coding-search demo** (`digitva-zm1`, closed):
  `/help/icd-codes/search-demo`, linked from `/help/icd-codes` — ICD-10 /
  ICD-11, age group, sex, same two columns, real search services (ICD-10
  refactored to `search_icd10_2019_2_coding_choices_for_policy`; ICD-11
  takes explicit `age_group`/`sex`), never recorded in telemetry.
  Browser-verified (head injury, dysentry, eclampsia by sex, preterm by
  age, ICD-11 TB).
* **Mapping origins** (`digitva-oeu`, closed): canonical WHO / overlap /
  outside-WHO / differs / not-a-cause / unmapped badges with plain reasons;
  expert-review tooltips; legacy `?origin=digitva` alias; legend included on
  all three mapping pages; raw audit note retained only in CSV; BA5x reasons
  filled; regression test keeps uncovered ICD-11 codes with no crosswalk
  unselectable. User-facing copy says "expert review"; stored notes, CSVs and
  policy docs retain "Owner decision N" as the audit trail.
* **Tuberculosis vocabulary** (`digitva-1u5`, closed): "tuberculosis" now
  promotes A16 / 1B10.Z, based on VA's inability to know bacteriological
  confirmation and the shared pulmonary-tuberculosis bucket. Reconcile
  migration `b7e2a9c4d6f1` chains from `a5f7c3d92b18`, inserts absent exact
  keys only, captures inserted IDs, and downgrades exactly.

* **Decisions 15-18 implemented** (`digitva-g2n`, closed): migration
  `a5f7c3d92b18` — 88 three-character `V01`-`V89`/`Y85` unselectable
  (saving `V89` is refused, `V89.2` accepted); 74 ICD-10 `V10`-`V82`/`V87`
  and 12 ICD-11 `PA2x` rows → Road traffic in `WHO_2022_VA_2026` (only
  where still at the workbook value); stillbirth vocabulary (fresh
  `KD3B.1` first) and the bare `KD3B` link retired; exact downgrade.
  Source files carry the decisions (ICD-10 overrides CSV, ICD-11 owner
  decisions CSV, regenerated native mappings, ICD-11 policy draft rule
  `decision_18_not_selectable`). `KD3B`/`KD3B.Z` unselectable on the
  **dev** ICD-11 draft only (via `flask icd11 policy-import`; ships when
  the owner approves the draft, `digitva-dus.3`). The snapshot MV joins
  mappings live — run `flask analytics refresh-submission-mv` after
  upgrading. **Dev: Road traffic final CODs 15 → 127, Other transport
  259 → 147.**

### Next (in order)

1. **`digitva-yds.3`**: public read-only COD bucket scheme browsers (one bead at
   a time; same anonymous/read-only access contract).
2. **`digitva-e5j`**: explain empty search results caused by age/sex policy
   ("1 code matches but is not selectable for an infant female: P95 (neonate
   only)") in the demo and the coding picker.
3. Telemetry review; candidate: rank focused matches by final-COD
   frequency ("myoc" lists I41 above I21).
4. Everything under "Approved, not started" below.

Lessons from part 6: dev serves the working tree, so a writer's model
change breaks dev pages until its migration runs (the vocabulary panel
500'd for ~30 min) — prefer writers finishing with the dev upgrade, or an
isolated worktree. Code-writers refuse scope relayed mid-task (they treat
orchestrator messages as possible injection); put the complete scope in
the initial prompt and restart a fresh writer rather than relaying.
Give parallel writers separate test databases (`minerva_test_help`,
`minerva_test_demo`, `minerva_test_main` now exist). Browser checks: the
pane's screenshot frame is not the page's coordinate frame, so drive
Wunderbaum by dispatching events on elements, not by pixel clicks.

## Landed 2026-09-25 (ninth pass, part 5)

* **Reset-safety snapshot** (`digitva-tet`, closed). New table
  `va_cod_bucket_scheme_snapshots` (whole-scheme JSON payload, reason
  `reset_scheme | reset_age_band | cli_import`, created_by). The reset
  route (both scopes) snapshots before anything is replaced, same
  transaction; a failed snapshot refuses the reset (400, nothing
  destroyed). `flask cod-buckets import-*` snapshots an existing scheme
  first (committed on its own). Reset modal lists the last 10 and
  auto-downloads the new one; restore = existing Import JSON. No prune yet.
  `reset_cod_bucket_scheme_age_band_to_source` now returns
  `(scheme, snapshot_id)`. The three label renames were cancelled.
* **Coding picker: two columns** (`digitva-blu`, closed). "Focused
  matches" left, "Term matches" right (CSS grid, one column when narrow);
  the "Show more" toggle is gone. It had a real bug: Select2 4.1 puts
  `select2:selecting` data under `params.args`, so the toggle was saved as
  the COD value and the expanded tail (e.g. I21 for "myoc") was
  unreachable. Live-verified on a dev coder session — this closes the
  picker visual-check gap from part 4.
* **Vocabulary hits no longer push title matches out**: the 30 cap applies
  to the lexical list only; vocabulary hits ride on top (both ICD-10 and
  ICD-11 coding search).
* **Diarrhoea vocabulary** (found through telemetry: every "diarrhoea"
  query returned 0, yet A09 is 141 of 8,547 dev final CODs — its title
  says "gastroenteritis"). Reconcile migration `f2b7c9e4a1d8`: diarrhoea,
  acute diarrhoea, (acute) diarrhoeal disease, acute gastroenteritis,
  loose motions, dysentery → A09 / 1A40.Z; bacillary dysentery → A03 /
  1A02. ME05.1 (symptom, maps to "unknown") deliberately not used; "AGE"
  left out (its key "age" would hijack plain "age" queries). Seed: 319
  links.

### Next (after part 5)

1. Let telemetry accumulate, then review the export (unchanged). Early
   signal from dev: bare "cancer" returns 0 — candidate vocabulary row.
2. Rank "focused" by how often a code is a final COD (e.g. "myoc" puts
   I41 Myocarditis above I21 AMI) — not filed; ask the owner.
3. Everything under "Approved, not started" below, minus item 1 (done).

## Landed 2026-09-25 (ninth pass, part 4)

**Dev smoke 2026-09-25 (live app, real death, admin session):** the
vocabulary is live on dev through the real HTTP path — `MI` → `MI — I21
Acute myocardial infarction` (30 results), `Kochs` → A15, `assault` →
Y09, `CVA` → I64, `heart attack` → I21, all rank-1 flagged
`vocabulary: true` / tier `focused`; the lexical control (`meningitis`)
unchanged. Admin panel renders 303 links with search/export/add/edit/
deactivate. Dev upgraded to `c4e7b1d8f2a9`; testadmin's dev password was
reset to the documented `Admin@123`; a one-allocation smoke grant was
created and deactivated afterwards. **Owner decisions:** the three WHO
bucket-label renames in `digitva-tet` are CANCELLED (US/UK spelling
immaterial, "what matters is code"; dev already matches the manual's
annex table — the manual's definitions section disagrees with its own
annex); tet proceeds with the reset-safety snapshot only.


* **Coding-search telemetry + two-stage picker + dual-spelling/hyphen
  fold** (`digitva-zpe.3`, closed): migration head **`c4e7b1d8f2a9`**
  (chain `e9d4b6f8a3c2 → b8f2d6a9c4e1 telemetry table → c4e7b1d8f2a9 trgm
  indexes`). New dependency **`localspelling==0.94`** (images rebuilt).
  Full suite: **2048 passed, 283 subtests, 0 failed**.
  - **Telemetry**: `cod_search_telemetry` (surface, query ≤128, count,
    zero-results, vocabulary-hit, latency, role; no user id/va_sid);
    every search request echoed `X-Search-Id`; chosen code + rank recorded
    on the COD save (coder AND reviewer paths); 90-day celery-beat prune;
    admin CSV export. Telemetry failure can never break or slow a search.
    Live on dev: 28 rows captured during the smoke.
  - **Two-stage picker**: Select2 grouping on the `tier` field —
    "Focused matches" then collapsed "Show more results"; vocabulary hits
    always focused (including promoted lexical rows); graceful degradation
    to the flat list. JS covered by template tests; a visual check with a
    real coder session is the one open verification gap (admin cannot
    open the coder view).
  - **Dual-spelling + hyphen fold** (owner-directed): `localspelling`
    (MIT, 34/54 of the owner's linguistic taxonomy) + a 22-entry medical
    supplement; query variants OR-ed into ILIKE with a hyphen/space-
    insensitive `translate` arm on BOTH sides ("cat scratch" reaches
    "Cat-scratch" and "catscratch" reaches both); vocabulary lookups
    bridge spellings and hyphens without rewriting stored keys; one
    helper everywhere (endpoints, tier, vocabulary, admin search).
    **The database is never modified for search** — invariant in policy.
    Wildcard escaping fixed so `1_00` no longer matches `1A00` (a real
    bug the suite caught). Library survey trail (rejected: snowball,
    pyspellchecker, spylls, eng with its edema→"edoema" corruption,
    PyMedTermino, UMLS; carded for Phase B: MedSpaCy/scispaCy) is in
    `docs/policy/icd-coding-search-vocabulary.md` and the design doc.
  - **trgm GIN indexes** on code+title of both catalogues (pg_trgm was
    already installed; the translate arm stays unindexed by design).
  - Dev live-verified: `anaemia`/`anemia` identical results, `MI` top-1
    flagged, `self harm` → X70 focused, `1_00` empty, X-Search-Id on
    every request. `cat scratch` on dev returns 0 because A28.1 is
    WHO-policy non-selectable there — correct behavior, not a gap.

### Next (after part 4)

1. **Let telemetry accumulate** — a few weeks of real coder queries in
   `cod_search_telemetry`, then review the CSV export
   (`/admin/api/coding-search-telemetry/export.csv`) for: shorthand the
   vocabulary misses (add via admin panel, `source='telemetry'`),
   zero-result queries (fold/spelling gaps), and chosen-code ranks
   (picker quality). This data decides Phase B (the 63-cause semantic
   mode) per the gates in `docs/planning/icd-semantic-search.md`.
2. **`digitva-tet` (P1, top of the approved queue)**: reset-safety
   snapshot only — force `export_cod_bucket_scheme_json()` into a new
   snapshot table before any reset-from-source, refuse the reset if the
   snapshot fails, auto-download in the UI, restore via existing JSON
   import. Renames cancelled (owner, 2026-09-25).
3. Visual picker check with a real coder session (the one open
   verification gap; JS is template-tested).


## Landed 2026-09-25 (ninth pass, part 3)

* **COD search vocabulary addendum** (owner-directed, same day): +54 seed
  links → **303 total** (`resource/icd_search_vocabulary_seed.csv`). New:
  cor pulmonale (I27.9 / BB01.5 — ICD-11 has a literal Cor pulmonale code),
  uremia/uraemia, head injury / head trauma (S06.9 / NA07), road traffic
  injury, suicide / self-harm (X70 / PC71 — anchored to hanging, the
  dominant method in the used CODs; ICD-10 has no suicide-NOS code),
  assault (Y09 / **PF2Z "Assault, unspecified"**, added after the owner
  flagged the missing counterpart), drowning (W74 / PA9Z), accident,
  cancer shorthand (kidney C64/2C90, bladder C67/2C94, cervical
  C53/2C77, gall bladder C23/2C13, blood C95/2B33.4, uterine/womb
  C55/2C78, prostate C61/2C82), drug reaction (T88.7/NF09), allergic
  reaction (T78.4/4A8Z), anaphylaxis (T78.2/4A84), disseminated/miliary
  TB (A19/1B13). "miliary tuberculosis" itself is NOT seeded — A19's own
  title contains it, so lexical search already finds it (policy: seed
  only what lexical misses). All anchors title-grounded in both
  catalogues.
  - Delivered via **reconcile migration `e9d4b6f8a3c2`**: inserts seed
    rows whose (term_normalized, classification, icd_code) key is absent,
    never touches existing rows (admin edits and deactivations survive),
    captures inserted ids in a `_mig_` table so the downgrade removes
    exactly the insertions. Migration test covers re-add-after-delete,
    admin-edit survival, idempotence and the downgrade.
  - Grounding sources: WHO VA cause list ranges for the external causes
    (drowning W65-W74, self-harm X60-X84, assault X85-Y09), WHO ICD-11
    Mortality Tabulation List and catalogue titles for counterparts. The
    WHO VA definitions themselves surface after selection through the
    floating VA-definitions panel (all VAs-12.x have definitions).


## Landed 2026-09-25 (ninth pass, part 2)

* **COD search vocabulary** (`digitva-zpe.1`, closed): `mas_icd_search_terms`
  — one flattened table, one row per term-code link, with a source
  vocabulary (`seed_used_cod` | `who_inclusion` | `admin`, later
  `telemetry`). The ICD-10 and ICD-11 coding-search endpoints expand
  queries through it (exact normalized match; targets resolved through the
  endpoint's own policy filters, so the vocabulary never bypasses coding
  policy), prepending hits flagged `vocabulary: true` and display
  `term — code title`. Results carry an inert `tier` field (`focused` =
  vocabulary/exact-code/title-prefix; `expanded` = the rest) for the
  upcoming two-stage picker. Migration `c5a8d2e7f1b4` creates the table and
  seeds it only when empty from `resource/icd_search_vocabulary_seed.csv`.
  - Seed: 249 links — 216 clinician shorthand curated from the codes
    actually used as final CODs (dev: 7,879 final CODs; ~50 codes cover
    73%; `MI`→I21/BA41, `CVA`→I64/8B20, `CCF`→I50/BD10, `Kochs`→A15+A16,
    `madhumeh`→E14, `RTA`→V89) plus 33 WHO ICD-10 inclusion terms mined
    from `icd102019en.xml` (ClaML). ICD-11 counterparts are title-grounded
    in the frozen 2026-01 MMS export; the WHO 11To10 crosswalk was
    discarded (it mis-derived 7 of 38, e.g. I50→BD12 "High output
    syndromes"). V89/W19/J22 ship ICD-10-only.
  - Admin panel `COD Search Vocabulary` (list/search/paging, add/edit with
    a soft absent-code warning, deactivate/reactivate, no delete, CSV
    export; admin-only + CSRF). Policy:
    `docs/policy/icd-coding-search-vocabulary.md`.
  - One-time ICD-11 definitions freeze from the local `whoicd/icd-api`
    image: `resource/icd11_definitions_2026_01.json` (18,505 in-scope codes
    → 13,131 entities → 6,637 WHO definitions; not imported by the app;
    superset frozen, subset to be embedded — Phase B decision).
  - Bucket ladder recorded in `docs/planning/icd-semantic-search.md`:
    vocabulary table → 63 VA causes → WHO ICD-11 Mortality Tabulation List
    (158 buckets, `docs/kb/MortalityTabulationList_en/`, frozen copy under
    migration-artifacts). Owner invariant: **every path terminates at an
    ICD code; buckets are navigation and post-hoc reporting only.**
  - Tests: 43 new (service 15, endpoint wiring incl. tier 13, admin routes
    14, migration 1). Full suite: see below. Verification: builder +
    main-session review of the wiring (policy clause shared, cap
    preserved); schema-drift and no-app-imports guard tests pass; ruff
    clean; single head `c5a8d2e7f1b4`.

Older ninth-pass header: migration head `a3c9e1f7b2d4` (no migration that
day); full suite then 1950 passed, 179 subtests, 0 failed.

## Landed 2026-09-25 (ninth pass)

* **COD bucket API scheme default** (`digitva-tcv`, closed): the report page
  and `/api/v1/cod-buckets/aggregates` + `/export.csv` now share one
  resolver, `default_reporting_scheme_code()` in
  `app/services/cod_bucket_mapping_service.py` (WHO_2022_VA_2026 when
  active, else first active scheme, else a 400 "no active scheme"). The API
  no longer silently falls back to the ICD-10-only `WHO_2022_VA`, which
  reported every ICD-11-coded death as unmatched. No migration.
* **ICD-11 title edits refresh the public mapping cache** (`digitva-yog`,
  closed): `_cache_key` in `app/services/va_code_mapping_public_service.py`
  now includes the release's `mas_icd11_mms` row count and latest
  `updated_at`, mirroring `get_icd11_catalogue`. A title change alone
  reaches the help page, compare view and unmapped CSVs on the next load.
* **`digitva-zpe` design + quality check done, browser ML parked** (bead
  open, phase 0 next): `docs/planning/icd-semantic-search.md` and
  `tooling/icd-semantic-search/quality_check.py`. Measured on the real
  catalogues (12,475 ICD-10 + 18,505 ICD-11 titles) with the exact int8
  ONNX models the browser would run, 30 grounded clinical phrases:
  MiniLM-L6 hit@10 11/30 (ICD-10) / 4/27 (ICD-11); bge-small + retrieval
  prefix 15/30 / 7/27. Owner constraints recorded: **browser memory ceiling
  2 GB, must not burden client machines, measure real use before building.**
  Footprint arithmetic (~35-60 MB lazy payload) sits far under the ceiling —
  retrieval quality is what fails, so ML is parked. Next: phase 0 telemetry
  on the existing coding-search endpoints (query terms, zero-result and
  no-selection rates, chosen-code rank); table namespace is an open owner
  question. Re-open gates are in the doc.

### `digitva-zpe` follow-up (same day): how to improve retrieval quality

**Work done.** `quality_check.py` grew into a configuration ladder and
every rung was measured on the same 30 grounded phrases (details and the
full table in `docs/planning/icd-semantic-search.md`): lexical baselines
(whole-phrase substring = today's endpoints; per-token overlap), dense
search over the 31k titles (MiniLM / bge-small / bge-base, retrieval
prefix, block-chapter document enrichment), reciprocal-rank fusion, and a
new **causes mode** that embeds the 63 VA causes
(`resource/who_2022_va_cause_list_icd10_icd11.csv`) with their WHO
definitions (`resource/va_cause_definitions_who_2022.json`) and expands a
chosen cause to its mapped codes.

**Results (top-5/top-10, MRR).** Today's substring search scores **0/30
and 0/27** on narrative queries — the problem is real. Token overlap
0-2/27. Dense over titles caps at ~50% hit@10 (bge-small 15/30, 7/27);
**bigger models do not help** (bge-base 13/30, 7/27), context enrichment
is a wash, naive RRF fusion actively hurts (5/30). **The 63-cause
reformation roughly triples quality: top-3 20-21/30 and 18-19/27, top-5
22/30 and 21/27, MRR 0.57-0.61 — with the smallest model (MiniLM-L6,
23 MB) and a ~0.1 MB vector file.** The WHO definitions carry most of the
gain (title-only drops to MRR 0.45-0.46). Two ICD-10 "misses" are
coverage artifacts, not retrieval: VAs-12.01's ICD-10 cell is empty
(footnote f holds the ranges) and no cause token list covers the ICD-11
preterm codes; rabies still ranks ~52 and needs a look.

**Next steps.**
1. Phase 0 telemetry on the existing coding-search endpoints (unchanged
   decision): confirm what clinicians type and collect their shorthand —
   the phrase corpus must become telemetry-derived before any build.
2. **Owner reframed the scope (2026-09-25): the search serves clinicians
   typing diagnoses, not layperson narratives.** Measured on a 33-query
   doctor-diagnosis batch: full names and synonyms work broadly top-1/2
   (AMI, heart attack, cardiac arrest, CCF full form, stroke, CKD, renal
   failure, cirrhosis, HCC, CA stomach, COPD, septicemia, PTB, diabetes,
   cerebral malaria, dengue, RTA); the only failures are doctor
   shorthand/eponyms — MI, CVA, CCF, cor pulmonale, Kochs disease,
   uremia, head injury. **New Phase A candidate: a server-side doctor-
   shorthand expansion table feeding the existing lexical endpoints**
   (MI → "myocardial infarction" → ILIKE) — zero client cost, no CSP
   change, no download; one table row fixes each failure. The browser-ML
   63-cause mode becomes Phase B for free-form diagnosis prose. Typos
   survive the semantic path, so fuzzy matching only matters lexically.
3. If telemetry shows free-form prose beyond the table: prototype the
   **two-stage causes shape** (rank 63 causes client-side with
   definitions → pick the code within the cause's mapped codes via the
   existing lexical search). Payload ~23 MB lazy, far under the 2 GB
   ceiling. Re-open gates are in the design doc.
4. Fix the coverage table regardless (annex + footnote f ranges), since
   any cause-based UI needs it.
5. Optional quality levers if the prototype falls short: fine-tune the
   small encoder on (phrase → cause) pairs built from the definitions,
   or cross-encoder re-rank of the top-5 causes.
6. Layman synonyms (measured while scope was still layman-facing, same
   mechanism): "heart attack" → Acute cardiac disease [I20-I26],
   "brain attack" / "brain stroke" / "paralysis" → Stroke, "kidney
   failure" → Renal failure, "sugar disease" → Diabetes, "TB of the
   lungs" → Pulmonary TB — all top-1 natively. True idioms ("fits",
   "falling sickness", "dog bite madness", "water in the lungs",
   "yellow eyes and dark urine") miss and are exactly what the bounded
   synonym/shorthand vocabulary is for — one curated, reviewable list
   per cause, maintained in the VA-definitions admin panel, populated
   from telemetry.

Older eighth-pass header (was stale, kept as history): migration head
`fba41e2f1f9d`; chain: `a4c7e2f9b1d6` structure mode → `62a637f5c38a`
ICD-11 bucket columns → `6c11b620f48f` ICD-11 bucket seed + Fresh
stillbirth → `fba41e2f1f9d` VA cause definitions. New dependency `nh3`
(images rebuilt).

## DigitVA V3

Owner naming (2026-09-22): **V1** = initial work before Feb 2026, **V2** =
Mar-Sep 2026, **V3** = Oct 2026 onwards, when organizations, web forms and
ICD-11 go live. Umbrella epic `digitva-dus`.

## Landed 2026-09-25

Commits `9232e76`..HEAD. Migration head **`a3c9e1f7b2d4`**; dev is there.
Chain: `fba41e2f1f9d → dc762caa67dd → fad35e5c4b79 → d1a6e3b7c2f4 →
e7b2c9d4a1f3 → 33dea3ea3303 → a3c9e1f7b2d4`. Full suite: 1928 passed, 176
subtests, 0 failed.

* **Owner ICD decisions applied** (`digitva-712.4`, `712.5`):
  - WHO_2022_VA_2026 has 18,505 ICD-11 rows and 0 unmapped.
  - ICD-10 decisions 10/11/12 are in.
  - The decisions live in
    `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_icd11_owner_decisions.csv`
    (read by the generator) and in
    `.../who-2022-va-icd-cod-2026-revision/WHO_2022_VA_2026_owner_decisions_overrides.csv`
    (read by import and admin reset).
* **ICD-11 deaths in reports** (`digitva-dus.1`): the snapshot MV, the export
  and the COD bucket report page bucket each death by its own
  classification, with provenance, and default to WHO_2022_VA_2026.
* **Project ICD classification** (`digitva-dus.2`):
  - icd10 / icd11 / selectable on `va_project_master`; the per-form column
    is deprecated and unread.
  - ICD-11 coding search.
  - A per-death switch on the coding screens, enforced server-side.
* **ICD-10 Q00-Q99 all ages** (owner decision 14; this is global).
* **ICD-11 selectable draft** (`digitva-dus.3`, still open): 16,204 of
  35,664 categories selectable. **Imported into dev only**, all
  `unreviewed`. Next: the owner reviews it in `/admin/panels/icd11-browser`,
  then a data migration ships it. Rollback steps are in
  `docs/policy/who-2022-icd11-coding-allowability.md`.

* **Public ICD compare and unmapped views** (`digitva-xud`, closed), no
  migration:
  - `/help/va-code-mappings/compare?va_code=`: ICD-10 hierarchy left, ICD-11
    right, for one VA cause.
  - `/help/va-code-mappings/unmapped` (+ `.csv`): all 18,505 in-scope ICD-11
    codes with current state, filter all / selectable / non-selectable,
    search. It lists 0 unmapped today; the 17,159 codes with no VA cause are
    chapter X extension codes, left out by the generator on purpose.
  - Built on vendored Wunderbaum through `components/tree_table.html`,
    `static/js/tree_table.js` and `static/css/tree_table.css`. The Units
    panel can adopt the wrapper later; it would need action buttons, the
    name filter and expansion persistence added (no drag-and-drop needed).
  - The unfiltered CSV variants are cached on disk in `APP_DATA/public_csv/`
    (atomic write, name keyed on the data version, live streaming when
    searching or when the folder is unwritable).
  - Full suite: 1947 passed, 179 subtests, 0 failed.
  - Fixed 2026-09-25 (`digitva-yog`): an ICD-11 title change alone now
    refreshes the mapping-row cache (the ICD-11 count and latest
    `updated_at` are part of `_cache_key`).

Next stage for `digitva-zpe` (designed 2026-09-25, browser ML parked — see
the ninth-pass section): phase 0 telemetry on the existing coding-search
endpoints, then the re-open gates in
`docs/planning/icd-semantic-search.md`. WHO's ICD API/ECT plan is
complementary and its memory use is unmeasured.

Open: `digitva-712.6` (12 specific-vs-specific disagreements for the owner
  to review). The test DBs created for this work were dropped 2026-09-25.

## Landed 2026-09-24

* **ICD-10 to ICD-11 transition record** (`digitva-712.2`):
  `docs/policy/icd10-to-icd11-transition.md`. It covers the method (native
  ICD-11 buckets; the crosswalk is only a cross-check), why the crosswalk was
  rejected (it loses sepsis, road traffic and fresh stillbirth), a
  measurement of the ICD-10 to ICD-11 direction, every ICD-10 and ICD-11
  override, the gaps found, and **13 open owner decisions** (section 6).
* **Public mapping page** (`digitva-712.3`): `/help/va-code-mappings` and a
  `.csv` download. Anonymous, GET only, 60 requests/min. Each
  WHO_2022_VA_2026 row gets an origin, derived at read time against the
  annex: WHO / WHO resolved by DigitVA rule / DigitVA decision. Service:
  `app/services/va_code_mapping_public_service.py`; annex copies in
  `resource/`, kept in step by a test. The footnote f reading was confirmed by
  the owner (decision 13a).
* **All 13 transition decisions made by the owner** (2026-09-24), recorded
  in section 6 of the transition record. They are **decided, not yet
  applied**. Next work, in order:
  - `digitva-712.4` (P1): ICD-11 decisions, via a decision file the
    generator reads, then regenerate and ship a migration.
  - `digitva-712.5` (P1): ICD-10 changes. `A80`-`A89` → Meningitis/
    encephalitis; 65 boarding codes → Road traffic.
  - `digitva-dus.1` (P1): ICD-11 deaths in bucket reports.
  - `digitva-dus.2` (P2): project-level ICD classification.
  - `digitva-712.6` (P2): 12 specific-vs-specific disagreements for the
    owner to review.

  The crosswalk method is withdrawn and will not be built.

## Landed this pass (2026-09-21/22)

* **DigitVA npj Digital Medicine manuscript draft** (`digitva-bsp`): generated
  `docs/manuscript/DigitVA_NPJ_Digital_Medicine_Manuscript.docx` from
  `scripts/build_digitva_npj_manuscript.py`. It describes Phase 1 UNSW and
  Phase 2 ICMR, the batch-to-real-time evolution, architecture, security,
  MINErVA/SRS lineage, CCVA-supported single PCVA, health-system and ICD-11
  plans, additional form profiles and bounded LLM assistance. Database snapshot
  (2026-09-22): 7,917 submissions, 7,877 active final-coded records, 82 distinct
  final-assessment authors and 11 sites. The DOCX contains five live Zotero
  citation fields and one live bibliography field; Benara et al. remains marked
  for Zotero import/linking. Code availability records the public MIT-licensed
  upstream at `https://github.com/drguptavivek/DigitVA`. Word-opening repair
  (`digitva-9og`, 2026-09-22): Zotero complex-field markers are now correctly
  wrapped in Word runs; validation, nine-page rendering and an application-level
  Microsoft Word open-and-close test all pass.
* **DigitVA manuscript diagrams** (`digitva-7w7`): two-slide editable
  PptxGenJS deck at `docs/manuscript/DigitVA_Architecture_and_Workflow.pptx`
  with a platform architecture/concept diagram and a death-notification-to-
  mortality-intelligence flowchart. Regenerator:
  `scripts/build_digitva_diagrams.js`; 1600x900 PNG exports are under
  `docs/manuscript/digitva_diagram_images/`. Slide tests report no overflow.
* **Project structure mode** (sites | organization), organization writes
  refused for sites projects, automatic site `Sites_in_project_<id>` (`O###`),
  `flask org ensure-site`.
* **Organization panel rebuilt**: numbered workflow tabs, Wunderbaum tree-grid
  (vendored 0.14.1) with drag-and-drop re-parenting, unplaced units + "Map
  parents" modal, cadres per level (sub-tabs), Workers tab with side-panel
  editor, worker code optional (`W#####`), CSV import of one sheet, coding
  scope box, in-page confirmations.
* **Projects panel**: create/edit on its own view, readiness hover popover.
* **Project Setup home phase 1** (`digitva-r1p`): one page per project,
  Overview (readiness with fix links) + Basics (the shared project form).
* **ICD-11 browser** at parity with ICD-10: editable policy, JSON/XLSX
  import/export, column panes with breadcrumb.
* **ICD-11 COD buckets** (`digitva-712`): `icd_classification` on mappings,
  `icd11_method` on schemes; WHO_2022_VA_2026 native ICD-11 buckets generated
  from WHO's cause list (more specific wins, per-code splits), seeded by
  migration from `resource/who_2022_va_2026_icd11_native_mappings.csv`;
  Fresh stillbirth bucket added (KD3B.1). Review report:
  `docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd11-native-2026-09-21/`.
  Policy draft: `docs/policy/icd11-cod-bucket-schemes.md`.
* **VA cause definitions** (`digitva-oyq`): `mas_va_cause_definitions` (63
  causes, groups and VAs-98 excluded), admin panel with read-only view + Quill
  editor (shared `rich_text_editor.js`, server `sanitize_rich_text` via nh3),
  coder "VA Definitions" button with filter, help page, and a floating
  definition panel that auto-shows for the selected ICD code
  (`/api/v1/va-definitions/for-icd`).
* COD bucket scheme cards fit laptop screens.

## Waiting on the owner

1. ICD-11 buckets review (`icd11_review.csv`): confirm PJ20-PJ2Z → Assault;
   (PA20-PA2Z decided 2026-09-25, decision 17); review 916 crosswalk
   disagreements; decide the WHO range errors (`5C52.Y-5C52-Z`,
   `3A00-3A4.Z`, three stale endpoints); whether any of the 2,351 uncovered
   codes need buckets.
2. VAs-99 has an empty definition in the source: keep or drop.
3. VAs-09.99 "Other and unspecified maternal cause" has no WHO definition:
   write one in the VA Definitions panel or leave empty.

## Approved, not started (owner said yes 2026-09-21/22)

1. `digitva-tet` (P1): snapshot a scheme's JSON export before
   reset-from-source (new snapshot table, reset refused if the snapshot fails,
   UI downloads it) **and** a data migration renaming three bucket labels in
   both WHO schemes to the WHO manual titles (VAs-01.04 Diarrhoeal diseases,
   VAs-01.13 COVID-19, VAs-12.07 ...noxious substances). Codes untouched.
2. Crosswalk override list for ICD-11 → ICD-10 misses, sepsis first (draft for
   owner review).
3. ICD-11 selectable/sex/age policy draft from the WHO annex for owner review
   (all 37,052 rows are `unreviewed`).
4. Retire the per-form ICD setting (Project Forms) in favour of a project-level
   ICD classification: icd10 | icd11 | selectable.
5. Refuse removing a cadre from a level while workers of that cadre sit there;
   refuse new workers with a deactivated cadre (server-side).
6. HP2026 (dev): MO was removed from Community Health Centre unintentionally —
   restore it (Code VA).
7. Server check: web intake must refuse a submission against an unplaced unit
   (today only the picker hides it).
8. Project Setup home phase 2 (Structure + Coding incl. project coding gate).
9. Replace native `confirm()` on the six remaining admin screens (sync
   dashboard, project forms, field mapping categories, both translation
   screens, reviewer dashboard).

## Epics filed this pass

* `digitva-sn1` (P1): passkeys/TOTP. Two-step login: username, then passkey if
  registered else password; admin and data_manager without a passkey must use
  TOTP; coders may register passkeys.
* `digitva-ddv`: study and integrate WHO's ICD-11 Coding Tool (mortality rules)
  into COD assessment — substantial.
* `digitva-1eq`: more ML-based VA coding frameworks besides SmartVA.
* `digitva-dus`: DigitVA V3 umbrella.

## Known caveats

* "Reset from source" on WHO_2022_VA_2026 drops the Fresh stillbirth node and
  all ICD-11 rows (the source workbook predates them) — `digitva-tet` adds the
  safety snapshot.
* The floating VA definition panel and the Quill save round-trip were not
  exercised on a live coding page with a real allocation.
* `tests/test_admin_api.py::AdminApiTests::test_odk_site_mappings` failed
  once in a full-suite run (1,850 passed, 1 failed) and passed alone, in its
  file, and in a second full run: order-dependent leftover data, not yet traced.
* Test databases created before this pass keep old table layouts
  (`create_all` never alters); drop `mas_va_cause_definitions` there if tests
  complain.

### English alongside the translation (`digitva-mxn`, closed)

Owner decided 2026-09-21, recorded in `docs/policy/va-web-form-options.md`
("English alongside the translation") and as an amendment to "Approval before
activation" in `va-form-project-configuration.md`:

* A non-English web form shows the English under every question label, hint
  and choice label (`show-english` attribute on the web component, rendered
  through `RichText`, `lang="en"`). "Show English" toggle beside the language
  picker, **on by default**, remembered per browser.
* **The six paused locales are selectable again, but only with English forced
  on.** "Servable" is now `is_active OR lifecycle_state='in_review'`
  (`SERVABLE_LOCALE`, `app/services/web_form_instruments.py`); they stay
  `in_review` and inactive, the CHECK constraint is untouched, `draft` is never
  served. The picker labels them "(under review)"; the toggle is locked on.
  Re-approval still needs a native speaker -- this did not approve anything.
* Verified in a browser on ZZD001: Hindi shows `(Id100010)` directly over the
  English `(Id10010)`, which is the cross-check this restores.
* Fixed in passing: a resumed non-English draft opened with the picker saying
  "English" (picker built before the locale attribute was set; pre-existing).

**Correction to earlier handoffs:** "vendored JS 28 passed" is the
`tooling/who-va-2022` node suite. The `vendor/who-va-2022` vitest suite has
**351 failures** in `question-by-question.test.ts`, identical at `bdf2e4e`:
`digitva-19l`.

### Next

1. `digitva-fb5` -- native speakers; corrections into the workbooks,
   republished. Unchanged: human-gated.
2. `digitva-8go.1` -- the 427 untranslated constraint messages and guidance.
3. `digitva-19l` -- the vitest failures.

---

Updated 2026-09-21 (fourth pass). `origin/main` is at `4e2a8d1`, tree clean.
Full suite **1,729 passed**, `PYTEST_EXIT=0`; vendored JS 28 passed. Dev is at
migration head **`d5b71c3e9a84`** (two data migrations this pass, below).

**Six of thirteen locales are now paused.** `bn, hi, kha, kn, mr, or` are
`in_review` and inactive; `ar, es, fr, ml, pt, sw, ta` stay approved and live.
This is deliberate, not a regression -- read the next section before
re-activating anything.

### Translation audit (`digitva-fb5`, P1, open)

Every deployed ODK workbook packs the English and its translation into ONE cell,
so each translation can be judged against the English it claims to render.
Twelve audits did that across all ten workbooks. Findings:

* `docs/current-state/translation-semantic-defects.md` -- **34 wrong-wording
  defects**: code, English, current translation, what it actually says, and
  **suggested corrections**, most sourced from the same workbook's own correct
  usage. Four are marked *needs a speaker* rather than guessed.
* `docs/current-state/translation-label-code-mismatches.md` (+ `.csv`) -- 68
  labels showing the wrong question code. Mostly cosmetic.

Worst: Hindi `Id10305` inverts "pregnant *and not yet* in labour" to "*or*",
and `Id10317` asks "how many babies" as a yes/no question -- identical across
ND01, RJ01, KEM and KA01. Odia `Id10191`-`Id10195` is pasted down by one row
(correct strings are one row below; fix bottom-first). Bangla "Yes" is a
Malayalam word on four questions. Kannada and Marathi ask *birth* year where
English asks year of *death*. Tamil (0.06%) and Malayalam (0.11%) were audited
to the same depth and are clean.

Demoted by migrations `c8e4a1f7b209` (or, kn) and `d5b71c3e9a84` (hi, mr, kha,
bn). Both capture prior state and `downgrade` restores it; verified on
throwaway databases. **These defects live in the deployed ODK workbooks** --
fixing them in DigitVA's string editor fixes only the web form. They must be
corrected in the workbooks and republished to ODK Central. ODK collection was
never switched off. Collected data is **not** shown to be affected: ODK shows
the English beside the translation.

### Translation editor rebuilt (`digitva-8go`, closed)

`/admin/instrument-translations/<instrument>/<locale>`, linked as **Edit** from
each locale row. One row per question in form order (code / English / locale
text), 50 per page, `?page=` and `?q=` in the URL. Modal edits label, hint and
choice options; constraint message and guidance show read-only, badged
untranslated; shared lists state how many questions they change
(`YES_NO_DK_REF` = 224); Save / Save and next / Undo / Close with dirty
tracking; per-field Google Translate links, hidden for Khasi. Covers all 449
WHO questions plus 80 DigitVA layer questions and 10 ownerless choice lists
(536 rows). Markup renders via the form's own `parseRichText`, now re-exported
from the bundle -- do not write a second parser.

Known limit: browser back/forward while the modal is dirty cannot be vetoed,
so that one path discards silently (commented in the template).

### WHO

#94 (`Id10304_a` unreachable) -- **unanswered**. #95 (`Id10230` agegroup) --
WHO replied 2026-09-21 that agegroup is an internal marker filtering nothing;
harmless on both sides. `digitva-mdj` stays open for #94 only.

### Web-intake demo

Project `ZZD001` (Demo) is READY: reactivated, web form `ZZD001Z00102`
materialised via `ensure_web_forms_for_project` (not raw SQL -- the side effect
matters). `testadmin@digitva.com` holds its interviewer grant. Verified in a
browser to `/intake/`, questionnaire render, draft save and locale switching.
No full submission has been completed.

### Next

1. `digitva-fb5` -- native speakers per language; corrections into the
   workbooks, republished. Hindi first (four workbooks share its defects).
2. `digitva-mxn` -- show English beside the translation in the web form. The
   audit is the argument: ODK's packed cells already do this, which is why its
   defects are survivable there and ours were not.
3. `digitva-8go.1` -- author the 427 untranslated constraint messages and
   guidance notes, seeded as `machine` so nothing unreviewed is served.

### Traps from this pass

* `bd close` refuses a blocked issue or one with an open child, and **piping it
  to /dev/null hides the refusal**. `bd ready` omits blocked issues too, so
  absence from it is not evidence of closure. Read the close output.
* `bd close` / `bd unclaim` do not rewrite `.beads/issues.jsonl`; run
  `bd export -o .beads/issues.jsonl` after.
* The container cannot write to the host scratchpad. Print to stdout and
  redirect on the host.
* Subagents' reach claims need checking: two of the three "shifted" Marathi unit
  lists are referenced by zero questions. Verify blast radius from the survey
  `type` column before repeating it.
* There are **ten** deployed workbooks, not eleven.

---

Updated 2026-09-20 (third pass). `origin/main` is at `d41c353`, working tree
clean. Full suite **1,714 passed**, `PYTEST_EXIT=0` read from pytest itself;
vendored JS suite 28 passed. Dev is at migration head `120f783ea138`; this pass
added no migration.

**The curated reference form is now WHO V2.0** (`2026081401`), English only,
with two accepted deviations. `digitva-13x` and `digitva-13x.1` are closed and
the decision is final -- not a holding position awaiting WHO.

Two defects were found in V2.0 and reported upstream. Neither reached our data:

* **`Id10304_a` can never be asked** under V2.0's rewired `relevant`.
  `selected(${Id10334},'yes') and selected(${Id10305},'yes')` is unsatisfiable,
  because `Id10334`'s own relevance contains `not(selected(${Id10305},'yes'))`.
  Enumerated with our own evaluator: reachable in 8,245 of 41,225 coherent
  states under V1.1, **0** under V2.0. It is the ruptured-ectopic fainting
  question, so adopting V2.0 verbatim would have silently dropped it from every
  interview. [SwissTPH/WHO-VA#94](https://github.com/SwissTPH/WHO-VA/issues/94).
* **`Id10230`'s `agegroup` narrowed to `a`** -- adult-only, and the only
  lowercase value among 508 -- while its own relevance, its five follow-up rows
  and its sibling `Id10227` all still say child-or-adult. Clinically arguable
  (its guidance names the elderly and diabetics) but applied to one cell and
  neither place that governs behaviour. [SwissTPH/WHO-VA#95](https://github.com/SwissTPH/WHO-VA/issues/95).

Both are `DEVIATIONS`: we keep V1.1's relevance and `C_A`. All ten deployed
project workbooks were checked and are unaffected -- the whole eight-question
relevance neighbourhood is byte-identical to V1.1, and those files came from
ODK Central, so that is a check of what is live. Analysis, diagram and a
standalone re-checker: `docs/kb/WHO_VA_2022_Docs/id10304a-v2-relevance-defect.md`
and `tooling/who-va-2022/check-id10304a-relevance.py` (runs under `uv run` with
no repo, exits 0/1/2 where 2 means "logic I was not written for" rather than a
false all-clear).

**Three things the previous handoff got wrong**, corrected here because they
cost this pass real time:

1. `instrument.ts` is hand-authored glue, but the 449 questions come from
   `generated/who-va-2022.instrument.json`, which
   `app/services/xlsform_instrument_builder.py` regenerates **faithfully** --
   a V1.1 rebuild reproduced the shipped JSON exactly outside its eleven
   recorded deviations. The move was a rebuild and a reconciliation, not the
   editorial work that was queued.
2. There was not one substantive change but two: the second is `Id10230` above.
   The brief's "no constraint, calculation or required change" was true and
   still missed it, because `agegroup` is none of those.
3. The dominant issue was never text. V2.0 is the *multilingual* workbook, so
   of 435 questions differing from the shipped instrument, **417 differ only in
   injected `ar`/`es`/`pt`/`sw` or rewritten `fr`**. Only 18 differ in English
   or structure.

**The instrument carries English only; every other language comes from the
translation engine.** Decided because the alternative was a second, staler copy
of served text: `map_instrument_translations` holds 260 French choice labels to
the bundle's 144, plus 476 question labels and 207 hints the bundle had none of,
and of the 142 keys in both, 53 differed with the engine holding the newer V2.0
text. `applyTranslations` already wrote the payload over the bundle, so the
database copy was winning anyway. The builder gained a `locales` parameter
defaulting to every language the workbook carries, so existing callers are
untouched. One accepted cost, recorded in policy: if a translation request
fails, a French interviewer now sees English for those 144 choice labels, which
is how all twelve other locales already behave.

Two smaller things worth knowing. The expression conformance corpus and the
layer reference **regenerate byte-identical** -- the right result, since
deviating `Id10304_a` back means the expression surface never moved. And the
shipped JSON now stores expressions as `source` without the precomputed `ast`
earlier revisions carried; semantically neutral (the runtime parses on demand
and verified a supplied `ast` against its source anyway), but no test asserts
it, so `vendor/who-va-2022/README.md` records it.

Also closed: `digitva-xv9`, which shipped in `fe498e6` and had sat
`in_progress` with an expired lease. Verified before closing, not assumed.

**Do these next.** Nothing is queued that needs a decision:

* `digitva-mdj` (P2) -- open only to track WHO's reply on #94 and #95. Blocks
  nothing. If WHO publishes a correction, re-run
  `tooling/who-va-2022/check-id10304a-relevance.py` against the new workbook
  before adopting anything from it.
* `digitva-ssi` (P3) and `digitva-3jj` (P3) -- both flakiness beads, both still
  needing a recurrence to be worth chasing. Neither reproduced this pass.

A trap that cost time here and will again: `bd close` and `bd unclaim` do not
rewrite `.beads/issues.jsonl` the way `bd update` does, so `git status` reads
clean while the tracked export still says `in_progress`. Run `bd export -o
.beads/issues.jsonl` after closing anything.

---

Updated 2026-09-20 (second pass). `origin/main` is at `8cdb1fd`. Working tree
clean; `dailybackups/` is now gitignored. Full suite **1,711 passed**,
`PYTEST_EXIT=0`. Dev is at migration head `120f783ea138`.

Nine beads closed in this pass, four commits:

**`8cdb1fd` -- dev's authorization constraint repaired, and live drift made
detectable** (`digitva-88e`, plus the pass's shared docs). Dev's
`va_user_access_grants` CHECK *and* its `access_role_enum` both omitted
`collaborator_pii`, so that grant was refused on dev and accepted on a fresh
install. Migration `120f783ea138` repairs both idempotently. The real fix is
`flask schema drift-check`: nothing here ever compared a *running* database
against the migration chain -- `test_schema_drift.py` validates migrations
against models, and alembic's autogenerate does not compare CHECK constraints at
all. The new command diffs a target against a throwaway chain-built reference on
constraint names and text, column defaults and enum members, read-only on the
target and normalising definitions so it does not cry wolf. Also corrects the
extension table (`geography` and `intake_screen` contribute **no** instrument
questions, citing O4), adds the `va_submission_payload_versions` section
data-model.md never had, and documents all four bucket schemes.

**`0343730` -- the 34 admin-editor bucket mappings frozen** (`digitva-2g7`).
Measured rather than assumed: nothing was lost on dev, and the whole delta is 34
deliberate additions. Frozen to a CSV the importer reapplies, with a live
snapshot so an administrator's later repointing beats the freeze. The overrides
are tied to the workbook they correct -- the first version applied them to every
import, which would have layered stale corrections onto an updated derivation.

**`bf5394f` -- the server judges a submission** (`digitva-cal.2`,
`digitva-aiy.1`). Relevance and constraints re-derived server-side, recorded as
`validation_err` per payload version, never refusing. Irrelevant answers
stripped at final submit with the draft intact, resolved to a fixed point.

**`b14362a` -- bundle reproducibility, two untested commands, a stale label**
(`digitva-cw9`, `digitva-28a`, `digitva-2c1`).

Earlier the same day, five commits, newest first. `origin/main` is at
`e77c293`, working tree clean apart from an untracked `dailybackups/`.

**`e77c293` -- Python has its own expression evaluator** (`digitva-cal.1`,
closed). `app/services/xform_expression_evaluator.py`, plus a conformance
corpus of 347 unique expressions and 1,903 cases generated from the TypeScript
engine by `tooling/who-va-2022/build-expression-corpus.mjs` and committed to
`vendor/who-va-2022/src/generated/expression-conformance-corpus.json`. The
corpus is the deliverable, not the port: two evaluators that drift are worse
than one that is merely trusted, and `78757d4` showed this codebase can carry a
silent evaluator defect for a year. Not vacuous -- 334 true, 1,351 false, 60
NaN, 59 strings. `now` and timezone pinned so regeneration reproduces it byte
for byte. Removing the six `re.ASCII` guards makes the corpus report "1 of 1903
corpus cases diverged"; verified independently in the main session, not taken on
report. Intake behaviour unchanged: `web_intake_service` still trusts the client
boolean until `digitva-cal.2`. Policy: `docs/policy/xform-expression-evaluator.md`,
which records the locale-independence invariant (a choice *value* is never a
translation target, so `selected(${sa01}, '1')` compares the same `'1'` in all
thirteen languages) and the two JS behaviours that did not port.

**`6d94656` -- re-import demotes an approved locale; fresh installs get the
drafts** (`digitva-dqh`, `digitva-dms`, both closed). A bulk re-import or XLIFF
hand-back into an `approved` locale returns it to `in_review`, clears the
approver and deactivates it; the import proceeds. Refused before any write
unless acknowledged -- `--acknowledge-demotion`, a form field on both import
routes, a panel confirmation. The panel sends the field **only** when its dialog
fired and was accepted; a stale locale list sends nothing so the route refuses
and explains, because acknowledging a warning nobody saw defeats the rule.
Migration `7134cb5dc7b6` creates the twelve locale rows when absent (draft,
inactive) and seeds the 214 strings as `machine`, so a fresh install with no
workbook ever imported now has them. Strings live in
`resource/digitva_layer_translations_2026_09_20.csv` rather than a third inlined
copy, with a test parsing both applied migrations' literals to catch drift.

Updated 2026-09-20. Earlier the same day, three commits; the second is described first
because it corrects the first.

**Machine drafts are no longer served** (`digitva-4kj`, `digitva-we0`, both
closed). `b6d2f4a9c1e7` seeded 214 LLM-authored strings as `source='imported'`,
indistinguishable from workbook-sourced text, so approving a locale blessed
both at once. `source` gains a third value `machine`; `c1a4b6e8d3f2` relabels
exactly those rows, matching on text so an administrator's correction is left
alone; `export_translations` and coverage exclude them, so the form falls back
to English per string while the panel still lists them with an **Accept**
button that promotes one to `edited`. Precedence `edited` > workbook
`imported` > `machine` needed no importer change: only `SOURCE_EDITED` was ever
special-cased. In XLIFF a machine row is `initial` with
`subState="digitva:machine"` carrying its draft, not `translated` — review
caught that it was being handed to CAT tools as finished work. An unmapped
`source` now understates rather than claiming translated. `d2b5c7f9e4a3`
renames the CHECK constraint, which the naming convention had doubled and
truncated to `ck_mas_instrument_locales_ck_mas_instrument_locales_act_5121`.
Verified: 32/32 seeded rows relabelled in a two-locale fixture, an `edited` row
survived a relabel round-trip while 31 returned to `machine`, a locale with 19
machine + 1 edited row served exactly 1 item with zero leakage, `pg_constraint`
reports the intended name. Full suite **1,656 passed**, `PYTEST_EXIT=0`.

One caveat written into policy: a machine draft exported and handed back
*untouched* with `--as imported` becomes servable, because the importer judges
the hand-back rather than each segment. Prefer the panel's per-string Accept.

Updated 2026-09-20 (translation management: de-gating, approval lifecycle,
seeded layer strings). Three related changes, all on `e1b6c9a3d7f4`.

**1. The importer no longer reads a policy document** (`digitva-dsj`, closed).
`SOURCE_POLICY_DOC`, `DocumentedSource` and `documented_sources()` are gone.
Any readable workbook may be imported for any locale; `_resolve_workbook`
still contains the path to the repo root or the system temp dir. The
"Translation sources" table in `docs/policy/va-form-project-configuration.md`
stays as provenance for humans and no code reads it. `--cross-check` survives
as a plain dry run. `language_name` now comes from the workbook's own
`field::Name (code)` header, then `--language-name`, then the locale code.
Decided by the owner: importing a questionnaire source is a reviewed one-time
activity, and the runtime path for changing translations is the admin string
editor, not a re-import.

**2. Per-locale approval lifecycle** (`digitva-j23`). `mas_instrument_locales`
gains `lifecycle_state` (`draft`/`in_review`/`approved`),
`approved_by_user_id` and `approved_at`, plus CHECK constraint
`ck_mas_instrument_locales_active_requires_approved`: only an `approved`
locale may be `is_active`, and leaving `approved` while active is refused.
Migration `a3f7c1d9e6b4` backfills every locale to `in_review` and
`is_active=false` — **a deliberate mass-deactivation**, per the owner's
decision that nothing unreviewed is served. Because `upgrade` clears
`is_active`, it first captures the prior active set into
`_mig_a3f7c1d9e6b4_prior_active` and `downgrade` restores from it; without
that the thirteen active locales would have been unrecoverable. `_mig_` is
excluded from drift detection in `app/schema_filters.py`, prefix-based so a
table the app should own cannot hide behind the rule. New
`set_locale_lifecycle_state`, CLI `instrument-translations lifecycle`
(`--approved-by` required for `approved`, since the CLI has no session),
route `POST .../<instrument_code>/<locale>/lifecycle`, panel badges with
**Activate** disabled until approved. Coverage still decides nothing.

**3. DigitVA-authored layer strings seeded** (migration `b6d2f4a9c1e7`).
The layers add questions no workbook carries — consent mode and its choices,
the medical-certificate upload, the shared "Medical and death documents"
heading, the two image-count hints, narration language and its choices, and
the two ABHA fields. 214 strings across twelve locales, as literals; the
migration reads no workbook and imports no application code. Khasi is
deliberately absent (no reliable source; a wrong label is worse than a gap
that falls back to English) and ABHA is seeded for the seven Indian locales
only. Rows land as `imported`, so a real translated workbook or an XLIFF
hand-back outranks them and an administrator's edit is never overwritten.
**These are machine translations awaiting a speaker's review** — which is what
the lifecycle in (2) is for.

Verified on a throwaway database (never `minerva_test`/dev): the full chain
reaches a single head `b6d2f4a9c1e7`; two active locales were deactivated on
upgrade, captured, and **restored on downgrade**, with the recovery table then
dropped; the seed inserts 20/12/16 rows for hi/fr/sw and 0 on an empty
database; `downgrade` deleted 46 of 48 seeded rows and preserved both rows a
human had touched; two consecutive upgrades leave the `edited` row unchanged.
Full suite: **1,641 passed**, `PYTEST_EXIT=0` read from pytest itself,
including `tests/migrations/test_schema_drift.py`. One full run in between
failed `tests/test_admin_api.py::test_odk_site_mappings`, which passed 45/45
three times in isolation and in three other full runs — the known
`digitva-ssi`, now with a second data point that weakens its load hypothesis
(see its notes). Five pre-existing test fixtures across `tests/services/test_instrument_translation_xliff.py`,
`tests/services/test_web_form_instruments.py` and
`tests/routes/test_form_options_api.py` built an active
`mas_instrument_locales` row directly and needed `lifecycle_state='approved'`
added to stay valid against the new CHECK constraint; behaviour unchanged.

**Do these next.** Only three remain open, and one needs a decision rather than
code:

* `digitva-13x` (P2) -- **done in the third pass; see the top of this file.**
  This bullet's analysis was wrong in three ways and is kept only so the
  corrections have something to point at: the instrument *is* regenerable from
  the workbook, there were two substantive changes rather than one, and the
  multilingual payload mattered more than the text.
* `digitva-ssi` (P3) -- ODK site-mapping POST idempotency. Did not reproduce in
  ten runs; second occurrence came in a normally-paced suite, which weakens the
  load hypothesis and favours order dependence.
* `digitva-3jj` (P3) -- vendored vitest flaky under load; a different test fails
  each time, which is how you tell it from a regression.

Closed this pass with reasoning worth reading in the bead rather than repeated
here: `digitva-ybt` (the geography flag is declarative, not dead),
`digitva-ajn` (ND01's constraint rejects a value its own data contains; fix
belongs upstream), and the `digitva-cal` parent, which notes that flipping from
record-and-accept to actual refusal is a separate decision that the new
`validation_err` data should inform.

Previously queued, now done:

* `digitva-cal.2` (P1) -- re-derive submission validity on the server with the
  new evaluator. Decided: **log and accept, do not reject.** A server that
  starts refusing what the client accepted leaves a field interviewer unable to
  complete a death record. Each disagreement is stored as a `validation_err` on
  `va_submission_payload_versions` (per-version, so a resubmission carries its
  own record) naming the question and the rule, never an answer value, and is
  returned in the HTTP response. A later release may flip to refusing; the data
  this collects is what should inform that.
* `digitva-aiy.1` (P2) -- strip irrelevant answers at final submit, drafts keep
  them so a mis-tap is recoverable. Needs the evaluator, which now exists.
  Cascade must resolve transitively (`md_available` -> `md_count` -> `md_im*`),
  and what happens to an already-uploaded attachment behind a stripped answer
  must be decided, not left implicit -- attachments phase 2 turns that into real
  wasted storage.
* `digitva-liu` (P3) -- eleven of fourteen CHECK constraints carry doubled,
  sometimes truncated names. Harmless today because create and drop are
  self-consistent, but no name in the database matches what the models declare,
  and `test_schema_drift.py` is structurally blind to it because alembic does not
  compare CHECK names.
* `digitva-ajn` (P4) -- `sa13`-`sa19` keep ND01's constraint verbatim by the
  owner's decision 2026-09-20, and real synced data contains `'0'`, which that
  constraint rejects. An observation to know about, not a defect to fix here.

Also still open from earlier in this work:

* `digitva-dms` (P2) — the 214 seeded strings reach **only an
  already-deployed database**. Verified: the migration inserts 0 rows on an
  empty one, because locales are created later by an operator import, and
  alembic will never run it again. A fresh install therefore never gets them
  and has no documented path to. Needs the strings in a committed data file
  plus an idempotent `flask instrument-translations seed-layers`.
* `digitva-dqh` (P2) — the approval gate holds for a *new* locale and is
  defeated for an *existing* one: an admin can re-import a workbook or push an
  XLIFF hand-back into a live, approved locale, rewrite every string, and it
  stays approved and served. Needs an owner decision (knock it back to
  `in_review`, or write down that bulk rewrites of a live locale are trusted).
* Operator step on this dev database after upgrading: re-import each language
  (eight of thirteen land within 3-34 items of complete), then approve and
  activate the ones a speaker has reviewed. Sizing table in
  `docs/current-state/admin-and-setup.md`.

Also filed today and out of scope: `digitva-ssi` (second occurrence, notes
updated), and from earlier sessions `digitva-c48`, `digitva-cal`,
`digitva-ybt`, `digitva-3jj`.

Previously: `digitva-thr` is closed: all four work packages landed, the
social autopsy layer is authored, and layer questions can be translated. On
top of the previous session's `e0164d9`; `origin/main` is at the commit that
updated this file, working tree clean before this session's uncommitted
change above.

## What landed

| Commit | What |
| --- | --- |
| `1e94b4c` | Layer questions enter the translation reference via a generated artifact; the 0.95 coverage activation gate and `--force` removed; per-extension coverage; the choice-code convention recorded |
| `78757d4` | The social autopsy layer authored from ND01 verbatim (`sa01`-`sa19`), plus an expression-tokenizer fix: a backslash is now an ordinary character, matching XPath 1.0 |
| `702f518` | The importer learns the packed-cell conventions ND01 actually uses (newline, `" / "`, `English (Translation)`), and treats an unsplittable interleaved cell as untranslated |
| `3a17d8c` | Viewer roles wired to routes; two scope leaks closed; per-unit coding gates; migration `a40c38e73af4` |
| `b8d05ef` | WHO 2026 annex ICD-10 ranges as the `WHO_2022_VA_2026` scheme; migration `c5f2a8d1e9b3` |
| `926c212` | Web intake configurability, organization-API ancestors, PII field registry; migration `b8e3d1f7a2c4` |
| `e16ea30` | `role_required` raises at decoration time on an unknown role name |
| `6ea5420` | `R10` selectable, bucketed to `VAs-06.01` |
| `b247950`, `ae6d6fa`, `5c5473a`, `8f0f672`, `98b9816` | Policy and task records (below) |
| `455eb34`, `d08fce7`, `63a3dcb`, `479b698`, `44ffbeb` | Tooling hygiene: Dolt log and backup pointer untracked, beads prefix fixed, droppings ignored |
| `4b0e308` | PII set fails closed per form type; PII cache versioned on `mas_field_display_config` `(count, max(updated_at))`. No migration. |
| `711710e` | Policy: what a second form type must pass before it goes live |
| `b159e53`, `e0d2300`, `4a7c623` | `tests/test_route_auth_coverage.py`: every `url_map` endpoint must carry `role_required` or `login_required`, or sit on an explicit allowlist; public set settled |
| `89c1b79` | CLAUDE.md trimmed; subagent working model written down |
| `ae8ace5` | `GET /api/v1/organization/<project_id>/form-options`; four `web_intake_*` columns on `va_project_master`; migration `f2a9c4d7e1b3`; intake form takes locale and instrument from the project |
| `10d38c8` | Fifteen migrations importing MV builders pinned; any new application import in a migration fails the suite |
| `705021e` | Closed projects resolve no grant of any scope; one shared predicate in twelve resolvers plus the redaction check |
| `1369c0e` | Form types are layers on the standard instrument; intake resolves `instrument_code`, so `WHO_2022_VA_SOCIAL` renders |
| `5b22094` | Projects admin panel reads and writes the four `web_intake_*` form options; project POST accepts them through the same validator as the PUT. No migration. |
| `742ea9d` | Web form locale is `en` everywhere plus what the instrument has translations for (`app/services/web_form_instruments.py`); interviewer picks a working language, remembered in the browser. No migration. |
| `10267ee` | `project_pi` role gate is an EXISTS (`VaUsers.is_project_pi`), closing `.tasks/auth-decorator-followups.md` item 3 |
| `32ea0fb` | The web-capture configuration plan and the register of every decision taken 2026-09-19 (Q6, P2, W6, extensions, base_instrument_code, D2, D3, D5, D6, C1/C4 deferred, annex follow-ups, translations delivery, API first) |
| `2b4b869` | Nine deployed project workbooks under `docs/kb/WHO_VA_2022_Docs/` with a README (form id, version, languages, checksum) |
| `0fb8d75` | End-to-end test: a web submission in a tree project routes to its unit and reaches only its coders |
| `ab663ca` | Every decision recorded in the document that raised it |
| `610f55d` | The 16 WHO_2022_VA_2026 overrides that depart from the annex documented and pinned by a file-based test; annex follow-ups 4-7 filed as `digitva-2g7`, `28a`, `jt3`, `2c1` |
| `5043448` | Web form type, welcome note, death-summary flag as project settings; `base_instrument_code` on `mas_form_types`; defaults for a new web project; migration `c3e8b5a1f4d2` |
| `fe498e6` | Web-capture readiness: nine checks as JSON, Projects panel badge and list, `flask web-intake readiness` |
| `383acef` | French, Portuguese, Arabic, Swahili and Spanish sourced from WHO's multilingual V2.0 form (`2022whova_xls_form_for_odk_multilingual.xlsx`); thirteen locales active on dev |
| `2af0885` | XLIFF 2.0 export and import per locale as the industry-standard interchange (resource ids `question.<name>.<field>`, `choice.<list>.<name>.label`); English fallback pinned |
| `8a4791b`, `d6902f3` | Hindi sourced from the ND01 ICMR form (the most commonly deployed); every DigitVA layer it carries inventoried in policy (social autopsy, death-certificate images, medical-record images, narration audio and image, intake screen, geography) |
| `0dd80ea`, `347bbf1` | Translation-sources parser stops at its table's end; tests read the Hindi source from policy. `d6902f3` and `0dd80ea` were pushed on a red targeted run (exit status of `tail`, not pytest); `347bbf1` corrects it and the full suite is green on that tree |
| `7bf1d5f` | The vendored WHO VA bundle rebuilt from its own source. The bundle committed in `926c212` was not built from the source beside it: three fixes in `src/` had never reached a browser (a language-dropdown `accessibilityRole` of `button` where source says `option`, and React keys on the form and preview roots). Found by a reproducibility check before layering on top |
| `d04a9f8` | DigitVA layers become conditional on the project's `enabled_extensions`; `medical_records` named as the eighth extension with `web_intake_medical_records_enabled` (migration `e1b6c9a3d7f4`); `ds_available`/`md_available` gate questions and a separate `consent_mode` question. `digitva-thr.1`, `digitva-thr.2` closed |
| `d497e0e` | Instrument translations stored, managed and served: `mas_instrument_locales`, `map_instrument_translations`, importer from one documented source workbook per language, admin panel, `GET /api/v1/instruments/<code>/translations/<locale>`, client-side apply in the intake page; migration `a7d4f1c9b0e6` |

Migration chain is linear: `f1c6a9d3e7b5 -> a40c38e73af4 -> c5f2a8d1e9b3 ->
b8e3d1f7a2c4 -> f2a9c4d7e1b3 -> c3e8b5a1f4d2 -> a7d4f1c9b0e6 ->
e1b6c9a3d7f4`. Verified by an empty-database `flask db upgrade` replay of the
whole chain, which reaches head and yields 2,489 selectable ICD-10 codes and
four COD bucket schemes.

Verified: full suite **1,624 passed at `702f518`**, `PYTEST_EXIT=0` read
from pytest itself, plus 16 tooling tests at `EXIT=0`. The vendored suite is
715 tests and passes on a quiet machine, but is timing-flaky under load
(`digitva-3jj`): a different test fails each run, which is how you tell it
from a regression. Earlier: 1,618 at `78757d4` and at `1e94b4c`, 1,605 at
`d04a9f8`, 1,602 at `347bbf1` (1,570 after WP6, 1,499 after WP1, 1,469 after the project_pi predicate, 1,464 after the instrument-locale rule, 1,453 after the projects-panel inputs, 1,449 after the instrument-layer change (1,445 after the closed-project rule, 1,423 with form-options, 1,409 after the public-route decisions, 1,391 after the PII change, 1,381 on the rebased tree before all of them).

## The access model, as it now stands

`collaborator` and `collaborator_pii` reach **five** read-only routes:
`/data-management/`, `/data-management/dashboard`, and the `submissions`,
`filter-options` and `kpi` APIs. Nothing else, no writes.

Two things worth knowing before extending it:

- **`dm_scope_filter` is wider than the grant and fails open.** An `org_unit`
  grant is bridged to the unit's whole project, because a unit does not name a
  site. Callers that enumerate submissions must AND in
  `dm_submission_org_unit_condition`. Two callers were not doing that and were
  serving a project's whole site roster to a viewer granted one leaf unit;
  both now narrow themselves. If you add a caller, apply the condition or write
  down why the coarse answer is right.
- **`/data-management/cod-buckets` is deliberately NOT viewer-reachable.** The
  page is a shell and all three endpoints behind it are `data_manager`/`admin`,
  so granting the page alone gives a screen that 403s on every fetch. Opening
  that API is a separate widening: `export.csv` emits staff identity.

## DigitVA layers (landed this session)

Layers are overlays on the one bundled WHO 2022 instrument (E7/E8), and
until `d04a9f8` the mechanism was half-built in a way worth remembering:
the server derived `enabled_extensions` and served it, but
`vendor/who-va-2022/src/instrument.ts` spliced **every** DigitVA question
into one module-level constant regardless, and the intake page branched on
exactly one name (`intake_screen`). A project that disabled a layer still
got its questions. Composition is now
`createWhoVa2022Instrument(enabledExtensions)`; `whoVa2022Instrument`
remains exported as the all-on composition so existing importers and the
vendor suite are unaffected.

`enabled_extensions` now has **eight** names: `medical_records` joins the
seven, carrying `md_available`/`md_count`/`md_im1..30` out of
`digitva_core`, derived from `web_intake_medical_records_enabled`
(default true, migration `e1b6c9a3d7f4`).

**ND01 was compared before adoption, and mostly not adopted.** Only
`ds_available` and `md_available` were taken. Rejected and why:
`Id10002`/`Id10003` gain a `calculation` hard-coding state `21` and
district `412`, so every other site would silently record "very low" HIV
and malaria mortality; `Id10365` loses the WHO constraint forbidding a
baby recorded as neither under 2.5 kg nor over 4.5 kg. `Id10476` was left
alone: its reference relevance `string-length(${Id10476_audio})=0` is
already true while web intake has no audio capture, so the typed narrative
shows today and the expression only becomes live with attachments phase 2.
ND01 encodes telephonic interviews as a third `Id10013` value and a
widened `consented` group; that was **not** adopted. `consent_mode` is a
separate question recording how consent was taken, because `va_consent`
stays the authoritative record that it was taken (owner, 2026-09-19).

Two traps for whoever builds the next layer:

- **Numbering.** `consent_mode` first shipped at `anchor.order + 1` and
  collided with `Id10011`, because `Id10013` is followed immediately by
  it. The neighbouring `custom_medical_certificate_upload` uses
  `anchor + 1` safely only because the generated instrument happens to
  leave a gap after `Id10473`. Number DigitVA questions from `maxOrder`.
  A test now asserts `order` uniqueness across all sixteen layer
  combinations; nothing held that invariant before.
- **`social_autopsy_enabled` means two unrelated things.** It drives the
  `social_autopsy` extension *and* the coder-side social-autopsy analysis
  panel (`app/routes/api/so.py`). A third consumer must not assume one
  meaning. `docs/planning/social-autopsy-rendering-plan.md` is a stale
  draft superseded by the layers model.

Both `digitva-thr.3` and `digitva-thr.4` are now closed -- see "Layer
translation (landed 2026-09-20)" below. One thing recorded here earlier was
wrong and is worth correcting rather than deleting: ND01 does NOT lack a
Hindi column and did not need a general parser. It has `label::Hindi (hi)`,
whose cells pack `English\nHindi`, and `split_packed` already handled that --
which is how Hindi reached close to full coverage on the base instrument's
survey labels (98.6% of the label breakdown once layer labels are counted
too; digitva-o3s widened the measure, see below). What was
genuinely missing was narrower: two other packing conventions and a
reference source that included the layers at all. Also `digitva-aiy`:
relevance is purely
presentational, so answering a gate "no" can orphan image answers already
captured -- pre-existing, but the gates widen it, and attachments phase 2
turns those references into real files.

## Layer translation (landed 2026-09-20)

`digitva-thr` is closed. What was actually wrong, and what it cost to fix:

**Layer questions existed only as TypeScript.** `createDigitVaExtension`
composed them at runtime and nothing serialized them, so
`who-va-2022.instrument.json` held the 449 WHO questions and none of
DigitVA's, and `reference_items()` raised for any code but `WHO_2022_VA`.
`consent_mode` and `md_available` therefore could not be imported, exported
as XLIFF, edited or scored. `tooling/who-va-2022/build-layer-reference.mjs`
now emits `vendor/who-va-2022/src/generated/digitva-layers.reference.json`
by set difference against the WHO base, so it cannot drift as layers are
added. It is deterministic on purpose -- no `built_at` -- and a byte-identical
regenerate is a test. It emits a data file only; the browser bundle is
untouched by it, and that isolation is pinned by a test that fingerprints the
bundle directory by content hash rather than asking git (the git version
conflated "the generator did not write there" with "nothing did").

**Entries carry every contributing extension, not one.** `digitva_documents`
belongs to both `medical_records` and `death_summary`; attributing it to
whichever came first in the extension list would score it under a layer the
project had not enabled.

**Activation is no longer gated on coverage** (owner, 2026-09-20: "whatever
the translation in the tool is the translation"). The 0.95 threshold, the
auto-activate on import and `--force` are gone. English fallback already
answers the question per string -- an untranslated key is ABSENT from the
served payload, not empty, verified in `export_translations` and in the
client's `setLocalized` -- so a percentage was deciding something it could
not see. Coverage is still computed and reported, now per extension too.
Base coverage keeps the WHO instrument's own 476 question labels as its
denominator; layer labels are deliberately NOT folded in.

**The social autopsy layer is ND01 verbatim, and that is the decision.**
`sas01`-`sas07` keep their ordinal values ("1".."8") although they are the
outlier against WHO's conventions and DigitVA's own, which are semantic.
`mas_choice_mappings` already carries those ordinals for `sa01` against form
type `WHO_2022_VA_SOCIAL`, and `submission_analytics_mv.py:371-374` projects
`sa01`-`sa19` raw into the COD-snapshot CSV export, so a semantic recode
would put two value shapes under one field id and one column. The
`sa13`-`sa19` relevance expressions stay literal string comparisons against
`"na"/"Na"/"nA"/"NA"` rather than `selected()`, which would change which
answers reveal the field.

**The choice-code convention, settled by the owner 2026-09-20:** questions
DigitVA authors itself save semantic codes; questions mirrored from a
deployed form keep that form's codes verbatim. Everything DigitVA had already
authored complied, so it cost nothing to adopt.

Three traps for whoever works here next:

- **The expression tokenizer no longer treats backslash as an escape.**
  ND01's `regex(.,'^(?!0{1,3}$)\d{1,3}$')` was being tokenized to `d{1,3}`,
  which no digit-only answer satisfies. The first fix unescaped only `\'`
  and `\"` and made a literal ending in a backslash throw instead of parse;
  the rule now matches XPath 1.0, where a backslash is ordinary and the
  doubled quote is the only escape. Safe because the corpus contains no
  backslash at all -- verified across the generated instrument JSON, the
  extension source, and the curated workbook's shared strings and every
  sheet. **The vendored engine is the only evaluator of this grammar in the
  system.** No Python parses it: `xlsform_instrument_builder.py:169-172`
  passes expression text through as opaque `{"source": ...}` and says so in
  its own docstring, and there is no pyxform/formpack/xpath dependency.
- **`split_packed` fails closed, and that is load-bearing.** It splits only
  on an exact match against the reference English. An unrecognised cell is
  kept whole and reported rather than guessed at. Do not add fuzzy or
  similarity matching to make a near miss "work" -- a near miss should be
  visible as untranslated. Whitespace runs are collapsed for the comparison
  only, never for the stored text.
- **`intake_screen` and `geography` contribute no instrument questions, and
  that is correct.** ND01's three-item `begin_screen` group is substituted by
  a single admin-configured `intake_note` rendered as a client welcome card,
  and geography's fields are server-injected after validation per decision
  O4. The policy table at `docs/policy/va-form-project-configuration.md:51`
  still describes both as question-contributing, which is how someone ends up
  "restoring" server-injected fields as interviewer questions -- filed as
  `digitva-c48`. The `geography` flag itself is derived and served but has no
  consumer anywhere: `digitva-ybt`.

Filed this session and deliberately out of scope: `digitva-c48` (stale policy
table), `digitva-ybt` (dead geography flag), `digitva-cal` (the server takes
the client's own `valid` boolean as the validity gate -- pre-existing, and a
decision to take rather than a bug to fix, given interviewers are
authenticated), `digitva-ssi` (an ODK site-mapping POST may not be idempotent
under extreme latency), `digitva-3jj` (the vendored vitest suite is
timing-flaky under machine load).

## The vendored bundle was stale (fixed this session)

`7bf1d5f`. The bundle committed in `926c212` was not built from the source
committed beside it: three fixes lived in `src/` and had never reached a
browser -- a language-dropdown `accessibilityRole` of `button` where source
says `option`, and React keys on the form and preview roots that stop one
subtree being reused across a view switch. Found only because a
reproducibility check ran *before* layering new work on top. **Run that
check first whenever you touch `vendor/who-va-2022`:** rebuild on an
unmodified tree and confirm `git diff app/static/vendor/who-va-2022/` is
empty but for `manifest.json`. That `built_at` timestamp dirties the
manifest on every rebuild and is what let the drift hide; `digitva-cw9`
proposes removing it so the invariant becomes testable.

## Start here

**The web-capture configuration plan is fully landed**
(`docs/planning/web-capture-project-configuration-plan.md`, beads
`digitva-6v1`, `xv9`, `shz`, `mze`, `9ff`, `0by` all closed). Operator
step on any database, dev included: import, **approve** and activate each
language with `flask instrument-translations import WHO_2022_VA <locale>
docs/kb/WHO_VA_2022_Docs/<workbook>`, then
`flask instrument-translations lifecycle WHO_2022_VA <locale> approved
--approved-by <admin>`, then `activate`. Since 2026-09-20 activation alone is
refused: only an approved locale may be served. Nothing serves Hindi until all
three are done. digitva-o3s (2026-09-20) widened coverage from a base-only
survey-label percentage to translated/all translatable reference items
(labels, hints, guidance hints, choice labels), with a label breakdown
(base + layer) reported alongside; none of the thirteen documented languages
reaches 100 percent under either measure now that layer labels count -- the
label breakdown ranges 85.6%-98.6% (eight from the deployed Indian forms,
five from WHO's multilingual V2.0 form; the eight Indian forms cluster around
93-98.6%, the five WHO multilingual locales around 85.6%), and the headline
item coverage is lower still, 65.7%-74.6%. Translators exchange a locale as
XLIFF 2.0 through
the panel or `flask instrument-translations export-xliff` / `import-xliff`;
where a string has no translation the form shows English. Whether the
curated reference form itself moves from V1.1 to V2.0 is `digitva-13x`.

**`digitva-thr` is closed.** All four work packages landed; the section
"Layer translation (landed 2026-09-20)" below has the detail and the traps.
The media parts are still attachments phase 2.

**Operator step, not optional:** re-import each language to pick up the
corrected packed-cell splitting. Three items were being stored wrong on
every deployment before `702f518` -- `language/hindi` as `Hindi (हिन्दी)`,
`language/english` as `English (English)`, and `Id10184_a`'s hint as English
-- and a re-import is the only thing that fixes rows already in the database.
Administrator edits are never overwritten, so this is safe to run.

Open after this pass, in order:

0. `digitva-aiy`: relevance is purely presentational, so answering a gate
   "no" can orphan image answers already captured. Settle it before
   attachments phase 2 turns those references into real files. Related and
   newly filed: `digitva-cal`, the server accepting the client's own `valid`
   boolean as the questionnaire validity gate.
1. ICD-11 phases 3 to 6 with decisions D1 to D6 all recorded, plus the
   project ICD classification default (web forms have no ODK mapping row,
   so `get_icd_classification_for_submission` returns `icd10` for them);
   the ICD-11 policy draft generated from the annex CSV for the owner's
   review, which also carries annex follow-up 2 (the full audit).
2. Attachments phase 2 (renders `death_summary`; W6: nothing mandatory),
   then the validator sidecar W1.
3. Annex follow-ups `digitva-2g7`, `28a`, `jt3`, `2c1`.
4. Older plans still carry "Open Questions" sections outside this pass's
   scope: `docs/planning/project-sites-forms-refactor.md`,
   `access-control-grants-design.md`, `social-autopsy-rendering-plan.md`,
   `icd11-self-hosted-api-and-ect-plan.md`,
   `docs/current-state/health-system-organization-model.md:298`. Most are
   superseded drafts; sweep or archive them.


Ranked across every session's input. Done since the previous ranking: the
PII set failing open, the PII cache never invalidating, and the route
decorator guarantee (see the two sections below). The six routes that were
pending a decision are settled: help, WHO documents and the home page are
public. The `form-options` endpoint is in (section below); its one open
consequence is the `WHO_2022_VA_SOCIAL` instrument.

The ranked list from the start of 2026-09-19 is exhausted, and the
projects-panel inputs are in (section below). Open, in order:

1. `digitva-4ym` is closed (section below). Left open by it: no bundled
   language other than `en` exists yet, so the picker never shows; and the
   dev database's projects still store `mas_languages` codes in
   `web_intake_available_locales` from before, which the resolver drops
   silently.
2. The `project_pi` predicate item is closed (section below).
3. The `base_instrument_code` column when a second standard instrument is
   bundled.

Then: attachments phase 2, the validator sidecar (written, unwired, decision
W1), ICD-11 coding screen phases 3-6.

## `project_pi` role gate is an EXISTS (landed this session)

Item 3 of `.tasks/auth-decorator-followups.md` said `project_pi` was the
only `role_required` predicate that queries and that reordering
`("admin", "project_pi")` would make its query unconditional. The premise
was stale: `is_admin()` is itself an EXISTS query, so every predicate costs
one statement and `any()` over booleans is order-independent already. What
remained was cost class: the gate fetched the user's whole PI project set to
answer yes/no. `VaUsers.is_project_pi()` is now an EXISTS over the same four
grant conditions plus `active_project_condition`, so a closed project still
yields False, and the predicate calls it. `get_project_pi_projects()` is
unchanged and still answers scope. `tests/test_role_required_project_pi_predicate.py`
asserts the semantics including the closed-project rule, identical statuses
under both argument orders for an admin, a PI and a plain user, and that
the gate is exactly one `SELECT EXISTS` statement with the scope query as
the discriminating control (both contain the word EXISTS because
`active_project_condition` is one; the outer select list is what differs).
Per-request caching of role checks was deliberately not added: admin routes
call `get_project_pi_projects()` several times per request and a memo on
`flask.g` would go stale inside the grant-mutating requests themselves.

## Web form locale is `en` plus the instrument's translations (landed this session)

Decided by the owner 2026-09-19 after the projects panel exposed the
problem: `web_intake_default_locale` defaulted to `en` while the seed creates
`mas_languages` codes `english`, `hindi`, ..., so on every seeded deployment
the resolver fell back to the first active code and dev's forms opened in
`assamese`. The rule now: **`en` is the default on every project and always
available; a project adds languages from what the bundled instrument
actually has translations for; the interviewer picks a working language on
the intake page and the browser remembers the last choice.** Narration
languages stay on `mas_languages`, because they describe the recording, not
the screen. The instrument's locales are an explicit registry,
`INSTRUMENT_LOCALES` in `app/services/web_form_instruments.py` (today
`WHO_2022_VA: {en}`), pinned to the vendored bundle by
`tests/services/test_web_form_instruments.py`, which greps the bundle for
`label:{<code>:` with positive and negative controls; there is no vendoring
script, so the registry is hand-maintained and the test is what keeps it
honest. The stored default column stays and is honoured only when it names
an instrument locale. The PUT/POST validate `available_locales` against the
registry and narration against `mas_languages`. `GET
/admin/api/web-form-locales` (admin) feeds the panel's available-languages
list, where `en` is ticked and disabled; the per-project default select is
gone. The intake page sets the component's `locale` attribute from
`localStorage` key `digitva.intake.locale` when the code is in the project's
list, else the default, and renders a picker only when more than one locale
is available; the component re-renders on the attribute change. Both JS
surfaces were exercised in jsdom (panel 21 checks, intake 9 including
blocked `localStorage`); the harness is in the session scratchpad, not the
repo.

## Projects panel inputs for the web form options (landed this session)

`app/templates/admin/panels/projects.html` gained a "Web form languages"
block: default language select, an "offer every active language" switch
(sends `null`) over an available-languages checkbox list, a narration
languages checkbox list (none ticked sends `null`), and a show-guidance
switch. Languages come from `GET /admin/api/languages` (active only),
fetched once at panel init. If that fetch fails the four fields are omitted
from the payload, so a languages outage never blanks a project's settings.
When languages arrive after an Edit form is already open the form is
refilled from the project, not reset to create defaults (a reviewer caught
that race). A stored default that is no longer active renders as
`<code> (inactive)` and Save is blocked with a message naming it; the
server would 400 anyway, with a terser one. The default locale is ticked
into a narrowed list on Save, matching what the resolver does. The PUT's
validation block moved into `_web_intake_form_option_updates` in
`app/routes/admin.py` and the project POST now calls it before constructing
the row, so a bad payload creates nothing. Three POST tests and a render
test cover the Python; the JavaScript was exercised in jsdom (21 checks:
edit fill, stale default, empty restricted list, late-languages race,
languages failure, create) but that harness is not checked in, because the
repo has no JS toolchain. `admin_create_project` still ignores
`coding_intake_mode` and `web_intake_mode` on create (pre-existing; the
panel has always sent them and they take effect on the next edit).

## Closed projects revoke every grant scope (landed this session)

A project with `project_status != active` (that is `deactive` or `pending`)
resolves no grant of any scope for any non-admin role. Grants are not
deleted or status-changed; reopening the project restores them and the
audit trail is untouched. The rule is one expression,
`org_grant_service.active_project_condition`, a correlated EXISTS on
`va_project_master`, applied inside every resolver's own query: seven in
`org_grant_service` and five on `VaUsers`. Everything else that derives
access (`dm_scope_filter` and friends, the organization and web-intake
reachable-unit helpers, the `is_*` role predicates) goes through those
twelve, plus `should_redact_pii`, which the security review caught: a
PII-granting grant on a closed project would otherwise keep switching
redaction off on screens reached through an open project. Its per-scope
subqueries must stay correlated to the grant row; the first draft lost the
correlation and scanned every grant, which eleven dashboard tests caught.
Both mechanisms the task file named now agree because they share the
predicate; a third resolver must use it too. Recorded in `docs/policy/access-control-model.md`, "Closed Projects".

## Migrations may not import application code (landed this session)

Fifteen historical migrations import the analytics MV SQL builders from
`app.services.submission_analytics_mv`; none imports models or enums. They
are pinned by filename and exact import set in
`tests/migrations/test_no_app_imports_in_migrations.py`, which walks every
file under `migrations/versions` with `ast` and fails on any application
import outside the pins, on a pin whose set has grown, and on a stale pin.
Inlining the fifteen was rejected: it would change what a replay executes
on a database that has already run them. The pairing check is the existing
schema-drift test, which builds a throwaway database from the chain alone.
Rule 7 in `docs/policy/migration-chaining.md`.

## form-options endpoint (landed this session)

`GET /api/v1/organization/<project_id>/form-options` serves the tier-2
options from `docs/policy/va-web-form-options.md`, with the same grant check
as `/units`. Four explicit columns on `va_project_master`
(`web_intake_default_locale`, `web_intake_available_locales`,
`web_intake_narration_languages`, `web_intake_show_guidance`; migration
`f2a9c4d7e1b3`, additive, no `app.*` import). `form_types` is derived from
`map_project_site_odk`; `enabled_extensions` is derived from existing flags,
with `intake_screen` and `death_summary` omitted until something can derive
them. The admin project PUT validates the four fields; the projects panel UI
does not expose them yet, because its settings form is built from explicit
element handles and the four inputs are more than a few lines of JS.

The intake template no longer hardcodes `locale="en"`. It sets
`el.instrument` from a map keyed on the form type's `instrument_code`, which
the endpoint now serves: `WHO_2022_VA` for every `WHO_2022_VA*` code. That
follows the product rule stated 2026-09-19: **DigitVA form types are layers
on top of the one standard WHO 2022 instrument, not separate
questionnaires.** `WHO_2022_VA_SOCIAL` renders the base instrument and
`enabled_extensions` says which layers apply. The first cut refused SOCIAL
as unbundled; that reading was wrong and is gone. `instrument_code` is a
naming convention today; when a second standard instrument (PHMRC) is
bundled it becomes a `base_instrument_code` column on `mas_form_types`,
recorded in `docs/policy/va-web-form-options.md`.

## Route decorator guarantee (landed this session)

`role_required` now stamps its wrapper with `__digitva_roles__`, and
`tests/test_route_auth_coverage.py` walks `app.url_map` at runtime, follows
each view's `__wrapped__` chain, and fails on any endpoint that carries
neither that marker nor Flask-Login's `login_required` (detected by code
object, because `functools.wraps` rewrites `__module__` and `__qualname__`
and a name check finds nothing). `hasattr(f, "__wrapped__")` was rejected
as the signal: any `wraps`-based decorator sets it, and the test keeps one
assertion proving unguarded-but-wrapped endpoints still exist so that
rationale stays falsifiable. Positive control registers an unguarded view on
a bare `flask.Flask` and asserts it is reported.

One allowlist, `PUBLIC_BY_DESIGN`, checked for stale entries and for
entries that later became guarded. It holds fifteen endpoints: static,
health, the seven `va_auth` account-access flows (login, logout, maintenance
banner, forgot password, reset link, resend verification, verify email), the
home page (`/`, `/index`, `/vaindex`), the WHO reference documents, and the
four help pages. Decided 2026-09-19: help and WHO documents are public so a
prospective user can read them before logging in; `help.page` keeps its
in-body role filter for role-restricted pages. The home page is public
because the site has a dedicated login page; a `login_required` on `/` was
landed and reverted the same day, so do not put it back.
`tests/routes/test_public_route_access.py` asserts the anonymous behaviour
of each class at runtime.

`API_PATH_PREFIXES` is now a constant on `role_required`, and a test asserts
every `/api/`-shaped rule matches one of its prefixes, closing item 2 of
`.tasks/auth-decorator-followups.md`. Item 3 (`project_pi` is the only
predicate that queries) is still open.

## PII set confirmation (landed this session)

A form type's PII set is **confirmed** when at least one `is_pii` row sits on
a field the form actually owns (`subcategory_code IS NOT NULL OR odk_label IS
NOT NULL OR is_custom = false`). "Zero `is_pii` rows" was never a usable
check: `apply_pii_field_registry` creates three redaction-only rows for every
form type, WHO-shaped or not. Derived from data, so no migration and no
confirm button: an admin confirms a PHMRC form by flagging one of its real
fields in the field-mapping panel.

Unconfirmed fails closed: a plain `collaborator` gets no payload at all on
the submission page, and the submissions CSV export writes the payload
columns empty for every role (it was already PII-filtered for every role).
The admin form-type list, `get_form_type_stats`, the field-mapping panel and
`flask form-types` all show the status.

**One exemption, deliberate:** the SmartVA input export still only strips
flagged fields on an unconfirmed form type, logged as
`pii set unconfirmed | <code> | smartva input export not withheld`. It is a
processing feed reachable only by data managers and admins, and withholding
there would make SmartVA unusable on any new questionnaire. The remaining
fail-open on that path is unchanged from before: a form whose form type
cannot be resolved exports its payload with only the hardcoded omit list
applied. Recorded in `docs/policy/access-control-model.md`.

The PII status cache is keyed on `(count(*), max(updated_at))` of
`mas_field_display_config` for the form type, so an admin edit or Celery-run
sync reaches every worker on its next call. The other mapping caches
(fieldsitepi, choices, labels) are still process-level and cleared only by
`clear_cache()` — a test that mutates a mapping row and renders must clear
them on cleanup, or later tests in the same process render the mutated
build after the savepoint has rolled the row back.

Test database for this tree: `minerva_test_pii` (created this session).

## Open and unexplained

- **The dev DB stamp moved backwards two revisions** with the later migrations'
  data still present. Fixed by re-running `flask db upgrade`; cause unknown.
  A stamp regressing without a downgrade is a data-integrity signal. Likely
  contributor: `boot.sh` retries `flask db upgrade` forever against a DB
  stamped at a revision the tree lacks, hanging silently instead of failing.
  `.tasks/dev-db-stamp-regression-and-infra.md`.
- **Dev and a fresh clone have diverged**: dev's `WHO_2022_VA` carries 2,414
  mappings against a fresh clone's 2,380. That is how a test passes here and
  fails everywhere else.
- **`test_odk_site_mappings`** failed once in a full run with its POST and GET
  each taking 35,118ms to within 3ms. Not reproduced, not explained. The
  identical timings are the fingerprint if it recurs.
- **15 migration files import from `app.*`**, unswept. The `mas_org_unit` break
  came from exactly this.
- **`stash@{0}`** is still present from the incident earlier this week. Not touched by this session; drop it only after someone confirms it holds nothing needed.

## How to work in this repo now

- **One test database per tree.** `TestConfig` honours `TEST_DATABASE_URL`
  above everything. `drop_all` cannot order a table its metadata has never
  seen, so a tree lacking another tree's uncommitted model cannot tear down a
  schema containing it — persistently, not as a race. See
  `docs/policy/test-harness.md`.
- **Shared checkout discipline.** Git read-only unless you are the session that
  owns landing commits; never `stash` (one swept 37 files across four sessions
  this week). Build file lists from `git diff`, never from memory of your own
  edits — in a shared tree the diff is the only source of truth about what a
  commit will contain.
- **Six vacuity rules** are in `docs/policy/test-harness.md`, each from a check
  that passed today while proving nothing: assert the subject is present before
  asserting it is absent; patch the module object, not a dotted path through a
  package that re-exports it; a missing fixture can make an authorization test
  vacuous; defeat the bytecode cache when mutation testing; treat an errored
  `setUpClass` as the whole class unverified; the dual-table FK trap.
- **Migrations chain onto committed revisions only**, verified in `git log`. An
  `origin/main` was broken this week by a revision naming a parent that existed
  only in a working tree. Three migrations named one parent today; each
  re-chained as it landed.

## Known gaps in what was verified

No suite has been mutation-tested except `tests/test_role_required_validation.py`.
The two new ICD CLI commands and migration `c5f2a8d1e9b3` have no automated
test. The intake page's JavaScript is inline in a Jinja template and
structurally untestable — which is why the optional-level reachability bug
lived there undetected. About 27 docs were last updated in March and have never
been checked against the code.
