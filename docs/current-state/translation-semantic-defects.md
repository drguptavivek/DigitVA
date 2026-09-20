---
title: "Translations that say something other than their English"
doc_type: reference
status: active
owner: DigitVA Data Collection
last_updated: 2026-09-21
---

# Translations that say something other than their English

Twelve audits read **both halves of every packed cell** in the ten deployed
project workbooks. Those cells carry the English reference text and its
translation together, separated by a newline, so a translation can be judged
against the text it claims to render without any external source.

This is the companion to `translation-label-code-mismatches.md`, which
catalogues labels showing the wrong question *code*. A wrong code with the
right wording misleads nobody. **These are wrong wording.**

**These defects are in the deployed ODK workbooks.** Correcting them in
DigitVA's admin string editor fixes only the web form; interviewers collecting
through ODK Central keep reading the wrong text until the workbooks themselves
are corrected and republished. See *Remediation* below.

## Every defect found

| Question | Language | Workbook(s) | English says | Current translation | What the translation actually says | Severity |
| --- | --- | --- | --- | --- | --- | --- |
| `yes` | Bangla | TR01 | Yes | ഉയർന്ന | “ഉയർന്ന” — Malayalam for “high”, not Bangla. YES_NO_REF/yes, on 4 questions | critical |
| `Id10304` | Hindi | ND01, RJ01, KEM | (Id10304) Did she have a sharp abdominal pain in the first 3 months of pregnancy? | (Id10304)क्या मृत्यु से कुछ समय पहले उसके पेट में तेज़ दर्द हुआ था? | “Did she have sharp abdominal pain **shortly before death**?” — the first-trimester window is gone | critical |
| `Id10305` | Hindi | ND01, RJ01, KEM, KA01 | (Id10305) Was she pregnant and not yet in labour at the time of death? | (Id10305)मृत्यु के समय क्या वह गर्भवती थी या प्रसव पीड़ा में थी? | “At the time of death, was she pregnant **or** in labour?” — connective inverted, “not yet” dropped | critical |
| `Id10317` | Hindi | ND01, RJ01, KEM, KA01 | (Id10317) How many babies was she pregnant with? | (Id10317)क्या उसकी मृत्यु एकाधिक गर्भधारण के दौरान या उसके बाद हुई? | “Did her death occur during or after a multiple pregnancy?” — a yes/no question, but the answers are singleton/twins/triplets | critical |
| `Id10024` | Kannada | KA01 | (Id10024) Please indicate the year of death. | (Id10024) ಸತ್ತವರು ಯಾವ ವರ್ಷ ಜನಿಸಿದರು? | “In which year was the deceased **born**?” — asks birth year, not year of death | critical |
| `Id10422` | Kannada | KA01 | (Id10422) Did (s)he receive (or need) treatment/food through a tube passed through the nose? | (Id10423) ಅವರು ಚುಚ್ಚುಮದ್ದಿನ ಪ್ರತಿಜೀವಕಗಳನ್ನು ಸ್ವೀಕರಿಸಿದ್ದಾರೆಯೇ (ಅಥವಾ ಅಗತ್ಯವಿದೆಯೇ)? | “Did (s)he receive injectable antibiotics?” — that is Id10423 | critical |
| `Id10471` | Kannada | KA01 | (Id10471) [Duration of third antecedent cause of death (Id):] | (Id10470) [ಪ್ರಮಾಣಪತ್ರದಿಂದ ಸಾವಿನ ಮೂರನೇ ಪೂರ್ವಭಾವಿ ಕಾರಣವನ್ನು ದಾಖಲಿಸಿ (ಸಾಲು 1d)] | “Record the third antecedent cause from the certificate” — that is Id10470 | critical |
| `Suicide` | Kannada | KA01 | Suicide | ಮೂತ್ರಪಿಂಡ ದುರವಸ್ಥೆ | “ಮೂತ್ರಪಿಂಡ ದುರವಸ್ಥೆ” (kidney disorder) — a coder cannot select suicide | critical |
| `Id10023_b` | Marathi | KA01, KEM | (Id10023_b) When did (s)he die? | वय वर्षांमध्ये | “Age in years” — an unrelated field's label on a date-of-death question | critical |
| `Id10024` | Marathi | KA01 | (Id10024) Please indicate the year of death. | (Id10024) मृत व्यक्तीचा जन्म कोणत्या वर्षी झाला? | “In which year was the deceased **born**?” — asks birth year, not year of death | critical |
| `Id10192` | Odia | OD01 | (Id10192) Was the vomit black? | (Id10191) ବାନ୍ତିରେ ରକ୍ତ ଥିଲା କି? | “Was there blood in the vomit?” — that is Id10191 | critical |
| `Id10194` | Odia | OD01 | (Id10194) Did (s)he have abdominal pain? | (Id10192) ବାନ୍ତି କଳା ରଙ୍ଗ ର ଥିଲା କି? | “Was the vomit black?” — that is Id10192 | critical |
| `Id10195` | Odia | OD01 | (Id10195) Was the abdominal pain severe? | (Id10194) ତାଙ୍କର ପେଟରେ ଯନ୍ତ୍ରଣା ହେଉଥିଲା କି? | “Did (s)he have abdominal pain?” — that is Id10194 | critical |
| `Id10182_units` | Hindi | KEM, KA01 | (Id10182_units) How long did (s)he have diarrhoea? | (Id10181)क्या उसे सामान्य से अधिक बार पतला टट्टी आया था? | “Did (s)he pass loose stools more than usual?” — the neighbouring yes/no question replaces a duration question | serious |
| `Id10190_units` | Hindi | ND01 | (Id10190_units) For how long did (s)he vomit? | (Id10190_units)मृत्यु से कितनी देर पहले उसने उल्टी की थी? | “How long **before death** did (s)he vomit?” — onset-before-death, not symptom duration | serious |
| `Id10306` | Hindi | ND01, RJ01 | (Id10306) Did she die within 6 weeks after delivery? | (Id10306)क्या उसकी मृत्यु प्रसव, गर्भपात या गर्भपात के 6 सप्ताह के भीतर हो गई? | “…within 6 weeks of delivery, abortion or abortion” — scope broadened, गर्भपात repeated | serious |
| `Id10308` | Hindi | RJ01 | (Id10308) Did she die less than 1 year after delivery, abortion or miscarriage? | (Id10308)क्या यह वह महिला थी जिसकी गर्भवती होने या बच्चे को जन्म देने के 1 वर्ष से भी कम समय में मृत्यु हो … | “…less than 1 year after **becoming pregnant or giving birth**” — abortion/miscarriage dropped | serious |
| `Id10322_a` | Hindi | ND01, RJ01, KEM | (Id10322_a) Did she have foul smelling vaginal discharge during pregnancy? | (Id10322)क्या उसे गर्भावस्था के दौरान या प्रसव के बाद दुर्गंधयुक्त योनि स्राव हुआ था? | “…during pregnancy **or after delivery**” — over-scoped; identical to Id10322_b | serious |
| `Id10322_b` | Hindi | ND01, RJ01, KEM | (Id10322_b) Did she have foul smelling vaginal discharge after delivery/abortion? | (Id10322_b)क्या उसे गर्भावस्था के दौरान या प्रसव के बाद दुर्गंधयुक्त योनि स्राव हुआ था? | identical text to Id10322_a, so the two time windows cannot be distinguished | serious |
| `Id10334` | Hindi | ND01, RJ01 | (Id10334) Did she have a pregnancy that ended in an abortion or miscarriage within 6 weeks before her death? | (Id10334)क्या उसे हाल ही में गर्भावस्था हुई थी जो गर्भपात (सहज या प्रेरित) में समाप्त हो गई? | “…a pregnancy that **recently** ended in abortion” — the 6-week window is gone | serious |
| `Id10487` | Hindi | ND01, RJ01, KEM | (Id10487) In the two weeks before death, did (s)he live with, visit, or care for someone who had any COVID-19 symptom… | (Id10487)मृत्यु से पहले के दो सप्ताहों में, क्या वे किसी ऐसे व्यक्ति के साथ रहे थे, उससे मिलने गए थे या उसक… | truncated mid-clause at “जिसका”; the positive-test condition never renders | serious |
| `Id10174` | Kannada | KA01 | (Id10174) Did (s)he have chest pain? | (Id10174)ಅವರಿಗೆ ಹೃದಯ ನೋವು ಇತ್ತಾ? | “Did they have **heart** pain?” — ಹೃದಯ (heart), not ಎದೆ (chest) | serious |
| `Id10175` | Kannada | KA01 | (Id10175) Was the chest pain severe? | (Id10175) ಹೃದಯ ನೋವು ಗಂಭೀರವಾಗಿತಾ? | “Was the **heart** pain severe?” — same chest/heart swap | serious |
| `Id10472` | Khasi | ML01 | (Id10472) [Record the contributing cause(s) of death from the certificate (part 2)] | Pyndap ia kiwei pat ki daw ba lah ban lam sha ka jingkhlad na ka syrnod [lain 1b] | points to certificate “**line 1b**” where the English says Part II | serious |
| `md_count` | Khasi | ML01 | How many images for medical documents? (Max: 30) | Don katno tylli ki dur ki kot sumar (ym dei ban palat ia ka 10 tylli) | “must not exceed **10**” where the English says 30 | serious |
| `Heart_attack` | Marathi | KA01 | Heart attack | हृदयविकार | “हृदयविकार” (general heart disease) — crossed with Heart_problem | serious |
| `Heart_problem` | Marathi | KA01 | Heart problem | हृदयाचे विकार | “हृदयाचा झटका” (heart attack) — crossed with Heart_attack | serious |
| `Id10414_b` | Tamil | PY01, JIPMER | (Id10414_b) Did s/he ever chew and/or sniff tobacco daily? | (Id10414_a)அவர் எப்போதாவது புகையிலையை மென்று சாப்பிட்டோ மூக்கு பொடியாகவோ பயன்படுத்தி இருக்கிறாரா? | “Has he ever chewed or sniffed tobacco?” — “daily” dropped, duplicating Id10414 | serious |
| `n10366` | Khasi | ML01 | Enter the birth weight from the card. Record the weight in grammes in 4 digits. For data entry, convert to grammes as… | Pyndap ia ka jingkhia I khyllung na ka ko tba don. Pyndap ia ka jingkhia ha ki gram. Na ka bynta ban pyndap… | the “record in **4 digits**” instruction is absent | moderate |
| `Id10254` | Marathi | KEM | (Id10254) Did (s)he have any lumps or sores in the mouth? | (Id10254) त्यांना तोंडात किंवा गळ्यात गाठी होत्या का? | “lumps in the mouth or **throat/neck**” — “sores” dropped, a body site added (moderate confidence) | moderate |
| `displayAgeAdult` | Odia | OD01 | ADULT was ${ageInYears} years old. | ସାବାଳକ ଜଣକ (ବୟସକୁ ବର୍ଷ ହିସାବ ରେ କୁହନ୍ତୁ) ବୟସର | same — ${ageInYears} dropped | moderate |
| `displayAgeChild` | Odia | OD01 | CHILD was ${ageInYears} years ${ageInMonths} months and ${ageInMonthsRemain} days old. | (ଉଦ୍ଧାହରଣ ସ୍ବରୂପ ଏକ ଶିଶୁଟି : ୨୦୨୪ ମସିହା, ଜାନୁଆରୀ ମାସର ୧ ତାରିଖରେ ଜନ୍ମ ହୋଇଛି, ତେବେ ୨୦୨୫ ମସିହା ମାର୍ଚ ମାସ ୧୧ ତା… | same — all three placeholders dropped | moderate |
| `displayAgeNeonate` | Odia | OD01 | NEONATE was ${ageInDays} days old. | ନବଜାତ ଶିଶୁର ବୟସ କେତେ (ବୟସ ଟି ଦିନ ହିସାବରେ କୁହନ୍ତୁ) | rewritten as an instruction; the ${ageInDays} placeholder is dropped so the computed age never shows | moderate |
| `Id10213` | Malayalam | KL01 | (Id10213) For how many months did (s)he have mental confusion? | (Id10213) [അദ്ദേഹത്തിന് / അവർക്ക് എത്ര വർഷമായി മാനസിക ആശയക്കുഴപ്പം ഉണ്ടായിരുന്നു എന്ന് നൽകുക]: | “how many **years**” where English says months — but the field is a hidden calculate, never shown | low |

## Defective choice lists, and which questions use them

A wrong answer option changes which answer is recorded, so the reach of each
list matters as much as the defect:

| Workbook | Language | List | Questions using it | Reach |
| --- | --- | --- | --- | --- |
| `TR01_DS` | Bangla | `YES_NO_REF` | `Id10020`, `Id10022`, `ds_available`, `md_available` | **4 live questions** |
| `KA01_DS` | Marathi | `units_5` | `Id10262_units` | 1 |
| `KA01_DS` | Kannada | `select_531` | `Id10484` | 1 |
| `KA01_DS` | Marathi | `select_510` | `Id10477` | 1 |
| `JIPMER_DS`, `PY01_ICMRVA` | Tamil | `select_510` | `Id10477` | 1 each |
| `TR01_DS` | Bangla | `select_512` | `Id10479` | 1 |
| `KA01_DS` | Marathi | `units_4` | — | **0, dead list** |
| `KA01_DS` | Marathi | `M_H_M_DK` | — | **0, dead list** |

The last two matter for what they are *not*. Both are shifted the same way as
`units_5`, but no question references either, so neither reaches an
interviewer. An early reading of this audit described the Marathi unit lists as
backing the duration questions across the illness history; that was wrong, and
is corrected here. Marathi's live damage is `Id10023_b` and `Id10024`.

**The reusable lists are clean.** `YES_NO_DK_REF` (224 questions),
`units_2` (13) and `D_M_DK_REF` are byte-correct in every workbook and
language. That is the result that matters most: a defect there would have
outweighed everything on this page.

## What each locale's audit concluded

| Locale | Cells read | Confirmed | Rate | Status |
| --- | --- | --- | --- | --- |
| Hindi | ~875 per workbook, 4 workbooks | 8 (ND01), 6 (RJ01), 6 (KEM), 4 (KA01) | ~1% | demoted `d5b71c3e9a84` |
| Marathi | 789 (KA01), 858 (KEM) | 9 / 3 | ~1% | demoted `d5b71c3e9a84` |
| Bangla | 806 | 2 | 0.25% | demoted `d5b71c3e9a84` |
| Khasi | 878 | 4, **~98% unassessable** | unknown | demoted `d5b71c3e9a84` |
| Odia | 883 | 6 | 0.7% | demoted `c8e4a1f7b209` |
| Kannada | 808 | 6 | 0.7% | demoted `c8e4a1f7b209` |
| Tamil | 1,677 (both workbooks) | 1 | 0.06% | **stays approved** |
| Malayalam | 884 | 1, in a hidden `calculate` | 0.11% | **stays approved** |

Hindi's six defects are byte-identical between RJ01 and ND01, so they share one
upstream source rather than being independent errors — fixing one workbook will
not fix the others.

Khasi was demoted for unverifiability rather than defect count. Roughly 98% of
its text could be judged by no reviewer available, and four real defects
surfaced in the 2% checkable by mechanical means (numerals, references,
dropped instructions). Serving text nobody has reviewed is what the lifecycle
exists to prevent.

## Suggested corrections

Most corrections do not need a translator: the same English option is already
rendered correctly elsewhere in the same workbook, so the fix is sourced from
the file's own usage. Where that is not true it is marked **needs a speaker** —
those are proposals, not evidence.

### Marathi — `KA01_DS` and `KEM_VAADU` unit lists

Every option is shifted onto its neighbour. `units_2` (13 live questions) is
correct and is the source for most of these.

| List | Option | English | Currently shows | Correct to | Sourced from |
| --- | --- | --- | --- | --- | --- |
| `units_5` | `days` | Days | तास (hours) | **दिवस** | `units_2` row 87 |
| `units_5` | `weeks` | Weeks | दिवस (days) | **आठवडे** | **needs a speaker** — no correct use in the workbook |
| `units_5` | `months` | Months | माहीत नाही (doesn't know) | **महिने** | `units_2` row 88 |
| `units_4` | `months` | Months | तास (hours) | **महिने** | `units_2` row 88 |
| `units_4` | `years` | Years | दिवस (days) | **वर्ष** | used for "Years" elsewhere |
| `M_H_M_DK` | `minutes` | Minutes | तास (hours) | **मिनिटे** | used for "Minutes" elsewhere |
| `M_H_M_DK` | `hours` | Hours | दिवस (days) | **तास** | used for "Hours" elsewhere |

Only `units_5` is live (`Id10262_units`); `units_4` and `M_H_M_DK` are
referenced by no question. Fix all three anyway — a dead list is one form
revision away from being live.

### Marathi — `select_510` (`Id10477`), the two heart options are crossed

| Option | English | Currently shows | Correct to |
| --- | --- | --- | --- |
| `Heart_attack` | Heart attack | हृदयविकार (heart disease) | **हृदयाचा झटका** |
| `Heart_problem` | Heart problem | हृदयाचा झटका (heart attack) | **हृदयविकार** |

The two strings simply swap. Both already exist in the file, so this needs no
new translation. Kannada renders the same pair correctly and distinctly
(ಹೃದಯಾಘಾತ / ಹೃದಯ ಸಮಸ್ಯೆ), which confirms the distinction is meant to be kept.

### Kannada — two isolated cells

| List / question | English | Currently shows | Correct to | Sourced from |
| --- | --- | --- | --- | --- |
| `select_531` `dk` (`Id10484`) | Don't know | `Don't know` — English, untranslated | **ಗೊತ್ತಿಲ್ಲ** | used for "Don't know" elsewhere in this workbook |
| `select_510` `Suicide` (`Id10477`) | Suicide | ಮೂತ್ರಪಿಂಡ ದುರವಸ್ಥೆ (kidney disorder) | **ಆತ್ಮಹತ್ಯೆ** | **needs a speaker** — no correct use in the workbook |

### Bangla — `TR01_DS`

| List / question | English | Currently shows | Correct to | Sourced from |
| --- | --- | --- | --- | --- |
| `YES_NO_REF` `yes` (4 questions) | Yes | ഉയർന്ന — Malayalam | **হ্যাঁ** | used for "Yes" elsewhere in this workbook |
| `select_512` `asphyxia` / `respiratory_distress` | Asphyxia / Respiratory distress | both শ্বাসকষ্ট | two distinct terms required | **needs a speaker** |

### Tamil — `select_510` (`Id10477`)

| Option | English | Currently shows | Correct to |
| --- | --- | --- | --- |
| `Heart_attack` | Heart attack | மாரடைப்பு | **மாரடைப்பு** (correct, leave) |
| `Heart_problem` | Heart problem | மாரடைப்பு | a distinct term — **needs a speaker** |

### Odia — the `Id10191`–`Id10195` shift corrects itself

Every correct Odia string is still in the file, one row below where it belongs,
because the run was pasted down by one. No new translation is needed:

| Question | Currently shows | Correct text is the one currently in |
| --- | --- | --- |
| `Id10192` "Was the vomit black?" | Id10191's text | `Id10194`'s cell |
| `Id10194` "Did (s)he have abdominal pain?" | Id10192's text | `Id10195`'s cell |
| `Id10195` "Was the abdominal pain severe?" | Id10194's text | `abdominal_pain`'s cell |

Apply from the bottom up, or the first move overwrites the next one's source.

### Where no correction can be sourced

For the Hindi maternal-death block, the Kannada chest/heart pair, the
birth-versus-death-year questions and the Khasi items, the correct wording does
not exist anywhere in the corpus — the cell was overwritten rather than
displaced. Those must be translated afresh against the English in the same
cell, then reviewed. This page deliberately does not invent them.

## Remediation

1. **Upstream, in the workbooks — this is the one that matters.** The defects
   ship in the ODK forms. Correct the cell in the site's workbook, republish
   the form to ODK Central, and the fix reaches ODK interviewers and any future
   DigitVA import together. Hindi's shared defects must be fixed in ND01, RJ01,
   KEM and KA01 alike.
2. **In DigitVA, for the web form,** the admin string editor promotes a
   corrected row to `edited`, which outranks a later re-import — so a fix made
   here survives the workbook being re-imported, and is the right place for a
   correction DigitVA wants regardless of upstream.
3. **Re-approve a locale only after a speaker has reviewed it**, through
   `flask instrument-translations lifecycle WHO_2022_VA <locale> approved
   --approved-by <admin>` then `activate`. Coverage does not gate this and
   should not: every defect above sits in a row coverage counts as translated.

## How these were found, and what that says about testing

By opening the form and reading it. No test in this repository could have
caught any of them: the conformance tests compare structure, and coverage
counts presence. Nothing compares a translation against the English it renders
— and until the packed cell was recognised as carrying both, nothing could.

Tracked as `digitva-fb5`.
