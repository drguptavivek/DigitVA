# Handoff

## Start here

Staging runs `5a3f994b3` (deployed 2026-11-26 on the owner's go; web
`expo-web-v2026.11.26.2`; migrations at `b5e2c8d4a9f7`; rollback, no
migration downgrade needed:
`sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh 634711950599b575b20387a9e805bc29adefc96c`;
the demo stack runs the same commit as `digitva-demo-app:5a3f994b3`, its
previous env saved at
`/data/digitva-demo.env.pre-5a3f994b3`;
EBS snapshots and pg_dump in `CHANGELOG.md` 2026-11-26). The image carries 0.3.31
(`android-v0.3.31`, `collect-plus-v0.3.31-plus.1`; supersedes 0.3.30, which
never reached phones); phones are offered 0.3.31 since 2026-11-26. Play AAB
0.3.31 (run 45770414218, expires about 2026-12-10) awaits the owner's upload.
No device check of 0.3.30 or 0.3.31.

Owner decisions:
- Next web release and APK: main carries the case-definition line-break fix
  (the web workspace on staging still shows one run-on paragraph).
- Homepage "DigitVA in use" counts only HMR001 (10 interviews): tick
  "Included in homepage KPIs" in Admin → Projects for the projects that are
  programme data (candidates by size: ICMR01, UNSW01, KEM001, TELE01).
- Redis outage 500s every request through the IP-ban check (`digitva-248z`):
  fail open or closed is the owner's call.
- Rerun training setup on staging (`digitva-veq5`); until then a reviewer
  trainee at a sub-centre may get `grant_not_allowed`.
- Not verified after the deploys: the signed-in pages (coding, training
  interview, ICD search, System health, a data manager's user management
  site list from `digitva-b94q`, ICD-10 VA definitions from `digitva-31ac`,
  the web org-unit pickers, the save-burst check `digitva-3ko3`), which need
  the owner's sign-in.
- Never re-run the ICD-10 CSV or policy import on staging: it re-enables the
  withdrawn R00-R94 codes (`1f037b4717e4`; R50 and R54 stay selectable by
  design).
- The sixteen pre-deploy EBS snapshots (tags `release=0.3.30`,
  `release=cb5c903c1`, `release=634711950` and `release=5a3f994b3`) never expire; delete them when no longer needed.

Owner rules: coding works the same on the web, Collect online and Collect
Plus online and offline (bd memory `coding-parity-all-surfaces`); Collect
screens are frozen (`docs/design/collect-petrol-theme/README.md`) and are the
DORIS reference the web follows; the Collect app uses no WebView or web page
for any screen (the WHO ICD browser, privacy and data requests, store links
and maps stay in the browser).

## Ranked next steps

- Device-check 0.3.31 (now offered to phones; adds the org-unit lineage
  pickers): re-enrol from Sign in again (`digitva-dbcw`), DORIS
  interview/report death dates, case summary, Reset DORIS dialog, COD form
  PDF on staging. Flaky under `-n 4`: `digitva-9czl`, `digitva-wd09`.
- Bulk invitations: owner gets the mail host's SMTP limits and relay logs
  for 21 and 23 Nov, then tune pace and backoff (`digitva-povs`). Pacing is
  per import only. 86 staging users whose 21 Nov invitations failed still
  need a resend from Users if the owner wants it; find unsent ones by
  grepping celery_tasks.log / errors.log for "gave up".
- Supervisor corrections (`digitva-hftq` open; policy interview-revisions.md
  "Supervisor correction", mobile-sign-in.md "Interview supervisors on the
  phone"): server, browser and phone list/case/death edit and Edit
  interview landed (migration `a7d3e9c5b2f1` since staging); first design
  review fixes in `c31195040` (screenshots in
  private/screenshots/supervisor-phone-2026-11-24). Left: owner look at the
  fixed screens, a CI APK device check (include the death edit's new
  informant, phone, ABHA, GPS and registration fields). `data_manager` on
  the phone: owner "not now" (2026-11-24, mobile-sign-in.md). Maestro 60/70/75/81 passed together
  on 2026-11-25 (flow 70 runs 36-61 min; `run-suite.sh` needs per-flow caps
  over an hour, `digitva-flkc`). Dev test DB
  `minerva_test_sup` kept for this.
- Org-unit pickers show each unit's lineage underneath (on staging's web
  since `cb5c903c1`; not in any APK yet, checked on a 0.3.20 debug build only, include it in the next CI
  APK check). The Users filter still lists bare names until the server
  sends unit paths (`digitva-p6fs.36`).
0. Consent withdrawal landed (`digitva-4gu7`); erasure of a withdrawn case
   is not built (owner to decide). Migrations since staging:
   `e3b7c9d1f5a2`, `f4c2a8e6b1d9`. Follow-ups: phone SA panel
   (`digitva-088j`), native mentor view (`digitva-3vj8`). Do not retire the
   server picker page before 2027-01-20 (`digitva-dxg1`).
1. Device check of today's Collect changes on a CI-built APK
   (`digitva-9m8o`). Earlier phone checks still open: offline coding journey
   (`digitva-9cll.5`), coding parity remainder (`digitva-9cll.22`), ICD-10
   parity (`digitva-tk7j`), real-phone document scan (`digitva-e2ju`).
2. Training (`digitva-9qer`, `digitva-q3iu`): owner supplies
   `app/services/training_corpus/english_v1.txt`; Maestro flows 96-98 need a
   trainee setup role; training media scope; refuse outdated apps (N11);
   hide DEMO01 in graduation; participant roles by session type.
3. Retire the server picker page after the APK rollout (`digitva-dxg1`).
4. Ready P1 beads audited 2026-11-19: none secretly done except `rou1`
   (closed). Open with code ready, owner action left: `yacr` (re-count KEM001
   and run the repair), `ddfx` (Aadhaar sweep on staging), `77ti` (count on
   staging), `zkgx` (Hindi review). Partly done: `yeg3.1`, `9cll.22.3`,
   `r9lk`, `xjpk`, `xk41`, `rpqp`. Open: `yeg3.18`, `yeg3.24`, `342x`,
   `bx43`, `7amd.27` (due 2027-10), `9cll.18`, `1b50`, `p8uj`, `oux5`.
5. Code audit refactors (epic `digitva-r8nh`). Waves 1-3 landed
   2026-11-24, wave 4 (Collect `.22`, `.23`, `.24`, `.26`) and wave 5
   (backend `.9`, `.13`, `.15`, slices of `.11`, `.14`, `.17`) and wave 6
   (leftover slices of `.9`, `.13`, `.14`, `.15`) 2026-11-25:
   `.25`, `.12`, `.16` closed (owner holds their behaviour changes `.33`,
   `.34`); `.5`, `.8`, `.9`, `.11`, `.13`, `.14`, `.15`, `.17`, `.20` have
   slices in, next slice in each bead's notes (`.5` api_v1 errorhandler:
   read-only pass first, owner if uncaught-exception replies change; then
   `.20` transport/authed retry). Pre-existing DM API bugs pinned, not
   fixed: `.37`, CSV header collisions and snapshot `unique_id` `.38` (owner).
   `.13` leftover (`_build_repair_map_for_form`,
   `_refresh_batch_plan_after_enrichment`) needs test patch-target edits:
   owner. Not started: `.6`, `.7`, `.10`, `.18`, `.19`,
   `.21`, `.27`-`.29`; ask the owner before starting. Every one follows the epic's
   behaviour-preservation protocol (bd memory
   `refactor-behaviour-preservation`): characterization tests first,
   committed before the refactor; tests unedited (check with a diff);
   independent equivalence review. Run one writer at a time on
   `app/__init__.py` (`.5`, `.6`, `.7`); `.19` waits on `.18`. Parallel
   writers' full suites exhaust Postgres shared memory: writers run
   targeted tests only, one full suite on the combined result. Expo
   worktrees need `npm ci` plus the WHO `dist` copied into `vendor/` and
   `node_modules` (no symlinks) for check-web.
6. Backend performance epic `digitva-f41g` (owner: "dont fix for now").
7. Collect: TalkBack/VoiceOver (`digitva-eizq`), Play screenshots
   (`digitva-fthd`; raw captures untracked), SM-E146B speed (`digitva-xxfz`),
   camera result after Android kills the app (not built). Owner review of the
   Hindi strings, including today's new ones.
8. Offline PHC station macOS acceptance (`digitva-xt9y`). Help chatbot
   (`digitva-wawz`): unbuilt; must use a CPU or edge small model, no paid API.

## Open owner decisions

- Final COD: reviewer workflow-state refusals stay 403/400 `wrong_state`
  where the coder gets 409 (kept on purpose in `digitva-r8nh.2`); aligning
  them needs an old-APK check. The global admin toggle still does not
  invalidate the user's authz cache (as before `r8nh.3`). The public-demo
  dashboard can lag 5 minutes after a data-manager action.
- Refactor findings, kept as they are until decided: phone and server word
  the causing-condition-unknown refusal differently (`r8nh.30`); create_app
  hook oddities (`r8nh.31`); device auth: a revoked device's refresh writes
  no audit row, three routes may be missing from the unauthenticated list
  (`r8nh.32`, old-APK check first).

- Golden postcoordination fixtures: 12 re-recorded on 2026-11-19 then the
  change reverted; the corpus is unchanged and approved.
- `kkdb` step 2 (on-device Dictate button); `wawz` start.
- Send the WHO technical note (one `[OPEN]`: a WHO contact email).
- Engine fixture provenance; WHO data files' duplicated sha256 values; CI as
  engine release source; InterVA2022/InSilicoVA2022 experimental: no go yet.
- AI interview-quality checks on hold (`digitva-qtmq`).
- Owner items: DORIS production ingress (`ddv.2`), engine v0.1.0 publish
  (`xw1s`), Play listing (`91f2`), translations (`fb5`), manuscript
  (`3kpb`), legal review (`gyfj`), engine pin on CI (`9cll.10`), rotated
  staging passwords (`jb4t`).

## Boundaries still true

- Staging deploys only via `scripts/deploy-staging.sh <full sha>` on the
  owner's go. Release builds only on CI; publishing is the owner's command.
- Golden corpora are owner-approved and frozen.
- Required ICD-11 postcoordination is a picker rule; the server accepts a
  bare stem (docs/policy/icd11-code-selection-principles.md section 4).
- On the owner's real phone: no PINs, passwords or system settings.
- Plus stays prerelease; device ICD/DORIS coding starts off. No Fable agents.

## Caveats

- `digitva-4650` deployed: the `/me` snapshot of all 662 staging users
  showed no access change. Old cadre columns stay until `digitva-8qh6`.
- Docker's disk on this Mac filled on 2026-11-19 and stopped the dev
  database; rebuildable cache was cleared and `.dockerignore` now drops local
  APK build folders. Rebuilding `doris_public_service` (`--profile icd11`)
  still costs several GB; run `docker builder prune -f` after.
- Full-suite noise under `-n 4`: `digitva-6igh`, contact form
  (`digitva-wd09`). `tests/routes/test_bundle_ingest_api.py` fails as a
  whole when the ODK host is unreachable (`digitva-z5t4`). The export streaming failures were a leaked
  `DB_BACKUP_TMP_DIR`, fixed in `f34093911`.
- Untracked on purpose: the orientation deck files under `docs/manuscript/`,
  `.claude/launch.json`, the Play screenshots.
- Dev DB: DEMO01 has narration languages enabled (english, hindi).
- Test databases still present: `minerva_test_codeapp`, `_consent`, `_pii`, `_cadre`,
  `_tst002` (and their `_gw*`).
- `npm run vendor:build` reinstalls the vendor package: stop Metro first
  and restart it with `--clear`.
