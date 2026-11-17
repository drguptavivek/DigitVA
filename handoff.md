# Handoff

## Start here

Staging runs `019e8ac7e`. Main is at `e6a17915d` plus beads-only commits;
its server image is built (`ghcr.io/drguptavivek/digitva-app:e6a17915dddb741acd57abbf084e65a5b9f5ad3b`)
and pins Collect 0.3.23 (APKs verified: versionCodes 3232/3231, release
cert). The owner approved the deploy on 2026-11-17; it stopped only because
the AWS `digitva` session had expired. Once the owner has run
`aws login --profile digitva` and says go, run
`scripts/deploy-staging.sh e6a17915dddb741acd57abbf084e65a5b9f5ad3b`.
The old-APK audit of `019e8ac7e..e6a17915d` is done: old apps accept the
new `access_changed` notification (any kind string, empty `project_id`),
the one migration (`d8a2f4c6e1b3`, `map_project_members`) is additive, and
nothing touches unsent work.

Owner rule (bd memory `coding-parity-all-surfaces`): coding works the same on
the web, Collect online and Collect Plus online and offline. Design rule:
Collect screens are frozen (`docs/design/collect-petrol-theme/README.md`);
any change to one is re-checked against `frozen/` and refrozen.

## Ranked next steps

0. Deploy `e6a17915d` to staging (above). Afterwards check on staging: the
   roster person page (`digitva-eyp3`, closed), `/download/android` serves
   0.3.23, and on a phone consent "No" then back (Id10013 fill) and the
   ICD-11 first-launch prompt.
1. Training (`digitva-9qer`, `digitva-q3iu`): owner supplies
   `app/services/training_corpus/english_v1.txt`; Maestro flows 96–98 need a
   trainee setup role; training media scope; refuse outdated apps (N11);
   hide DEMO01 in graduation; participant roles by session type.
2. Prove the full offline coding flow on a phone (`digitva-9cll.5`),
   standalone then as an enrolled TST001 coder. Coding parity remainder:
   `digitva-9cll.22` (`.22.3`–`.22.6`, `.22.8`, `.22.9`); ICD-10 parity
   `digitva-tk7j`.
3. Backend performance epic `digitva-f41g` (21 beads, filed not fixed,
   owner: "dont fix for now"). P1s `.1`–`.5`: repair batching, SmartVA
   pending scan, backfill stats filesystem checks, coder gate computed three
   times, non-concurrent MV refresh after DM actions. Unmeasured: confirm on
   production stats first. `.10` and `.20` need an old-APK check.
4. Roster follow-ups: `digitva-sjts` (grant-then-issue QR), `digitva-42yo`
   (code endpoint vs grid for deactivated accounts). Optional, offered and
   not approved: hide other projects' actor names in the person page's
   account events.
5. Collect: TalkBack/VoiceOver (`digitva-eizq`), Play screenshots
   (`digitva-fthd`; raw captures untracked in
   `mobile/digitva-collect/store/play/screenshots/`), arm64 engine
   `load_failed` (`digitva-rih6`), SM-E146B speed (`digitva-xxfz`), web
   attachments (`digitva-e621`). Owner review of the Hindi strings.
6. Offline PHC station macOS security acceptance (`digitva-xt9y`).
   Standalone engine `v0.1.0` draft awaits owner publish (`digitva-xw1s`).
7. Help chatbot PII redaction (`digitva-wawz`). DORIS validation gaps
   (`docs/current-state/doris-validation-checks.md`). iOS simulator CI
   workflow (`digitva-bfq3`).

## Open owner decisions

- Staging deploy timing (approved; waiting on AWS sign-in).
- When to start `digitva-f41g` fixes.
- Send the WHO technical note (one `[OPEN]`: a WHO contact email).
- Engine `tests/fixtures/doris_help_examples.json` provenance; WHO data
  files' duplicated sha256 values; CI as engine release source.
- InterVA2022/InSilicoVA2022 experimental: no go yet.
- AI interview-quality checks on hold (`digitva-qtmq`).

## Boundaries still true

- Staging deploys only via `scripts/deploy-staging.sh <full sha>` on the
  owner's go. `server-images.yml` needs the full 40-char sha.
- Release builds only on CI; local debug builds for development only.
  Publishing releases and tags is the owner's command.
- Golden corpora are owner-approved and frozen.
- On the owner's real phone: no PINs, passwords or system settings.
- Plus stays prerelease; device ICD/DORIS coding starts off.
- No Fable agents.

## Caveats

- Full-suite noise under `-n 4`: `digitva-6igh`, and 9 export streaming
  tests (`digitva-jaea`) that pass serially.
- Untracked on purpose: the orientation deck files under `docs/manuscript/`
  (owner: don't commit), `.claude/launch.json`, the Play screenshots.
  Full parity TSVs live in `private/icd11-parity/results/`.
- Test databases still present for other work: `minerva_test_codeapp`,
  `_consent`, `_pii`, `_tst002` (and their `_gw*`).
- `npm run vendor:build` reinstalls the vendor package: stop Metro first
  and restart it with `--clear`.
- Old APKs show "The selected code does not match its WHO URI." for the
  extension/category refusals (same `INVALID_SELECTION` 422).
