---
title: ICD-10 to ICD-11 Transition for VA Cause Buckets
doc_type: policy
status: draft
owner: engineering
last_updated: 2026-09-25
---

# ICD-10 to ICD-11 Transition for VA Cause Buckets

This is the one record of how DigitVA assigns WHO 2022 VA cause buckets to
ICD-10 and ICD-11 codes. It covers the method, the process, every override
made so far and the decisions still open. It links to the detailed documents
instead of repeating them:

- Rules: [ICD-11 COD Bucket Schemes](icd11-cod-bucket-schemes.md)
- ICD-10 selectability: [WHO 2022 ICD-10 coding allowability](who-2022-icd10-coding-allowability.md)
- WHO source table: `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who-2022-va-cause-list-icd10-icd11.md`
- ICD-10 decision history: `.tasks/who-2026-annex-icd10-icd11-review.md`
- Tracking: beads `digitva-712` (ICD-11 schemes) and `digitva-712.2` (this record)

## 1. Method: direct ICD-11 mappings, not the crosswalk

As of 2026-09-24:

| Scheme | ICD-10 rows | ICD-11 rows | ICD-11 method |
|---|---:|---:|---|
| `WHO_2022_VA` (original curated) | 2,414 | none | none (ICD-10 only) |
| `WHO_2022_VA_2026` (2026 annex) | 2,498 | 18,505 (every catalogue code outside chapter X) | `native` |
| `SRS_INDIA`, `CMEA10` | ICD-10 only | none | none |

- **ICD-11 codes are bucketed directly** (native). Each ICD-11 code maps to
  a VA cause through WHO's own ICD-11 ranges in the 2026 annex. The code is
  not first translated to ICD-10.
- **The crosswalk is used only as an offline cross-check.** WHO's ICD-11 to
  ICD-10 table (`11To10MapToOneCategory`, 2025-01) is read by the generator
  to flag every code where the native bucket differs from the bucket the
  code's ICD-10 equivalent gets. No scheme uses `icd11_method = crosswalk`,
  and the app has no runtime crosswalk table or lookup yet.
- **Why native:** the crosswalk loses whole causes. Examples are in
  section 1.1.
- **The crosswalk method will not be built** (owner, 2026-09-24, decision 6).
  Projects that mix ICD-10 and ICD-11 bucket each death through the rows of
  its own classification in the native scheme.

Where the ICD-11 rows are read today:

- the coding screen shows VA cause definitions for an ICD-11 code;
- admin can view, edit and export the ICD-11 rows.

ICD-11-coded deaths in bucket reports: Included (digitva-dus.1). The COD
bucket report page and the coded COD snapshot export bucket each death
through the rows of its own classification; see
`docs/current-state/cod-bucket-reporting.md`.

The coded ICD-11 value is always the record of truth. Buckets are derived
and can be recomputed at any time.

### 1.1 Why we did not bucket ICD-11 through the crosswalk

The obvious route would reuse the existing ICD-10 buckets: translate each
ICD-11 code to ICD-10 with WHO's `11To10MapToOneCategory` table, then look up
its ICD-10 bucket. We measured that route against WHO's own 2026 cause list
(owner decision 2026-09-21) and rejected it for the WHO scheme, for these
reasons.

**1. It loses entire causes.** Each row below counts only the ICD-11 codes
that WHO itself assigns to that cause. "Wrong via crosswalk" means the code
would not land in that cause after going through the crosswalk.

| VA cause | ICD-11 codes | Wrong via crosswalk | Example |
|---|---:|---:|---|
| Sepsis `VAs-01.01` | 2 | 2 (all) | `1G40` goes to block `A30-A49` (six buckets); `1G41` septic shock goes to `R57.2` (ill-defined, `VAs-99`) |
| Road traffic accident `VAs-12.01` | 18 | 18 (all) | `PA00`-`PA0x` go to blocks such as `V01-V09` or `V01-X59`, which span road traffic, other transport, falls and more |
| Fresh stillbirth `VAs-11.01` | 1 | 1 (all) | `KD3B.1` intrapartum death goes to `P95`, which is Macerated stillbirth |
| Pregnancy-related sepsis `VAs-09.06` | 9 | 8 | `JB40` puerperal infections go to `O86` (other maternal); only `JB40.0` goes to `O85` |
| Haemorrhagic fever `VAs-01.11` | 50 | 27 | `1D4C` Alkhurma goes to `A92-A99` (haemorrhagic fever or dengue); `1D4D` Ross River goes to `B33.1` (other infectious) |
| Meningitis/encephalitis `VAs-01.07` | 52 | 19 | `1C80` viral encephalitis, `1C82` rabies and `1C81` polio go to `A80-A89`, which our ICD-10 scheme puts in other infectious |
| Birth asphyxia `VAs-10.02` | 22 | 5 | `KB20` intrauterine hypoxia goes to `P20-P29`, which spans asphyxia, neonatal pneumonia and other perinatal |

These are the causes that matter most in VA mortality statistics. A scheme
that reports zero sepsis and zero road-traffic deaths is wrong, not merely
imprecise.

**2. It often lands on a block, not a code.** 337 of the native mappings
cross to an ICD-10 block that covers several buckets. The policy forbids
guessing, so each of these becomes `unmapped`. The transport and sepsis
losses above are mostly this.

**3. It cannot express distinctions ICD-11 added.** ICD-10 has one code
where ICD-11 has two (fresh vs macerated stillbirth). Going back to ICD-10
throws the distinction away.

**4. Overall agreement is too low to trust unreviewed.**
- Against WHO's own list: 88.6% land in the same cause, 9.6% in another,
  and 1.9% have no ICD-10 target.
- Against our curated ICD-10 scheme: only 11,099 of 16,154 codes (69%)
  reach the same bucket. Another 4,123 have an ICD-10 target that our scheme
  does not bucket at all (injury `S`/`T`, symptoms `R`, eye/ear `H`), because
  it covers only codes a coder may select.

**5. The tables come from different releases.** The crosswalk is 2025-01 and
the catalogue is 2026-01. Codes new in 2026-01 must first be translated
through WHO's change list, which is another step where codes can be lost.

**6. It chains two lossy steps.** An ICD-11 code first goes through WHO's
11-to-10 table, then through our ICD-10 buckets. An error at either step
carries through, and a report cannot show which step caused it. The native
mapping is a single step taken straight from WHO's own ICD-11 column.

**What the crosswalk is still used for:**
- A cross-check on every native mapping (the 916 `crosswalk_disagreement`
  review items).
- A suggested bucket for each unmapped code (not applied).
- The planned `crosswalk` method for projects that mix ICD-10 and ICD-11
  data. That method needs an audited override list first, starting with
  sepsis, road traffic and stillbirth.

### 1.2 The other direction: ICD-10 to ICD-11

WHO also publishes ICD-10 to ICD-11 tables (`10To11MapToOneCategory`,
`10To11MapToMultipleCategories`, 2025-01). They are frozen in
`migration-artifacts/icd11-icd10-mapping-tables-2025-01-base-2026-09-16/`, but
**nothing in the app reads them**. No ICD-10-coded death is converted to
ICD-11, and none is planned. The ICD-10 code stays the record of truth,
and ICD-10 deaths are bucketed through their ICD-10 rows.

This direction would matter in two cases:
- converting historical ICD-10 data into a pure ICD-11 report;
- checking that the scheme's ICD-10 and ICD-11 rows agree with each other.

A one-off measurement (2026-09-24) did the second. It used the ICD-10
point-code resolution already in `WHO_2022_VA_2026`: a specific
four-character code beats its three-character range. For example `V01.1`
(traffic) is Road traffic, while `V01.0` (nontraffic) and `V01.9`
(unspecified) are Other transport. Each **effective** ICD-10 row was put
through WHO's one-category table, and its bucket was compared with the
native ICD-11 bucket of the target code. A three-character row was counted
only where it has no four-character rows beneath it. Only the first code of
a combined target was used, and the catalogue parent chain was followed.

| Result | Effective ICD-10 rows |
|---|---:|
| Same bucket | 2,159 (90.1%) |
| Different bucket | 184 |
| ICD-11 target has no native bucket | 34 |
| No usable target (`D37`-`D44` have none; `C30`, `B34` and others point to codes not in 2026-01; `UU1`/`UU2` are local) | 18 |
| Total | 2,395 |

What the differences show:

- **Stillbirths with unknown timing are not counted as stillbirths.**
  `P95` goes to `KD3B.Z` ("unspecified time of fetal death"). In ICD-11,
  `KD3B` and `KD3B.Z` fall under the "other perinatal" range `KD30.2-KD5Z`,
  so they land in `VAs-10.99` rather than a stillbirth bucket. This is a
  native-mapping gap as well: an ICD-11 coder who cannot tell antepartum
  from intrapartum puts the death in the neonatal group.
- **Our ICD-10 manual overrides have no ICD-11 counterpart.** The overrides
  in section 3 were never mirrored in the ICD-11 rows, so the same condition
  lands in a different bucket depending on the classification:
  - `K72`/`K73` (Liver cirrhosis in ICD-10) → `DB9Z`/`DB97.2`, which are
    `VAs-98`;
  - `K64`/`K75`/`K76` (Other GI) → `VAs-98`;
  - `I25`/`I50` (Acute cardiac) → `VAs-04.99`.
  - `G47` (`VAs-99`) → `7B2Z`, which is `VAs-98`;
  - `R50` fever (`VAs-01.99`) → `MG26`, which is `VAs-99`.

  `G46`, `R10` and `R95` do agree across the two classifications.
- **WHO's own ICD-10 and ICD-11 columns disagree.** For viral infections
  of the central nervous system, the annex puts ICD-10 `A80`-`A89` in
  Unspecified infectious (`VAs-01.99`) but ICD-11 `1C80`-`1C8F` in
  Meningitis/encephalitis (`VAs-01.07`). Examples: `A80` polio → `1C81`,
  `A82` rabies → `1C82`, `A85`/`A86` → `1C80`. The same death changes cause
  when the classification changes. `D74` (methaemoglobinaemia) shows the
  same kind of disagreement: `VAs-98` in ICD-10, Severe anaemia in ICD-11.
- **Transport: our point-code resolution holds, but WHO's ICD-10 to ICD-11
  table does not keep the traffic split.** 103 of the 184 differences are
  transport codes:
  - 66 are ICD-10 "person injured while boarding or alighting" codes (for
    example `V10.3`, `V43.4`). Our resolution puts them in Other transport;
    WHO's table sends them to ICD-11 traffic codes (`PA02`, `PA04`), which
    are Road traffic. This is a policy difference to confirm, not an error.
  - 15 ICD-10 codes explicitly marked "traffic accident" go to ICD-11
    codes that are not traffic codes, so they would leave Road traffic.
    Examples: `V25.4`/`V25.5`/`V25.9` → `PA23` ("unknown whether traffic",
    with traffic kept only in an extension code); `V39.4`-`V39.6` → `PA19`
    (a "nontraffic" code). These are errors in WHO's table.
  - The rest are codes whose titles do not say traffic or nontraffic:
    `V80.x` animal-rider (Road traffic in ICD-10, other transport in
    ICD-11), `V82.x` streetcar and `Y85` sequelae.
- **Point codes that already agree** include the pedestrian and occupant
  traffic codes (`V01.1` → `PA00`, `V43.5` → `PA04`) and their nontraffic
  and unspecified counterparts (`V01.0` → `PA10`, `V01.9` → `PA20`, all
  Other transport). The ICD-11 PA split (section 4) matches our ICD-10
  resolution: "unknown whether traffic" (`PA2x`) is Other transport in both.
- Other external causes: 19 `VAs-12.99` codes have a specific ICD-11 bucket
  (for example `W35`-`W41` explosions and pressure → `PB55`, which is in
  Smoke/fire; `W60` plant thorns → `PA79`, which is in Venomous animals and
  plants). `W16` (diving or jumping into water, injury *other than*
  drowning) goes to `PA92`, which the native ranges put in Drowning. That is
  a native-mapping gap: `PA92` is explicitly not a drowning.
- The rest fall mainly in residual buckets (`VAs-98` 23, `VAs-99` 5,
  `VAs-04.99` 5), plus `G03`-`G05` (meningitis in ICD-10, `VAs-98` in ICD-11)
  and `O02`/`O20`/`O86` (other maternal in ICD-10, a specific maternal cause
  in ICD-11).

The measurement script is not checked in, and the one-category table
gives one preferred target where the multiple-category table has several.
If ICD-10 data ever has to be converted, repeat this as a proper generator
report, the way the ICD-11 report was produced.

## 2. Process

### ICD-10 (2026 annex revision, decided 2026-09-18)

1. Transcribe WHO's 2026 annex Table A1 into
   `who_2022_va_cause_list_icd10_icd11.csv`, checked against the PDF text.
2. Diff the annex ICD-10 ranges against the curated `WHO_2022_VA` scheme,
   code by code.
3. Build `WHO_2022_VA_2026` as a new scheme alongside `WHO_2022_VA`, which
   stays unchanged. Apply the annex additions and carry forward the manual
   overrides already in `WHO_2022_VA` (section 3).
4. Ship both changes in migration `c5f2a8d1e9b3`, from the artifacts in
   `migration-artifacts/who-2022-va-icd-cod-2026-revision/`.

### ICD-11 (native generation, decided 2026-09-21)

1. Expand each annex ICD-11 range against the ICD-11 MMS 2026-01 catalogue
   (chapter X excluded, 18,505 categories).
2. Give each code one cause:
   - the narrowest range wins;
   - a tie between two ranges of the same size is never guessed and is not
     mapped;
   - ranges shared between two causes are split code by code (section 4).
3. Cross-check every mapped code against the curated ICD-10 buckets through
   the crosswalk. The 2026-01 codes are first translated to 2025-01 through
   WHO's change list.
4. Write the report files under
   `migration-artifacts/who-2022-va-icd11-native-2026-09-21/`: the generated
   mappings, `icd11_review.csv`, and the unmapped codes with suggestions.
5. Freeze the mappings as `resource/who_2022_va_2026_icd11_native_mappings.csv`
   and seed them with migration `6c11b620f48f`. That migration also sets the
   scheme to `native` and adds the Fresh stillbirth bucket.

6. Apply the owner's decisions (section 6): the generator reads
   `docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_icd11_owner_decisions.csv`
   after the annex ranges, then maps every code still without a bucket by
   the decision 5b rule. Migration `dc762caa67dd` brings existing databases
   to the regenerated table.

Regenerate with `flask cod-buckets generate-icd11 --scheme WHO_2022_VA_2026
--seed-csv resource/who_2022_va_2026_icd11_native_mappings.csv`. Never edit
the generated CSVs by hand: change the source CSV, the decisions file or the
generator, then regenerate, freeze the previous seed CSV, and ship a new
migration.

## 3. ICD-10 overrides and decisions (all decided)

All of these are in `WHO_2022_VA_2026`. `WHO_2022_VA` is unchanged except
for its own earlier manual overrides.

| Decision | Detail | Date |
|---|---|---|
| Adopt 2026 annex ranges | 109 codes made selectable and bucketed: `G43`-`G47`, `K72`/`K73`/`K75`/`K76`, 13 `K70.x`/`K71.x`, `R00`-`R09` (no `R08`), `R10`, `R11`-`R94`. Default bucket `VAs-98`/`VAs-99` | 2026-09-18 |
| Liver cirrhosis carve-out | `K70.2`, `K70.3`, `K71.7`, `K74` stay in `VAs-06.02`; other `K70.x`/`K71.x` go to `VAs-98` | 2026-09-18 |
| `R10` to Acute abdomen | `VAs-06.01`, as the annex lists it. Replaces an earlier override to "Other Gastrointestinal Diseases", which was deliberately not carried | 2026-09-19 |
| `R95` (SIDS) moved | From `VAs-99` to `VAs-10.99` (other perinatal) | 2026-09-18 |
| 33 earlier manual overrides carried forward | From `WHO_2022_VA` so prior curation is not lost. 7 of them differ from what the annex ranges alone would give: `G46` to Stroke, `G47` to `VAs-99`, `K72`/`K73` to Liver cirrhosis, `K75`/`K76` to Other GI, `R50` to `VAs-01.99` | 2026-09-18 |
| Bucket-only codes | 9 codes (`I11`, `I46`, `I50`, `K64`, `K70`, `U07`, `Y91`, `UU1`, `UU2`) have bucket rows but are not selectable. Left as they were | 2026-09-18 |
| Selectability is global | The ICD-10 selectability table has no per-scheme partition, so the annex additions changed what every project can select. The bucket scheme can be reverted; the selectability change cannot | 2026-09-18 |
| Owner decisions 10, 11, 12 | `I50.0`/`I50.9` to Acute cardiac; `A80`-`A89` to Meningitis/encephalitis; 65 boarding/alighting codes to Road traffic (section 6.1). Applied by migration `fad35e5c4b79`, and by every import or reset of the scheme from `WHO_2022_VA_2026_owner_decisions_overrides.csv` | 2026-09-24 |

## 4. ICD-11 rules and overrides applied

| Decision | Detail | Status |
|---|---|---|
| Native method for the WHO 2026 scheme | `WHO_2022_VA_2026.icd11_method = native` | Decided 2026-09-21 |
| Narrowest range wins | A specific cause's range beats a residual "other/unspecified" range | Decided 2026-09-21 |
| Transport split | `PA0x` (traffic events) to `VAs-12.01` Road traffic; `PA1x`-`PA5x` (nontraffic, rail, water, air, other) to `VAs-12.02` Other transport. 71 codes, following the owner's earlier ICD-10 split | Decided 2026-09-21. The 18 `PA2x` "unknown whether traffic" codes stay Other transport (decision 3, 2026-09-24) |
| Fresh vs macerated stillbirth | New bucket `VAs-11.01` Fresh stillbirth. `KD3B.1` (intrapartum) goes to Fresh; `KD3B.0` (antepartum) goes to `VAs-11.02` Macerated. ICD-10 `P95` cannot tell the two apart and stays Macerated, so the two classifications count fresh stillbirths differently | Decided 2026-09-21 |
| Sepsis | `1G40` and `1G41` go natively to `VAs-01.01`. The crosswalk would have lost them (section 1.1) | Follows from the native method |
| Maltreatment `PJ20`-`PJ2Z` | Both Assault and Other external claim the same range. Mapped to `VAs-12.09` Assault (maltreatment by others) | Decided 2026-09-24 (decision 2) |
| "Ruptured uterus" label | The annex prints `VAs-09.0`; matched by label to node `vas_09_08` | Applied; confirm |
| Selectability is separate | Bucket rows never make an ICD-11 code selectable or unselectable. That is set by the ICD-11 catalogue policy (ICD-11 browser) | Decided 2026-09-21 |

## 5. Gaps found during the transition

All counts come from the generator report of 2026-09-21 and are weighted by
codes, not deaths.

### 5.1 Classification gaps: ICD-10 and ICD-11 do not line up

| Gap | Evidence | Effect |
|---|---|---|
| ICD-11 separates things ICD-10 lumps together | Stillbirth: `KD3B.1` (intrapartum) vs `KD3B.0` (antepartum); ICD-10 has only `P95` | Fresh stillbirths can be counted in ICD-11 but not in ICD-10. Trends across the switch are not comparable for `VAs-11.x` |
| Injuries are coded differently | ICD-10 VA buckets use external-cause codes (V01-Y98). The crosswalk sends ICD-11 injury codes to nature-of-injury codes (S, T): 2,062 generated mappings | These mappings cannot be cross-checked, and a death coded by nature of injury only has no external cause |
| Crosswalk targets that are not codes | 337 mappings point to an ICD-10 block that spans several buckets (e.g. `R50-R69` 88, `V01-X59` 46, `P20-P29` 28, `G00-G09` 27). Some point to a whole chapter (`I`) | In a crosswalk scheme these become `unmapped` rather than a guessed bucket |
| No ICD-10 equivalent | 44 generated mappings have no crosswalk target | Nothing to compare against |
| Chapters with no ICD-10 counterpart | Traditional medicine (`S`, 1,120 codes), functioning (`V`, 130), extension codes (`X`, excluded) | Not causes of death. They stay unmapped by design |
| Codes that combine several concepts | ICD-11 allows a stem code plus extension codes | Only the first stem is bucketed; extension codes are ignored |
| Different code structure | ICD-11 codes are not ordered by prefix the way ICD-10 codes are | Lookup follows the catalogue's parent chain rather than cutting the code string short |

### 5.2 Gaps in WHO's source material

| Gap | Evidence | Effect |
|---|---|---|
| Different release years | Crosswalk and mortality list are 2025-01; catalogue is 2026-01 | 2026-01 codes are translated through WHO's change list before lookup. A code still missing is `unmapped` |
| Range errors in the annex | 5 malformed or non-existent endpoints (e.g. `5C52.Y-5C52-Z` skipped; `2C20-2C2Z` and `3A00-3A4.Z` end on codes that do not exist) and 3 ranges that reach past their written end | The malformed range is skipped by the parser and corrected in the decisions file (decision 4); the missing endpoints were expanded by code order and kept (decision 4) |
| Label error | The annex prints `VAs-09.0` for Ruptured uterus | Matched by label to `vas_09_08` |
| Ranges shared by two causes | `PA` codes (road traffic vs other transport) and `PJ2x` (maltreatment: Assault vs Other external) | Split code by code; `PJ2x` to Assault (decision 2) |
| Annex ranges miss clinically relevant codes | 2,351 catalogue codes are in no range (12.7%). Most are expected (2,101 are `S`/`V`/`Q`/`X`). These are not: diabetic acute complications `5A20`-`5A2Y`, including ketoacidosis `5A22` (the Diabetes range is `5A10`-`5A14` only); thalassaemias `3A50` (Severe anaemia ranges skip it); alcoholic liver disease `DB94.0`/`DB94.1` including `DB94.10` "alcoholic hepatitis with cirrhosis" (Liver cirrhosis lists only `DB94.2`/`DB94.3`); tick-borne encephalitis `1C8G`; the parent codes `RA01` (COVID-19) and `3A4Z` | Resolved 2026-09-24: decision 5a maps these, and decision 5b maps every other code, so no ICD-11 code is unmapped |
| Broad annex ranges | "Sickle cell with crisis" is `D57` / `3A51` whole, which includes sickle cell trait and haemoglobin C/D/E disease | Applies to both classifications; inherited from WHO |

### 5.3 Crosswalk quality

The losses for each cause, and why they ruled the crosswalk out, are in
section 1.1.


- Running WHO's ICD-11 ranges through the crosswalk and comparing with the
  same causes' ICD-10 ranges: 88.6% land in the same cause, 9.6% in
  another, and 1.9% have no ICD-10 target.
- Agreement by cause:
  - Sepsis: 0% (lost entirely);
  - pregnancy-related sepsis: 11%;
  - haemorrhagic fever: 54%;
  - meningitis/encephalitis: 71%.
- Against our curated ICD-10 buckets, the 16,154 native mappings break down
  as:

| Result | Mappings |
|---|---:|
| Same bucket | 11,099 |
| Different bucket | 551 |
| ICD-10 target has no curated bucket | 4,123 |
| Target is a block spanning several buckets | 337 |
| No target | 44 |

  The 916 `crosswalk_disagreement` review items (896 after the 2026-09-24
  decisions, section 6.1) are the second and fourth
  rows combined, plus codes whose ICD-10 target is bucketed differently in
  the two ICD-10 schemes.
- **A quarter of the native mappings cannot be cross-checked.** The curated
  ICD-10 scheme buckets only codes a coder may select (2,414 rows). Many
  crosswalk targets (injury `S`/`T`, symptoms `R`, eye/ear `H`) are not among
  them.

### 5.4 System gaps

| Gap | Where it stands |
|---|---|
| ICD-11 deaths in bucket reports | Included (digitva-dus.1): each death is bucketed through the rows of its own classification |
| No runtime crosswalk | No crosswalk table or lookup; `crosswalk` schemes cannot work yet |
| Decisions are machine-readable (resolved 2026-09-24) | The generator reads `who_2022_va_icd11_owner_decisions.csv`, and `icd11_review.csv` has a `decision` column naming the decision that settles each item |
| Web forms are always ICD-10 | A web-form submission has no ODK mapping row, so its classification resolves to `icd10` |
| ICD-10 selectability is global | Adopting the annex changed what every project can select. It cannot be scoped per scheme |
| Test coverage | No automated test covers migration `c5f2a8d1e9b3` or the `import-who-2022-va-2026` and `policy-import` commands |

## 6. Owner decisions (2026-09-24)

The owner decided all 13 open items on 2026-09-24. Decisions 1-5 and 9-12
are applied (section 6.1); 6-8 and 13 are tracked separately. Each applied
change is a regenerated artifact plus a new data migration, recorded where
the generator or the scheme import reads it, so that regenerating or
resetting does not undo it.

| # | Item | Decision |
|---|---|---|
| 1 | 916 `crosswalk_disagreement` items | Accept WHO's native ICD-11 bucket wherever either side is a residual bucket (`VAs-98`, `VAs-99`, `*.99`, or a bucket that is not a VA cause). The **12** items with a specific cause on both sides come back to the owner: 7 transport, plus `vas_01_07`/`vas_01_11`, `vas_01_11`/`vas_01_02`, `vas_04_02`/`vas_10_06`, `vas_11_01`/`vas_11_02`, `vas_12_04`/`vas_12_03` |
| 2 | Maltreatment `PJ20`-`PJ2Z` | **Assault** (`VAs-12.09`). The provisional mapping is confirmed |
| 3 | 18 flagged `PA20`-`PA2Z` (unknown whether traffic) | **Other transport** (`VAs-12.02`), consistent with ICD-10 "unspecified whether traffic" point codes |
| 4 | Annex range errors | Read `5C52.Y-5C52-Z` as `5C52.Y-5C52.Z` and map to `VAs-98`. Keep the other seven as currently expanded, including the descendants past the written end |
| 5a | Clinically relevant codes in no annex range | `5A20`-`5A2Y` diabetic acute complications → `VAs-03.03`. `3A50.x` thalassaemias and `3A4Z` → `VAs-03.01`. `DB94.10` alcoholic hepatitis with cirrhosis → `VAs-06.02`, and the other `DB94.0`/`DB94.1x`/`DB94.Y`/`DB94.Z` → `VAs-98`, as for ICD-10 `K70.0`/`K70.1`. `1C8G`, `1C8H` → `VAs-01.07`. `RA01` → `VAs-01.13` |
| 5b | Remaining 2,301 unmapped codes | Accept the 152 single-bucket crosswalk suggestions (not the 8 `RA` codes, which were wrongly suggested as COVID-19). Map **everything else** (the `RA` codes, traditional medicine `S`, functioning `V`, factors `Q`, and the rest) to **`VAs-99`**, so no ICD-11 death reports as `unmapped` |
| 6 | Crosswalk method | **Not built.** Projects that mix ICD-10 and ICD-11 use the native scheme: each death is bucketed through the rows of its own classification. Remove the `crosswalk` method from [ICD-11 COD Bucket Schemes](icd11-cod-bucket-schemes.md). The crosswalk stays as an offline cross-check only |
| 7 | ICD-11 in bucket reports | **Build now**, V3 scope: bucket each death through the rows of its own classification, and record provenance |
| 8 | Project ICD classification | **Project setting only.** Move each project's current per-form ODK value up to the project (flag projects whose forms disagree), then stop reading `map_project_site_odk.icd_classification`. Web forms follow the project setting |
| 9 | `KD3B` / `KD3B.Z` unknown-timing fetal death | **Macerated stillbirth** (`VAs-11.02`), the same as ICD-10 `P95` |
| 10 | ICD-10 overrides with no ICD-11 counterpart | **Copy all nine** to their ICD-11 equivalents, but only where each is still relevant in the ICD-11 scheme; check each code when applying. `K72`/`K73` → Liver cirrhosis (`DB99.x` hepatic failure, `DB97.2`). `K64`/`K75`/`K76` → Other GI (`DB60`-`DB6Z`, `DB97.Z`, `DB9Z`). `I25`/`I50` → Acute cardiac (`BA5x`, `BD10`/`BD1Z`; `BD11` is already there). `G47` → `VAs-99` (`7A`-`7B`). `R50` → `VAs-01.99` (`MG26`). All nine still differ as of 2026-09-24 |
| 11 | Viral CNS infections | **Both to Meningitis/encephalitis** (`VAs-01.07`): move ICD-10 `A80`-`A89` there, matching ICD-11 `1C80`-`1C8F`. This is a DigitVA decision against WHO's ICD-10 column |
| 12 | Boarding/alighting ICD-10 codes | **Road traffic** (`VAs-12.01`): 65 codes such as `V10.3` and `V43.4`, matching WHO's ICD-10 → ICD-11 table. `V82.4` (streetcar) is the exception: it stays Other transport under 13b. The 15 "traffic accident" codes that WHO's table sends to non-traffic ICD-11 codes need no action, because no ICD-10 data is converted |
| 13a | Footnote f tail `V90`-`V99`, `Y85.9` | **Other transport**. The provisional reading is confirmed |
| 13b | `V81.2`-`V81.9`, `V82.2`-`V82.8` | **Keep Other transport** (rail and streetcar events are not road traffic). They stay DigitVA decisions |
| 14 | ICD-10 congenital anomalies `Q00`-`Q99` (added 2026-09-24) | **All ages**, to match ICD-11 chapter 20 in the ICD-11 selectability draft. The 87 selectable Q rows that were neonate-only change from `neonate` to `all`, in migration `a3c9e1f7b2d4`. This is global: it changes what coders can select in every project. Re-importing the released 2026 ICD-10 policy JSON would undo it |

### 6.1 Applied (2026-09-24)

ICD-11 decisions live in
`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_icd11_owner_decisions.csv`
(one row per code or range: a single code covers only itself, `A-B` covers
what the same annex range would). Explicit decisions beat annex ranges; among
decisions the narrower entry wins. Rows carry `match_type` `owner_decision`
(or `owner_fallback` for 5b) and a note "Owner decision N (2026-09-24): ...".
Migration `dc762caa67dd` (ICD-11) and `fad35e5c4b79` (ICD-10) apply them to
existing databases and leave admin-edited rows alone. All of these rows derive
as "DigitVA decision" on the public page, because the annex does not give the
code to the row's cause.

| # | Applied | Rows |
|---|---|---:|
| 1 | `icd11_review.csv` marks 822 `crosswalk_disagreement` items "accepted: native bucket (owner decision 1)" and the 12 specific-vs-specific items "owner review (digitva-712.6)" (unchanged: 7 transport, `1C8C`, `1D64`, `8B22.40`, `KD3B.1`, `PA92`). The other 62 disagreements are on rows set by decisions 5a, 5b and 10 | 0 changed |
| 2 | `PJ20`-`PJ2Z` Assault; review type `pj2x_split`, no longer a proposal | 5 (unchanged) |
| 3 | `PA20`-`PA2Z` Other transport; marked decision 3 in the PA split review | 18 (unchanged) |
| 4 | `5C52.Y-5C52.Z` to `VAs-98` (`5C52.Y`, `5C52.Z`); the other seven range errors kept as expanded | 2 added |
| 5a | `5A20`-`5A2Y` (18) to `VAs-03.03`; `3A50` family (14) and `3A4Z` to `VAs-03.01`; `DB94.10` to `VAs-06.02`, the other seven `DB94` codes to `VAs-98`; `1C8G` family (5) and `1C8H` to `VAs-01.07`; `RA01` to `VAs-01.13` | 48 added |
| 5b | Every other unmapped code: 152 take the crosswalk's single-bucket suggestion (147 `VAs-98`, 3 `VAs-10.06`, 1 `VAs-01.02`, 1 `VAs-09.99`); 2,148 go to `VAs-99` (the 9 `RA` codes, `S`, `V`, `Q` and codes with no or a multi-bucket suggestion). Unmapped ICD-11 codes: 0 | 2,300 added |
| 9 | `KD3B`, `KD3B.Z` to `VAs-11.02` Macerated stillbirth (`KD3B.1`/`KD3B.0` unchanged) | 2 changed |
| 10 | `DB99.7`, `DB99.8`, `DB97.2` to Liver cirrhosis (3); `DB60`-`DB6Z` (10), `DB97.Z`, `DB9Z` to Other GI (12); `BA50`-`BA5Z` (15), `BD10`, `BD1Z` to Acute cardiac (17); `7A00`-`7B2Z` to `VAs-99` (79, of which `7A82` was unmapped); `MG26` to `VAs-01.99` (1). `DB91` (acute or subacute hepatic failure, WHO's 10To11 target of `K72.0`) was considered and deliberately left with its native bucket (owner, 2026-09-24). Other 10To11 point-code targets of `K75`/`K76` (for example `DB90.0`, `DB96.0`, `DB98.x`, `DB92.Z`, `DB99.2`) are not in the owner's list and keep their native bucket. ICD-10 side: `I50.0` and `I50.9` move to Acute cardiac, so heart failure is Acute cardiac in both classifications (`I50.1` already was) | 111 changed, 1 added; 2 ICD-10 rows |
| 11 | ICD-10 `A80`-`A89` (the scheme has only the ten three-character rows) to `VAs-01.07` | 10 ICD-10 rows |
| 12 | The 65 ICD-10 codes whose title says "boarding or alighting" and whose WHO 10To11 one-category target is a `PA0x` traffic code, to Road traffic. Excluded: `V81.4` (rail) and `V82.4` (streetcar) under 13b, and `V15.3`, `V25.3`, `V97.1`, whose targets are not `PA0x` | 65 ICD-10 rows |

ICD-11 totals after regeneration: 18,505 rows (range 15,965, split 76,
owner decision 164, decision 5b 2,300).

## 7. Public mapping page (owner, 2026-09-24)

DigitVA publishes, without login, the mappings of `WHO_2022_VA_2026`: which
ICD-10 code (including point codes) and which ICD-11 code goes to which VA
cause, and whether that follows WHO or is a DigitVA decision.

- **Scope:** `WHO_2022_VA_2026` only, ICD-10 and ICD-11 rows, active rows only.
  Read-only; GET only.
- **Origin is derived, not stored.** Each row is compared at read time with
  WHO's 2026 annex
  (`docs/icd-causegrp-mappings/ICD-to-VA-Buckets/who_2022_va_cause_list_icd10_icd11.csv`
  and its footnotes), so it cannot drift from the data:
  - **WHO**: the code falls in the annex range of the row's VA cause and in
    no other cause's range. Transport codes are WHO when footnote f lists
    them for road traffic (`VAs-12.01`), or when they are outside that list
    and bucketed as Other transport (`VAs-12.02`). Footnote f's list ends
    `...Y85.0; V90-V99; Y85.9`. The page reads only the codes before `V90`,
    plus `Y85.0`, as road traffic, and treats `V90`-`V99` (water, air, other)
    and `Y85.9` as Other transport. The owner confirmed this reading on 2026-09-24
    (decision 13a).
  - **WHO, resolved by DigitVA rule**: two or more causes' annex ranges claim
    the code, and DigitVA picked the one the row shows by a stated rule. The
    rules are: narrowest range wins; specific code beats range; the transport
    split; the `PJ2x` decision.
  - **DigitVA decision**: the row's cause is not one the annex gives the code.
    This includes codes outside every annex range and buckets that are not
    WHO VA causes (e.g. "Other Gastrointestinal Diseases").
- **Each row shows:** classification, code, code title, VA code and title,
  origin, and the row's note.
- **Use:** server-side search (code, title, VA cause), filters
  (classification, origin, VA cause), paged results, and a download of the
  full list as CSV.
- **No PII.** Only reference data is shown. Admin identities and edit
  history are not shown.
- If an admin edits a row, the page reflects the edit on the next load, and
  the origin is re-derived.
- **Compare view** (`/help/va-code-mappings/compare?va_code=...`, added
  2026-09-25, `digitva-xud`): pick a VA cause; the ICD-10 codes mapped to it
  are shown on the left and the ICD-11 codes on the right. Both are trees
  grouped by chapter and block, and each code carries its origin badge. The
  hierarchy comes from the catalogue tables the admin browsers read
  (`mas_icd10_2019_2`, `mas_icd11_mms`). For ICD-11, the block shown is the
  outermost block, which is the level an ICD-10 block sits at.
- **ICD-11 state view** (`/help/va-code-mappings/unmapped`, and `.csv`):
  lists every ICD-11 category in the generator's scope with its current
  state. The scope is release `2026-01`, active, coded, outside chapter X:
  18,505 codes. Each code shows its VA cause and origin, or **Unmapped**
  when no active row maps it. It also shows whether coders may select it and
  the policy review status (`reviewed` / `unreviewed`).
  - The page shows the selectable list as it stands. It does not wait for
    the owner's sign-off (`digitva-dus.3`): unreviewed codes are labelled
    as such.
  - Filters: selectable / not selectable / all, and a text search. Results
    are paged and grouped by chapter and block.
  - The CSV without a search is cached on disk, one file per selectable
    variant. A mapping or catalogue edit replaces the file. Its bytes equal
    the live download. A search always streams live.
  - Every in-scope code is mapped today (decision 5b), so the view reports
    "0 unmapped". The route name stays `unmapped` as requested.
  - Chapter X's 17,159 extension codes are left out. They are never bucketed,
    and none of them is selectable.
