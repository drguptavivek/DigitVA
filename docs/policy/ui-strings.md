---
title: UI String Corrections Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-06
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
  export: `<EXPO_CLIENT_DIST>/ui-strings/<locale>.json` with its
  `theme-<locale>.json` and `form-<locale>.json` (see "Two namespaces"), copied
  in by `npm run export:web` in `mobile/digitva-collect`. The source files stay under
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
- the locale is `en`, or is neither a shipped locale, a machine locale nor a
  language added on the page. A path-like locale is refused
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

## Two namespaces

The editor and the packs cover two namespaces of UI text (digitva-s028):

- **App strings**: `src/strings/<locale>.json` plus the theme screens'
  `src/strings/theme-<locale>.json`, both copied into the export as they are.
- **WHO form labels** (Next, Back, Don't know, validation messages): the
  vendor package's own labels, `vendor/who-va-2022/src/languages/ui.ts`.
  `npm run export:web` runs `scripts/export-form-ui-strings.mjs`, which writes
  `ui-strings/form-en.json` (the reference, from the vendor's English
  templates) and `ui-strings/form-<locale>.json` for each built-in translation.
  In the editor and in `mas_ui_string_override` these keys carry the prefix
  `form:` (`form:next`); app keys are camelCase, so the two cannot collide.

Every check above (known English key, placeholder equality, markup) applies to
both. Questionnaire question and choice text stays in the instrument
translation packs (`docs/policy/va-form-project-configuration.md`).

## Publishing a UI language

A UI language reaches clients only once an administrator publishes it on the
UI strings page ("UI languages" card, `PUT /admin/api/ui-languages/<locale>`,
admin only, CSRF-checked). Each language is one `mas_ui_locale` row: the code
(2 or 3 lower-case letters, never `en`), its name in its own script, a BCP 47
tag starting with the code (`pa-IN`), the direction (`ltr` or `rtl`) and the
published flag. Adding a language makes it editable on the page, with machine
drafts and review, before it is published; it needs no bundled file. A new
language starts unpublished, and a save that sends no `published` flag keeps
the current state, so editing a name never unpublishes a language. Publishing
a language with no bundled file and no accepted row is refused (`422`,
`nothing_to_publish`): it would serve an empty pack. The language codes are ISO codes, not the narration-language names of
`mas_languages`, which is why the Languages panel's table is not reused.

Unpublished languages are never listed or served, whatever rows they hold.
Hindi was seeded published by the migration, because its corrections were
served before this gate existed. A right-to-left language stays unpublished
until it is checked on a phone; the app does not offer one yet in any case.
Every change writes one log line naming the locale, the actor and the old and
new settings.

## Public read

No sign-in is needed, because the sign-in screen is translated too. The bodies
are reference text and hold no personal data. Both responses carry an ETag (a
quoted SHA-256 hex, the form the app's `If-None-Match` check accepts); a
matching `If-None-Match` gets `304`. `Cache-Control` is `public, max-age=60`.

- `GET /api/v1/ui-strings` lists the published UI languages:
  `{version, languages: [{locale, native_name, bcp47_tag, direction, version,
  reviewed}]}`, ordered by code.
- `GET /api/v1/ui-strings/<locale>` returns one published language's full
  pack: `{version, locale, native_name, bcp47_tag, direction, reviewed,
  strings, form}`. `strings` is the app namespace and `form` the WHO form
  labels (keys without the `form:` prefix): the bundled text with the accepted
  corrections over it, or the accepted rows alone for a language with no
  bundle. Only keys of the English reference are served, and machine drafts
  never. `en`, and any unpublished locale, is `404`.

If the export cannot be read (the folder or `en.json` missing mid-deploy, a
file that is not UTF-8 JSON) both reads answer `503` (`unavailable`), never a
shortened list: a phone drops the pack of a language the list no longer names.

Each built pack is kept in process memory, one entry per published language,
until its fingerprint moves: the export folder, the corrections' version
(count and newest edit of the accepted rows), the language row's edit time and
the mtimes of `<locale>.json`, `theme-<locale>.json`, `form-<locale>.json` and
the three `en` files. A repeat or revalidating read costs two small queries
and six `stat` calls; the list reads every language's version in one query.

`version` is the SHA-256 of the rest of the body, so it moves with a
correction and with a rebuilt export alike. `reviewed` is the share (0 to 1,
three decimals) of the reference keys, both namespaces, whose text an
administrator wrote or accepted; bundled text counts as unreviewed. The app
labels a language "machine-translated" by this share.

Compatibility: before digitva-s028 `strings` held the corrections only. No
released app read the endpoint (the client was digitva-dt1e), and a full pack
laid over a bundle gives the same text as the corrections laid over it, so the
field kept its name.

The admin export (`/admin/api/ui-strings/<locale>/export`) holds the app
namespace only. `flask ui-strings bake` still writes `<locale>.json` from the
keys of `en.json`, so accepted theme-screen and form-label rows have no bake
path yet: theme rows are served from the pack, and form labels move into
`vendor/who-va-2022/src/languages/ui.ts` by hand at a release.

## The app side (digitva-dt1e)

`mobile/digitva-collect/src/uiPacks.ts` fetches the list and the pack it needs
when the app can reach its server (start, language switch, after a phone
sync), keeps the last list and the last pack per language on the device
(`src/uiPackStore.ts`: localStorage in a browser, a file under the app's
documents folder on a phone; packs are reference text, not PII), and lays the
pack over the bundled dictionary in `t()`. Offline it uses the stored pack;
with none, the bundled text; missing keys fall back to English. Each key is
checked again on the phone (a known English key, the same placeholder set, no
markup or control characters) and a key that fails is dropped, never applied.
When a fetched list no longer offers a language whose pack the app holds (it
was unpublished), the app drops that pack in memory and overwrites its stored
file, so a bundled language shows its bundled text again. A list request that
fails (offline, `503`, any non-200) changes nothing: the stored list and packs
stay.
Before enrolment and in standalone mode only the bundled languages (English,
Hindi) are offered. `useUiLanguages()` gives every screen the one list.

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
- **Pacing and resumability:** requests are at most 100 texts / 10,000
  characters, paced to `AZURE_TRANSLATOR_CHARS_PER_MINUTE` (default 30,000) with
  `Retry-After` honoured on 429/503. Drafts are committed per request, so a
  failure part-way keeps them and a rerun drafts only the remainder; the page
  shows the language's error message.

## Keeping translations across a cutover (decided 2026-10-24, digitva-3b65)

Translations made on staging (machine drafts and reviewed or edited text) must
not be lost when production goes live. Two routes, used together:

- **Dump and load.** `flask translations dump <file.json>` writes every row of
  `mas_ui_string_override` and of the questionnaire store
  (`map_instrument_translations`, see `docs/policy/va-form-project-configuration.md`,
  "Carrying translations across servers"), all sources including `machine`.
  `flask translations load <file.json> [--dry-run]` inserts them on the target.
  Load is insert-only and idempotent: a row whose (locale, key) already exists
  on the target, of any source, is skipped and never overwritten. Authors travel
  as email addresses (user ids differ between servers); an unknown email loads
  as no author and is counted. The file holds translations only: no secrets, no
  personal data. Texts are never logged.
- **Bake into the app.** `flask ui-strings bake --locale hi --out <dir>` writes
  the bundled locale file with the accepted (`edited`) overrides merged over it,
  in the source format of `mobile/digitva-collect/src/strings/<locale>.json`
  (key order of `en.json`, two-space indent, no ASCII escaping, trailing
  newline). Only keys present in `en.json` are written, and a placeholder set
  that differs from the English stops the bake with nothing written. Machine
  drafts are excluded. A locale with no bundled file yet (pa, mr, ...) gets one
  built from accepted rows only. The command reads the database it runs against,
  so run it on the server holding the reviewed strings.

Workflow: translate and review on staging -> `bake` -> the owner commits the
files -> release the app. After a bake the override rows may stay: they equal
the bundle. Machine drafts are carried by dump and load only, never baked.

## Storage

Corrections and machine candidates live in `mas_ui_string_override`, one row per
(locale, key), told apart by `source` (`edited` or `machine`); form labels use
the `form:` key prefix. Reverting deletes the row. The UI languages and their
published flag live in `mas_ui_locale`. The downgrade of its migration refuses while rows exist.
See `docs/current-state/data-model.md`.

## Related

- `docs/policy/va-form-project-configuration.md` ("Translation sources"): the
  questionnaire editor this one copies.
- `docs/current-state/expo-client.md`: the export and the `dist/ui-strings`
  folder.
