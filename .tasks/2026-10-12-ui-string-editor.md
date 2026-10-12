# Server page to correct Expo UI strings

- Status: approved (owner, 2026-10-12), not started
- Priority: P2
- Created: 2026-10-12
- Beads: `digitva-fsjz` server store, API and admin page;
  `digitva-dt1e` Expo overlay

## Goal

A native reader corrects any Expo UI string in any of the ten UI languages
(en, hi, pa, mr, kn, ta, ml, te, gu, or; `digitva-1g1h`) on a server page,
and the fix reaches every browser without a new Expo build.

## Shape

- **The bundled JSON stays.** `mobile/digitva-collect/src/strings/<locale>.json`
  remains the shipped default and the offline fallback for the native app.
  English (`en.json`) is the reference: its keys are the only keys, and its
  `{placeholders}` must survive every translation.
- **Server overrides.** One row per (locale, key) the reader changed, with
  text, status and who and when. Copy the questionnaire editor's pattern
  (`app/services/instrument_translation_service.py`, `update_string`):
  per-locale version bumped on every edit, statuses, the same text checks
  (no markup or placeholders the English lacks, length cap), and an audit of
  each change. Reuse its tables if a UI namespace fits them cleanly;
  otherwise a new `mas_ui_string` table in an additive migration.
- **Reference keys on the server.** The server needs `en.json`'s keys and
  English text to refuse unknown keys and to show the English beside each
  string. Read it from the served Expo export (`EXPO_CLIENT_DIST`) or a
  committed copy refreshed by the Expo build; decide in implementation, never
  hand-edit a generated copy.
- **API.** `GET /api/v1/ui-strings/<locale>` returns `{version, strings}`
  (overrides only), public to signed-in and signed-out clients alike (the
  login screen is translated too), cacheable by version.
- **Expo.** On start and on a language switch, fetch the overrides for the
  current locale and lay them over the bundled dictionary; keep the last set
  per locale so a reload without network still shows the corrections.
- **Admin page.** Under Setup, beside the questionnaire translations editor:
  pick a language; a table of key, English, current text (bundled or
  corrected), status; filter by "machine draft", "corrected", "missing";
  edit inline; revert a correction to the bundled text.
  Each row has a "Google Translate" link (owner, 2026-10-12) opening
  `https://translate.google.com/?sl=en&tl=<locale>&text=<English, URL-encoded>&op=translate`
  in a new tab (`target="_blank" rel="noopener noreferrer"`), for a quick
  look-up while correcting. Only the English reference string is ever put in
  the link, never the current translation or any data; it is a static UI
  string with no personal data. `{placeholders}` stay in the text so the
  reader sees where they go. The link is a plain anchor built in the
  template; the server makes no call to Google. Admin only, as
  Setup is (owner, 2026-10-06), unless a translator role is decided later.
- **Feeding corrections back.** An export of the corrections per locale as
  JSON, so the Expo session can fold them into the bundled files at release.

## Tests

Unknown key refused; placeholder or markup the English lacks refused; empty
refused; version bumps on edit and on revert; the API returns only that
locale's overrides; a non-admin cannot edit; CSRF on the edit calls.

## Decided

- Admin only (owner, 2026-10-12), as Setup is; no translator role.
