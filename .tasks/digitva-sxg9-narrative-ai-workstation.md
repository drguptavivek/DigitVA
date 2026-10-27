# digitva-sxg9: narrative AI on a local workstation (plan)

Status: plan only. The policy draft is `docs/policy/narrative-ai-processing.md`
and needs owner sign-off first.

## Shape

```
DigitVA server                                  Local AI workstation (India)
  work queue (per enabled project)  <-- lease --  worker (machine account)
  pseudonymised narrative + language  -------->   models run locally
  results table (versioned)         <-- upload --  score / translation / hints
  coder and supervisor UI shows suggestions
```

## Pipeline order per narrative

1. Server-side rule pseudonymiser.
2. Lease to the workstation.
3. PII detection and de-identified copy.
4. Quality score.
5. Translation.
6. Symptom hints.

Steps 4–6 read only the de-identified copy.

## Phases

0. **PII detection and de-identification (built together with phase 2, since
   every later stage depends on it).**
   - **Detector:** a named-entity model for Indian languages (for example
     AI4Bharat IndicNER) plus Indian phone and Aadhaar-like number patterns.
     A constrained LLM pass, JSON spans only, catches names and places the
     model misses.
   - **Output:** spans (offset, length, category) and a de-identified copy
     with typed placeholders, the same value mapping to the same
     placeholder within a narrative. Spans are stored as offsets only,
     never the detected values.
   - **Use:** flag residual PII to the data manager; the de-identified copy
     feeds steps 4–6, research exports and the training/demo copy.
   - **Gate:** recall and precision on a hand-labelled sample per language
     (about 200 narratives each). Recall is the headline: a missed name is
     the costly error.
   - Also measure how much the server-side rules alone already catch. That
     shows what the model adds.
1. **Narrative quality model (fits current policy).**
   - Training data: the ~6,800 coder NQA ratings on dev (rating and score)
     with their narratives. Train a TF-IDF plus logistic regression model; a
     small multilingual encoder is a later option. Split by site and time so
     the evaluation is not flattered.
   - Output: a predicted rating and probability. The supervisor's list flags
     probable Poor or Cannot Grade narratives at intake, so the case can go
     back to the interviewer.
   - Gate: agreement with held-out coder ratings, reported per language.
   - Runs on a CPU. Training could even run on the server, but the
     workstation keeps one path for all models.
2. **Machine account and results API.**
   - Role `narrative_processor` on a device-bound account (`auth_devices`).
   - `POST /api/v1/narrative-ai/lease`: N work items (id, pseudonymised text,
     language, task), with a lease timeout like SmartVA's batch claiming.
   - `POST /api/v1/narrative-ai/results`: id, task, model, version, payload.
   - New tables: `va_narrative_ai_work` (queue and lease) and
     `va_narrative_ai_results` (append-only, versioned; task `pii` stores
     spans and the de-identified copy). Migration; purge
     PLAN entries; a project-level enable flag.
   - The worker is a small Python CLI shipped as its own package or
     container. No inbound ports.
3. **Translation.**
   - Model: AI4Bharat IndicTrans2 (open, 22 scheduled languages), on a GPU.
   - Shown beside the original narrative, labelled "machine translation".
   - Gate: a native-speaker review of a sample per language.
4. **Symptom hints.**
   - Model: an open LLM (8B–32B, for example Qwen or Llama) with a
     JSON-schema prompt that maps to WHO 2022 VA indicators. It runs on the
     translation, or on the original if supported.
   - Shown only where the hint disagrees with the form answer, for example
     "Narrative suggests fever; form says no".
   - Never merged into answers or SmartVA input.
   - Gate: reviewed precision on a sample. Negation handling must be tested
     explicitly.

## Reuse

- `app/services/training_pseudonymiser.py`: de-identify the narrative
  before leasing.
- The SmartVA run and batch-claim pattern (`app/models/va_smartva_runs.py`)
  for leasing and retries.
- Device auth (`app/models/auth_devices.py`) for machine identity.

## Not in scope

Automated cause of death, SmartVA or InterVA on merged data, sending
narratives to external AI services, and keeping narratives on the
workstation.

## Hardware (rough)

- Phase 1: CPU only.
- Phases 3–4: one GPU with 24 GB (8B model, IndicTrans2) or 48 GB (32B
  model); 64 GB RAM; encrypted NVMe.
