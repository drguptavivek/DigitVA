# Above-scope view-only access to COD and submission data

- Status: pending
- Priority: high
- Created: 2026-09-18

## Goal

A coder or reviewer granted at a unit **above** the project's coding scope
level, where `above_scope_coding_mode = 'view_only'`, should see the cause of
death and the submission data for their subtree, read-only. Today they see
nothing at all.

## Decision (2026-09-18)

`view_only` means: sees COD and data, codes nothing. Phase 4 implemented only
the second half — `codeable_unit_ids` returns an empty set for such a grant,
so the pick list, the dashboard counts and the per-submission gate all exclude
the whole subtree.

## Context

Phase 4 of the organization model
(`docs/current-state/health-system-organization-model.md`,
`docs/policy/organization-model.md#coding-scope`). The coding scope rule lives
in `app/services/org_grant_service.py::codeable_unit_ids`; the list filter in
`app/services/coder_workflow_service.py::_org_unit_scope_filter`; the
per-submission gate in `app/services/org_grant_service.py::submission_within_org_scope`,
called from `app/decorators/va_validate_permissions.py`.

## Expected Scope

- a **viewable** unit set beside the codeable one: the grant's whole subtree,
  regardless of the scope level, for roles that may view
- a read-only submission view for those units — the existing data-manager
  read-only view (`/data-management/view/<va_sid>`) is the closest precedent
  and may be reusable rather than building a second one
- the coding surfaces must stay unchanged: a `view_only` grant must not make a
  submission codeable, allocatable, or offered in the pick list
- decide whether a `view_only` holder sees uncoded submissions too (the
  decision says "COD and data", which reads as both coded and uncoded)
- tests: a grant above the scope level sees its subtree read-only and cannot
  code it; a grant at or below is unchanged; a project without a tree is
  unaffected

## Risks

Authorization surface. The viewing path must not reuse the codeable set, or a
viewer becomes a coder. Keep the two sets separate and named differently.
