---
title: "Translated labels that display another question's code"
doc_type: reference
status: active
owner: DigitVA Data Collection
last_updated: 2026-09-20
---

# Translated labels that display another question's code

WHO question labels carry their own code as a visible prefix — `(Id10192) Was
the vomit black?`. In 34 translated labels the code shown is **not** the code
of the question the row belongs to. Found 2026-09-20 by reading the Hindi web
form, not by a test: no test compares a label's text against the question it is
attached to, because until the browser intake was exercised nothing read a
label the way an interviewer does.

All 34 are `source='imported'`, so they arrived from the source workbooks
listed in `docs/policy/va-form-project-configuration.md`. None originate in
DigitVA.

**These are not one problem.** They divide into three classes by consequence,
and only the third is a data-integrity issue.

## Class 1 — case only (11 rows, harmless)

The question's own name is lowercase; the label capitalises it.

| Locales | Row | Displays |
| --- | --- | --- |
| ar, bn, kn, mr, or, sw, ta | `id10161_unit` | `(Id10161_unit)` |
| bn, es, kn, mr | `id10120_unit` | `(Id10120_unit)` |

Nothing resolves this code, and a reader would not notice. No action needed.

## Class 2 — a code that is not any question (10 rows, cosmetic)

The text is the question's own; the bracketed code is mistyped.

| Locale | Row | Displays | Slip |
| --- | --- | --- | --- |
| hi, kn, mr | `Id10010` | `(Id100010)` | extra `0` |
| kn, mr, or, ta | `Id10282` | `(Id0282)` | missing `1` |
| sw | `Id10167_units` | `(Id10167_unit)` | missing `s` |
| hi | `Id10322_a` | `(Id10322)` | parent's code |
| or | `mother_deliv` | `(Id10386)` | ODK-only name, not in our instrument |

An interviewer sees a wrong number next to the right question. Worth fixing,
not urgent.

## Class 3 — another question's text (serious, needs a speaker's review)

Here the row carries **the neighbouring question's wording**. The interviewer
reads one question; the answer is recorded against a different one. Verified by
comparing the translated text's meaning against both English labels:

| Locale | Row (what is answered) | Text actually shown | Status |
| --- | --- | --- | --- |
| or | `Id10192` "Was the vomit black?" | `Id10191` "Was there blood in the vomit?" | **confirmed wrong** |
| or | `Id10194` "Did (s)he have abdominal pain?" | `Id10192` "Was the vomit black?" | **confirmed wrong** |
| or | `Id10195` "Was the abdominal pain severe?" | `Id10194` "Did (s)he have abdominal pain?" | **confirmed wrong** |
| kn | `Id10422` "treatment/food through a tube" | `Id10423` "injectable antibiotics" | **confirmed wrong** |
| kn | `Id10471` "Duration of third antecedent cause" | `Id10470` "Record the third antecedent cause" | **confirmed wrong** |
| hi | `Id10148_units` "How long did the fever last?" | `Id10148_a` "How many days…" | likely wrong (a unit selector showing a days question) |

The Odia run is a contiguous shift — `Id10191→Id10192→Id10194→Id10195` each
carrying its predecessor's text — which is what an off-by-one paste in a
translation workbook looks like, not independent typos.

### Same class, but the text is its own — bracket only

Checked and found benign: the row's text matches its own question despite the
stale code. `or/Id10213_units`, `or/Id10248_b` (months, correct), `ta/Id10148_c`
(months, correct), `ta/Id10414_b`, `mr/botecrn`, `mr/noteccd`,
`or/abdominal_pain` (ODK-only name, not in our instrument).

### Not yet verified

`fr/Id10184_c`, `ml/Id10184_c` and `ml/Id10179_1` differ from the code they
show only by a unit (days/hours/months). Deciding them needs a reader of those
languages to say which unit the text names. **They are listed here rather than
guessed at.**

## The same defect in the deployed workbooks

The 34 rows above are only what DigitVA imported. Sweeping the eleven deployed
project workbooks directly is worse: **68 translated label lines carry a code
that is not their row's own**, in *every* workbook, ICMR and DS alike.

| Workbook | Duplicated line | Stale code only |
| --- | --- | --- |
| `OD01_ICMRVA` (Odia) | 1 | 11 |
| `KA01_DS` (kn, mr, hi) | 1 | 11 |
| `KEM_VAADU` (hi, mr) | 0 | 17 |
| `ML01_ICMRVA` (kha) | 0 | 6 |
| `ND01_ICMRVA` (hi) | 0 | 5 |
| `PY01_ICMRVA` (ta) | 0 | 6 |
| `RJ01_ICMRVA` (hi) | 0 | 5 |
| `JIPMER_DS` (ta) | 0 | 3 |
| `KL01_DS` (ml) | 0 | 2 |
| `TR01_DS` (bn) | 0 | 0 |

These cells are **packed**: English and the translation in one cell, separated
by a newline, which `split_packed` divides on import. So the deployed ODK form
shows an interviewer *both* lines. In DigitVA's web form only the translated
half is served, so a wrong translation has no English beside it to catch it.

"Duplicated" means the translated line is byte-identical to another question's,
which is proof of copy-paste. The clearest case, in `OD01_ICMRVA`:

```
Id10191  "(Id10191) Was there blood in the vomit?\n(Id10191) <Odia: blood in vomit>"
Id10192  "(Id10192) Was the vomit black?\n(Id10191) <Odia: blood in vomit>"
```

An Odia-speaking interviewer at OD01 reads the same Odia question twice, and
the second answer is stored as "was the vomit black".

**Byte-identity undercounts.** Where a run is shifted, each line differs from
the one it was copied from because that one was itself overwritten. Reading the
Odia confirms `Id10194` carries `Id10192`'s wording and `Id10195` carries
`Id10194`'s — genuinely wrong, and invisible to the automated check. The true
count of wrong-text cases is above 2 and below 68; **closing that gap needs a
reader of each language**, which is precisely what the locale lifecycle is for.

## Was the collected data affected?

Not demonstrated. If Odia interviewers followed the duplicated line, `Id10191`
and `Id10192` should agree more often at OD01 than elsewhere. They agree 85.6%
of the time at OD01 (118 submissions answering both) — the highest of any site,
but `UNSW01KA0101` reaches 84.4% and `UNSW01KL0101` 82.8%, and the baseline is
high everywhere because most answers are "no". **This is suggestive and not
evidence.** The interviewer also sees the correct English line in ODK, so
practice decides the outcome. Do not cite the workbook defect as proof that
OD01's data is wrong.

## What to do

Fix in the admin string editor, which promotes the row to `edited` and so
outranks any future re-import — not by editing workbooks DigitVA does not own.
Report Class 3 to whoever maintains the affected site workbook, since the same
rows will be wrong wherever else that workbook is used.

Class 3 is the reason the locale lifecycle exists: a translation can be
complete, fluent and still attached to the wrong question, and only a speaker
reading it against the English will catch that. Coverage counts these rows as
translated, correctly — coverage measures presence, never correctness.

Reproduce the sweep with:

```sql
select locale_code, item_key,
       substring(text from '\(([A-Za-z0-9_]+)\)') as shown_code, text
from map_instrument_translations
where item_kind='question' and field='label'
  and text ~ '\(Id[0-9_a-z]+\)'
  and substring(text from '\(([A-Za-z0-9_]+)\)') <> item_key
order by locale_code, item_key;
```

Tracked as `digitva-fb5`.
