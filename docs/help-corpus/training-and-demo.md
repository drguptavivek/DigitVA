---
title: How-Do-I Corpus - Training and Demo
doc_type: help-corpus
status: draft
owner: engineering
last_updated: 2026-11-06
---

# How-Do-I Corpus - Training and Demo

Entries for the training project, demo coding projects, the synthetic demo and
the public demo. Format and truth rules: `docs/policy/help-chatbot.md`.

### How do I practise coding without touching real cases?

- id: hdi-training-001
- roles: coder, reviewer, interviewer
- surfaces: web
- steps:
  1. Ask your trainer to add you to a training session with a role.
  2. Open **Training** in the menu, then **Start** on the overview.
  3. Use the **Coding** sub-item.
- notes: The Training menu appears only if you are an active participant in an active session. Training work stays in the training project and is separate from real cases. You use your own account; no practice accounts are made.
- sources: training-demo; docs/policy/training-demo-project.md; `mobile/digitva-collect/src/web/navTabs.ts`
- checked: 2026-11-06

### Why can't I see the Training menu?

- id: hdi-training-002
- roles: coder, reviewer, interviewer
- surfaces: web
- steps:
  1. Ask your trainer to add you with your account's email address.
- notes: The screen says "You have not been added to an active training session." A closed session removes the menu. Training is a browser feature; the phone app works real projects only.
- sources: `mobile/digitva-collect/src/strings/en.json` (`trainingNone`); docs/policy/training-demo-project.md
- checked: 2026-11-06

### What do I do on the training overview?

- id: hdi-training-003
- roles: coder, reviewer, interviewer
- surfaces: web
- steps:
  1. Read the confidentiality notice.
  2. Press **Start**. The page stays available from the Training menu.
  3. Open your area from "Your training areas".
- notes: Cases are consented interviews; names, addresses and phone numbers in text answers are replaced with made-up ones. Photos, documents and audio are original: do not copy, photograph or share them.
- sources: `mobile/digitva-collect/src/strings/en.json` (`training*`); training-demo
- checked: 2026-11-06

### How many cases do I code in training, and which are mine?

- id: hdi-training-004
- roles: coder
- surfaces: web
- steps:
  1. Open **Training**, then **Coding**. The screen names your coder slot.
  2. Pick one of your 10 cases, read it and assign the cause of death.
- notes: "You hold coder slot N: ten cases are yours to code." Coders see only their own 10; reviewers and data managers see the whole session. Your coding languages must include the narration language of your slot's cases (for example Hindi), or you cannot be added.
- sources: `mobile/digitva-collect/src/strings/en.json` (`trainingCoderSlot`, `trainingCodingStep`); docs/policy/training-demo-project.md
- checked: 2026-11-06

### How long can I recode a training case?

- id: hdi-training-005
- roles: coder
- surfaces: web
- steps:
  1. Open **My coded cases** in the training coding screen and press **Recode** within 60 minutes of saving.
- notes: The training project's recode window is 60 minutes instead of 24 hours, so your case reaches review quickly. The usual one-hour allocation timeout still applies.
- sources: viewing-history; docs/policy/training-demo-project.md; docs/policy/coding-workflow-state-machine.md ("Recode Window")
- checked: 2026-11-06

### Can I hold a training case and a real case at the same time?

- id: hdi-training-006
- roles: coder, reviewer
- surfaces: web
- steps:
  1. Resume or release each case from its own side (Training menu versus VA Code).
- notes: One allocation is allowed per side. A training case never blocks a real case, or the reverse.
- sources: docs/policy/coding-workflow-state-machine.md ("One active allocation per side")
- checked: 2026-11-06

### What do reviewers do in training?

- id: hdi-training-007
- roles: reviewer
- surfaces: web
- steps:
  1. Open **Training**, then **Review**.
  2. Review the coders' work across the session, and see its data, progress and exports.
  3. Open "Read the training report (progress and agreement)" for the trainer report.
- notes: This role is called reviewer and data manager in training. A trainee may review a case they coded.
- sources: `mobile/digitva-collect/src/strings/en.json` (`trainingReviewStep`, `trainingReadReport`); docs/policy/training-demo-project.md
- checked: 2026-11-06

### What is demo (practice) coding, and how is it different from real coding?

- id: hdi-training-008
- roles: coder
- surfaces: web
- steps:
  1. If your account has no project roles, press **Practice demo coding** on the home screen; it opens **VA Code**.
  2. Code a case exactly as in real coding.
- notes: In a project marked Demo / Training any signed-in user may code and no coder grant is needed. Allocations are revoked after 15 minutes. Your codes are temporary (default 10 minutes, set per project) and then removed, returning the case to the pool. Practice work does not count in output totals.
- sources: demo-coding; docs/policy/demo-coding-retention.md; `app/services/demo_project_service.py`; `mobile/digitva-collect/src/web/WorkspaceScreen.tsx`
- checked: 2026-11-06

### My practice code disappeared. Why?

- id: hdi-training-009
- roles: coder
- surfaces: both
- steps:
  1. Code the case again if you want to practise more.
- notes: Demo codes, NQA and Social Autopsy are deactivated when the project's retention ends and the case returns to ready for coding. The audit trail records the reason as demo expiry.
- sources: demo-coding; docs/policy/demo-coding-retention.md
- checked: 2026-11-06

### Can I practise reviewing on a demo project?

- id: hdi-training-010
- roles: reviewer
- surfaces: web
- steps:
  1. Start a review on a demo case; a demo coder's final code makes the case reviewable at once.
- notes: The review expires with the coder's demo code, even mid-review.
- sources: docs/policy/demo-coding-retention.md ("Demo Reviewing")
- checked: 2026-11-06

### What does a coding tester do?

- id: hdi-training-011
- roles: coding_tester
- surfaces: both
- steps:
  1. Use **VA Code** like a coder, to check forms, ICD lookup, NQA and Social Autopsy before regular coders start.
- notes: Testers bypass coding gates (disabled, dates, daily limit). Their output is flagged as tester output, never becomes a case result and returns the case to the pool.
- sources: coding-tester
- checked: 2026-11-06

### What is the signed-in synthetic demo?

- id: hdi-training-012
- roles: coder, reviewer, interviewer, data_manager
- surfaces: web
- steps:
  1. Sign in with the demo account for your role (an administrator supplies it).
  2. Open the help page "Synthetic Organization Demo" and use "Open ... workspace" for your role.
- notes: It is a separate synthetic project. Demo cases reset every Sunday at 11:00 p.m. India time; accounts, grants and settings stay. If the page says it is not enabled, an administrator has not opted the project in. Never enter real participant information.
- sources: organization-demo; docs/policy/organization-demo.md; `app/services/synthetic_demo_service.py`
- checked: 2026-11-06

### How do I try the whole system on the public demo?

- id: hdi-training-013
- roles: coder, interviewer
- surfaces: android
- steps:
  1. On the enrolment screen choose **Try the demo** and read the notice.
  2. Press **Create a demo account** (or **I already have a demo account**) with your own username and a password of at least 12 characters.
- notes: The demo exists only on deployments that enable it. Do not enter real personal or health data; entries are visible to the demo team and your account is deleted 30 days after your last sign-in. There is no password reset in the demo.
- sources: docs/policy/public-demo.md; `mobile/digitva-collect/src/strings/en.json` (`demo*`)
- checked: 2026-11-06

### Can I try the DORIS tool without signing in?

- id: hdi-training-014
- roles: coder
- surfaces: android
- steps:
  1. On Collect Plus open Help and press **Try DORIS (offline demo)**.
  2. Load an example certificate or choose **Blank certificate**, then process it.
- notes: Nothing is saved or sent; **Reset to the loaded example** restores the certificate. Do not type real patient details.
- sources: `mobile/digitva-collect/src/strings/en.json` (`dorisDemo*`); docs/current-state/expo-client.md
- checked: 2026-11-06

### How do I practise ICD search for a given age and sex?

- id: hdi-training-015
- roles: coder, coding_tester, reviewer
- surfaces: web
- steps:
  1. Open the help page "ICD Codes, VA Causes and the Coding Search" and follow "Try the coding search".
  2. Choose ICD-10 or ICD-11, an age group and a sex, then type.
- notes: Saves nothing.
- sources: icd-codes-search-demo
- checked: 2026-11-06

### As a trainer, how do I set up a training session?

- id: hdi-training-016
- roles: admin
- surfaces: web
- steps:
  1. Open the admin **Training sessions** panel and create a session, choosing 1 to 100 coder slots.
  2. Add existing users with one or more roles, singly or in bulk.
  3. Close the session when training ends.
- notes: Sessions are numbered S001, S002 and so on; each slot holds 10 pseudonymised cases. An unknown email is refused. Removing a participant or closing a session deactivates only training grants and deletes nothing. Admin only.
- sources: docs/policy/training-demo-project.md ("Trainer management")
- checked: 2026-11-06
