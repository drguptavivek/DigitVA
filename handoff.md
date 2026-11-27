# Handoff

Start prompt: "You are the DigitVA COORDINATOR. Read CLAUDE.md, this
handoff and `bd prime`. You alone land on main, run full suites, build and
deploy; every landing needs the INDEPENDENT CODE REVIEWER's land. Start with
ranked step 1."

## Start here

Staging runs `c7b1ac797` (deployed 2026-11-27, owner go; migrations at
`a40477e55b72`; rollback, the one new column is nullable:
`sudo -Hu ubuntu env SKIP_BACKUP=1 bash scripts/deploy-server.sh eeb8e48158dc3073013d9580237e22fdcced6ff6`;
snapshots and pg_dump in `CHANGELOG.md` 2026-11-27). The demo stack runs
`eeb8e4815` (`digitva-demo-app:eeb8e4815`, env backup
`/data/digitva-demo.env.pre-eeb8e4815`). The image carries 0.3.33
(`android-v0.3.33`, `collect-plus-v0.3.33-plus.1`, web
`expo-web-v2026.11.27.3`; 0.3.32 never pinned), and phones are offered
0.3.33 since 2026-11-27 (owner go; 0.3.31 kept in `private/android-hosted`). Play AAB 0.3.33 is run
46014411448 (expires about 2026-12-11). No device check of 0.3.31 or 0.3.33.

Owner decisions waiting:
- Each its own go: upgrade the demo, upload the Play AAB, deploy the ICD-11 client tokens (landed
  `f09e6ec6f`) and issue the first token.
- Homepage KPIs: the owner ticks "Included in homepage KPIs" for ICMR01,
  UNSW01, KEM001, TELE01 (only HMR001 counts now).
- Redis outage 500s every request via the IP-ban check (`digitva-248z`):
  fail open or closed.
- Rerun training setup on staging (`digitva-veq5`); until then a reviewer
  trainee at a sub-centre may get `grant_not_allowed`.
- Signed-in staging pages are unchecked since the deploys (queues with the
  Sort and filter panel, training, ICD search, System health, `digitva-b94q`,
  `digitva-31ac`, org-unit pickers, `digitva-3ko3`): owner sign-in.
- Consent withdrawal: erasure of a withdrawn case is not built (`digitva-4gu7`).
- Final COD refusals: reviewer gets 403/400 `wrong_state` where the coder
  gets 409 (`r8nh.2`, needs an old-APK check). Refactor findings kept as is:
  `r8nh.30`, `r8nh.31`, `r8nh.32`; DM API bugs `.37`, `.38`.
- Owner items: DORIS production ingress (`ddv.2`), engine v0.1.0 (`xw1s`),
  Play listing (`91f2`), translations (`fb5`), manuscript (`3kpb`), legal
  review (`gyfj`), engine pin on CI (`9cll.10`), rotated staging passwords
  (`jb4t`), WHO technical note (a WHO contact email), `kkdb` step 2, `wawz`
  start, engine provenance and InterVA/InSilicoVA (no go yet), AI
  interview-quality checks (`digitva-qtmq`, on hold), Hindi string review.
- The 24 pre-deploy EBS snapshots (tags `release=0.3.30`, `cb5c903c1`,
  `634711950`, `5a3f994b3`, `eeb8e4815`, `c7b1ac797`) never expire; delete
  when no longer needed.

## Ranked next steps

1. ICD-11 client tokens landed on main (`f09e6ec6f`, migration
   `a4d7e2c9b1f6`); staging deploy and the first live token each need the
   owner's go. Follow-up `digitva-zcmg`.
2. `digitva-329t` landed (`c7cd883bb`) and ships in the next APK; its
   device check is `digitva-wlfr`.
3. Device-check 0.3.33 (now offered on staging): Local cases
   row (`5cqm`), phone cards (`2b7d`), Sort and filter sheet and Recodeable
   (`znbm`), Reported deaths chips and Refused badge (`aunm`), tab-return
   (`1xof`), offline Social Autopsy, re-enrol from Sign in again (`dbcw`),
   DORIS death dates, case summary, Reset DORIS, COD form PDF, org-unit
   lineage pickers, supervisor death edit fields (`hftq`). Older phone
   checks: `9m8o`, `9cll.5`, `9cll.22`, `tk7j`, `e2ju`.
4. Bulk invitations (`digitva-povs`): owner gets the mail host's SMTP limits
   and relay logs for 21 and 23 Nov; 86 staging users from 21 Nov need a
   resend if wanted ("gave up" in celery_tasks.log / errors.log).
5. Supervisor corrections (`digitva-hftq`): owner look at the fixed screens
   (private/screenshots/supervisor-phone-2026-11-24); Maestro flow caps
   (`digitva-flkc`); dev DB `minerva_test_sup` kept.
6. Training (`digitva-9qer`, `digitva-q3iu`): owner supplies
   `app/services/training_corpus/english_v1.txt`; flows 96-98 need a trainee
   setup role; refuse outdated apps (N11); hide DEMO01 in graduation.
7. Server picker page: retire after the APK rollout, not before 2027-01-20
   (`digitva-dxg1`). Users filter unit paths (`digitva-p6fs.36`). Phone SA
   panel (`digitva-088j`), native mentor view (`digitva-3vj8`).
8. P1 beads with owner action left: `yacr`, `ddfx`, `77ti`, `zkgx`; partly
   done `yeg3.1`, `9cll.22.3`, `r9lk`, `xjpk`, `xk41`, `rpqp`.
9. Refactor epic `digitva-r8nh`: next slice of each started bead is in its
   notes; not started `.6`, `.7`, `.10`, `.18`, `.19`, `.21`, `.27`-`.29`
   (ask the owner first). Protocol: bd memory
   `refactor-behaviour-preservation`; one writer at a time on
   `app/__init__.py`.
10. Collect: TalkBack (`eizq`), Play screenshots (`fthd`), SM-E146B speed
    (`xxfz`). Offline PHC station (`xt9y`). Help chatbot (`wawz`, CPU or
    edge model only). Backend performance `f41g`: owner "dont fix for now".
11. Queue search has no index yet (reviewer note on `digitva-wqz7`).

## Boundaries still true

- Only the COORDINATOR session commits to main, pushes, runs the full
  suite, builds and deploys (bd memory `coordinator-owns-landing`); every
  landing has the INDEPENDENT CODE REVIEWER's land
  (`reviewer-reviews-everything`); owner questions about a session's work
  come from that session (`owner-questions-from-sessions`).
- Staging deploys only via `scripts/deploy-staging.sh <full sha>` on the
  owner's go. Release builds only on CI.
- Coding works the same on web, Collect and Collect Plus (bd memory
  `coding-parity-all-surfaces`); Collect screens are frozen
  (`docs/design/collect-petrol-theme/README.md`); no WebView screens.
- Golden corpora are owner-approved and frozen. Required ICD-11
  postcoordination is a picker rule (icd11-code-selection-principles.md §4).
- Never re-run the ICD-10 CSV or policy import on staging: it re-enables the
  withdrawn R00-R94 codes (`1f037b4717e4`).
- On the owner's real phone: no PINs, passwords or system settings. Plus
  stays prerelease. No Fable agents.

## Caveats

- Flaky under `-n 4`: `digitva-6igh`, `9czl`, `wd09`; `digitva-jajs` fails
  before 13:00 UTC; `test_bundle_ingest_api.py` fails when the ODK host is
  unreachable (`digitva-z5t4`).
- Expo worktrees need `npm ci` (or linked `node_modules`) and the WHO
  `vendor/who-va-2022/dist` before Jest or check-web. `npm run vendor:build`
  needs Metro stopped and restarted with `--clear`.
- On staging use `docker exec minerva_app ...`; `docker compose exec` there
  needs the deploy's env files.
- Rebuilding `doris_public_service` costs several GB; run
  `docker builder prune -f` after.
- Untracked on purpose: `docs/manuscript/` deck files, `.claude/launch.json`,
  Play screenshots. Dev DB: DEMO01 has English and Hindi narration.
- Test DBs: `minerva_test_codeapp`, `_consent`, `_pii`, `_cadre`, `_tst002`,
  `_sup` (and their `_gw*`).
