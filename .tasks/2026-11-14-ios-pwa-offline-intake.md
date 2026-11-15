# iOS PWA offline interview intake (plan only)

- Status: proposed, awaiting owner decision
- Priority: medium (training sessions first)
- Created: 2026-11-14
- Bead: none yet (file one when the owner picks an option)

## Goal

Decide whether the Expo web export of DigitVA Collect can become an installable
PWA on iOS Safari so an interviewer records interviews with no network and syncs
when online. First use: training sessions where iOS users must use the web.

## Short answer

Technically possible; not small, and it reverses a written policy. The browser
client is online-only by design and stores no answers in the browser. Going
offline means building a second offline store (IndexedDB + WebCrypto) beside
the native SQLCipher one, plus an offline auth model for the web. iOS can
evict that store. Recommendation: **not a full offline PWA now**. For training,
use the online web app on venue Wi-Fi or a hotspot (Phase 0). If offline iOS is
still needed, build a narrow **offline queue for training-project interviews
only** (Option B) with dummy/training data first.

## What exists today (cited)

Web (online):
- Policy: the browser client is "an online client ... it does not persist
  questionnaire answers, identifiers or attachments in browser storage"
  (`docs/policy/expo-client.md:33-38`); "Caching public assets does not make the
  browser interview offline" (`docs/policy/expo-client.md:66-67`).
- WHO drafts go to the server: `ServerDraftStore` "never uses localStorage or
  IndexedDB" (`mobile/digitva-collect/src/client/serverDraftStore.ts:63-64`).
  The web interview autosaves ~600 ms after a change and pauses autosave when the
  cookie session dies (`mobile/digitva-collect/src/web/InterviewScreen.tsx:317-322`,
  `:1027`); sign-out waits for the pending save (`InterviewScreen.tsx:774-776`).
- `activateBrowserDraft` is not an interview store: it is per-tab COD recovery
  in sessionStorage for coders (`mobile/digitva-collect/src/workspace/doris/browserDraft.ts:1`,
  `:100`; called from `src/workspace/CaseWorkspaceScreen.tsx:231`), the policy
  exception in `docs/policy/expo-client.md:40-43`.
- A service worker already exists: anonymous, release-keyed public asset cache
  (`scripts/expo-web-cache/worker.js:32`, `scripts/expo-web-cache/register.js`),
  coordinated by `mobile/digitva-collect/src/web/interviewAssetCache.ts:1-5`,
  which never sees accounts, form definitions or answers. API, auth, forms and
  attachments are excluded (`docs/policy/expo-client.md:45-49`).
- One encrypted browser store already exists: the attachment buffer, AES-GCM
  with a non-extractable key in IndexedDB (`app/static/js/intake/attachment_buffer.js:4`,
  `:101-102`, `:122`), wiped on sign-out
  (`mobile/digitva-collect/src/web/attachmentBufferSession.ts:1-31`). This is
  the pattern an offline web draft store would extend.
- Small prefs already use localStorage (`src/preferences.ts:24`,
  `src/uiPackStore.ts:10`, `src/interviewerRecall.ts:74`).
- `app.json` web block is `"output": "single"` with only a favicon
  (`mobile/digitva-collect/app.json:104-108`): no web manifest, no
  apple-touch-icon, not installable as configured.

Native (offline):
- One SQLCipher file per interviewer (`mobile/digitva-collect/src/interviewerDb.ts:4`,
  `app.json:42` `useSQLCipher`); drafts schema and project-store guards in
  `src/drafts.ts:119`, `:237`.
- Sync order and idempotency: deaths (`client_death_id`), contact attempts,
  submissions (`client_draft_id`), access refresh, draft sync, outstanding
  report, case download; unsent work is never purged
  (`mobile/digitva-collect/src/sync.ts:1-20`); entry points `uploadQueuedWork`
  `src/sync.ts:415`, `syncInterviewer` `src/sync.ts:817`, reference/form caching
  `src/sync.ts:1359`, `:1554`.
- Native-only boundary: native routes reach `app/` only through
  `src/nativeRouteScreens.{base,native,web}.tsx`; the test fails if any web route
  reaches expo-sqlite or the native stores
  (`mobile/digitva-collect/__tests__/web-bundle-boundary.test.ts:6`, `:27`, `:53`).
  So `src/sync.ts`/`src/drafts.ts` cannot be reused on web as-is: they take a
  SQLite `Db`.
- Auth: native uses bearer device sessions on `/api/v1/` only
  (`docs/policy/expo-client.md:77-81`); web uses the Flask cookie session + CSRF.

## What offline web needs

1. **Installability:** web manifest, icons, `display: standalone`,
   apple-touch-icon, served from the app origin; extend the existing worker
   rather than adding a second.
2. **App shell offline:** worker serves cached `/app/` HTML for navigations when
   offline. Today HTML revalidates (`expo-client.md:46-47`); that rule changes.
   The WHO runtime group must be fully cached before going offline (today warmed
   only on 4G, `expo-client.md:59-65`) — add an explicit "Prepare for offline"
   download with a done/not-done check.
3. **Form definitions / reference data:** today private config never enters the
   cache (`expo-client.md:47-48`). Offline needs authorised form definitions,
   translations, sites, identifier types and assigned cases stored per user —
   in the encrypted IndexedDB store, not the anonymous asset cache.
4. **Draft store:** an IndexedDB `WhoVaDraftStore` implementation beside
   `ServerDraftStore`, encrypted like the attachment buffer; outbox of completed
   interviews and registered deaths with the same client ids as native.
5. **Encryption at rest:** WebCrypto AES-GCM, non-extractable key in IndexedDB
   (existing pattern). Honest limit: this protects against casual reads of
   exported files, not against anyone who can run script in the origin or an
   unlocked phone; the key sits next to the data. Wrapping the key with a
   PIN-derived key (PBKDF2) gives a PIN-lock equivalent; that is the minimum
   for real PII. iOS device encryption covers a locked phone.
6. **Media:** reuse the attachment buffer; offline audio/images count toward
   the same quota. Cap per-draft size offline lower than the 50 MB server cap.
7. **GPS and camera:** `navigator.geolocation` and `<input capture>` /
   `getUserMedia` work without network but need permission prompts; verify in
   standalone mode on the iOS versions in use. Offline GPS is satellite-only
   and slow; keep "skip with reason" (`docs/policy/native-location-capture.md`).
8. **Sync:** on open and on `online` events while foregrounded, via
   cookie session + CSRF, reusing the server's idempotent endpoints
   (`/deaths`, `/submissions`, `/drafts/sync`) so the server sees nothing new.

## iOS limits (verified 2026-11-14; re-check on the target iOS version)

- WebKit storage policy (Safari 17 / iOS 17): home-screen web apps get origin
  quotas based on disk size; `persist()` is granted by heuristics, including
  being opened as a home-screen app; at quota, data can be evicted
  ([WebKit: Updates to Storage Policy](https://webkit.org/?p=14403),
  [MDN quotas](https://developer.mozilla.org/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria)).
- The 7-day script-writable storage deletion applies to Safari tabs without
  user interaction; home-screen apps have their own usage counter. Not
  confirmed from Apple whether a home-screen app unused for 7+ days is safe —
  **test on a device**.
- `persist()` returning false has been reported
  ([WebKit bug 271401](https://bugs.webkit.org/show_bug.cgi?id=271401)); the
  app must treat storage as evictable regardless.
- Each home-screen install has storage separate from Safari: a user who opens
  the site in Safari instead of the icon sees none of the offline work.
  Deleting the icon deletes the data.
- No Background Sync / periodic sync on iOS (to be confirmed against current
  WebKit feature status): sync runs only with the app open.
- Web Push exists only for home-screen apps (iOS 16.4+); not needed here.

## Auth offline

- Cookie session expiry and idle sign-out (`expo-client.md` "Idle sign-out",
  `digitva-kc89`) would sign the interviewer out mid-field. Offline mode needs:
  a local unlock (PIN wrapping the data key) that works without the server, and
  re-authentication when back online before upload; uploads use the cookie
  session, never a stored password.
- No web device enrolment exists. Option: a "web device" enrolment that mints a
  bearer token kept in the encrypted store — larger, touches auth; avoid in B.
- Sign-out with unsent work: block or warn as native does; today sign-out wipes
  the attachment buffer after a warning (`attachmentBufferSession.ts:1-5`) —
  that must not silently wipe unsent interviews.
- A different user signing in on the same install: separate stores per user id;
  never mix.

## Policy constraints

- Reverses `docs/policy/expo-client.md:33-38` and `:45-49`; needs an owner
  baseline in `docs/policy` (and `docs/policy/field-data-collection.md` browser
  path) before code.
- PII minimisation: store only what the outbox needs; purge on server ack (as
  native, `src/sync.ts:18`).
- Consent captured offline (`docs/policy/web-intake.md:245`) must be stored with
  the interview and sent with the same shape the server already accepts.
- Backward compatibility: reuse existing endpoints and bodies; no server
  contract change means old APKs are unaffected.

## Options

- **A. Full offline PWA** (case worklist, registration, drafts, attachments,
  coding off): parity with Collect. Months; second offline stack to maintain.
- **B. Offline queue for new interviews only, training project only**
  (recommended if offline is required): assigned-form definitions cached on
  "Prepare for offline", new interviews and attachments in encrypted IndexedDB,
  PIN unlock, sync on open. No case download, no revisions, no coding.
- **C. Not now**: training on Wi-Fi/hotspot with the online web app; iOS field
  use waits for an iOS native build (TestFlight is already pending in
  `handoff.md`).

Recommendation: **C now, B only if training venues truly lack connectivity**,
and A not at all while the iOS native app is possible (it reuses the SQLCipher
path for free).

## Phases (for B)

0. Owner decision + policy baseline; measure on an iPhone: install, quota,
   7-day idle survival, `persist()`, camera/GPS/audio in standalone mode.
1. Manifest + offline app shell + explicit prepare-for-offline download.
2. Encrypted IndexedDB draft store and outbox (`WhoVaDraftStore` impl), PIN
   key wrap, per-user isolation, unsent-work guards on sign-out.
3. Sync on open/online through existing idempotent endpoints; show "N not sent"
   prominently; storage estimate warning.
4. Training-only rollout on staging; then decide on real projects.

## Tests

- Jest: IndexedDB store (fake-indexeddb), key wrap, outbox idempotency,
  sign-out guard, per-user isolation; keep `web-bundle-boundary.test.ts` green.
- `make check-web` for every change; extend `scripts/tests/expo-web-cache.test.mjs`
  for offline navigation.
- Playwright (WebKit engine, offline context): install-free flow —
  prepare, go offline, record, reload, come online, verify server row once.
  Real iPhone checks for eviction and permissions (Playwright WebKit is not iOS).

## Risks

- **Data loss on eviction or icon deletion** (main risk): mitigate with sync
  every time online, persistent "not sent" counter, storage warnings, training
  data only until proven.
- Users opening Safari instead of the icon see an empty store.
- Weak at-rest protection relative to SQLCipher; key next to data without PIN.
- Two offline stacks drift from native semantics (consent, death registration).
- Larger cached bundle on low-storage phones.

## Open owner decisions

1. Option A, B or C.
2. Is browser-stored PII acceptable at all, and with PIN-wrapped WebCrypto?
3. Training data only, or real projects later?
4. Can trainings guarantee Wi-Fi (makes C sufficient)?
5. Is an iOS native (TestFlight) build a nearer path than a PWA?

## Owner decisions (2026-11-14)

1. Option B, kept extremely limited: sign in, set a PIN, do an interview offline, resume an
   unfinished interview, auto-sync when online. Nothing else offline (no case worklist, no
   death registration, no coding, no revisions).
2. Respondent data may be stored in the browser, encrypted behind the PIN.
3. Both training and real projects (not training-only).
4. Trainings cannot guarantee Wi-Fi but mostly have good mobile data; offline is a fallback.
5. TestFlight: explained to the owner; no decision recorded yet.

This reverses the online-only web policy: the `docs/policy/expo-client.md` baseline must be
updated and approved before any implementation.

Owner 2026-11-14 (later): the primary iOS path is a native iOS build of DigitVA Collect via
TestFlight (`.tasks/2026-11-14-ios-collect-testflight.md` once planned). Keep this limited
offline web queue as the fallback for any user, iOS or Android, who cannot install our app
for whatever reason; build it after the TestFlight path. Test it on Android Chrome as well as
iOS Safari.
