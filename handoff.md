# Handoff

## Start here

Fully offline DORIS coding in Collect Plus (`digitva-9cll`). Collect and Collect
Plus 0.3.16 are live on staging (`3d5cf4f06`, web `expo-web-v2026.10.30.2`).
main carries 0.3.17 (standalone home tabs, list refresh, actions in Settings,
picker keyboard), not yet built: the owner dispatches the CI release. Never
reset or stash; preserve the unrelated `scripts/loadtest/restore.sh`,
manuscript decks, tool-config and Play artwork changes. WHO notes, parity runs
and phone measurements live in `private/` (git-ignored; also holds keys).

Owner rule (bd memory `coding-parity-all-surfaces`): coding works the same on
the web, Collect online and Collect Plus online and offline. NQA and Social
Autopsy follow the project setting online and for enrolled accounts; standalone
has neither, and its coding is one direct step with SmartVA visible.

## Ranked next steps

1. Verify 0.3.17 on the USB Samsung (RZCW81QZT2Z) once the owner has built and
   installed it: tabs, name/age/sex, list refresh after back and after
   finalize, Settings actions, picker keyboard. Release builds only (owner
   2026-10-30: no local debug build on the phone; the debug variant is a
   separate `.dev`/`.plus` package anyway).
2. `digitva-9cll.5` phone proof, still to do: standalone certificate steps
   (search, Use, Build/axes, details, hierarchy, XK8G/NC72 refusals, DORIS,
   CoDEdit, save shows Coded), then an enrolled TST001 coder offline (the owner
   signs in), incl. when `:icd11` starts. Done 30 Oct: standalone record,
   finalize, SmartVA, coding opens; `:icd11` started 0.53 s after tapping
   Offline coding, not at launch (so `docs/policy/field-data-collection.md` is
   right for standalone; check enrolled before closing). Capture:
   `private/engine-measurements/20261030-coding-journey` (icd11 PSS max 819 MB,
   no LMK).
3. `digitva-ljx2` (P1): standalone finalize shows "Something went wrong" after
   the draft is already completed. Reproduce on the emulator debug build to see
   the JS error.
4. `digitva-9cll.22` coding parity (P1), children ranked: `.22.2` online phone
   attachments never load (likely one prop), `.22.4` enrolled offline NQA/SA
   ignore the project and import skips the gates, `.22.3` native category view
   below the web's, `.22.5` offline not-codeable/remark, `.22.6` SmartVA sex
   raw code. The offline case-data view (local CategoryPayload from a bundled,
   drift-tested display-config pack) is the parent's main work. Policy
   baseline first.
5. `digitva-9cll.23` standalone direct coding ("Save cause of death").
   `digitva-9cll.24` coded case: one read-only summary screen (as the Expo
   web completed-case view) with Revise reopening coding pre-filled; the Coded
   tab's interim "Revise coding" then opens it.
6. `digitva-gt2v`, `digitva-bged`: offline reply-shape and Build/axes bugs.
7. DORIS validation gaps in `docs/current-state/doris-validation-checks.md`:
   `digitva-l0ey`, `digitva-2j57`, `digitva-e505`, `digitva-giym`,
   `digitva-o16a`, `digitva-37gr`.
8. `digitva-9cll.11` CI engine build not byte-identical; `digitva-9cll.13`–`.21`
   Android ICD/DORIS review findings.

## Open owner decisions

- Send the WHO technical note (`docs/manuscript/who-technical-note-offline-icd11-doris.md`,
  one `[OPEN]`: a WHO contact email).
- `digitva-9cll.14`: should an enrolled phone send the interview when its
  offline coding is rejected or stale?
- `digitva-dn15`: should the ECT selection check also refuse non-leaf categories?
- Hindi strings awaiting approval (incl. 0.3.17's tab, Settings and backup
  strings; `src/i18n.ts` REVIEW NEEDED note).
- WHO data files' duplicated sha256 values: keep both, or add a drift check.
- CI as the engine release source (after `digitva-9cll.11`).

## Boundaries still true

- Golden corpora are owner-approved and frozen (`scripts/icd11-golden/README.md`).
- Release builds only on CI; local debug builds for the emulator only. Engine
  bundles use only public, unrestricted inputs. Publishing releases is the
  owner's command; the agent approves gates.
- On the owner's real phone: no PINs, passwords or system settings; leave the
  "vivekdemo" account alone. Emulator accounts: `private/emulator-test-accounts.md`.
- Plus stays prerelease; WHO has not answered the licence points in writing.
- Device ICD/DORIS coding starts off; enabling grants no permission.
- No Fable agents (weekly usage).

## Caveats

- Old APKs show "The selected code does not match its WHO URI." for the
  extension/category refusals (same `INVALID_SELECTION` 422).
- 0.3.16 phones: the standalone home list is stale until Lock and unlock.
- Local vendor `dist` may lag the engine source: run `npm run vendor:build` in
  `mobile/digitva-collect` before a local device build.
