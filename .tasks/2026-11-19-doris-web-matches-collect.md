# Web DORIS editor matches the frozen Collect DORIS screen (digitva-knh9)

- Status: in progress
- Priority: P1
- Created: 2026-11-19
- Goal: the web coder's DORIS editor shows what the frozen Collect DORIS
  screen shows; the public demo is the web editor itself (owner 2026-11-19).
  Collect screens are not changed.

## Owner decisions (2026-11-19)

- Collect DORIS screen (`mobile/digitva-collect/src/workspace/doris/`) is the
  reference and stays frozen.
- Web coder editor (`_doris_certificate_editor.html`, `doris_clinical.js`)
  follows it.
- Public demo is exactly the web editor (step 1: rebuilt on the partial).

## Step 2: content gaps, web changes to match Collect

From the 2026-11-19 audit (Collect file:line first, web second):

- "Use DORIS result: CODE — title" (`DorisPanel.tsx:842`; `doris_clinical.js:308`).
- Picker search inside the modal: 3 chars, 500 ms (`IcdPicker.tsx:234,241`;
  `doris_clinical.js:227`, `digitva_icd11_picker.js` 2/250).
- Pregnancy follow-ups disabled with the line "Pregnancy follow-up answers
  are excluded from processing unless pregnancy is Yes." (`DorisPanel.tsx:1260`).
- First Part I line cannot be removed (`DorisPanel.tsx:1092`; `doris_clinical.js:244`).
- "Remove Part II" when it has conditions (`DorisPanel.tsx:1088`).
- 8 conditions per line, search hidden at 8 (`DorisPanel.tsx:1104`).
- Uncoded chip shows the text alone (`DorisPanel.tsx:1031`; `doris_clinical.js:171`).
- Pre-Process checks: "Enter at least one Part I condition.", "Enter the
  immediate cause text in the first Part I line.", "Conditions on the same
  Part I line must share one interval." (`DorisPanel.tsx:438-449`).
- 422 errors show `Check: path — message` (`DorisPanel.tsx:224-230`).
- Wording: Process button "Process current certificate"; notice "Review both
  results, then independently confirm the final underlying cause."; result
  card "DORIS: {status}" and "CoDEdit: {status}"; rejected text; full code
  badge; Details holds the explanation, stem, URI and reports
  (`DorisPanel.tsx:454,760,1318-1344`). Web keeps its "did not run" and "could
  not select" texts, which Collect lacks.
- Picker extras: "Showing the first 20 matches…", Hierarchy on Details,
  Details close, "Show all N", Close label on Hierarchy (`IcdPicker.tsx:205`,
  `DetailsCard.tsx:45-49`, `BuildCard.tsx:107`).

Left as platform differences (same choices, different control): chips vs
selects, year dropdown vs year box, icon search vs Search button, modal vs
inline final-cause search, VA definition placement, number field
placeholders.

## Not done

Masked Step 2 card wording (`DorisPanel.tsx:669-688` vs
`_masked_doris_final_cod.html:19-30`) needs its own comparison.
