---
title: VA Form Project Configuration Policy (extensions, languages, geography)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-18
---

# VA Form Project Configuration Policy

## Purpose

A DigitVA client does not render a questionnaire taken from a workbook. It
renders the **WHO VA 2022 base plus the extensions a project has switched on**,
with every option list supplied from project configuration. This policy fixes
what a project configures, where each option list comes from, and who may see
what.

It governs DigitVA's own clients. ODK Central collection is unaffected: those
forms carry their own choice lists, published with the form.

## Why configuration, not form content

Measured across the live deployment on 2026-09-18:

- The three ICMRVA forms (ND01, ML01, OD01) are **structurally identical** —
  538 questions, same names, same order — and differ *only* in the choice lists
  for `Site`, `survey_state` and the language questions.
- Each site's form offers just that site's languages: ND01 english + hindi,
  ML01 english + khasi, OD01 english + odia. Each form's `Site` has exactly one
  choice, because a site's form is locked to its site.
- The generic WHO workbook ships placeholder choices (`Language 2`,
  `Language 3`) which must never reach an interviewer.

So an option list describes a deployment, not a questionnaire. Baking one into
an instrument — or into the engine, as `DIGITVA_NARRATION_LANGUAGES` currently
is — is wrong for every deployment but one.

## What a project configures

### 1. Extensions

The WHO base is a subset; everything else is a layer on top. A project records
which layers it collects:

| Extension | Questions |
|---|---|
| `digitva_core` (always on) | `unique_id`, `Site`, `imagenarr`, `md_count` + `md_im1..30`, `comment` |
| `social_autopsy` | the social-autopsy sections |
| `intake_screen` | `introduction`, `instructions`, `confirm_inst` |
| `geography` | `survey_state`, `survey_district`, `survey_block`, `site_individual_id` |
| `narration_language` | `narr_language` |
| `death_summary` | `ds_available`, `ds_count`, `ds_im1..5` |
| `abha` | `abha_number`, `abha_address` (web intake only) |

A project picks layers; it does not pick a whole form. The deployed forms
decompose exactly this way — KEM_VAADU is the base plus `social_autopsy`; the
ICMRVA family adds `intake_screen`, `geography` and `death_summary`.

### 2. Narration languages

The options for `narr_language`: **the language the narrative was recorded in**.
Per-project selection over the system language list (`mas_languages`).

This is case data, not presentation. It reaches the coder and the SmartVA
free-text path, and it is normalized through `map_language_aliases`.

### 3. Display translations

**The language the questionnaire is shown in** — the WHO base's own `language`
question. Bounded by the translations the system actually holds, and
standardized system-wide rather than chosen per project.

**These two are different axes and must never be merged.** An interviewer may
read the form in English while the family speaks Khasi; the case must record
Khasi. That every deployed form happens to offer the same short list for both
is a property of those deployments, not evidence that one field is redundant.

### 4. Geography codes

Standardized in project settings, derived from the project's organization
hierarchy, and linked to form routing. One set of codes serves attribution,
routing and reporting rather than two parallel mechanisms.

**The project's geography codes and the routing codes are the same values.**
`mas_org_unit.unit_code` is free-form and unique per project, so a census code
is stored as the unit code itself: a District unit coded `088` means
`org_district_code = 088` is what routing reads, what a choices sheet offers,
what the picker submits and what reporting groups by. There is no mapping
table, and deliberately no second coding column on the unit — one value, one
reader.

That carries a trap worth stating before someone hits it as a failed import:
**`unit_code` is unique per project, not per level, and census codes are not.**
State `06` and a block numbered `06` in the same project collide. Indian census
state (01–36) and district (1–640) codes do not collide with each other, so
`06` (Haryana) and `088` (Faridabad) are safe as they stand; village and
sub-district codes repeat across parents and will collide. Seeding rule: use a
census code bare where it is unique within the project, and below district
prefix it with the parent (`088_0123`), keeping the bare code out of the unit
code. Unit codes are `^[A-Z0-9_]{1,32}$` — underscore is the separator, hyphens
are rejected by the validator — so prefix with the parent, not the full path,
which would not fit. The authoritative statement of this rule lives in
[organization model policy](organization-model.md).

The legacy `survey_state` / `survey_district` / `survey_block` fields predate
the organization model and are not themselves routing inputs; routing reads
`org_<level_code>_code` (decision O4).

## Exposure

Project configuration is served to clients by the project's own API, read once
at draft creation rather than assembled per request. The organization tree is
served by the organization API, which is the single reader of the tree, its
codes and its active rules.

## Who may fill, and for which unit

- Filling is an **explicit `interviewer` grant**, at project, project-site or
  organization-unit scope. Fillers who never log in are
  `mas_org_unit_worker` rows and are not covered here.
- A unit-scoped interviewer may attribute a case only to units inside their
  granted subtrees.
- A project- or site-scoped interviewer holds no unit of their own and must be
  able to choose any unit in the project. Serving them an empty list, or
  refusing them, is wrong.
- **A unit picker asks for units by role.** The organization API returns the
  union of everything a caller can see unless a role is named, which crosses
  purposes: a user who codes at one facility and interviews at another would
  otherwise be offered the facility they may not interview at. A filling screen
  requests interviewer scope explicitly.
- **When a project has an organization tree, a case must be attributed to a
  unit.** Since the routed unit decides who may code, an unattributed case is
  visible to no coder. A draft that cannot name a live unit must fail at
  submission, loudly, with the draft preserved — never file a death that
  nobody can see.
- A project with no organization tree attributes nothing; `org_unit_id` stays
  NULL by design.

## Open

| # | Question |
|---|---|
| P2 | Who signs off on rebuilding a project's instrument after its configuration changes? |

## References

- [VA Data Collection — Consolidated Plan](../planning/va-data-collection-plan.md) (decisions E1–E9)
- [Web Intake Policy](web-intake.md) · [Organization Model Policy](organization-model.md) · [Field Data Collection Policy](field-data-collection.md)
