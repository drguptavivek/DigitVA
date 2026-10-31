# Handoff

## Start here

Fully offline DORIS coding in Collect Plus (`digitva-9cll`). Collect and Collect
Plus 0.3.16 are live on staging (`3d5cf4f06`, web `expo-web-v2026.10.30.2`).
Collect Plus 0.3.17 is on the USB Samsung. main carries 0.3.18 (phone-check
fixes, finalize race, DORIS pre-start and spinner; see CHANGELOG): the owner
dispatches the CI releases. Never
reset or stash; preserve the unrelated `scripts/loadtest/restore.sh`,
manuscript decks, tool-config and Play artwork changes. WHO notes, parity runs
and phone measurements live in `private/` (git-ignored; also holds keys).

Owner rule (bd memory `coding-parity-all-surfaces`): coding works the same on
the web, Collect online and Collect Plus online and offline. NQA and Social
Autopsy follow the project setting online and for enrolled accounts; standalone
has neither, and its coding is one direct step with SmartVA visible.

## Ranked next steps

1. Offline coding shows the full coding interface (owner 2026-10-30): reuse
   the `CaseWorkspaceScreen` the regular Collect app already runs online,
   driven by a local `WorkspaceApi` (local `getWorkspace`/`getCategory` from
   the draft plus a bundled, drift-tested category/field display pack, offline
   media slot, DORIS in `renderDoris`). This is `digitva-9cll.22`'s main work;
   policy baseline first.
2. Verify 0.3.18 on the USB Samsung (RZCW81QZT2Z) once built: icons and
   confirmations, Hindi wrap (Id10128/Id10129/Id10484), certificate camera and
   preview, standalone document questions, tabs and row buttons, no error after
   Complete (`digitva-ljx2`), Send now disabled, DORIS warm on the Pending tab
   (`digitva-4j8h`; ICD11WARM in logcat) and the spinner. Then close
   `digitva-9l5c`, `digitva-ljx2`, `digitva-4j8h`. Release builds only.
3. `digitva-9cll.5` phone proof, still to do: standalone certificate steps
   (search, Use, Build/axes, details, hierarchy, XK8G/NC72 refusals, DORIS,
   CoDEdit, save shows Coded), then an enrolled TST001 coder offline (the owner
   signs in), incl. when `:icd11` starts. Done 30 Oct: standalone record,
   finalize, SmartVA, coding opens; `:icd11` started 0.53 s after tapping
   Offline coding, not at launch (so `docs/policy/field-data-collection.md` is
   right for standalone; check enrolled before closing). Capture:
   `private/engine-measurements/20261030-coding-journey` (icd11 PSS max 819 MB,
   no LMK).
4. `make collect-plus-local` (debug-signed local verification build, not for
   distribution): container mode untested end to end (Docker 12 GB or more;
   24 GB set 2026-10-31); `NATIVE=1` builds on the Mac (Node 24 and Java 21
   accepted with a warning) built a debug-signed APK end to end on
   2026-10-31 in 4.5 min (4,313 Jest tests, module JVM tests, assembleRelease)
   after the source copy kept `resource/doris_help_examples.json` (that fix is
   uncommitted at the time of writing).
   The engine's memory grew 511 MB to 1,082 MB over the 50,959-call full
   parity run (591 MB on 29 Oct without the golden/sweep entity reads);
   attributed to WHO's entity cache, not confirmed.
5. `digitva-9cll.22` coding parity (P1), children ranked: `.22.2` online phone
   attachments never load (likely one prop), `.22.4` enrolled offline NQA/SA
   ignore the project and import skips the gates, `.22.3` native category view
   below the web's, `.22.5` offline not-codeable/remark, `.22.6` SmartVA sex
   raw code. The offline case-data view (local CategoryPayload from a bundled,
   drift-tested display-config pack) is the parent's main work. Policy
   baseline first.
6. `digitva-9cll.23` standalone direct coding ("Save cause of death").
   `digitva-9cll.24` coded case: one read-only summary screen (as the Expo
   web completed-case view) with Revise reopening coding pre-filled; the Coded
   tab's interim "Revise coding" then opens it.
7. `digitva-gt2v`, `digitva-bged`: offline reply-shape and Build/axes bugs.
8. DORIS validation gaps in `docs/current-state/doris-validation-checks.md`:
   `digitva-l0ey`, `digitva-2j57`, `digitva-e505`, `digitva-giym`,
   `digitva-o16a`, `digitva-37gr`.
9. `digitva-9cll.11` CI engine build not byte-identical; `digitva-9cll.13`–`.21`
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
