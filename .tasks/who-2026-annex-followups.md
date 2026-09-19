# Follow-ups from the WHO 2026 annex adoption

- **Status:** pending
- **Priority:** medium (first item is a coding-coverage question, needs the clinical lead)
- **Created:** 2026-09-19
- **Parent:** `.tasks/who-2026-annex-icd10-icd11-review.md` (landed as `3177f8a`)

## Open items

1. **R10 is not selectable, and its bucket contradicts the WHO annex.** The annex puts
   `R10` in VAs-06.01 (Acute abdomen). In `mas_icd10_2019_2` it is `is_coding_selectable=false`,
   the frozen 2026-04-27 workbook and policy have no `R10` row, and the live scheme maps it by
   manual override to "Other Gastrointestinal Diseases", a bucket that is not in the WHO list.
   `WHO_2022_VA_2026` carries that override forward. `docs/policy/who-2022-icd10-coding-allowability.md`
   says `R10` "stays reserved to VAs-06.01"; that is not what the data does. Decide, then fix the
   policy text or the data.
2. **Full annex-vs-policy audit not done.** Only the four ranges that differ between the old extract
   and the 2026 annex were compared. Codes the annex lists that are absent from the policy (like R10)
   in the other ranges were not checked.
3. **The 34 carried-forward manual overrides are undocumented in policy.** Several differ from the
   WHO annex (`G46`->Stroke, `K70`/`K72`/`K73`->Liver cirrhosis, `G47`, `R50`, `R10`). They were kept
   at the user's direction to avoid dropping prior curation, but `docs/policy` does not record them or
   who decided. Clinical lead should confirm each.
4. **Dev DB and a fresh clone differ for the old scheme.** Live `WHO_2022_VA` has 2,414 mappings
   (34 manual overrides, version 3); a fresh clone gets 2,380 from the frozen workbook. Invisible in
   `git status`. Also a cosmetic label drift: live "Pregnancy-, childbirth..." vs frozen
   "Pregnancy, childbirth..." on 86 codes.
5. **No automated test** for the `policy-import` and `import-who-2022-va-2026` CLI commands or for
   migration `c5f2a8d1e9b3` (it was replayed by hand from an empty DB up to that revision only).
6. **`docs/current-state` not updated** (project rule 44): the two new CLI commands and the
   `WHO_2022_VA_2026` scheme are not in `docs/current-state/cli-reference.md` or the data-model doc.
7. **UI copy:** coder panels still label the PDF "Selected ICD-10 Codes"; it now also has ICD-11 columns.
8. **Item 4 (ICD-11 coding integration)** untouched: see `.tasks/icd11-coding-screen-integration.md`.
   Bucket mapping for ICD-11 codes is still a follow-up there.
