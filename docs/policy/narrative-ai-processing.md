---
title: Narrative AI Processing Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-10-27
---

# Narrative AI Processing Policy (draft)

## Purpose

Verbal autopsy narratives (`Id10476`, `narration`) hold clinical detail that
the closed questions miss. They are often in a regional language, and their
quality varies. DigitVA runs open AI models over them to help people:

1. **PII detection and de-identification.** Find names, places, phone and
   ID numbers, and addresses left in the narrative, and produce a
   de-identified copy;
1. a **quality score** that predicts the coders' NQA rating;
2. a **translation** into English, shown beside the original;
3. **symptom hints**: symptoms the narrative mentions that the form answers
   do not reflect.

Tracked in `digitva-sxg9`. Plan: `.tasks/digitva-sxg9-narrative-ai-workstation.md`.

## Owner decisions (2026-10-27)

- **Where the models run.** On a local AI workstation that DigitVA's operator
  controls, in India, or an equivalent GPU host in India. No narrative goes to
  a third-party AI service.
- **The workstation connects outward only.** It pulls work from DigitVA and
  uploads results through the API. DigitVA never connects into the
  workstation's network.

## Rules

- **Suggestions only.** Results never overwrite an ODK answer, the original
  narrative, an NQA rating or a cause of death. ODK stays the source of
  truth. A coder or supervisor decides.
- **No automated cause of death.** DigitVA does not assign causes from
  narrative AI without physician coding. Running SmartVA or InterVA on
  merged form and narrative data is out of scope. If it is ever added, it is
  a labelled research output beside the standard run, never in place of it.
- **De-identification happens in two layers, then everything else uses the
  de-identified text.**
  1. **On the server, by rules:** the existing pseudonymiser
     (`app/services/training_pseudonymiser.py`) replaces the case's own
     names, address and place tokens and phone numbers with consistent
     synthetic values before the workstation gets the text. The workstation
     receives that text, its language and a work-item id (not `va_sid`),
     and nothing else from the case.
  2. **On the workstation, by a model:** a PII detector (a named-entity model
     for Indian languages, with an LLM pass for what it misses) finds what
     the rules missed: other people's names, villages, hospitals, phone and
     ID numbers (Aadhaar-like), and addresses. It returns span offsets and
     categories plus a de-identified copy, with each span replaced by a
     typed placeholder such as `[PERSON_1]` or `[VILLAGE_1]`.

  Quality scoring, translation and symptom hints run only on the
  de-identified copy.
- **What de-identification results are for:**
  - **Flags:** a narrative with residual PII is flagged to the data manager.
  - **Research and repository exports:** they use the de-identified copy in
    place of the raw narrative.
  - **Training/demo copies:** the same.
  - **Any later external AI use:** that would need its own policy change
    and could only send the de-identified copy.

  The original narrative is never changed. Coders with case access still
  see the original.
- **PII results are sensitive too.** Detected spans are stored as offsets and
  categories, never as a copy of the detected value. The de-identified copy
  is stored. Logs and audit rows carry counts per category only.
- **Machine identity.**
  - The workstation signs in as a device-bound machine account with one role
    (`narrative_processor`), reusing the device-auth tables
    (`app/models/auth_devices.py`).
  - The role can lease work items and post results, and nothing else. It has
    no UI, no other API and no export.
  - The account can be revoked at once from admin.
- **Workstation duties.** The workstation holds personal data while it works
  and has the same DPDP duties as the server:
  - full-disk encryption and a hardened OS;
  - named operators only;
  - no narrative kept after upload, except an in-flight queue cleared on
    success;
  - logs hold no narrative text.
- **Versioned and auditable.**
  - Each result records the model name, model version, task and time.
  - Reprocessing adds a new version and keeps the old one.
  - Every lease and upload is logged, with no narrative text in the log.
- **Per project, off by default.** A project's PI enables narrative AI only
  after its consent notice and ethics approval cover automated processing.
  Training/demo data may be enabled for testing.
- **Consent (DPDP).**
  - The respondent notice gets its own optional purpose,
    `narrative_automated_processing`. The text is in
    `docs/policy/respondent-consent-notice-draft.md`, "Proposed addition:
    automated processing of the narrative".
  - Where the project requires consent, a narrative is processed only when
    its consent record answers that purpose "yes". No answer means no
    processing, which covers older notice versions too.
  - A withdrawal stops processing and deletes that case's narrative-AI
    results.
- **Quality gate.** A model's suggestions show to users only after it is
  measured against held-out coder data:
  - **PII detector:** recall on a hand-labelled sample per language (missed
    PII is the costly error), reported with precision;
  - **quality score:** agreement with held-out NQA ratings;
  - **translation:** reviewed by a native speaker on a sample;
  - **symptom hints:** precision on a reviewed sample.
  
  The results are recorded in `docs/current-state` before release.

## Open questions for the owner

1. Workstation or a GPU host in AWS Mumbai next to the server? Both meet the
   rules above. The choice is about cost and upkeep.
2. Which languages first? The mix of narration languages per project decides
   this.
3. Who reviews translations and symptom hints for the quality gate?
4. Adopt the proposed consent item 7 (`narrative_automated_processing`) into the respondent
   consent notice under legal review (`digitva-athy`).
