# digitva-r5s0: curated KPI pool, registry and MCP (plan for owner approval)

This is the Opus advisor's proposal of 2026-10-27, with the Collect
correction-loop KPIs added by the main session. Nothing is implemented yet.
The audit table it classifies is `.tasks/digitva-0hul-kpi-query-refresh.md`.

## Owner direction

- "A small accurate and meaningful KPI pool is better than a wide
  inconsequential one."
- "Retain as many as possible."
- Classify and categorise every KPI.
- Group by input, process, output and outcome.
- Provide blockers, critical paths, predicted completion and trends.
- Make the definitions searchable and queryable by AI agents over MCP.

## Summary

**18 core panels, 31 registered (queryable, no fixed panel), 18 merged and
5 retired.** All 5 retirements are things that are not measures: the 4
stored-aggregate rows, which the owner already retired, and D-PS-03, a
configuration listing.

The Collect correction loop (`digitva-ydnl.5`, advisor addendum) adds 4
registered KPIs (CL-01 to CL-04) and enriches the C-23 "Sent back" row.
Totals: **18 core, 35 registered, 18 merged, 5 retired**.

| Stage | Core | Registered | Merged | Retired |
|---|---|---|---|---|
| Input | 2 | 2 | 2 | 0 |
| Process | 7 | 13 (+3 loop) | 8 | 4 |
| Output | 5 | 14 (+2 loop) | 8 | 1 |
| Outcome | 4 | 2 | 0 | 0 |

**Shared rules for every core KPI:**
- **Scope:** `DmScope.sql()`, counting a pair or unit subtree once, with
  confirmed duplicates excluded and training excluded.
- **Peers:** siblings inside the viewer's grant only.
- **Rates and ranks:** shown only when the denominator is 20 or more
  (`PERCENT_MIN_WHOLE`).
- **Small cells:** any count under 5 is folded.
- **Canonical terms:** as defined in `docs/policy/kpis.md`.

## Core pool (18)

| # | id | Question | Stage / category / type | Level | Views | Replaces |
|---|---|---|---|---|---|---|
| 1 | C-21 | Do we have enough coders, and are they busy? | Input / workforce / rate | Dt Bk Fu | status, trend* | C-21, D-LC-02 |
| 2 | C-15 | Which ready cases have no coder for their language? | Input / workforce / gap | Dt Bk Fu | status, blocker | C-15, D-LC-03 |
| 3 | C-04 | How much is uncoded, and when will it clear? | Process / flow / rate and days | Pj-St | status, trend, forecast | C-04, C-22, D-WT-03, C-17, grid Pending |
| 4 | C-19 | Are we keeping up (inflow against outflow)? | Process / flow / net | Pj Dt Bk Fu | trend, forecast | C-19 |
| 5 | C-23 | What is stopping cases, why, how old, and who can unblock them? | Process / flow / volume | Pj Dt Bk Fu | blocker, status | C-23, C-10, SmartVA failed |
| 6 | C-07 | Which states hold cases too long? | Process / timeliness / aged volume | Dt Bk Fu | status, trend, blocker | C-07, D-WF-03 (thresholds kept) |
| 7 | C-08 | How long does a coding episode take? | Process / timeliness / duration | Dt Bk Fu | status, trend | C-08 |
| 8 | D-WF-02 | Which stage dominates end-to-end time, and where is the bottleneck against peers? | Process / timeliness / duration | Pj Dt Bk Fu | critical path, trend | D-WF-02, area medians |
| 9 | C-03 | Is ODK sync working? | Process / system / rate | System | status, trend | C-03, C-02 |
| 10 | C-01 | What came in and what got coded each day? | Output / flow / volume | Pj-St | trend | C-01, D-PS-01, D-PS-02 |
| 11 | AD-FCOD | What share of codeable cases has an authoritative cause? | Output / coverage / rate | Pj-St | status, trend, forecast | area Final COD, Site-PI coded, C-18 achieved |
| 12 | AD-COV | Are reported deaths being interviewed, and how many have waited over 30 days? (death-register projects) | Output / coverage / rate | Dt Bk Fu | status, trend, blocker | area deaths reported and interviews pending |
| 13 | C-05 | How many cases are lost to coding, by whom and why? | Output / data quality / rate | Pj Dt Bk Fu | status, trend | C-05, D-QG-01 to 05 |
| 14 | C-06 | How many interviews cannot be analysed, and why? | Output / data quality / rate | Pj Dt Bk Fu | status, trend | C-06 |
| 15 | O-UNK | What share of finals has no meaningful cause? | Outcome / coding quality / rate | Pj Dt Bk | status, trend | new |
| 16 | D-QG-09 | Do coders and reviewers agree, at the WHO 2026 bucket level? | Outcome / coding quality / rate | Pj Dt | status, trend | D-QG-09 |
| 17 | EQ-01 | Are female deaths under-reported in some districts, against peers? | Outcome / equity / gap | Dt Bk | status, trend | new |
| 18 | EQ-02 | Do female cases get a final cause as often as male cases? | Outcome / equity / gap | Pj Dt Bk | status, trend | new |

\* The C-21 trend needs its grant and allocation history checked first.

**Owner of each C-23 blocker row:**
- screening, upstream and soft gates: the DM;
- attachment sync and SmartVA: the DM, or admin when the queue is down;
- language gap and "no coder at unit": the coder supervisor or in-charge;
- sent back and ODK flagged: the field team, through the IC.

## Registered (queryable, no fixed panel)

**Input:** D-LC-06 coder roster (web only, because it names people);
ST-01 staff per unit (new).

**Process:**
- **Flow:** C-16 daily coding rate; C-20 per-language pendency forecast;
  D-WF-01 CONSORT; D-WF-04 transitions.
- **Timeliness:** D-WT-02 upstream resolution time.
- **Coding quality:** C-09 review coverage; D-WT-04 reopen rate; CQ-FAST
  share of fast finals (new).
- **System:** C-13 sync latency; C-14 attachment health; D-SH-01; D-SH-04;
  D-SH-02 (web only).
- **Loop:**
  - **CL-01, send-back and reopen rate by reason.** The reason code comes
    from the submission audit row (`<reason>:<code>`), paired with the
    workflow event by `LATERAL`. `by=actor_role` is available. ODK is shown
    only as a proxy: hasIssues plus upstream-change counts.
  - **CL-02, time to correct.** Each request is paired with the next
    `interviewer_revision`, giving the median and p90 in hours. Open and
    cancelled requests are counted, with no duration. Collect only. It also
    becomes the "correction" stage of the D-WF-02 critical path.
  - **CL-04, supervisor review turnaround.** Inactive until
    `digitva-ydnl.4` ships. It counts only projects that have the switch on.

**Output:**
- **Flow:** C-18 burndown (the forecast of AD-FCOD).
- **Coverage:** D-QG-08 SA completion; D-LC-01 languages; AD-VN visit
  notes.
- **Data quality:** D-QG-06; D-LC-07; C-11; D-SH-03; D-QG-07 NQA;
  D-LC-05; EQ-03 sex or age unknown (new).
- **Workforce:** C-12 throughput (totals only on MCP); C-24 forms per coder
  (web only; D-LC-04 merges into it); D-WT-01 reviewer throughput.
- **Loop:** CL-03, repeat send-backs (cases with 2 or more requests).
  Collect only.
- **Awaiting correction** is merged into the core C-23 "Sent back" row,
  which gains age, owner ("interviewer, through the IC") and
  `by=interviewer` (web only). Every C-23 row gains an `intake_source`
  split.

**Correction-loop facts:**
- **Send-back and reopen are Collect only.** ODK submissions are refused,
  and ODK uses hasIssues plus Central edits instead.
- **ODK review-state history is not stored,** so ODK time to correct,
  repeat flags and reasons are not captured.
- **Per-interviewer rows name people,** so they are web only, for DMs and
  ICs in scope, and never sent over MCP.
- **The Collect/ODK split** is `va_forms.form_source`. Browser against
  device is not split.

**Outcome:** SV-AGR agreement with SmartVA (new); MO-01 cause mix.

**Retired:** stored total/new/updated, stored event counts, stored
end-of-day state and stored durations (aggregates retired); D-PS-03
(a configuration listing, not a measure).

**Infrastructure, kept to serve the registry and MCP:** `/analytics/kpi`
(it still needs the pending fix), the `by-*` series, demographics,
workflow, the MV unit rollups and the dashboards.

### Policy points to amend first

- `kpis.md:17` and `kpis.md:740` are written around fixed panels; rewrite
  them as core and registered.
- AD-COV and the register half of EQ-02 apply to death-register projects
  only.
- D-PS-03 needs a retirement line.
- The D-WF-03 thresholds carry into the registry unchanged.
- The D-QG-03 reviewer-rejection item is still a known gap.
- `within_24h` keeps its one-release overlap.
- Sending KPI definitions to the model needs a line in
  `ai-analytics-questions.md`. It is definition text, not data.

## Analytic views (registry field `views`)

- **Blocker (C-23):** a count, age (p50 and max) and owner for each reason,
  by unit, against peers.
- **Critical path (D-WF-02):** the median and p90 time in each stage, from
  workflow events.
  - The dominant stage is the one with the largest median share.
  - The bottleneck is the stage with the largest gap to the sibling median,
    when n is 20 or more.
- **Forecast:**
  - `days_to_clear = pending ÷ 28-day moving average of outflow`.
  - The range comes from the lowest and highest of the last four weekly
    rates.
  - A capacity ceiling (coders × their recent rate) is shown as an
    assumption, not mixed into the estimate.
  - "Does not clear" is flagged when the 28-day net inflow is above 0.
  - **Backtest:** weekly over the last 12 weeks, comparing each forecast
    with the actual pending 14 days later. It reports the share inside the
    range and the mean absolute error.
  - Suppressed under 20 cases.
- **Trend:**
  - A series with the change from the previous period, and the same period
    last year when 13 months of history exist.
  - The flag: rising or falling when the last-4-week mean differs from the
    prior 4 weeks by at least 10% and at least 5 cases; otherwise flat. No
    flag under n 20.
- **Gaps:**
  - web-intake interview start and end times;
  - death→interview, which exists only for register cases;
  - imported cases that have no events;
  - non-state blocker rows, which keep current values only;
  - C-21 history, not yet verified;
  - unit routing history and recode-window history;
  - no population figure, and no time on screen.

## Equity in the core

**Captured today:** sex, age band, district and block names from org-unit
ancestors, and register sex and date of death.

- **Core:** EQ-01 and EQ-02, both about composition and completeness.
- **Registered:** EQ-03, sex or age unknown, guards their validity.
- **Sex values are raw strings.** Normalise them to female, male and unknown
  in one place.
- **Later:** per-population rates and expected female share (DHS or SRS,
  `digitva-1835`), and SES, caste and education (`digitva-r9lk`).

## Registry

- **File:** `app/data/kpi_registry.json`. It uses only the stdlib and is
  loaded like the AI question catalog.
- **Fields:**
  - `id`, `name`, `question`;
  - `stage`, `category`, `type`;
  - `level[]`, `audience[]`, `cadence`;
  - `tier`, `merged_into`, `retired_reason`;
  - `views[]`;
  - `definition` (measure, base, canonical terms) and `helper`;
  - `unit`, `direction`, `thresholds`;
  - `peer`, `min_whole`, `cell_min`;
  - `periods[]`, `dimensions[]`;
  - `sources[]`, `replaces[]`;
  - `mcp` (full, totals_only or none) and `catalog_key`;
  - `policy_anchor` and `decisions[]`.
- **Drift test, no generator:**
  - every non-retired id has its heading in `kpis.md`, and every heading
    has an entry;
  - every helper imports;
  - every `catalog_key` and every `merged_into` target exists.
  
  The help page renders its KPI table from the registry.
- **Search:** a `kpi` kind in `ai_search_service`. Results link to
  `/help/kpis#<id>` and are restricted to DMs and admins.
- **AI questions:**
  - cube-answerable KPIs (O-UNK, EQ-01 to EQ-03, AD-FCOD, C-05, C-06,
    MO-01, D-LC-01) get `kpi_<id>` catalog entries;
  - event-based KPIs point to the dashboard or MCP, and the model's "not
    captured" list names them.

## MCP (minimal)

- **Where:** a Flask blueprint at `POST /api/v1/mcp`. It uses Streamable
  HTTP as plain JSON-RPC (`initialize`, `tools/list`, `tools/call`), hand
  written. No SDK and no SSE; move to the SDK if streaming or OAuth is
  needed.
- **Tools:**
  - `list_kpis(stage, category, level, audience, tier, q)`;
  - `describe_kpi(id)`, which includes the caller's scope summary;
  - `get_kpi_values(kpi_id, scope, period, compare, by, view)`. `scope`
    can only narrow the caller's own scope: anything outside it is a 403.
- **Auth: the caller's own grants, never a shared key.**
  - A personal token in a new `va_api_tokens` table: hashed, purpose
    `mcp_kpi_read`, expiring after at most 90 days, revocable, created
    after re-authentication and shown once.
  - Its own `before_request` branch for `/api/v1/mcp` only. Device tokens
    are refused there, and MCP tokens are refused everywhere else.
    `NATIVE_DEVICE_ROLES` is not widened.
  - The scope is resolved on every call, so a revoked grant takes effect
    immediately.
  - OAuth 2.1 is deferred.
- **Aggregates only:**
  - counts under 5 become `<5`, and a rate with a denominator under 20
    becomes null;
  - no names (entries marked `mcp: totals_only` or `none` return no
    per-person rows);
  - only cell-level suppression for now. Complementary suppression is
    needed if MCP output is ever published further.
- **Rate limits** per token user: 60 a minute overall, 20 a minute for
  `get_kpi_values`, and a daily cap.
- **Audit:** in `va_ai_query_audit_log`, with the mode CHECK widened to
  include `mcp_tool` in the same migration as the token table.

## Steps (replacing 0hul steps 2-8)

| Step | Work | Migration | Order |
|---|---|---|---|
| 0 | Policy: rewrite `kpis.md` as core and registered; add the new ids, the merges and the retirements; write the rules for the four views; add the MCP and token rules to `access-control-model.md` and the AI policy; mirror in current-state and help | No | First |
| 1 | Shared constants (done in 0hul step 1); reuse the suppression helpers | No | Done |
| 2 | Fix the core KPIs only, as `compute_*(scope, period, by)` in their modules, in groups a–g (flow, timeliness, blockers, workforce, quality, outcome and equity, critical path and coverage) | No | Groups in parallel after 1 |
| 3 | Views: one generic `series()`, the trend flag, the forecast with its backtest, blocker age, critical-path dominance | No | After 2(a) |
| 4 | Retire fixed panels, not endpoints: trim `dm_kpi_dashboard.js` to the core panels, keep every endpoint, update the help page | No | After 2, parallel with 3 |
| 5 | Registry JSON, drift test, the help page rendered from it, the `kpi` search kind and reindex, `kpi_<id>` catalog entries | No | Draft in parallel with 2 |
| 6 | MCP: token table and audit CHECK, token UI, auth branch, the three tools, suppression, limits and audit, with tests | **Yes** | After 2 and 5 |

**Do not:**
- delete non-core endpoints;
- schedule or backfill the aggregates;
- add the MCP SDK or new Typesense schema fields;
- give MCP tokens access to any other route;
- widen the native bearer roles.
