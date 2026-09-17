# Agent Guide: Expo Mobile App

This file applies to the complete Expo demo app in `examples/expo-demo/`.

## Project Shape

- This is a host-app shaped Expo Router demo for the WHO VA package.
- It depends on the workspace package via `@drguptavivek/who-2022-va: workspace:*`.
- The app demonstrates mobile interview lifecycle screens: home, case entry, dashboard, start, continue, drafts, and completed submissions.
- The WHO VA package owns rendering, questionnaire state, validation, relevance, calculations, and draft envelopes. This app owns routing, local persistence, user/case workflow, platform services, and server sync.

## Important Paths

- `app/`: Expo Router screens.
- `app/_layout.tsx`: route stack setup.
- `app/index.tsx`: home entry.
- `app/case-entry.tsx`: case/death record collection before the WHO VA form.
- `app/dashboard.tsx`: case workflow dashboard.
- `app/start.tsx`, `app/continue.tsx`, `app/drafts.tsx`, `app/completed.tsx`: interview lifecycle routes.
- `components/`: local storage, platform adapters, dashboard UI, sync, and app helpers.
- `components/ServerSync.ts`: pushes local completed data to the demo server.
- `android/` and generated native folders: Expo prebuild output. Avoid hand edits unless the native project is intentionally being changed.
- `dist-web/` and `dist/`: generated build output.

## Commands

Run mobile commands from `examples/expo-demo/`.

```sh
npm start
npm run android
npm run ios
npm run web
npm run build:web
npm run build:android:apk
npm run build:ios:simulator
```

- The `prestart`, `preandroid`, `preweb`, and related scripts build the root package first.
- Android/iOS build commands may require local SDKs, emulators, CocoaPods, or platform-specific shell support.
- For package-level validation after mobile changes, run relevant root checks from `../..`, usually `pnpm typecheck`, `pnpm test`, or `pnpm check`.

## Mobile App Rules

- Keep host-only workflow state out of canonical WHO answer data. Use case records, draft IDs, local database fields, or sync envelopes instead.
- Preserve offline-first behavior: local case entries, drafts, and completed submissions should work before server sync.
- Completed submissions should only sync valid interviews for the current registered user, and failures should not delete local data.
- Use package exports from `@drguptavivek/who-2022-va/native` for the form and native-specific helpers.
- Platform services such as date picking, camera/image selection, file picking, audio, persistence, and upload belong in the host app adapters.
- Do not copy browser-only helpers such as `createInsecureWhoVaBrowserDefaults()` into the mobile app.
- Treat attachment files as app-controlled data. Persist processed image outputs durably before storing references, and keep server validation authoritative.

## Style

- Follow the existing Expo Router screen patterns and colocated component helpers.
- Keep screens workflow-focused and avoid moving questionnaire logic out of the shared package.
- Do not hand-edit generated native build artifacts unless the change is specifically about native project configuration.
- Keep generated outputs such as `dist-web/`, `dist/`, and native build products out of source changes unless the user explicitly asks for artifacts.
