# Handoff

## Start here

Fully offline DORIS coding in Collect Plus (`digitva-9cll`). Collect and Collect
Plus 0.3.16 are released and live on staging (`3d5cf4f06`, web
`expo-web-v2026.10.30.2`, hosted APKs copied). Never reset or stash; preserve
the unrelated `scripts/loadtest/restore.sh`, manuscript decks, tool-config and
Play artwork changes. WHO notes, parity runs and phone measurements live in
`private/` (git-ignored; also holds keys).

## Ranked next steps

1. `docs/manuscript/who-technical-note-offline-icd11-doris.md`: owner adds a
   WHO contact email (the one `[OPEN]`), reads it, and sends it. It is checked
   against the repo; its 30 Oct phone figures were sampled every 2–3 s.
2. `digitva-9cll.5`: phone proof of the full offline coding journey on the USB
   Samsung with Plus 0.3.16, incl. the XK8G/NC72 refusals.
3. `digitva-axim`: Collect Plus home cleanup (enrol, export, backup, restore
   move to Settings).
4. `docs/policy/field-data-collection.md` says the engine starts only when
   eligible coding opens; on the phone it starts 2.6–4 s after launch when
   coding is enabled (owner: fine). Find the trigger and fix the line.
   `digitva-48qf` (P3): background thread priority only if lag is reported.
5. `digitva-gt2v`, `digitva-bged`: offline reply-shape and Build/axes bugs.
6. DORIS validation gaps in `docs/current-state/doris-validation-checks.md`:
   `digitva-l0ey`, `digitva-2j57`, `digitva-e505`, `digitva-giym`,
   `digitva-o16a`, `digitva-37gr`.
7. DORIS doc consolidation into 4 docs (design decisions, validations, parity,
   engine performance), as its own commit; fix `android-release-builds.md`'s
   local release build text.
8. `digitva-9cll.11`: CI engine build not byte-identical to the Mac release.
9. `digitva-9cll.13`–`.21` (Android ICD/DORIS code review findings), e.g.
   `.13` JNI non-BMP characters, `.16` init retry per process.

## Open owner decisions

- `digitva-9cll.14`: should an enrolled phone send the interview when its
  offline coding is rejected or stale?
- `digitva-dn15`: should the ECT selection check also refuse non-leaf
  categories?
- Hindi strings awaiting approval (incl. the new language-menu and standalone
  profile strings; `src/i18n.ts` REVIEW NEEDED note).
- WHO data files' duplicated sha256 values: keep both, or add a drift check.
- CI as the engine release source (after `digitva-9cll.11`).

## Boundaries still true

- Golden corpora are owner-approved and frozen; a change goes back to `draft`
  and to the owner (`scripts/icd11-golden/README.md`).
- Release builds only on CI; local debug builds for the emulator only. Engine
  bundles use only public, unrestricted inputs. Publishing releases is the
  owner's command (the agent's dispatch is refused); the agent approves gates.
- On the owner's real phone: no PINs, passwords or system settings; leave the
  "vivekdemo" account alone. Emulator accounts: `private/emulator-test-accounts.md`.
- Plus stays prerelease; WHO has not answered the licence points in writing.
- Device ICD/DORIS coding starts off; enabling grants no permission.
- No Fable agents (weekly usage).

## Caveats

- Old APKs show "The selected code does not match its WHO URI." for the
  extension/category refusals (same `INVALID_SELECTION` 422).
- The VA cause lookup now returns 200 with an empty definition where it used
  to 404 for a bucket without one; old APKs show the label alone.
- Local vendor `dist` may lag the engine source: run `npm run vendor:build` in
  `mobile/digitva-collect` before a local device build.
