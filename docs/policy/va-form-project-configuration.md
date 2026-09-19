---
title: VA Form Project Configuration Policy (extensions, languages, geography)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-19
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
| `intake_screen` | `introduction`, `instructions`, `confirm_inst` — project setting `web_intake_intake_note` (2026-09-19) |
| `geography` | `survey_state`, `survey_district`, `survey_block`, `site_individual_id` |
| `narration_language` | `narr_language` |
| `death_summary` | `ds_available`, `ds_count`, `ds_im1..5` — project setting `web_intake_death_summary_enabled`, on by default (2026-09-19) |
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

## Translation sources

**Exactly one source form per language, documented here.** A language's
strings are imported from one deployed ODK form definition and no other. This
table *is* the rule: `app/services/instrument_translation_service.py` parses it
and refuses any workbook that is not the documented source for the locale, so
changing a language's source means editing this table first. The workbooks live
in `docs/kb/WHO_VA_2022_Docs/`, inventoried by that folder's README.

| Language | Locale | Source workbook | Project | ODK form id | Download date | Assigned by |
| --- | --- | --- | --- | --- | --- | --- |
| Hindi | hi | RJ01_ICMRVA_WHOVA2022.xlsx | RJ01 ICMR VA | RJ01_ICMRVA_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| Tamil | ta | JIPMER_DS_WHOVA2022.xlsx | JIPMER DS | JIPMER_DS_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| Kannada | kn | KA01_DS_WHOVA2022.xlsx | KA01 DS | KA01_DS_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| Marathi | mr | KEM_VAADU_WHOVA2022.xlsx | KEM VAADU | KEM_VAADU_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| Malayalam | ml | KL01_DS_WHOVA2022.xlsx | KL01 DS | KL01_DS_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| Khasi | kha | ML01_ICMRVA_WHOVA2022.xlsx | ML01 ICMR VA | ML01_ICMRVA_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| Odia | or | OD01_ICMRVA_WHOVA2022.xlsx | OD01 ICMR VA | OD01_ICMRVA_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| Bangla | bn | TR01_DS_WHOVA2022.xlsx | TR01 DS | TR01_DS_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
| French | fr | 2022whova_xls_form_for_odk_multilingual.xlsx | WHO multilingual form V2.0 | va_who_2022 | 2026-09-19 | DigitVA Data Collection owner |
| Portuguese | pt | 2022whova_xls_form_for_odk_multilingual.xlsx | WHO multilingual form V2.0 | va_who_2022 | 2026-09-19 | DigitVA Data Collection owner |
| Arabic | ar | 2022whova_xls_form_for_odk_multilingual.xlsx | WHO multilingual form V2.0 | va_who_2022 | 2026-09-19 | DigitVA Data Collection owner |
| Swahili | sw | 2022whova_xls_form_for_odk_multilingual.xlsx | WHO multilingual form V2.0 | va_who_2022 | 2026-09-19 | DigitVA Data Collection owner |
| Spanish | es | 2022whova_xls_form_for_odk_multilingual.xlsx | WHO multilingual form V2.0 | va_who_2022 | 2026-09-19 | DigitVA Data Collection owner |

Cross-check workbooks carry the same language but are *not* its source. They
are read only with `--cross-check`, which reports differences and writes
nothing: Hindi against `KA01_DS_WHOVA2022.xlsx` and `KEM_VAADU_WHOVA2022.xlsx`,
Tamil against `PY01_ICMRVA_WHOVA2022.xlsx`, Marathi against
`KA01_DS_WHOVA2022.xlsx`. The curated reference form
`whova2022_xls_form_for_odk.xlsx` (V1.1) carries French on its choices sheet
only; the WHO multilingual form V2.0 (`2022whova_xls_form_for_odk_multilingual.xlsx`,
form version `2026081401`) carries the same 479 question names with full
French, Portuguese, Arabic, Swahili and Spanish labels and hints, and is the
source for those five. It is a translation source only: whether the
reference form itself moves from V1.1 to V2.0 is a separate decision.

Instrument locale codes are a separate axis from `mas_languages` codes (`kha`
here is `khasi` there). Nothing maps between them, and adding a
`mas_languages` row does not add a display language.

### What a translation may change, and what it may not

Structure is pre-built from the curated reference form
`docs/kb/WHO_VA_2022_Docs/whova2022_xls_form_for_odk.xlsx` and is immutable
(decision O1). A translation supplies **only** the text an item is shown with:

| May change | May not change |
| --- | --- |
| A question's `label`, `hint` and `guidance_hint` | Which questions exist, their names, order or section |
| A section (group) label | Relevance, constraint or calculation expressions |
| A choice's `label` | Choice *values*, or which choices a list holds |
| | Data types, required flags, appearances |

The importer keys every string to an item the reference already has. A string
for an item the reference lacks is **reported and discarded**, never stored, so
a project workbook that has drifted structurally cannot add a question by the
back door. The strings a workbook lacks are reported the same way.

A locale is served to forms only when it is **active**, and it is activated
when its coverage of the reference's survey labels reaches
`TRANSLATION_COVERAGE_THRESHOLD` (0.95). Activating below that is possible but
is logged as forced. The version on `mas_instrument_locales` is bumped by every
import and every edit; every submission records the locale and the version it
was filled in (`intake_locale`, `intake_translation_version`), so what the
respondent saw stays reconstructible.

Importing the documented source for each language is an **operator step**, not
a migration: `flask instrument-translations import <instrument_code> <locale>
<workbook>` per language on a new install, or the Instrument Translations admin
panel. Migrations import no application code and must not read reference
workbooks.

## Sign-off on a configuration change (P2, decided 2026-09-19)

**The admin who saves the setting is the sign-off.** There is no pending
state and no second approver: the save is recorded in the admin activity log
([Admin Activity Log](admin-activity-log.md)), which is the audit trail.

This is affordable because instruments are pre-built *per standard
instrument*, not per project: changing a project's configuration selects
layers and option lists, it never rebuilds a questionnaire. What a project
picks — the web form type (`web_intake_form_type_id`), the extensions, the
languages — is served as options by the project API, and a form type may only
be chosen once its PII set is confirmed
([New Form Type Onboarding](new-form-type-onboarding.md)), which is where the
second pair of eyes already sits.

## Open

*Nothing open.*

## References

- [VA Data Collection — Consolidated Plan](../planning/va-data-collection-plan.md) (decisions E1–E9)
- [Web Intake Policy](web-intake.md) · [Organization Model Policy](organization-model.md) · [Field Data Collection Policy](field-data-collection.md)
