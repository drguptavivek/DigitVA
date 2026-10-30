# clinical-variants-10k

DigitVA's earlier DORIS test suite, made by the DigitVA team on 2026-10-24 (`ICD11-DORIS-kotlin-rust-source.zip`, `icd-offline-0.3`,
`tests/fixtures`). 250 clinical scenario families, each in 40 challenge variants (10,000 certificates), over 5 cohorts of 50 families
each (adult, elderly, children, neonates, pregnancy), with 272 distinct ICD-11 codes in the proposed cause chains. Plus 10 edge cases.

| file | content |
| --- | --- |
| `inputs_all.jsonl.gz` | the 10,000 variant inputs: family, cohort, variant, challenge description, proposed chain, and the certificate in `submission` |
| `edge_inputs.jsonl.gz` | 10 erroneous or unusual certificates (`EDGE_0` to `EDGE_9`) |
| `oracle_results.jsonl.gz` | reference outputs for the 10,000 inputs, produced by the team with DORIS rules 1.2.1 |
| `edge_oracle.jsonl.gz` | reference outputs for the 10 edge cases |
| `hashes.json` | sha256 of the four plain (unpacked) files; all four were checked against the gzipped copies |

Each file is gzip -9n of the original. `build_inputs.py` reads `inputs_all.jsonl.gz` and `edge_inputs.jsonl.gz` and checks the unpacked bytes
against the pinned hashes. The parity runs do not use the oracle files: the WHO container is the reference there. The oracle is from DORIS
rules 1.2.1, not the 1.1.176 engine the parity runs use, so it is not expected to match them.

Caveats:

- Every certificate is marked `pending_expert_adjudication`: no clinician has judged the cause chains, and many variants are deliberately
  implausible (`minor_condition_as_underlying`, `male_pregnancy_contradiction`, `onset_before_birth`).
- 2,200 certificates carry `FetalOrInfantDeath.BirthWeight`, which WHO's DORIS draft-06 schema does not allow.
- `disease_category` labels are inconsistent in case.
- The inputs hold no WHO material beyond ICD codes and titles.

## The 42 variant names

A family carries 40 of these (six names are not used for every family). `variant_index` is the number.

| # | variant | challenge |
| --- | --- | --- |
| 0 | `baseline_proposed_chain` | Unmodified synthetic proposed certificate; clinical adjudication pending. |
| 1 | `reversed_chain` | Reverse the submitted cause sequence; no claim that the engine must reject it. |
| 2 | `top_pair_swap_missing_intervals` | Swap the first two causes and remove their interval fields; combined challenge. |
| 3 | `immediate_cause_omitted` | Remove the first cause; for one-cause certificates this removes all Part I causes. |
| 4 | `underlying_cause_omitted` | Remove the final cause; singleton fallback moves it to Part II without its interval. |
| 5 | `underlying_in_part2` | Move the proposed underlying cause from Part I to Part II. |
| 6 | `causes_same_line` | Place the causes together on one line; singleton includes an unrelated minor condition. |
| 7 | `same_line_reversed` | Reverse conditions within one line; singleton minor condition precedes the cause. |
| 8 | `blank_part1_line` | Insert a blank line before the final cause. |
| 9 | `underlying_repeated` | Repeat the final cause on another Part I line. |
| 10 | `immediate_repeated_same_line` | Repeat the immediate cause within its line. |
| 11 | `minor_condition_as_underlying` | Substitute myopia as the final antecedent: deliberately implausible fatal attribution. |
| 12 | `terminal_mechanism_only` | Retain only unspecified cardiac arrest; no etiologic disease or external cause. |
| 13 | `terminal_mechanism_added` | Add unspecified cardiac arrest to the top cause line. |
| 14 | `intervals_unknown` | Set every Part I interval to an empty string. |
| 15 | `interval_order_reversed` | Reverse onset-to-death intervals; singleton uses zero seconds. |
| 16 | `intervals_identical` | Give all Part I conditions the same short interval; not automatically clinically invalid. |
| 17 | `onset_before_birth` | Give the antecedent an onset-to-death interval exceeding the stated age. |
| 18 | `duration_text_invalid` | Use non-ISO duration text for one condition. |
| 19 | `sex_unknown` | Set certificate Sex to 9, meaning unknown. |
| 20 | `sex_missing` | Omit the Sex field. |
| 21 | `recorded_sex_flipped` | Flip the recorded sex; a true sex/cause contradiction only for relevant sex-specific conditions. |
| 22 | `male_pregnancy_contradiction` | Record Sex=1 together with affirmative maternal pregnancy fields. |
| 23 | `age_missing` | Omit birth date and estimated age; retain the death date. |
| 24 | `age_as_dates` | Represent age using birth/death dates instead of EstimatedAge. |
| 25 | `birth_after_death` | Supply a birth date later than the death date. |
| 26 | `conflicting_age_fields` | Supply dates and an incompatible EstimatedAge. |
| 27 | `major_part2_competitor` | Add a major competing condition to Part II. |
| 28 | `minor_part2_condition` | Add myopia to Part II; test handling of an unrelated minor condition. |
| 29 | `manner_cause_conflict` | Change manner to disease for injury families or assault for disease families. |
| 30 | `external_ancillary_missing` | Omit the MannerOfDeath structure, even if injury codes remain. |
| 31 | `recent_surgery_recorded` | Add recent surgery information without changing the coded sequence. |
| 32 | `surgery_after_death` | Record a surgery date after the date of death. |
| 33 | `autopsy_findings_without_request` | Record findings used despite autopsy not requested. |
| 34 | `autopsy_requested_findings_used` | Record autopsy requested and findings used; classification sensitivity probe. |
| 35 | `maternal_unknown` | Set all maternal fields to unknown. |
| 36 | `maternal_timing_alternative_a` | Change the pregnancy timing category, with female recorded sex. |
| 37 | `maternal_timing_alternative_b` | Use another pregnancy timing category, including beyond one year in some cases. |
| 38 | `stillbirth_livebirth_conflict` | Set Stillborn=1 despite the synthetic liveborn/older-person history. |
| 39 | `gestation_weight_conflict` | Record 20 gestational weeks and 4500 g; neonatal physiology or age-context challenge. |
| 40 | `manner_unknown` | Set manner to unknown. |
| 41 | `surgery_unknown_with_date` | Record unknown surgery status but provide a surgery date. |
