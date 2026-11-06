---
title: How-Do-I Corpus - Reviewing and Mentoring
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Reviewing and Mentoring

Entries for reviewers and for mentoring-institute staff. Format and truth
rules: `docs/policy/help-chatbot.md`. Reviewer screens are the Collect
workspace (`mobile/digitva-collect/src/workspace/`). On Android, review exists
only in the experimental Collect Plus build.

### How do I find cases to review?

- id: hdi-reviewing-001
- roles: reviewer
- surfaces: web
- steps:
  1. Open **VA Review** in the menu.
  2. Read **Available to review** and the list under **Reviewer queue**.
  3. Use **Filter cases** (ID, area, collector, form), the sex filter or **Within Area** to narrow it.
- notes: Only cases in your area and in the languages on your profile are listed. A case appears only after its coder's recode window has closed. If it is empty the page says "No cases to review right now." or "Nothing to review ... yet: cases appear here after a coder finalises them."
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; docs/policy/coding-workflow-state-machine.md ("Reviewer precondition")
- checked: 2026-11-06

### How do I start reviewing a case?

- id: hdi-reviewing-002
- roles: reviewer
- surfaces: web
- steps:
  1. Open **VA Review**.
  2. On the case press **Review case**.
- notes: Reviewing is optional and sample-based: not every coded case is reviewed, and cases never picked simply stay available. You hold one review at a time. Refusals you may see: "Only reviewer-eligible submissions can start reviewer coding.", "A reviewer final COD already exists for this submission.", "Your profile does not support reviewing forms in <language>.", "This submission belongs to a unit outside your reviewing scope."
- sources: coding-workflow; `app/services/reviewer_coding_service.py`; `mobile/digitva-collect/src/workspace/QueueScreen.tsx`
- checked: 2026-11-06

### What do I do in a review?

- id: hdi-reviewing-003
- roles: reviewer
- surfaces: web
- steps:
  1. Read the case in the category list.
  2. Expand **Coder's cause of death** if you want to see the coder's assessment (it is collapsed by default; **Details** opens it).
  3. Save your own Narrative Quality Assessment and Social Autopsy if the project uses them.
  4. Enter your own cause of death (same forms as a coder) and save the final cause.
- notes: Reviewing is a second, independent coding, not accept or reject. Your final cause is the one that counts; the coder's is kept in history as superseded. The coder's record is never changed.
- sources: coding-workflow; docs/policy/final-cod-authority.md; `mobile/digitva-collect/src/workspace/CaseWorkspaceScreen.tsx` (`CoderCodReference`); `app/routes/api/va_case.py`
- checked: 2026-11-06

### Can I see the coder's decision while I review?

- id: hdi-reviewing-004
- roles: reviewer
- surfaces: web
- steps:
  1. In the review, open **Coder's cause of death** and press **Details**.
- notes: The reviewer workspace serves the coder's Step 1, final cause and not-codeable report as read-only reference. Some help pages say reviewers work without seeing the coder's decision; the screen does show it.
- sources: `app/routes/api/va_case.py` (reviewer branch of the workspace payload); `mobile/digitva-collect/src/workspace/CaseWorkspaceScreen.tsx`
- checked: 2026-11-06

### How does reviewing work in a masked ICD-10 project?

- id: hdi-reviewing-005
- roles: reviewer
- surfaces: web
- steps:
  1. Step 1: enter your immediate and antecedent causes and press **Save Assessment**.
  2. Step 2: read the SmartVA result and choose the final underlying cause, then save.
- notes: Same two steps as a coder. SmartVA is shown only in Step 2.
- sources: coding-workflow; `mobile/digitva-collect/src/workspace/SimpleCodPanel.tsx`; `app/services/reviewer_coding_service.py`
- checked: 2026-11-06

### How does reviewing work in a masked ICD-11 (DORIS) project?

- id: hdi-reviewing-006
- roles: reviewer
- surfaces: web
- steps:
  1. Step 1: the certificate starts as a copy of the coder's. Edit it, press **Process current certificate**, confirm your own underlying cause and press **Save Step 1**.
  2. Step 2: choose your final cause (Step 1 cause, SmartVA result, or your own ICD-11 code) and press **Save final cause**.
- notes: Your changes never alter the coder's record.
- sources: coding-workflow; icd11-codes; `mobile/digitva-collect/src/workspace/doris/DorisPanel.tsx`
- checked: 2026-11-06

### How long do I have, and how do I give up a review?

- id: hdi-reviewing-007
- roles: reviewer
- surfaces: web
- steps:
  1. Submit your final cause within one hour of starting.
  2. To give up earlier, open **VA Review**, press **Release case** and confirm.
- notes: On timeout or release your review, NQA and Social Autopsy are cleared; "The saved Step 1 is kept" and the case returns to the reviewer pool. The page says "Review case released. Step 1 is kept; NQA and Social Autopsy are cleared." Saved NQA and Social Autopsy are intermediate: only the final cause completes a review.
- sources: docs/policy/coding-allocation-timeouts.md ("Reviewer release"); `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; `mobile/digitva-collect/src/strings/en.json` (`releaseReviewWarning`)
- checked: 2026-11-06

### How do I resume a review in progress?

- id: hdi-reviewing-008
- roles: reviewer
- surfaces: web
- steps:
  1. Open **VA Review** and press **Resume case**.
- notes: "You already have an active reviewer allocation." means finish or release it before starting another.
- sources: `mobile/digitva-collect/src/workspace/QueueScreen.tsx`; `app/services/reviewer_coding_service.py`
- checked: 2026-11-06

### How do I see the cases I have reviewed?

- id: hdi-reviewing-009
- roles: reviewer
- surfaces: web
- steps:
  1. Open **VA Review** and look at **My reviewed cases**.
  2. Press **View case**.
- notes: "No reviewed cases yet." when empty.
- sources: `mobile/digitva-collect/src/workspace/QueueScreen.tsx`
- checked: 2026-11-06

### Which cause is final when the reviewer and coder differ?

- id: hdi-reviewing-010
- roles: reviewer, coder, data_manager
- surfaces: both
- steps:
  1. The reviewer's final cause replaces the coder's as the authoritative one.
- notes: The coder's cause stays in history marked superseded. DigitVA has no separate reconciliation screen for disagreements. A coder who also holds a reviewer role may review a case they coded; there is no self-review guard.
- sources: docs/policy/final-cod-authority.md; docs/policy/coding-workflow-state-machine.md ("Reviewer authority"); docs/policy/training-demo-project.md
- checked: 2026-11-06

### Why can't I review on my phone?

- id: hdi-reviewing-011
- roles: reviewer
- surfaces: android
- steps:
  1. Review in the browser (**VA Review**), or use the Collect Plus build (**Review cases** in Settings).
- notes: The normal Collect app says "Coding and review are done in the DigitVA web app, not on this phone."
- sources: `mobile/digitva-collect/src/nativeRouteScreens.native.tsx`; `mobile/digitva-collect/src/nativeRoutes/settings.tsx`
- checked: 2026-11-06

### What do I do with the Narrative Quality Assessment as a reviewer?

- id: hdi-reviewing-012
- roles: reviewer
- surfaces: web
- steps:
  1. Open **Narration / Documents**, answer Q1. to Q6. and press **Save narrative quality**.
- notes: Same form as for coders. Unlike coders, reviewers are not blocked from saving the final cause by missing NQA. Social Autopsy gates reviewers only if the project enables it for reviewers.
- sources: docs/policy/narrative-quality-assessment.md; `app/services/case_content_service.py` (`final_blockers`)
- checked: 2026-11-06

### What is a mentoring institution?

- id: hdi-reviewing-013
- roles: mentor, coder, reviewer
- surfaces: web
- steps:
  1. Open **More** and then **Mentoring Institution** in the menu to see your institution and the districts it supports.
- notes: A medical college supports linked districts by coding and reviewing. Its doctors can hold coder, reviewer, coding tester or viewer-with-names roles. Mentors appear on a mentoring roster, not in district headcounts. Staff membership gives no project access by itself; a district manager grants roles.
- sources: mentoring-institutes; `mobile/digitva-collect/src/web/MentoringScreen.tsx`; `app/templates/admin/panels/mentor_institutes.html`
- checked: 2026-11-06

### I am mentoring staff and see no districts or roles. What do I do?

- id: hdi-reviewing-014
- roles: mentor
- surfaces: web
- steps:
  1. Open **Mentoring Institution**.
  2. If it says "No Mentoring Institution Membership", ask your Institute Admin or a platform administrator to add you.
  3. If you are a member but have no roles, ask the District Programme Manager or Project Lead of a supported district to assign your Coding, Review or Viewer role.
- notes: "No districts attached yet." means an administrator has not attached districts to your institute.
- sources: `mobile/digitva-collect/src/web/MentoringScreen.tsx`; mentoring-institutes
- checked: 2026-11-06

### How does an Institute Admin add faculty or resident staff?

- id: hdi-reviewing-015
- roles: mentor
- surfaces: web
- steps:
  1. Open **Mentoring Institution** and the staff roster ("Staff Roster").
  2. Press **Add Faculty / Resident Staff**.
  3. Fill in Full Name, Email, Confirm Email, optional Designation / Job Title, optional Mobile Number (10 digits) and at least one Coding Language.
  4. Press **Send Invitation**.
- notes: Name, email, matching confirmation and a language are required. After the person verifies their email, the District Programme Manager assigns district roles. The institute admin does not grant district roles.
- sources: `mobile/digitva-collect/src/web/MentoringScreen.tsx`; `app/routes/admin_mentor_institute.py`
- checked: 2026-11-06

### How do I remove someone from the institute?

- id: hdi-reviewing-016
- roles: mentor
- surfaces: web
- steps:
  1. In the staff roster press **Remove from Institute** on the person.
  2. Press **Confirm Removal**.
- notes: Any active mentoring roles they hold in the institute's districts are deactivated. Nothing is deleted. An institute admin cannot remove themselves, and only a platform administrator can remove another admin.
- sources: `mobile/digitva-collect/src/web/MentoringScreen.tsx`; `app/routes/admin_mentor_institute.py`
- checked: 2026-11-06

### How does an administrator set up a mentoring institute?

- id: hdi-reviewing-017
- roles: admin
- surfaces: web
- steps:
  1. In the admin console open **Mentoring institutes**.
  2. Enter an Institute code and name and press **Create institute**.
  3. Under Attached districts, enter the Project ID, find districts and press **Attach district** (or **Detach**).
  4. Under Staff, link an existing account or **Create staff account**.
- notes: Staff membership gives no project access: assign ordinary unit grants separately in Access Grants. Removing staff deactivates their mentor grants in these districts unless another institute still covers them.
- sources: `app/templates/admin/panels/mentor_institutes.html`; `app/routes/admin_mentor_institute.py`
- checked: 2026-11-06

### Can mentors see a coder-by-coder performance view?

- id: hdi-reviewing-018
- roles: mentor
- surfaces: web
- steps:
  1. No such view exists yet. Use **VA Review** and **VA Code** for your own work.
- notes: The mentor view policy is a draft and not built.
- sources: docs/policy/mentor-view.md
- checked: 2026-11-06
