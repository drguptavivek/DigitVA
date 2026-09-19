---
title: Migration Chaining Policy
doc_type: policy
status: active
owner: engineering
last_updated: 2026-09-19
---

# Migration Chaining Policy

## Purpose

Several people and sessions write Alembic migrations against this repository
at the same time. Three separate incidents on 2026-09-18 came from the same
root: a migration chained onto a revision that existed only in somebody's
working tree. One of them left `origin/main` unable to run `flask db upgrade`
at all, and therefore unbootable, since `boot.sh` runs it on every deploy.

These rules are those incidents generalised. They are not about Alembic
mechanics; they are about the difference between what your working tree can
see and what a fresh clone can see.

This repository is also worked on by several sessions in one shared
checkout. The companion rules for that are in
[Shared Working Tree Policy](shared-working-tree.md); rule 1 there is the
same hazard as rule 1 here, in a different medium.

## Rules

### 1. Chain only onto a COMMITTED revision

Before writing a migration, `git fetch`, then determine the head **as
committed on origin/main**.

Do NOT use `flask db heads` to decide this. It reads your working tree and
will happily report an untracked file belonging to another session as the
head. A migration whose `down_revision` names a revision that is not on
origin cannot resolve for anyone who clones — the chain has a dangling
parent, and `flask db upgrade` fails outright.

To find the committed head, read the committed files, not the tree:

```bash
git worktree add -q --detach /tmp/chaincheck origin/main
```

then walk `migrations/versions/*.py` in that worktree.

### 2. If two heads appear locally, the UNCOMMITTED one re-chains

Never the committed one. A committed migration has already been pulled by
others and may have been applied; re-parenting it rewrites history that has
left the building.

This asymmetry is deliberate: the cost falls on the work that has not landed.
Expect an uncommitted migration to be re-chained several times while it
waits.

### 3. Whoever commits second re-chains FIRST, not after

Once pushed, rule 2 makes it expensive to move.

### 4. Two local heads are a normal state, not a defect

Which means **tooling must cope with it**. Anything that applies migrations
in a test or a script has to use `upgrade(revision="heads")` rather than a
bare `upgrade()`, or it fails routinely on the state this policy calls
correct. `tests/migrations/test_schema_drift.py` did exactly that until
2026-09-18.

A check that is expected-red whenever the documented-correct state obtains
stops being informative: people learn to ignore it, and it then fails to
report the case it exists for. That is rule 5's hazard arriving from the
opposite direction — a check nobody trusts is as useless as one that cannot
fail.


Two independent uncommitted migrations sharing a committed parent is the
correct shape. Do not "resolve" it by chaining one onto the other while both
are untracked — that is rule 1's failure, reintroduced. `flask db upgrade
heads` works meanwhile, and the heads collapse as the work lands.

### 5. A working-tree check cannot verify any of this

Anything that reads the live tree — `flask db heads`, the schema-drift test,
an empty-database replay run in place — resolves through untracked files. It
will pass while `origin/main` is broken. A check that cannot fail for the
thing it appears to test is worse than no check, because it is trusted.

Verification must read the committed ref: a detached `git worktree`, or
`git show origin/main:<path>`.

Two practical traps when writing such a check, each of which produced a
confident, specific, wrong answer on 2026-09-18:

- **Tuple parents.** Merge migrations use `down_revision = ("a", "b")`. Parse
  every quoted string on the line, not the first.
- **Non-hex revision ids.** Some revisions are slugs (`n1lhxggm3txo`,
  `add_nqa_cannot_grade`). Do not assume hex.

Both mistakes fabricate phantom heads, and a false alarm about a broken chain
is what sends somebody re-chaining migrations that were fine.

### 6. The stronger check is that it BOOTS, not that the graph is valid

A chain can be graph-valid and still fail to run. Where it matters, run an
actual `flask db upgrade` from an empty database against the committed
migrations only:

```bash
flask db --directory <worktree>/migrations upgrade
```

`--directory` lets this read the worktree without touching the live
`migrations/` folder.

### 7. A migration must never import application code

No file under `migrations/versions` may import `app` or any `app.*` module.
A migration is a historical record: it must mean the same thing on a fresh
clone in a year that it meant the day it was reviewed. Calling application
code pins it to whatever that code means *today* instead, and the revision
silently starts doing something else. The `mas_org_unit` break was exactly
this — historical revisions calling
`build_submission_analytics_core_mv_sql()` while the service grew columns
underneath them.

A materialized-view rebuild therefore **copies the SQL into the migration**.
Duplicated SQL that is frozen is correct here; a shared builder that drifts
is not. This is the one place in the repository where copying beats reuse.

Fifteen historical migrations predate this rule, all importing MV SQL
builders from `app.services.submission_analytics_mv`. They are pinned by
filename and by the exact set of names each one imports in
`tests/migrations/test_no_app_imports_in_migrations.py`. A pin may be
**removed by inlining** that migration's SQL; it must never be extended, and
no new file may be added to the list. The test fails on an unpinned import,
on a pin that grew, and on a pin that has gone stale.

Its pairing check is `tests/migrations/test_schema_drift.py`, which replays
the whole chain into a throwaway empty database and compares the result with
the models. That one proves the chain still runs; rule 7's test proves it
still means what it said.

## What a healthy chain looks like

As of 2026-09-18, on `origin/main`: no dangling parents, exactly one head,
exactly one root.
