# digitva-qwvt: AI analytics studio (discuss first)

Status: plan only, nothing built. The source is a Gemini-written spec that the owner pasted on 2026-10-27.

## Gating owner decision

The spec sends up to 200 result rows to Google Vertex AI in Stage B, and the
Stage A prompts are free text. A query such as `SELECT * FROM <view>` returns
submission id, site, date, sex, age group and cause of death. Those are
quasi-identifiers, not aggregates, which makes Google a data processor for
VA mortality data. `docs/policy/pii-encryption-at-rest.md` still leaves the
DPDP-for-the-deceased question open.

The owner chooses one of:

1. No external LLM. Ship only the deterministic parts: saved and pinned
   queries, drill-downs and charts over the existing analytics MVs.
2. Gemini sees aggregates only. The sandbox requires `GROUP BY`, applies a
   minimum cell size and a row cap, and never sends raw rows. Stage B gets
   only aggregated rows.
3. Gemini sees scoped rows, as the spec says.

Whichever is chosen goes into a `docs/policy` baseline before any code.

## Proposed v1 slice (if 1 or 2)

- Views are built on the existing MVs in
  `app/services/submission_analytics_mv.py` (core, demographics, COD detail,
  COD snapshot), not on base tables. A read-only role is granted SELECT on
  those views only.
- Scope comes from the existing services (`org_grant_service.scope_unit_ids_for_roles`,
  `access_summary_service`), not a new permission resolver. It is resolved for
  the caller on every run and never stored with a saved query.
- The guard is the database, not a regex: `SET LOCAL TRANSACTION READ ONLY`,
  `SET LOCAL ROLE`, `statement_timeout`, a server row cap and grants that
  reach only the views. A string check stays as a cheap first filter only.
- Saved queries store `validated_sql` and a layout recipe, and rerun with no
  LLM call.
- The existing `api/analytics.py` endpoints and the ag-grid vendor stay in
  place. Choose one vendored chart library; ECharts is not vendored today.

## Cut from the spec

- Typesense: `pg_trgm` is already enabled (two migrations), and the spec
  says itself that the trigram fallback works with no extra service.
- `flask ai-catalog generate`: a second LLM pipeline with no value until the
  core works.
- 16 built-in patterns: start with 2–3 that mirror existing reports.
- The 5-turn breadcrumb popover, floating pill and offcanvas: build after the
  slice has users.

## Spec defects to correct

- Ids: `va_users.user_id` is a UUID and `va_sites.site_id` is a string, but
  the spec uses Integer FKs.
- Roles: the quota table names `superadmin` and `mentor`, and neither exists
  (`app/models/va_selectives.py`). Users hold several grants, so the quota is
  the maximum over their roles.
- Tables: use the `va_ai_*` prefix, not bare `ai_*`.
- `gen-lang-client-0562123691` must not be a code default; read it from the
  environment through the existing secrets path.
- Migration: the role creation must tolerate parallel test workers
  (`EXCEPTION WHEN duplicate_object`), and downgrade must not
  `DROP ROLE`, since roles are cluster-wide. Staging migrations need
  CREATEROLE, or a pre-created role; check before relying on it.
- `md5(user_id)` pseudonyms are stable, so results can be linked across
  queries. Record this in the policy.
- The model ids (`gemini-3-flash-preview`, `gemini-3.1-pro-preview`) and the
  `thinking_budget` semantics come from model output. Verify them against
  current Vertex docs at build time.

## Open question

Would the existing reports plus CSV export serve these users just as well?
Confirm who would use NL questions before building the studio.
