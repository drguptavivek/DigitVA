---
title: AI help for interview and narrative quality
doc_type: policy
status: deferred
owner: engineering
last_updated: 2026-11-06
---

# AI help for interview and narrative quality

Owner direction, 2026-11-06:

- AI is built in to get **better quality data** in WHO VA interviews and
  narratives.
- An external model API is allowed.
- Projects can configure it to suit their scenario.

On hold (owner 2026-11-06): kept as a draft for later; do not build.

## What it does

AI makes suggestions to people; it never changes data itself.

- **While interviewing** (Collect and Collect Plus, and the web form), the
  interviewer can ask for a check before Send. They also get one on Send, if
  the project turns that on.
  - **Narrative check.** It looks for missing elements: who is telling the
    story, when the illness began and how long it lasted, the order of
    symptoms, care sought and where, and the place and circumstances of
    death. It also flags parts too vague to code. It returns short follow-up
    questions in the interview language.
  - **Consistency check.** It finds answers that contradict each other or the
    narrative. Examples: sex against pregnancy questions, age against the
    module, or "no fever" while the narrative describes fever. It also flags
    implausible values and key sections left as "Don't know" when the
    narrative answers them.
- **In Narrative QA and review**, reviewers see the same findings next to the
  case. They may use them in their NQA scoring.
- **Every finding is one of two kinds:**
  - **advisory:** shown, can be dismissed;
  - **confirm:** the interviewer must fix it, or keep it with a short reason.

  Each finding names the field or the sentence it is about.
- **Never automatic.** No answer, narrative or code is changed by the model.
  The interviewer edits, or the edit goes through the existing revision flow.
- **Never blocks work.** If the AI is off, offline, slow or failing, the
  interview saves and sends as it does today. A check that could not run is
  shown as "not checked", never as passed.

## Privacy and data handling

- The phone never calls the external API and never holds its key. The phone
  asks the DigitVA server, and the server calls the model with a key kept
  only in server secrets.
- **Before anything leaves the server, the request is de-identified:**
  - Names, phone numbers, addresses, ID numbers (ABHA and others), GPS
    points, free-text identifiers and the interviewer's details are removed
    or replaced with role tags ("[deceased]", "[respondent]", "[village]").
  - Dates become intervals relative to death.
  - Audio, photos and attachments are never sent.
  - A test suite of planted identifiers must come out clean.
- **The vendor** works under a data processing agreement, with no training on
  our data and the shortest retention it offers. Only text from projects
  that turned the feature on is sent.
- **Projects and consent.** Each project turns AI on explicitly (off by
  default). Its consent text states that de-identified answers may be
  checked by an external service. Demo and training projects use the same
  path, but on synthetic data.
- **Records.** For each check the server records:
  - case, form version and answers hash;
  - checks run, model and version, prompt version;
  - latency and the number of findings;
  - what the user did with each finding.

  It never stores the de-identified request or the raw response beyond the
  findings, and never logs PII.

## Configuration

Settings are per project, with optional per-site overrides, edited by project
admins in the admin screens:

- On or off, and which checks run (narrative, consistency).
- When checks run: on request only, on Send, or both. They can also run
  after sync on the server, for interviews sent offline.
- Strictness: for each check, which findings are advisory and which need
  confirmation.
- The language of follow-up questions (the interview language by default).
- Extra project rules written by the admin, in plain words, added to the
  check (for example, "always ask about snake bite in this district").
  These are versioned and shown on each finding they produced.
- Presets for common scenarios, which admins can start from and change:
  - household survey;
  - facility death;
  - training (everything advisory, with explanations);
  - research (strict).
- The model and endpoint are server settings, not project settings. Projects
  pick a quality level (fast or thorough), and the server maps it to a
  model.

## Speed

- **Targets:** a narrative or consistency check answers within 3 s at p95 for
  one case, and 6 s for thorough mode. The phone shows progress, and the
  user can keep working.
- **One call per check run.** The prompt carries the form version's question
  text once, and the findings come back as structured JSON. Findings are
  cached by answers hash, prompt version and model, so an unchanged
  interview is never checked twice.
- **Speed tools:** prompt caching for the fixed instrument text, streaming so
  findings appear as they come, and a hard timeout (10 s) that shows "not
  checked".
- **After sync,** server-side checks run in the Celery queue in batches, with
  rate limits. They never run in request paths, dashboards or list queries.
  Lists read stored findings through an index on (case, answers hash).
- **The database side follows the existing perf rules:**
  - index-backed queries;
  - no per-row queries;
  - bounded work.

  The NQA and review lists show a finding count without loading findings.

## Measuring it

Each project dashboard shows:

- the share of cases checked;
- findings per case;
- the share of findings acted on;
- NQA scores before and after AI was turned on.

If a check's findings are mostly dismissed, its prompt is reviewed.
