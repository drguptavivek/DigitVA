# Handoff — Offline PHC Desktop (`feat/offline-phc-desktop`)

## Start here

Read `AGENTS.md`, `docs/policy/offline-phc-desktop-edition.md`, and the
authoritative server contract under `docs/policy/`:

1. `docs/kb/offline-session-message-2026-10-21.md`
2. `docs/policy/offline-api-contract.md`
3. `docs/policy/offline-bundle-and-transfer.md`
4. `docs/policy/pii-envelope-format.md`

Keep all edits inside `/Users/vivekgupta/workspace/DigitVA/.claude/worktrees/offline-phc-desktop`.
Never stash. Stage explicit file paths from `git diff`.

## Ranked next steps

1. **Cross-team bundle vector conformance (`digitva-gb8w.6`)**:
   - Once the server session commits `tests/fixtures/bundles/` (canonical JSON
     cases, deterministic sample `.dvb` bundle with fixed DEK/nonces and all
     intermediates, and expected reports for tampered, replayed, expired,
     unknown-key and consent-missing variants), wire a test in
     `desktop/crates/digitva-bundle` calling `build_bundle_deterministic` to
     verify byte-for-byte reproduction.
2. **End-to-end integration against server beads (`digitva-gb8w.2`..`digitva-gb8w.8`, `digitva-athy`)**:
   - Verify live station onboarding (`signing_public_key` registration and
     custodian verification), importing a server-issued two-line signed
     `.station-config` (`GET /api/v1/intake/station-config` or browser export),
     exporting a `.dvb` bundle from `digitva-server`, validating/ingesting via
     `POST /api/v1/intake/bundles/validate` and `POST /api/v1/intake/bundles`,
     and importing the returned two-line `.dvb.receipt` (including `purge`
     execution).
3. **Desktop Tauri packaging & OS keystore integration (`digitva-ke83`)**:
   - Wire `desktop/src-tauri` to bundle the static Expo web export
     (`mobile/digitva-collect/dist`) and bind the 256-bit installation secret to
     macOS Keychain / Windows Credential Manager alongside the user's 6-16 digit
     PIN for SQLCipher (`bundled-sqlcipher`) key derivation.
4. **Repository / branch settlement (owner decision)**:
   - Settle whether `feat/offline-phc-desktop` merges into `main` as part of the
     monorepo (`desktop/` + shared `mobile/digitva-collect/`) once the server
     `digitva-gb8w.*` slice lands, or moves to a dedicated repository/worktree.

## Open owner decisions

- **Repo layout for Offline PHC Desktop**: Keep in the `DigitVA` monorepo
  (`desktop/` workspace + shared `mobile/digitva-collect` UI and shared
  `tests/fixtures/` vectors) vs. split into a standalone repository.
- **Narrative `Id10476` in SmartVA input** (Contract 6.6 open check): `Id10476`
  is not in `PII_FIELDS_FLOOR` and is visible to coders; confirm whether any
  project flags `Id10476` in `projects[].sealed_field_ids`.

## Approved work not started

- Cross-check against `tests/fixtures/bundles/` once server bead
  `digitva-gb8w.6` lands on `main`.
- Native macOS `.dmg` and Windows `.msi`/`.exe` installer builds via
  `cargo tauri build`.

## Caveats and invariants still true

- **Epic `digitva-ke83` (`digitva-ke83.1`..`.6`) is complete and closed** in the
  worktree:
  - `digitva-pii` (5/5 Rust tests + 5/5 `scripts/check_pii_blob.py` two-way
    vectors against `tests/fixtures/pii_envelope_vectors.json`).
  - `digitva-bundle` (6/6 tests: Ed25519 station signing, 2-line station config
    verification, `.dvb` sealing, receipt verification + `purge` planning).
  - `digitva-text` (13/13 tests: 19-field `PII_FIELDS_FLOOR`, `Id10073`
    reduction, phone prefix stripping, anchored regex with `rule.example`,
    RFC 8785 JCS + NFC).
  - `digitva-smartva` (1/1 unit + 8,273/8,273 `corpus_parity`).
  - `digitva-db` & `digitva-server` (7/7 tests: SQLCipher PIN lock & 5-attempt
    wipe, canonical roles `death_reporter` / `interviewer` /
    `station_supervisor` / `coder`, supervisor correction guards `409
    case_completed` and `409 case_closed`, sorted `identifiers` list,
    unwatermarked MCCD PDF, per-launch 256-bit bearer token, `Host`/`Origin`
    checks, `Cache-Control: no-store`, zero CORS headers).
  - `mobile/digitva-collect` (`106` Jest suites, `1,614` tests passing; reuses
    central `DeathRegistrationScreen.tsx`, `PhoneInput.tsx`, `phoneFormat.ts`,
    `IdentifierFields.tsx`, `CaseIdentifiers.tsx`, `identifiers.ts`).
- **Unprovisioned standalone mode (`project_id = "1"`) is a sandbox**: never
  ingestable, never remapped, and `.dvb` bundle export is refused (`403
  sandbox_not_exportable`).
- **Local demo server**:
  - Export web bundle: `npx expo export -p web` in `mobile/digitva-collect`.
  - Run server: `OPENSSL_DIR=/opt/homebrew/opt/openssl@3 cargo run -p digitva-server`
    in `desktop/` (binds `127.0.0.1:18420`, redirects `/` to `/app/`, injects
    `window.__DIGITVA_LAUNCH_TOKEN__` in memory into `index.html`, and serves
    `/static/*` from `app/static`).
