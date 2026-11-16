# InterVA2022 and InSilicoVA2022 as experimental algorithms

- Status: exploration done, not started (needs owner go)
- Priority: P3 (under `digitva-13gs`)
- Created: 2026-10-30
- Goal: run the openVA team's WHO-2022 pre-release InterVA and InSilicoVA on
  web-platform submissions as "algorithm suggestions" next to SmartVA, never
  authoritative.

## Upstream (checked 2026-10-30)

| Repo | Last commit | What it is | Runtime |
| --- | --- | --- | --- |
| verbal-autopsy-software/InterVA2022 | 2025-08-29 | R package `InterVA2022Prerelease` 0.0.999, ~450 lines of plain R, per-record | R >= 4.4, no Java, no compilation |
| verbal-autopsy-software/InSilicoVA2022 | 2025-08-29 | R package `InSilicoVA2022Prerelease` 0.0.999, MCMC, bundles `Insilico.jar` | R >= 4.0 + rJava + Java >= 7; depends on CRAN `InterVA5`, `InSilicoVA`, `coda`, `ggplot2` |
| verbal-autopsy-software/probbase2022 | 2025-08-29 | probbase "V1 20250829" (343 x 71); identical copy is bundled in both packages | data only |
| verbal-autopsy-software/pyCrossVA | 2026-02-23 | ODK -> indicator mapping, has `2022WHOv0101 -> InterVA_2022 / InSilicoVA_2022` | Python, pandas |

All four are GPL-3. All three 2022 repos say pre-release, untested,
unvalidated and unsupported. The PyPI `interva` port is WHO-2016 (InterVA5)
only, so it cannot replace R for the 2022 instrument.

## Inputs and outputs

- Input: 343 columns `ID, i004a ... i446o`, values `y` / `n` / `.`; the last
  column must be `i446o`. Priors per run: HIV, malaria **and COVID**, each
  `h` / `l` / `v` (the bead names only HIV and malaria).
- InterVA2022 output per record: top 3 causes with likelihoods, `INDET`,
  `PREGSTAT` / `PREGLIK`, and optionally the full probability vector.
- Cause list (`causetext2022`): 64 causes `b_0101 ... b_1299` (WHO 2022 VA
  cause codes, for example b_0108 COVID-19) plus 3 pregnancy states. Mapping to
  the platform's WHO buckets and ICD-11 display is separate work.
- Version to record in run metadata: `probbase2022[1, 3]`.

## Fit with the platform

- Mapping: pyCrossVA crops input columns by suffix regex
  (`configuration.py:400`), so flat `Id10xxx` payload keys work. All 252 plain
  source fields of the InterVA_2022 mapping (including `ageInYears`,
  `age_adult`, `age_child_years`, `age_neonate_days`, `isNeonatal`) are present
  in a sample of 300 dev payloads.
- Trial run 2026-10-30 (see "Trial on dev data" below) confirmed the mapping
  works end to end.
- InterVA2022 is per record and fits the SmartVA pattern: batch per form,
  group by priors (extend `group_sids_by_run_options` with COVID), PII scrub
  (`_clean_payload_for_smartva`), `SMARTVA_BLOCKED_WORKFLOW_STATES`,
  `payload_version_id` staleness, run and form-run records, Redis coalescing.
- InSilicoVA is a population model: individual causes come from one joint MCMC
  fit over the batch (default Nsim 4000, burn-in 2000), so a case's result
  depends on which other cases are in the batch. It does not fit the
  per-submission 30 s sweep. Run it as a scheduled per-project (or
  per-period) batch, and store the batch id with every result.
- Nothing is generic today: tables, services and templates are all
  `va_smartva_*`. New algorithms need either an `algorithm` column on new
  `va_algo_*` tables or their own tables.

## Trial on dev data (2026-10-30)

400 dev submissions (active payload versions, only the 252 mapped symptom
fields exported), local R 4.x on macOS, scratchpad only, nothing in the app.

- pyCrossVA `2022WHOv0101 -> InterVA_2022`: 400 x (ID + 342), 0.3 s; columns
  in exact probbase order. About 4 % `y`, 28 % `n`, 68 % missing.
- InterVA2022 (HIV/malaria/COVID all `l`): 0.2 s for 398 records. 2 records
  were skipped because they have no sex and no age, which the algorithm
  requires (record this as a failed outcome, not a silent drop). 62
  indeterminate.
- InSilicoVA2022 (Nsim 4000, burn-in 2000, thin 10, `-Xmx2g`): 9-11 s for 400.
  It warned that not all causes with CSMF > 2 % converged; the trial set
  `auto.length = FALSE`, so the chain was not extended as the default would.
  A real run should use the defaults. It also warned that the data
  consistency check now runs "outside InSilicoVA" (no WHO-2022 check exists in
  InterVA5's `DataCheck5`; we would have to supply one).
- Agreement on the platform's WHO 2022 VA (2026 revision) buckets. The
  final cause is `authoritative_who_bucket` / `_section` from
  `va_submission_cod_snapshot_mv`, and SmartVA is `smartva_cause1_who_bucket`
  from the same view. Algorithm cause `b_XXYY` maps to bucket `vas_XX_YY`
  (`b_9800` -> `vas_98`), one to one. Indeterminate counts as "Cause of
  death unknown", as the view does for SmartVA. 365 records have a final
  bucket and all three results; 307 of them have a final cause other than
  unknown.

  | Algorithm | Same bucket (all 365) | Same bucket (307 known) | Same section (307 known) | Algorithm "unknown" |
  | --- | --- | --- | --- | --- |
  | SmartVA | 42 % | 36 % | 53 % | 119 |
  | InSilicoVA2022 | 20 % | 24 % | 53 % | 0 |
  | InterVA2022 | 19 % | 21 % | 41 % | 58 |

  The "all" column credits unknown-vs-unknown matches, which flatters
  SmartVA; the "known" columns are the fair comparison. Of the 48 external
  deaths, the section matched for SmartVA in 36, InSilicoVA2022 in 41 and
  InterVA2022 in 14 (32 indeterminate, the `i098o` defect below).
  InterVA2022 and InSilicoVA2022 give the same bucket in 197 of 307.
  Script: `agree_buckets.py` in the session scratchpad; not in the repo.
- The final cause is set after the coder has seen SmartVA, so it favours
  SmartVA. Against the coder's step-1 cause (entered with SmartVA hidden,
  `routes/va_form.py:887`): underlying = step-1 antecedent, else immediate.
  ICD-10 is mapped to a bucket by looking it up in the code -> bucket pairs
  the snapshot view already resolved; a 3-character code is used only when
  all its subcodes share one bucket. 363 of 364 resolved (one `O69` did not).

  | Algorithm | Same bucket (all 363) | Same bucket (310 known) | Same section (310 known) |
  | --- | --- | --- | --- |
  | SmartVA | 37 % | 32 % | 51 % |
  | InSilicoVA2022 | 20 % | 23 % | 54 % |
  | InterVA2022 | 19 % | 21 % | 42 % |

  Step 1 and final share a bucket in 273 of 310. Of the 37 that changed, the
  final moved to SmartVA's bucket in 19, against 3 where step 1 already
  matched SmartVA: the anchoring is visible. Against step 1, InSilicoVA2022
  edges SmartVA at section level; SmartVA still leads at bucket level.
  Script: `agree_step1.py` in the session scratchpad.

## Full dev run (2026-10-30)

All 8,617 submissions with an active payload (synthetic demos excluded),
same export filter. pyCrossVA 1.5 s. InterVA2022 4.6 s: 8,477 assigned,
140 skipped (no age or sex), 1,226 indeterminate. InSilicoVA2022 with
defaults (`auto.length` on, `-Xmx8g`): 446 s, extended to 8,000 iterations,
still "not all causes with CSMF > 2 % convergent".

Against the step-1 cause (7,833 resolved, 6,405 known; 46 step-1 entries
did not resolve, e.g. F17, R64, J99*, free-text "Pneumonia"):

| Algorithm | Same bucket (all) | Same bucket (known) | Same section (known) |
| --- | --- | --- | --- |
| SmartVA | 42 % | 36 % | 52 % |
| InSilicoVA2022 | 20 % | 25 % | 52 % |
| InterVA2022 | 20 % | 21 % | 42 % |

Against the final cause (6,436 known): SmartVA 40 % / 55 %, InSilicoVA2022
26 % / 54 %, InterVA2022 22 % / 43 % (bucket / section). Step 1 and final
differ in 730 of 6,405; in 372 the final moved to SmartVA's bucket (83 where
step 1 already matched SmartVA).

External deaths (872 final): section matched by InSilicoVA2022 714,
SmartVA 635, InterVA2022 161 (623 indeterminate: defect 1).

InSilicoVA2022 "Breast neoplasms": 594 deaths (5.7 % CSMF), 341 male, only
24 with a breast lump (`i294o`); coders put 196 of them in "Cause of death
unknown". It looks like low-information records are being absorbed into
b_0204; this is systematic, not a small-batch artefact.

### Defects to raise with the openVA team (Dr Li)

1. probbase V1 20250829, row `i098o` "Was the injury accidental?": `N` (never)
   for every external cause except b_1299 (`N N N N N N N N N N I`), the same
   pattern as the row above it, `i097o` "any other injury". The 2016
   probbase (v19 20210720) has `A` for every accidental cause and `N` only for
   self-harm and assault. It looks copied from `i097o`. An accidental
   road-traffic death (`i079o=y`, `i098o=y`) therefore zeroes every cause in
   InterVA2022, giving indeterminate. 32 of the coder-certified injury deaths
   in the trial hit this; dropping `i098o`, `i079o`, `i083o` or `i082o`
   restores a result.
2. Same probbase, row `i082o` "non-road transport injury": `N` for every
   external cause, including b_1202 "Other transport accident" (2016: `I`).
   More broadly, the 2022 injury-mechanism rows are hard `N` off the matching
   cause (2016 used graded levels), so any two mechanisms answered yes also
   zero every cause.
3. InSilicoVA2022 assigned "Breast neoplasms" to 30 deaths, 17 of them male,
   none with a breast lump (`i294o`); coders mostly certified I21. The
   probbase allows males (P(female | b_0204) = `A`). The full run (594
   deaths, 341 male, 24 with a lump, defaults, 8,000 iterations) shows it
   is systematic: likely sparse records drifting to b_0204.

InSilicoVA2022 avoids defect 1 because it assigns external causes by its
own rule before the model (`external.sep = TRUE`).

## Recommended shape

1. Runner outside the app image (bead: "R in its own container"): one image
   with R, InterVA2022, InSilicoVA2022 (+ Java), and pyCrossVA. CSV in, CSV
   out. This also keeps GPL-3 code out of the MIT app process (owner to
   confirm the licence position).
2. App side: export the PII-free payload subset, call the runner, store the
   results in new tables keyed by `va_sid`, `payload_version_id`, algorithm,
   algorithm and probbase version, and mapping version.
3. Show both results only to coders, after their own coding (like SmartVA),
   labelled "experimental, unvalidated".
4. InterVA2022 first (simplest runtime); InSilicoVA2022 after, as a batch
   mode. Do not show InterVA2022 to coders until defect 1 is fixed upstream:
   it makes injury deaths indeterminate. Patching the probbase locally (the
   `sci` argument) is possible but should be the openVA team's call.

## Open questions for the owner

- Licence position for GPL-3 code alongside the MIT app and in published images.
- Where the runner lives: an app-side container or the support-model host
  (Mac mini or Linux GPU box) from the bead.
- Per-project HIV, malaria and COVID priors, and their defaults.
- Whether to tell Dr Li (JHU/openVA) we are trialling the pre-release, and
  whether to feed agreement data back.

## References

- Bead `digitva-13gs` (InterVA5 + EAVA, InSilicoVA later).
- `app/services/smartva_service.py`, `app/utils/va_smartva/va_smartva_02_prepdata.py`,
  `app/tasks/sync_tasks.py:2284`, `app/models/va_smartva_*.py`.
- `docs/policy/smartva-generation-policy.md`, `docs/policy/narrative-ai-processing.md`.
