# Agent Guide: Web Package

This file applies to the root package, `src/`, `demo/`, `tests/`, `e2e/`, `docs/`, and general repository work. The Expo mobile app has its own guide at `examples/expo-demo/AGENTS.md`.

## Project Shape

- This repo is the `@drguptavivek/who-2022-va` TypeScript package for the 2022 WHO Verbal Autopsy instrument.
- The checked-in JSON contract at `src/generated/who-va-2022.instrument.json` is the executable source of truth. The workbook `whova2022_xls_form_for_odk.xlsx` is retained only for human provenance review.
- Runtime behavior is shared across headless, web, web-component, and native entry points. Keep questionnaire rules in shared engine/session/validation code rather than platform adapters.
- The root web demo lives in `demo/` and exercises the published web entry points through Vite and the local server.

## Important Paths

- `src/index.ts`: root package entry for headless/server consumers.
- `src/web.tsx`: React web entry point and browser adapters.
- `src/web-component.tsx`: custom element wrapper for non-React sites.
- `src/native.tsx`: React Native entry point.
- `src/engine/`: expression, session, validation, and navigation logic.
- `src/ui/`: shared form presentation and question controls.
- `src/web-attachments.ts` and `src/web-audio.ts`: browser attachment/audio handling.
- `demo/`: Vite browser demo and local database-backed demo server.
- `tests/`: Vitest coverage for runtime, contract, controls, and integration behavior.
- `e2e/`: Playwright browser automation.
- `docs/`: public API, architecture, examples, workflow, and development notes.

## Commands

Use `pnpm` from the repo root.

```sh
pnpm dev
pnpm dev:vite
pnpm db:migrate
pnpm test
pnpm test:e2e
pnpm lint
pnpm format:check
pnpm typecheck
pnpm build
pnpm check
pnpm check:all
```

- `pnpm dev` starts the local demo server at `http://127.0.0.1:5173`.
- Use focused Vitest files while iterating, then run `pnpm check` for ordinary code changes.
- Run `pnpm check:all` for user-visible browser flow, navigation, persistence, or attachment changes.

## Development Rules

- Do not parse, import from, or regenerate runtime code from the XLSX workbook in production code, tests, or builds.
- Treat `src/generated/who-va-2022.instrument.json` as checked-in contract data. Changes to it need clear provenance and focused conformance/runtime tests.
- Keep root imports platform-neutral. Do not introduce browser globals into the root entry point or native-only dependencies into web bundles.
- Prefer public API/session tests over duplicating internal calculations. If a behavior comes from the WHO source contract, include or update conformance coverage.
- Web and native forms are in-memory unless the host injects stores and platform services. Demo-only helpers such as `createInsecureWhoVaBrowserDefaults()` should not be presented as production defaults.
- Attachment handling is fail-closed. New formats or processing paths need byte validation, canonical storage representation, lifecycle cleanup, and tests.

## Style

- Follow the existing TypeScript and React patterns; keep platform-specific adapters thin.
- Preserve stable WHO question names and coded values. Host-only identifiers belong in host envelopes, draft IDs, or server payload metadata, not in canonical WHO answer data.
- Use ASCII in new files unless the surrounding file already requires Unicode.
- Keep docs practical and update `README.md`/`docs/` when public behavior, commands, or integration guidance changes.
