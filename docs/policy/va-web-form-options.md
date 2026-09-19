---
title: VA Web Form Options Contract
doc_type: policy
status: draft
owner: DigitVA Data Collection
last_updated: 2026-09-19
---

# VA Web Form Options Contract

Everything the DigitVA VA web form accepts as an option, in one place, so the
route that renders a form knows exactly what it may supply and the project API
knows exactly what it must serve.

The rule this document exists to enforce: **the form itself decides nothing.**
It renders the instrument it is given, in the language it is told, with the
extensions the project enabled. Every choice belongs to project configuration
and arrives as an option. Anything the form decides for itself is a default
that some project will eventually need to override, so it is listed here even
where today's value is a constant.

## Where an option can come from

| Tier | Source | Changes per |
|---|---|---|
| 1. Instrument | The compiled instrument (`form_type_code`) | Questionnaire |
| 2. Project | Project settings, served by the organization/project API | Project |
| 3. Session | The route, from the draft and the signed-in user | Draft / user |

A tier-2 option must never be hardcoded in a template or inferred from the
instrument. That is the whole point of the tier: two projects running the same
questionnaire differ only by tier-2 options.

## The complete option surface

### Tier 1 — which questionnaire

| Option | Type | Set today | Notes |
|---|---|---|---|
| `instrument` | `InstrumentDefinition` (property) | **No** — falls back to the bundled WHO 2022 instrument | The host must pass this once more than one form type is live. Built offline; never compiled at request time. |
| `formTypeCode` | string, inside the instrument | Emitted by the builder | The mapping key. Survives a republish that changes `version`. |
| `enabled_extensions` | string[] | **No** — not yet an option | `digitva_core`, `social_autopsy`, `intake_screen`, `geography`, `narration_language`, `death_summary`, `abha`. Decides which sections exist. |

### Tier 2 — project configuration

| Option | Type | Set today | Notes |
|---|---|---|---|
| `locale` | string (attribute) | **Hardcoded `"en"`** | The display language of labels, hints and choices. |
| `available_locales` | string[] | **No** | Which languages this project's users may switch to. Drawn from the system-wide translation catalogue, not from the form. |
| `uiTranslations` | `WhoVaUiTranslations` | **No** | Chrome strings (buttons, validation). Separate from instrument translations. |
| `narration_languages` | `{code,label}[]` | **No** | Options for `narr_language` — the language the narrative was *recorded* in. Distinct from `locale` and from the instrument's own "Interview language" question. Per-project checkboxes. |
| `geography` | level + unit codes | Partly — via the units API | Feeds `survey_state`/`survey_district`/`survey_block` and `org_<level_code>_code` routing. Comes from the project's organization hierarchy. |
| `show-guidance` | boolean (attribute) | **No** — defaults off | Whether source guidance notes render. An interviewer-training setting. |
| `attachment_policy` | image/audio/PDF limits | **No** — engine defaults | Size and dimension ceilings. |

### Tier 3 — session and runtime

| Option | Type | Set today | Notes |
|---|---|---|---|
| `draft-id` | string (attribute) | Yes | |
| `draftStore` | `WhoVaDraftStore` | Yes | Debounced PATCH to the intake API. |
| `auto-save-draft-on-change` | boolean (attribute) | Yes | |
| `auto-save-draft-interval-ms` | number \| false | No — default | |
| `initialData` / prefill answers | `SubmissionData` | Yes, via `PREFILL.answers` | |
| `lockedQuestionNames` | string[] | Yes, via `PREFILL.lockedQuestionNames` | Answers carried from death registration that the interviewer may not contradict. |
| `platform` | `WhoVaPlatformServices` | **No** | Capture hooks: audio, image, file, date picker, barcode, geopoint, drawing. Web supplies browser implementations; the native app supplies its own. This is the single seam between the shared engine and the host platform. |
| `org_unit_id` | uuid | Yes, via the picker | The deepest unit selected. Server re-validates against grants regardless of what the client sends. |

## What the project API must serve

The options in tier 2 are per-project and the form route has no other way to
learn them. They belong next to the organization tree, which is already the
per-project configuration the intake page fetches:

```
GET /api/v1/organization/<project_id>/form-options
```

```jsonc
{
  "project_id": "...",
  "config_version": "...",          // moves when any option changes, like tree_version
  "enabled_extensions": ["digitva_core", "geography", "narration_language"],
  "form_types": [                    // questionnaires live for this project
    {"form_type_code": "WHO_2022_VA_SOCIAL", "title": "...", "is_default": true}
  ],
  "default_locale": "en",
  "available_locales": [{"code": "en", "label": "English"}],
  "narration_languages": [{"code": "hi", "label": "Hindi"}],
  "show_guidance": false
}
```

Notes on the shape:

- `config_version` exists for the same reason `tree_version` does: a client
  caches the options and revalidates, so a settings change reaches a page that
  is already open.
- Geography is **not** repeated here. It is the organization tree, served by
  `GET /api/v1/organization/<project_id>/units`, and duplicating it would
  create two sources for the codes that drive routing.
- `available_locales` is the intersection of what the project allows and what
  the system has translations for. The form must tolerate a locale it has no
  strings for by falling back, not by failing.

## Open questions

| # | Question |
|---|---|
| Q6 | Do the standardized project geography codes bind to `org_<level_code>_code` as the same codes, or through a mapping? |
| ~~O1~~ | ~~Pre-built instrument variants, or a filter over one superset at load?~~ **Resolved 2026-09-19: pre-built variants.** Not for tidiness — an instrument whose identity depends on request state cannot be tied back to what the respondent was actually shown, which makes a submission hard to defend evidentially. Immutable instruments, selected by `form_type_code`. |
| ~~O2~~ | ~~Who owns `attachment_policy`?~~ **Resolved 2026-09-19:** a system-wide constant until a project has a real reason otherwise; making it project-level later is additive. |

## Related

- `docs/policy/web-intake.md`
- `docs/policy/organization-model.md`
- `docs/planning/va-data-collection-plan.md`
