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

## The support-model host: a dedicated Mac mini or GPU workstation (owner decisions 2026-10-27)

The "local AI workstation" is a dedicated machine, used only for this:
either an Apple-silicon Mac mini, or a Linux workstation or server with an
NVIDIA GPU. Either qualifies, under the same rules. It runs every support model and pushes results to the server
through the API:

- **Narrative stage:** PII detection and de-identification, the quality
  score, translation and symptom hints (this policy).
- **Documents:** the vision-language model reading death summaries and
  medical records (`digitva-sxg9.1`).
- **Algorithms:** InterVA5 and EAVA, the additional cause-of-death
  algorithms (`digitva-13gs`), fed the same personal-data-free answer export
  as SmartVA. SmartVA stays on the server, where it runs today.
- **Teacher:** the teacher model for distilling the on-phone classifier
  (`digitva-fixy.1`).

**How it runs:**
- It connects outward only. It signs in with the device-bound
  `narrative_processor` machine account (renamed `support_models` if that
  reads better), leases work items and uploads versioned results. DigitVA
  never connects into it.
- Each work item carries only what its task needs:
  - the algorithms get the scrubbed answers;
  - the narrative tasks get the pseudonymised narrative;
  - the document model gets the page images.

  Results never include identifiers.
- **Software:** one worker, with a runtime per platform.
  - **Mac mini:** native services under launchd, using MLX and mlx-vlm,
    llama.cpp with Metal, PyTorch with MPS, and R (arm64). Docker on macOS
    cannot use the Apple GPU.
  - **NVIDIA host:** Docker images with the NVIDIA Container Toolkit, using
    vLLM or llama.cpp with CUDA, PyTorch with CUDA, and R.
  - The job contract, results and machine account are the same on both, so
    the host can be swapped or a second one added.
- It sends a heartbeat. The server shows when the host was last seen and
  how deep the queue is, so a stopped host is visible and the cases simply
  wait. Cases are never processed elsewhere as a fallback.
- **Host security:**
  - FileVault on, with a dedicated macOS account, automatic security
    updates and the firewall on with no inbound services;
  - physically secured, with named operators only;
  - nothing kept after upload except the in-flight queue;
  - logs hold no narrative or answer text.
- **Sizing and choice:**
  - **Mac mini (M4 Pro, 48–64 GB unified memory):** holds a 7B-class
    vision model, translation and an 8B text model at once. It is quiet,
    low power and little upkeep, and enough for phase 1 (the quality
    classifier, InterVA5 and EAVA) and moderate volumes.
  - **NVIDIA workstation or server (one 24–48 GB GPU, for example an RTX
    4090/5090 or an A6000-class card):** faster batch throughput for the
    vision and text models, and the widest model support (vLLM). It needs
    more power, cooling and driver upkeep.
  - Choose the NVIDIA host for large document volumes or models above 8B;
    otherwise the Mac mini.

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

1. Settled 2026-10-27: a dedicated Mac mini (above).
2. Which languages first? The mix of narration languages per project decides
   this.
3. Who reviews translations and symptom hints for the quality gate?
4. Adopt the proposed consent item 7 (`narrative_automated_processing`) into the respondent
   consent notice under legal review (`digitva-athy`).
