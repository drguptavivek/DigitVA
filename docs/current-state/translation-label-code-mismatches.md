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

The 34 rows above are only what DigitVA imported. Sweeping the ten deployed
project workbooks directly is worse: **68 translated label lines carry a code
that is not their row's own**, in *every* one of the ten, ICMR and DS alike.

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

## Every affected question, by form

68 rows, also in `translation-label-code-mismatches.csv` beside this
file for working through in the string editor. Read the last two columns
together: where they describe *different* questions, the interviewer may be
reading the wrong one.

Classes: **duplicate** = the translated line is byte-identical to the shown
question's line, which is proof of copy-paste. *needs review* = the shown code
is a real other question, so the wording may belong to it — a reader of that
language must decide. *stale code* = the shown code is not a question at all,
so only the number is wrong.

| Workbook | Language | Question | Shows | Class | The question asks | The shown code's question asks |
| --- | --- | --- | --- | --- | --- | --- |
| `KA01_DS` | Kannada (kn) | `Id10471` | `Id10470` | **duplicate** | [Duration of third antecedent cause of death (Id):] | [Record the third antecedent cause of death from the cer |
| `OD01_ICMRVA` | Odia (or) | `Id10192` | `Id10191` | **duplicate** | Was the vomit black? | Was there blood in the vomit? |
| `JIPMER_DS` | Tamil (ta) | `Id10148_c` | `Id10148_b` | needs review | [Enter how long the fever lasted in months]: | [Enter how long the fever lasted in days]: |
| `JIPMER_DS` | Tamil (ta) | `Id10414_b` | `Id10414_a` | needs review | Did s/he ever chew and/or sniff tobacco daily? | For how long did s/he chew and/or sniff tobacco? |
| `KA01_DS` | Hindi (hi) | `Id10148_units` | `Id10148_a` | needs review | How long did the fever last? | How many days did the fever last? |
| `KA01_DS` | Hindi (hi) | `Id10182_units` | `Id10181` | needs review | How long did (s)he have diarrhoea? | Did (s)he have diarrhoea? |
| `KA01_DS` | Kannada (kn) | `Id10422` | `Id10423` | needs review | Did (s)he receive (or need) treatment/food through a tub | Did (s)he receive (or need) injectable antibiotics? |
| `KA01_DS` | Marathi (mr) | `botecrn` | `Id10069_a` | needs review | Civil registration: "This refers to the legal death cert | Do you have a Death Certificate from the Civil Registry? |
| `KA01_DS` | Marathi (mr) | `noteccd` | `Id10462` | needs review | Death certificate with cause of death: "This refers to t | Was a medical certificate of cause of death issued? |
| `KEM_VAADU` | Hindi (hi) | `Id10148_units` | `Id10148_a` | needs review | How long did the fever last? | How many days did the fever last? |
| `KEM_VAADU` | Hindi (hi) | `Id10182_units` | `Id10181` | needs review | How long did (s)he have diarrhoea? | Did (s)he have diarrhoea? |
| `KEM_VAADU` | Marathi (mr) | `botecrn` | `Id10069_a` | needs review | Civil registration: "This refers to the legal death cert | Do you have a Death Certificate from the Civil Registry? |
| `KEM_VAADU` | Marathi (mr) | `noteccd` | `Id10462` | needs review | Death certificate with cause of death: "This refers to t | Was a medical certificate of cause of death issued? |
| `KL01_DS` | Malayalam (ml) | `Id10179_1` | `Id10179` | needs review | [Enter how long the chest pain lasted in days]: | [Enter how long the chest pain lasted in hours]: |
| `KL01_DS` | Malayalam (ml) | `Id10184_c` | `Id10184_b` | needs review | [Enter how long before death the diarrhoea started in mo | [Enter how long before death the diarrhoea started in da |
| `ND01_ICMRVA` | Hindi (hi) | `Id10148_units` | `Id10148_a` | needs review | How long did the fever last? | How many days did the fever last? |
| `OD01_ICMRVA` | Odia (or) | `Id10194` | `Id10192` | needs review | Did (s)he have abdominal pain? | Was the vomit black? |
| `OD01_ICMRVA` | Odia (or) | `Id10195` | `Id10194` | needs review | Was the abdominal pain severe? | Did (s)he have abdominal pain? |
| `OD01_ICMRVA` | Odia (or) | `Id10213_units` | `Id10212` | needs review | How long did (s)he have mental confusion? | Did (s)he have mental confusion? |
| `OD01_ICMRVA` | Odia (or) | `Id10248_b` | `Id10248_a` | needs review | [Enter how long (s)he had puffiness of the face in month | [Enter how long (s)he had puffiness of the face in days] |
| `OD01_ICMRVA` | Odia (or) | `abdominal_pain` | `Id10195` | needs review | (not in DigitVA instrument) | Was the abdominal pain severe? |
| `PY01_ICMRVA` | Tamil (ta) | `Id10148_c` | `Id10148_b` | needs review | [Enter how long the fever lasted in months]: | [Enter how long the fever lasted in days]: |
| `PY01_ICMRVA` | Tamil (ta) | `Id10414_b` | `Id10414_a` | needs review | Did s/he ever chew and/or sniff tobacco daily? | For how long did s/he chew and/or sniff tobacco? |
| `RJ01_ICMRVA` | Hindi (hi) | `Id10148_units` | `Id10148_a` | needs review | How long did the fever last? | How many days did the fever last? |
| `JIPMER_DS` | Tamil (ta) | `Id10282` | `Id0282` | stale code | (Id0282) Did the baby become unresponsive or unconscious | (no such question) |
| `KA01_DS` | Hindi (hi) | `Id10010` | `Id100010` | stale code | [Name of VA interviewer] | (no such question) |
| `KA01_DS` | Hindi (hi) | `Id10322_a` | `Id10322` | stale code | Did she have foul smelling vaginal discharge during preg | (no such question) |
| `KA01_DS` | Kannada (kn) | `Id10010` | `Id100010` | stale code | [Name of VA interviewer] | (no such question) |
| `KA01_DS` | Kannada (kn) | `Id10282` | `Id0282` | stale code | (Id0282) Did the baby become unresponsive or unconscious | (no such question) |
| `KA01_DS` | Marathi (mr) | `Id10010` | `Id100010` | stale code | [Name of VA interviewer] | (no such question) |
| `KA01_DS` | Marathi (mr) | `Id10282` | `Id0282` | stale code | (Id0282) Did the baby become unresponsive or unconscious | (no such question) |
| `KEM_VAADU` | Hindi (hi) | `Id10010` | `Id100010` | stale code | [Name of VA interviewer] | (no such question) |
| `KEM_VAADU` | Hindi (hi) | `Id10322_a` | `Id10322` | stale code | Did she have foul smelling vaginal discharge during preg | (no such question) |
| `KEM_VAADU` | Hindi (hi) | `reachinghealthcare` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `Id10010` | `Id100010` | stale code | [Name of VA interviewer] | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `Id10282` | `Id0282` | stale code | (Id0282) Did the baby become unresponsive or unconscious | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `reachinghealthcare` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `sa07_a` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `sa09` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `sa15` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `sa18` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `sa_note` | `0` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `sa_tu15` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `KEM_VAADU` | Marathi (mr) | `sa_tu18` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `ML01_ICMRVA` | Khasi (kha) | `Interviewer` | `VA` | stale code | (not in DigitVA instrument) | (no such question) |
| `ML01_ICMRVA` | Khasi (kha) | `death_summary` | `Images` | stale code | (not in DigitVA instrument) | (no such question) |
| `ML01_ICMRVA` | Khasi (kha) | `ds_available` | `images` | stale code | (not in DigitVA instrument) | (no such question) |
| `ML01_ICMRVA` | Khasi (kha) | `g10366` | `gram` | stale code | (not in DigitVA instrument) | (no such question) |
| `ML01_ICMRVA` | Khasi (kha) | `introduction` | `2022` | stale code | (not in DigitVA instrument) | (no such question) |
| `ML01_ICMRVA` | Khasi (kha) | `reachinghealthcare` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `ND01_ICMRVA` | Hindi (hi) | `Id10010` | `Id100010` | stale code | [Name of VA interviewer] | (no such question) |
| `ND01_ICMRVA` | Hindi (hi) | `Id10322_a` | `Id10322` | stale code | Did she have foul smelling vaginal discharge during preg | (no such question) |
| `ND01_ICMRVA` | Hindi (hi) | `introduction` | `2022` | stale code | (not in DigitVA instrument) | (no such question) |
| `ND01_ICMRVA` | Hindi (hi) | `reachinghealthcare` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `OD01_ICMRVA` | Odia (or) | `Id10282` | `Id0282` | stale code | (Id0282) Did the baby become unresponsive or unconscious | (no such question) |
| `OD01_ICMRVA` | Odia (or) | `Id10467` | `Ib` | stale code | [Duration of the first antecedent cause of death (Ib):] | (no such question) |
| `OD01_ICMRVA` | Odia (or) | `introduction` | `2022` | stale code | (not in DigitVA instrument) | (no such question) |
| `OD01_ICMRVA` | Odia (or) | `mother_deliv` | `Id10386` | stale code | (not in DigitVA instrument) | (no such question) |
| `OD01_ICMRVA` | Odia (or) | `reachinghealthcare` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `OD01_ICMRVA` | Odia (or) | `sa_note` | `0` | stale code | (not in DigitVA instrument) | (no such question) |
| `PY01_ICMRVA` | Tamil (ta) | `Id10282` | `Id0282` | stale code | (Id0282) Did the baby become unresponsive or unconscious | (no such question) |
| `PY01_ICMRVA` | Tamil (ta) | `introduction` | `2022` | stale code | (not in DigitVA instrument) | (no such question) |
| `PY01_ICMRVA` | Tamil (ta) | `reachinghealthcare` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |
| `PY01_ICMRVA` | Tamil (ta) | `sa_note` | `0` | stale code | (not in DigitVA instrument) | (no such question) |
| `RJ01_ICMRVA` | Hindi (hi) | `Id10010` | `Id100010` | stale code | [Name of VA interviewer] | (no such question) |
| `RJ01_ICMRVA` | Hindi (hi) | `Id10322_a` | `Id10322` | stale code | Did she have foul smelling vaginal discharge during preg | (no such question) |
| `RJ01_ICMRVA` | Hindi (hi) | `introduction` | `2022` | stale code | (not in DigitVA instrument) | (no such question) |
| `RJ01_ICMRVA` | Hindi (hi) | `reachinghealthcare` | `HCF` | stale code | (not in DigitVA instrument) | (no such question) |

Counts by workbook: JIPMER_DS 3, KA01_DS 12, KEM_VAADU 17, KL01_DS 2, ML01_ICMRVA 6, ND01_ICMRVA 5, OD01_ICMRVA 12, PY01_ICMRVA 6, RJ01_ICMRVA 5.
By class: DUPLICATE 2, shifted? 22, stale code 44.

## The choices sheet

Audited separately 2026-09-20, since a wrong answer option changes which answer
is recorded. **The reusable lists are clean**, which is the result that matters
most: `YES_NO_DK_REF` (224 questions), `D_M_DK_REF` and `units_2` are
byte-correct in every workbook and every language. A defect there would have
reached hundreds of questions.

Four defects found, each reaching exactly one question:

| Workbook | Language | List | Defect |
| --- | --- | --- | --- |
| `KA01_DS` | Marathi | `units_5` (`Id10262_units`) | **cascade**: days→"hours", weeks→"days", months→"doesn't know", DK→"doesn't know" |
| `KA01_DS` | Kannada | `select_531` (`Id10484`) | cell is `Don't know\n` — English only, no Kannada |
| `JIPMER_DS`, `PY01_ICMRVA` | Tamil | `select_510` (`Id10477`) | "Heart attack" and "Heart problem" both `மாரடைப்பு` |
| `TR01_DS` | Bangla | `select_512` (`Id10479`) | "asphyxia" and "respiratory distress" both `শ্বাসকষ্ট` |

The Marathi cascade is the worst of the four: every option in the list is
shifted onto its neighbour, and two options end up reading identically, so an
interviewer choosing "months" sees the same Marathi as "doesn't know". Every
other workbook's `units_5` is correct, so it is isolated to this one column.

The Kannada row is a missing translation disguised as a present one:
`split_packed` has no second line to take, so English is stored and served as
though translated — and counted in coverage.

The Tamil and Bangla pairs are structurally identical but may be defensible
catch-alls; a reader of each language should say whether the two options are
meant to be distinguishable. Kannada renders the same heart pair correctly and
distinctly (ಹೃದಯಾಘಾತ / ಹೃದಯ ಸಮಸ್ಯೆ), which is evidence the distinction is meant
to survive translation.

Per-option corrections for all of these, sourced from each workbook's own
correct usage wherever possible, are in
`translation-semantic-defects.md` under "Suggested corrections".

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

Odia and Kannada were demoted from `approved` to `in_review` and deactivated
on 2026-09-20 by migration `c8e4a1f7b209`, so DigitVA's web form no longer
serves them and falls back to English. ODK collection is unaffected. The
migration captures each locale's prior state into
`_mig_c8e4a1f7b209_prior_locale_state` so `downgrade` can restore it, and its
UPDATE matches only a locale still `approved`, so re-running changes nothing.
Re-approving a locale after review is a deliberate administrator action:
`flask instrument-translations lifecycle WHO_2022_VA <locale> approved
--approved-by <admin>` then `activate`.

Tracked as `digitva-fb5`.
