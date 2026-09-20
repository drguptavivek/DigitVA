# Handoff

Updated 2026-09-20. Two commits today; the second is described first because
it corrects the first.

**Machine drafts are no longer served** (`digitva-4kj`, `digitva-we0`, both
closed). `b6d2f4a9c1e7` seeded 214 LLM-authored strings as `source='imported'`,
indistinguishable from workbook-sourced text, so approving a locale blessed
both at once. `source` gains a third value `machine`; `c1a4b6e8d3f2` relabels
exactly those rows, matching on text so an administrator's correction is left
alone; `export_translations` and coverage exclude them, so the form falls back
to English per string while the panel still lists them with an **Accept**
button that promotes one to `edited`. Precedence `edited` > workbook
`imported` > `machine` needed no importer change: only `SOURCE_EDITED` was ever
special-cased. In XLIFF a machine row is `initial` with
`subState="digitva:machine"` carrying its draft, not `translated` — review
caught that it was being handed to CAT tools as finished work. An unmapped
`source` now understates rather than claiming translated. `d2b5c7f9e4a3`
renames the CHECK constraint, which the naming convention had doubled and
truncated to `ck_mas_instrument_locales_ck_mas_instrument_locales_act_5121`.
Verified: 32/32 seeded rows relabelled in a two-locale fixture, an `edited` row
survived a relabel round-trip while 31 returned to `machine`, a locale with 19
machine + 1 edited row served exactly 1 item with zero leakage, `pg_constraint`
reports the intended name. Full suite **1,656 passed**, `PYTEST_EXIT=0`.

One caveat written into policy: a machine draft exported and handed back
*untouched* with `--as imported` becomes servable, because the importer judges
the hand-back rather than each segment. Prefer the panel's per-string Accept.

Updated 2026-09-20 (translation management: de-gating, approval lifecycle,
seeded layer strings). Three related changes, all on `e1b6c9a3d7f4`.

**1. The importer no longer reads a policy document** (`digitva-dsj`, closed).
`SOURCE_POLICY_DOC`, `DocumentedSource` and `documented_sources()` are gone.
Any readable workbook may be imported for any locale; `_resolve_workbook`
still contains the path to the repo root or the system temp dir. The
"Translation sources" table in `docs/policy/va-form-project-configuration.md`
stays as provenance for humans and no code reads it. `--cross-check` survives
as a plain dry run. `language_name` now comes from the workbook's own
`field::Name (code)` header, then `--language-name`, then the locale code.
Decided by the owner: importing a questionnaire source is a reviewed one-time
activity, and the runtime path for changing translations is the admin string
editor, not a re-import.

**2. Per-locale approval lifecycle** (`digitva-j23`). `mas_instrument_locales`
gains `lifecycle_state` (`draft`/`in_review`/`approved`),
`approved_by_user_id` and `approved_at`, plus CHECK constraint
`ck_mas_instrument_locales_active_requires_approved`: only an `approved`
locale may be `is_active`, and leaving `approved` while active is refused.
Migration `a3f7c1d9e6b4` backfills every locale to `in_review` and
`is_active=false` — **a deliberate mass-deactivation**, per the owner's
decision that nothing unreviewed is served. Because `upgrade` clears
`is_active`, it first captures the prior active set into
`_mig_a3f7c1d9e6b4_prior_active` and `downgrade` restores from it; without
that the thirteen active locales would have been unrecoverable. `_mig_` is
excluded from drift detection in `app/schema_filters.py`, prefix-based so a
table the app should own cannot hide behind the rule. New
`set_locale_lifecycle_state`, CLI `instrument-translations lifecycle`
(`--approved-by` required for `approved`, since the CLI has no session),
route `POST .../<instrument_code>/<locale>/lifecycle`, panel badges with
**Activate** disabled until approved. Coverage still decides nothing.

**3. DigitVA-authored layer strings seeded** (migration `b6d2f4a9c1e7`).
The layers add questions no workbook carries — consent mode and its choices,
the medical-certificate upload, the shared "Medical and death documents"
heading, the two image-count hints, narration language and its choices, and
the two ABHA fields. 214 strings across twelve locales, as literals; the
migration reads no workbook and imports no application code. Khasi is
deliberately absent (no reliable source; a wrong label is worse than a gap
that falls back to English) and ABHA is seeded for the seven Indian locales
only. Rows land as `imported`, so a real translated workbook or an XLIFF
hand-back outranks them and an administrator's edit is never overwritten.
**These are machine translations awaiting a speaker's review** — which is what
the lifecycle in (2) is for.

Verified on a throwaway database (never `minerva_test`/dev): the full chain
reaches a single head `b6d2f4a9c1e7`; two active locales were deactivated on
upgrade, captured, and **restored on downgrade**, with the recovery table then
dropped; the seed inserts 20/12/16 rows for hi/fr/sw and 0 on an empty
database; `downgrade` deleted 46 of 48 seeded rows and preserved both rows a
human had touched; two consecutive upgrades leave the `edited` row unchanged.
Full suite: **1,641 passed**, `PYTEST_EXIT=0` read from pytest itself,
including `tests/migrations/test_schema_drift.py`. One full run in between
failed `tests/test_admin_api.py::test_odk_site_mappings`, which passed 45/45
three times in isolation and in three other full runs — the known
`digitva-ssi`, now with a second data point that weakens its load hypothesis
(see its notes). Five pre-existing test fixtures across `tests/services/test_instrument_translation_xliff.py`,
`tests/services/test_web_form_instruments.py` and
`tests/routes/test_form_options_api.py` built an active
`mas_instrument_locales` row directly and needed `lifecycle_state='approved'`
added to stay valid against the new CHECK constraint; behaviour unchanged.

**Do these next, in this order.** Two of them are consequences of this work
that were deliberately left open rather than fixed in scope:

* `digitva-dms` (P2) — the 214 seeded strings reach **only an
  already-deployed database**. Verified: the migration inserts 0 rows on an
  empty one, because locales are created later by an operator import, and
  alembic will never run it again. A fresh install therefore never gets them
  and has no documented path to. Needs the strings in a committed data file
  plus an idempotent `flask instrument-translations seed-layers`.
* `digitva-dqh` (P2) — the approval gate holds for a *new* locale and is
  defeated for an *existing* one: an admin can re-import a workbook or push an
  XLIFF hand-back into a live, approved locale, rewrite every string, and it
  stays approved and served. Needs an owner decision (knock it back to
  `in_review`, or write down that bulk rewrites of a live locale are trusted).
* Operator step on this dev database after upgrading: re-import each language
  (eight of thirteen land within 3-34 items of complete), then approve and
  activate the ones a speaker has reviewed. Sizing table in
  `docs/current-state/admin-and-setup.md`.

Also filed today and out of scope: `digitva-ssi` (second occurrence, notes
updated), and from earlier sessions `digitva-c48`, `digitva-cal`,
`digitva-ybt`, `digitva-3jj`.

Previously: `digitva-thr` is closed: all four work packages landed, the
social autopsy layer is authored, and layer questions can be translated. On
top of the previous session's `e0164d9`; `origin/main` is at the commit that
updated this file, working tree clean before this session's uncommitted
change above.

## What landed

| Commit | What |
| --- | --- |
| `1e94b4c` | Layer questions enter the translation reference via a generated artifact; the 0.95 coverage activation gate and `--force` removed; per-extension coverage; the choice-code convention recorded |
| `78757d4` | The social autopsy layer authored from ND01 verbatim (`sa01`-`sa19`), plus an expression-tokenizer fix: a backslash is now an ordinary character, matching XPath 1.0 |
| `702f518` | The importer learns the packed-cell conventions ND01 actually uses (newline, `" / "`, `English (Translation)`), and treats an unsplittable interleaved cell as untranslated |
| `3a17d8c` | Viewer roles wired to routes; two scope leaks closed; per-unit coding gates; migration `a40c38e73af4` |
| `b8d05ef` | WHO 2026 annex ICD-10 ranges as the `WHO_2022_VA_2026` scheme; migration `c5f2a8d1e9b3` |
| `926c212` | Web intake configurability, organization-API ancestors, PII field registry; migration `b8e3d1f7a2c4` |
| `e16ea30` | `role_required` raises at decoration time on an unknown role name |
| `6ea5420` | `R10` selectable, bucketed to `VAs-06.01` |
| `b247950`, `ae6d6fa`, `5c5473a`, `8f0f672`, `98b9816` | Policy and task records (below) |
| `455eb34`, `d08fce7`, `63a3dcb`, `479b698`, `44ffbeb` | Tooling hygiene: Dolt log and backup pointer untracked, beads prefix fixed, droppings ignored |
| `4b0e308` | PII set fails closed per form type; PII cache versioned on `mas_field_display_config` `(count, max(updated_at))`. No migration. |
| `711710e` | Policy: what a second form type must pass before it goes live |
| `b159e53`, `e0d2300`, `4a7c623` | `tests/test_route_auth_coverage.py`: every `url_map` endpoint must carry `role_required` or `login_required`, or sit on an explicit allowlist; public set settled |
| `89c1b79` | CLAUDE.md trimmed; subagent working model written down |
| `ae8ace5` | `GET /api/v1/organization/<project_id>/form-options`; four `web_intake_*` columns on `va_project_master`; migration `f2a9c4d7e1b3`; intake form takes locale and instrument from the project |
| `10d38c8` | Fifteen migrations importing MV builders pinned; any new application import in a migration fails the suite |
| `705021e` | Closed projects resolve no grant of any scope; one shared predicate in twelve resolvers plus the redaction check |
| `1369c0e` | Form types are layers on the standard instrument; intake resolves `instrument_code`, so `WHO_2022_VA_SOCIAL` renders |
| `5b22094` | Projects admin panel reads and writes the four `web_intake_*` form options; project POST accepts them through the same validator as the PUT. No migration. |
| `742ea9d` | Web form locale is `en` everywhere plus what the instrument has translations for (`app/services/web_form_instruments.py`); interviewer picks a working language, remembered in the browser. No migration. |
| `10267ee` | `project_pi` role gate is an EXISTS (`VaUsers.is_project_pi`), closing `.tasks/auth-decorator-followups.md` item 3 |
| `32ea0fb` | The web-capture configuration plan and the register of every decision taken 2026-09-19 (Q6, P2, W6, extensions, base_instrument_code, D2, D3, D5, D6, C1/C4 deferred, annex follow-ups, translations delivery, API first) |
| `2b4b869` | Nine deployed project workbooks under `docs/kb/WHO_VA_2022_Docs/` with a README (form id, version, languages, checksum) |
| `0fb8d75` | End-to-end test: a web submission in a tree project routes to its unit and reaches only its coders |
| `ab663ca` | Every decision recorded in the document that raised it |
| `610f55d` | The 16 WHO_2022_VA_2026 overrides that depart from the annex documented and pinned by a file-based test; annex follow-ups 4-7 filed as `digitva-2g7`, `28a`, `jt3`, `2c1` |
| `5043448` | Web form type, welcome note, death-summary flag as project settings; `base_instrument_code` on `mas_form_types`; defaults for a new web project; migration `c3e8b5a1f4d2` |
| `fe498e6` | Web-capture readiness: nine checks as JSON, Projects panel badge and list, `flask web-intake readiness` |
| `383acef` | French, Portuguese, Arabic, Swahili and Spanish sourced from WHO's multilingual V2.0 form (`2022whova_xls_form_for_odk_multilingual.xlsx`); thirteen locales active on dev |
| `2af0885` | XLIFF 2.0 export and import per locale as the industry-standard interchange (resource ids `question.<name>.<field>`, `choice.<list>.<name>.label`); English fallback pinned |
| `8a4791b`, `d6902f3` | Hindi sourced from the ND01 ICMR form (the most commonly deployed); every DigitVA layer it carries inventoried in policy (social autopsy, death-certificate images, medical-record images, narration audio and image, intake screen, geography) |
| `0dd80ea`, `347bbf1` | Translation-sources parser stops at its table's end; tests read the Hindi source from policy. `d6902f3` and `0dd80ea` were pushed on a red targeted run (exit status of `tail`, not pytest); `347bbf1` corrects it and the full suite is green on that tree |
| `7bf1d5f` | The vendored WHO VA bundle rebuilt from its own source. The bundle committed in `926c212` was not built from the source beside it: three fixes in `src/` had never reached a browser (a language-dropdown `accessibilityRole` of `button` where source says `option`, and React keys on the form and preview roots). Found by a reproducibility check before layering on top |
| `d04a9f8` | DigitVA layers become conditional on the project's `enabled_extensions`; `medical_records` named as the eighth extension with `web_intake_medical_records_enabled` (migration `e1b6c9a3d7f4`); `ds_available`/`md_available` gate questions and a separate `consent_mode` question. `digitva-thr.1`, `digitva-thr.2` closed |
| `d497e0e` | Instrument translations stored, managed and served: `mas_instrument_locales`, `map_instrument_translations`, importer from one documented source workbook per language, admin panel, `GET /api/v1/instruments/<code>/translations/<locale>`, client-side apply in the intake page; migration `a7d4f1c9b0e6` |

Migration chain is linear: `f1c6a9d3e7b5 -> a40c38e73af4 -> c5f2a8d1e9b3 ->
b8e3d1f7a2c4 -> f2a9c4d7e1b3 -> c3e8b5a1f4d2 -> a7d4f1c9b0e6 ->
e1b6c9a3d7f4`. Verified by an empty-database `flask db upgrade` replay of the
whole chain, which reaches head and yields 2,489 selectable ICD-10 codes and
four COD bucket schemes.

Verified: full suite **1,624 passed at `702f518`**, `PYTEST_EXIT=0` read
from pytest itself, plus 16 tooling tests at `EXIT=0`. The vendored suite is
715 tests and passes on a quiet machine, but is timing-flaky under load
(`digitva-3jj`): a different test fails each run, which is how you tell it
from a regression. Earlier: 1,618 at `78757d4` and at `1e94b4c`, 1,605 at
`d04a9f8`, 1,602 at `347bbf1` (1,570 after WP6, 1,499 after WP1, 1,469 after the project_pi predicate, 1,464 after the instrument-locale rule, 1,453 after the projects-panel inputs, 1,449 after the instrument-layer change (1,445 after the closed-project rule, 1,423 with form-options, 1,409 after the public-route decisions, 1,391 after the PII change, 1,381 on the rebased tree before all of them).

## The access model, as it now stands

`collaborator` and `collaborator_pii` reach **five** read-only routes:
`/data-management/`, `/data-management/dashboard`, and the `submissions`,
`filter-options` and `kpi` APIs. Nothing else, no writes.

Two things worth knowing before extending it:

- **`dm_scope_filter` is wider than the grant and fails open.** An `org_unit`
  grant is bridged to the unit's whole project, because a unit does not name a
  site. Callers that enumerate submissions must AND in
  `dm_submission_org_unit_condition`. Two callers were not doing that and were
  serving a project's whole site roster to a viewer granted one leaf unit;
  both now narrow themselves. If you add a caller, apply the condition or write
  down why the coarse answer is right.
- **`/data-management/cod-buckets` is deliberately NOT viewer-reachable.** The
  page is a shell and all three endpoints behind it are `data_manager`/`admin`,
  so granting the page alone gives a screen that 403s on every fetch. Opening
  that API is a separate widening: `export.csv` emits staff identity.

## DigitVA layers (landed this session)

Layers are overlays on the one bundled WHO 2022 instrument (E7/E8), and
until `d04a9f8` the mechanism was half-built in a way worth remembering:
the server derived `enabled_extensions` and served it, but
`vendor/who-va-2022/src/instrument.ts` spliced **every** DigitVA question
into one module-level constant regardless, and the intake page branched on
exactly one name (`intake_screen`). A project that disabled a layer still
got its questions. Composition is now
`createWhoVa2022Instrument(enabledExtensions)`; `whoVa2022Instrument`
remains exported as the all-on composition so existing importers and the
vendor suite are unaffected.

`enabled_extensions` now has **eight** names: `medical_records` joins the
seven, carrying `md_available`/`md_count`/`md_im1..30` out of
`digitva_core`, derived from `web_intake_medical_records_enabled`
(default true, migration `e1b6c9a3d7f4`).

**ND01 was compared before adoption, and mostly not adopted.** Only
`ds_available` and `md_available` were taken. Rejected and why:
`Id10002`/`Id10003` gain a `calculation` hard-coding state `21` and
district `412`, so every other site would silently record "very low" HIV
and malaria mortality; `Id10365` loses the WHO constraint forbidding a
baby recorded as neither under 2.5 kg nor over 4.5 kg. `Id10476` was left
alone: its reference relevance `string-length(${Id10476_audio})=0` is
already true while web intake has no audio capture, so the typed narrative
shows today and the expression only becomes live with attachments phase 2.
ND01 encodes telephonic interviews as a third `Id10013` value and a
widened `consented` group; that was **not** adopted. `consent_mode` is a
separate question recording how consent was taken, because `va_consent`
stays the authoritative record that it was taken (owner, 2026-09-19).

Two traps for whoever builds the next layer:

- **Numbering.** `consent_mode` first shipped at `anchor.order + 1` and
  collided with `Id10011`, because `Id10013` is followed immediately by
  it. The neighbouring `custom_medical_certificate_upload` uses
  `anchor + 1` safely only because the generated instrument happens to
  leave a gap after `Id10473`. Number DigitVA questions from `maxOrder`.
  A test now asserts `order` uniqueness across all sixteen layer
  combinations; nothing held that invariant before.
- **`social_autopsy_enabled` means two unrelated things.** It drives the
  `social_autopsy` extension *and* the coder-side social-autopsy analysis
  panel (`app/routes/api/so.py`). A third consumer must not assume one
  meaning. `docs/planning/social-autopsy-rendering-plan.md` is a stale
  draft superseded by the layers model.

Both `digitva-thr.3` and `digitva-thr.4` are now closed -- see "Layer
translation (landed 2026-09-20)" below. One thing recorded here earlier was
wrong and is worth correcting rather than deleting: ND01 does NOT lack a
Hindi column and did not need a general parser. It has `label::Hindi (hi)`,
whose cells pack `English\nHindi`, and `split_packed` already handled that --
which is how Hindi reached 100 percent on the base instrument. What was
genuinely missing was narrower: two other packing conventions and a
reference source that included the layers at all. Also `digitva-aiy`:
relevance is purely
presentational, so answering a gate "no" can orphan image answers already
captured -- pre-existing, but the gates widen it, and attachments phase 2
turns those references into real files.

## Layer translation (landed 2026-09-20)

`digitva-thr` is closed. What was actually wrong, and what it cost to fix:

**Layer questions existed only as TypeScript.** `createDigitVaExtension`
composed them at runtime and nothing serialized them, so
`who-va-2022.instrument.json` held the 449 WHO questions and none of
DigitVA's, and `reference_items()` raised for any code but `WHO_2022_VA`.
`consent_mode` and `md_available` therefore could not be imported, exported
as XLIFF, edited or scored. `tooling/who-va-2022/build-layer-reference.mjs`
now emits `vendor/who-va-2022/src/generated/digitva-layers.reference.json`
by set difference against the WHO base, so it cannot drift as layers are
added. It is deterministic on purpose -- no `built_at` -- and a byte-identical
regenerate is a test. It emits a data file only; the browser bundle is
untouched by it, and that isolation is pinned by a test that fingerprints the
bundle directory by content hash rather than asking git (the git version
conflated "the generator did not write there" with "nothing did").

**Entries carry every contributing extension, not one.** `digitva_documents`
belongs to both `medical_records` and `death_summary`; attributing it to
whichever came first in the extension list would score it under a layer the
project had not enabled.

**Activation is no longer gated on coverage** (owner, 2026-09-20: "whatever
the translation in the tool is the translation"). The 0.95 threshold, the
auto-activate on import and `--force` are gone. English fallback already
answers the question per string -- an untranslated key is ABSENT from the
served payload, not empty, verified in `export_translations` and in the
client's `setLocalized` -- so a percentage was deciding something it could
not see. Coverage is still computed and reported, now per extension too.
Base coverage keeps the WHO instrument's own 476 question labels as its
denominator; layer labels are deliberately NOT folded in.

**The social autopsy layer is ND01 verbatim, and that is the decision.**
`sas01`-`sas07` keep their ordinal values ("1".."8") although they are the
outlier against WHO's conventions and DigitVA's own, which are semantic.
`mas_choice_mappings` already carries those ordinals for `sa01` against form
type `WHO_2022_VA_SOCIAL`, and `submission_analytics_mv.py:371-374` projects
`sa01`-`sa19` raw into the COD-snapshot CSV export, so a semantic recode
would put two value shapes under one field id and one column. The
`sa13`-`sa19` relevance expressions stay literal string comparisons against
`"na"/"Na"/"nA"/"NA"` rather than `selected()`, which would change which
answers reveal the field.

**The choice-code convention, settled by the owner 2026-09-20:** questions
DigitVA authors itself save semantic codes; questions mirrored from a
deployed form keep that form's codes verbatim. Everything DigitVA had already
authored complied, so it cost nothing to adopt.

Three traps for whoever works here next:

- **The expression tokenizer no longer treats backslash as an escape.**
  ND01's `regex(.,'^(?!0{1,3}$)\d{1,3}$')` was being tokenized to `d{1,3}`,
  which no digit-only answer satisfies. The first fix unescaped only `\'`
  and `\"` and made a literal ending in a backslash throw instead of parse;
  the rule now matches XPath 1.0, where a backslash is ordinary and the
  doubled quote is the only escape. Safe because the corpus contains no
  backslash at all -- verified across the generated instrument JSON, the
  extension source, and the curated workbook's shared strings and every
  sheet. **The vendored engine is the only evaluator of this grammar in the
  system.** No Python parses it: `xlsform_instrument_builder.py:169-172`
  passes expression text through as opaque `{"source": ...}` and says so in
  its own docstring, and there is no pyxform/formpack/xpath dependency.
- **`split_packed` fails closed, and that is load-bearing.** It splits only
  on an exact match against the reference English. An unrecognised cell is
  kept whole and reported rather than guessed at. Do not add fuzzy or
  similarity matching to make a near miss "work" -- a near miss should be
  visible as untranslated. Whitespace runs are collapsed for the comparison
  only, never for the stored text.
- **`intake_screen` and `geography` contribute no instrument questions, and
  that is correct.** ND01's three-item `begin_screen` group is substituted by
  a single admin-configured `intake_note` rendered as a client welcome card,
  and geography's fields are server-injected after validation per decision
  O4. The policy table at `docs/policy/va-form-project-configuration.md:51`
  still describes both as question-contributing, which is how someone ends up
  "restoring" server-injected fields as interviewer questions -- filed as
  `digitva-c48`. The `geography` flag itself is derived and served but has no
  consumer anywhere: `digitva-ybt`.

Filed this session and deliberately out of scope: `digitva-c48` (stale policy
table), `digitva-ybt` (dead geography flag), `digitva-cal` (the server takes
the client's own `valid` boolean as the validity gate -- pre-existing, and a
decision to take rather than a bug to fix, given interviewers are
authenticated), `digitva-ssi` (an ODK site-mapping POST may not be idempotent
under extreme latency), `digitva-3jj` (the vendored vitest suite is
timing-flaky under machine load).

## The vendored bundle was stale (fixed this session)

`7bf1d5f`. The bundle committed in `926c212` was not built from the source
committed beside it: three fixes lived in `src/` and had never reached a
browser -- a language-dropdown `accessibilityRole` of `button` where source
says `option`, and React keys on the form and preview roots that stop one
subtree being reused across a view switch. Found only because a
reproducibility check ran *before* layering new work on top. **Run that
check first whenever you touch `vendor/who-va-2022`:** rebuild on an
unmodified tree and confirm `git diff app/static/vendor/who-va-2022/` is
empty but for `manifest.json`. That `built_at` timestamp dirties the
manifest on every rebuild and is what let the drift hide; `digitva-cw9`
proposes removing it so the invariant becomes testable.

## Start here

**The web-capture configuration plan is fully landed**
(`docs/planning/web-capture-project-configuration-plan.md`, beads
`digitva-6v1`, `xv9`, `shz`, `mze`, `9ff`, `0by` all closed). Operator
step on any database, dev included: import, **approve** and activate each
language with `flask instrument-translations import WHO_2022_VA <locale>
docs/kb/WHO_VA_2022_Docs/<workbook>`, then
`flask instrument-translations lifecycle WHO_2022_VA <locale> approved
--approved-by <admin>`, then `activate`. Since 2026-09-20 activation alone is
refused: only an approved locale may be served. Nothing serves Hindi until all
three are done. All thirteen documented languages reach 100 percent coverage on the
survey labels (eight from the deployed Indian forms, five from WHO's
multilingual V2.0 form). Translators exchange a locale as XLIFF 2.0 through
the panel or `flask instrument-translations export-xliff` / `import-xliff`;
where a string has no translation the form shows English. Whether the
curated reference form itself moves from V1.1 to V2.0 is `digitva-13x`.

**`digitva-thr` is closed.** All four work packages landed; the section
"Layer translation (landed 2026-09-20)" below has the detail and the traps.
The media parts are still attachments phase 2.

**Operator step, not optional:** re-import each language to pick up the
corrected packed-cell splitting. Three items were being stored wrong on
every deployment before `702f518` -- `language/hindi` as `Hindi (हिन्दी)`,
`language/english` as `English (English)`, and `Id10184_a`'s hint as English
-- and a re-import is the only thing that fixes rows already in the database.
Administrator edits are never overwritten, so this is safe to run.

Open after this pass, in order:

0. `digitva-aiy`: relevance is purely presentational, so answering a gate
   "no" can orphan image answers already captured. Settle it before
   attachments phase 2 turns those references into real files. Related and
   newly filed: `digitva-cal`, the server accepting the client's own `valid`
   boolean as the questionnaire validity gate.
1. ICD-11 phases 3 to 6 with decisions D1 to D6 all recorded, plus the
   project ICD classification default (web forms have no ODK mapping row,
   so `get_icd_classification_for_submission` returns `icd10` for them);
   the ICD-11 policy draft generated from the annex CSV for the owner's
   review, which also carries annex follow-up 2 (the full audit).
2. Attachments phase 2 (renders `death_summary`; W6: nothing mandatory),
   then the validator sidecar W1.
3. Annex follow-ups `digitva-2g7`, `28a`, `jt3`, `2c1`.
4. Older plans still carry "Open Questions" sections outside this pass's
   scope: `docs/planning/project-sites-forms-refactor.md`,
   `access-control-grants-design.md`, `social-autopsy-rendering-plan.md`,
   `icd11-self-hosted-api-and-ect-plan.md`,
   `docs/current-state/health-system-organization-model.md:298`. Most are
   superseded drafts; sweep or archive them.


Ranked across every session's input. Done since the previous ranking: the
PII set failing open, the PII cache never invalidating, and the route
decorator guarantee (see the two sections below). The six routes that were
pending a decision are settled: help, WHO documents and the home page are
public. The `form-options` endpoint is in (section below); its one open
consequence is the `WHO_2022_VA_SOCIAL` instrument.

The ranked list from the start of 2026-09-19 is exhausted, and the
projects-panel inputs are in (section below). Open, in order:

1. `digitva-4ym` is closed (section below). Left open by it: no bundled
   language other than `en` exists yet, so the picker never shows; and the
   dev database's projects still store `mas_languages` codes in
   `web_intake_available_locales` from before, which the resolver drops
   silently.
2. The `project_pi` predicate item is closed (section below).
3. The `base_instrument_code` column when a second standard instrument is
   bundled.

Then: attachments phase 2, the validator sidecar (written, unwired, decision
W1), ICD-11 coding screen phases 3-6.

## `project_pi` role gate is an EXISTS (landed this session)

Item 3 of `.tasks/auth-decorator-followups.md` said `project_pi` was the
only `role_required` predicate that queries and that reordering
`("admin", "project_pi")` would make its query unconditional. The premise
was stale: `is_admin()` is itself an EXISTS query, so every predicate costs
one statement and `any()` over booleans is order-independent already. What
remained was cost class: the gate fetched the user's whole PI project set to
answer yes/no. `VaUsers.is_project_pi()` is now an EXISTS over the same four
grant conditions plus `active_project_condition`, so a closed project still
yields False, and the predicate calls it. `get_project_pi_projects()` is
unchanged and still answers scope. `tests/test_role_required_project_pi_predicate.py`
asserts the semantics including the closed-project rule, identical statuses
under both argument orders for an admin, a PI and a plain user, and that
the gate is exactly one `SELECT EXISTS` statement with the scope query as
the discriminating control (both contain the word EXISTS because
`active_project_condition` is one; the outer select list is what differs).
Per-request caching of role checks was deliberately not added: admin routes
call `get_project_pi_projects()` several times per request and a memo on
`flask.g` would go stale inside the grant-mutating requests themselves.

## Web form locale is `en` plus the instrument's translations (landed this session)

Decided by the owner 2026-09-19 after the projects panel exposed the
problem: `web_intake_default_locale` defaulted to `en` while the seed creates
`mas_languages` codes `english`, `hindi`, ..., so on every seeded deployment
the resolver fell back to the first active code and dev's forms opened in
`assamese`. The rule now: **`en` is the default on every project and always
available; a project adds languages from what the bundled instrument
actually has translations for; the interviewer picks a working language on
the intake page and the browser remembers the last choice.** Narration
languages stay on `mas_languages`, because they describe the recording, not
the screen. The instrument's locales are an explicit registry,
`INSTRUMENT_LOCALES` in `app/services/web_form_instruments.py` (today
`WHO_2022_VA: {en}`), pinned to the vendored bundle by
`tests/services/test_web_form_instruments.py`, which greps the bundle for
`label:{<code>:` with positive and negative controls; there is no vendoring
script, so the registry is hand-maintained and the test is what keeps it
honest. The stored default column stays and is honoured only when it names
an instrument locale. The PUT/POST validate `available_locales` against the
registry and narration against `mas_languages`. `GET
/admin/api/web-form-locales` (admin) feeds the panel's available-languages
list, where `en` is ticked and disabled; the per-project default select is
gone. The intake page sets the component's `locale` attribute from
`localStorage` key `digitva.intake.locale` when the code is in the project's
list, else the default, and renders a picker only when more than one locale
is available; the component re-renders on the attribute change. Both JS
surfaces were exercised in jsdom (panel 21 checks, intake 9 including
blocked `localStorage`); the harness is in the session scratchpad, not the
repo.

## Projects panel inputs for the web form options (landed this session)

`app/templates/admin/panels/projects.html` gained a "Web form languages"
block: default language select, an "offer every active language" switch
(sends `null`) over an available-languages checkbox list, a narration
languages checkbox list (none ticked sends `null`), and a show-guidance
switch. Languages come from `GET /admin/api/languages` (active only),
fetched once at panel init. If that fetch fails the four fields are omitted
from the payload, so a languages outage never blanks a project's settings.
When languages arrive after an Edit form is already open the form is
refilled from the project, not reset to create defaults (a reviewer caught
that race). A stored default that is no longer active renders as
`<code> (inactive)` and Save is blocked with a message naming it; the
server would 400 anyway, with a terser one. The default locale is ticked
into a narrowed list on Save, matching what the resolver does. The PUT's
validation block moved into `_web_intake_form_option_updates` in
`app/routes/admin.py` and the project POST now calls it before constructing
the row, so a bad payload creates nothing. Three POST tests and a render
test cover the Python; the JavaScript was exercised in jsdom (21 checks:
edit fill, stale default, empty restricted list, late-languages race,
languages failure, create) but that harness is not checked in, because the
repo has no JS toolchain. `admin_create_project` still ignores
`coding_intake_mode` and `web_intake_mode` on create (pre-existing; the
panel has always sent them and they take effect on the next edit).

## Closed projects revoke every grant scope (landed this session)

A project with `project_status != active` (that is `deactive` or `pending`)
resolves no grant of any scope for any non-admin role. Grants are not
deleted or status-changed; reopening the project restores them and the
audit trail is untouched. The rule is one expression,
`org_grant_service.active_project_condition`, a correlated EXISTS on
`va_project_master`, applied inside every resolver's own query: seven in
`org_grant_service` and five on `VaUsers`. Everything else that derives
access (`dm_scope_filter` and friends, the organization and web-intake
reachable-unit helpers, the `is_*` role predicates) goes through those
twelve, plus `should_redact_pii`, which the security review caught: a
PII-granting grant on a closed project would otherwise keep switching
redaction off on screens reached through an open project. Its per-scope
subqueries must stay correlated to the grant row; the first draft lost the
correlation and scanned every grant, which eleven dashboard tests caught.
Both mechanisms the task file named now agree because they share the
predicate; a third resolver must use it too. Recorded in `docs/policy/access-control-model.md`, "Closed Projects".

## Migrations may not import application code (landed this session)

Fifteen historical migrations import the analytics MV SQL builders from
`app.services.submission_analytics_mv`; none imports models or enums. They
are pinned by filename and exact import set in
`tests/migrations/test_no_app_imports_in_migrations.py`, which walks every
file under `migrations/versions` with `ast` and fails on any application
import outside the pins, on a pin whose set has grown, and on a stale pin.
Inlining the fifteen was rejected: it would change what a replay executes
on a database that has already run them. The pairing check is the existing
schema-drift test, which builds a throwaway database from the chain alone.
Rule 7 in `docs/policy/migration-chaining.md`.

## form-options endpoint (landed this session)

`GET /api/v1/organization/<project_id>/form-options` serves the tier-2
options from `docs/policy/va-web-form-options.md`, with the same grant check
as `/units`. Four explicit columns on `va_project_master`
(`web_intake_default_locale`, `web_intake_available_locales`,
`web_intake_narration_languages`, `web_intake_show_guidance`; migration
`f2a9c4d7e1b3`, additive, no `app.*` import). `form_types` is derived from
`map_project_site_odk`; `enabled_extensions` is derived from existing flags,
with `intake_screen` and `death_summary` omitted until something can derive
them. The admin project PUT validates the four fields; the projects panel UI
does not expose them yet, because its settings form is built from explicit
element handles and the four inputs are more than a few lines of JS.

The intake template no longer hardcodes `locale="en"`. It sets
`el.instrument` from a map keyed on the form type's `instrument_code`, which
the endpoint now serves: `WHO_2022_VA` for every `WHO_2022_VA*` code. That
follows the product rule stated 2026-09-19: **DigitVA form types are layers
on top of the one standard WHO 2022 instrument, not separate
questionnaires.** `WHO_2022_VA_SOCIAL` renders the base instrument and
`enabled_extensions` says which layers apply. The first cut refused SOCIAL
as unbundled; that reading was wrong and is gone. `instrument_code` is a
naming convention today; when a second standard instrument (PHMRC) is
bundled it becomes a `base_instrument_code` column on `mas_form_types`,
recorded in `docs/policy/va-web-form-options.md`.

## Route decorator guarantee (landed this session)

`role_required` now stamps its wrapper with `__digitva_roles__`, and
`tests/test_route_auth_coverage.py` walks `app.url_map` at runtime, follows
each view's `__wrapped__` chain, and fails on any endpoint that carries
neither that marker nor Flask-Login's `login_required` (detected by code
object, because `functools.wraps` rewrites `__module__` and `__qualname__`
and a name check finds nothing). `hasattr(f, "__wrapped__")` was rejected
as the signal: any `wraps`-based decorator sets it, and the test keeps one
assertion proving unguarded-but-wrapped endpoints still exist so that
rationale stays falsifiable. Positive control registers an unguarded view on
a bare `flask.Flask` and asserts it is reported.

One allowlist, `PUBLIC_BY_DESIGN`, checked for stale entries and for
entries that later became guarded. It holds fifteen endpoints: static,
health, the seven `va_auth` account-access flows (login, logout, maintenance
banner, forgot password, reset link, resend verification, verify email), the
home page (`/`, `/index`, `/vaindex`), the WHO reference documents, and the
four help pages. Decided 2026-09-19: help and WHO documents are public so a
prospective user can read them before logging in; `help.page` keeps its
in-body role filter for role-restricted pages. The home page is public
because the site has a dedicated login page; a `login_required` on `/` was
landed and reverted the same day, so do not put it back.
`tests/routes/test_public_route_access.py` asserts the anonymous behaviour
of each class at runtime.

`API_PATH_PREFIXES` is now a constant on `role_required`, and a test asserts
every `/api/`-shaped rule matches one of its prefixes, closing item 2 of
`.tasks/auth-decorator-followups.md`. Item 3 (`project_pi` is the only
predicate that queries) is still open.

## PII set confirmation (landed this session)

A form type's PII set is **confirmed** when at least one `is_pii` row sits on
a field the form actually owns (`subcategory_code IS NOT NULL OR odk_label IS
NOT NULL OR is_custom = false`). "Zero `is_pii` rows" was never a usable
check: `apply_pii_field_registry` creates three redaction-only rows for every
form type, WHO-shaped or not. Derived from data, so no migration and no
confirm button: an admin confirms a PHMRC form by flagging one of its real
fields in the field-mapping panel.

Unconfirmed fails closed: a plain `collaborator` gets no payload at all on
the submission page, and the submissions CSV export writes the payload
columns empty for every role (it was already PII-filtered for every role).
The admin form-type list, `get_form_type_stats`, the field-mapping panel and
`flask form-types` all show the status.

**One exemption, deliberate:** the SmartVA input export still only strips
flagged fields on an unconfirmed form type, logged as
`pii set unconfirmed | <code> | smartva input export not withheld`. It is a
processing feed reachable only by data managers and admins, and withholding
there would make SmartVA unusable on any new questionnaire. The remaining
fail-open on that path is unchanged from before: a form whose form type
cannot be resolved exports its payload with only the hardcoded omit list
applied. Recorded in `docs/policy/access-control-model.md`.

The PII status cache is keyed on `(count(*), max(updated_at))` of
`mas_field_display_config` for the form type, so an admin edit or Celery-run
sync reaches every worker on its next call. The other mapping caches
(fieldsitepi, choices, labels) are still process-level and cleared only by
`clear_cache()` — a test that mutates a mapping row and renders must clear
them on cleanup, or later tests in the same process render the mutated
build after the savepoint has rolled the row back.

Test database for this tree: `minerva_test_pii` (created this session).

## Open and unexplained

- **The dev DB stamp moved backwards two revisions** with the later migrations'
  data still present. Fixed by re-running `flask db upgrade`; cause unknown.
  A stamp regressing without a downgrade is a data-integrity signal. Likely
  contributor: `boot.sh` retries `flask db upgrade` forever against a DB
  stamped at a revision the tree lacks, hanging silently instead of failing.
  `.tasks/dev-db-stamp-regression-and-infra.md`.
- **Dev and a fresh clone have diverged**: dev's `WHO_2022_VA` carries 2,414
  mappings against a fresh clone's 2,380. That is how a test passes here and
  fails everywhere else.
- **`test_odk_site_mappings`** failed once in a full run with its POST and GET
  each taking 35,118ms to within 3ms. Not reproduced, not explained. The
  identical timings are the fingerprint if it recurs.
- **15 migration files import from `app.*`**, unswept. The `mas_org_unit` break
  came from exactly this.
- **`stash@{0}`** is still present from the incident earlier this week. Not touched by this session; drop it only after someone confirms it holds nothing needed.

## How to work in this repo now

- **One test database per tree.** `TestConfig` honours `TEST_DATABASE_URL`
  above everything. `drop_all` cannot order a table its metadata has never
  seen, so a tree lacking another tree's uncommitted model cannot tear down a
  schema containing it — persistently, not as a race. See
  `docs/policy/test-harness.md`.
- **Shared checkout discipline.** Git read-only unless you are the session that
  owns landing commits; never `stash` (one swept 37 files across four sessions
  this week). Build file lists from `git diff`, never from memory of your own
  edits — in a shared tree the diff is the only source of truth about what a
  commit will contain.
- **Six vacuity rules** are in `docs/policy/test-harness.md`, each from a check
  that passed today while proving nothing: assert the subject is present before
  asserting it is absent; patch the module object, not a dotted path through a
  package that re-exports it; a missing fixture can make an authorization test
  vacuous; defeat the bytecode cache when mutation testing; treat an errored
  `setUpClass` as the whole class unverified; the dual-table FK trap.
- **Migrations chain onto committed revisions only**, verified in `git log`. An
  `origin/main` was broken this week by a revision naming a parent that existed
  only in a working tree. Three migrations named one parent today; each
  re-chained as it landed.

## Known gaps in what was verified

No suite has been mutation-tested except `tests/test_role_required_validation.py`.
The two new ICD CLI commands and migration `c5f2a8d1e9b3` have no automated
test. The intake page's JavaScript is inline in a Jinja template and
structurally untestable — which is why the optional-level reachability bug
lived there undetected. About 27 docs were last updated in March and have never
been checked against the code.
