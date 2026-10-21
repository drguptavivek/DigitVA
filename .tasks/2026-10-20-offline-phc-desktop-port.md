# Task: Offline PHC Desktop Port (`digitva-ke83`)

- **Status**: completed
- **Priority**: P1
- **Created**: 2026-10-20
- **Completed**: 2026-10-21
- **Goal**: Build the offline PHC station edition of DigitVA ("DigitVA Field / PHC Edition") in pure Rust and compiled TypeScript/React Native (`digitva-pii`, `digitva-bundle`, `digitva-text`, `digitva-smartva`, `digitva-icd11` + `vendor/who-icd11-api`, `digitva-pdf`, `digitva-db`, `digitva-server`, and `mobile/digitva-collect`), aligned to the finalised 2026-10-21 Offline API Contract v1 (`offline-api/1`, commits `a91fc7cc8` / `8af8d0710`).
- **References**:
  - `docs/from-server/2026-10-21/kb/offline-session-message-2026-10-21.md`
  - `docs/from-server/2026-10-21/policy/offline-api-contract.md`
  - `docs/from-server/2026-10-21/policy/offline-bundle-and-transfer.md`
  - `docs/from-server/2026-10-21/policy/pii-envelope-format.md`
  - `docs/policy/offline-phc-desktop-edition.md`
- **Completed Scope**:
  - **Phase 1 (`digitva-ke83.1`)**: Pure-Rust in-memory SmartVA runner (`desktop/crates/digitva-smartva`, 8,273/8,273 corpus parity) and unwatermarked WHO Standard MCCD A4 PDF generator (`desktop/crates/digitva-pdf`).
  - **Phase 2 (`digitva-ke83.2`)**: Offline WHO ICD-11 2.6.0 / DORIS pure-Rust engine (`vendor/who-icd11-api` & `desktop/crates/digitva-icd11`).
  - **Phase 3 (`digitva-ke83.3`)**: SQLCipher (`bundled-sqlcipher`) local store with HKDF-SHA256 per-user PIN key derivation, auto-lock, and 5-attempt store wipe; station roster (`death_reporter`, `interviewer`, `station_supervisor`, `coder`) & custodian onboarding; registration-time DPDP consent gate; anchored identifier validation & phone normalisation; supervisor correction rules (`death_correction` before interview completion, `identifiers_set` before/after, closed cases refused); and FTS5 reference catalogs (`desktop/crates/digitva-db`, `desktop/crates/digitva-text`).
  - **Phase 4 (`digitva-ke83.4`)**: Loopback-only Rust Axum `/api/v1/*` server (`desktop/crates/digitva-server`) with per-launch 256-bit bearer token, `Host`/`Origin` validation, `Cache-Control: no-store`, zero CORS headers, and frontend alignment in `mobile/digitva-collect` (`consent.ts`, `identifiers.ts`, `roster.ts`, `StationRosterScreen.tsx`, `DeathRegistrationScreen.tsx`, `SettingsScreen.tsx`).
  - **Phase 5 (`digitva-ke83.5`)**: Dropped per server contract 2026-10-21 (central server bundle ingest is owned by server bead `digitva-gb8w.2`).
  - **Phase 6 (`digitva-ke83.6`)**: Hybrid `ML-KEM-768 + X25519` PII envelope crate (`desktop/crates/digitva-pii`, passing all 48 committed vectors + `check_pii_blob.py` both ways) and `.dvb` bundle writer / receipt & station-config verifier crate (`desktop/crates/digitva-bundle`).
