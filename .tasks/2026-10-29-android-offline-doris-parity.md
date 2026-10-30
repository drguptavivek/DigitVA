# Android offline DORIS coding: parity with the web flow

Status: design approved 2026-10-29; WP1/WP1b built and packaged 2026-10-30 (not published); WP2 and WP3 built 2026-10-30 (jest and golden replay; not yet run on a phone); rest not started
Priority: P1
Created: 2026-10-29
Bead: `digitva-9cll` (epic); WP1 `.1`, WP4 `.2`, WP2 `.3`, WP3 `.4`, WP5 `.5`; gaps `digitva-gt2v`, `digitva-bged`
Owner rule (2026-10-29): Collect Plus does the whole web DORIS coding flow on
the phone **with no server call** — enrolled or standalone, online or not. The
Android bridge (`mobile/digitva-collect/modules/digitva-icd11`) is the primary
ICD-11/DORIS use case; the desktop Rust host is not for Android.

## Goal

Every step a coder takes in the web DORIS form works the same on the phone,
answered by the on-device WHO engine and files in the APK:

1. Load the DORIS form for a case (seeded certificate, saved processing).
2. Search a certificate line: terms with badges (postcoordination, maternal,
   perinatal, coding note), **Use**, **+ Build**, **Details**, hierarchy,
   related maternal/perinatal.
3. Select a code: codeinfo, selection check, postcoordination axes and
   options ("More choices"), "Other postcoordination?" (X chapter) search,
   build a `&` / `/` expression, causing condition.
4. Add more codes on other lines.
5. Process: DORIS and CoDEdit, UCOD parts with titles, rule and tabular
   reports, warnings, reject, CoDEdit issues, VA definition, allowability,
   save.

## Design principle

The picker and `DorisPanel` already talk only to eight JSON routes
(`terms`, `codeinfo`, `selection-check`, `postcoordination`,
`postcoordination-options`, `hierarchy`, `related`, `details`) plus
`process` and the VA definition (`.tasks/2026-09-27-doris-picker-who-parity-and-reusable-component.md`
made these "the durable reusable surface"). **On the phone we answer the same
routes locally with the same reply shapes.** The screens do not change.

Three layers, each with one job:

| Layer | Job | Changes only when |
| --- | --- | --- |
| **Bridge** (`engine-src/Bridge.cs` → `libdigitva_icd11.so`) | Call WHO's controller actions; return **exactly WHO's REST JSON** (camelCase, REST status codes) | WHO releases, or a new WHO action is needed |
| **WHO client** (new `src/workspace/whoEngineApi.ts`) | The same calls the server's Python makes (`search`, `codeinfo`, `entity`, `foundationEntity`, `doris`, `codedit`), over the engine; small in-memory caches (titles, entities) | a WHO call is added |
| **DigitVA rules** (TypeScript port of the server's Python) | Build each DigitVA reply from WHO JSON exactly as `icd11_postcoordination.py`, `doris_certificate.py`, `doris_processing.py`, `icd11_titles.py` do | the server's rules change (golden tests catch drift) |

Rejected: doing the DigitVA reshaping inside the C# bridge. Every rule
change would need a 131 MB engine rebuild, a new pin and a phone parity run,
and C# in NativeAOT is harder to test than jest.

## Operation matrix

WHO calls are what the server makes today (`app/services/*`); the bridge
action is what the phone calls instead (`ICD-API.dll` metadata, 2026-10-29).

| Step | DigitVA route | WHO calls the server makes | Bridge action (offline) | Reshaping (ported to TS) | Today offline |
| --- | --- | --- | --- | --- | --- |
| Load form | workspace `doris` block | none | none | `certificateSeedFromInterview` (exists) | works |
| Search line | `terms` | `POST mms/search` with `q="<text>%"`, `includePostcoordination`, `flatResults`, `highlightingEnabled`, `medicalCodingMode`, `subtreesFilter` | `LinearizationController.SearchLinearization` **with those options** | `search_terms` (`icd11_postcoordination.py:547-604`) | partial: text only, no `%`, subtree ignored |
| Code typed / code chip | `codeinfo` | `codeinfo/{code}` ×2 + `mms/{stemId}` entity (+1 per cluster token) | `GetCodeInfo` (+ `GetCodeInfo2` for clusters) + `GetLinearizationEntity` | `_codeinfo_item`, `search_context_from_entity`, `expected_expression_uri` | broken: needs title (not in codeinfo) and entity flags |
| **Use** | `selection-check` | as codeinfo | as codeinfo | URI must equal expression URI | broken (as codeinfo) |
| **+ Build** | `postcoordination` | codeinfo, stem entity, one entity per axis root (≤12 × ≤12) | `GetCodeInfo` + `GetLinearizationEntity` | `postcoordination`, `_stem`, `_axes`, `_option` | throws |
| More choices | `postcoordination-options` | codeinfo, stem entity, ≤12 parent walk, parent, ≤12 children | same | `postcoordination_options` | throws |
| Other postcoordination? | `terms` + `subtree_uris` (X chapter) | search with `subtreesFilter` | `SearchLinearization(subtreesFilter=…)` | `search_terms` | wrong results (unfiltered) |
| Extension check | `codeinfo` `stem&ext` | codeinfo | `GetCodeInfo` | — | broken (as codeinfo) |
| Hierarchy | `hierarchy` | codeinfo, stem, ≤12 ancestors, siblings, ≤12 children, foundation entity per maternal/perinatal URI | `GetLinearizationEntity` + `FoundationController.GetFoundationEntity` | `hierarchy` | throws |
| Maternal / perinatal | `related` | stem entity, `mms/{foundationId}` per related URI, children | `GetLinearizationEntity` | `related_terms` | throws |
| Details | `details` | codeinfo, stem, one entity per exclusion (≤12) | `GetLinearizationEntity` | `code_details` | throws |
| Process | `process` | 1 codeinfo per coded condition, `POST doris`, `POST codedit`, title per UCOD token | `GetCodeInfo`, `UnderlyingCauseOfDeathDetection`, `CertificateCheck`, entity for titles | `verify_certificate_codes`, `who_safe_certificate`, envelope `{status,result}` (`doris_processing.py`), `ucod_parts`, `who_notes` | broken: PascalCase, no envelope, no checks |
| VA definition | `va-definitions/for-icd` | none for stems; codeinfo for `/` clusters | `GetCodeInfo` (clusters) | exists (`getBundledVaDefinition`) | works |
| Save / allowability | `coding/initial` | codeinfo for clusters | `GetCodeInfo` | exists (`judgeUnderlyingCause`, bundled pack) | works (needs codeinfo fix) |

The picker itself is the web page `app/static/doris_picker_host.html`, loaded
from the server in a WebView (`IcdPickerFrame.native.tsx`): **no step above
can run offline until Collect Plus has its own picker** (WP4).

## Bounded replies (owner 2026-10-29)

Every reply is bounded at every layer; nothing in the coding flow asks for
unbounded data.

- **DigitVA replies** keep the server's caps (20 terms, 12 axes, 12 options,
  12 ancestors/siblings/children, 20 inclusions, 12 exclusions) and set
  `truncated: true` when cut, so the picker says "refine the search". No
  cursor pagination: `next_cursor` stays `null`, as on the server.
- **Engine calls** never use `include=descendant`, and search always runs
  with `flatResults=true`. The bridge gets an optional `limit` for `search`
  that trims `destinationEntities` and sets `resultChopped: true` (a DigitVA
  addition; without it the reply is WHO's, unchanged, so parity holds), and
  refuses `include=descendant` and `limit` together with `flatResults=false`
  (WHO nests descendants under each result, which the trim does not reach).
  All three are in engine release 2026.10.29.1 (WP1b, packaged 2026-10-30,
  published by the owner).
- **Transport backstop:** a reply text over 250,000 characters becomes
  `too_large` (Binder limit), and a reply that still fails to send answers
  `too_large`; the app treats it as a handled error, never a hang.

## Work packages

**WP1 — Bridge rebuild (one engine release).** `engine-src/Bridge.cs`, `rd.xml`, `shim.c`, Kotlin, `offlineEngine.ts`.
Done 2026-10-30 as engine release `2026.10.29.1` (bead `digitva-9cll.1`, WP1b `.6`), packaged but not published. **No old-engine
fallback** (owner 2026-10-29): the bridge exports only `init`, `free` and `digitva_icd11_call` (the four single-argument
exports are gone); the shim's `load` requires `digitva_icd11_call` and returns 3 without it, so an old library fails loudly and
the app reports the engine unavailable (`load_failed`); the Kotlin `invoke`/`NativeCalls` mapping, `hasCall` and the shim's legacy
`call` are removed; CI fails the build when the staged library does not export the three functions. The APK always ships the
shim, Kotlin and JS built in the same run as the staged engine (no OTA updates), so a mismatch can only be a stale pin.
- One export `digitva_icd11_call(op, json, &status)`; the allowed ops live
  in C# only. Shim, `EngineJni`, `Icd11Service` and `EngineHost` pass the op
  name through. Keeps future ops to C# + TS.
- Ops: `search` (all `SearchLinearization` parameters), `codeinfo` (incl.
  cluster form, `flexiblemode`), `entity` (`GetLinearizationEntity`, with
  `include` and residuals), `foundation_entity`
  (`FoundationController.GetFoundationEntity`), `doris`, `codedit`.
  `FoundationController` is built in `Init` from the objects already there
  (constructor order: `ServiceConfig, ICDServiceSerializer, APIVersion,
  NewIndexAccessor, IConfiguration`).
- `Render` writes what WHO's REST layer writes: camelCase for DORIS/CoDEdit
  (today Newtonsoft PascalCase). Verify the exact serializer settings against
  the container, not by assumption.
- NativeAOT: root the new reply types (`LinearizationEntity`,
  `FoundationEntity`, `CodeInfo`, `PostcoordinationSet`, search results);
  regenerate `rd_gen.xml` and **commit its generator**.
- Parity kit (`scripts/icd11-parity`): add entity, foundation entity and
  search-with-options requests; compare field names **case-sensitively**.
  Learn the accepted `include` / `propertiesToBeSearched` values from the
  engine's error text in the first phone run.

**WP2 — WHO client and process.** `src/workspace/whoEngineApi.ts`, `offlineDoris.ts`.
- WHO client over `offlineEngine`, with the server's search parameters
  (trailing `%`, coding mode, subtree filter) and caches for titles and
  entities (per engine process).
- `onTerms`, `codeinfo`/`selection-check` via `_codeinfo_item` port (title
  and badges from the entity).
- `onProcess`: `verify_certificate_codes`, `who_safe_certificate`, the
  `{status, result}` envelope with the server's key checks, `ucod_parts`,
  `who_notes`. Token stays `local-<uuid>` (no server HMAC offline).
- A personal-data key check before any engine call (the server's PII rule).
- **No old-engine capability** (reversed by the owner decision of 2026-10-29; the Fable review had asked
  for a `generic: true|false` flag and an old-engine mode): the WHO client
  assumes the new engine's camelCase replies and search options. An old
  library is refused at load (see WP1), so there is nothing to adapt to.
- **Provenance:** each saved offline coding records the engine version, the
  DORIS rule-engine and rules versions and the ICD release.

Done 2026-10-30 (bead `digitva-9cll.3`; built, jest green, not yet run on a
phone). `src/workspace/whoEngineApi.ts` (WHO client, caches, pinned versions),
`dorisTerminology.ts` (`search_terms`, `search_context_from_entity`,
`_codeinfo_item`), `dorisCertificate.ts` (`doris_certificate.py`),
`dorisProcessing.ts` (`doris_processing.py`, `icd11_titles.py`),
`piiBoundary.ts` (Rule 6 of `vendor/who-icd11-api`), wired in `offlineDoris.ts`;
errors are `ApiError`s with the server's codes. Golden replay
(`__tests__/offline-who-golden.test.ts`): 238/238 search, 182 codeinfo and
selection-check operations of 44 postcoordination fixtures (485 guidance
operations wait for WP3), 173/173 DORIS, no unresolved mismatch. Deliberate
differences: the `local-<uuid>` token, `result_digest` binds the engine release,
no `timeout` status, the codeinfo item has no `primary_stem` (the editor's
`primaryStem()` answers it), a personal-data refusal is `INVALID_INPUT` with
`error.reason: "pii_boundary"`. Provenance is `packVersions` in the saved row;
`src/sync.ts` sends it as `pack_versions` because the server fixes the keys of
`provenance` (a coding without allowability provenance is no longer sent). The
terms reply's `release` is `2026-01`, as the server's (it was `ICD-11`). To
confirm on the emulator: the real engine's search, codeinfo (title absent), entity
and DORIS/CoDEdit replies feed the ports as the fixtures say; Binder timing of the
2 to 4 calls per code; `limit` 20 trimming; the picker's Use on a mandatory
stem (`BD54`) opens the builder from `postcoordination_availability: 2`.

**WP3 — Guidance offline.** port of `icd11_postcoordination.py` routes.
- `postcoordination`, `postcoordination-options`, `hierarchy`, `related`,
  `details` in TS over the WHO client, keeping the server's caps (12 axes, 12
  options, 48 calls) so replies match.
- Replace `offlineRequester` (always throws) with a local router for the five
  guidance paths; `pickerBridge.ts` and `guidance.ts` stay unchanged.

Done 2026-10-30 (bead `digitva-9cll.4`; built, jest green, not yet run on a
phone). `src/workspace/dorisGuidance.ts` (ports of `postcoordination`, `_stem`,
`_axes`, `_option`, `postcoordination_options`, `hierarchy`, `related_terms`,
`code_details`, `_resource`, the 48-read/10-second budget and the two-slot
capacity), `OfflineDorisEditor.onGuidance` and `createGuidanceRequester` in
`offlineDoris.ts`, wired in `offlineCoding.native.tsx` (one requester per open
store, as before, now answering the five routes for the open case). Golden
replay (`offline-who-golden`): 485/485 guidance operations (44 postcoordination,
77 options, 91 each of hierarchy, related maternal, related perinatal, details),
exact replies, no unrecorded engine call, no unresolved mismatch. Most engine
calls per request in the fixtures (cold caches): 46 (`PA50.Z` Build), 26
hierarchy. Deliberate differences: the guidance 503 wording, a personal-data
refusal is `INVALID_INPUT` with `error.reason: "pii_boundary"`, no 32 KB body
check, a non-string `chapter` is `INVALID_INPUT`. To confirm on the emulator:
the engine's status for an entity WHO has no coded form of (must be 404 for the
related-terms skip), Binder time of a Build against the 10-second budget, and
the picker's parallel Build + Details inside the capacity of two.

**WP4 — React ICD-11 picker for Collect Plus.**
- A React (React Native) picker inside `DorisPanel`, used in the **Collect
  Plus build only** (`isPlusVariant()`), online and offline. Plain Collect,
  the Expo web build and the Flask website keep the shared web picker.
- No WebView, iframe, Bootstrap or Font Awesome: app components and
  `theme.ts` tokens (light/dark); the two badge icons (maternal, perinatal)
  as small `react-native-svg` components.
- Talks only to `WorkspaceApi` (`searchDorisTerms`, `getDorisCodeInfo`,
  `checkDorisSelection`) and the guidance routes (`guidance.ts`), so online
  it uses the server and offline WP2/WP3 answer the same calls.
- Starting point: the React `IcdSelector` removed on 2026-10-13
  (`git show 1805595e6^:mobile/digitva-collect/src/workspace/doris/IcdSelector.tsx`),
  brought to the current web picker's behaviour (`app/static/js/digitva_icd11_picker.js`
  and `docs/kb/doris-picker-who-behaviour-rules.md`).
- Superseded 2026-10-29: the bundled web page (patch kept in the session
  scratchpad, not in git).

**WP6 — Offline DORIS demo in Collect Plus Help (owner 2026-10-29).**
- A "Try DORIS" demo reachable from Help in the Collect Plus build **without
  signing in** (from the lock and enrolment screens too), to exercise the
  React picker and the on-phone engine directly. Offline only: no server
  call, no case, no account, nothing saved.
- `DorisPanel` with the React picker over a demo `WorkspaceApi` built on the
  same offline editor as offline coding (WP2/WP3 rules over the engine);
  save, queue and case calls are absent, not stubbed to succeed.
- Loads the six synthetic examples (`resource/doris_help_examples.json`,
  bundled at build time) or a blank certificate, and runs DORIS and CoDEdit
  afresh on what is on screen. WHO's recorded `observed` values are **not
  shown** (owner 2026-10-29).
- **Try on web** button (deferred by the owner 2026-10-30 until WP7; not built): opens the public web demo (`/help/doris-demo`) in the
  phone's browser with the same certificate — `#example=<id>` for an unedited
  example, else `#certificate=<base64url JSON>`. The parameters travel in the
  URL fragment, which the browser never sends to the server, so nothing
  reaches server logs. The web demo (`app/static/js/doris_demo.js`) gains
  fragment loading (no other website change). This is the demo's only network
  action, and only on tap. A `#certificate=` link lands in the phone
  browser's history; acceptable for synthetic examples, so the button offers
  only `#example=` unless the owner decides otherwise. Origin: the demo server, `digitvademo.causeofdeathindia.com`
  (`demoServer()` in `src/demo.ts`), owner 2026-10-29 — after WP7 deploys the
  public DORIS demo there (today it answers 404: the demo ingress has one
  upstream, the demo app, and the public DORIS demo is served only by
  `doris_public_service` behind main's ingress).

**WP6 as built (2026-10-30).** `Try DORIS (offline demo)` row in the Help
sheet (Plus on Android only, hidden over an open form and on the demo itself)
opens `/doris-demo`; the header keeps its Help button on the sign-in, lock,
enrolment and PIN screens in Plus, and the accounts list already has it. Files:
`app/doris-demo.tsx`, `src/nativeRoutes/dorisDemo{,.web,.native}.tsx`,
`src/workspace/dorisDemo.ts` (demo editor and API), `src/dorisDemoAccess.ts`
(`canTryDorisDemo`), `assets/doris-help-examples.json`, strings
`helpTryDoris`/`dorisDemo*` in en and hi, tests `__tests__/doris-demo.test.tsx`
plus cases in `native-shell` and `native-collection-gate`.
- The examples file is a **copy** in `assets/` (no `metro.config.js`, so
  Metro does not watch `resource/`); a test keeps it equal to the resource file.
- `DorisPanel` still draws its Save and "Not codeable" buttons; pressing Save
  shows "This demo does not save anything." A `demo` prop on `DorisPanel` to
  hide them (and relabel "Reset DORIS from interview") was not added because
  that file has another change in flight.
- The "Try on web" button is deferred (owner): it comes with WP7.

**WP7 — Public DORIS demo on the demo server (owner 2026-10-29).**
- `docker-compose.demo.yml`: a demo-owned `demo_doris_public_service` from the
  same image (database-free, own limits, on `digitva_icd` for the WHO
  container), so demo visitors never share capacity with main's public demo.
- `deploy/ingress-demo.conf`: route `= /help/doris-demo` and
  `^~ /api/v1/doris-demo/` to it, as `deploy/ingress-routes.conf` does on main.
- Memory budget and steps in `docs/current-state/public-demo-deployment.md`;
  deploy only on the owner's go, following that runbook; verify with a GET of
  `/help/doris-demo` (200) and one DORIS process through the demo hostname.
- Engine start (~20 s) shows progress; the device-wide ICD-11 / DORIS switch
  is respected (when off, the demo says so and links to Settings).
- Tests: jest for the demo API (no store or network reachable), example
  loading, and the not-signed-in route.

**WP8 — Engine build on CI (Fable review 2026-10-29).** The engine is built
on a developer Mac today; `Bridge.csproj` hard-codes the ASP.NET shared
framework path and `/tmp/icdapi_portable`. Build it on CI from WHO's pinned
image with a pinned .NET SDK and NDK, `gen_rd.cs` and the parity kit — the
"next step 1" in the WHO note and the answer to WHO's maintenance concern.
Publishing the result stays an owner decision.

*Built 2026-10-30 (not yet run on GitHub).* `build.sh` is portable (macOS and
Linux x64; SDK pinned in `engine-src/global.json`, ASP.NET Core found from the
SDK, `Bridge.csproj` takes `IcdApiDir` and `AspNetDir`), and
`.github/workflows/icd11-engine-build.yml` builds from the digest-pinned WHO
image, fails on a stale `rd_gen.xml`, checks the three exports and 16 KB
alignment, packages the archive, uploads it for 7 days and reports whether the
library equals the pinned release's. Details in
`docs/current-state/icd11-android-engine-interface.md` ("Building the
engine"). The Mac build with the portable script reproduced the release
library (`8bfdc258...`) and left `rd_gen.xml` unchanged. Not covered: the parity
kit and the JNI smoke need an arm64 phone and stay manual; the Linux build
path is untested until the first run. Open owner decisions: whether CI becomes
the source of release builds (then publish from its artifact and pin its
library sha256 in `collect-plus-release.yml`), and runner cost if the
repository is private.

**WP4 layout round 2 — phone portrait and tablet landscape (Fable review
2026-10-29).** After the current safety/density fixes:
- **Rows:** flat two-line rows (hairline separators, no card): line 1 is the
  whole-line tap target (Use, or Build when postcoordination is mandatory)
  with code + title and a trailing 32 dp Details "ⓘ"; line 2 only when
  present: 28 dp badge pills (token tints per kind), "Matched:" one line,
  age-restricted warning. No row Use/Hierarchy buttons (Hierarchy lives in
  Details). Target on the SM-E146B: ~8 annotated / 14 plain rows, ~5 / 8 with
  the keyboard up (web phone ≈ 4).
- **Header and footer:** title and search input fixed above the scroll (no
  separate Search button; the keyboard's search key submits), "Add uncoded
  text" as a small link; footer carries BUILDING with the live expression and
  both Use actions, capped at 28 % of the height with inner scroll.
- **Cards:** on phones scroll to the opened card and offer "Back to results";
  on tablets (`useUi().phone` false, ≥ 768 dp) a two-pane picker inside the
  modal like the web: results ~40 % (min 320 dp) | details/builder/hierarchy.
- **Build:** 40 dp option rows with a check circle; optional axes collapsed on
  phones ("(optional) · n chosen"), expanded on tablets; long lists capped at
  8 + "Show all".
- **Certificate form:** tighter line cards on phones; on tablets a centred
  840 dp column, the three actions in one row, and the processing summary in
  two columns. The picker stays a modal.
- **Accessibility:** no fixed heights on text, `maxFontSizeMultiplier` only on
  pills and captions, stack the Details button at font scale ≥ 1.5, Devanagari
  line heights.
- **Orientation (owner decision 2026-10-29: tablets in landscape, "like a
  desktop monitor"):** `app.json` `"default"`; phones (width < 600 dp) locked
  to portrait in the root layout. Applies to every screen of both apps on
  tablets, so the interview form and other screens must be checked in
  landscape too.
- Keyboard on Android (edge-to-edge, Modal) verified on the phone before
  adding any keyboard handling.

**Round 2 status (2026-10-30, digitva-9cll.2).** Built in JS, not yet seen on
a device: flat rows with the ⓘ and 28 dp pills, header without a Search
button, build rows with check circles / folded optional axes / "Show all N",
the tablet two-pane picker, `Modal supportedOrientations`, `app.json`
`"orientation": "default"` (needs a native rebuild). Phone portrait lock landed 2026-10-30 (owner go): `expo-screen-orientation`,
and `app/_layout.tsx` locks to portrait when the screen's shortest side is
under 600 dp. Every app and VA form scroller (31 in `src`, `app` and
`vendor/who-va-2022`) closes the keyboard on drag (`keyboardDismissMode`),
after the emulator showed the keyboard toolbar covering the picker footer.
Seen on the Pixel 7 emulator 2026-10-30: round-2 rows, Build with a
mandatory axis (CA40.1Z/1D82), DORIS and CoDEdit equal to the WHO API. To confirm on the emulator: row counts per
screen (target ~8 annotated / ~14 plain; ~5 / ~8 with the keyboard), Matched
caption staying on one line, the ⓘ and pills reach at 44 dp, keyboard
behaviour with the fixed header, and on a tablet the two-pane split, rotation
with a card open (a window crossing 768 dp re-mounts the open card), and the
interview form and other screens in landscape.

**WP5 — Proof.**
- Golden tests: record the server's replies for a fixed code set (stems with
  required axes, clusters, X extensions, maternal/perinatal links, injuries)
  together with the WHO JSON they were built from; the TS port must produce
  the same replies from the same WHO JSON. This catches Python↔TS drift.
- Phone run of the full journey (test plan in
  `private/DigitVA offline coding phone test plan.md`), airplane mode,
  standalone and enrolled; timings and memory with `scripts/android-profile.sh`.

Order: WP1 and WP4 in parallel (different files); WP1b (bounded search, no descendant include) in the next engine build; WP2 after WP1's op names
are fixed; WP3 after WP2; WP5 throughout.

## Test coverage (owner 2026-10-29: full coverage)

Every layer has its own tests, and every change ships with them. No layer is
"verified by the layer above".

| Layer | Tests | Runs where |
| --- | --- | --- |
| C# bridge (`Bridge.cs`) | Parity kit: every op and every argument against WHO's container, case-sensitive; error paths (unknown op, bad JSON, wrong types, before init, `limit`, refused `include`) | phone over adb (`scripts/icd11-parity`), on every engine build |
| C shim (`shim.c`) | JNI smoke: an old library (no `digitva_icd11_call`) is refused by `load` with 3 and nothing works through it; the new library: `load`, `initEngine`, `callOp` for every op and refusal, NULL and error paths, no engine text returned | instrumentation test on the phone (adb), on every engine build |
| Kotlin (`EngineHost`, `Icd11Service`, module) | JVM unit tests: result maps and error codes, `toBundle` caps, `too_large` reply, op-name validation, priority queue order, init wait | CI (`gradlew :digitva-icd11:test…UnitTest`) before the APK build |
| `offlineEngine.ts` | jest: every method, options omitted when unset, re-init after a lost process, every error code | CI (`npm test`) |
| WHO client and DigitVA rules (WP2, WP3) | jest golden tests: recorded WHO JSON in → the server's recorded DigitVA reply out, for a fixed code set; plus edge cases (clusters, X extensions, required axes, maternal/perinatal, injuries, empty, too large) | CI |
| React picker (WP4) | React Native Testing Library: search, badges, Use, Build with required-first axes, More choices, Other postcoordination?, causing condition, Details, hierarchy, related, final mode, errors, empty and truncated states, light/dark | CI |
| Whole journey (WP5) | Phone run in airplane mode, standalone and enrolled, with timings and memory | phone, before each Collect Plus release |

### Golden sets (owner 2026-10-29)

Three frozen, versioned sets, recorded from the reference (WHO's 2.6.0
container and the DigitVA server's rules) and replayed against the phone
engine (parity kit) and the TS port (jest). A change to any expected value is
a reviewed change, never a silent re-record.

1. **DORIS golden set.** Certificates covering the WHO 2022 VA cause list —
   adult, child, neonatal and maternal; single and multi-line Part I; Part II;
   clusters; uncoded and rejected cases; intervals; external causes and manner
   of death; surgery, autopsy, maternal and fetal/infant blocks — with the
   expected UCOD `code`, `stemCode`, `uri`, `reject`, `warning`, the rule
   report rows (`tabularReport`) and CoDEdit `issueIds`, plus DigitVA's
   `ucod_parts` and `who_notes`.
2. **Postcoordination golden set.** Stems with **mandatory** postcoordination
   (e.g. `BD54` "Has causing condition"), injury stems with several axes
   (`NC72.7`, `NC71.Z`), optional-axis stems (`2A01.0Y`), X-chapter extension
   checks (`stem&X…`), clusters (`1B12.2&XA0G74`, `1A00/5A11`), causing
   condition and "unknown" — with the expected DigitVA replies for
   `codeinfo`, `selection-check`, `postcoordination` (stem, axes in order,
   required flags, instructions, root options, subtree URIs, Other
   postcoordination?), `postcoordination-options`, `hierarchy`, `related`,
   `details`, and the final expression and URI after stem selection plus axis
   values.
3. **Search golden set: top 5 for cause-of-death terms.** The terms medical
   officers search when certifying VA deaths (common diseases, injuries,
   maternal and neonatal conditions, lay and abbreviated wording, typos, and
   **partial words as typed mid-search** — `myocard`, `hyperten`, `cirrho`,
   `pneumon`, `tubercul`, `septic`, `haemorrh`/`hemorrh`, `eclamp`, `asphyx`,
   `prematur`, `malign`, `diabet`, `poison`, `drown`), and **words that sit
   in the middle or end of a title** rather than at its start — `mellitus`,
   `insipidus`, `sarcoma`, `carcinoma`, `infarction`, `failure`, `fracture`,
   `obstruction`, `haemorrhage` — and their partial forms (`mellit`,
   `sarcom`)) with
   the expected top 5 results (code, title, URI, badges) under the
   server's search options. Two uses (Fable review 2026-10-29): the **parity**
   run (phone engine vs WHO container, same release) requires the same top 5
   in the same order; the **clinical** check (TS port, and across WHO
   releases) requires only that the expected code is in the top 5, so a WHO
   ranking change is a reviewed difference, not a failure.

Corpus lists live in one reviewable file per set; the owner approves the
lists before they are frozen. Fixtures carry the WHO JSON they were built
from, so the TS port is tested offline in jest and the engine on the phone.

Coverage is measured for TS (`jest --coverage` on the changed files, target
100% of new lines and branches; exceptions named in the PR) and listed per
Kotlin class for the JVM tests.

## Risks

- **Two copies of the rules (Python and TS).** Golden tests in WP5 are the
  guard; any change to `icd11_postcoordination.py` or the DORIS processing
  must update both.
- **NativeAOT trimming** of the new reply types: found only by running on a
  phone; the parity kit must cover every op.
- **Call volume:** hierarchy can need ~40 entity reads; each is a Binder hop
  plus ~1 ms in the engine. Measure; cache entities per engine process.
- **Engine shared state:** language is fixed to English on the bridge's
  `HttpContext`; Hindi entity text would need per-call headers under the lock.
- **Search wording:** server uses POST with a form body; the bridge calls the
  method with the same values, so results should match — confirm in parity.

## Owner decisions (2026-10-29)

1. **Reshaping in the app, in TypeScript.** The bridge returns exactly WHO's
   REST JSON; the app ports the server's rules.
2. **One generic engine call** (`digitva_icd11_call(op, json)`); allowed ops
   live in the C# bridge only.
3. **React ICD-11 picker in Collect Plus only** (revised the same day; the
   first choice, a bundled copy of the web page, was dropped). Plain Collect,
   the Expo web build and the website keep the shared web picker.
5. **Bounded replies everywhere** (see that section); no cursor pagination.
7. **Tablets rotate to landscape** across both apps; phones stay portrait
   (see WP4 layout round 2).
6. **Engine bundles may be public releases** (existing and new), only if every
   input is public, open and unrestricted: WHO's assemblies from the public
   `whoicd/icd-api` image by digest, WHO's data from WHO's public CDN by
   SHA-256, and this repository's bridge sources. Recorded in
   `docs/policy/icd11-local-api-runtime.md`. The new engine (WP1, WP1b) is
   packaged as `icd11-engine-2026.10.29.1`; the owner publishes it, and the
   commit that pins it must land with the publish. The app has no fallback to
   the old engine (decision 2 of this list, 2026-10-30): the old release stays
   published but no app built from this tree can use it.
4. **Offline process token stays `local-<uuid>`.** No on-phone signing; the
   server does not re-run DORIS on offline results.

## References

- As-built interface, every layer's functions and input/output shapes:
  `docs/current-state/icd11-android-engine-interface.md` (update it with WP1).
- Server flow inventory (2026-10-29): routes in `app/routes/api/doris_clinical.py`;
  WHO calls in `app/services/who_icd_api.py`, `icd11_postcoordination.py`,
  `doris_certificate.py`, `doris_processing.py`, `icd11_titles.py`.
- WHO controller surface: `ICD-API.dll` 2.6.0 metadata
  (`LinearizationController`, `FoundationController`; all actions synchronous,
  `IActionResult`).
- Architecture paper: `private/DigitVA offline ICD-11 and DORIS on Android - engine architecture and data flow.md`.
