---
title: Signed-in Organization Demo
doc_type: policy
status: active
owner: engineering
last_updated: 2026-10-19
---

# Signed-in organization demo

The demonstration uses a separate synthetic organization project and ordinary
signed-in interviewer, coder, reviewer and data-manager accounts. It does not
reuse or reset TST001, grant anonymous access, or bypass authorization. Demo
content is visibly synthetic and must never contain real clinical data.

## Reset scope and time

Reset demonstration work every Sunday at 23:00 Asia/Kolkata (17:30 UTC).
Preserve the project settings, organization, units, cadres, workers, accounts,
credentials, device enrollment and grants. Restore the documented synthetic
starting cases so each role has a useful demonstration after the reset.

The reset requires both an exact configured project ID and an explicit
database opt-in on the project. Neither a project name nor the older coding
practice flag alone authorizes deletion. Projects with ODK synchronization
are ineligible. The weekly project does not use the short coding-practice
retention mode, whose separate behavior remains unchanged.

## Data protection and execution

Before any reset deletion, obtain a verified database backup and record its
identity, size and checksum with the reset audit. A failed backup prevents
reset. Preserve attachment objects through the recovery window; reset removes
their demo references, not their recoverable bytes. A documented recovery path
must exist before enabling the reset in an environment.

The reset is project-scoped, auditable and idempotent per scheduled week.
Concurrent reset jobs must not run together, and demo writes must be safely
excluded during reset. Unknown database dependencies, an invalid target,
backup failure or a reseed failure must leave the demo data intact. Never
truncate shared tables, disable constraints or cascade deletion to another
project. Log counts and short error codes rather than record contents.

## Discoverability and activation

An authenticated demo guide links each role to its real app surface and
explains the weekly reset. Credentials are supplied only through the intended
demo setup, never published for unrelated existing accounts. Deployment
activation requires the explicit demo configuration and seed; deploying code
does not turn on destructive scheduling for existing projects.
