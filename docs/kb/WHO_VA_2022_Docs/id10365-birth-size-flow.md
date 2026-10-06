---
title: "WHO 2022 birth weight and size flow (Id10366, Id10363, Id10365) and the Id10365 constraint"
doc_type: reference
status: active
owner: DigitVA Data Collection
last_updated: 2026-10-06
---

# Birth weight and size: flow, relevance and the `Id10365` constraint

Source: WHO's multilingual release `2022whova_xls_form_for_odk_multilingual.xlsx`
(*2022 WHO Verbal Autopsy instrument V2.0*, version `2026081401`), the latest
WHO form in this folder. The V1.1 file (`whova2022_xls_form_for_odk.xlsx`,
version `2023072701`) has the same rows, relevance and constraint for every
question below; nothing in this flow changed between V1.1 and V2.0.

## Who is asked

Only a deceased newborn or infant:

- `isNeonatal` = age at death 0-27 days (`ageInDays <= 27`, or the
  respondent-reported age group "neonate" when dates are missing);
- or `isChild` with `ageInMonthsByYear < 12` (28 days to under one year).

Every adult and every child aged one year or more skips the whole block.

## Flow

```
Id10354  Was the child part of a multiple birth?             (newborn/infant)
   |
Id10366_check  Is the child health card available?              Yes / No
   |
   +-- Yes --> Id10366  Birth weight in grams, from the card     0-9999, required
   |              --> Id10367 (size questions are NOT asked)
   |
   +-- No ---> Id10363  At birth, was the baby smaller than usual
                        (weighing under 2.5 kg)?                  Yes / No / DK / Ref
                  |
                  +-- Yes ---------> Id10367 (Id10365 NOT asked)
                  |
                  +-- No / DK / Ref -> Id10365  At birth, was the baby larger
                                       than usual (weighing over 4.5 kg)?
                                                                  Yes / No / DK / Ref
                                       WHO constraint:
                                       not(Id10363 = No and Id10365 = No)
                                       --> Id10367
   |
Id10367  How many months long was the pregnancy?               (newborn/infant)
```

Relevance as written in the workbook:

| Row | `relevant` | Why it is asked or skipped |
|---|---|---|
| `Id10366_check` | newborn, or infant under 12 months | Routes to the measured weight when a card exists. |
| `g10366` / `Id10366` | the same, and `Id10366_check = yes` | A recorded weight makes the size questions unnecessary. |
| `Id10363` | the same, and `Id10366_check = no` | No card: fall back to the mother's report of size. |
| `Id10365` | `Id10363` is `no`, `dk` or `ref` | Asked only when the baby was not reported small; a small baby cannot also be large. |
| `Id10367` | newborn, or infant under 12 months | Asked whatever the weight path. |

The field interviewer manual (`2022-va-field-interviewer-manual.pdf`, pages
around 50) describes the same flow: card weight if available, otherwise
`Id10363`; if "Yes", skip to `Id10367`; `Id10365` "is to be asked only if the
response to `Id10363` was NO/DK/Ref". It states no rule against answering "No"
to both.

## Why the `Id10365` constraint is wrong

The constraint can fire on one path only: no health card, and the mother
says the baby was **not** smaller than usual (`Id10363 = No`). It then refuses
`Id10365 = No`, "not larger than usual".

"Not small" and "not large" together is a normal-size baby, 2.5 to 4.5 kg: the
most common answer for a live-born infant. With the constraint in place the
interviewer cannot record it and must enter "Yes", "Doesn't know" or
"Refused" for a baby whose size the mother knows, which writes a wrong answer
into an item the cause-of-death tools read (low or high birth weight).

The constraint message ("It is not possible to select 'No weighing under 2.5
kg' and 'No weighing over 4.5 kg' together") reads as if the two were
complementary, but they are two tails of the same scale with a normal range
between them.

No other row in the form reads `Id10363`, `Id10365`, `Id10366` or
`Id10366_check` in a `relevant`, `constraint` or `calculation`, so dropping the
constraint changes nothing else in the flow.

## Deployed forms

All ten deployed site workbooks in this folder (JIPMER, KA01, KEM, KL01,
ML01, ND01, OD01, PY01, RJ01, TR01) carry `Id10365` with **no** constraint.
Only WHO's two reference files have it. Checked 2026-10-06 by reading the
`constraint` column of each `survey` sheet.

## Where DigitVA uses these answers

- Coder and site PI screens show them (`app/utils/va_mapping/va_mapping_02_fieldcoder.py`,
  `va_mapping_01_fieldsitepi.py`, `va_mapping_04_summary.py`: "Weighed under
  2.5 kg at birth", "Weighed over 4.5 kg at birth").
- DORIS prefill takes the card weight `Id10366` (100-9999 g) as the
  certificate's birth weight (`app/services/doris_prefill.py`).
- SmartVA receives the raw answers with the rest of the submission; its own
  mapping of them is inside SmartVA and is not checked here.

## Decision

Owner, 2026-10-06 (bead `digitva-aek`): DigitVA drops this one WHO constraint
in both the web form and the generated ODK form, through the shared
deviations list `resource/who_va_2022_deviations.json`; every other WHO check
is kept. This supersedes the earlier ND01 review line that kept it. The defect
is to be reported to WHO with the `Id10304_a` report (`digitva-0lf7`).
