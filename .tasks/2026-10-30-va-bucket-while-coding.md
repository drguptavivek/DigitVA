# VA cause bucket while coding (digitva-to74)

- Status: built and tested 2026-10-30, not committed. Approved by owner 2026-10-30 (label only for definition-less nodes; "VA cause: not mapped" for unmapped, which never blocks submission). Baseline: docs/policy/va-cause-definitions.md.
- Priority: P2
- Created: 2026-10-30

## What already exists

Most of this is already built. The bucket's VA cause is shown during coding today:

- Web DORIS editor and masked Step 2 picker: a floating panel shows the VA
  cause and its definition for the picked or confirmed ICD-11 code
  (`app/static/js/va_definition_panel.js` → `GET /api/v1/va-definitions/for-icd`
  → `find_va_definition_for_icd`).
- Collect Plus: "Associated VA codes: VAs-xx.xx Title" plus the case definition,
  inline under the chosen final cause and on the Step 1 card (`AssociatedVaCodes`),
  and in the (i) sheet. Offline it reads the bundled
  `assets/va-definitions-WHO_2022_VA_2026.json` (`scripts/export_offline_va_definitions.py`).
- Definitions exist: 63 WHO 2022 definitions in `mas_va_cause_definitions`
  (`docs/policy/va-cause-definitions.md`).

## The gap (measured on the dev DB, 2026-10-30)

The display resolves only nodes that have a WHO definition. When the nearest
mapped node has none, it walks up the ICD-11 tree to an ancestor whose node does.
Analytics stops at the nearest mapped node.

- **10 codes show a different VA cause than analytics.** `JB0A.2`–`JB0A.Z` map
  directly to `vas_09_99` (Other and unspecified maternal cause), but the panel
  shows `VAs-99` Cause of death unknown, which is the mapping of their parent
  `JB0A`. Likewise `QA00.62` maps to `vas_98`, but the panel shows `VAs-99` from `QA00.6`.
- **6,600 codes show nothing** but do have a bucket in analytics: `vas_98` Other
  and unspecified NCD (6,231), `vas_09_99` (367), `other_gastrointestinal_diseases` (12).
- The parent section (e.g. "Non-communicable diseases") is never shown.
- There are three implementations of the walk: `_who_2026_bucket_sql`
  (snapshot), `_icd_candidates` + `find_va_definition_for_icd` (web), and
  `resolve_codes` (pack). They differ on age scope as well: the snapshot reads
  only `age_scope IS NULL`, while the lookups take any scope with NULL first.
- The pack records no migration revision, and nothing checks the committed
  pack against the DB at head.

## Proposal

1. **What shows.** Under the selected underlying cause, in the existing slot
   (web panel, `AssociatedVaCodes`, (i) sheet), both before and after Process:
   `VA cause: <node_label> (<VAs code or node_code>)`, with the section
   `<parent node_label>` above it. Below that comes the WHO definition, if the
   node has one. Nodes without a definition (`vas_98`, `vas_09_99`,
   `other_gastrointestinal_diseases`) show the label and section only. No new
   endpoint or component: the existing response and pack gain `bucket_code`,
   `bucket_label` and `bucket_section`.
2. **One rule.** Factor the `bucket_rows` and ancestor-walk CTEs out of
   `_who_2026_bucket_sql` into one helper, used by the snapshot MV, by the
   exporter, and by the server lookup. The materialized view's SQL text stays
   the same, so no migration is needed. The whole resolution takes 0.13 s for
   18,505 codes. The server builds it once and caches it in-process, keyed by
   the scheme's `mapping_version` and `updated_at`. That avoids a catalogue scan
   per request. Age: `WHO_2022_VA_2026` has one band (All Ages,
   `age_scope` NULL), so no age logic is needed. The lookups switch to
   `age_scope IS NULL`, as in the snapshot. Primary stem: the saved
   `primary_stem`, else the first stem (unchanged).
3. **Definition text.** Use the existing 63 WHO 2022 definitions; no new
   source. Owner: should the 3 nodes without a definition get text (e.g. the
   WHO note on VAs-98 that we skip today), or show the label only?
4. **Fully offline.** In Collect Plus the bucket line always comes from the
   bundled pack, in every mode, online included, so it never needs the network.
   The pack moves to schema 2 of the same file. It adds a `buckets` table (node
   code, label, section, VA code if any), `codes` maps each stem to its node
   code, and it gains `db_revision` and `content_sha256` over the whole content.
   It is generated from the shared helper. A pytest drift test compares the
   committed pack with the DB at head, as `test_icd11_allowability_pack.py`
   does, plus an exhaustive parity test: pack = server lookup = snapshot for
   every catalogue code. The TS reader validates the hash and rejects an
   unknown schema. Web (browser) uses the server lookup. Caveat: if an admin
   edits mappings on a server after the app was built, the app shows the
   bucket it shipped with until the next pack.
5. **Unmapped and other schemes.** A code with no bucket on its chain shows
   `VA cause: not mapped`; today it shows nothing. Owner: show that line, or
   stay silent? The display is gated on `icd_classification == 'icd11'`, which
   uses `WHO_2022_VA_2026` (fixed in `VA_DEFINITION_SCHEMES`). Projects have no
   bucket-scheme column, so "only when the project's scheme is
   WHO_2022_VA_2026" needs a schema change if wanted. ICD-10 projects keep
   today's `WHO_2022_VA` lookup, unchanged.

The source ICD code stays the record of truth. The bucket is display only and
changes no stored value or provenance.

## After approval

Policy baseline in `docs/policy/va-cause-definitions.md` ("Definition for the
selected ICD code"), with a cross-link from `icd11-cod-bucket-schemes.md`.
Then build:

- shared CTE helper; lookup and exporter on it; regenerate the pack
- web panel and Expo components show the bucket and section
- Collect Plus reads the pack in every mode
- tests: drift, parity, unmapped, no stored-value change
- Jest for the pack reader; `make check-web`
- `docs/current-state/doris-cod-workflow.md`

No migration and no data change.
