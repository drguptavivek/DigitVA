# Review WHO 2026 Annex 1 ICD-10 changes and ICD-11 correspondences

- **Status:** items 1-3 done and committed (`3177f8a`); follow-ups in
  `.tasks/who-2026-annex-followups.md`. Item 4 (ICD-11 support) still open, tracked
  separately.
- **Priority:** medium
- **Created:** 2026-09-16
- **Updated:** 2026-09-18
- **Goal:** Decide whether the ICD-10 coding allowability policy and the coder-facing VA codes PDF should be regenerated from the 2026 WHO annex, and whether ICD-11 support is wanted.
- **Plan:** [`docs/planning/icd11-self-hosted-api-and-ect-plan.md`](../docs/planning/icd11-self-hosted-api-and-ect-plan.md) (self-hosted WHO ICD API container plus Embedded Coding Tool; branch `icd-11`)
- **Reference doc:** [`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md`](../docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md)

## Context

The 2026 WHO manual for physician reviewers (Annex 1, Table A1) publishes the
WHO 2022 VA cause list with both ICD-10 and ICD-11 codes. Its ICD-10 column
differs from the earlier extract used in this repo in four places (VAs-98,
VAs-10.99, VAs-99, VAs-12.99). The largest change is VAs-99, which now covers
R00-R09, R11-R94 and R96-R99 instead of R95-R99 only.

The app's ICD-10 coding allowability policy was generated from the earlier
crosswalk workbook and has not been re-derived from the 2026 annex. The app has
no ICD-11 catalog, and nothing in the app reads the new reference files.

## References

- `docs/policy/who-2022-icd10-coding-allowability.md`
- `docs/policy/icd10-reference-catalog.md`
- `docs/icd-causegrp-mappings/migration-artifacts/README.md`
- `app/static/WHO_2022_VA_CODES.pdf` (coder-facing extract, ICD-10 only)
- `docs/kb/WHO_VA_2022_Docs/2026 - pcva_manual-for-physician-reviewers.pdf`

## Expected Scope

1. Compare the reviewed policy JSON with the 2026 annex ICD-10 ranges and list
   the codes whose selectability or WHO bucket would change.
2. Decide with the clinical lead whether to adopt the 2026 ranges. If yes,
   update the policy doc first, then regenerate the policy JSON and bucket
   mapping through the existing generator rather than by hand.
3. Replace or supplement `app/static/WHO_2022_VA_CODES.pdf` with a version that
   carries the 2026 ranges and, if wanted, the ICD-11 column.
4. ICD-11 support is planned in `docs/planning/icd11-self-hosted-api-and-ect-plan.md`:
   self-hosted `whoicd/icd-api` container, `mas_icd11_mms` master with a
   migration plan, Embedded Coding Tool in the coder panels behind an
   authenticated same-origin proxy, and expansion of the annex ranges into
   VA bucket rows. The WHO Simple Tabulation exports (2026-01 and 2025-01
   releases, a development snapshot, and WHO's change list between the two
   releases) are frozen under
   `docs/icd-causegrp-mappings/migration-artifacts/icd11-mms-*/`; the catalog
   is seeded from the release export, not from the API. WHO's ICD-10 to
   ICD-11 mapping tables and ICD-11 mortality tabulation list for the same
   release are frozen beside them for bucket cross-checks and reporting.
   Start with the staging spike in that plan.

## Findings (2026-09-18): Item 1 — code-level diff

Compared against
`docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-04-27/who_2022_icd10_2019_2_policy_reviewed.json`
(the reviewed policy JSON, 2380 rows) and the current bucket mapping in
`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/cod_bucket_scheme_who_2022_va_with_manual_overrides.json`,
using the full ICD-10 hierarchy master
(`docs/icd-causegrp-mappings/migration-artifacts/icd10-2019-base-2026-04-27/icd10_2019_hierarchy.csv`)
to expand the annex's three-character ranges. VAs-12.99's `(S00-T99)` change
is punctuation only — that range is already never-selectable under the
"Never selectable: S00-T99" rule, so it needs no action.

**VAs-98 (Other and unspecified NCD): floor moves from K77 to K70, adds
G43-G47**

- `G43`, `G44`, `G45`, `G46`, `G47` — 5 three-character codes, currently
  entirely absent from the policy (not selectable anywhere). Would become
  newly selectable under VAs-98 if adopted.
- `K72`, `K73`, `K75`, `K76` — 4 three-character codes, currently absent.
  Would become newly selectable under VAs-98.
- `K70`, `K71` — currently NOT selectable at three-character level; only the
  dotted sub-codes `K70.2`, `K70.3`, `K71.7` are selectable, and those are
  already bucketed to VAs-06.02 (Liver cirrhosis), confirmed in the bucket
  mapping. Adopting VAs-98's three-character `K70-K93` range as printed
  would overlap that existing dotted carve-out (this is the overlap the
  annex doc's "Source Irregularities" section already flags). Needs an
  explicit decision: keep the dotted carve-out for VAs-06.02 and add only
  the remaining K70.x/K71.x sub-codes to VAs-98, rather than making whole
  `K70`/`K71` selectable at three-character granularity.
- `K74` — already fully selectable at three-character level, already
  bucketed to VAs-06.02. No change; the annex's wider VAs-98 range does not
  need to (and per the existing VAs-06.02 carve-out, should not) reassign it.

**VAs-99 (Unknown and ill-defined COD): expands from R95-R99 to R00-R09,
R11-R94, R96-R99**

- `R00`, `R01`, `R02`, `R03`, `R04`, `R05`, `R06`, `R07`, `R09` — 8
  three-character codes (R08 does not exist in ICD-10), currently entirely
  absent from the policy. Would become newly selectable under VAs-99.
- `R11`-`R94` minus `R10` (already bucketed to Gastrointestinal disorders /
  VAs-06.01, unaffected) — 77 three-character codes, currently absent.
  Would become newly selectable under VAs-99.
- Total new VAs-99 candidates: 85 three-character ICD-10 codes.
- `R95` (Sudden infant death syndrome) is already selectable today
  (infant-only, both sexes) and is currently bucketed to "Cause of death
  unknown" (old VAs-99). Under the 2026 annex it moves to VAs-10.99
  (perinatal). This is a bucket reassignment, not a new selectability grant.
- `R96`-`R99` are unchanged in both the old and new VAs-99 range.

**Net new selectable-code candidates if the 2026 ranges are adopted:** 5
(G43-G47) + 4 (K72/K73/K75/K76) + a still-to-be-decided partial slice of
K70/K71 + 85 (R00-R09 + R11-R94 minus R10) ≈ **94 three-character codes**,
plus one bucket reassignment (R95: VAs-99 → VAs-10.99).

**Still needed for item 2:** clinical-lead sign-off on (a) adding the ~94
codes above as selectable under VAs-98/VAs-99, (b) the K70/K71
granularity split against the existing VAs-06.02 liver-cirrhosis carve-out,
and (c) moving R95 from the "Cause of death unknown" bucket to VAs-10.99.
Once decided, update `docs/policy/who-2022-icd10-coding-allowability.md`
first, then regenerate the policy JSON and bucket mapping through the
existing generator (not by hand, per that doc's baseline-source note).

## Resolution (2026-09-18): Items 1-2 adopted and landed

Decisions confirmed: adopt the 2026 annex ranges; for the K70/K71 overlap,
keep the VAs-06.02 carve-out (K70.2, K70.3, K71.7, K74) and add only the
remaining K70.x/K71.x sub-codes to VAs-98; move R95 to VAs-10.99. The COD
bucket side was built as a new, coexisting `who_2022_va_2026` scheme rather
than overwriting `who_2022_va`, because the ICD-10 coding-selectability
policy (`mas_icd10_2019_2`) has no per-scheme partition and adopting it is
necessarily a live, global change for every project — so the two parts of
this change have different reversibility: the bucket scheme is fully
reversible (delete/ignore `who_2022_va_2026`), the selectability change is
not (it directly changed what every coder can select).

**Policy doc:** `docs/policy/who-2022-icd10-coding-allowability.md` updated
with a "2026 Annex Adjustments" section and a generalized overlap rule (a
more specific ICD code wins over a broader range it falls inside).

**New frozen artifacts** under
`docs/icd-causegrp-mappings/migration-artifacts/who-2022-va-icd-cod-2026-revision/`:
- `who_2022_icd10_2019_2_policy_reviewed.json` — full-replacement selectability
  policy, 2488 items (2380 baseline + 108 additive: G43-G47, K72/K73/K75/K76,
  13 K70.x/K71.x detailed codes minus the VAs-06.02 carve-out, R00-R09 minus
  R08, R11-R94 minus R10).
- `WHO_2022_VA_Bucket_Mapping_document_derived_2026_revision.xlsx` — source
  workbook for the new `who_2022_va_2026` COD bucket scheme.

**Manual-override discovery, mid-build:** the live `who_2022_va` scheme
(mapping_version=3, 2414 rows) had 34 manual bucket overrides layered on top
of the frozen 2026-04-27 workbook (2380 rows) — real prior clinical curation,
not noise. 7 directly conflicted with a blanket annex-range assignment
(`G46`->Stroke not VAs-98, `G47`->VAs-99 not VAs-98, `K72`/`K73`->Liver
cirrhosis not VAs-98, `K75`/`K76`->"Other Gastrointestinal Diseases" not
VAs-98, `R50`->Unspecified infectious disease not VAs-99). All 34 overrides
were carried into the new workbook/scheme, including 10 codes
(`I11`,`I46`,`I50`,`K64`,`K70`,`R10`,`U07`,`Y91`,`UU1`,`UU2`) that exist only
as bucket-mapping entries — not selectable in `mas_icd10_2019_2` today, and
left that way; only their bucket coverage was replicated, no new
selectability was granted beyond the confirmed annex adoption.

**Code changes:** `app/services/cod_bucket_mapping_service.py` gained
`SCHEME_CODE_WHO_2022_VA_2026` as a scheme coexisting with `WHO_2022_VA`
(same pattern as `SRS_INDIA`/`CMEA10`: default source path, reset-from-source
support, age-band metadata, `import_who_2022_va_2026_scheme`).
`app/commands/cod_buckets.py` gained `flask cod-buckets
import-who-2022-va-2026`. `app/commands/icd10.py` gained `flask icd10
policy-import --path=...` (previously only reachable via the admin API route).

**Landed in the shared dev DB 2026-09-18** (team notified before/after):
`flask icd10 policy-import` (2488 items, 108 updated, 0 reset — nothing
previously selectable was lost) and `flask cod-buckets
import-who-2022-va-2026` (2498 mapping rows). Verified: selectability and
bucket spot-checks for the annex additions and all 34 overrides; the
`who_2022_va` scheme unchanged at 2414 rows; a full code-by-code bucket diff
against `who_2022_va` showed only the intentional R95 move plus a
pre-existing cosmetic label difference ("Pregnancy," vs "Pregnancy-,") already
present in the live scheme before this session touched anything.

**Fresh clones:** migration `c5f2a8d1e9b3` (data-only, idempotent, additive;
chained on committed head `f1c6a9d3e7b5` and must be re-chained onto the final
head when landed) marks the 108 codes selectable and creates `WHO_2022_VA_2026`.
Verified 2026-09-19 inside a rolled-back transaction on the dev DB: re-run on a
populated DB changed nothing; from a simulated-fresh state it produced 108
selectable codes and 2498 mappings; a second run changed nothing. Also run
2026-09-19 as `flask db upgrade c5f2a8d1e9b3` on an EMPTY throwaway database
(`minerva_icd_upgrade_test`, since dropped): the whole chain applied, and the
result was 12,771 ICD rows of which 2,488 selectable (2,380 + the 108), scheme
`WHO_2022_VA_2026` with 2,498 mappings, `WHO_2022_VA` with 2,380. That replay
did not include the two other uncommitted head migrations; re-run after the
final landing order is set. No automated test covers the migration.

**Tests:** two tests added to `tests/services/test_cod_bucket_mapping_service.py`
(coexistence with `WHO_2022_VA`; the real frozen workbook applies the annex
additions, the R95 move, the liver-cirrhosis carve-out and the carried-forward
overrides). Run 2026-09-19 by the shared test runner on `minerva_test`: the three WHO-import tests
passed, the full file passed (28), and `test_icd10_2019_2_service.py` passed (5). The new
tests were not mutation-tested. No test covers the two new CLI commands or migration
`c5f2a8d1e9b3`.

**Committed:** `3177f8a` (2026-09-19). Migration `c5f2a8d1e9b3` re-chained onto `a40c38e73af4` at landing.
Follow-ups: `.tasks/who-2026-annex-followups.md`.

**Still open:** item 4 (ICD-11 catalog / self-hosted API / ECT integration,
tracked separately in `docs/planning/icd11-self-hosted-api-and-ect-plan.md`).

## Resolution (2026-09-18): Item 3 — coder-facing PDF replaced with the WHO source extract

`app/static/WHO_2022_VA_CODES.pdf` and its mirror copy in
`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/WHO_2022_VA_CODES.pdf` were
replaced with a direct 5-page extract (printed pages 79-83, PDF pages 86-90)
of Annex 1 Table A1 from the official WHO source document,
`docs/kb/WHO_VA_2022_Docs/2026 - pcva_manual-for-physician-reviewers.pdf` —
the same pages this session transcribed into
`who_2022_va_cause_list_icd10_icd11.csv` for items 1-2. This carries WHO's
own 2026 ICD-10 and ICD-11 columns verbatim, replacing the earlier
ICD-10-only, pre-2026 extract. Pages were sliced with `pypdf` (a throwaway
host-side venv, not a project dependency).

An earlier attempt in this session regenerated the PDF from the transcribed
CSV via HTML + headless Chrome rather than using the WHO source directly;
that approach was replaced by this direct extract per feedback that the
official source PDF should be used instead of a re-derived rendering.
