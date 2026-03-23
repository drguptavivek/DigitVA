---
title: "Plan: Finalized Upstream Change Gap Closure"
doc_type: planning
status: draft
owner: engineering
last_updated: 2026-03-20
---

# Plan: Finalized Upstream Change Gap Closure

## Purpose

Close the remaining gaps between the current protected-state ODK sync behavior
and the intended policy for finalized submissions whose upstream ODK data
changes after finalization.

This plan covers the current implemented state key:

- `finalized_upstream_changed`

It also tracks the preferred future rename:

- `finalized_upstream_changed`

## Current Implemented Baseline

Today the runtime already does the following:

- treats finalized submissions as protected during ODK sync
- preserves active coding artifacts on protected-state ODK updates
- updates `va_submissions.va_data` to the new ODK payload
- transitions workflow to `finalized_upstream_changed`
- blocks automatic SmartVA regeneration while in the protected state
- exposes the state in the data-manager dashboard

## Remaining Gaps

### 1. No dedicated pre-update ODK payload snapshot

Current behavior overwrites `va_submissions.va_data` in place.

Needed:

- preserve the prior ODK payload before overwrite
- make the snapshot queryable and auditable by `va_sid`
- retain enough context to compare old vs new payloads

### 2. No explicit historical COD linkage for upstream-change review

Current behavior preserves active final-assessment rows by leaving them active,
but there is no dedicated upstream-change preservation pointer analogous to the
recode `base_final_assessment` concept.

Needed:

- explicit linkage to the previously authoritative final COD
- clear distinction between:
  - ordinary recode episode
  - upstream-change review state

### 3. No notification artifact

Current behavior logs and changes state but does not create a notification
record or queue entry for data managers/admins.

Needed:

- durable notification record
- enough context for dashboard/admin visibility
- deduplication rules for repeated upstream changes

### 4. Authorization mismatch

Policy target says only admins may resolve finalized-upstream-change
submissions.

Current implementation still allows data managers to:

- accept upstream change
- reject upstream change

Needed:

- align API and service authorization with the chosen policy
- if the product decision is to keep data-manager resolution, update policy
  explicitly instead of leaving the mismatch unresolved

### 5. State-name cleanup

`finalized_upstream_changed` is the adopted clearer state name.

Preferred target:

- internal state key: `finalized_upstream_changed`
- UI label: `Finalized - ODK Data Changed`

Needed:

- code rename plan
- data migration for existing workflow rows
- UI/filter/test/doc updates

## Desired State Summary

```text
coder_finalized -- ODK data changed during sync --> finalized_upstream_changed
                                                  UI: Finalized - ODK Data Changed

finalized_upstream_changed -- admin accepts upstream change --> smartva_pending
smartva_pending ----------- SmartVA generated / regenerated / recorded failure --> ready_for_coding
finalized_upstream_changed -- admin rejects upstream change --> coder_finalized

coder_finalized -- admin overrides final COD --> ready_for_coding
coder_finalized -- recode window expires automatically --> reviewer_eligible
```

Operational intent:

- protect finalized COD from automatic destruction
- preserve both the prior authoritative COD and the prior ODK payload
- require explicit operator resolution
- keep `ready_for_coding` as the re-entry queue when a case legitimately needs recoding
- require SmartVA rerun only when the accepted path introduces a changed
  payload; same-payload returns do not require SmartVA rerun

Out of scope for this specific gap plan:

- broader reviewer secondary-coding workflow after `reviewer_eligible`

`closed` is no longer the active post-24-hour target state in current runtime.

## Proposed Delivery Order

### Phase 1. Decide and lock the authorization baseline

Choose one and document it as final:

1. admin-only resolution
2. data-manager-plus-admin resolution

Then align:

- policy docs
- API guards
- service-level permission checks
- audit labels
- UI visibility and action affordances

### Phase 2. Preserve old payload before overwrite

Add an upstream-change snapshot model/table that stores:

- `va_sid`
- old ODK payload
- new ODK payload reference or hash
- detection timestamp
- triggering sync metadata
- workflow state at the moment of detection

### Phase 3. Add explicit preserved-final-COD linkage

Model the authoritative final COD that was in effect when the upstream change
was detected.

This should be queryable without inferring from whatever rows happen to remain
active later.

### Phase 4. Add notification artifact and queue surfaces

Create a durable notification model and expose it in:

- data-manager dashboard
- admin operational view

### Phase 5. Rename state key

Rename:

- migration/backfill completed from `revoked_va_data_changed` -> `finalized_upstream_changed`

Update:

- workflow constants
- sync logic
- data-manager filters
- analytics queries
- tests
- docs

Do this only after the preservation and authorization behavior is stable, so
the rename does not obscure functional gaps.

### Phase 6. Verify SmartVA and dashboard behavior after resolution

Confirm:

- SmartVA is still blocked while the case is in the protected upstream-change state
- accept path returns the case to `smartva_pending` and then `ready_for_coding`
- reject path keeps the prior COD authoritative
- dashboard counts, filters, and labels use the resolved state name consistently

## Risks

- historical-data loss if payload snapshots are added incorrectly
- ambiguous authority if preserved final COD is inferred instead of modeled
- user confusion if state rename happens before UI labels are aligned
- authorization drift if docs and routes are changed in separate releases

## Verification

Required verification before closing this gap set:

1. finalized submission receives upstream ODK change
2. prior payload is recoverable
3. prior authoritative final COD is recoverable
4. notification is visible to intended operator roles
5. SmartVA does not auto-regenerate while protected
6. accept/reject authorization matches documented policy
7. dashboard filters and counts reflect the finalized-upstream-change state
8. admin override and recode-window auto-close remain distinct from upstream-change handling
