---
title: How-Do-I Corpus - Coding
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Coding

Entries for coders and coding testers. Format and truth rules:
`docs/policy/help-chatbot.md`. Screen labels are copied from the Collect
workspace (`mobile/digitva-collect/src/workspace/`), which both the browser app
and the Android app use for online coding. Entries for reviewers, mentors,
training and accounts are in the sibling files.

### How do I find my coding cases?

- id: hdi-coding-001
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Open **VA Code** in the menu (browser), or **Online cases** on the Android home screen.
  2. Read the counts at the top of the queue, then use **Start a random case** or **Pick case** (see the next two entries).
- notes: Which button you get depends on the project's coder-intake mode (random or pick). The queue only lists cases in your area and in the languages on your profile. Without any coding grant the page says the account has no active coding or review access.
- sources: coding-workflow; `mobile/digitva-collect/src/web/navTabs.ts`; `mobile/digitva-collect/src/workspace/QueueScreen.tsx`
- checked: 2026-11-06

### How do I get the next case when my project uses random allocation?

- id: hdi-coding-002
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Open **VA Code**.
  2. Press **Start a random case**.
  3. The case opens. Complete Step 1 and Step 2 (see the Step entries).
- notes: DigitVA picks one eligible case at random from the pool you may code. You cannot choose it. The button is disabled while you already hold a case; **Resume case** or **Release case** it first. If the pool is empty you see "No forms are available to you for VA coding."
- sources: coding-workflow; `app/services/coder_workflow_service.py` (`allocate_random_form`); `mobile/digitva-collect/src/workspace/QueueScreen.tsx`
- checked: 2026-11-06

### How do I pick a specific case to code?

- id: hdi-coding-003
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Open **VA Code** in a project that uses pick-and-choose coding.
  2. Find the case in the list. Use **Filter cases** (ID, area, collector or form), the sex filter or **Within Area** to narrow it.
  3. Press **Pick case**.
- notes: **Pick case** is disabled while you hold another case, and when the project does not use pick-and-choose ("This project does not use pick-and-choose coding."). A case already taken by another coder gives "This submission is no longer available for coding."
- sources: coding-workflow; `app/services/coder_workflow_service.py` (`allocate_pick_form`); `mobile/digitva-collect/src/workspace/QueueScreen.tsx`
- checked: 2026-11-06

### How do I know whether my project uses random or pick-and-choose coding?

- id: hdi-coding-004
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Open **VA Code**.
  2. Look at the queue header: **Random allocation** (with **Random pool**) means random; **Ready to pick** means you choose.
- notes: The mode is a project setting ("Coding Intake Mode") that an administrator changes on the project form. One account can see both kinds if it codes in several projects.
- sources: `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; `app/templates/admin/panels/projects.html` (Coding Intake Mode); docs/policy/coding-workflow-state-machine.md
- checked: 2026-11-06

### Why does the queue show no cases, or "No forms are available to you for VA coding"?

- id: hdi-coding-005
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Press **Refresh cases**, in case another coder just took the last one.
  2. Check your coding languages and area with your data manager (see "How do I check my coding languages and access?").
  3. If the cases should exist, ask your data manager whether they have passed the SmartVA step and are not marked not codeable.
- notes: A case is offered only when it is ready for coding, not finished, not held by another coder, not a confirmed duplicate, not removed from ODK, in your area, in a narration language on your profile, and its site's coding gates are open. This list is a reason list, not a check of your own account.
- sources: `app/services/coder_workflow_service.py` (`_available_submission_filters`); `app/services/duplicate_exclusion.py`; `app/services/odk_retirement_service.py`
- checked: 2026-11-06

### Why does a case say it is "still preparing" or "not ready for coding yet"?

- id: hdi-coding-006
- roles: coder
- surfaces: both
- steps:
  1. Wait a minute and try again, or press **Refresh cases**.
  2. If it stays like that, tell your data manager the case id.
- notes: Before coding, a case waits for its attachments and for a SmartVA attempt on its current data. The messages are "This case is still preparing. Checking again shortly..." (Code this case now) and "This case is not ready for coding yet." (409).
- sources: coding-workflow; docs/policy/coding-workflow-state-machine.md ("SmartVA Gate"); `app/services/coder_workflow_service.py` (`_unavailable`); `mobile/digitva-collect/src/strings/en.json` (`codeNowPreparing`)
- checked: 2026-11-06

### Why can't I start coding at a site ("Coding for this site opens on...", "ended on...", "currently disabled", "today's coding limit")?

- id: hdi-coding-007
- roles: coder
- surfaces: both
- steps:
  1. Read the message: it names the site (or unit) and the date.
  2. If coding has not opened or has ended, or is disabled, ask your project PI or administrator.
  3. If you hit "You have reached today's coding limit of N forms for this site.", come back the next day (dates use UTC).
- notes: The gates are per site or organisation unit: coding enabled, start date, end date and a daily coder limit. A coding tester is not stopped by them; a coder is.
- sources: coding-workflow; coding-tester; `app/services/coder_workflow_service.py` (`_get_site_coding_error`); docs/policy/coding-workflow-state-machine.md ("Coding Access Gates")
- checked: 2026-11-06

### Why do I get "Your profile does not support coding forms in <language>"?

- id: hdi-coding-008
- roles: coder
- surfaces: both
- steps:
  1. Ask your data manager or administrator to add that narration language to your coding languages.
  2. Meanwhile pick a case in a language that is on your profile.
- notes: You cannot edit coding languages yourself. The case list and the pick check both use the narration language of the case.
- sources: profile; `app/services/coder_workflow_service.py` (`allocate_pick_form`)
- checked: 2026-11-06

### What does "You have reached today's limit of 200 coding allocations in this project." mean?

- id: hdi-coding-009
- roles: coder
- surfaces: both
- steps:
  1. Wait for the next day and start or pick a case again. The limit clears by itself.
- notes: A coder can take at most 200 coding allocations per project per day, counted from midnight on the project's clock (its timezone, set by an admin). Each site may also set its own lower daily limit. Resuming a case you already hold is not a new allocation, and coding-tester allocations are not counted. The limit is checked when you start or pick a case. DigitVA gives you no way to clear it yourself; for an urgent exception ask your data manager or the Central Admin Team.
- sources: docs/policy/coding-workflow-state-machine.md ("Coder daily allocation limit")
- checked: 2026-11-06

### Why do I see "You already have an active coding allocation"?

- id: hdi-coding-010
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Finish the case you hold: press **Resume case**.
  2. Or give it up: press **Release case** and confirm.
- notes: A coder holds one coding case at a time on real work, and one more on the training project. The queue shows "You have an active coding case" and "Resume it, or release it, before you start another case."
- sources: `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; docs/policy/coding-workflow-state-machine.md ("One active allocation per side")
- checked: 2026-11-06

### How do I resume the case I was working on?

- id: hdi-coding-011
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Open **VA Code**.
  2. Press **Resume case**.
- notes: Resuming works only inside the one-hour allocation (see the timeout entries). Saved Step 1 work is still there.
- sources: `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; `app/routes/coding.py` (`resume`)
- checked: 2026-11-06

### How do I release a case I do not want to code?

- id: hdi-coding-012
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Open **VA Code**.
  2. Press **Release case**. The dialog is titled "Release this case?".
  3. Press **Release** to confirm.
- notes: "An unfinished saved Step 1 will be discarded. Unsaved work may also be lost." The case goes back to the pool (or, for a recode, back to your finalised result). After release the screen says "Coding case released."
- sources: `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; docs/policy/coding-allocation-timeouts.md ("Coder release"); `mobile/digitva-collect/src/strings/en.json` (`releaseCodingWarning`)
- checked: 2026-11-06

### How long do I have to finish a case, and what happens if I run out of time?

- id: hdi-coding-013
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Finish and save the final cause within one hour of taking the case.
  2. If you did not, open **VA Code** again and take a case (see the next entry).
- notes: Allocations older than one hour are released automatically (a background sweep, and when someone starts a new case). First-pass work that is not finished is thrown away: Step 1, Narrative Quality Assessment and Social Autopsy are deactivated and the case goes back to the pool. Practice cases on demo projects time out after 15 minutes.
- sources: coding-workflow; demo-coding; docs/policy/coding-allocation-timeouts.md
- checked: 2026-11-06

### The case timed out while I was working. What do I do now?

- id: hdi-coding-014
- roles: coder
- surfaces: both
- steps:
  1. If the screen says "Your case allocation is no longer active.", leave the case.
  2. Open **VA Code** and press **Start a random case** or **Pick case**. The same case may be given to you or to another coder.
  3. Enter Step 1 again. Nothing from the timed-out attempt is kept.
- notes: A timed-out recode is different: it is abandoned but your earlier final cause stays authoritative (see the recode entries). Save the final cause quickly in future; keep the case open only while you work on it.
- sources: coding-workflow; recode-window; `mobile/digitva-collect/src/workspace/CaseWorkspaceScreen.tsx`; docs/policy/coding-allocation-timeouts.md
- checked: 2026-11-06

### What are Step 1 and Step 2?

- id: hdi-coding-015
- roles: coder, reviewer, coding_tester
- surfaces: both
- steps:
  1. Step 1: read the case and record your own immediate and antecedent causes (or, in an ICD-11 project, the DORIS certificate and your underlying cause). The SmartVA result is hidden.
  2. Step 2: see the SmartVA result and your Step 1, then enter or confirm the final underlying cause.
- notes: This is the masked workflow. Projects that turn masking off ("Require masked COD workflow" off) show one "Final Cause of Death Assessment" with the SmartVA result visible. Step 1 is never the authoritative final cause; it is kept for audit.
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; `app/templates/va_form_partials/vainitialasses.html`; `app/templates/va_form_partials/vafinalasses.html`
- checked: 2026-11-06

### How do I complete Step 1 in an ICD-10 project?

- id: hdi-coding-016
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Read the case in the category list (narration, history, symptoms).
  2. Under "Cause of Death Ascertainment - Step 1", search and choose the **Immediate Cause of Death**.
  3. Choose the **Antecedent Cause of Death**. If you cannot find an underlying cause, copy the immediate cause.
  4. Optionally add **Other significant conditions (if any)**.
  5. Press **Save Assessment**.
- notes: Immediate cause means the disease, injury or complication that caused death, not a mode of dying such as heart failure. Both causes are required. If the project needs Narrative Quality Assessment, you must save it before Step 2 opens.
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; `app/forms/va_iniassess_form.py`
- checked: 2026-11-06

### How do I complete Step 2 in an ICD-10 project?

- id: hdi-coding-017
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. After **Save Assessment** on Step 1, "Cause of Death Ascertainment - Step 2" opens.
  2. Read the SMART VA analysis and your Step 1 causes ("Your Step 1 Assigned Causes").
  3. Search and choose the **Final Underlying / Antecedent Cause of Death**.
  4. Add a remark if you wish, then press **Save Assessment**.
- notes: The final code must be one the case's age group and sex allows (see the code entries). After saving, the case leaves your queue and appears under your coded cases.
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; `app/templates/va_form_partials/vafinalasses.html`; `app/forms/va_finassess_form.py`
- checked: 2026-11-06

### How do I code a case in a project with unmasked coding?

- id: hdi-coding-018
- roles: coder
- surfaces: both
- steps:
  1. Open the case. The SmartVA result is shown from the start.
  2. Under "Final Cause of Death Assessment", enter the **Immediate cause**, **Underlying cause** and (optionally) **Associated conditions (optional)**.
  3. Press **Save final assessment**.
- notes: There is no separate Step 1. In an ICD-11 unmasked project the same screen is the DORIS certificate (see the DORIS entries).
- sources: `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; `app/templates/va_form_partials/vafinalasses.html`
- checked: 2026-11-06

### Where is the SmartVA result, and why can't I see it in Step 1?

- id: hdi-coding-019
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Finish and save Step 1.
  2. The SmartVA analysis appears at the top of Step 2.
- notes: Masked coding hides SmartVA in Step 1 on purpose, so your own assessment is independent. A panel on the case page shows only the SmartVA status.
- sources: coding-workflow; `app/templates/va_form_partials/_smartva_summary.html`; docs/policy/coding-workflow-state-machine.md ("SmartVA status on the coding page")
- checked: 2026-11-06

### SmartVA says "Not requested" or failed. What can I do?

- id: hdi-coding-020
- roles: coder, reviewer
- surfaces: both
- steps:
  1. In the SmartVA panel, press **Run SmartVA** (not requested) or **Run again** (failed).
  2. After "SmartVA has been queued." reload the case in a minute.
- notes: If SmartVA keeps failing, you can still code: the panel then shows no result and Step 2 works without it. The panel is not offered once the case is past coding.
- sources: `mobile/digitva-collect/src/workspace/SmartvaStatusPanel.tsx`; docs/policy/coding-workflow-state-machine.md ("SmartVA status on the coding page")
- checked: 2026-11-06

### How do I search for an ICD code?

- id: hdi-coding-021
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Click the cause box and type at least two characters (placeholder "Search ICD codes...").
  2. Read **Focused matches** (strongest) and **Term matches** (everything else containing your text).
  3. Choose the code you want.
- notes: You can type a code (A09), a title word, or a clinical term or shorthand (MI, CVA, TB, heart attack, loose motions). UK and US spellings match, and close misspellings are tried when nothing is found. The two help buttons beside the box are **Selected ICD Codes** and **VA Definitions**.
- sources: icd-codes; `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; docs/policy/icd-coding-search-vocabulary.md
- checked: 2026-11-06

### Why is the code I want not offered in the search?

- id: hdi-coding-022
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Check the message under the box: when nothing is selectable it says how many codes match but "are not selectable for" the case's age group and sex, with up to three examples and the reason (for example "female only", "neonate only").
  2. Search for a more specific code, or an external cause for an injury (see the injury entry).
  3. If you believe the rule is wrong, tell your administrator; they curate selectability.
- notes: Codes are offered only if they pass the WHO VA 2022 allowability list and the case's age group (neonate under 28 days, infant to 1 year, child to 12 years, adult 12 and over) and sex. ICD-10 injury codes S00-T99 and three-character transport codes V01-V89 and Y85 are never selectable. A code an administrator has disabled is silently missing.
- sources: icd-codes; `app/services/icd_coding_policy.py`; docs/policy/who-2022-icd10-coding-allowability.md
- checked: 2026-11-06

### What if an ICD-11 code is "age-restricted" or I see "Age restriction ... Save anyway"?

- id: hdi-coding-023
- roles: coder, reviewer
- surfaces: both
- steps:
  1. In ICD-11 search a code with an age mismatch shows an **age-restricted** marker and a note.
  2. If you choose it as the final underlying cause, a dialog titled "Age restriction" says the code is usually used only for that group and that "WHO's DORIS treats this as a plausibility warning."
  3. Press **Save anyway** to keep it, or cancel and pick another code.
- notes: In ICD-11, age mismatches warn and need your confirmation; the confirmation is recorded. In ICD-10 an age mismatch is refused. A sex mismatch blocks in both and cannot be confirmed.
- sources: `app/services/icd_coding_policy.py`; `app/services/icd11_mms_service.py`; `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; `mobile/digitva-collect/src/strings/en.json` (`ageRestriction*`)
- checked: 2026-11-06

### Can I use an ICD-10 code in an ICD-11 project, or the other way round?

- id: hdi-coding-024
- roles: coder
- surfaces: both
- steps:
  1. Use the classification your project uses. The coding box, the ICD browser link and the search follow it.
- notes: A code from the other catalogue is rejected when you save. ICD-11 projects always code through DORIS; ICD-10 projects use simple entry.
- sources: icd-codes; icd11-codes; `app/templates/admin/panels/projects.html` (ICD Classification, COD Entry)
- checked: 2026-11-06

### How do I code a death caused by an injury?

- id: hdi-coding-025
- roles: coder
- surfaces: both
- steps:
  1. Search for the injury as you would (for example "head injury").
  2. Choose the external cause that the search offers instead: road traffic, fall, assault, struck by a falling object, or unspecified.
- notes: WHO codes injury deaths by the external cause. ICD-10 S00-T99 are not selectable. Anaphylaxis and allergic reaction similarly offer drug, vaccine, sting, venomous animal or unspecified.
- sources: icd-codes
- checked: 2026-11-06

### Why can't I pick a transport accident code like V89?

- id: hdi-coding-026
- roles: coder
- surfaces: both
- steps:
  1. Search again and choose a code at the level that says whether it was a road traffic accident, for example V89.2 (unspecified motor-vehicle accident, traffic).
- notes: The three-character ICD-10 codes V01-V89 and Y85 are not selectable because WHO separates road traffic from other transport only at the fourth character.
- sources: icd-codes
- checked: 2026-11-06

### How do I code a stillbirth?

- id: hdi-coding-027
- roles: coder
- surfaces: both
- steps:
  1. In an ICD-11 project choose KD3B.1 (intrapartum, fresh) or KD3B.0 (antepartum, macerated).
  2. In an ICD-10 project choose P95, which covers both.
- notes: The unspecified ICD-11 stillbirth codes are not selectable.
- sources: icd-codes
- checked: 2026-11-06

### Where can I read the definition of a VA cause?

- id: hdi-coding-028
- roles: coder, reviewer
- surfaces: both
- steps:
  1. After you choose a code, the floating definition panel shows the WHO definition of the VA cause that code belongs to.
  2. Press **VA Definitions** beside the box for the full list ("VA Codes, Titles and Definitions"); use the filter box to find a cause.
- notes: Every ICD code maps to one WHO 2022 VA cause. The VA cause is how deaths are grouped for reporting; you still choose an ICD code.
- sources: icd-codes; `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`
- checked: 2026-11-06

### How can I try the coding search without opening a case?

- id: hdi-coding-029
- roles: coder, coding_tester, reviewer
- surfaces: web
- steps:
  1. Open the help page "ICD Codes, VA Causes and the Coding Search" and follow its "Try the coding search" link.
  2. Choose **ICD-10** or **ICD-11**, an age group (neonate, infant, child, adult) and a sex, then type.
- notes: It runs the real search with the age group and sex you choose, saves nothing and is not recorded as a search. It is open to coders, coding testers, reviewers and administrators.
- sources: icd-codes-search-demo; `app/routes/help.py` (`icd_codes_search_demo`)
- checked: 2026-11-06

### How do I code in an ICD-11 project (DORIS)?

- id: hdi-coding-030
- roles: coder
- surfaces: both
- steps:
  1. Open the case. The DORIS certificate opens with what the interview already gave (Part 1 causes, administrative data); check it and fix it.
  2. Press **Process current certificate**. DORIS and CoDEdit return their results and any problems under "Check before you decide".
  3. Review both results, then choose the final underlying cause: **Use DORIS result**, or search ICD-11 under "Or search ICD-11 for your own code".
  4. Add a **COD remark** if needed, then press **Save final COD**.
- notes: You, not DORIS, decide the final cause. If you edit the certificate after processing, the screen says "Certificate changed. Process it again before saving." and the save button stays off until you process again. In masked projects use the Step 1 / Step 2 flow in the next two entries.
- sources: coding-workflow; doris-demo; `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; docs/policy/doris-cod-workflow.md
- checked: 2026-11-06

### How do I do Step 1 in a masked ICD-11 project?

- id: hdi-coding-031
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Fill in the DORIS certificate (Part 1 lines, **Add line** for more, Part 2 conditions).
  2. Press **Process current certificate**.
  3. Under **Confirm Step 1 underlying cause**, confirm the cause you choose (DORIS's suggestion or your own code).
  4. Press **Save Step 1**.
- notes: SmartVA is not shown in Step 1. Part I line 1 is saved as the immediate cause. You can change the underlying cause in Step 2.
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; `app/templates/va_form_partials/vainitialasses.html`
- checked: 2026-11-06

### How do I do Step 2 in a masked ICD-11 project?

- id: hdi-coding-032
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Read "Your Step 1 assigned causes" and the SmartVA result.
  2. Under **Choose and confirm the final underlying cause**, press one of: **Use Step 1 underlying cause**, **Use SmartVA result**, or search ICD-11 for your own code.
  3. Add a **COD remark** if needed and press **Save final cause**.
- notes: There is no second certificate. "DORIS result from Step 1 (for information)" is shown for reference.
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; `app/templates/va_form_partials/_masked_doris_final_cod.html`
- checked: 2026-11-06

### What does "Reset DORIS from interview" do?

- id: hdi-coding-033
- roles: coder
- surfaces: both
- steps:
  1. Press **Reset DORIS from interview** to throw away your edits to the certificate and reload what the interview supplied.
  2. Process the certificate again.
- notes: "Remarks, notes and SmartVA results are retained."
- sources: `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`
- checked: 2026-11-06

### DORIS says my certificate has a problem, or will not process. What do I check?

- id: hdi-coding-034
- roles: coder
- surfaces: both
- steps:
  1. Read the messages under "Check before you decide".
  2. Common fixes: enter at least one Part I condition; put the immediate cause text in the first Part I line; fill or remove blank Part I lines; conditions on the same Part I line share one interval.
  3. Process again.
- notes: The screen says "WHO ICD-11 did not confirm that code. Search for the cause instead." when a typed code fails. If the WHO service is unavailable the save is refused; try again later. "DORIS could not select an underlying cause from this certificate." means you must pick your own code.
- sources: `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; `app/routes/va_form.py` (DORIS conflict codes); `app/services/reviewer_coding_service.py`
- checked: 2026-11-06

### Can I choose a different cause than DORIS suggests?

- id: hdi-coding-035
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Under **Or search ICD-11 for your own code**, search and choose your code.
  2. Save as usual.
- notes: The screen says "Your choice matches ..." when it equals a suggestion.
- sources: `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; docs/policy/doris-cod-workflow.md
- checked: 2026-11-06

### How do I try DORIS before I code a real case?

- id: hdi-coding-036
- roles: coder, coding_tester, reviewer
- surfaces: both
- steps:
  1. In the browser, open the help page "Try DORIS & CoDEdit" if your site offers it. It uses invented certificates and saves nothing.
  2. On Collect Plus (Android), open Help and press **Try DORIS (offline demo)**. Pick one of the examples or **Blank certificate**.
- notes: On Collect Plus the first engine start takes about 20 seconds. If ICD-11 / DORIS coding is off on the phone, turn it on in Settings first. Do not type real patient details.
- sources: doris-demo; `mobile/digitva-collect/src/strings/en.json` (`helpTryDoris`, `dorisDemo*`); docs/current-state/expo-client.md ("Try DORIS demo")
- checked: 2026-11-06

### What is the Narrative Quality Assessment (NQA) and how do I fill it in?

- id: hdi-coding-037
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Open the **Narration / Documents** category.
  2. In "Narrative quality" answer Q1. Length of Narrative, Q2. Number of Positive Symptoms, Q3. Presence of Negative Symptoms, Q4. Chronology of Events, Q5. Document Review and Q6. Comorbidities / Risk Factors.
  3. Press **Save narrative quality** (it can be changed and saved again).
- notes: The score is out of 10 and rated Good (7 or more), Fair (5 to 6) or Poor (below 5). If the narrative is missing or in a language you cannot grade, choose **Cannot grade**. NQA appears only in projects where an administrator has switched it on.
- sources: coding-workflow; `app/services/narrative_qa_service.py`; `app/models/va_narrative_assessments.py`; docs/policy/narrative-quality-assessment.md
- checked: 2026-11-06

### Why am I told to complete the Narrative Quality Assessment before the final assessment?

- id: hdi-coding-038
- roles: coder
- surfaces: both
- steps:
  1. Open the **Narration / Documents** category.
  2. Save the NQA (see the NQA entry).
  3. Return to the assessment.
- notes: The screen says "Complete the Narrative Quality Assessment before proceeding." (the older web page says "Complete the Narrative Quality Assessment first" and links to Narration / Documents). The project requires NQA before the final cause. Your saved Step 1 is kept. Reviewers are not blocked by NQA.
- sources: docs/policy/narrative-quality-assessment.md; `app/templates/va_form_partials/_nqa_required_notice.html`; `app/services/case_content_service.py` (`nqa_blocks_final`)
- checked: 2026-11-06

### How do I complete the Social Autopsy analysis?

- id: hdi-coding-039
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Open the **Social Autopsy** category.
  2. For each of the three delay levels (Delay 1: delay in decision to seek care; Delay 2: delay in reaching health facility; Delay 3: delay in receiving adequate care) tick every factor you observed, or **None**.
  3. Add a remark if needed and press **Save social autopsy**.
- notes: Every level needs an explicit answer. "None" cannot be combined with other options in the same level. It exists only if the project enables Social Autopsy for your role.
- sources: `app/services/social_autopsy_analysis_service.py`; docs/policy/social-autopsy-analysis.md; `mobile/digitva-collect/src/workspace/QualityPanels.tsx`
- checked: 2026-11-06

### Why do I get "Save the Social Autopsy Analysis before proceeding to the next category"?

- id: hdi-coding-040
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Go back to the Social Autopsy category and save the analysis.
  2. Continue to the next category or the assessment.
- notes: The same screen may say "Complete the required assessment (code) before proceeding." when NQA or Social Autopsy is still missing. A refused final save says "Narrative QA or Social Autopsy must be completed first".
- sources: `app/services/case_content_service.py` (`_COMPLETION_BLOCK_MESSAGES`); `mobile/digitva-collect/src/strings/en.json` (`codingRefused_final_blocked`)
- checked: 2026-11-06

### How do I flag a case that cannot be coded (Not Codeable)?

- id: hdi-coding-041
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. While you hold the case, press **Not Codeable** (simple projects) or use **Report not codeable** (ICD-11 projects).
  2. Choose the reason: "I cannot read this narrative language.", "Narrative content doesn't match with the deceased whose VA form has been filled", "There is no information available in Questions as well as Narration", the empty-form option, or Others.
  3. For Others, describe the issue in "Please brief the other issue".
  4. Press **Report Issue** (simple) or **Submit not-codeable report** (ICD-11).
- notes: Use it only when the narrative really cannot support a cause. If details could be gained by asking the family again, tell your supervisor or data manager instead: only supervisors and data managers can send an interview back for revision. A reason is required.
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`; `app/forms/va_coderreview_form.py`
- checked: 2026-11-06

### What happens after I report a case Not Codeable?

- id: hdi-coding-042
- roles: coder
- surfaces: both
- steps:
  1. The case leaves your queue and shows as not codeable under your coded cases.
- notes: The screen warns: "Once reported an error, this VA form will be flagged for review by the Site PI." DigitVA saves the outcome first; ODK Central is updated separately and a failure there is logged for follow-up. The case is excluded from coder allocation. You cannot recode a not-codeable report.
- sources: coding-workflow; `app/templates/va_form_partials/vacoderreview.html`; docs/policy/not-codeable-odk-central-sync.md
- checked: 2026-11-06

### How do I recode a case after I saved the final cause?

- id: hdi-coding-043
- roles: coder
- surfaces: both
- steps:
  1. Open **VA Code** and find the case in **My coded cases**.
  2. Press **Recode**. (Use **Recodeable only** to filter the list.)
  3. Enter Step 1 and Step 2 again and save.
- notes: You can recode your own finalised case, as many times as you like, while the project's recode window is open. The window is measured from your first final cause on the case; recoding does not extend it. Your earlier final cause stays authoritative until the replacement is saved; if you leave the recode unfinished, the old cause stands. The coder dashboard also shows "Recode until <date>" on eligible cases.
- sources: recode-window; viewing-history; `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; `app/services/coder_workflow_service.py` (`start_recode_allocation`)
- checked: 2026-11-06

### How long is the recode window, and where do I see my deadline?

- id: hdi-coding-044
- roles: coder
- surfaces: both
- steps:
  1. Look under the case in **My coded cases**: "Recode until <local time>", or "Recode window closed".
- notes: The window is set per project, between 1 minute and 7 days; the default is 24 hours. It is measured from your first final cause on the case, so recoding never extends it. The training project uses 60 minutes. After it closes the case becomes eligible for a reviewer and you cannot recode it.
- sources: recode-window; `app/services/recode_window.py`; docs/policy/coding-workflow-state-machine.md ("Recode Window")
- checked: 2026-11-06

### Why is there no Recode button on my case?

- id: hdi-coding-045
- roles: coder
- surfaces: both
- steps:
  1. Check the line under the case. "Recode window closed" means the time is up.
  2. Check that you were the coder who finalised it.
  3. If you hold another case, release or finish it first: the button is disabled while you hold one.
- notes: Recode is refused for: not coder-finalised cases ("Only coder-finalized submissions can be reopened for recode."), another coder's case ("You can only re-code VA forms you initially coded."), and a closed window ("This submission is outside the recode window."). A case a reviewer has finalised can no longer be recoded by you. Ask your data manager or administrator if you need an exception.
- sources: recode-window; `app/services/coder_workflow_service.py`; `app/utils/va_permission/va_permission_05_validaterecodelimits.py`
- checked: 2026-11-06

### What happens to my NQA and Social Autopsy during a recode?

- id: hdi-coding-046
- roles: coder
- surfaces: both
- steps:
  1. Open the recode as normal. Your saved NQA and Social Autopsy are still there.
  2. Edit them if needed and save the new final cause.
- notes: They survive a recode timeout too. This differs from first-pass coding, where a timeout throws them away.
- sources: recode-window; docs/policy/coding-allocation-timeouts.md
- checked: 2026-11-06

### My recode timed out. Did I lose my earlier cause?

- id: hdi-coding-047
- roles: coder
- surfaces: both
- steps:
  1. Open **My coded cases** and check the case. It shows your earlier final cause.
  2. If the window is still open, press **Recode** again.
- notes: A recode that is not finished within an hour is abandoned. Your earlier final cause stays, and saved NQA and Social Autopsy are kept. The case goes back to the finalised state.
- sources: recode-window; docs/policy/coding-allocation-timeouts.md
- checked: 2026-11-06

### Which cause of death is the final one when a coder and a reviewer both coded?

- id: hdi-coding-048
- roles: coder, reviewer, data_manager
- surfaces: both
- steps:
  1. The reviewer's final cause, if one exists, is authoritative. Otherwise the coder's final cause is.
- notes: Your Step 1 is never the final cause. The coder's cause is kept in history as superseded when a reviewer finalises. A not-codeable report has no final cause: the outcome is the not-codeable status.
- sources: coding-workflow; docs/policy/final-cod-authority.md
- checked: 2026-11-06

### How do I see the cases I have already coded?

- id: hdi-coding-049
- roles: coder, coding_tester
- surfaces: both
- steps:
  1. Open **VA Code** (browser) or **My coded cases** (Android home).
  2. Use **Filter cases**, the sex filter or **Within Area** to find the case.
  3. Press **View case** to open it read-only.
- notes: The view shows your Step 1, final cause, remarks, NQA and Social Autopsy. Your history shows final causes and not-codeable reports. Practice codes on demo projects drop out when their retention ends. The coded count on the dashboard excludes demo and coding-tester work.
- sources: viewing-history; `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; docs/policy/demo-coding-retention.md
- checked: 2026-11-06

### Can I see what happened to a case, and when?

- id: hdi-coding-050
- roles: coder, reviewer
- surfaces: both
- steps:
  1. Open the case.
  2. Open the **Workflow history** panel and read **Latest events**; press **Load older events** for more.
- notes: It lists state changes with times shown in your time zone (coding started, Step 1, final cause, recode window closed, reviewer started, allocation released). The administrator's activity log is separate and admin only.
- sources: viewing-history; `mobile/digitva-collect/src/workspace/WorkflowHistory.tsx`
- checked: 2026-11-06

### How do I write a private note on a case?

- id: hdi-coding-051
- roles: coder, reviewer
- surfaces: both
- steps:
  1. While you code or review a case, open the **Notes** panel.
  2. Type your note; it is saved against the case for you.
- notes: The note is private to you. When you only view a case, the panel says "Open Notes to view your saved note." or "No note saved for this submission yet."
- sources: `mobile/digitva-collect/src/workspace/CaseWorkspaceScreen.tsx`; `app/routes/va_form.py` (`vausernote`)
- checked: 2026-11-06

### How do I code a case I just interviewed myself ("Code this case now")?

- id: hdi-coding-052
- roles: coder
- surfaces: both
- steps:
  1. After you submit the interview, press **Code this case now**, or use "Code now" in your interview worklist.
  2. If the case is still preparing, wait; it retries.
- notes: Only the interviewer who submitted the case, in a self-coding project, with the case ready for coding and no other case held. If you hold another case: "You already hold another coding case." with **Release my other case and continue**. "Another coder took this case. Refresh the worklist." means someone else started it. Self-coding is a project setting ("Self-coding (coders also interview; needs web intake on)").
- sources: docs/policy/web-intake.md ("Self-coding projects"); docs/policy/coding-workflow-state-machine.md ("Self-coding"); `mobile/digitva-collect/src/workspace/CodeNowButton.tsx`; `app/services/coder_workflow_service.py`
- checked: 2026-11-06

### How do I check my coding languages and project access on my phone?

- id: hdi-coding-053
- roles: coder
- surfaces: android
- steps:
  1. Unlock the app and open **Settings**.
  2. Under Account, open **Profile and project access**.
  3. Read **Coding languages**, **Coding scope** and, per project, "Coding allowed" or "Coding unavailable".
- notes: This screen is on the Android app only. Languages and access are set by your data manager or administrator. Turning on the ICD-11 / DORIS switch on the phone does not grant coding access to a project.
- sources: `mobile/digitva-collect/src/nativeRoutes/settings.tsx`; `mobile/digitva-collect/src/strings/en.json` (`profileAccess*`, `profile*`)
- checked: 2026-11-06

### How does a coding tester differ from a coder, and what happens to my test codes?

- id: hdi-coding-054
- roles: coding_tester
- surfaces: both
- steps:
  1. Use the same **VA Code** queue and screens as a coder.
  2. Save your final cause as usual to test the full path.
- notes: A tester can code when coding is disabled, outside the date window, or after the daily limit. In a production project the tester's result is flagged as tester output, never becomes the case's result, does not open a recode window, and the case goes straight back to ready for coding for a real coder. In demo and training projects test codes are removed after the retention window. Tester output is excluded from coder, data manager and burndown counts.
- sources: coding-tester
- checked: 2026-11-06

### Why can't I code as a project PI or site PI?

- id: hdi-coding-055
- roles: coder, project_pi, site_pi
- surfaces: both
- steps:
  1. Ask your administrator or data manager for an explicit **coder** or **coding tester** grant on the project.
- notes: Oversight roles do not carry coding access by themselves.
- sources: coding-tester; docs/policy/coding-workflow-state-machine.md ("Coding Access Gates")
- checked: 2026-11-06

### Why can I open some cases only to view, not code? ("My area")

- id: hdi-coding-056
- roles: coder, reviewer
- surfaces: web
- steps:
  1. On the web coding dashboard (**VA Coding** in the classic menu) press **Open my area**. The card appears only if you hold a coding-track grant on an organisation project.
  2. Open a case to read it. Nothing on that page changes the case.
- notes: A grant above the project's coding level lets you oversee the whole subtree read-only (cause of death and submission data) but not code those cases. The page lists up to 200 cases.
- sources: `app/routes/coding.py` (`area_overview`, `area_view_submission`); docs/policy/area-dashboard.md
- checked: 2026-11-06

### Can I code on my phone without a connection (Collect Plus)?

- id: hdi-coding-057
- roles: coder
- surfaces: android
- steps:
  1. Use the experimental Collect Plus build installed by your project team. Online coding in the normal Collect app needs a connection.
  2. Turn on ICD-11 / DORIS coding in the app when asked ("Enable coding").
  3. On the home screen open **Local cases**, choose a completed interview and code it with the on-phone DORIS engine.
- notes: Collect Plus is not published on a store. Local coding needs a coder grant and self-coding in the same project (standalone mode keeps its own local flow). The first engine start takes about 20 seconds. Local coding results are sent with the interview and the server may refuse them (for example "your account has no coding role on this project"). Set your **Offline profile** first.
- sources: docs/current-state/expo-client.md ("Collect Plus", "Pure offline mode", "Unified phone coding access"); `mobile/digitva-collect/src/ui/CodingCaseChips.tsx`; `mobile/digitva-collect/src/strings/en.json` (`standaloneCodingRefused*`)
- checked: 2026-11-06

### Can I review cases on the normal Collect app?

- id: hdi-coding-058
- roles: coder, reviewer
- surfaces: android
- steps:
  1. Review in the browser app (**VA Review**), or in the Collect Plus build (**Review cases** in Settings).
- notes: The normal phone app says "Coding and review are done in the DigitVA web app, not on this phone." for review-only accounts. Coders can code online in both builds.
- sources: `mobile/digitva-collect/src/nativeRouteScreens.native.tsx`; `mobile/digitva-collect/src/nativeRoutes/settings.tsx`
- checked: 2026-11-06

### Why is a phone coding case blocked ("Unlock this account", "Sign in again", access blocked)?

- id: hdi-coding-059
- roles: coder
- surfaces: android
- steps:
  1. "Unlock this account to see its coding cases.": enter your PIN.
  2. "Sign in again to see and code this account's cases.": sign in again.
  3. "This account's access is blocked...": contact your supervisor.
- notes: Unsent work on the phone is kept when you sign in again.
- sources: `mobile/digitva-collect/src/NativeCollectionGate.native.tsx`; `mobile/digitva-collect/src/strings/en.json` (`codingBlocked*`)
- checked: 2026-11-06
