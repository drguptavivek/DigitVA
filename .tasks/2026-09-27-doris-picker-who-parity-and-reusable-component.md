# DORIS condition picker: WHO postcoordination parity and reusable component

Status: done 2026-09-27 (commits 3cd435a, 492149f); clinical visual check and mobile auth remain open
Priority: P1
Created: 2026-09-27
Depends on: nothing for the web work; mobile use of the picker depends on
API token auth (SSO/OAuth2 record `.tasks/2026-09-26-project-sso-oauth2.md`,
deferred by the owner: "SSO is for later").

## Owner asks (2026-09-27)

1. Assess the DORIS-inspired COD picker against WHO's page and improve it.
   Mandatory postcoordination must come first.
2. Match WHO's axis grouping and wording seen for `2A01.0Y`: "Object or
   substance producing injury", "Specific anatomy", "Histopathology", "Has
   manifestation", each with "(use additional code, if desired.)", and an
   "Other postcoordination?" group.
3. Smaller, more compact fonts in the modal.
4. Make the picker a reusable unit that a web app or a JS mobile shell
   (React Native, Cordova) can use. **Most important: it must work well
   inside DigitVA and the planned DigitVA coder mobile app.**

## WHO reference evidence (icd.who.int/doris/workspace, 2026-09-27)

Captured in the built-in browser. The postcoordination builder opens from
the "+" next to a matching term (Details panel), not from the code chip.

- `2A01.0Y` (no required axis): sections in WHO order, each headed
  `Label (use additional code, if desired.)` with a "search in axis" box
  and the root options; uncoded roots ("Meningiomas, benign") show a `▷`
  and expand inline. Last section is "Other postcoordination? (use
  additional code, if desired.)" with only a search box.
- `BD54` (required axis): "Has causing condition (code also)" is first,
  then Laterality, Specific anatomy, Has manifestation, then "Other
  postcoordination?". Details also show "Related categories in maternal
  chapter: ... (JB64.4/BD54)" as the exact composite, and the coding note.
  A code-typed search shows Details without the builder.
- `NC72.7`, `NC71.Z` (injury): Laterality, Fracture subtype, Fracture open
  or closed, Joint involvement in fracture, Associated with. Clicking `▷`
  on an uncoded node ("23 External causes") expands it inline; clicking
  the uncoded title only highlights it. No alert was observed.
- ECT 1.8 bundle (`icdcdn.who.int/embeddedct/icd11ect-1.8.js`): axis
  labels are `upperFirst(lowerCase(axisId))`, so "Object or substance
  producing injury" is the WHO axis id itself. "Other postcoordination?"
  is synthesised by ECT as an open-ended search over the X chapter
  (foundation 979408586), shown only for MMS category stems outside
  chapter X, and is not a wrapper around optional axes.

## Assessment of the current state (verified 2026-09-27)

- Required-first ordering already exists: `app/static/js/doris_postcoordination.js`
  sorts axes by `required` before rendering (`renderPostcoordination`).
- Axis labels in `app/services/icd11_postcoordination.py` (`_axes`) split
  the axis id's camelCase and capitalise, which is the same rule ECT uses.
  No name table is needed. Instruction text already matches WHO
  ("code also" / "use additional code" / "use additional code, if desired").
- Gaps against WHO: no per-axis search box; no "Other postcoordination?"
  open-ended search; heading punctuation differs; uncoded folder label
  "(uncoded hierarchy block)" is noisier than WHO's plain `▷` node.
- Portability: the picker is three IIFEs on `window.DigitvaDoris*`
  (`doris_search_modal.js`, `doris_postcoordination.js`,
  `doris_interval.js`), uses Bootstrap utility classes, appends its backdrop
  to `document.body`, hard-wires an `htmx:beforeSwap` close hook, and reads
  CSRF from `app.dataset.csrf`. The JSON routes it calls (`terms`,
  `codeinfo`, `postcoordination`, `postcoordination-options`, `hierarchy`,
  `related`, `details`, `selection-check`) exist on both the public and
  clinical APIs and are the durable reusable surface.
- React Native cannot render DOM; a web module reaches RN only through a
  WebView. Cordova is a WebView. The planning docs
  (`docs/planning/coder-api-first-workflow-plan.md`,
  `docs/planning/coder-web-and-api-contracts.md`) already say mobile
  consumes the JSON API and that mobile auth is not implemented.

## Scope

### A. WHO parity in the postcoordination panel (web, DigitVA-first)

1. **Headings.** Required axes first (already). Heading becomes
   `Label (instruction.)` with WHO punctuation; the multiplicity hint moves
   to a muted suffix. Optional axes stay as their own sections in WHO
   order; do not wrap them in a group.
2. **Scoped search (one feature).** Per-axis "search in axis" boxes and
   the final "Other postcoordination?" section are the same thing: a WHO
   MMS search restricted to a subtree (the axis root URIs, or the X-chapter
   root). The `terms` route does not forward WHO's `subtreesFilter`
   today (checked 2026-09-27), so add exactly one bounded `subtree_uris`
   parameter to `terms`, validated against the stem's axis roots or the
   X-chapter root, and use it for both. No second endpoint.
   The open-ended section appears only for MMS category stems outside
   chapter X, mirroring ECT. Selected codes join the expression as
   extension codes in WHO order.
4. **Uncoded folders.** Keep expand-only. Render as a `▷` node with the
   title and no select control; drop the "(uncoded hierarchy block)"
   suffix. No alert, matching WHO.
5. **Maternal/perinatal related panel** (open handoff question, now
   answered by evidence): show the exact WHO composite (`JB64.4/BD54`) as
   the primary related choice, above the broader category list.

### B. Density and typography (CSS only)

- `app/static/css/doris_demo.css`: modal base `0.875rem` to `0.8rem`, axis
  headings `0.78rem`, option buttons `btn-sm` at `0.75rem` with tighter
  padding, details/coding-note line height `1.3`, list-group rows `.15rem`
  vertical padding. One line item; do not let it grow.

### C. Reusable picker module (smallest step that DigitVA needs)

Extract the picker into one framework-free ES module,
`app/static/js/digitva_icd11_picker.js`, exporting
`createIcd11Picker({mount, transport, onSelect, onClose, release})`:

- No globals. `transport` is an object the host supplies:
  `{post(path, body) -> Promise<json>}`. The Help page and clinical editor
  pass a transport that adds `X-CSRFToken` and same-origin credentials; a
  mobile host later passes one that adds a bearer token. The picker never
  reads the DOM for CSRF.
- `mount` is the element the modal renders into; the backdrop is a child of
  `mount`, not `document.body`. The HTMX close hook moves to the clinical
  host page, which calls the returned `close()`.
- `onSelect(choice)` returns the same server-verified choice shape the
  chips use today (code, title, WHO URIs, release). The selection-check
  call stays inside the picker so every consumer gets the same validation.
- Bootstrap classes stay for now. Shadow DOM and self-contained CSS are the
  next rung, added only when a consumer outside DigitVA templates needs
  style isolation.
- `doris_demo.js` and `doris_clinical.js` become thin hosts. The
  postcoordination module folds into the picker. `doris_interval.js` stays
  a sibling module the host wires to its certificate line: onset-to-death
  belongs to the line, not to code selection, and a mobile host must not
  inherit it. No `window.DigitvaDoris*` remains.
- Build: plain ES module served as today; add a one-line `<script type="module">`
  in both templates. No bundler. If the mobile app needs a single-file
  bundle, that is a later `esbuild` line, not now.

### D. Mobile path (design only, no code now)

- **Cordova / any WebView shell:** load the same module inside the WebView
  with a transport that injects the app's auth header. Works once bearer
  auth exists.
- **React Native:** host the module in `react-native-webview` and bridge
  `onSelect` through `postMessage`; the host RN screen owns the certificate
  lines. A native RN picker against the same JSON routes is a separate
  later task if the WebView path proves clumsy on device.
- **API:** freeze the eight picker JSON shapes in
  `docs/kb/doris-certificate-ui-contract.md` as the mobile contract. The
  authenticated `POST /api/v1/icd11/*` routes for mobile, bearer tokens and
  CORS are blocked on the deferred SSO/OAuth2 work and are out of scope here.

## Files

- `app/services/icd11_postcoordination.py` (open-ended X-chapter option,
  axis-scoped search if needed)
- `app/static/js/doris_postcoordination.js`, `doris_search_modal.js`,
  `doris_interval.js` -> `app/static/js/digitva_icd11_picker.js`
- `app/static/js/doris_demo.js`, `app/static/js/doris_clinical.js` (hosts)
- `app/static/css/doris_demo.css`
- `app/templates/help/pages/doris-demo.html`,
  `app/templates/**/_doris_certificate_editor.html`
- `tests/routes/test_doris_clinical_ui.py`, `tests/routes/test_help_doris_demo.py`
  (static assertions on module names and globals will break; update them)
- `tests/services/test_icd11_postcoordination.py` (open-ended section and
  axis-scoped search)
- Docs: `docs/policy/doris-cod-workflow.md` (grouping and uncoded rule,
  before implementation), `docs/current-state/doris-cod-workflow.md`
  (module layout), `docs/kb/doris-certificate-ui-contract.md` (picker
  module API and the frozen JSON shapes).

## Migration and data impact

None. No schema, endpoint shape or stored payload changes. Selected chips keep
the same provenance shape.

## Risks

- Axis-scoped search may need a new bounded route if `terms` cannot be
  scoped to root URIs; keep it under the existing guidance budget.
- Moving the backdrop into `mount` changes stacking; verify z-index inside
  the clinical page layout and the Help page.
- Removing globals breaks any template or test that references
  `window.DigitvaDoris*`; grep before deleting.
- The open-ended X-chapter search can return large sets; bound it like the
  other guidance calls and mark truncation.
- Mobile parity is not proven until bearer auth exists; do not claim it.
- WHO's search row for `NC72.7` carried the "Mandatory postcoordination"
  badge although every axis in its builder was optional; `BD54` carried
  the same badge and did have "code also". The badge is not driven by
  `requiredPostcoordination` alone. Compare the local API's
  `postcoordinationAvailability` for `NC72.7` with `_axes()` output before
  trusting the required icon in DigitVA search rows.
- The uncoded-folder check clicked a node title inside an axis, not the
  top "Select" button on an uncoded tree node; the design (no select
  control on uncoded nodes) sidesteps both cases.

## Verification

- Side-by-side against WHO's page for `2A01.0Y` (section order, heading
  wording, per-axis search, "Other postcoordination?", uncoded
  histopathology folder expand-only) and `BD54` (required axis first,
  coding note, `JB64.4/BD54` maternal composite).
- Picker mounted in both the Help page and the clinical editor from the
  same module, no `window.DigitvaDoris*` in the served page, HTMX swap
  still closes it in the clinical editor.
- Select `2A01.0Y` with one optional anatomy, `BD54/5A14`, and
  `1B12.2&XA0G74`; confirm the footer expression and chip provenance.
- Focused Docker DORIS suite on `minerva_test_pii`, Ruff, `node --check`
  on the new module, mobile-width (375px) screenshot of the modal.

## Order

1. Evidence: done (see WHO reference evidence above).
2. Policy line in `docs/policy/doris-cod-workflow.md`.
3. A (headings, per-axis search, open-ended section, uncoded label) + B (CSS).
4. C (module extraction) as its own commit.
5. D stays a doc update in the KB contract.
