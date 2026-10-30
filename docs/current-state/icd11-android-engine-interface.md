---
title: ICD-11 Android Engine Interface
doc_type: current-state
status: active
owner: engineering
last_updated: 2026-10-31
---

# ICD-11 Android Engine Interface

The as-built interface of the Collect Plus offline ICD-11 / DORIS engine
(`mobile/digitva-collect/modules/digitva-icd11`), layer by layer: every
function each layer exposes, what goes in and what comes out. Android only.

This page does not restate shapes documented elsewhere:

- The WHO certificate (`AdministrativeData`, `Part1[].Conditions[]`,
  `Part2`, `Surgery`, `Autopsy`, `MannerOfDeath`, `FetalOrInfantDeath`,
  `MaternalDeath`) and DigitVA's `process` request and reply:
  [DORIS Certificate UI and API Contract](../kb/doris-certificate-ui-contract.md).
- WHO's REST reply fields for DORIS and CoDEdit, and how to read them:
  [WHO DORIS, CoDEdit and AutoCoding in DigitVA](../kb/doris-icd-api-and-va.md).
- What the WHO web DORIS sends while a coder types and picks:
  [WHO DORIS Web Behavior and API Shape](../kb/doris-web-behavior-and-api-trace.md).
- The coding workflow and screens: [DORIS COD Workflow](doris-cod-workflow.md).

The engine answers one call (`digitva_icd11_call`) that returns what WHO's REST
API returns for the same action. There is no other call and no fallback: the
APK always ships the shim, the Kotlin and the JS built in the same CI run as the
staged engine, so new code meets an old engine only through a stale pin, and the
shim then refuses that library at load (see [Layer 2](#layer-2-jni-shim-libdigitvaicd11shimso))
and a CI check fails the release first (see [CI check](#ci-check-of-the-staged-engine)). The plan for what is built on it (WHO client,
DigitVA rules, guidance routes, React picker) is
`.tasks/2026-10-29-android-offline-doris-parity.md` (bead `digitva-9cll`).

## Call chain

```text
DorisPanel / picker (JS)
  └─ offlineWorkspaceApi (WorkspaceApi)        src/nativeRoutes/offlineCoding.native.tsx
      └─ OfflineDorisEditor                    src/workspace/offlineDoris.ts
          └─ DigitVA rules (server ports)     src/workspace/dorisTerminology.ts, dorisGuidance.ts, dorisCertificate.ts, dorisProcessing.ts, piiBoundary.ts
              └─ WHO client                    src/workspace/whoEngineApi.ts
                  └─ OfflineEngine             src/offlineEngine.ts
                      └─ DigitvaIcd11Module (Expo)     android/.../DigitvaIcd11Module.kt     app process
                          ══ Binder (Messenger) ══
                      └─ Icd11Service → EngineHost     android/.../Icd11Service.kt, EngineHost.kt   ":icd11" process
                          └─ EngineJni → shim.c        libdigitvaicd11shim.so (JNI)
                              └─ Icd11Bridge           libdigitva_icd11.so (NativeAOT: Bridge.cs + WHO ICD-API 2.6.0)
                                  └─ LinearizationController (WHO)
```

Every text that crosses a boundary is UTF-8. Every operation is an op name plus
one JSON string of named arguments, and returns one JSON string plus a status.

## Layer 1: C functions exported by `libdigitva_icd11.so`

Source: `engine-src/Bridge.cs` (class `Icd11Bridge`, `[UnmanagedCallersOnly]`).

| Function | Input | Output |
| --- | --- | --- |
| `char* digitva_icd11_init(const char* bundleDir, const char* dataDir)` | Absolute paths of the copied `bundle/` (appsettings, `Data/languageResources.txt`) and `data/` (release, index, DORIS rules) folders | `NULL` when ready; otherwise an exception text (caller frees it). A second call after success returns `NULL` at once. |
| `char* digitva_icd11_call(const char* op, const char* json, int* status)` | An op name and a JSON object of named arguments; see [the ops](#the-ops-of-the-call) | WHO's REST JSON for that action, with `*status` |
| `void digitva_icd11_free(char* text)` | A result from either function above | Releases it |

These three are the library's whole interface. The engine bundle is a public
release (owner decision 2026-10-29; every input is public).

### The ops of the call

The list of ops lives in `Icd11Bridge.Dispatch` and nowhere else; adding one is
a C# and TypeScript change. Release is fixed to `2026-01`, linearization to
`mms`. An absent argument, or one that is `null`, takes WHO's default (an empty
string counts as absent, as ASP.NET's binder reads an empty query or form
value). A non-string where a string is expected, or a non-boolean where a
boolean is, is a 400.

| Op | Arguments (default) | WHO action |
| --- | --- | --- |
| `search` | `q`; `subtreesFilter` (none; comma-separated linearization URIs); `subtreeFilterUsesFoundationDescendants` (false); `includeKeywordResult` (false); `chapterFilter` (none); `includePostcoordination` (true); `useFlexisearch` (false); `flatResults` (true); `highlightingEnabled` (true); `medicalCodingMode` (true); `propertiesToBeSearched` (none; `Title`, `FullySpecifiedName`, `Definition`, `Exclusion`, `IndexTerm`, `RelatedImpairment`, `CodingNote`, comma-separated); `limit` (none; DigitVA's, not WHO's: an integer 1 to 200) | `LinearizationController.SearchLinearization`. A missing or empty `q` is WHO's own 400. The server sends `q` with a trailing `%` and the four flags above set as listed. With `limit`, the reply keeps the first `limit` `destinationEntities` and sets `resultChopped` to `true` when it cut any (WHO's own `resultChopped` is never cleared); without it the reply is WHO's, unchanged. A `limit` that is not an integer from 1 to 200 is a 400, and so is a `limit` together with `flatResults=false` (see Bounded replies). |
| `codeinfo` | `code` (required: a code, `stem&ext`, or a cluster `a/b`); `flexiblemode` (false); `convertToTerminalCodes` (false) | `GetCodeInfo`. Clusters go through it as they did before; `GetCodeInfo2` is not used. |
| `entity` | `id` (required, numeric entity id); `residual` (none; `unspecified` or `other`); `include` (none; `ancestor`, `diagnosticCriteria`; `descendant` is refused, see below) | `GetLinearizationEntity`, or `GetLinearizationResidualEntity` when `residual` is given |
| `foundation_entity` | `id` (required); `include` (none; same values, `descendant` refused) | `FoundationController.GetFoundationEntity` (release not set) |
| `doris` | `certificate` (required: any JSON value, the WHO certificate object) | `UnderlyingCauseOfDeathDetection` |
| `codedit` | `certificate` (required) | `CertificateCheck` |

**`*status`** is the HTTP status of WHO's result, or the bridge's own:

| Status | Body | When |
| --- | --- | --- |
| WHO's (200, 400, 404, ...) | WHO's JSON (a 400 is a JSON string, e.g. `"value of the include paramater is incorrect. Accepted values are ancestor,descendant,diagnosticCriteria"`, WHO's list, though the bridge refuses `descendant` itself; a `NotFound` result has no body in-process, so `null`, where REST sends a text) | the controller returned a result |
| 503 | `{"error":"not initialized"}` | called before a successful `init` |
| 400 | `{"error":"unknown op"}`, `{"error":"bad json"}` (`json` is not JSON), `{"error":"bad argument: <name>"}` (not an object, a missing required argument, or the wrong type; for `limit`, a value outside 1..200 too), `{"error":"limit requires flatResults"}` (`search` with `limit` and `flatResults` false; checked after `limit` itself, so an invalid `limit` is the `bad argument` above), `{"error":"include descendant is not allowed"}` (`entity` or `foundation_entity` with an `include` that contains `descendant`, in any case, alone or in a list) | the call was refused before WHO ran. The reply names the argument, never its value. |
| 500 | `{"error":"<exception message>"}` | WHO threw |

**Rendering** (`Render`): a `ContentResult` is passed through; a string is
written as a JSON string; any other `ObjectResult` is written by the
formatters WHO registers for its REST API in `Startup.ConfigureServices`, in
the same order: `JSONLDFormatter`, `EnhancedPCCSFormatter`, then
`SystemTextJsonOutputFormatter` with `PropertyNamingPolicy = CamelCase`. The
last one writes DORIS and CoDEdit, which is why their fields are camelCase over
REST.

**Bounded replies** (owner decision 2026-10-29, `.tasks/2026-10-29-android-offline-doris-parity.md`): `include=descendant` would return a whole subtree, so the bridge refuses it before WHO runs; `search` takes `limit` so a caller can ask for a short list. The trim (`Chop`) parses WHO's reply, drops the entities after the first `limit`, sets `resultChopped` and writes the JSON again (relaxed escaping, WHO's numbers kept as text); a reply without `limit` is never parsed or rewritten, so parity with WHO holds for every request that does not use these two additions. `limit` trims only the top-level `destinationEntities`, and with `flatResults=false` WHO nests descendants under each result, so the trim would not bound the reply: the bridge refuses `limit` together with `flatResults=false` (400) before WHO runs. The app always sends `flatResults=true`. `flatResults=false` without `limit` is WHO's own reply, unchanged.

**Init configuration**: `appsettings.json` + `appsettings.container.json`,
overridden with `acceptLicense=true`, `enableDoris=true`, `include=2026-01_en`,
`saveAnalytics=false`, `applicationCacheFolder=<dataDir>`,
`icd11Conf:EnableCodingTool=false`; DORIS loads `dorisVersion_default`. One
`LinearizationController` and one `FoundationController` are built from the same
objects (`ServiceConfig`, `ICDServiceSerializer`, `APIVersion`,
`NewIndexAccessor`, `IConfiguration`; the two constructors take them in
different orders). The HTTP context asks for `Accept: application/json`,
`Accept-Language: en`, `API-Version: v2`. Phase end times are written to
`<root>/init-timings.txt` (`config=… doris=… index=… ready=…`, ms).
`DIGITVA_ICD11_SERIAL=1` loads DORIS and the index one after the other instead
of in parallel.

**Threading**: every call takes one lock (`Gate`). The caller must not run two
calls at once anyway (see layer 3).

**NativeAOT**: `rd.xml` (hand-written) and `rd_gen.xml` root the generic
instantiations that protobuf-net, Newtonsoft.Json and System.Text.Json reach by
reflection. `engine-src/gen_rd.cs` generates `rd_gen.xml` from the metadata of
WHO's assemblies, and `engine-src/build.sh` runs it before every publish (see [Building the engine](#building-the-engine)). The
reply types of the entity and search ops (`LinearizationEntity`,
`FoundationEntity`, `CodeInfo`, the search results) live in `ICD-API` and
`OCT`, which are rooted whole.

## Layer 2: JNI shim `libdigitvaicd11shim.so`

Source: `android/src/main/cpp/shim.c`; Kotlin side `EngineJni.kt`. The shim
`dlopen`s the engine and looks up its three symbols; it is the only code that
touches C pointers. `load` requires all three (`digitva_icd11_init`,
`digitva_icd11_free`, `digitva_icd11_call`): a library without
`digitva_icd11_call`, such as an engine archive from before 2026.10.29, is
refused with 3, nothing is initialised or called through it, and the app reports
the engine unavailable (`load_failed`, layer 3). It fails loudly instead of
running half-way.

| Kotlin (`EngineJni`) | Input | Returns |
| --- | --- | --- |
| `load(path: String): Int` | Absolute path of `libdigitva_icd11.so` | 0 loaded (or already loaded); 1 the path string could not be read from Java; 2 `dlopen` failed; 3 a required symbol (`digitva_icd11_init`, `digitva_icd11_free`, `digitva_icd11_call`) is missing (no `dlerror` text is passed on) |
| `initEngine(bundleDir: String, dataDir: String): Int` | As `digitva_icd11_init` | 0 ready; 1 engine reported an error (its text is freed, never returned); 2 `load` has not succeeded |
| `callOp(op: String, json: String, status: IntArray): ByteArray?` | op name and JSON arguments (layer 1 ops) | UTF-8 JSON bytes, `status[0]` = layer 1 status; `null` if not loaded or no result (`status` untouched when the strings cannot be read) |
| `loadOpenSsl(): Boolean`, `loadShim(): Boolean` | — | Load `libcrypto`/`libssl` and the shim with `System.loadLibrary`; false when absent |

Not thread-safe; called from one worker thread only.

## Layer 3: engine service (`:icd11` process)

Sources: `Icd11Service.kt`, `EngineHost.kt`, `EngineData.kt`.

### Binder protocol (`Icd11Service`, bound with a `Messenger`)

Request `Message`: `what` = request kind, `arg1` = request id (echoed),
`data["input"]` = input text, `data["op"]` = op name (calls only), `replyTo` =
the caller's `Messenger`.

| `what` | Request | `data` |
| --- | --- | --- |
| 0 | `OP_INIT` | none |
| 1 | `OP_CALL`: one engine call | `op`: the op name (layer 1); `input`: the JSON object of its arguments |
| 5 | `OP_UPDATE` (legacy) | none; always answers `{ok:false, error:"bundled_only"}` |

The service and the host check only the shape of an op name
(`[a-z_]{1,32}`); which names exist is the bridge's list, and an unknown one
comes back as status 400. 

Reply `Message`: same `what` and `arg1`; `data` is the result map below as a
`Bundle`. A `text` longer than 250,000 characters is replaced by
`{ok:false, error:"too_large"}` (Binder transactions are capped near 1 MB and a
Parcel stores strings as UTF-16); a reply that still fails to send with
`TransactionTooLargeException` is answered with the same code, so no request is
left waiting.
While an init runs, extra messages with `what = 100` (`WHAT_PROGRESS`) carry
`phase` (`copy`, `engine`, `ready`) and `percent` (0–100, or -1 unknown); they
never answer a request.

Scheduling (`JobScheduler`): one worker thread (32 MB stack) runs a priority queue —
interactive calls (0) before init (1) before housekeeping (2), first come
first served within a priority. A call that arrives while init is queued or
running is held and joins the queue, in arrival order, when the init has
answered.

### Result maps (`EngineHost`)

| Operation | Success | Failure |
| --- | --- | --- |
| init | `{ok:true, copyMs, initMs, ms, cached:false, phases:"config=… ready=…", setup:"{\"mode\":\"shipped\",\"files\":[]}"}`; later inits in the same process return the first result with `cached:true, ms:0` | `{ok:false, error, copyMs, initMs, ms, cached:false}`, `error` one of `unavailable` (no shim), `load_failed` (no library, `dlopen` failed, or the library lacks an export, `digitva_icd11_call` included), `init_failed`, `data_copy_failed`; sticky until the process restarts |
| a call (`OP_CALL`) | `{ok:true, status, text, nativeMs}` for status 200–299 | `{ok:false, error:"engine_status", status, nativeMs}` (body dropped: it can echo input or a stack trace; a 400 from the bridge or from WHO shows as status 400); `{ok:false, error:"not_initialized", status:503}`; `{ok:false, error:"bad_op", status:0}` (op name of the wrong shape) |
| any (throwable in the service) | — | `{ok:false, error:"native_error"}` |

Before init: data is copied once from APK assets to
`filesDir/icd11-<DATA_VERSION>/` (`EngineData.ensureCopied`), WHO files are
checked against `assets/digitva-icd11/who-files.json` and restored if missing
or the wrong size, `TMPDIR` is set to `data/`, and
`http(s)_proxy`/`HTTP(S)_PROXY` are set to `http://127.0.0.1:9` so WHO's
start-up downloads fail at once.

## Layer 4: Expo module `DigitvaIcd11` (JS-visible)

Source: `DigitvaIcd11Module.kt`.

| Function / event | Input | Resolves with | Rejects with |
| --- | --- | --- | --- |
| `isAvailable()` | — | `true` if this build ships `libdigitva_icd11.so` (does not start it) | — |
| `init()` | — | init map (layer 3) | `ERR_ICD11_PROCESS` if the engine process stopped |
| `updateWhoFiles()` | — | init map of the init that runs in a new engine process | `ERR_ICD11_PROCESS` |
| `call(op, input)` | `op`: the op name (`"search"`, `"codeinfo"`, `"entity"`, `"foundation_entity"`, `"doris"`, `"codedit"`); `input`: the JSON text of its arguments | call map (layer 3) | `ERR_ICD11_OP` op name of the wrong shape; `ERR_ICD11_PROCESS` engine process stopped |
| event `icd11Progress` | — | `{phase, percent}` during init | — |

The module binds the service on first use, queues messages until it is
bound, and fails every pending request when the process dies.

## Layer 5: `OfflineEngine` (`src/offlineEngine.ts`)

`offlineEngine()` returns the process-wide engine; every method returns
`{ok:false, error:"icd11_doris_disabled"}` while the ICD-11 / DORIS preference
is off, and `{ok:false, error:"unavailable"}` on web and in the plain build.

| Method | Input | Output |
| --- | --- | --- |
| `available()` | — | `boolean` |
| `init()` | — | `EngineInit`: `{ok:true, ms, copyMs, initMs, cached, phases?, setup?:{mode, files[]}}` or `{ok:false, error, ms}`. Concurrent calls share one request. |
| `call(op, args)` | `op`: an `EngineOp`; `args`: the object of named arguments (sent as `JSON.stringify`; `undefined` members are left out) | `EngineResult` |
| `search(query, options?)` | `q` and `options`: any other `search` argument (`SearchOptions`, including `limit`) | `EngineResult`; `call("search", {q, ...options})` |
| `codeinfo(code, options?)` | `code`; `{flexiblemode?, convertToTerminalCodes?}` | `EngineResult` |
| `entity(id, options?)` | numeric id; `{residual?, include?}`; `include: "descendant"` comes back as status 400 (`engine_status`) | `EngineResult`; op `entity` |
| `foundationEntity(id, options?)` | numeric id; `{include?}` | `EngineResult`; op `foundation_entity` |
| `doris(certificate: object)` | certificate object | `EngineResult`; `call("doris", {certificate})` |
| `codedit(certificate: object)` | certificate object | `EngineResult` |
| `onProgress(listener)` | `({phase, percent?}) => void` | unsubscribe function |
| `updateWhoFiles()` | — | `EngineInit` |

`EngineResult` = `{ok:true, data: <parsed JSON>, status, ms, nativeMs}` or
`{ok:false, error, status?, ms}` with `error` one of `engine_status`,
`not_initialized`, `bad_json` (reply not JSON), `native_error`,
`unavailable`, `icd11_doris_disabled`, or the init error after a failed
re-init. If Android killed the engine process, a call re-initialises once and
retries.

## Operation shapes as returned on the phone

What `data` holds in layer 5. Every reply is WHO's REST JSON for the same
action, compared field name for field name (case-sensitively) with the WHO
container by `scripts/icd11-parity` (targeted run of 2026-10-30 on the SM-E146B against the 2.6.0 container, with the library of engine release 2026.10.29.1 (no fallback, `limit` refused with `flatResults=false`), everything through the one call: 200 generated certificates through DORIS and CoDEdit, 5 malformed certificates, 92 search texts, 57 code-info inputs and 118 rows of `calls.json` (search options, code-info options, 39 entity and 16 foundation-entity requests, 28 rows of the bounds: `limit` valid and invalid, `limit` with and without `flatResults=false`, refused `include`): 472 of 472 requests identical (431) or refused with the same class of status on both sides (41), none only on one side. WHO's container knows none of the bridge's bounds, so `run_container.py` trims its reply the way the bridge does for `limit` and writes the bridge's refusals (`include` with `descendant`, `limit` with `flatResults=false`); `compare.py` requires those refusal bodies to match exactly). The kit now also sends the 1,431 WHO reads and 161 certificates recorded in `scripts/icd11-golden` (section `golden`, in `eval.sh quick` and `full`) and 8,909 reads the coding screen makes for 401 codes (`datasets/api-sweep`, `full`) through the same comparison: every engine read the golden sets recorded, plus the picker reads of `datasets/api-sweep` (its README lists the caps). The first full run (2026-10-30, SM-E146B, engine 2026.10.29.1, 30,783 request lines) matched in every row: 30,088 identical, 695 refused on both sides (648 of them sweep reads of residual categories that do not exist), none different or one-sided (`scripts/icd11-parity/results/2026-10-30-full-engine-2026.10.29.1-surface/`). A second full run with all four libraries (engine, `libssl`, `libcrypto`, `libc++_shared`) taken from the published Collect Plus 0.3.18 APK matched the same way (`...-apk-0.3.18/`); `run_phone.sh` now takes them from that APK and stops if its engine differs from the pinned archive. Under that load the engine made 50,959 calls in 173 s (DORIS median 3.4 ms, CoDEdit 4.4 ms, search 5.2 ms with p99 186 ms, lookups under 0.5 ms) and its RSS grew from 511 MB after start to 1,082 MB (peak 1,179 MB), most likely WHO's entity cache filling with the 6,548 entity reads; full table in the WHO technical note, section 6. The kit, its committed datasets and the results of every run, in one layout (`scripts/icd11-parity/eval.sh quick|full`), are described in `scripts/icd11-parity/README.md`; the runs themselves are in `scripts/icd11-parity/results/`. Field lists here are the
top-level names; WHO's own documentation describes their meaning.

### search

- **Input**: `q` plus the options in [the ops table](#the-ops-of-the-call).
  The server sends `q="<text>%"` with `includePostcoordination`, `flatResults`,
  `highlightingEnabled`, `medicalCodingMode` all true and `subtreesFilter` set
  to the comma-joined URIs; the same arguments give the same hits. With only
  `q`, WHO's defaults apply. An empty or missing `q` is 400. `limit` (1 to 200) trims the list as described in the ops table; the picker's own caps (20 terms) are applied by the app on top.
- **Output**: `destinationEntities[]`, `error`, `errorMessage`, `resultChopped`,
  `wordSuggestionsChopped`, `guessType`, `uniqueSearchId` (a new random value on
  every call; the parity comparison drops it) and `words`. Each entity carries at
  least `id`, `title` (with `<em class='found'>` highlighting), `stemId`,
  `isLeaf`, `postcoordinationAvailability` (0/1/2), `hasCodingNote`,
  `hasMaternalChapterLink`, `hasPerinatalChapterLink`, `matchingPVs[]`
  (`propertyId`, `label`, `score`, `important`, `foundationUri`,
  `propertyValueType`), `propertiesTruncated` and `isResidualOther`. The code is
  read from `theCode` (or `code`).
- A bad `propertiesToBeSearched` is 400 with WHO's text (it lists the accepted
  values).

### codeinfo

- **Input**: `code`, `flexiblemode`, `convertToTerminalCodes`. Unknown code → 404.
- **Output** (camelCase, JSON-LD): `{"@context", "@id", "code", "stemId"}` for a
  stem, e.g. `BA41.Z` →
  `stemId: "http://id.who.int/icd/release/11/2026-01/mms/1334938734/unspecified"`.
  **No title** (use `entity` with the id in `stemId`). For clusters the app also
  reads `stemCode` and `hasCausingCondition`
  (`src/coding/icd11Allowability.ts`).

### entity

- **Input**: `id` (numeric), optional `residual`, `include`.
- **Output** (JSON-LD, linearization URIs): `@context`, `@id`, `parent[]`,
  `child[]`, `browserUrl`, `code`, `source`, `classKind`,
  `postcoordinationScale[]`, `title` (`{@language, @value}`), `definition`,
  `exclusion[]` and, when the entity has them, `inclusion`, `indexTerm`,
  `codingNote`, `relatedEntitiesInMaternalChapter` and so on. A residual entity
  (`residual: "unspecified"` or `"other"`, or the `/unspecified`, `/other` child)
  carries its parent in `parent`. An unknown id is 404 or 400 with WHO's text.

### foundation_entity

- **Input**: `id`, optional `include`.
- **Output** (JSON-LD, foundation URIs `http://id.who.int/icd/entity/<id>`):
  `@context`, `@id`, `parent[]`, `child[]`, `browserUrl`, `title`, `synonym`,
  `definition`, `exclusion` and the fields the entity has.

### DORIS

- **Input**: `certificate`, the certificate JSON. A certificate WHO rejects → 400 or 500.
- **Output**: WHO's nine fields in camelCase — `stemCode`, `stemURI`, `code`,
  `uri`, `report`, `tabularReport` (13 `;`-separated columns per row, incl.
  `BER`), `reject` (boolean), `error`, `warning`. The meaning of each is in
  [the DORIS response section](../kb/doris-icd-api-and-va.md).

### CoDEdit

- **Input**: `certificate`.
- **Output** in camelCase: `report`, `tabularReport`, `issueIds` (a
  comma-separated string, not a list).

## Layer 6: what the coding screen receives (`OfflineDorisEditor`)

`createOfflineDorisEditor(engine, store, allowability)` answers the
`WorkspaceApi` DORIS calls with the types in `src/workspace/contracts.ts`,
the same ones the online client builds from the server. Since WP2
(`digitva-9cll.3`, 2026-10-30) the replies are the server's, built by
TypeScript ports of its rules over the WHO client (`src/workspace/whoEngineApi.ts`),
and a refusal is an `ApiError` with the server's status, code, message and body
(`{schema_version: 1, error: {code, message, fields?}}`).

| `WorkspaceApi` call | Editor method | Reply type | Built from |
| --- | --- | --- | --- |
| `searchDorisTerms(vaSid, query, {limit, subtreeUris})` | `onTerms` | `DorisTermsReply {schema_version, items: DorisTerm[], truncated, next_cursor:null}`; `DorisTerm {code, title, uri, release:"2026-01", matching_text, postcoordination, postcoordination_availability, related_maternal, related_perinatal, has_coding_note, extension, leaf?}` (`extension`: WHO chapter X; `leaf` only when WHO's reply carried `isLeaf`) | one `search` (`q="<text>%"`, the four flags, `subtreesFilter`, `limit` 20); port of `search_terms` (`dorisTerminology.ts`). Checks: query 2 to 80 characters, limit 1 to 20, subtree URIs as `valid_subtree_uris` (else 422 `INVALID_INPUT`) |
| `getDorisCodeInfo(vaSid, code)` | `onCodeInfo` | `DorisCodeInfoReply {schema_version, item:{code, title, uri, release:"2026-01", postcoordination, leaf, extension, ...}}` (`leaf` and `extension` describe the first stem: no `child` list on its entity means leaf); a single stem also has `postcoordination_availability` (0, 1, 2), `related_maternal`, `related_perinatal`, `has_coding_note`; an expression has `postcoordination:false` only | `codeinfo`, `codeinfo` per expression part, and `entity` of the stem (title when codeinfo has none, badges); port of `_codeinfo_item`, `expected_expression_uri`, `search_context_from_entity`. 422 `CODE_NOT_FOUND` for an unknown code |
| `checkDorisSelection(vaSid, code, uri)` | `onSelectionCheck` | same item | as codeinfo; the `uri` must equal the item's, else 422 `INVALID_SELECTION`; then `selectionRefusal` (port of `selection_refusal`) refuses an extension code or a category with children as any stem of the expression, also 422 `INVALID_SELECTION` (final codes only, `digitva-9cll.12`; each further `/` stem costs one codeinfo and one entity read). The picker's mandatory-stem check reads `postcoordination_availability` 2 from this reply |
| `processDoris(vaSid, role, rev, certificate)` | `onProcess` | `DorisProcessReply {schema_version, client_revision, icd_release, certificate (normalised), certificate_digest, result_digest, doris:{status,result}, codedit:{status,result}, who_notes, ucod_parts, process_token:"local-<uuid>"}` | port of `process_certificate`: personal-data check, `normalize_certificate`, `verify_certificate_codes` (`codeinfo` per coded condition), `who_safe_certificate`, `doris` then `codedit`, the envelope with the server's key checks (`completed`, `rejected` for DORIS `reject`, `malformed_response`, `unavailable`; never `timeout`), `ucod_parts` (titles from the certificate, else `entity`), `who_notes` |
| `getVaDefinitionForIcd(code)` | `primaryStem` | the stem that drives the VA cause | `codeinfo` of a `/` cluster (WHO's causing condition) |
| `saveInitial(vaSid, body)` | `save` | `{va_sid}`; allowability failures as `ApiError(400,"invalid_cod")` or `ApiError(422,"AGE_RESTRICTION_CONFIRMATION_REQUIRED")` | bundled allowability pack + `codeinfo` for clusters; provenance gets `packVersions` |
| `postcoordination`, `postcoordination-options`, `hierarchy`, `related`, `details` (picker guidance: `POST /api/v1/doris-clinical/<route>/<va_sid>` through the screen's requester, `guidance.ts` in the picker) | `onGuidance(route, body)` via `createGuidanceRequester` | the server's route bodies, each with `schema_version` and `release:"2026-01"`: `postcoordination {stem, axes[{id,label,required,instruction,allow_multiple,allow_multiple_values,options[{code,title,uri,has_children,block_uri}],subtree_uris,truncated}], other_postcoordination, truncated}`; `postcoordination-options {stem, axis_id, parent_uri, items, truncated}`; `hierarchy {selected, selected_expression, ancestors, siblings, children, matching_terms, related_maternal, related_perinatal, truncated}`; `related {selected, chapter, composite, terms[{code,title,uri,requires_postcoordination}], truncated}`; `details {selected, definition, coding_note, fully_specified_name, inclusions, exclusions[{code,title}], truncated}` | `codeinfo` + `entity` (+ `foundation_entity` for hierarchy related terms, `residual` for `/unspecified` stems); ports of `postcoordination`, `_stem`, `_axes`, `_option`, `postcoordination_options`, `hierarchy`, `related_terms`, `code_details` (`dorisGuidance.ts`). Caps: 12 axes, 12 options, 12 ancestors/siblings/children/related, 20 inclusions, 12 exclusions, `truncated` when cut. Budget: 48 reads and 10 s per request (`GUIDANCE_LIMIT` 503), two requests at once (`GUIDANCE_BUSY` 429). Body: exactly `schema_version` 1 and the route's fields, else 422 `INVALID_INPUT`. Any other path still throws `offline_server_unavailable` |

Errors, as the server's: 422 `INVALID_INPUT` (a request the server refuses, or a
certificate it refuses, with `fields: [{path, message}]` in the words of
`doris_certificate.py`), 422 `CODE_NOT_FOUND`, 422 `INVALID_SELECTION`, 503
`WHO_API_UNAVAILABLE` for any engine failure (`WhoUnavailableError` in the
client: the engine's own text is never kept). A WHO 404 is an answer ("no such
code"), not a failure.

**Personal-data boundary** (`src/workspace/piiBoundary.ts`, a port of
`vendor/who-icd11-api/src/privacy.rs`): a search text, code, URI or certificate
with a personal-data key (`name`, `informant_phone`, `address`, `aadhaar`,
`abha`, `identifiers`, `crs_number`, `mccd_number` and the rest of that list) or a
12-digit Aadhaar-like or 10-digit phone number is refused before any engine call:
422 `INVALID_INPUT`, `error.reason: "pii_boundary"`, and the path of the field,
never its value. WHO URIs are ignored by the number check. Digits of the Indian
scripts and Arabic-Indic digits count as digits.

**WHO client** (`src/workspace/whoEngineApi.ts`): `search` (the server's options
and `limit`, never `include=descendant`), `codeinfo` (404 is null; cached),
`entity` (a linearization, residual or foundation URI; cached), `title`
(codeinfo's title, else the stem entity's; cached), `runProcessor`. Caches hold
at most 128 entries each and live as long as the editor, which is one open case
screen; failures are never cached.

**Guidance routes** (`src/workspace/dorisGuidance.ts`, WP3 `digitva-9cll.4`): the call chain is
requester (`createGuidanceRequester`: POST, one of the five paths, the open case's id, then the
"still allowed" check) → `OfflineDorisEditor.onGuidance` → `createGuidance(...).answer` (body check, personal-data
check on every string, capacity of two, one read budget per request) → the WHO client. Engine reads
per request are `codeinfo` (cached) and `entity` / `foundation_entity` (cached, so an entity read twice in one
request or across requests costs one engine call). The server's budget counts each read the port asks for, cached
or not, so `GUIDANCE_LIMIT` fires at the same read as on the server; the engine sees fewer calls. Most engine calls
per request in the 485 recorded operations (cold caches): `postcoordination` 46 (`PA50.Z`), `hierarchy` 26 (`NC72`),
`related` perinatal 16, `postcoordination-options` 15, `related` maternal 9, `details` 9. A guidance failure of the
engine is 503 `WHO_API_UNAVAILABLE` with the guidance wording ("WHO ICD-11 guidance is unavailable."), not the terms
wording. Differences from the server: a personal-data hit is `INVALID_INPUT` with `error.reason: "pii_boundary"`,
decided before the code grammar; `chapter` that is not a string is `INVALID_INPUT` (the server raises); no 32 KB
body check; the 10-second budget runs on `performance.now`; a URI with an empty query (`...?`) is refused.

**Deliberate differences from the server.** The process token is
`local-<uuid>` (nothing signs offline). `certificate_digest` is the server's
(SHA-256 of the canonical normalised certificate); `result_digest` is SHA-256 of
the canonical `{icd_release, engine, doris, codedit}` where `engine` names the
engine release, the DORIS rule engine and the rules (no WHO image digest
exists on the phone). The engine has no timeout, so the envelope status
`timeout` never occurs. A title lookup outage skips the rest of that reply's
titles instead of the server's 60-second cross-request memory. The engine is
asked for 20 hits whatever the caller's limit, and the caller's limit cuts the
list, so `truncated` agrees with the server's. A `Part2: null` that crashes the
server's `verify_certificate_codes` is simply skipped. `primary_stem` is no
longer in the codeinfo item (the server never sends it); `primaryStem()` answers
it.

**Provenance on save**: `provenance.packVersions` is `{icd11_engine,
doris_engine, doris_rules, icd_release}` = `2026.10.29.1`, `1.1.176`, `1.2.0`,
`2026-01`. The engine release is the constant `ENGINE_PROVENANCE.icd11_engine` in
`whoEngineApi.ts`, because the JS bundle has no other way to learn which engine
the APK ships; a jest test fails when it differs from `ICD11_ENGINE_VERSION` in
`scripts/icd11-engine.env` (which the release workflow also checks against the
pinned archive). The DORIS versions are those of the bundled data files
(`DORIS_v2.1_1.2.0`). `src/sync.ts` (`offlineCodingBody`) sends it as the
contract's `pack_versions` and removes it from `provenance`, whose keys the
server fixes (`app/services/offline_coding_import_service.py`); a coding with no
allowability provenance is not sent.

Not produced offline (optional in the contract): nothing; `who_notes` and
`ucod_parts` are now built as the server builds them.

## Tests

Each layer has its own, and none is "verified by the layer above" (`.tasks/2026-10-29-android-offline-doris-parity.md`, "Test coverage").

| Layer | Tests | Run with |
| --- | --- | --- |
| Bridge (`Bridge.cs`) | Parity kit `scripts/icd11-parity`: every op and argument against WHO's container, field names compared case-sensitively; `calls.json` holds the error paths and the bounds (`limit` valid and invalid, `limit` with `flatResults` false, `include` with `descendant`) | `scripts/icd11-parity/run_phone.sh` on a phone, on every engine build (targeted: `ENGINE_SO`, `STAGED`, `CERTIFICATES`) |
| Shim (`shim.c`) | `scripts/icd11-parity/jni_smoke.sh`: the shim compiled unchanged, its JNI functions called with a fake `JNIEnv` (`jni_smoke.c`) against an old library (no `digitva_icd11_call`) and the new one. Old: `load` must return 3 (twice), nothing can be initialised or called afterwards (`initEngine` 2, `callOp` NULL, status untouched), no engine text on stdout or stderr (10 checks). New: `load` 0/1/2/3, `initEngine`, `callOp` for every op and each refusal (unknown op, bad JSON, `limit` bounds, `limit` with `flatResults` false, `include` descendant, mistyped argument, certificate that is not JSON), NULL and failed-allocation paths, every string released, no engine text on stdout or stderr (30 checks). No APK, nothing installed | `ENGINE_OLD=… ENGINE_NEW=… STAGED=… scripts/icd11-parity/jni_smoke.sh WORK_DIR` |
| Kotlin (`EngineHost`, `Icd11Service`) | JVM unit tests in `android/src/test` (JUnit 4, no Robolectric): `EngineHostCallResultTest` (9: `bad_op`, `not_initialized`, `engine_status`, success), `Icd11ServiceTest` (20: 250,000-character cap, `native_error`, `too_large` fallback, op-name shape, priority order and init gate) | `./gradlew :digitva-icd11:testReleaseUnitTest` from the prebuilt Plus project; the Plus release workflow runs it after prebuild and before `assembleRelease` |
| `offlineEngine.ts` | jest `__tests__/offline-engine.test.ts` (every method, options omitted when unset, `limit`, re-init, error codes) | `npm test` |
| WHO client and DigitVA rules (WP2) | jest, 100% of lines and branches of the new modules: `who-engine-api` (options sent, caches, failure mapping, pinned versions), `who-text-pii`, `doris-certificate`, `doris-terminology`, `doris-processing`, `offline-doris`. **Golden replay** `offline-who-golden`: a fake engine maps each `call(op, args)` to the WHO REST request the server made and answers only from the fixtures of `scripts/icd11-golden` (a call the fixture did not record fails); the port must produce the server's recorded reply exactly: 238 of 238 search, 182 codeinfo/selection-check operations and (WP3) 485 of 485 guidance operations of the 44 postcoordination fixtures (44 postcoordination, 77 options, 91 each of hierarchy, related maternal, related perinatal and details), 173 of 173 DORIS. The three golden sets are owner-approved (2026-10-30) and frozen (`scripts/icd11-golden/README.md`); their fixtures carry the `leaf` and `extension` flags and the final-code refusals. WP3 unit tests `doris-guidance` (100% of lines and branches of `dorisGuidance.ts`: caps, truncation, the 48-read budget and 10-second deadline, `GUIDANCE_BUSY`, every refusal, X-chapter `other_postcoordination`, uncoded leaves, 404 skips of related terms, details with exclusions, the editor's error mapping, the requester's routing and the picker's own client and parsers over it) and the route test in `offline-coding-route` | `npm test` |

Not covered by a JVM test, because they need the Android runtime: the Binder handler in `Icd11Service` and its `Bundle` copy (`toBundle`, `toMap`), `EngineHost.init`, `EngineData` and the Expo module. No automated test covers those paths yet: the phone parity and JNI runs drive the engine library and the shim directly, not this Kotlin, so they are exercised only when the app itself runs on a phone. An instrumented or Robolectric round-trip test is the open item (bead `digitva-9cll.6`). The Kotlin code the tests reach was split into small functions for this (`callResult`, `Icd11Service.boundReply` and `answerWith`, `JobScheduler`). `EngineJni` is now only the JNI declarations (nothing to test on the JVM); the shim's `load` refusal is covered by the JNI smoke.

## CI check of the staged engine

`.github/workflows/collect-plus-release.yml` pins the engine release (`ICD11_ENGINE_TAG`, `ICD11_ENGINE_SHA256`, which must match `scripts/icd11-engine.env`). After `expo prebuild` has staged the library, the step "Check the staged engine exports the functions the shim loads" runs the NDK's `llvm-nm -D --defined-only` on `jniLibs/arm64-v8a/libdigitva_icd11.so` and fails the build unless `digitva_icd11_init`, `digitva_icd11_call` and `digitva_icd11_free` are all exported (NativeAOT writes them as `T digitva_icd11_call@@V1.0`). A stale pin therefore fails the release before the JVM tests and the APK build, not on a phone.

Local builds that stage from `private/icd11-offline-spike` (or `DIGITVA_ICD11_SPIKE_DIR`) get no such check: with an old library the app builds, `load` returns 3 and the engine reports `load_failed`. Stage from the release archive (`DIGITVA_ICD11_ENGINE_ARCHIVE`) or put a library from `engine-src/build.sh` into the spike folder.

## Building the engine

`engine-src/build.sh OUT_DIR` compiles `Bridge.cs` and WHO's assemblies with NativeAOT for `linux-bionic-arm64`. It runs on macOS and on Linux x64:
the host picks the NDK's prebuilt folder and the sha256 tool. The inputs are `ICDAPI_DIR` (WHO's `/usr/share/icdapi` from `whoicd/icd-api:2.6.0`),
the .NET SDK pinned in `engine-src/global.json` (the one place for the version; `rollForward` is `latestPatch`) with the ASP.NET Core shared
framework it ships with (`build.sh` finds it from `dotnet --list-runtimes`, or `ASPNET_DIR`: `setup-dotnet` on CI adds a newer bare runtime beside the SDK, so the host version does not name the SDK's own framework), and NDK 28.2.13676358 (`ANDROID_NDK`). `Bridge.csproj` takes the
WHO assembly folder and the ASP.NET folder as the MSBuild properties `IcdApiDir` and `AspNetDir`; their defaults are the Mac paths the build used
before. `build.sh` regenerates `rd_gen.xml` with `gen_rd.cs` on every run.

Checked on the Mac on 2026-10-30: the portable `build.sh` reproduced the library of release `2026.10.29.1` (sha256
`8bfdc258f0e2c316a50656bc9d61ff07531d187f8855d9c5fd1ce4c6c109c718`) and left `rd_gen.xml` byte for byte unchanged.

`.github/workflows/icd11-engine-build.yml` (manual, and on pull requests and pushes to `main` that touch `engine-src`, the packaging script, `icd11-engine.env`,
`stage-engine.js` or the workflow) does the same on a hosted `ubuntu-24.04` runner with read-only permissions:

1. installs the SDK from `global.json` into a fresh folder and NDK 28.2.13676358;
2. pulls `whoicd/icd-api:2.6.0@sha256:1b77eb6d...ada1b7c` (the digest `vendor/who-icd11-api` pins) and copies `/usr/share/icdapi` out;
3. runs `build.sh`, then fails if the regenerated `rd_gen.xml` differs from the committed one;
4. with the NDK's `llvm-nm` and `llvm-readelf` fails unless the library is AArch64, exports exactly `digitva_icd11_init`, `_call` and `_free` as its `digitva_*` symbols
   and has every LOAD segment aligned to a multiple of 16 KB;
5. downloads WHO's data from its CDN and checks every file against the sha256 values of `vendor/who-icd11-api/src/bootstrap.rs` (they are copied into the
   workflow), takes the three bundle files from the image, and packages the archive with `scripts/package-icd11-engine.sh`;
6. uploads the library and the archive as a workflow artifact kept 7 days, with both sha256 values in the job summary;
7. reports, without failing, whether the library and the other archive files equal those of the release `collect-plus-release.yml` pins. That workflow
   records only the archive's sha256, so the step downloads the pinned (public) release and compares the unpacked files. The archives themselves are not compared:
   macOS bsdtar and GNU tar write different headers (and `touch -t` uses the local time zone) for the same files.

Not covered by CI: the parity kit (`scripts/icd11-parity`, every op against WHO's container) and the shim's JNI smoke (`jni_smoke.sh`) run the library on an arm64
Android phone over adb, and a hosted runner has no such device and no KVM for an arm64 emulator. They stay manual, on a phone, for every engine build. A green
run shows that the build completes and that the exports and alignment are right, not that the engine behaves or that it equals the release. CI never publishes: the release, its tag and the
pin in `collect-plus-release.yml` stay with the owner (`scripts/publish-icd11-engine.sh`). The engine builds on CI (`digitva-9cll.10`). The CI library is not byte-identical to the
Mac-built release (build ID, `.comment` and about 1.6 KB of `.rodata` differ; `digitva-9cll.11`), so the Mac-built release stays the pinned one until that is resolved.

## Release

Engine release `icd11-engine-v2026.10.29.1` is the first without the four single-argument exports. Its inputs are all public: WHO's assemblies from `whoicd/icd-api:2.6.0` (digest `sha256:1b77eb6dc43e0c65a12e9e9340ad178493c93488e728d0d936507cc57ada1b7c`), WHO's data files (byte for byte the files of `icd11-engine-v2026.10.25.1`), and this repository's `engine-src`. It was built on the Mac and is still the pinned one: the CI build differs in bytes (see above). Release `2026.10.25.1` stays published but no app built from this tree can use it. The archive is packaged by `scripts/package-icd11-engine.sh` and published by the owner with `scripts/publish-icd11-engine.sh`; the commit that pins the new tag and sha256 must land together with the publish, since the Plus CI build fails until the release exists.

## Known gaps

Tracked under `digitva-9cll`: the Collect Plus build has not yet run the WP2
and WP3 flows on a phone (the emulator run confirms the engine's real replies
against the ports). To confirm for the guidance routes: the status the engine
gives for an entity WHO has no coded form of (the related-terms skip needs a
404, as WHO's REST gives; any other 4xx would show as "guidance unavailable"),
Binder time of a Build (up to about 46 engine calls cold) against the 10-second
budget, and that the picker's two parallel requests (Build with its details)
stay inside the capacity of two.
