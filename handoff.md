# Handoff

## Start here

Fully offline DORIS coding in Collect Plus (`digitva-9cll`). Collect and Collect
Plus 0.3.15 are released; the engine builds on CI (`01b41cb8d`). The final-code
picker guard (`digitva-9cll.12`) and the web interviewer-name fix
(`digitva-k7m4`) are in this tree but not on staging. Never reset or stash;
preserve unrelated loadtest, manuscript, tool-config and Play artwork changes.

## Ranked next steps

1. Staging deploy of `digitva-9cll.12` + `digitva-k7m4` on the owner's go
   (`scripts/deploy-staging.sh <sha>`, old-APK audit first). Close `k7m4` after.
2. `digitva-9cll.5`: phone proof of the full offline coding journey on the USB
   Samsung (release Plus APK from CI), incl. XK8G/NC72 refusals and the web
   picker in a browser (checked on the emulator only).
3. `digitva-gt2v`, `digitva-bged`: offline reply-shape and Build/axes bugs.
4. DORIS validation gaps from `docs/current-state/doris-validation-checks.md`:
   `digitva-l0ey` (web mandatory-stem guard), `digitva-2j57` (offline pack only
   at save), `digitva-e505` (server ranges vs V11), `digitva-giym`, `digitva-o16a`,
   `digitva-37gr`.
5. `digitva-9cll.11`: CI engine build is not byte-identical to the Mac release
   (build ID, `.comment`, ~1.6 KB `.rodata`); blocks CI becoming the release source.
6. `digitva-9cll.8`/`.9`: offline DORIS demo in Help; public demo deploy.
7. Play listing `digitva-91f2` (Collect only; Plus APK-only until WHO writes).
8. `digitva-hs7e.15.2` (authorized release of a submitted shared-case refusal
   hold; parent `.15` and epic `hs7e` stay open for it).

## Open owner decisions

- `digitva-dn15`: should the ECT `/api/v1/icd11/selection-check` also refuse the
  2,077 non-leaf categories DORIS now refuses?
- 11 Hindi strings shown to the owner for approval.
- WHO data files' duplicated sha256 values: keep both, or add a drift check.
- CI as the engine release source (after `digitva-9cll.11`).

## Boundaries still true

- Golden corpora are owner-approved (2026-10-30) and frozen; a change sets them
  back to `draft` and goes to the owner (`scripts/icd11-golden/README.md`).
- Release builds only on CI; local debug dev builds for the emulator only.
  Engine bundles use only public, unrestricted inputs.
- On the owner's real phone: no PINs, passwords or system settings (airplane
  mode); the owner creates accounts. Leave the "vivekdemo" account alone.
  Emulator test accounts live in `private/emulator-test-accounts.md`.
- Plus stays prerelease; WHO written redistribution clearance is pending. Owner
  publication authorization is not WHO permission.
- Device ICD/DORIS coding starts off; enabling grants no permission. WHO or DP
  refusal stops collection and coding in every mode.

## Caveats

- Old APKs show "The selected code does not match its WHO URI." for the new
  extension/category refusals (same `INVALID_SELECTION` 422).
- Each extra `/` cluster stem in a selection check costs 2 WHO calls.
- Emulator: the deep link `digitvacollectdev://doris-demo` did not resolve on
  emulator-5554; open Help > Try DORIS instead. `adb input text` with "rr"
  reloads JS.
