"""Every reader of coding state applies the confirmed-duplicate predicate.

Rule: a web case confirmed as a duplicate leaves every allocation, list,
count, export and analytics path through ONE predicate,
``app.services.duplicate_exclusion`` (docs/policy/coding-workflow-state-machine.md,
"Confirmed duplicate cases"). This guard makes "forgot the predicate" a test
failure instead of a silent leak.

How: sweep every function in ``app/`` with ``ast``. A function whose source
names coding workflow state or an analytics materialized view is a *reader*.
Each reader must

  - apply the predicate itself (``not_confirmed_duplicate_condition``,
    ``is_confirmed_duplicate`` or the raw-SQL ``_NOT_DUPLICATE_SQL``), or
  - call a ``COVERED_HELPERS`` function, each of which is itself checked to
    apply the predicate, or
  - sit on ``EXEMPT`` with the reason it is not a reader in this sense
    (a writer, a single-submission lookup behind an allocation, an MV
    definition, ...).

A new reader has exactly those three outcomes; "undecided" fails, naming it.
A stale ``EXEMPT`` or ``COVERED_HELPERS`` key (gone, no longer a reader, or
now applying the predicate) fails too, so the lists cannot rot.

A second check covers raw SQL: every ``AND {_IN_ODK_SQL}`` line (the
ODK-retirement reader rule, applied to the same readers) must be followed by
the duplicate rule, so a multi-CTE query cannot filter one CTE and leak
another.

ponytail: textual, not semantic. A reader that merely *names* a covered
helper passes, and one that reads coding state without naming it (a column
alias, a dynamic table name) is not seen. Upgrade path: route every coding
reader through one query builder and assert on the compiled SQL.
"""

import ast
import pathlib
import re

APP = pathlib.Path(__file__).resolve().parent.parent / "app"

#: Names coding workflow state or an analytics materialized view.
READER_PATTERN = re.compile(
    r"workflow_state|VaSubmissionWorkflow\b|va_submission_workflow"
    r"|_MV_NAME\b|va_submission_analytics|va_submission_cod_"
)
PREDICATE_PATTERN = re.compile(
    r"not_confirmed_duplicate_condition|is_confirmed_duplicate|_NOT_DUPLICATE_SQL"
)

#: Shared builders that apply the predicate for their callers.
COVERED_HELPERS = frozenset({
    "services/coder_workflow_service.py::_available_submission_filters",
    "services/coder_workflow_service.py::get_pick_available_forms",
    "services/submission_analytics_mv.py::_mv_scope_filter",
    "services/submission_analytics_mv.py::build_dm_mv_filter_conditions",
    "services/data_management_service.py::_dm_submission_query_parts",
    "services/sitepi_reporting_service.py::_workflow_kpis",
    "routes/api/analytics.py::_dm_scope_filter",
})

_WRITER = "writer of workflow state; readers exclude the submission, writers keep it consistent"
_ONE_ROW = "acts on one named submission behind an active allocation, revoked on confirmation"
_MV_DDL = "materialized-view definition or refresh; exclusion is applied at query time"
_SYNC = "ODK sync / payload maintenance; must keep a duplicate's data current for a reopen"

EXEMPT = {
    "models/va_submission_workflow.py::VaSubmissionWorkflow.__repr__": "debug repr",
    "routes/admin.py::_project_has_in_progress_coding": (
        "safety guard on COD-mode changes: a duplicate's coding resumes on reopen, so it must "
        "still block"
    ),
    "routes/api/coding.py::admin_override_recode": (
        "thin route over admin_override_to_recode, which refuses a confirmed duplicate"
    ),
    "routes/api/dm_kpi/dm_kpi_grid.py::daily_grid": (
        "dispatcher; its live queries (_grid_from_*) apply the predicate, the aggregate table "
        "is pre-counted (see va_daily_kpi_aggregates follow-up)"
    ),
    "routes/api/reviewing.py::finalize": _ONE_ROW,
    "routes/va_form.py::renderpartial": (
        "renders one submission a user already reached through an allocation or view grant"
    ),
    "services/case_transition_service.py::_needs_data_manager": (
        "reads one case's coding state to decide who may confirm it"
    ),
    "services/coding_allocation_service.py::cleanup_expired_demo_coding_artifacts": (
        "demo-retention cleanup of expired demo coding, not a reader"
    ),
    "services/data_management_service.py::_submission_analytics_mv_available": "to_regclass probe",
    "services/data_management_service.py::_submission_cod_snapshot_mv_available": "to_regclass probe",
    "services/data_management_service.py::dm_upstream_change_details": (
        "one named submission's upstream diff for its data manager"
    ),
    "services/data_management_service.py::dm_screening_pass": _WRITER,
    "services/data_management_service.py::dm_screening_reject": _WRITER,
    "services/data_management_service.py::dm_accept_upstream_change": _WRITER,
    "services/data_management_service.py::dm_keep_current_icd_on_upstream_change": _WRITER,
    "services/open_submission_repair_service.py::_advance_workflow_after_current_payload_repair": _SYNC,
    "services/payload_enrichment_backfill_service.py::_run_single_submission_workflow_transition": _SYNC,
    "services/payload_enrichment_backfill_service.py::_find_transition_eligible_rows": _SYNC,
    "services/payload_enrichment_backfill_service.py::_run_workflow_transition_stage": _SYNC,
    "services/reviewer_coding_service.py::submit_reviewer_final_cod": _ONE_ROW,
    "services/reviewer_coding_service.py::submit_reviewer_initial_cod": _ONE_ROW,
    "services/smartva_service.py::_transition_to_ready_after_smartva_if_pending": _WRITER,
    "services/smartva_service.py::_transition_to_ready_after_smartva_failure_if_pending": _WRITER,
    "services/smartva_service.py::repair_protected_current_payload_smartva": (
        "rebinds existing SmartVA history to the current payload; generates nothing"
    ),
    "services/submission_analytics_mv.py::build_submission_analytics_core_mv_sql": _MV_DDL,
    "services/submission_analytics_mv.py::build_submission_analytics_demographics_mv_sql": _MV_DDL,
    "services/submission_analytics_mv.py::build_submission_cod_detail_mv_sql": _MV_DDL,
    "services/submission_analytics_mv.py::build_submission_cod_snapshot_mv_sql": _MV_DDL,
    "services/submission_analytics_mv.py::build_submission_analytics_mv_sql": _MV_DDL,
    "services/submission_analytics_mv.py::refresh_submission_analytics_mv": _MV_DDL,
    "services/submission_analytics_mv.py::ensure_submission_cod_snapshot_mv": _MV_DDL,
    "services/submission_analytics_mv.py::area_breakdown_columns": (
        "column builder; its callers scope through build_dm_mv_filter_conditions"
    ),
    "services/submission_analytics_mv.py::_core_table_with_org_unit": (
        "table reference; its callers scope through build_dm_mv_filter_conditions"
    ),
    "services/va_data_sync/va_data_sync_01_odkcentral.py::_handle_protected_submission_update": _SYNC,
    "services/va_data_sync/va_data_sync_01_odkcentral.py::_workflow_state_for_consent": _SYNC,
    "services/va_data_sync/va_data_sync_01_odkcentral.py::_upsert_form_submissions": _SYNC,
    "services/va_data_sync/va_data_sync_01_odkcentral.py::_finalize_enriched_submissions_for_form": _SYNC,
    "services/workflow/definition.py::coding_bucket": "pure state -> bucket mapping",
    "services/workflow/state_store.py::get_submission_workflow_record": _WRITER,
    "services/workflow/state_store.py::set_submission_workflow_state": _WRITER,
    "services/workflow/state_store.py::infer_workflow_state_from_legacy_records": _WRITER,
    "services/workflow/state_store.py::infer_workflow_state_after_coding_release": _WRITER,
    "services/workflow/state_store.py::sync_submission_workflow_from_legacy_records": _WRITER,
    "services/workflow/state_store.py::get_submission_workflow_state": (
        "one submission's state; the allocating callers ask is_confirmed_duplicate"
    ),
    "services/workflow/transitions.py::_apply_transition": _WRITER,
    "services/workflow/transitions.py::_apply_release_reset_transition": _WRITER,
    "services/workflow/upstream_changes.py::record_protected_upstream_change": _SYNC,
    "tasks/sync_tasks.py::_refresh_batch_plan_after_enrichment": _SYNC,
    "tasks/sync_tasks.py::refresh_submission_analytics_mv_task": _MV_DDL,
    "utils/va_permission/va_permission_07_ensurenotreviewed.py::va_permission_ensurenotreviewed": _ONE_ROW,
    "utils/va_permission/va_permission_10_reviewedonce.py::va_permission_reviewedonce": _ONE_ROW,
}


def _functions():
    """Yield (key, source) for every module-level function and method in app/.

    Nested functions belong to their enclosing function's source, so a
    ``compute`` closure is judged with the route that owns it.
    """
    for path in sorted(APP.rglob("*.py")):
        source = path.read_text()
        lines = source.splitlines()
        relative = path.relative_to(APP).as_posix()

        def visit(node, prefix):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    yield from visit(child, f"{prefix}{child.name}.")
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    body = "\n".join(lines[child.lineno - 1:child.end_lineno])
                    yield f"{relative}::{prefix}{child.name}", body

        yield from visit(ast.parse(source), "")


FUNCTIONS = dict(_functions())
_HELPER_NAMES = {key.rsplit("::", 1)[1] for key in COVERED_HELPERS}
_HELPER_CALL = re.compile(r"\b(" + "|".join(sorted(_HELPER_NAMES)) + r")\(")


def _applies(source: str) -> bool:
    # Skip the ``def`` line, so a helper's own name does not count as a call.
    body = source.split("\n", 1)[-1]
    return bool(PREDICATE_PATTERN.search(body) or _HELPER_CALL.search(body))


def test_every_covered_helper_applies_the_predicate():
    for key in sorted(COVERED_HELPERS):
        assert key in FUNCTIONS, f"COVERED_HELPERS names a missing function: {key}"
        assert _applies(FUNCTIONS[key]), f"{key} is listed as covered but applies no predicate"


def test_every_coding_state_reader_applies_the_predicate_or_is_exempt():
    readers = {key for key, source in FUNCTIONS.items() if READER_PATTERN.search(source)}
    # Presence first: the sweep must see the readers this rule exists for.
    assert "services/coder_workflow_service.py::allocate_random_form" in readers
    assert "services/submission_analytics_mv.py::get_dm_kpi_from_mv" in readers

    missing = sorted(
        key for key in readers - EXEMPT.keys() if not _applies(FUNCTIONS[key])
    )
    assert not missing, (
        "These functions read coding state but skip the confirmed-duplicate predicate "
        "(app/services/duplicate_exclusion.py). Apply it, or add the function to EXEMPT "
        "with the reason it is not a reader:\n  " + "\n  ".join(missing)
    )


def test_exempt_list_has_no_stale_entries():
    stale = sorted(key for key in EXEMPT if key not in FUNCTIONS)
    assert not stale, "EXEMPT names functions that no longer exist:\n  " + "\n  ".join(stale)
    not_readers = sorted(key for key in EXEMPT if not READER_PATTERN.search(FUNCTIONS[key]))
    assert not not_readers, "EXEMPT names functions that no longer read coding state:\n  " + "\n  ".join(not_readers)
    applying = sorted(key for key in EXEMPT if key in FUNCTIONS and PREDICATE_PATTERN.search(FUNCTIONS[key]))
    assert not applying, "EXEMPT names functions that now apply the predicate:\n  " + "\n  ".join(applying)


def test_every_raw_sql_odk_filter_is_paired_with_the_duplicate_filter():
    checked = 0
    unpaired = []
    for path in sorted(APP.rglob("*.py")):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            match = re.fullmatch(r"(\s*)AND \{_IN_ODK_SQL(_S2)?\}", line)
            if not match:
                continue
            checked += 1
            expected = f"{match.group(1)}AND {{_NOT_DUPLICATE_SQL{match.group(2) or ''}}}"
            if index + 1 >= len(lines) or lines[index + 1] != expected:
                unpaired.append(f"{path.relative_to(APP)}:{index + 1}")
    assert checked, "the sweep found no raw-SQL reader; the pattern no longer matches"
    assert not unpaired, "Raw SQL filters retired rows but not duplicates:\n  " + "\n  ".join(unpaired)
