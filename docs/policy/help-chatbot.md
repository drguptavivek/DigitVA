---
title: Help Chatbot and How-Do-I Corpus Policy
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-11-06
---

# Help Chatbot and How-Do-I Corpus Policy

Owner direction, 2026-11-06 (bead `digitva-wawz`). This is the baseline the
corpus and the chatbot code are built against. Nothing here is built yet.

## Purpose

Signed-in users ask how to do something in DigitVA ("How do I recode a
death?", "How do I add a coder to a site?") and get a short answer with steps,
drawn only from a curated corpus, with a link to the source.

Today's help search (`app/services/ai_search_service.py`) only offers
typo-tolerant title and keyword matches. It does not use a language model.

## Audience

- Signed-in users of the web app only. The logged-out site keeps the public
  help pages and their search, with no chatbot. The Collect Android app does
  not get the chatbot; phones keep the help pages.
- Every signed-in role may use it. Answers favour entries tagged with the
  roles the user holds, but no corpus entry is secret, so another role's
  entry may be shown, labelled with that role ("Administrators do this…").

## Grounding

- The model answers only from retrieved text: the How-Do-I corpus, the help
  pages and the WHO VA definitions. It does not answer from its own
  knowledge.
- Every answer cites the corpus entry or help page it used, as a link.
- If no retrieved text covers the question, the chatbot says so and links the
  help index. It does not guess.
- It never states what a user is permitted to do in a specific project, which
  record is assigned to them, or any data value. It explains how the feature
  works and where to find it. Live state stays in the app's own screens.

## Data sent to the model

- The model receives the user's question, the retrieved corpus and help text,
  and the user's role names. No submission data, no case identifiers, no user
  record, no project data.
- Users are told not to type names or case details. Before the question leaves
  the server, a new redaction step removes phone numbers, email addresses,
  long digit runs (identifiers such as Aadhaar) and DigitVA case identifiers.
  This step is not built yet. The existing `redact_quoted` in
  `app/services/ai_analytics_sandbox.py` only strips quoted values from SQL
  errors and does not cover this.
- The chatbot uses the same provider and model configuration as AI analytics
  questions (`docs/policy/ai-analytics-questions.md`). It is off when no
  provider is configured.

## Limits and logging

- Rate limited per user. The monthly cost cap is an admin setting per
  deployment, with no fixed default amount; until an admin sets it, the
  chatbot stays off. When the cap is reached, the chatbot is switched off
  for the rest of the month and points to the help pages.
- The log keeps the time, the user, the corpus entries cited and whether an
  answer was given. Question text is kept for 30 days, then deleted. It is
  used to find gaps in the corpus.
- A thumbs-up or thumbs-down on each answer is recorded against the entries
  it cited.

## How-Do-I corpus

- **Location:** `docs/help-corpus/`, one Markdown file per area. Each file has
  this repo's docs front matter, with `doc_type: help-corpus`.
- **Entry format:** each entry is a level-3 heading phrased as the user would
  ask it, followed by a fixed field list:

  ```markdown
  ### How do I recode a death after the final cause is saved?

  - id: hdi-coding-012
  - roles: coder, reviewer
  - surfaces: web | android | both
  - steps:
    1. ...
    2. ...
  - notes: limits, common errors, what to do if the button is missing
  - sources: help page slug(s); code path(s) checked; policy file
  - checked: 2026-11-06
  ```

- **Truth:**
  - Every entry describes behaviour that exists in the code today, and is
    checked against the route, template or screen named in `sources`.
  - Planned features are left out.
  - Button and menu labels are copied from the templates or screens, not
    paraphrased.
- **Content:**
  - No passwords, test accounts, tokens, server names or internal URLs.
  - No real names or case data.
  - Examples use made-up values.
- **Ownership:**
  - A corpus entry is updated in the same change as the feature it describes.
  - An entry whose `sources` no longer exist is a failing check, to be added
    with the chatbot code.

## Owner decisions, 2026-11-06

- Provider: the one configured for AI analytics questions.
- Cost cap: an admin setting per deployment.
- Surfaces: web app only.
- Question text: kept 30 days, then deleted.
