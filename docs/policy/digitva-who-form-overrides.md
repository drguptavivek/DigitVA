---
title: DigitVA overrides and extensions to the WHO VA form
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-10
---

# DigitVA overrides and extensions to the WHO VA form

DigitVA composes the WHO VA 2022 instrument with its own corrections and extension layers. An **override** changes an existing WHO field or group; an **extension** adds fields. A deployment choice list or translation is neither a clinical logic correction nor a new question. The original WHO XLSForm remains unchanged.

## Sources and scope

- WHO comparison baseline: `vendor/who-va-2022/2022whova_xls_form_for_odk_multilingual.xlsx`, instrument V2.0, settings version `2026081401`, form ID `va_who_2022`. The older V1.1 workbook (`whova2022_xls_form_for_odk.xlsx`, version `2023072701`) is a historical reference only.
- ICMR comparison: `docs/kb/WHO_VA_2022_Docs/ND01_ICMRVA_WHOVA2022.xlsx`, settings version `ND01_ICMRVA_WHOVA2022_20251203`.
- UNSW sources: local `KA01_DS_WHOVA2022.xlsx` (20250726), `KL01_DS_WHOVA2022.xlsx` (20250625), `TR01_DS_WHOVA2022.xlsx` (20250526), under `docs/kb/WHO_VA_2022_Docs`. The local mapping confirms these belong to UNSW01. `NC01_DS_WHOVA2022` is also mapped but its workbook is unavailable locally; JIPMER is not treated as UNSW.
- Field matrix: `app/static/help/digitva-form-field-matrix.xlsx` (Field matrix, Read me, Sources, Rules and Choices sheets), displayed in Help → Data Collection. Source SHA256 values are recorded in the workbook.
- Runtime composition: `vendor/who-va-2022/src/instrument.ts` and `src/digitva-extension.ts`.
- Existing base adaptations: `vendor/who-va-2022/docs/xlsform-app-audit.md`, “Intentional runtime adaptations”.
- Layer configuration and deployment semantics: [VA form project configuration](va-form-project-configuration.md). DORIS proposal and generated ODK rows: `docs/kb/DORIS/who-va-2022-doris-consistency-proposal.md` and `docs/kb/WHO_VA_2022_Docs/odk-doris-support-rows.md`.

ND01 is the available ICMR workbook in this comparison; it must not be relabelled NC01. Workbook rows below are Excel row numbers. WHO and ND01 settings versions describe the source files, not a promise that either is the current ODK Central deployment.

## Overrides to existing WHO questions

| Field or group | WHO baseline | DigitVA behavior | Scope and reason |
|---|---|---|---|
| `Id10476` typed narrative | Required multiline text, relevant only when `string-length(${Id10476_audio})=0` (WHO survey row 88) | Required multiline text with no question-level relevance; visible with or without audio/image. Remove the audio hint that presents typing as a fallback | Always-on DigitVA core override in browser, server composition and generated project XLSForm. Matches ND01 row 109. The parent consent gate still applies. |
| `Id10365` birth weight above 4.5 kg | Constraint `not(selected(${Id10363}, 'no') and selected(${Id10365}, 'no'))` | Constraint omitted in the generated app base | Documented base adaptation; ND01 row 482 also omits it. Do not reintroduce the constraint by copying the WHO workbook. |
| `Id10382` duration in hours | `.>=0 and .<=99` | `(.>=0 and .<=98) or .=99` | Documented base adaptation makes the 99 code explicit; for integer inputs it accepts the same numeric set. |
| `Id10023_a`, `Id10023_b`, `Id10382` validation text | WHO messages | Clearer app English constraint messages | Documented interviewer-facing adaptation; date constraints remain unchanged. |
| `nmh` note placement | Direct child of `consented` | Inside `consented/injuries_accidents` | Documented runtime section adaptation. |
| `consented` label | WHO container label | `Interview completion` | Documented screen-label adaptation; consent relevance remains enforced. |
| `Id10366` recorded birth weight | WHO constraint | DORIS grams constraint 100–9999; acknowledgement `Id10366_confirm` outside 500–6000 | DORIS support browser override. Server re-derivation retains the looser WHO rule so valid browser answers survive. |
| `Id10308` pregnancy question | WHO requiredness | Required | DORIS A9; implemented browser behavior, proposal status remains `proposed` in the source block. |
| `Id10340` hysterectomy | WHO relevance | Asked only after a recorded pregnancy event, excluding the specified short injury interval | DORIS A10; implemented browser behavior, proposal status remains `proposed`. Exact expression is defined once in `DORIS_ID10340_RELEVANT`. Server retains WHO’s broader relevance. |

`whoOverrides: false` in server composition disables the DORIS tightening, not the always-on typed-narrative correction. Requiredness is enforced by the form validator; server relevance processing must preserve `Id10476` alongside media.

Generated project XLSForms derive this narrative override from the composed web definition. Export retains required multiline text and clears the obsolete audio hint in every exported language. This applies to newly generated workbooks; existing ODK Central deployments need the updated form published. Web-only intake workflow and host-supplied identifiers still have their documented ODK equivalents rather than identical screen behavior.

## Extensions grouped by purpose

| Purpose | Fields or behavior | DigitVA layer | ND01 evidence and differences |
|---|---|---|---|
| Social autopsy | `sa01`–`sa19` and `sa_tu13`–`sa_tu19`, socioeconomic, reaching-care and event-chronology sections | `social_autopsy` | Added ND01 survey rows 115–152; absent from WHO base. |
| Narration language and handwritten narrative image | `narr_language`, `imagenarr` | `narration_language` | ND01 rows 106, 108. These are added fields, separate from the `Id10476` relevance override. Audio and image are optional; neither hides typed text. |
| Death summary capture | `ds_available`, `ds_count`, `ds_im1`–`ds_im5` | `death_summary` | ND01 rows 566–574; availability gate, required count 1–5, image slots gated by count. |
| Medical documents capture | `md_available`, `md_count`, `md_im1`–`md_im30` | `medical_records` | ND01 rows 578–610; availability gate, required count 1–30, image slots gated by count. |
| Medical certificate file | `custom_medical_certificate_upload` image/PDF attachment following `Id10473` | Always-on core | DigitVA addition; not a verbatim ND01 field. |
| DORIS certificate support | Date-of-birth precision, hours survived, injury date/place/context, maternal age/gestation, surgery and autopsy fields | `doris_support_whova_2022` | Additional DigitVA DORIS layer; these fields are not additions in the inspected ND01 workbook. See the DORIS proposal for A1–A10 decisions. |
| Intake instructions | Configured welcome card | `intake_screen` | Replaces ND01 `begin_screen`, introduction, instructions and confirmation trigger; does not reproduce these as survey questions. |
| Geography and collection identity | Organization/death-register supplied geography and identifiers | Core and geography host context | Replaces ND01 hardcoded choice lists and ID calculation with project configuration/server context. See project configuration policy. |
| Consent mode | `consent_mode` following WHO `Id10013` | Always-on core | Keeps WHO yes/no consent; records mode separately instead of ND01’s `telephonic_consent` answer value. |
| Interview outcome and refusal visit note | `interview_outcome`, `visit_address`, `visit_date`, `visit_remarks` | Always-on core | Web workflow additions, not WHO or inspected ND01 questions. |
| ABHA identifiers | `abha_number`, `abha_address` | `abha` | DigitVA web extension, not inspected ND01 additions. |

Layers may be project-enabled or host supplied. The authoritative enablement rules are in the project configuration policy; this register does not make every optional extension mandatory.

## Organization and project identifier hierarchy

Organization projects add project-scoped unit attribution to the form payload. Each configured level contributes `org_<level_code>_code`, derived from the selected unit’s ancestors. These values support routing, reporting and access scope; they are supplied from the organization model, not re-entered as questionnaire answers. See [Organization model](organization-model.md) and [Project configuration](va-form-project-configuration.md), “Geography codes”.

`unit_code` is unique within a project, not merely within a level. Lower-level codes that repeat across parents use a parent prefix (for example `088_0123`); this is separate from the materialized organization path and from the case identifier. The human-readable death ID is `<unit_code or site_id>-<6 digits>`, assigned by a PostgreSQL sequence. Drafts and submissions retain internal UUIDs. Project, site, organization-unit, case and ODK identifiers must not be collapsed into one identifier.

DigitVA injects `Site`, `unique_id`, geography, hierarchy codes and submitter context at submission. ND01’s `unique_id` instead concatenates site, state, district, block and start-time components. Organization attribution is a DigitVA context extension, not an alteration of a WHO clinical response or a copy of ND01’s identifier calculation. The `geography` flag itself is currently documented as having no consumer; the injection follows host context and must not be described as newly enabled by that flag.

## Other WHO versus ND01 differences

These are observed source-file differences, not automatically approved DigitVA overrides.

| Difference | Exact ND01 behavior | DigitVA disposition |
|---|---|---|
| Presets `Id10002`, `Id10003` (rows 26–27) | Read-only, calculated `if(${survey_state}='21' and ${survey_district}='412','high','veryl')`, triggered by district | DigitVA supplies area presets from organization context; do not copy the hardcoded state/district formula. ND01 choices actually contain Haryana `06` and Faridabad `088`, so the source formula’s `high` branch is unreachable through those choices. |
| Consent (rows 37, 40) | Expanded consent statement, `select_one consent`; group accepts `yes` or `telephonic_consent` | DigitVA uses WHO yes/no plus separate consent mode. ND01 wording and answer value are not adopted wholesale. |
| Age metadata `Id10191` (row 301) | ND01 and WHO2026 both use `C_A`; older WHO2023 used `N` | Already corrected in WHO2026; not an ND01 override against the active baseline. |
| Read-only serialization | WHO `=TRUE()` versus ND01 Boolean true for `Id10120`, `Id10161`, `Id10197`, `Id10201`, `Id10205` | Equivalent intended read-only behavior, not five distinct clinical overrides. |
| Validation-message column | WHO `constraint_message::English (en)` becomes ND01 unqualified `constraint_message` | 85 messages move unchanged; `Id10365` loses its message along with its constraint. This is not mass removal of validation rules. |
| Site and geography choices | ND01, Haryana `06`, Faridabad `088`, blocks 1–3; district filter `state=${survey_state}` | Deployment configuration, not a WHO clinical-rule override. |
| Languages | WHO placeholders 1/2/3 replaced by `english` and `hindi`; Hindi survey/choice labels added | Project language configuration and translations. WHO choices’ French column is absent from ND01. |
| Collection metadata | Added `start`, `end`, `today`, `deviceid`; `unique_id`, display note and `site_individual_id`; `finalAgeInYears` | ODK metadata/identity additions. Do not impose ND01’s concatenated site/geography/time ID scheme on DigitVA identifiers. |
| Settings | Site-specific title/ID/version; instance name `concat(${unique_id},"_WHOVA2022")`; WHO `style=pages` absent | ODK packaging and display configuration, not clinical semantics. |

## Differences against WHO 2026 in the project workbooks

The matrix compares every named field/group across WHO2026, the all-on DigitVA Web composed artifact, ICMR ND01 and mapped UNSW KA01/KL01/TR01. The NC01 column is explicitly unverified. It records source presence, type, requiredness and exact question relevance; Rules and Choices retain the detailed expressions and source row numbers. Source files describe their own versions, not necessarily the currently published Central revision.

The summary below applies to **DigitVA Web and DigitVA-generated XLSForms**. Both keep typed narrative required and visible, support optional audio or a narrative image, apply shared WHO logic corrections, and include social autopsy, DORIS support and document-capture layers according to the same project configuration. Web navigation, draft storage and host-supplied identifier presentation have separate ODK implementations. The downloadable field matrix currently measures the Web composed artifact; it is not a full generated-XLSForm conformance comparison.

| Field or feature | WHO2026 | ND01 ICMR | UNSW KA01/KL01/TR01 | DigitVA Web and DigitVA-generated XLSForms |
|---|---|---|---|---|
| `Id10476` | Text shown only with empty audio | Always relevant | Always relevant | Always relevant under parent consent gate; required multiline |
| `Id10304_a` (WHO row 386) | `selected(${Id10334},'yes') and selected(${Id10305},'yes')` | `selected(${Id10304},'yes')`, row 445 | Same older rule, row 406 | Corrected to `selected(${Id10304},'yes')` through the shared deviation register (`digitva-13x`) |
| `Id10073` (WHO row 490) | `selected(${Id10069_a}, 'yes')` | Retains WHO rule | `false()`, row 510 | Retains WHO2026 rule; project suppression not copied |
| `Id10365` | Source constraint present | Omitted | Omitted | Omitted as documented base adaptation |
| Social autopsy | Absent | Present | Absent from these three source workbooks | Optional `social_autopsy` layer |
| Narrative image/language | Absent | Present | Present | Optional `narration_language` layer |
| Death summary and medical records | Absent | Present | Present | Separate optional layers |
| English guidance | WHO2026 populated guidance | Retained | 340 populated WHO guidance cells blank | Retained from WHO2026 |
| Consent | WHO yes/no statement | Expanded consent label and extra audio-consent value | Expanded site statement; WHO yes/no codes | WHO yes/no plus separate consent mode |

WHO2026 and older project versions also differ in seven English hints (`age_group`, `Id10167_units`, `Id10323`, `Id10324`, `Id10327`, `Id10462`, `Id10484`), and wording for `Id10262_a`, `Id10262_b`, `Id10370`, `deceased_CRVS`, `noteend`, `presets`. In particular WHO2026 says adult **12 years and above**, while the older project hint says **above 12**; pregnancy hints clarify applicability after at least six months and the period during/after delivery. These are source-version differences, not automatically approved overrides. Full literal wording is in Rules. Choice-label differences for `select_2/undetermined` and `select_533/singleton`, `twins`, `triplets` are in Choices; KA01 also differs on `select_534/more`.

Requiredness and appearance of matched question rows are unchanged across these project workbooks. ND01’s consent is a changed type/list, not a missing consent question. Clinical expressions are compared separately from translation columns, whitespace and equivalent read-only serialization.

## Known WHO logic issues retained

The existing audit identifies four constraints that reference values outside their actual choice lists: `Id10260`, `Id10414`, `Id10414_a`, `Id10414_b`. They remain preserved and evaluable but cannot fire for valid runtime choices. These are **documented unresolved source issues**, not completed DigitVA corrections. No correction is authorized merely by including an issue in this register.

## Maintenance and verification

Regenerate the comparison with `tooling/who-va-2022/build-form-comparison-matrix.py` using the document Python environment after rebuilding the composed instrument. It reads the XLSForms and composed artifact, emits the Help table and XLSX, and checks the saved workbook.

Change the composition/source definition, never patch generated artifacts by hand. Regenerate browser, server, composed-instrument and related reference artifacts through their build scripts. For every override, test the changed field with the trigger condition present and absent, check preservation of submitted answers, and record any deliberately looser server rule. Preserve the original WHO workbook and canonical WHO base when adding a DigitVA-only override.

The typed-narrative regression must cover two alternatives separately: typed text with saved audio, and typed text with a narrative image. Source-conformance tests continue to check the WHO base independently of DigitVA composition. See [Web intake policy](web-intake.md) for recording lifecycle and data preservation.
