# Follow-ups from the WHO 2026 annex adoption

- **Status:** pending (items 1, 3 and 8 closed; 2 moved; 4-7 to be filed as beads)
- **Priority:** medium
- **Created:** 2026-09-19
- **Updated:** 2026-09-19
- **Parent:** `.tasks/who-2026-annex-icd10-icd11-review.md` (landed as `3177f8a`)

## Open items

1. **R10 — confirmed by the clinical lead 2026-09-19.** `R10` is selectable (both sexes,
   all ages) and bucketed to VAs-06.01 Acute abdomen in `WHO_2022_VA_2026`, via the artifacts read by
   migration `c5f2a8d1e9b3` (policy JSON 2,489 items / 109 added codes; workbook R10 row changed). The old
   `WHO_2022_VA` scheme still maps `R10` to "Other Gastrointestinal Diseases"; that override was not carried.
   Recorded in `docs/policy/who-2022-icd10-coding-allowability.md`, section
   "Carried-forward overrides in WHO_2022_VA_2026".
2. **Full annex-vs-policy audit — moved into the ICD-11 policy-generator work.** The generator
   diffs the annex ICD-10 column against the reviewed policy JSON and reports every code present in
   one and absent from the other, for the clinical lead's review. Report only: no mapping or
   selectability change without sign-off. Tracked with the generator, not here.
3. **Done — the carried-forward overrides are documented in policy.** See
   `docs/policy/who-2022-icd10-coding-allowability.md`, section "Carried-forward overrides in
   WHO_2022_VA_2026": a table of the 16 of the 33 carried-forward overrides whose bucket differs
   from the annex-derived bucket (`G46`, `G47`, `I11`, `I46`, `I50`, `K64`, `K70`, `K72`, `K73`,
   `K75`, `K76`, `R50`, `U07`, `Y91`, `UU1`, `UU2`), each with the bucket kept, the bucket the annex
   gives and the clinical lead's 2026-09-19 keep decision. The other 17 carried-forward rows agree
   with the annex. `tests/test_icd10_2026_overrides_doc.py` recomputes the set from the checked-in
   artifacts and asserts the table matches.
4. **Dev DB and a fresh clone differ for the old scheme.** Live `WHO_2022_VA` has 2,414 mappings
   (34 manual overrides, version 3); a fresh clone gets 2,380 from the frozen workbook. Invisible in
   `git status`. Also a cosmetic label drift: live "Pregnancy-, childbirth..." vs frozen
   "Pregnancy, childbirth..." on 86 codes.
   beads: `digitva-2g7`.
5. **No automated test** for the `policy-import` and `import-who-2022-va-2026` CLI commands or for
   migration `c5f2a8d1e9b3` (it was replayed by hand from an empty DB up to that revision only).
   beads: `digitva-28a`.
6. **`docs/current-state` not updated** (project rule 44): the two new CLI commands and the
   `WHO_2022_VA_2026` scheme are not in `docs/current-state/cli-reference.md` or the data-model doc.
   `cli-reference.md` is done as of 2026-09-19; the data-model doc still needs the scheme.
   beads: `digitva-jt3`.
7. **UI copy:** coder panels still label the PDF "Selected ICD-10 Codes"; it now also has ICD-11 columns.
   beads: `digitva-2c1`.
8. **Item 4 (ICD-11 coding integration) — decisions recorded.** See
   `docs/planning/web-capture-project-configuration-plan.md` (decisions table and WP5) and
   `.tasks/icd11-coding-screen-integration.md`. Bucket mapping for ICD-11 codes remains a follow-up
   there.
