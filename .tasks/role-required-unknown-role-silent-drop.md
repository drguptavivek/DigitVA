---
title: role_required silently drops unknown role names
doc_type: task
status: open
owner: engineering
last_updated: 2026-09-19
---

# `role_required` silently drops unknown role names

## What

`app/decorators/role_required.py` looks each role name up in `_ROLE_METHODS`
and skips any name it does not find. A route gated only on names that are
absent therefore evaluates `any()` over an empty generator and refuses
everyone.

## Why it matters

The direction is right — it fails closed. The problem is that it fails
closed *silently*, so a typo'd role name is indistinguishable from a
deliberately locked-down route. Nothing logs, nothing raises, and the route
simply 403s every user forever.

This was found while wiring `collaborator` / `collaborator_pii`: at the
committed state neither name was in `_ROLE_METHODS`, so
`role_required("collaborator", "collaborator_pii")` on its own would have
403'd the data-management dashboard rather than widening it. The wiring
change adds both entries, so the live code is correct — but the next person
to add a role can make the same mistake and see a plausible-looking 403
instead of an error.

## Proposed fix

Raise at decoration time (import time) on a role name that is not in
`_ROLE_METHODS`. A bad name then breaks the app immediately and loudly,
rather than producing a route nobody can reach.

Check for existing routes gated on names not in the dict before doing this —
the raise will surface any that already exist, which is the point, but they
should be understood rather than discovered during a deploy.

## References

- `app/decorators/role_required.py` (`_ROLE_METHODS`, `role_required`)
- `docs/policy/access-control-model.md`
