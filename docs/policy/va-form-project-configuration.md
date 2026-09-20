---
title: VA Form Project Configuration Policy (extensions, languages, geography)
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-20
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

The column says **what the layer contributes**, which is not always a question
an interviewer answers. Two layers contribute no instrument questions at all,
and the table used to list ODK field names for them as though they did — which
invited someone to author server-injected context as questions and entangle app
identifiers with ODK ones. Corrected 2026-09-20 (`digitva-c48`).

| Extension | What it contributes |
|---|---|
| `digitva_core` (always on) | Questions: `unique_id`, `Site`, `comment`, `consent_mode`, `custom_medical_certificate_upload` |
| `social_autopsy` | Questions: the social-autopsy sections (`sa01`–`sa19`, `sa_tu13`–`sa_tu19`, `sas01`–`sas07`) |
| `intake_screen` | **No instrument questions.** A single admin-configured welcome card, from the project setting `web_intake_intake_note`, rendered client-side (`app/templates/va_frontpages/va_intake_form.html`). It deliberately *replaces* ND01's three-item `begin_screen` group (`introduction`, `instructions`, `confirm_inst`) rather than reproducing it (2026-09-19). |
| `geography` | **No instrument questions.** `survey_state`, `survey_district`, `survey_block` and `site_individual_id` are server-injected into the payload after validation (`app/services/web_intake_service.py`) from the death register and the interviewer's organization unit, per decision **O4** — they are never asked. The flag is derived and served but currently has no consumer (`digitva-ybt`). |
| `narration_language` | Questions: `narr_language`, `imagenarr` |
| `death_summary` | Questions: `ds_available`, `ds_count`, `ds_im1..5` — project setting `web_intake_death_summary_enabled`, on by default (2026-09-19) |
| `medical_records` | Questions: `md_available`, `md_count`, `md_im1..30` |
| `abha` | Questions: `abha_number`, `abha_address` (web intake only) |

A project picks layers; it does not pick a whole form. The deployed forms
decompose exactly this way — KEM_VAADU is the base plus `social_autopsy`; the
ICMRVA family adds `intake_screen`, `geography`, `death_summary` and
`medical_records`.

Medical records was folded into `digitva_core` when this table was first
written; the owner has since decided it is its own named extension
(`medical_records`), matching how ND01 actually structures it as a separate
"Medical Documents" group with its own availability gate. It is no longer
part of `digitva_core`.

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

**Decided 2026-09-20: this table records provenance for a human reader; no
code reads it.** Earlier, `app/services/instrument_translation_service.py`
parsed this table and refused any workbook that was not the row named for a
locale. That rule is gone: importing a questionnaire source is a reviewed
one-time activity, not something the importer gates, and any readable
workbook may be imported for any locale (path containment against the
workbook directory and the repository still applies). The reason is that a
re-import was never the way to change a translation already in service — the
admin string editor is — so gating imports on this table bought no safety and
cost the ability to seed or cross-check a language from whatever workbook an
operator actually has in hand. This table still records, for each deployed
language, which one deployed ODK form definition its strings were reviewed
against. The workbooks live in `docs/kb/WHO_VA_2022_Docs/`, inventoried by
that folder's README.

| Language | Locale | Source workbook | Project | ODK form id | Download date | Assigned by |
| --- | --- | --- | --- | --- | --- | --- |
| Hindi | hi | ND01_ICMRVA_WHOVA2022.xlsx | ND01 ICMR VA (the most commonly deployed ICMR form) | ND01_ICMRVA_WHOVA2022 | 2026-09-19 | DigitVA Data Collection owner |
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

Cross-check workbooks carry the same language but are *not* its source. By
convention they are read only with `--cross-check`, which reports differences
and writes nothing — a convention now, not an enforced rule: since 2026-09-20
the importer accepts any readable workbook for any locale, so importing one of
these as a source is possible and simply unwise. The pairs: Hindi against `RJ01_ICMRVA_WHOVA2022.xlsx` (structurally identical to ND01; one Hindi string differs), `KA01_DS_WHOVA2022.xlsx` and `KEM_VAADU_WHOVA2022.xlsx`,
Tamil against `PY01_ICMRVA_WHOVA2022.xlsx`, Marathi against
`KA01_DS_WHOVA2022.xlsx`. The curated reference form
`whova2022_xls_form_for_odk.xlsx` (V1.1) carries French on its choices sheet
only; the WHO multilingual form V2.0 (`2022whova_xls_form_for_odk_multilingual.xlsx`,
form version `2026081401`) carries the same 479 question names with full
French, Portuguese, Arabic, Swahili and Spanish labels and hints, and is the
source for those five. It is a translation source only; the reference form's
own move from V1.1 to V2.0 is decided separately, below.

### The curated reference form moves to V2.0, English only

Decided 2026-09-20 by the owner (`digitva-13x`), and **final**: the two
deviations below are accepted platform behaviour, not a holding position
awaiting WHO. They are revisited only if WHO publishes a correction, and
`tooling/who-va-2022/check-id10304a-relevance.py` is what tells you a new
release changed either one. The reference form becomes
`2022whova_xls_form_for_odk_multilingual.xlsx` (V2.0, `2026081401`), rebuilt
through `app/services/xlsform_instrument_builder.py`, with three decisions
fixed here because each was a judgement call rather than a mechanical
consequence.

**The instrument carries English only. Every other language comes from the
translation engine.** A rebuild from V2.0 would otherwise write WHO's French,
Portuguese, Arabic, Swahili and Spanish into the instrument itself, a second
copy of text `map_instrument_translations` already serves — and serves better.
Those five locales were imported from this same workbook, are approved and
active, and `applyTranslations` (`app/static/js/intake/translations.js`)
writes the payload over the bundle, so the database copy already wins wherever
it has a key. Measured before deciding: the shipped instrument's inline French
covers 144 choice labels, the engine covers 260 of them plus 476 question
labels and 207 hints, and of the 142 keys in both, 53 differ — with the engine
holding the newer V2.0 text. The inline copy is therefore stale, narrower, and
shadowed. The two keys only it carries, `select_32/parent` ("Parent") and
`select_501/stridor` ("Stridor"), are spelled identically in English, which is
why the equal-to-English rule dropped them at import; falling back to English
shows the same word. One cost, accepted: if a translation request fails, a
French interviewer now sees English rather than French for those 144 choice
labels. Every other locale already behaves that way, so this makes French
consistent rather than adding a weakness.

**`Id10304_a` keeps V1.1's relevance**, `selected(${Id10304},'yes')`, as a
recorded `DEVIATION`. V2.0's rule is unsatisfiable and would silently drop the
question. See `docs/kb/WHO_VA_2022_Docs/id10304a-v2-relevance-defect.md` and
[SwissTPH/WHO-VA#94](https://github.com/SwissTPH/WHO-VA/issues/94).

**`Id10230` keeps `agegroup` `C_A`**, also as a `DEVIATION`. V2.0 narrows it to
`a` — adult-only, and the only lowercase value among 508. The restriction is
clinically arguable (the question's guidance names "the elderly and in
diabetics"), but it was applied to one cell and nowhere else: the question's
own relevance still reads `selected(${isChild}, '1') or selected(${isAdult},
'1')`, its five follow-up rows (`Id10231`, `Id10232_units`, `Id10232_a`,
`Id10232_b`, `Id10232`) are all still `C_A`, and the sibling `Id10227` is
`C_A` with identical relevance. The owner chose the wider value deliberately:
asking a child one more question costs a question, while not asking loses the
observation irrecoverably. Reported to WHO as
[SwissTPH/WHO-VA#95](https://github.com/SwissTPH/WHO-VA/issues/95); if WHO
confirms adult-only and publishes the matching relevance and chain changes,
take their version rather than keep diverging.

`Id10191`'s `agegroup` correction (`N` to `C_A`, resolving V1.1's own
contradiction with `${isNeonatal} != '1'`) is accepted, as are V2.0's fifteen
English label and hint changes — which include two more V1.1 self-corrections,
the `Id10167_units` hint naming the wrong symptom and the `age_group` hint
leaving twelve-year-olds in no age band.

### Packed cells: a workbook cell carrying English and the translation together

A source workbook sometimes puts the English reference text and the target
language in one cell rather than two columns. `split_packed` (in
`app/services/instrument_translation_service.py`) recognises three
conventions, all seen in the documented source workbooks above:

- **newline-separated** — `"VA interviewer\nवीए साक्षात्कारकर्ता"` (a label or
  hint column).
- **`" / "`-separated** — `"Minutes / मिनट"` (choice labels, e.g. `sa_tu` in
  ND01).
- **`English (Translation)` parenthetical** — `"Hindi (हिन्दी)"` (the
  narration `language` choice list).

An English half is dropped only when it matches the reference English
**exactly** (whitespace runs collapsed for that comparison only — a workbook's
stray double space does not defeat an otherwise-exact match, but the kept
text is never rewritten). A cell that does not match one of these three
shapes exactly is stored whole, not guessed at: a translation that happens to
start or end with an English word must never be truncated.

A cell that **interleaves** the two languages line by line — ND01's `sa05`
hint alternates an English bullet with its `*`-prefixed Hindi counterpart —
has no single boundary to cut at; it is not a prefix, a suffix, or a two-part
separator. When every line of the reference English shows up verbatim among
the cell's lines in this shape, it is treated as not splittable at all and
the item is left untranslated, rather than stored as a mixed English/Hindi
blob.

**A result equal to the reference English is not a translation.** Whether a
cell was never packed (some ND01 group labels, e.g. `socialautopsy`, are
simply left as English in both columns) or was packed but not cleanly
splittable (the `sa05` case above), if the text that would be stored is
identical to the reference English, the item is treated as untranslated so
English fallback applies — which renders the same thing — and so coverage
reports the truth instead of counting an unfinished translation as done.
This equality check lives in `import_translations`, the caller that already
holds the reference text and is deciding set membership for "translated";
`split_packed` only performs the mechanical unpacking and has no opinion on
what counts as a translation.

**Operator note: re-importing corrects this, but only on request.** Rows
already imported before this fix carry whatever `split_packed` produced at
the time — English text, English-plus-translation, or a mixed blob — with
`source = imported`. Re-running the import for that language rewrites every
`imported` row with the corrected split (an administrator's `edited` row is
never touched — see below). A language is only corrected when someone
re-imports it; this is not applied retroactively in the background.

### DigitVA layers in the ND01 form

The ICMR deployment form (`ND01_ICMRVA_WHOVA2022.xlsx`, the version used
most commonly, 2026-09-19) carries the WHO instrument plus every DigitVA
layer the option contract names, as deployed structure with English and
Hindi text, 96 names beyond the WHO reference:

| Layer (`enabled_extensions`) | ND01 structure |
| --- | --- |
| `intake_screen` | `begin_screen`: `introduction`, `instructions` (with Hindi variants), `confirm_inst` |
| `geography` | `Site`, `survey_state`, `survey_district`, `survey_block`, `unique_id`, `site_individual_id` |
| `narration_language` | `narr_language`; narration capture `Id10476_audio` (audio) and `imagenarr` (image) |
| `social_autopsy` | `socialautopsy` group: `socioeconomic` (`sa01` to `sa06_a`), `reachinghealthcare` (`sa07` to `sa12`), `eventchronology` (`sa13` to `sa19` with `sa_tu*` time units) |
| `death_summary` | `death_summary` "Death Certificate (Images)": `ds_available`, `ds_count`, `ds_im1` to `ds_im5` |
| `medical_records` | `md_records`: `md_available`, `md_count`, `md_im1` to `md_im30` |

These are the structural reference for those layers when they are built
(decisions E7 and E8: overlay from a deployed form, never invented). The
importer reports them as "unknown in workbook" against the WHO reference
today, which is expected. The `abha` layer is not in ND01.

Medical records was recorded above as "not yet a named extension"; the owner
has since decided it is one (`medical_records`), matching ND01's own
`md_records` group and gate question. The Extensions table reflects this.

#### ND01 comparison verdicts

Building the `ds_available`/`md_available` gates against ND01's deployed
`death_summary` and `md_records` groups surfaced structure this instrument
does not adopt wholesale. Decided, so as not to relitigate:

- **Adopt** ND01's `ds_available` and `md_available` gate questions and their
  relevance (`selected(${ds_available}, 'yes')` / `selected(${md_available},
  'yes')` gating `ds_count` / `md_count`) — this is exactly what WP-A2 builds.
- **Reject** ND01's `Id10002`/`Id10003` calculations: they hard-code one
  district, which is wrong for every deployment but ND01's own.
- **Reject** ND01 dropping the `Id10365` constraint: it is a data-quality
  check, not deployment-specific noise, and stays enforced.
- **Reject** touching `Id10476`'s relevance: its reference expression is
  already effectively true until audio capture lands in the attachments
  phase 2 work; ND01's difference here is not a structural gap to close now.

#### Consent mode

Telephonic consent is recorded as a **separate field naming the mode of
consent**, not as a third value on `Id10013`. `Id10013` (`va_consent`) stays
the sole authoritative record that consent was taken, and the `consented`
group's relevance (`selected(${Id10013}, 'yes')`) is unchanged. The new
`consent_mode` question (`digitva_core`, always on) is optional and relevant
only once `Id10013` is `'yes'`. ND01 has no precedent for this field — it
folds the distinction into its own consent choice list instead — so the name
and shape here are DigitVA's own.

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

### The reference also carries the DigitVA layers (decided 2026-09-19)

The DigitVA layer questions (`consent_mode`, `md_available`, `md_im1`..`30`,
`ds_*`, `narr_language`, `abha_*`, and later the social autopsy `sa01`..`sa19`)
exist only in the TypeScript instrument builder
(`vendor/who-va-2022/src/*`), not in the curated WHO workbook. They are still
things a translator must be able to translate, so
`app/services/instrument_translation_service.py` treats the reference as the
WHO workbook **plus** the DigitVA layer entries, read from the committed
`vendor/who-va-2022/src/generated/digitva-layers.reference.json` artifact
(built by `tooling/who-va-2022/build-layer-reference.mjs`). Python never
authors this file or duplicates the layer definitions; it only reads the
artifact's English strings and, per item, which extension(s) it belongs to
(an item may belong to more than one, e.g. `digitva_documents` names both
`death_summary` and `medical_records`).

The WHO base and the DigitVA layers are disjoint namespaces today. If a layer
entry's `(item_kind, item_key, field)` ever collided with a WHO base item, the
merge **raises** rather than letting one silently shadow the other — a
collision is a bug in one of the two sources, never something to paper over.
A layer item is translated, exported to XLIFF and edited exactly like a
workbook item, and round-trips through the same resource-id scheme
(`resource_id`/`parse_resource_id`).

Headline coverage (shown everywhere) is translated / all translatable
reference items — question labels, hints, guidance hints and choice labels
together, WHO base and DigitVA layers alike, computed live from the reference
rather than hardcoded. A label breakdown is reported alongside it: translated
/ all question labels, base and layer together (not base-only — layer
question labels count once an extension makes them translatable). Layer
coverage is reported the same two ways per extension
(`{extension: translated/total}` for items, `{extension: label_translated/
label_total}` for the label breakdown). Coverage decides nothing about
serving (see the next section); it is informational at every level.

### Activation is explicit, not gated on coverage (decided 2026-09-19)

*"Whatever the translation in the tool is the translation; it may be a single
language or two languages."* The serving payload already falls back to
English **per string** (an item absent from the payload renders in English;
see "Where no translation exists the form shows English" in
[VA Web Form Options Contract](va-web-form-options.md)), so a whole-locale
coverage percentage was never a fact about whether the language could be
served safely — it only measured how much of it was done. A locale is served
once an administrator **approves and then activates** it (see "Approval
before activation" below — activation alone stopped being sufficient on
2026-09-20); there is still no coverage threshold to pass, and the `--force` flag/`force=`
parameter that existed only to bypass that threshold have been removed from
the importer, `set_locale_active`, the CLI, the admin API and the panel.
Coverage (base and per-extension) stays **computed and reported** everywhere
it was before — `locale_status`, `ImportReport`, the CLI `status` command, the
admin panel — it simply decides nothing.

The version on `mas_instrument_locales` is bumped by every import and every
edit; every submission records the locale and the version it was filled in
(`intake_locale`, `intake_translation_version`), so what the respondent saw
stays reconstructible.

Importing a source workbook for each language is an **operator step**, not
a migration: `flask instrument-translations import <instrument_code> <locale>
<workbook>` per language on a new install, or the Instrument Translations admin
panel. Migrations import no application code and must not read reference
workbooks.

### Choice-code convention (decided 2026-09-19)

A question **DigitVA authors itself** saves semantic choice codes — `yes`,
`no`, `ref`, `in_person`, `telephonic` and the like — because there is no
existing decode path to protect and a semantic code is what the next person
reading `map_instrument_translations` or an export expects. A question
**mirrored from a deployed form** (an overlay layer built from ND01 or another
project's workbook, decisions E7/E8) keeps that form's own codes verbatim,
because fidelity to a working instrument outranks our own naming consistency
— changing a mirrored code would fork the decode path a live deployment
already depends on.

ND01's `sas01`–`sas07` social-autopsy ordinals (`"1"`..`"8"`, not a semantic
code) are the deliberate outlier against *both* conventions above, kept under
the second clause: `mas_choice_mappings` already carries live ND01-ordinal
rows for `sa01` against form type `WHO_2022_VA_SOCIAL`, and
`submission_analytics_mv.py:371-374` projects `sa01`..`sa19` raw into the
COD-snapshot CSV export. Renumbering them to a semantic scheme would fork that
already-live decode path for no gain; when the social autopsy layer
(`sa01`..`sa19`) is built, its choice values follow ND01's ordinals, not
DigitVA's own convention.

### Interchange format (decided 2026-09-19)

**XLIFF 2.0 is the standard exchange for a language's strings.** A translator
works in a CAT tool, not in this application's editor and not in a spreadsheet,
so a language is handed out and taken back as an XLIFF 2.0 document
(`urn:oasis:names:tc:xliff:document:2.0`, `version="2.0"`, `srcLang="en"`,
`trgLang` the locale). The seeding path is unchanged in shape: a language still
*begins* with a workbook import, and XLIFF exchanges the strings of a language
that already exists. Which workbook is a human decision recorded in the table
above, not a rule the importer enforces (see "Translation sources").

**Resource ids.** One canonical id per stored string, used wherever XLIFF is
concerned and nowhere translated into something else:

| Stored item | `<unit id>` |
| --- | --- |
| A question's (or group's) label, hint or guidance note | `question.<name>.label` / `.hint` / `.guidance_hint` |
| A choice's label | `choice.<list_name>.<choice_name>.label` |

The id is parsed back by splitting on dots, so **no name may contain a dot**.
None in the curated reference form does (checked over all 1,292 reference
strings), and XLSForm names are conventionally `[A-Za-z0-9_-]`; a name that did
would raise rather than produce an id two items could share.

**What an export says.** One `<unit>` per *reference* item, not per stored
string, so a translator sees the work that is left. `<source>` is the English
reference text; `<target>` is the stored translation. The segment state records
where the string came from: `translated` for an `imported` row, `reviewed` for
an `edited` one, and `initial` with an empty `<target>` where nothing is
stored — which is the form falling back to English, said in the exchange
format. A `<note category="reference">` carries the enclosing section title, or
the choice's list name, so a translator knows what they are looking at.

**What an import may and may not do.** The same rule as the workbook importer:

| May | May not |
| --- | --- |
| Set the text of any item the reference form already has | Create an item, a question, a choice or a locale |
| Mark what it writes `imported` (a bulk hand-back) or `edited` (reviewed) | Change coverage or the version scheme, or activate/deactivate a locale |
| Leave an `edited` row standing when marked `imported` | Delete a string: an empty `<target>` leaves what is stored alone |

A unit whose id is not a reference item is **reported and skipped**, exactly as
an unknown workbook string is. A target longer than
`MAX_TRANSLATION_TEXT_CHARS` is reported and skipped rather than truncated, so
one bad segment does not cost a translator the rest of the file. The locale's
version is bumped once, and only if at least one row changed. A document with a
DOCTYPE is refused before it is parsed, and so is one whose `version`,
namespace, `srcLang` or `trgLang` is not the one asked for.

CLI: `flask instrument-translations export-xliff` / `import-xliff`. Admin:
`GET`/`POST /admin/api/instrument-translations/<instrument_code>/<locale>/xliff`,
admin-only, CSRF on the upload, 5 MB cap.

### Approval before activation (decided 2026-09-20)

**A locale must not be served to interviewers unless a human has approved it,
and that approval must be recorded.** `mas_instrument_locales.lifecycle_state`
moves through three states:

| State | Meaning |
| --- | --- |
| `draft` | Every locale starts here, including a freshly imported one. |
| `in_review` | A human is looking at it. |
| `approved` | A human has reviewed it and it may be activated. |

Two invariants hold at every point, enforced in
`instrument_translation_service.set_locale_active` /
`set_locale_lifecycle_state` **and** by the database CHECK constraint
`ck_mas_instrument_locales_active_requires_approved` on
`mas_instrument_locales` (belt-and-suspenders, both deliberate — the service
gives a named, actionable error; the constraint is the backstop if some other
code path ever writes the row directly):

1. **Only an `approved` locale may be activated.** Activating a `draft` or
   `in_review` locale is refused, naming the locale and its current state.
2. **A locale may not leave `approved` while it is still active.** Moving an
   active, approved locale to `draft` or `in_review` is refused with a
   message to deactivate first — this keeps the CHECK constraint always
   satisfiable; there is never a moment where an active row could fail it.

Entering `approved` records who approved it and when
(`approved_by_user_id`, `approved_at`); leaving `approved` (to `draft` or
`in_review`) clears both back to `NULL` — an approval record must not survive
a locale being sent back for more work.

**Coverage still decides nothing** (2026-09-19 decision stands): a locale's
survey-label or per-extension coverage percentage is not consulted by either
the lifecycle transition or the activation check. This is a *human* approval
gate, not an automated quality gate — an administrator may approve a locale
at any coverage level, and the reverse (declining to approve a
high-coverage locale) is equally their call.

**Why now (2026-09-20):** importing a questionnaire source stopped requiring
a documented source workbook (see "Translation sources" above) the same day
this was decided — any readable workbook may now be imported for any locale.
That widened who can get a locale into the servable state; this narrows who
can put it in front of an interviewer, by requiring an explicit, recorded
human sign-off in between.

**Operator note:** this lifecycle was added by a migration that deactivates
every existing locale (`lifecycle_state` backfilled to `in_review`,
`is_active` forced to `false` — there is no history to infer an "approved"
state from). See "Instrument Translations Panel" in
[Admin & Setup](../current-state/admin-and-setup.md) for the operator
checklist and the estimated translation work remaining per locale.

### Machine-translated strings are not served (decided 2026-09-20)

`map_instrument_translations.source` carries a third value alongside
`imported` (workbook-sourced) and `edited` (an administrator's correction):
`machine` -- a string an LLM drafted, not a speaker, awaiting human review.
Migration `b6d2f4a9c1e7` seeded 214 such rows for twelve locales as
`imported`, the same value a workbook-sourced string carries, which meant
approving a locale (per-locale, not per-row) blessed both at once. Migration
`c1a4b6e8d3f2` relabels exactly those seeded rows `machine`, matching on
locale, item, field **and text** so a row an administrator already corrected
or that no longer matches the literal seeded is left untouched.

**Precedence, highest first: `edited` > `imported` (workbook) > `machine`.**
A re-import (`import_translations`) and a bulk XLIFF hand-back
(`import_xliff`) both overwrite `imported` and `machine` rows alike and never
touch an `edited` one -- a real workbook or a reviewed hand-back beats a
machine draft exactly as it beats a stale workbook import.

**In XLIFF a `machine` row is `initial`, not `translated`.** It exports with
`state="initial"` and `subState="digitva:machine"`, carrying its draft in
`<target>` so a translator corrects rather than retypes -- which is what
`initial` with a non-empty target means in XLIFF 2.0 and is ordinary
machine-pretranslation practice. Labelling it `translated`, as the export
briefly did, showed a CAT tool finished work and invited the reviewer to skip
the one thing that most needed looking at. A `source` value this module has no
mapping for exports as `initial` too: understating progress makes a reviewer
look, overstating it does the opposite.

**Known caveat.** A machine draft exported and handed back *untouched* with
`--as imported` becomes an `imported` row and is served, because the importer
judges the hand-back, not each segment's state. That is the same trust the
`--as` flag always carried -- the administrator asserts a translator handled
the file -- but with machine drafts in play it is now a way for unreviewed text
to become servable without anyone reading it. Use `--as edited` only for a file
a reviewer genuinely worked through, and prefer the panel's per-string
**Accept** for drafts.

A `machine` row stays visible and editable in the admin string editor (the
panel marks it distinctly) and is included in `list_strings`, but:

* `export_translations` -- the one delivery contract every frontend reads --
  **excludes** it. The served payload simply omits that item, the identical
  shape an untranslated string already has, so the client's existing
  per-string English fallback (see "Purpose" above) covers it with no new
  mechanism.
* Coverage (`locale_status`, and per-extension coverage on an import report)
  **does not count** a `machine` row as translated, so a locale is never
  reported complete on strings it is not actually serving.

An administrator reviews a `machine` string in the panel and either edits its
text (`update_string`, which sets `edited` as it always has) or, if it reads
correctly as-is, clicks **Accept** (`accept_machine_translation`), which
promotes `machine` straight to `edited` without retyping. Either action makes
the string servable on the locale's next version bump.

**Seeded on a fresh install too (decided 2026-09-20, digitva-dms).**
`b6d2f4a9c1e7` only inserts its 214 strings where a locale row already
exists, so a brand-new database got none of them (an operator creates locale
rows later, by importing a workbook). Migration `7134cb5dc7b6` creates the
twelve locale rows (`draft`, inactive) when absent and inserts the same 214
strings as `machine` from the start, reading them from the checked-in
`resource/digitva_layer_translations_2026_09_20.csv` rather than pasting the
literal a third time (`b6d2f4a9c1e7` and `c1a4b6e8d3f2` are applied and must
not be edited, so they keep their own copies).
`tests/migrations/test_seed_layer_translations_on_fresh_install.py` checks
the CSV against both byte-for-byte. A later operator workbook import still
finds and fills in the locale row this migration created, exactly as before.

### A bulk re-import demotes an approved locale, after warning (decided 2026-09-20)

**Re-importing into a locale an administrator already approved returns it to
`in_review` -- but never silently.** The approval gate above holds for a
locale nobody has approved yet; it did nothing to stop a re-import (a
workbook or an XLIFF hand-back) from silently rewriting every string of a
locale that is already approved and being served, with nobody re-reviewing
the new content (found by audit 2026-09-20, digitva-dqh).

When `import_translations` or `import_xliff` writes into a locale whose
`lifecycle_state` is `approved`:

* `lifecycle_state` returns to `in_review`;
* `approved_by_user_id` and `approved_at` are cleared;
* `is_active` is set `false` (the CHECK constraint requires it once
  `lifecycle_state` is no longer `approved`);
* the import still proceeds -- this is a demotion, not a refusal to import.

`update_string` and the per-string **Accept** action are **not affected**: an
administrator editing or accepting one string *is* the reviewer, the same way
entering `approved` always required a human in the first place.

**Never silently.** The caller must acknowledge the consequence before
anything is written, or the whole call is refused (nothing written, nothing
demoted) with a message naming the locale and what proceeding would do:

| Surface | How it warns |
| --- | --- |
| CLI (`instrument-translations import` / `import-xliff`) | Refused unless `--acknowledge-demotion` is passed. |
| Admin panel | A `confirm()` dialog states the consequence before the request is sent, and `acknowledge_demotion=1` is sent **only** if it was accepted. When the panel's cached locale list does not know the locale is approved (stale, or not yet loaded) no dialog fires and the field is deliberately omitted, so the route refuses and the operator is told -- acknowledging a warning nobody saw would defeat the rule. |
| Route (`POST .../import`, `POST .../xliff`) | Refused unless the multipart payload carries `acknowledge_demotion=1`. |

The demotion and the string writes happen in the same database transaction
the caller commits (or rolls back on any error), so they can never
half-apply: the refusal itself is raised before any row is written -- for the
XLIFF route, after the document is validated as well-formed XLIFF 2.0 for the
right locale, so a malformed or misdirected upload still fails with its own
error rather than the demotion refusal masking it. The import report names
the demotion (`"demoted": true`), so it shows up in CLI output and in the
logged `instrument locale demoted by import` line.

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
