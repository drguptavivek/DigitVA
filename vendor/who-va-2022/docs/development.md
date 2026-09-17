# Developer guide

This guide covers local development of `@drguptavivek/who-2022-va`. For application integration, start with the [README](../README.md). For exported interfaces and functions, see the [API reference](api.md).

## Prerequisites

- Node.js 24 for the contributor toolchain; `.nvmrc` pins the recommended version. The published runtime remains compatible with Node.js 18 and newer.
- pnpm 11.9.0 (the version pinned in `package.json`)
- Chromium installed through Playwright for browser end-to-end tests

```bash
corepack enable
pnpm install
pnpm exec playwright install chromium
```

The package is ESM-only. React is required by the UI entry points; React DOM, React Native, and React Native Web are optional peer dependencies so consumers install only the platforms they use.

## Run the project

```bash
pnpm dev
```

This starts the Vite demo at `http://127.0.0.1:5173`. The demo uses the same web entry point published by the package. It also runs the local PostgreSQL-backed demo server, using `localhost:5433`, user `postgres`, database `whova`, and demo password `aiims@123` by default. Override the connection with `DATABASE_URL` or `PGPASSWORD` when your local PostgreSQL uses different credentials.

Useful commands:

| Command                | Purpose                                                            |
| ---------------------- | ------------------------------------------------------------------ |
| `pnpm typecheck`       | Check TypeScript without emitting files                            |
| `pnpm test`            | Run Vitest unit, integration, tracer, and canonical-contract tests |
| `pnpm test:watch`      | Run Vitest in watch mode                                           |
| `pnpm test:e2e`        | Run Playwright against the Vite demo                               |
| `pnpm test:e2e:headed` | Run the browser suite visibly and sequentially                     |
| `pnpm test:e2e:report` | Open the latest Playwright HTML report                             |
| `pnpm build`           | Build ESM bundles, declarations, and source maps into `dist/`      |
| `pnpm build:demo`      | Produce a static demo build                                        |
| `pnpm check`           | Run lint, formatting, type checking, Vitest, and package build     |
| `pnpm check:all`       | Run `pnpm check` plus the Chromium end-to-end suite                |

`pnpm check` intentionally remains the browser-free package gate. Run `pnpm check:all` when Chromium is available; GitHub Actions runs the package gate and browser suite as separate jobs.

## Repository map

| Path                              | Responsibility                                                                      |
| --------------------------------- | ----------------------------------------------------------------------------------- |
| `src/index.ts`                    | Root, headless package entry point                                                  |
| `src/native.tsx`                  | Expo and React Native entry point                                                   |
| `src/web.tsx`                     | React web entry point and browser adapters                                          |
| `src/web-component.tsx`           | Custom-element wrapper for non-React sites                                          |
| `src/engine/`                     | Expression parsing/evaluation, calculations, validation, indexes, and session state |
| `src/ui/`                         | Shared form and reusable question-control factories                                 |
| `src/generated/`                  | Checked-in canonical instrument and question audit                                  |
| `docs/xlsform-app-audit.md`       | Group-by-group and question-by-question audit of XLSForm against app JSON           |
| `src/languages/`                  | Lazily imported built-in language files                                             |
| `src/attachments.ts`              | Platform-neutral attachment policy and processing contracts                         |
| `src/web-attachments.ts`          | IndexedDB, browser image processing, and PDF.js adapters                            |
| `src/native-attachments.ts`       | Native image-processing adapter seam                                                |
| `tests/`                          | Vitest tests, including workbook conformance checks                                 |
| `e2e/`                            | Playwright form automation                                                          |
| `examples/`                       | Minimal React web, Expo, and plain-web integrations                                 |
| `demo/`                           | Local Vite preview used by developers and Playwright                                |
| `whova2022_xls_form_for_odk.xlsx` | WHO source workbook retained only as provenance/reference documentation             |

## Source-of-truth rules

`src/generated/who-va-2022.instrument.json` is the authoritative executable instrument. It is checked in so builds are deterministic and offline. The runtime and package build must not read the workbook or import `exceljs`.

The workbook is a provenance artifact for human review only. Production code, builds, and automated tests must not parse it, import an Excel library, or regenerate the checked-in contract from it.

When changing the instrument:

1. Edit the canonical JSON deliberately and review the diff as data.
2. Keep stable question names and coded choice values unless the external data contract is intentionally changing.
3. Update `who-va-2022.question-audit.json` when the human-review matrix must change with the contract.
4. Run canonical-contract and question-by-question runtime tests.
5. Document any intentional divergence from the retained workbook.

Known deviations and gotchas are tracked in `docs/xlsform-app-audit.md`. Current intentional differences are the `nmh` runtime section path, the omitted `Id10365` constraint, the adapted `Id10382` constraint and messages, and clearer app messages for `Id10023_a`, `Id10023_b`, and `Id10382`. The current source-form constraint gotchas are `Id10260`, `Id10414`, `Id10414_a`, and `Id10414_b`: those constraints are preserved and evaluable, but their formulas refer to values outside the compiled app choice lists, so they cannot fire as constraint validation errors for valid app inputs.

## Runtime flow

The headless engine is shared by every renderer:

```text
canonical instrument -> session -> calculations/relevance -> field validation
                                      -> navigation -> submission validation
```

`createWhoVaSession()` is the stateful boundary. It owns answers, the current visible section, navigation, and subscriptions. The validation functions are also exported independently for server-side or batch use. Renderers add controls and platform adapters but do not implement separate questionnaire rules.

The root entry point exposes a synchronous `whoVa2022Instrument` for compatibility. UI entry points call `loadWhoVa2022Instrument()` so the large JSON contract is parsed only when the first default form needs it.

## Making changes

### Engine or instrument behavior

Add focused tests under `tests/`. Prefer testing public functions or a session over duplicating internal calculations. If behavior originates in the workbook, include or update a source-conformance assertion.

### Shared controls

Control behavior belongs in `src/ui/question-controls.tsx`, while shared labels, attachment messages, and presentation styles live in `src/ui/question-control-support.ts`. Form presentation helpers and styles live in `src/ui/form-presentation.tsx`. Keep questionnaire behavior outside platform-specific entry points. Verify shared behavior with Vitest and browser interaction with Playwright when relevant.

### Platform adapters

Keep native-only APIs in `src/native.tsx` or native adapter modules, and browser-only APIs in `src/web.tsx` or web adapter modules. Do not pull browser globals into the root entry point or native dependencies into the web bundle.

### Languages

Language files translate interviewer-facing text only. Question names, choice values, expressions, and stored answers remain unchanged. The public package ships only English; experimental translation fixtures in the repository must not be imported into a published entry point. See the README for the language-file shape, rights warning, and lazy-loader example.

### Attachments

Attachment handling is fail-closed. New formats or processing paths need byte-level validation, a canonical stored representation, lifecycle cleanup, and tests. Review [Attachment processing](attachments.md) before changing this boundary.

## Test strategy

The suites are intentionally layered:

- Unit tests cover dates, expressions, localization, attachments, and isolated controls.
- Tracer and integration tests cover calculations, constraints, sessions, web-component events, and runtime boundaries.
- Parameterized tests exercise every named WHO question through field and submission validation.
- `tests/exhaustive-runtime-expressions.test.ts` evaluates all 38 calculations and all 87 configured constraints, including explicit coverage for inert source-form constraints.
- Source-conformance tests compare the canonical JSON with the workbook without mutating either artifact.
- Playwright drives the rendered form, including error correction, age calculations, and navigation.

For a normal code change, run the narrowest related Vitest file while iterating, then `pnpm check`. Use `pnpm check:all` for user-visible browser or navigation changes.

## Build and package boundaries

`tsup.config.ts` emits four ESM entry points: root, native, web, and web component. React platform packages are externalized. Before publishing or consuming a local build, inspect `dist/` and confirm that:

- declarations exist for every entry point;
- the root bundle has no React, browser, React Native, Excel, or workbook dependency;
- platform-specific code remains behind its documented subpath;
- the generated instrument chunk needed at runtime is included;
- experimental translation fixtures are not included.

## Data and deployment responsibilities

This repository provides the instrument, offline interview state, validation, and client-side attachment canonicalization. A host application remains responsible for identity, encryption, access control, synchronization, retention, backups, device-loss handling, upload authorization, malware scanning, and authoritative server-side file validation.
