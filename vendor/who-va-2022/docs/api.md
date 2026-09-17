# API reference

This is a practical guide to the public package surface. TypeScript declarations emitted by `pnpm build` remain the exact signature reference.

The normative data contract and its differences from the WHO 2022 reference are documented in [Form schema and WHO differences](form-schema.md).

## Entry points

| Import                                    | Use it for                                                                                                 |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `@drguptavivek/who-2022-va`               | Instrument data, sessions, expressions, validation, drafts, localization, and platform-neutral attachments |
| `@drguptavivek/who-2022-va/native`        | Expo/React Native form, controls, and native attachment processing                                         |
| `@drguptavivek/who-2022-va/web`           | React web form, controls, and browser attachment persistence                                               |
| `@drguptavivek/who-2022-va/web-component` | Custom element plus all web exports                                                                        |

## Instrument loading

- `whoVa2022Instrument` is the synchronous, built-in canonical instrument. Importing it through the root entry point includes the JSON contract in that entry's module graph.
- `loadWhoVa2022Instrument()` lazily imports and caches the canonical instrument.
- `loadWhoVa2022Language(locale)` returns the built-in English source instrument. Unsupported locale requests fall back to `en`.
- `WHO_VA_2022_LANGUAGES` lists the single built-in English choice. Use `createWhoVaLanguageLoader()` for authorized host-provided translations.
- `compileInstrumentDefinition(instrument)` validates a custom instrument, builds its runtime indexes, verifies expression ASTs against their source, and freezes the accepted definition. Normal engine entry points call it automatically.

Use the lazy loader in applications sensitive to startup parsing cost. Use the synchronous export for headless/server workflows that need immediate access.

## Headless sessions

```ts
import {
  createWhoVaInitialDataFromPrefill,
  createWhoVaSession,
  loadWhoVa2022Instrument
} from "@drguptavivek/who-2022-va";

const instrument = await loadWhoVa2022Instrument();
const session = createWhoVaSession(instrument, {
  initialData: createWhoVaInitialDataFromPrefill({
    presets: { hivAidsMortality: "low", malariaMortality: "high" },
    interviewer: { name: "Interviewer One", id: "INT-001", sex: "female", language: "en" },
    deceased: {
      givenNames: "Asha",
      surname: "Rao",
      sex: "female",
      citizenship: "citizen_at_birth",
      dateOfBirth: "1980-04-10",
      dateOfDeath: "2026-07-01"
    },
    location: { state: "Karnataka", district: "Mysuru" }
  }),
  locale: "en"
});

session.setAnswer("Id10021", "1980-04-10");
const snapshot = session.getSnapshot();
const navigation = session.next();
if (navigation.status === "completed") queueForSubmission(navigation.result.data);
const result = session.complete();
```

`initialData` can also be supplied as raw canonical WHO question IDs. The helper maps common host data to IDs including `Id10002`/`Id10003` for HIV/AIDS and malaria mortality presets, `Id10010`/`Id10010c` for interviewer name/ID, `Id10017`/`Id10018`/`Id10019` for deceased name/sex, `Id10052` for citizenship/nationality, `Id10020`/`Id10021` for known DOB, `Id10022`/`Id10023_a`/`Id10023_b`/`Id10024` for date or year of death, and `Id10057` for a composed country/state/district/village/death-place string. These values can be made non-editable by passing their question IDs in `lockedQuestionNames`; demo case-entry data does this so fields populated from the case record cannot be edited while filling the WHO VA instrument. Host-only death-list identifiers are not WHO answers; keep them in `draftId`, route state, or the server submission envelope.

Birth and death evidence are mutually exclusive: provide `dateOfBirth` or `ageInYears`, and provide `dateOfDeath` or `yearOfDeath`, never both. TypeScript rejects contradictory prefill objects and the runtime guard protects untyped callers.

| Prefill data                              | WHO code                   | Label                                        | Expected shape                                                                       |
| ----------------------------------------- | -------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------ |
| `presets.hivAidsMortality`                | `Id10002`                  | Is this a region of high HIV/AIDS mortality? | `"high" \| "low" \| "veryl"`                                                         |
| `presets.malariaMortality`                | `Id10003`                  | Is this a region of high malaria mortality?  | `"high" \| "low" \| "veryl"`                                                         |
| `interviewer.name`                        | `Id10010`                  | Name of VA interviewer                       | Letters and spaces only                                                              |
| `interviewer.age`                         | `Id10010a`                 | Age of VA interviewer                        | Number, 18-89 or 99                                                                  |
| `interviewer.sex`                         | `Id10010b`                 | Sex of VA interviewer                        | `"female" \| "male" \| "undetermined"`                                               |
| `interviewer.id`                          | `Id10010c`                 | ID of VA interviewer                         | Non-empty string                                                                     |
| `interviewer.language`                    | `language`                 | Interview language                           | ISO/BCP-47 language tag string, for example `"en"` or `"hi-IN"`                      |
| `deceased.givenNames`                     | `Id10017`                  | First or given name(s) of the deceased       | Non-empty string                                                                     |
| `deceased.surname`                        | `Id10018`                  | Surname(s) or family name(s) of the deceased | Non-empty string                                                                     |
| `deceased.sex`                            | `Id10019`                  | Sex of the deceased                          | `"female" \| "male" \| "undetermined"`                                               |
| `deceased.citizenship`                    | `Id10052`                  | Citizenship/nationality                      | `"citizen_at_birth" \| "naturalized_citizen" \| "foreign_national" \| "dk" \| "ref"` |
| `deceased.dateOfBirth`                    | `Id10021`                  | When was the deceased born?                  | ISO date string, `YYYY-MM-DD`; also sets `Id10020="yes"`                             |
| `deceased.ageInYears`                     | `age_adult`                | Adult age in years                           | Number, 12-119; also sets `Id10020="no"`, `age_group="adult"`                        |
| `deceased.dateOfDeath`                    | `Id10023_a` or `Id10023_b` | When did (s)he die?                          | ISO date string, `YYYY-MM-DD`; also sets `Id10022="yes"`                             |
| `deceased.yearOfDeath`                    | `Id10024`                  | Please indicate the year of death            | Four-digit year string; also sets `Id10022="no"`                                     |
| `location.country/state/district/village` | `Id10057`                  | Where did the death occur?                   | Strings composed as `country, state, district, village`; also sets `Id10051="yes"`   |
| `location.deathPlace`                     | `Id10057`                  | Where did the death occur?                   | Non-empty string, appended after `; ` when structured location is present            |

Language dropdown options display the English language name plus the local/native name. For custom language choices, use the ISO/BCP-47 tag as the choice value and provide `label.en` plus a native label keyed by the same tag or its base language, for example `{ value: "hi-IN", label: { en: "Hindi (India)", "hi-IN": "हिन्दी" } }`.

The session exposes:

| Method                             | Result                                                                            |
| ---------------------------------- | --------------------------------------------------------------------------------- |
| `getSnapshot()`                    | Current normalized data, visible section, questions, issues, and navigation flags |
| `setAnswer(name, value)`           | Validate and apply one answer, then recompute derived values                      |
| `replaceData(data)`                | Replace session answers as a unit                                                 |
| `setInstrument(instrument)`        | Switch to another compatible instrument, such as a translated instance            |
| `goToSection(name)`                | Navigate to a visible section by name                                             |
| `setLocale(locale, translations?)` | Change display locale and UI messages                                             |
| `next()` / `previous()`            | Validate and navigate the interview                                               |
| `validate()` / `complete()`        | Return normalized data and validation issues                                      |
| `subscribe(listener)`              | Observe snapshots; returns an unsubscribe function                                |

`next()` returns a discriminated `SessionNavigationResult`: `blocked` includes a non-empty issue list, `advanced` moves to another section, and `completed` includes the already-validated submission result. `validate()` and `complete()` likewise return a discriminated validation union, so `valid: true` guarantees an empty issue list. Every validation result also carries `formVersion`, `instrumentId`, and `instrumentVersion` outside `data`, allowing a stored submission to identify the exact form model without polluting canonical WHO answers.

## Stateless engine functions

- `parseExpression(source)` converts a supported XLSForm expression to the runtime AST.
- `evaluateExpression(expression, data, options?)` evaluates an AST or source expression against answers.
- `applyCalculations(instrument, data)` returns data with calculated questions recomputed.
- `createWhoVaInitialDataFromPrefill(prefill)` maps common host deceased/interviewer context to canonical initial answers.
- `getQuestion(instrument, name)` returns a named question or throws when it is absent.
- `isQuestionRelevant(instrument, question, data)` evaluates visibility.
- `validateAnswer(instrument, question, value, data, ...)` validates one field.
- `validateSubmission(instrument, data, ...)` recalculates, removes irrelevant and unknown fields from normalized output, and validates the complete submission.

Prefer `validateSubmission()` at server ingress even if the client already validated the interview.

## Form component

`WhoVaForm` is exported by `/native` and `/web`. Important props include:

| Prop                            | Purpose                                                                           |
| ------------------------------- | --------------------------------------------------------------------------------- |
| `instrument`                    | Use a supplied canonical or translated instrument instead of the built-in default |
| `session`                       | Reuse a caller-owned session                                                      |
| `initialData`                   | Seed a new session                                                                |
| `lockedQuestionNames`           | Mark supplied question IDs as read-only, commonly for case-entry prefill data     |
| `locale` / `uiTranslations`     | Control question localization and form chrome                                     |
| `showSourceGuidance`            | Display source guidance text                                                      |
| `platform`                      | Inject date, audio, image, file, and attachment lifecycle services                |
| `draftId` / `draftStore`        | Control durable draft identity and persistence                                    |
| `onReady`                       | Receive the initialized session                                                   |
| `onChange`                      | Receive answer data and the current snapshot                                      |
| `onValidation`                  | Receive current validation issues                                                 |
| `onDraftSaved` / `onDraftError` | Observe draft persistence                                                         |
| `onInstrumentError`             | Handle default-instrument loading failures                                        |
| `onComplete`                    | Receive the normalized submission result                                          |

Web and native forms are in-memory by default. Hosts must inject a `WhoVaDraftStore` to enable durable saves and platform services to enable binary capture. Web exports `createInsecureWhoVaBrowserDefaults()` only for demos and low-risk prototypes that deliberately accept plaintext `localStorage` and unencrypted IndexedDB.

Form ownership is explicit. A managed form may receive `initialData`; a caller-owned `session` must also receive its matching `instrument` and cannot receive `initialData`. `setInstrument()` accepts presentation-only translations for the same instrument identity/version but rejects changes to questions, choices, rules, or hierarchy.

Native hosts should also inject `platform.pickDate` when they want full-date fields to open a calendar. On Android, the Expo demo uses `@react-native-community/datetimepicker` and `DateTimePickerAndroid.open()` for date questions including `Id10021`, `Id10023_a`, and `Id10023_b`. Without `pickDate`, native full-date fields fall back to validated text entry.

The web component exposes `draftStore` and `platform` JavaScript properties. Assign a `WhoVaDraftStore` and host-controlled attachment/recording services before appending the element; otherwise persistence and binary controls remain disabled.

## Reusable question controls

`WhoVaQuestionControls` is exported by `/native` and `/web`. `Control` dispatches from `question.control`; named components are also available for text, integer, date, single choice, multiple choice, confirm, audio, image, file, note, calculated, and system questions.

Each receives the same core contract: `question`, `value`, `data`, `locale`, `issues`, `platform`, and `onAnswer`. Use these controls when a host needs its own section layout but wants the package's input behavior.

## Drafts

- `createDraftId()` creates a UUID draft identifier.
- `createLocalStorageDraftStore(storage?)` creates the browser-compatible key/value adapter.
- `WHO_VA_DRAFT_KEY_PREFIX` is the default `who-va-2022:draft:` prefix.
- `WHO_VA_DRAFT_SCHEMA_VERSION` is the current envelope version.
- `WHO_VA_FORM_VERSION` identifies this implementation's form model independently of the WHO instrument and draft schema.
- `decodeWhoVaDraft(value)` validates host-loaded data, migrates legacy unversioned envelopes to version 1, and rejects malformed or unknown versions.

A `WhoVaDraft` contains `schemaVersion: 1`, `formVersion`, its ID, instrument ID/version, current section, timestamps, and unvalidated answer data. Legacy drafts without `formVersion` are assigned the current version during decoding. Treat storage as an untrusted serialization boundary and call `decodeWhoVaDraft()` in custom stores before using decoded JSON. Draft metadata is deliberately outside the WHO submission object. Session initialization, `replaceData()`, and normalized validation output retain only question names declared by the supplied instrument; unknown host fields must remain in the host application's separate record.

## Localization

- `localizeText()` resolves localized text with fallback behavior.
- `resolveUiMessages()` resolves form chrome and validation messages.
- `withInstrumentTranslation()` and `withInstrumentTranslations()` apply partial translations without changing stable data identifiers.
- `createWhoVaLanguageLoader()` builds a lazy, bounded translation loader.
- `localeCandidates()` and `localeFromLanguageName()` help normalize locale selection.

Language files may translate section labels, question labels, hints, guidance, choice labels, constraint messages, and UI text. They must not translate question names, coded values, or expressions.

## Attachments

Platform-neutral exports include `WHO_VA_ATTACHMENT_POLICY`, `inspectRasterImage()`, image/PDF processing functions, processed-value guards, and `AttachmentProcessingError`.

The native entry point adds `processNativeImageAttachment()`. The web entry point supplies browser adapters and these application-facing helpers:

- `loadWhoVaWebAttachmentBlob(reference)` loads an IndexedDB-backed attachment for streaming through `fetch` or `FormData`.
- `cleanupWhoVaWebAttachments(references)` deletes binaries not reachable from the complete supplied set of retained drafts or answers.

Attachment answer values are references, not base64 payloads. Picker methods return `AttachmentCandidate`; image processors return `ProcessedImageAttachmentReference`; retained PDFs and recordings return their corresponding reference types; lifecycle methods receive `AttachmentReference`. This prevents temporary picker values from being mistaken for canonical processed binaries. See [Attachment processing](attachments.md) before implementing storage, upload, cleanup, or a new file format.

## Web component

```ts
import { defineWhoVaElement } from "@drguptavivek/who-2022-va/web-component";

defineWhoVaElement();
```

`<who-va-2022-form>` observes `locale` and `show-guidance`, accepts `draft-id`, and exposes `getData()`, `setData()`, `getDraftId()`, `validate()`, and `complete()`.

It emits bubbling custom events: `who-va-change`, `who-va-validation`, `who-va-draft-saved`, `who-va-draft-error`, and `who-va-complete`. Event data is available on `event.detail`.

## Core data contracts

The most commonly used types are:

- `InstrumentDefinition`, `InstrumentSection`, and `InstrumentQuestion`
- `SubmissionData` and `AnswerValue`
- `AttachmentCandidate`, `AttachmentReference`, and its processed image, retained PDF, and audio variants
- `ValidationIssue` and `SubmissionValidationResult`
- `WhoVaSession`, `WhoVaSessionOptions`, and `SessionSnapshot`
- `WhoVaDraft` and `WhoVaDraftStore`
- `WhoVaFormProps` and `WhoVaPlatformServices` from the UI entry points

Stored answers use stable WHO question names as keys. Choice answers store coded values, dates use ISO `YYYY-MM-DD`, multi-select answers use string arrays, and attachments use structured reference objects.
