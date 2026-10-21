# Handoff

## Start here

Read `AGENTS.md`, `docs/current-state/README.md`, then the policy for the piece
you take: `docs/policy/pii-encryption-at-rest.md` (+ `docs/kb/pii-slice-1a.md`,
`pii-slice-1b.md`), `docs/policy/offline-api-contract.md`,
`docs/policy/offline-bundle-and-transfer.md`,
`docs/policy/death-registration-identifiers.md`,
`docs/policy/respondent-consent-notice-draft.md`. Stage explicit paths
(`grep -Ev` filters, check the staged list), never stash (not even
`--autostash`), one full parallel run (`-n 4`) on a database of your own, one
test database per concurrent agent. The owner decides commit timing. The
offline PHC app is a separate agent in worktree `feat/offline-phc-desktop`
(bead `digitva-ke83`); the owner relays messages. The owner owns
`vendor/who-va-2022`. Owners may edit accounts and translations: reread live
state. Staging Hindi 40 in_review is the owner's live state: never overwrite
(the 36 saved edits already matched live; no restore needed).

## State (2026-10-21)

Staging runs `1bfdb8fdb` (supervision tab + shared case list), healthy; its Expo
export was built on the host (no Node there: node:22 container, vendor package
built first, see `bd memories staging-expo-export-build`). The commit after it
adds, with `PAYLOAD_PII_SPLIT_ENABLED` OFF everywhere: identifiers epic (stages
1-5), cryptography 50.0.2 + google-re2, PII stage 0, slice 1a, slice 1b parts I
and II-A, the offline specs. Two new migrations, `c7e3a9d1f5b2` (identifiers)
and `d4f1b8c2a6e9` (payload PII side table); single head `d4f1b8c2a6e9`. Last
full run: pytest -n 4 4725 passed, 2 failed (one fixed in the commit; one
parallel-only worker crash in `test_migrate_who_2026_annex`, passes alone),
jest 105 suites / 1598 tests, tsc clean.

## Ranked next steps

1. Deploy to staging when the owner says. In order: PII keys at
   `/data/digitva-secrets/` (`make ensure-secrets-prod` refuses a key inside the
   checkout on purpose, see `split-production-deploy.md`), beat limit 384m (done
   in compose, check staging free memory), image rebuild (cryptography,
   google-re2), Expo export, both migrations, verified dump. Then the ONE
   controlled Aadhaar sweep `digitva-ddfx`: `flask pii sweep-national-id
   --apply --confirm-backup <dump>`; mask every non-empty `Id10073`; dry-run first.
2. PII part II-B readers, then flip the flag (`digitva-kzyp` family): case
   content, `va_case.py`, `va_form.py`, coding, visit note, ODK identity, DORIS
   prefill, exports, upstream accept (list, release procedure and rollback in
   `docs/kb/pii-slice-1b.md`). Then the client stage (vendor form engine + Expo
   reduce `Id10073` at capture, hash the reduced text), then slice 2 (register
   columns encrypted; phones shown/callable; exact blind index only). Never-sealed
   list (`Id10023`, sex, age fields) is in `pii_field_registry.py`.
3. Offline server side, epic `digitva-gb8w` (.2-.8): bundle ingest
   `POST /api/v1/intake/bundles`, consent tables + `GET /intake/consent-config`
   + `consent` on submissions and registration (`digitva-athy`), signed station
   config (purge list, roster, custodian), device signing key enrolment,
   station_supervisor authorization path (needs a server interview_supervisor
   grant), vectors under `tests/fixtures/bundles/`, tests. The offline team builds
   to `offline-api-contract.md`.
4. `digitva-9ffj`: stop using ODK `unique_id` / `unique_id2` / `instanceName`
   (name fragments possible); `va_sid` already uses the stable `__id`. Policy
   baseline first. `digitva-fx2c`: research export (district, rural/urban, month
   and year of death, age group, GPS jitter 2 km fixed per case, nothing identifying).
5. Case list `digitva-pt0s`: Expo `CaseListScreen` on `GET /api/v1/cases`; counts
   are a seq scan (~250 ms at 200k rows with JIT off; no index helps).
6. Older: `digitva-p6fs.5` physical auth acceptance, `digitva-jkvl` offline
   attachments, `digitva-gyt9` sync chip, translation review (owner),
   `digitva-xzdm`, vendor lockfile out of sync + Dockerfile Expo step (bead filed).

## Open owner decisions

- Retention of pre-split database dumps and SmartVA run archives (they hold full
  national IDs; ODK Central does too). Legal review: Aadhaar Data Vault rule,
  DPDP scope (deceased data, research exemption, sharing abroad).
- SmartVA run scrub: a DB dump does not prove run files were archived; archive
  them first (assumed acceptable, confirm).
- Seal `Id10021` exact date of birth? Keep `Id10022` + derived age flags on the
  never-sealed list (judgement call)? Check each XLSForm `unique_id` /
  `instance_name` calculation.

## Decisions already made (do not reopen)

Supervision only in the Deaths tab; admin is a PII holder, no scope bypass;
Aadhaar last 3 digits only, no hash or index, devices reduce at capture; no
partial phone digits anywhere; phones encrypted but shown and callable; per-record
data keys; key custody simple (app-host files outside the repo, never on the DB
host or in beat/DORIS); consent at registration (web, Expo, station), interview
reuses it, withdrawal web-only; the offline app has a local server but no
central-server duties; offline-coded MCCD PDF not watermarked; station
supervisor corrections accepted with the user id in the audit log (identifiers
only after the interview, closed cases need the web); date of death stays
readable for staff, research release keeps month and year only.

## Caveats

`app/static/expo-client/` is a stale untracked export and `resource/smartva-phmrc-dataset/`
(49 MB) is untracked and not part of this work. Dev: testadmin has extra grants on
ICMR01/HP2026/GUJ026; dev `.env` holds throwaway PII keys under `private/`. Beat
sits near its old memory limit until the new one is deployed. The offline worktree
holds a read-only copy of the specs in `docs/from-server/2026-10-21/`; refresh it
after the commit. Deployment details: `runtime-and-operations.md`,
`split-production-deploy.md`.
