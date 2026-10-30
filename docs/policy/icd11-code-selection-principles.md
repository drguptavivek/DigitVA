---
title: ICD-11 Code Selection Principles
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-30
---

# ICD-11 Code Selection Principles

## Purpose

These are the rules for choosing ICD-11 codes on a death certificate and
for the final underlying cause of death (COD). Each rule is grounded in WHO ICD-11. Where DigitVA is narrower or
broader than WHO, the rule says so and gives the DigitVA decision. Software
implements this policy; it is not the source of it.

## Three separate decisions

Coding behaviour comes from three independent decisions. None implies another.

| Decision | Answers | Basis | Where recorded |
| --- | --- | --- | --- |
| Allowability | Which category may be the final underlying cause | WHO 2022 VA annex ranges (owner 2026-09-24), owner additions (decision 5a), widened to every real category (owner 2026-09-27), minus exclusions (principles 9, 11) | `docs/policy/who-2022-icd11-coding-allowability.md` |
| VA cause mapping | Which WHO 2022 VA cause a code counts toward | WHO 2022 VA annex ranges plus owner decisions; first stem of an expression | `docs/policy/icd11-cod-bucket-schemes.md` |
| Expression building | How a stem and its axes become one code | WHO MMS metadata for the pinned release; picker modelled on WHO's DORIS web tool | `docs/kb/doris-certificate-ui-contract.md` |

Allowability started from the VA mapping (the annex) but no longer depends
on it: selectability is independent of the mapping (owner 2026-09-21), and a
selectable code with no VA cause reports as unmapped.

## Basis key

- **(W)** WHO ICD-11 rule. Cited as a section of the ICD-11 Reference Guide
  ("RG", see References), or as an MMS coding note, the WHO mortality rules
  or DORIS documentation.
- **(V)** WHO 2022 Verbal Autopsy instrument, its cause-list annex, or the
  WHO VA physician-review manual. The RG also carries a VA target list (RG
  3.14.14).
- **(D)** DigitVA decision. Rationale and the owner decision id or date as
  recorded in our docs.

"WHO basis not located" means the RG was searched and it was not found. That is
a finding, not a rule.

## Principles

### 0. Two levels: certificate conditions and the final underlying cause

- **Rule.** A condition written on the certificate (Part I and Part II) is
  checked only against WHO ICD-11 terminology: the code or expression must be
  real in the pinned MMS release and agree with its WHO URI. DigitVA's
  allowability policy (principles 7 to 12) applies only to the medical
  officer's final underlying cause, never to certificate conditions.
- **Basis.** (W) The certificate records what the certifier reported; WHO's
  rules (DORIS, RG 2.17 to 2.19) then select the underlying cause, and may
  need conditions such as a chapter 22 injury on the certificate to do so.
  (D) Recorded in the DORIS plan and contracts.
- **Source.** `docs/kb/doris-certificate-ui-contract.md` (processing
  contract); `docs/planning/project-cod-masking-doris-plan.md` (step 3);
  `docs/planning/coder-web-and-api-contracts.md`.

### 1. Stem codes stand alone; extension codes never do

- **Rule.** A selectable entry starts with a stem code. A chapter X extension
  code is only ever added to a stem and is never chosen alone.
- **Basis.** (W) RG 2.8: stem codes can be used alone. RG 2.9: extension codes
  "can never be used without a stem code for statistical purposes".
  RG 2.9 also says an extension can never be first in a cluster.
- **Final codes only.** (D, owner 2026-10-30, `digitva-9cll.12`) A certificate
  condition's stem, and the stem after each `/`, must be a final code: an
  extension alone, or a category with children, is refused at selection with
  422 `INVALID_SELECTION`. Words and picker behaviour:
  `docs/policy/doris-cod-workflow.md`; the checks:
  `docs/current-state/doris-validation-checks.md`.
- **Source.** RG 2.8, 2.9.

### 2. Cluster syntax: `/` joins stems, `&` adds extensions

- **Rule.** `stem/stem` combines stems. `stem&extension` adds detail to one
  stem. Stems come before extensions. Each stem keeps its own `&` extensions
  before the next `/`.
- **Basis.** (W) RG 2.10 and 2.10.2 (rules 2 to 5).
- **Source.** RG 2.10, 2.10.2.

### 3. Which stem is first (primary)

- **Rule.** In a cluster for mortality, the first stem is the one that best
  describes the aetiology. Mortality tabulation keeps that first stem.
- **Basis.** (W) RG 2.10.2 rule 4: for a single retained code, order by
  aetiology. RG 2.18.4 (Step M4): the underlying cause goes first in the
  cluster. The VA cause comes from this first stem (D, see principle 13).
- **Source.** RG 2.10.2, 2.18.4, 2.21.4.

### 4. Required postcoordination

- **Current behaviour.** A category whose WHO postcoordination axis is
  required, for example `FB80.B` pathological fracture with
  `hasCausingCondition`, is not offered alone in the picker. It is completed
  with the required axis. Optional axes may be left empty.
- **Decision status.** Until 2026-10-26 no owner decision recorded this
  strictness. It is neither an allowability rule (`FB80.B` is selectable)
  nor a mapping rule (`FB80.B` alone and `FB80.B` with its causing condition
  map to the same VA cause, by first stem). It came from how the picker reads
  WHO's required flag, modelled on WHO's DORIS web tool.
  **Owner decision 2026-10-26 (`digitva-xmpx`): follow WHO.** The picker
  offers an explicit "Causing condition not known" choice on a required axis,
  which completes the stem alone and is recorded with the final
  (`causing_condition_unknown`).
- **Basis.** WHO: (W) RG 2.10 (table): the causing condition is "mandatory"
  for primary tabulation when known. RG 2.7.2.1: a "code also" category must
  be clustered with its aetiology. Optional detail is marked as additional
  code, if desired.
  (W) Which axes exist and which are required come from WHO's own MMS
  metadata for the pinned release (`requiredPostcoordination`), not from
  DigitVA. WHO's DORIS web tool shows a mandatory-postcoordination
  indicator for such stems; DigitVA's picker follows the same behaviour:
  mandatory axes first, the stem added only when every required axis is
  satisfied (DORIS UI contract; WHO web trace 2026-09-26).
  WHO is softer than the current behaviour: RG 2.7.2.1 and RG 2.21.4
  describe reporting the code alone when the aetiology is unknown, which is
  common in verbal autopsy. The picker does not offer that path.
- **Source.** RG 2.7.2.1, 2.10, 2.21.4; MMS release 2026-01 (axis flag);
  `docs/kb/doris-web-behavior-and-api-trace.md`;
  `docs/kb/doris-certificate-ui-contract.md`.

### 5. Residual categories

- **Rule.** `Other specified` (`.Y`) and `Unspecified` (`.Z`) categories are
  selectable like any other. Use `unspecified` when the source lacks detail.
  Use `other` when the detail is specific but no category exists.
- **Basis.** (W) RG 2.7.5 (and 2.7.3 on NEC/NOS).
- **Source.** RG 2.7.5.

### 6. Do not duplicate a precoordinated concept

- **Rule.** If one stem already holds the concept, use it. Do not rebuild its
  meaning from a less specific stem plus extensions.
- **Basis.** (W) RG 2.10.1 note: postcoordination "must never be used" to
  replicate a precoordinated code.
- **Source.** RG 2.10.1.

### 7. Underlying cause of death: injuries use the external cause

- **Rule.** For an injury or poisoning, the underlying cause is the chapter
  23 external cause. The chapter 22 injury is added as the main injury, not
  chosen as the underlying cause.
- **Basis.** (W) RG 2.18.4 (Step M4), RG 2.19.3.24 (chapter 22 is not used
  as the underlying cause), RG 2.19.5.
  On the certificate a chapter 22 injury is reported as WHO intends
  (principle 0), and DORIS applies Step M4. As the final underlying cause,
  chapter 22 is **not selectable** (owner 2026-10-26, `digitva-kmm2`),
  matching WHO and the ICD-10 rule on `S`/`T` codes. Until 2026-10-26 the
  widening of 2026-09-27 had left it selectable; every chapter 22 category
  mapped to the catch-all `vas_12_99` and lost the transport, fall or
  drowning distinction. With no known mechanism the coder uses an
  unspecified external cause such as `PB6Z`, as DORIS itself assigns.
- **Source.** RG 2.18.4, 2.19.3.24, 2.19.5.

### 8. Ill-defined causes

- **Rule.** Chapter 21 conditions (for example `MH11`, `MH12`, `MG26`) stay
  selectable. WHO ranks them last: they are ignored as underlying cause when
  any well-defined condition is reported.
- **Basis.** WHO: (W) RG 2.17.10 (Step SP7) and RG 3.14.6 list of ill-defined
  conditions; RG 2.21.7 uses `MH14` as the fallback.
  DigitVA: (D) selectable, owner 2026-09-27 ("everything else"), because DORIS
  and the coder may legitimately reach them.
- **Source.** RG 2.17.10, 3.14.6.

### 9. Categories never selectable alone

- **Rule.** Not selectable: chapter 24 (`Q`), chapter 26 (`S`), section V,
  chapter X, and chapter 25 except `RA01`, `RA02`, `RA03`.
- **Basis.**
  - Chapter 24: (W) RG 2.19.3.24 and RG 2.21.8.10: not for primary mortality
    coding or as the underlying cause.
  - Chapter X: (W) RG 2.9 and RG 2.19.3.24 (extension code as underlying
    cause goes to `MH14`).
  - Chapter 25: (W) RG 2.17.1 says WHO may issue special instructions for
    named emergency conditions using chapter 25, and they take precedence.
    Allowing only `RA01`-`RA03` is (D), owner 2026-09-29. `RA01` is also a
    cause in the VA mapping (owner decision 5a, 2026-09-24). Other `RA` codes
    have no recorded WHO mortality instruction (not located in the RG).
  - Chapter 26: RG 3.2.26 calls it a supplementary chapter for optional use.
    A WHO mortality exclusion was not located. (D) not selectable.
  - Section V: RG 3.2.27 describes it as a functioning-assessment set, not
    diseases. A WHO mortality exclusion was not located. (D) not selectable.
- **Source.** RG 2.9, 2.17.1, 2.19.3.24, 2.21.8.10, 3.2.26, 3.2.27.

### 10. Everything else is selectable

- **Rule.** Any other real category may be chosen, whether or not a VA
  cause maps to it.
- **Basis.** (V) The policy was first drafted from WHO's 2022 VA annex ICD-11
  ranges (owner 2026-09-24), with owner additions (decision 5a).
  (D) owner decision 2026-09-27 (`digitva-ddv.6`) widened it to every real
  category: DORIS applies WHO's own selection rules (W, RG 2.17 to 2.19)
  and may return any cause.
  Selectability carries no promise of a VA cause bucket (owner decision 5b,
  2026-09-24, in `docs/policy/icd10-to-icd11-transition.md`).
- **ICD-10 differs on purpose.** ICD-10 projects stay annex-only (2,401
  of 12,771 rows): they have no DORIS, so the annex list is their only check
  that a final is a WHO VA cause code (owner 2026-10-26, `digitva-7pl2`).
- **Source.** RG 2.17 to 2.19; `docs/policy/who-2022-icd11-coding-allowability.md`.

### 11. Stillbirth

- **Rule.** Fetal death uses `KD3B.1` (intrapartum, fresh), `KD3B.0`
  (antepartum, macerated) or, when the timing is not known, `KD3B.Z`
  (owner 2026-10-26, `digitva-kmm2`). The parent `KD3B` is not selectable.
  `KD3B.Z` maps to the Macerated VA cause, as ICD-10 `P95` does.
- **Basis.** WHO: (W) RG 2.21.8.4: `KD3B.Z` is the code when a fetal death has
  no stated cause. RG 2.19.3.24: `KD3B` is not used if another fetal cause is
  known. RG 2.25.4.3: antepartum goes with maceration; intrapartum goes with
  fresh skin. (V) the VA target list (RG 3.14.14) has separate Fresh
  (`VAs-11.01`) and Macerated (`VAs-11.02`) stillbirth causes.
  DigitVA: (D) owner decision 18, 2026-09-25 (`digitva-g2n`): refusing the
  unspecified-timing codes forces every ICD-11 stillbirth into one of the two
  VA causes. `KD3B.1` to Fresh was confirmed by decision 20, 2026-09-29.
  WHO ICD-PM guidance: not consulted, no basis cited.
- **Source.** RG 2.19.3.24, 2.21.8.4, 2.25.4.3, 3.14.14;
  `docs/policy/icd10-to-icd11-transition.md` section 6.

### 12. Sex and age

- **Rule.** For the final underlying cause (and the Step 1 underlying-cause
  pick in masked projects), a sex conflict refuses the code; an age conflict
  warns and is allowed on recorded confirmation (owner 2026-10-26 and
  2026-10-27, `digitva-oh7j`). A DORIS
  Part I immediate-cause line is left to DORIS.
- **Basis.** WHO: (W) RG 2.21.7 and the annex lists RG 3.14.11 (female) and
  3.14.12 (male): check consistency of sex and diagnosis. RG 2.18.4 also says
  to check for age-range limits. WHO lists sex only; a WHO age table was not
  located.
  DigitVA: (D) the category-level sex and age tables (chapter 18 female adult,
  chapter 19 neonate or infant, genital blocks, tetanus `1C15`) were set by the
  owner on 2026-09-24 and 2026-09-29. Part I exemption: (D) owner 2026-10-05,
  because DORIS runs WHO's own check. Warn-on-age: (D) owner 2026-10-26,
  because WHO has no age table and DORIS itself only warns on age and sex
  plausibility; sex stays a hard block as a recording error.
- **Source.** RG 2.18.4, 2.21.7, 3.14.11, 3.14.12;
  `docs/policy/who-2022-icd11-coding-allowability.md` ("Sex and age").

### 13. One expression, validated whole; the primary stem drives policy and VA cause

- **Rule.** A combined expression is validated as a whole against WHO. The
  allowability check and the VA cause use the primary stem: the causing
  condition when WHO's codeinfo reports one for the expression
  (`hasCausingCondition`), otherwise the first stem. Extensions never change
  the VA cause (owner 2026-10-26, `digitva-443q`).
- **Why.** WHO's picker form puts the manifestation first (`FB80.B/2F9Z`);
  codeinfo returns `hasCausingCondition: ["2F9Z"]` for it, and DORIS selects
  `2F9Z` (a neoplasm) as the underlying cause. Mapping by the first stem gave
  `FB80.B`'s `vas_98` instead of the neoplasm cause.
- **Basis.** Whole validation: WHO RG 2.10.1 says tools should embed the
  instructions; how DigitVA checks is (D). First stem: (W) principle 3 for
  ordering, and (V) RG 3.14.14 codes a death to one cause label. Choosing the
  first stem as the VA cause is (D), consistent with
  `docs/policy/icd11-cod-bucket-schemes.md`.
- **Source.** RG 2.10.1, 2.10.2, 3.14.14.

### 14. Uncoded "window" entities are not offered as axis choices

- **Rule.** An axis value that is an uncoded grouping is not offered as a
  choice. Its coded descendants remain reachable.
- **Basis.** RG 1.6.2 describes a window as a grouping with no primary
  children, no terms and no residual categories, created for display.
  Whether a window has no code is not stated there. Not offering it is (D),
  `digitva-cth7`, because nothing codable can be saved from it.
- **Source.** RG 1.6.2.

## Where DigitVA narrows (or widens) WHO

| Point | Basis | Rationale |
| --- | --- | --- |
| Required axis must be filled (picker) | W (owner 2026-10-26) | Follow WHO: the stem may stand alone when the causing condition is not known (RG 2.7.2.1, 2.21.4); the picker offers "Causing condition not known" (`digitva-xmpx`). |
| Allowability applies to final cause only | D | Certificate conditions are checked against WHO terminology only (DORIS contracts). |
| Certificate stem must be a final code | D | Owner 2026-10-30: WHO objects to a category (BER-CE-10) or an extension alone (FER-CE-883) only after processing; the picker and selection-check refuse it first. |
| Chapters 24, 26, V, X not selectable | W (24, X), D (26, V) | Chapter 24 and X are WHO-excluded; 26 and V are not diseases or are optional. |
| Chapter 25 only `RA01`-`RA03` | D | Owner 2026-09-29; WHO uses ch. 25 only by special instruction. |
| `KD3B`, `KD3B.Z` refused | D | Owner decision 18, 2026-09-25: force fresh or macerated VA cause. |
| ICD-11 wider than ICD-10 (annex-only) | D | DORIS may return any real cause; ICD-10 has no DORIS, so the annex list stays its check (owner 2026-10-26, `digitva-7pl2`). |
| Chapter 22 and ill-defined selectable as final cause | D | Owner 2026-09-27: DORIS may reach any real cause; on the certificate they are WHO-normal. |
| Sex and age tables per category | D on W | WHO lists sex only; age tables are owner decisions 2026-09-24, 2026-09-29. Sex blocks, age warns (owner 2026-10-26, `digitva-oh7j`). |
| DORIS Part I exempt from the local check | D | Owner 2026-10-05: WHO's DORIS check suffices. |
| First stem is the VA cause | D | Aetiology-first ordering is WHO's; the VA use is ours. |

## References

- ICD-11 Reference Guide (HTML): https://icdcdn.who.int/icd11referenceguide/en/html/index.html
- ICD-11 Reference Guide (PDF): https://icdcdn.who.int/icd11referenceguide/en/refguide.pdf
- Requested entry URL https://icd.who.int/icd11refguide/en/index.html returned
  404 when checked on 2026-10-26.
- ICD-11 MMS browser: https://icd.who.int/browse/latest-release/mms/en
- WHO Verbal Autopsy: https://www.who.int/standards/classifications/other-classifications/verbal-autopsy-standards-ascertaining-and-attributing-causes-of-death-tool

Implementers: see `docs/policy/who-2022-icd11-coding-allowability.md` and
`docs/current-state/doris-cod-workflow.md`.
