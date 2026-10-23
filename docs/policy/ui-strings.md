---
title: UI String Corrections Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-24
---

# UI String Corrections Policy

A native reader can correct an Expo UI string in one language on a server page,
and the fix reaches every browser and phone without a new build (digitva-fsjz).
The bundled JSON stays the shipped default and the offline fallback.

## Who

Admin only, as the questionnaire translations editor is (owner decision,
2026-10-12). No translator role is decided. The admin page sits under Setup,
beside Instrument Translations, and every write is refused to any other role
on the server, whatever the page shows.

## What the editor does

- Reads the reference (`en`) and each bundled locale from the served Expo
  export: `<EXPO_CLIENT_DIST>/ui-strings/<locale>.json`, copied in by
  `npm run export:web` in `mobile/digitva-collect`. The source files stay under
  `mobile/digitva-collect/src/strings/`; the server never edits them.
- Lists the reference keys with the English, the bundled text, the current
  text and a status. Filters: all, corrected, missing, machine.
- Saves a correction for one key, or reverts it to the bundled text.
- Exports one locale as JSON with the corrections applied, for the release that
  folds them into the bundled files.

English is the reference. Its strings are not edited here, and only keys present
in `en` can be corrected.

## Statuses

- `corrected`: a correction row exists for the key.
- `missing`: no correction, and the bundled locale file has no text for the key
  (or only whitespace).
- `machine`: no correction, no bundled text, and a machine candidate awaits review.
- `bundled`: no correction; the bundled text is shown.

## Checks on a correction

Refused with a message, and nothing is written:

- the key is not an `en` key;
- the text is empty after trimming;
- the text is longer than the questionnaire cap (`MAX_TRANSLATION_TEXT_CHARS`,
  16000 characters);
- the `{placeholder}` names are not exactly those of the English. Equality, not
  a subset: a dropped `{count}` hides a value, and an extra one names nothing the
  app fills in;
- markup or a link the English does not have, or control characters, by the same
  rule the questionnaire editor applies (`validate_translation_text`);
- the locale is `en`, or is not a shipped locale. A path-like locale is refused
  before it reaches the filesystem.

## Versioning

A locale's version is a stable token made of the count of its corrections and
the newest correction time. Every save moves the newest time; every revert lowers
the count. A client that holds a version can tell whether anything changed
without downloading the body.

## Audit

Every save and every revert writes one log line naming the locale, key, actor,
and the old and new text (truncated to 120 characters), as the questionnaire
editor's `update_string` does. There is no audit table for these corrections.

## Public read

`GET /api/v1/ui-strings/<locale>` returns `{version, strings}`, where `strings`
holds the corrections only. It needs no sign-in, because the sign-in screen is
translated too. The body is reference text and holds no personal data. The ETag
is the version; a matching `If-None-Match` gets `304`. `Cache-Control` is
`public, max-age=60`. `en`, and any unshipped locale, is `404`.

The Expo app lays these corrections over the bundled dictionary on start and on a
language switch. The client side is tracked as digitva-dt1e.

## Google Translate link

Each row links to Google Translate for a quick look-up while correcting:

`https://translate.google.com/?sl=en&tl=<locale>&text=<English, URL-encoded>&op=translate`

The link opens in a new tab with `rel="noopener noreferrer"`. Only the English
reference text goes in the link: never the current translation, never data about
a person. The server makes no call to Google; the link is a plain anchor built in
the template.

## Machine candidates

Decided 2026-10-24 (digitva-cqw9). An administrator can ask for the strings a
language lacks to be drafted by machine, then review each draft.

- **Provider:** Azure Translator v3 (free F0 tier), configured by
  `AZURE_TRANSLATOR_KEY`, `AZURE_TRANSLATOR_REGION` and
  `AZURE_TRANSLATOR_ENDPOINT`. Unset, the page says "Not configured" and the job
  refuses to run.
- **What is sent:** the English UI text of the missing keys, and nothing else: no
  user, case or site data. `{name}` placeholders are shielded from translation.
- **Languages:** English into hi, pa, mr, kn, ta, ml, te, gu, or (the owner set,
  digitva-1g1h), even before a language's JSON file ships.
- **What it writes:** a row with `source='machine'` for each key that the
  bundled file lacks (or holds only whitespace) and that has no override row of
  any source. Insert only: it never updates a row, so an edit, an accepted text
  or an earlier draft is never overwritten.
- **Never served:** machine rows are left out of the public API, the version and
  the export. They are served only after an administrator accepts one (Accept
  keeps the text; Edit saves a new one). Both make the row `edited`.
- **Checks:** a draft is dropped, and counted as rejected, if its placeholder
  set differs from the English or it fails the correction checks above.
- **Who:** admin only, from a button on the page or
  `flask ui-strings machine-translate [--locale] [--dry-run] [--limit]`. One run
  at a time; the last run's per-language counts (created, rejected, skipped,
  errors) are shown on the page.

## Storage

Corrections and machine candidates live in `mas_ui_string_override`, one row per
(locale, key), told apart by `source` (`edited` or `machine`). Reverting
deletes the row. The downgrade of its migration refuses while rows exist.
See `docs/current-state/data-model.md`.

## Related

- `docs/policy/va-form-project-configuration.md` ("Translation sources"): the
  questionnaire editor this one copies.
- `docs/current-state/expo-client.md`: the export and the `dist/ui-strings`
  folder.
