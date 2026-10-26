---
title: ICD-11 Code Selection Principles
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-26
---

# ICD-11 Code Selection Principles

## Purpose

These are the rules for choosing ICD-11 codes on a death certificate and
for the final underlying cause of death (COD). Each rule is grounded in WHO ICD-11. Where DigitVA is narrower or
broader than WHO, the rule says so and gives the DigitVA decision. Software
implements this policy; it is not the source of it.

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

- **Rule.** A category whose WHO postcoordination axis is required, for
  example `FB80.B` pathological fracture with `hasCausingCondition`, is not
  chosen alone. It is completed with the required axis. Optional axes may be
  left empty.
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
  Note for review: RG 2.7.2.1 and RG 2.21.4 describe reporting the code
  alone when the aetiology is unknown. The picker does not offer that path.
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
  (principle 0), and DORIS applies Step M4. For the final underlying cause,
  chapter 22 is not on the never-selectable list (D, owner 2026-09-27,
  rule 4 of the allowability policy). The ICD-10 side keeps the
  injury-nature `S`/`T` codes unselectable as final causes, per
  `docs/policy/who-2022-icd10-coding-allowability.md`.
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
- **Basis.** (D) owner decision 2026-09-27 (`digitva-ddv.6`): DORIS applies
  WHO's own selection rules (W, RG 2.17 to 2.19) and may return any cause.
  Selectability carries no promise of a VA cause bucket (owner decision 5b,
  2026-09-24, in `docs/policy/icd10-to-icd11-transition.md`).
- **Source.** RG 2.17 to 2.19; `docs/policy/who-2022-icd11-coding-allowability.md`.

### 11. Stillbirth

- **Rule.** Fetal death uses `KD3B.1` (intrapartum, fresh) or `KD3B.0`
  (antepartum, macerated). `KD3B` and `KD3B.Z` are not selectable.
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

- **Rule.** A category limited by sex or age is refused when the deceased
  does not fit. A DORIS Part I immediate-cause line is left to DORIS.
- **Basis.** WHO: (W) RG 2.21.7 and the annex lists RG 3.14.11 (female) and
  3.14.12 (male): check consistency of sex and diagnosis. RG 2.18.4 also says
  to check for age-range limits. WHO lists sex only; a WHO age table was not
  located.
  DigitVA: (D) the category-level sex and age tables (chapter 18 female adult,
  chapter 19 neonate or infant, genital blocks, tetanus `1C15`) were set by the
  owner on 2026-09-24 and 2026-09-29. Part I exemption: (D) owner 2026-10-05,
  because DORIS runs WHO's own check.
- **Source.** RG 2.18.4, 2.21.7, 3.14.11, 3.14.12;
  `docs/policy/who-2022-icd11-coding-allowability.md` ("Sex and age").

### 13. One expression, validated whole; first stem drives policy and VA cause

- **Rule.** A combined expression is validated as a whole against WHO. The
  allowability check and the VA cause use the first stem. Extensions and later
  stems never change the VA cause.
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
| Required axis must be filled | W (MMS flag, DORIS web tool) | Follows WHO's required flag and WHO's DORIS tool; RG 2.7.2.1 alone-when-unknown path not offered (for review). |
| Allowability applies to final cause only | D | Certificate conditions are checked against WHO terminology only (DORIS contracts). |
| Chapters 24, 26, V, X not selectable | W (24, X), D (26, V) | Chapter 24 and X are WHO-excluded; 26 and V are not diseases or are optional. |
| Chapter 25 only `RA01`-`RA03` | D | Owner 2026-09-29; WHO uses ch. 25 only by special instruction. |
| `KD3B`, `KD3B.Z` refused | D | Owner decision 18, 2026-09-25: force fresh or macerated VA cause. |
| Chapter 22 and ill-defined selectable as final cause | D | Owner 2026-09-27: DORIS may reach any real cause; on the certificate they are WHO-normal. |
| Sex and age tables per category | D on W | WHO lists sex only; age tables are owner decisions 2026-09-24, 2026-09-29. |
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
