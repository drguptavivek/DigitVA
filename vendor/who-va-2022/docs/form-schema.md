# Form schema and differences from WHO 2022

This document is the normative description of the data contract implemented by this package. It distinguishes the WHO 2022 Verbal Autopsy reference instrument from this application's schema, extensions, and serialization metadata.

## Version identifiers

These identifiers are independent and must not be substituted for one another.

| Identifier                                      | Current value      | Meaning                                              | Change policy                                                                  |
| ----------------------------------------------- | ------------------ | ---------------------------------------------------- | ------------------------------------------------------------------------------ |
| `WHO_VA_FORM_VERSION` / `formVersion`           | `"2022"`           | The WHO VA form edition implemented by this package  | Change when adopting a different WHO form edition                              |
| `instrument.id`                                 | `"va_who_2022"`    | Stable machine identifier for the questionnaire      | Change only for a different questionnaire family                               |
| `instrument.version` / `instrumentVersion`      | `"2023072701"`     | Version of the retained WHO 2022 instrument contract | Change when the underlying WHO contract changes                                |
| `WHO_VA_DRAFT_SCHEMA_VERSION` / `schemaVersion` | `1`                | This project's draft-envelope serialization format   | Increment for an incompatible persistence-shape change and provide a migration |
| npm package version                             | See `package.json` | Version of the JavaScript implementation             | Follow semantic versioning                                                     |

`formVersion`, `instrumentId`, and `instrumentVersion` are emitted with drafts and validation/completion results. They remain outside `data`, so implementation metadata cannot be mistaken for WHO answers.

## Authoritative contract

`src/generated/who-va-2022.instrument.json` is the sole executable WHO contract. It contains 30 sections and 449 question-bearing rows. `src/instrument.ts` adds the one implementation-specific question described below, producing 450 runtime questions.

The retained workbook is provenance/reference documentation for manual inspection only. Runtime code, builds, and automated tests do not parse Excel, import an Excel library, or generate the JSON from the workbook. The JSON's `sourceFile` property is provenance metadata, not an instruction to load that file.

## Canonical answer schema

Submission `data` is an object keyed by stable question name. Only names declared by the active instrument are retained.

| Instrument data type | Canonical answer shape                                                      |
| -------------------- | --------------------------------------------------------------------------- |
| `string`             | String; coded choice questions use the declared choice value, not its label |
| `number`             | Finite JavaScript number                                                    |
| `boolean`            | Boolean                                                                     |
| `date`               | ISO calendar date, `YYYY-MM-DD`                                             |
| `dateTime`           | Valid date-time string                                                      |
| `string[]`           | Array of declared coded choice values                                       |
| `attachment`         | Durable `AttachmentReference` metadata; never embedded base64 bytes         |
| `audit`              | Object containing at least `startedAt`                                      |
| `calculated`         | Runtime-derived value; caller input is not authoritative                    |
| `none`               | No stored answer                                                            |

On validation, calculations are recomputed, irrelevant non-system answers are removed, and unknown keys are discarded. Labels, hints, translated text, section navigation, preview state, and host-only record identifiers are not submission answers.

## Implementation-specific addition

The runtime adds exactly one question that is not a WHO source row:

| Property         | Value                                                  |
| ---------------- | ------------------------------------------------------ |
| Name             | `custom_medical_certificate_upload`                    |
| Position         | Immediately after `Id10473`                            |
| Section          | `consented > deathcert`                                |
| Type/control     | `attachment` / `file`                                  |
| Accepted content | JPEG, PNG, or PDF through the host attachment services |
| Required         | No                                                     |
| Relevance        | Same relevance expression as `Id10473`                 |
| Source metadata  | `sourceType: "custom-attachment"`, `sourceRow: 0`      |

Its answer is part of canonical runtime `data`, but downstream systems expecting the unextended WHO dataset must map or remove this field explicitly.

## Intentional adaptations from the WHO 2022 reference

| Item                 | WHO reference                                                    | Implemented schema                  | Reason                                                                                 |
| -------------------- | ---------------------------------------------------------------- | ----------------------------------- | -------------------------------------------------------------------------------------- |
| `nmh` section path   | `consented`                                                      | `consented > injuries_accidents`    | Places the guidance with the injury questions instead of as a detached completion item |
| `Id10365` constraint | `not(selected(${Id10363}, 'no') and selected(${Id10365}, 'no'))` | Omitted                             | The source rule rejects a valid normal-birth-weight combination                        |
| `Id10382` constraint | `.>=0 and .<=99`                                                 | `(.>=0 and .<=98) or .=99`          | Preserves `99` as the coded “do not know” value and the special guidance for 88 hours  |
| `Id10023_a` message  | Source wording                                                   | Clearer English application message | Improves interviewer-facing date validation; rule is unchanged                         |
| `Id10023_b` message  | Source wording                                                   | Clearer English application message | Improves interviewer-facing date validation; rule is unchanged                         |
| `Id10382` message    | Source wording                                                   | Clearer English application message | Explains the adapted allowed range                                                     |
| `consented` label    | Source container label                                           | `Interview completion`              | Makes the runtime screen name match its displayed purpose                              |

Four retained source constraints—`Id10260`, `Id10414`, `Id10414_a`, and `Id10414_b`—refer to values outside their compiled choice lists. They remain represented and evaluable, but valid UI input cannot trigger them.

## Presentation and normalization adaptations

- Full dates are stored as ISO `YYYY-MM-DD`, regardless of localized display order.
- WHO `year` controls display a four-digit year and normalize it to January 1 in the underlying date-valued contract.
- Prefill accepts either known date of birth or reported age, and either known date of death or reported year; contradictory evidence is rejected.
- Translations may change labels, hints, guidance, constraint messages, and choice labels. They cannot change question names, coded values, rules, hierarchy, or calculations within an existing session.
- Image and file picker outputs are temporary candidates. Only processed image, retained PDF, audio, or explicitly external attachment references enter answer data.
- Binary content is host-managed. Draft and submission JSON contain reference metadata only.

## Persistence and submission envelopes

A draft has this outer shape:

```ts
interface WhoVaDraft {
  schemaVersion: 1;
  formVersion: "2022" | string;
  id: string;
  instrumentId: string;
  instrumentVersion: string;
  currentSection: string;
  createdAt: string;
  updatedAt: string;
  data: SubmissionData;
}
```

The TypeScript field is `string` so historical drafts remain representable. New drafts use `WHO_VA_FORM_VERSION`. The decoder migrates legacy drafts that lack `schemaVersion` or `formVersion`; unknown schema versions are rejected.

Validation and completion return the same identity alongside answers:

```ts
{
  valid: true,
  formVersion: "2022",
  instrumentId: "va_who_2022",
  instrumentVersion: "2023072701",
  data: { /* WHO answers plus the documented custom field */ },
  issues: []
}
```

Host-only identifiers, authentication data, workflow state, synchronization metadata, and server record IDs belong in the host's envelope, not in `data`.

## Governing a schema change

Every future divergence from the WHO reference must:

1. update the checked-in JSON or explicit runtime extension;
2. be added to the appropriate table in this document;
3. include focused runtime and type-level tests;
4. preserve stable question names and coded values unless an intentional breaking migration is documented;
5. increment the draft schema version only when stored envelope compatibility requires it; and
6. update the form version only when the implemented WHO form edition changes.

The detailed manual provenance inventory remains in [XLSForm to app instrument audit](xlsform-app-audit.md). Attachment storage and security requirements are specified in [Attachment processing](attachments.md).
