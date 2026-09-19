---
title: The PII field set fails open for any non-WHO questionnaire
doc_type: task
status: done
owner: engineering
last_updated: 2026-09-19
---

# The PII field set fails open for any non-WHO questionnaire

Raised by the audit session after the viewer-role work landed. Both items
below were verified against the tree at `44ffbeb`.

## 1. A new form type gets no PII flags, and nothing says so

`PII_FIELDS` in `app/services/pii_field_registry.py:124` is a flat
`field_id -> pii_type` map keyed on **WHO instrument field ids** (`Id10017`,
`Id10073`, and so on). `apply_pii_field_registry` applies it to *every* active
form type, and the module comment states the property outright: it is "not
gated on the form type already having any of these WHO instrument field ids."

So for a questionnaire whose field ids differ — PHMRC and Ballabgarh are
planned via `xlsform_instrument_builder.py` — the registry creates
redaction-only rows for WHO ids the form does not contain, and **the form's
own name and identifier fields are never flagged**. Its names and national
IDs then export unredacted.

This matters more than it did. `mas_field_display_config.is_pii` is now the
single source of truth behind the `collaborator` / `collaborator_pii` split
and five redaction surfaces. An empty flag set does not read as "unconfigured",
it reads as "nothing here is personal data".

**Fail closed.** Either refuse to activate a form type with zero `is_pii` rows,
or surface a standing admin warning until someone confirms the set for that
form type. Silence is currently indistinguishable from a deliberate answer.

Not established: nobody has run a PHMRC import and watched it happen. What is
established is that nothing prevents it.

### Done (2026-09-19)

"Zero `is_pii` rows" turned out to be a vacuous test — the registry creates
rows for every form type — so confirmation is derived instead: a form type is
confirmed when at least one row it *owns* (`subcategory_code IS NOT NULL OR
odk_label IS NOT NULL OR is_custom = false`) is flagged. No migration.
`FieldMappingService.get_pii_set_status()`. Unconfirmed withholds the whole
payload at both redaction sites, and the admin panel, `GET
/admin/api/form-types` and `flask form-types stats` carry the warning.
Activation is deliberately *not* blocked: it would break register -> sync ->
flag, since a form type has no fields at registration time.

## 2. The PII set is cached per process, with no invalidation

`FieldMappingService.get_pii_field_ids()` (`app/services/field_mapping_service.py:92`)
memoizes into `self._cache` under `pii_field_ids_<form_type_code>`. A repo-wide
grep finds no `cache_clear` anywhere, and `apply_pii_field_registry` clears only
the process that calls it.

So a flag change made by an admin edit, or by a Celery-run sync, does not reach
a running web worker until it restarts. That was a minor note when redaction
meant one CSV export. It is now the control behind "viewer without PII", and a
stale cache there means a viewer keeps seeing a field that was just flagged.

Fix: key the cache on the newest `mas_field_display_config.updated_at` for the
form type, or drop the cache for this one query and measure before adding it
back.

### Done (2026-09-19)

Version-keyed on `(count(*), max(updated_at))` over the form type's
`mas_field_display_config` rows, re-checked per call. The count is there
because deleting a row does not move `max(updated_at)`. Only the PII set is
versioned; the other caches on the service still rely on `clear_cache()`.

## Related, same shape

Nothing stops a migration from calling live application code. The
`mas_org_unit` break came from four historical migrations calling
`build_submission_analytics_core_mv_sql()`. `grep` finds 15 migration files
importing from `app.*`; most are probably model or enum imports, but nobody has
swept them. A lint flagging `app.services` imports inside `migrations/versions`
would close it, paired with the empty-database `flask db upgrade` replay that
is now known to work.

Still open, moved to `.tasks/migrations-importing-app-code.md`.
