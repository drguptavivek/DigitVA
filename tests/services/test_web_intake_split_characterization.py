"""Characterization of app.services.web_intake_service before its split into
app/services/web_intake/ (digitva-r8nh.12): the facade keeps every name, and
the names tests patch still reach their callers through the facade.
"""
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services import web_intake_service as intake_svc
from tests.base import BaseTestCase
from tests.services import test_web_intake_service as intake_tests

#: Every public and private name the module exposed before the split.
FACADE_NAMES = (
    "ATTACHMENT_REFERENCE_PREFIX",
    "AUDIT_ROLE",
    "Action",
    "CANDIDATES_MAX",
    "CASE_CLOSED_MESSAGE",
    "CASE_STATES",
    "CHOICE_REASONS",
    "CODING_TIMELINE_EVENTS",
    "CONTACT_OUTCOMES",
    "DEATH_NUMBER_SEQUENCE",
    "DEATH_REGISTERING_ROLES",
    "DEATH_SEX_VALUES",
    "DEFAULT_INTAKE_NOTE",
    "DEFAULT_LOCALE",
    "DETAILS_EDITED",
    "DEVICE_ANSWERS_MAX_BYTES",
    "DEVICE_ANSWERS_MAX_DEPTH",
    "DEVICE_SECTION",
    "DUPLICATE_CANDIDATES_MAX",
    "DUPLICATE_CASE_STATUS",
    "EDITOR_OWNER",
    "EDITOR_SUPERVISOR",
    "EXCLUDED_HOLDS",
    "FINAL_SECTION",
    "HISTORY_SECTION",
    "IDENTIFIER_CLOSED_STATES",
    "IDENTIFIER_FORBIDDEN_MESSAGE",
    "IDENTITY_FROM_INTERVIEW",
    "INSTRUMENT_ID",
    "INTERVIEW_CHOSEN_REASON",
    "INTERVIEW_TIMELINE_EVENTS",
    "LOCATION_FIELDS",
    "MapCaseContactAttempt",
    "MapCaseTransition",
    "MasOrgLevel",
    "MasOrgUnit",
    "OUTCOME_CASE_STATES",
    "PARTIAL_BIRTH_MIN_YEAR",
    "PAUSE_REASONS",
    "PAYLOAD_ROLE",
    "PREFILL_ANSWER_FIELDS",
    "PREFILL_LOCKED_FIELDS",
    "PROTECTED_WORKFLOW_STATES",
    "REGISTER_FIELDS",
    "REPORTED_PAGE_DEFAULT",
    "REPORTED_PAGE_MAX",
    "RESUBMITTED_REASON",
    "REVISION_REASONS",
    "SOURCE_INTERVIEWER_REVISION",
    "SOURCE_SUPERVISOR_CHOICE",
    "SOURCE_SUPERVISOR_REVISION",
    "SUPERSEDED_BY_SUPERVISOR_REVISION",
    "SUPERVISED_ROW_PII",
    "SUPERVISION_SORTS",
    "SUPERVISION_STUCK_DAYS",
    "SUPERVISOR_CORRECTION_REASON",
    "SYNC_MESSAGE",
    "UPSTREAM_CHANGE_STATUS_REJECTED",
    "USER_SEX_VALUES",
    "UTC",
    "VaAccessRoles",
    "VaDeathRegister",
    "VaForms",
    "VaProjectMaster",
    "VaProjectSites",
    "VaSiteMaster",
    "VaStatuses",
    "VaSubmissionPayloadVersion",
    "VaSubmissionWorkflow",
    "VaSubmissions",
    "VaSubmissionsAuditlog",
    "VaUsers",
    "VaWebIntakeAttachment",
    "VaWebIntakeDraft",
    "VaWebIntakeDraftSection",
    "WEB_INTAKE_MODES",
    "WEB_PROJECT_DEFAULTS",
    "WORKFLOW_FINALIZED_UPSTREAM_CHANGED",
    "WORKFLOW_READY_FOR_CODING",
    "WORKFLOW_REVIEWER_CODING_IN_PROGRESS",
    "WORKLIST_PAGE_DEFAULT",
    "WORKLIST_PAGE_MAX",
    "WORKLIST_SORTS",
    "WebIntakeError",
    "WorkflowTimelineError",
    "WorkflowTransitionError",
    "_ABHA_ADDRESS_RE",
    "_ABHA_NUMBER_RE",
    "_ADDRESS_ATTRS",
    "_AGE_INFO_FIELDS",
    "_CASE_DETAIL_HIDDEN",
    "_CHANGE_CHANNELS",
    "_CLOCK_BLOCK_SECONDS",
    "_CLOSED_WRITER_ROLES",
    "_CODING_STATUS",
    "_CODING_TIMELINE_CLIENT_EVENTS",
    "_CODING_TIMELINE_MAX",
    "_CODING_TIMELINE_META_KEY",
    "_COMPOSED_VERSION_RE",
    "_DEATH_REPORTER",
    "_DEFINITION_IDENTITY_KEYS",
    "_DEVICE_TIME_KEYS",
    "_ENVELOPE_META_KEYS",
    "_EPOCH",
    "_EXTENSION_NAME_RE",
    "_FALSE",
    "_FUTURE_TOLERANCE",
    "_INCOMPLETE_OUTCOMES",
    "_INTERVIEWER",
    "_INTERVIEWER_AGE_RANGE",
    "_INTERVIEWER_ANSWER_KEYS",
    "_INTERVIEWER_NAME_RE",
    "_LEGACY_STATUS",
    "_LOCALE_CODE_RE",
    "_MAX_CLOCK_OFFSET_SECONDS",
    "_MAX_DEFINITION_EXTENSIONS",
    "_PARTIAL_DATE_RE",
    "_PHONE_FIELDS",
    "_PLACE_OF_DEATH_CHOICES",
    "_PLACE_OF_DEATH_KEYWORDS",
    "_SECTION_NAME_RE",
    "_SHA256_RE",
    "_STARTABLE_STATES",
    "_SUPERSEDED_CASE_STATES",
    "_SUPERVISION_OPEN_STATES",
    "_TIMELINE_META_KEY",
    "_TRUE",
    "_VISIT_AHEAD",
    "_VISIT_PAST",
    "_VISIT_STATES",
    "_after_reported_cursor",
    "_after_worklist_cursor",
    "_allocate_unique_id",
    "_answers_of",
    "_approximate_date_of_death",
    "_assigned_only",
    "_audit_details_change",
    "_begin_interview",
    "_birth_age_from_answers",
    "_candidate_completed_at",
    "_candidate_condition",
    "_case_address",
    "_check_attachment_draft_matches",
    "_clean",
    "_clean_abha",
    "_clean_date",
    "_clean_death_fields",
    "_clean_locale_meta",
    "_clean_location",
    "_clean_number",
    "_clean_partial_birth",
    "_clean_phone",
    "_clean_visit_at",
    "_clock_meta",
    "_code_now",
    "_code_now_unit_ok",
    "_completion_time",
    "_correct_register_fields",
    "_current_prefill",
    "_decode_cursor",
    "_device_completion",
    "_device_time",
    "_draft_locked_answers",
    "_encode_cursor",
    "_encode_worklist_cursor",
    "_enforce_locked",
    "_expression_now",
    "_has_candidate",
    "_identity_from_answers",
    "_interview_completed",
    "_interview_outcome",
    "_interviewed_condition",
    "_interviewer_age",
    "_is_attachment_reference",
    "_is_outdated_form_version",
    "_json_value",
    "_keep_history",
    "_keep_losing_version",
    "_locked_answers",
    "_merged_answers",
    "_micros",
    "_mine_condition",
    "_missing_identity_error",
    "_mode_allows",
    "_note_last_change",
    "_own_submitted_draft",
    "_parse_coding_timeline",
    "_prefill_from_death",
    "_project_today",
    "_register_values",
    "_replace_raw_answers",
    "_reporter_reaches",
    "_require_age_info",
    "_require_live_org_unit",
    "_require_scope",
    "_revisable_now",
    "_revision_reply",
    "_serialize_location",
    "_set_final_section",
    "_store_superseded_copy",
    "_supersede_draft",
    "_supervising_actor",
    "_sync_case_identity",
    "_sync_reply",
    "_unit_context",
    "_unit_label",
    "_unit_prefill_parts",
    "_utcnow",
    "_visit_note",
    "_waiting_case",
    "_who_place_of_death",
    "_without_location",
    "_worklist_scope",
    "_worklist_select",
    "admin_actor",
    "age_field",
    "aliased",
    "annotations",
    "apply_submission_projection",
    "attachments",
    "birth_answer",
    "build_final_payload",
    "build_submission_projection",
    "build_web_payload",
    "can",
    "can_code_now",
    "can_edit_identifiers",
    "case_prefill",
    "case_row",
    "case_submission_view",
    "cases",
    "check_definition_identity",
    "check_device_answers",
    "check_device_times",
    "check_refusal_resume",
    "choice_answer",
    "choose_interview",
    "clear_direct_identity_for_refusal",
    "collection_gate",
    "collection_hold",
    "consent_is_valid",
    "data_manager_actor",
    "dataclasses",
    "date",
    "datetime",
    "db",
    "death_identifiers",
    "derive_final_age_in_years",
    "derive_validation_errors",
    "discard_draft",
    "draft_is_stale",
    "ensure_active_payload_version",
    "ensure_web_runtime_form",
    "find_device_attempt",
    "find_device_registration",
    "find_device_upload",
    "find_own_submission",
    "find_revisable_submission",
    "flag_death",
    "fold_into_own_submission",
    "form_version_of",
    "get_active_payload_version",
    "get_case_detail",
    "get_case_for_supervisor",
    "get_death",
    "get_device_case",
    "get_draft",
    "get_latest_pending_upstream_payload_version",
    "get_open_revision_request",
    "get_submission_workflow_state",
    "get_supervised_case",
    "get_web_intake_mode",
    "gps_projects",
    "has_visit_note_condition",
    "hashlib",
    "identifier_edit_condition",
    "identifier_field_scopes",
    "identifier_write_flags",
    "identifier_write_parts",
    "identifier_write_status",
    "interview_supervisor_actor",
    "interviewer_context",
    "interviewer_reaches",
    "is_attachment_draft",
    "is_new_refusal",
    "is_withdrawn",
    "json",
    "last_change",
    "list_candidates",
    "list_deaths",
    "list_drafts",
    "list_supervised_cases",
    "list_worklist",
    "load_draft_envelope",
    "lock_draft_for_browser_write",
    "log",
    "log_contact_attempt",
    "logging",
    "mark_attachment_sync_completed",
    "mark_consulted",
    "mark_upstream_change_detected",
    "math",
    "may_read_submitted_answers",
    "merge_incoming_timeline_meta",
    "merge_timeline",
    "normalise_phone",
    "normalize_consent",
    "notification_service",
    "opened_payload",
    "org",
    "org_grant_service",
    "org_routing",
    "parse_timeline",
    "pause_interview",
    "payload_matches",
    "pii_scope",
    "possible_duplicates",
    "prefill_policy",
    "prepare_browser_overwrite",
    "project_clock",
    "project_country",
    "public_demo_service",
    "pytz",
    "re",
    "reachable_unit_ids",
    "redact_national_id_digits",
    "redact_payload_national_ids",
    "refusal_stale",
    "register_death",
    "register_death_context",
    "register_duplicate_service",
    "register_pii_accessor",
    "reject_pending_upstream_payload_version",
    "release_coding_for_changed_payload",
    "release_who_refusal_hold",
    "reopen_coding_after_revision",
    "reported_deaths_page",
    "require_identifier_write",
    "resolve_draft_display_names",
    "resolve_grants",
    "resolve_intake_note",
    "resolve_pending_upstream_change",
    "resubmit_browser_draft",
    "resubmit_device_interview",
    "revise_submission",
    "revision_unlocked",
    "route_synced_submission",
    "sa",
    "save_draft_sections",
    "scrub_attachment_names",
    "scrub_refused_draft",
    "selectinload",
    "self_coding_project_ids",
    "serialize_case_detail",
    "serialize_death",
    "serialize_device_upload",
    "serialize_draft",
    "serialize_drafts",
    "serialize_supervised_row",
    "serialize_worklist_row",
    "served_form_service",
    "server_event",
    "set_visit",
    "shows_gps",
    "smartva_service",
    "start_attachment_draft",
    "start_draft",
    "stored_answers",
    "strip_irrelevant_answers",
    "submit_device_interview",
    "submit_draft",
    "subtree_select",
    "supervised_case_row",
    "supervised_row_facts",
    "supervision",
    "supervision_attention_conditions",
    "supervision_tiles",
    "sync_device_draft",
    "system_actor",
    "timedelta",
    "training_scope",
    "update_death",
    "uuid",
    "whole_answer",
    "worklist_page",
)


class FacadeNamesTests(BaseTestCase):
    def test_every_name_the_module_exposed_is_still_there(self):
        missing = [n for n in FACADE_NAMES if not hasattr(intake_svc, n)]
        self.assertEqual(missing, [])
        self.assertGreater(len(FACADE_NAMES), 300)  # the list itself is present


class SubmitAndReviseCharacterizationTests(intake_tests.WebIntakeServiceTests):
    """Reuses the web intake fixtures; the inherited tests run in their own module."""

    def _counts(self):
        return tuple(
            db.session.scalar(sa.select(sa.func.count()).select_from(model))
            for model in (VaSubmissions, VaSubmissionPayloadVersion, VaSubmissionsAuditlog, MapCaseTransition)
        )

    def test_a_submit_writes_one_submission_one_version_and_closes_the_case(self):
        death = self._register_death()
        before = self._counts()
        draft, submission = self._submit_for_new_draft(death, self._completion())
        after = self._counts()
        self.assertEqual((after[0] - before[0], after[1] - before[1]), (1, 1))
        self.assertGreaterEqual(after[3] - before[3], 1)  # case transitions recorded
        self.assertEqual((death.status, death.va_sid, draft.status, draft.va_sid),
                         ("submitted", submission.va_sid, "submitted", submission.va_sid))

    def test_a_submit_without_completion_data_is_a_400_with_its_message(self):
        draft = intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID)
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(draft, self.interviewer, completion={"valid": True})
        self.assertEqual((ctx.exception.status_code, str(ctx.exception)), (400, "completion.data is required."))
        self.assertEqual(draft.status, "draft")  # present: still open, nothing written

    def test_a_second_submit_is_a_409_and_writes_nothing(self):
        death = self._register_death()
        draft, _ = self._submit_for_new_draft(death, self._completion())
        before = self._counts()
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertEqual((ctx.exception.status_code, str(ctx.exception)), (409, "This draft has already been submitted."))
        self.assertEqual(self._counts(), before)

    def test_revising_an_unknown_submission_is_a_404(self):
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.revise_submission(
                self.interviewer, "no-such-sid", reason_code="interviewer_correction", data={},
                answers_sha256=None, completion={"valid": True, "issues": []}, envelope={},
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_an_unchanged_resubmission_writes_no_version(self):
        death = self._register_death()
        draft, _ = self._submit_for_new_draft(death, self._completion())
        stored = intake_svc.datetime.fromisoformat(draft.meta["effectiveSavedAt"])
        tie = {"completedAt": stored.isoformat(), "deviceClockAt": stored.isoformat()}
        versions = self._counts()[1]
        reply = self._resubmit(draft, self._completion()["data"], envelope=tie)
        self.assertEqual((reply["changed"], self._counts()[1]), (False, versions))
        self.assertEqual(set(reply), {"changed", "va_sid", "payload_version_id", "answers_sha256", "outcome",
                                      "workflow_state", "kept", "locked"})

    # -- names tests patch on the facade must reach the moved callers --------

    def test_patching_the_org_unit_check_on_the_facade_stops_a_submit(self):
        death = self._register_death()
        draft = intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       death_id=death.death_id)
        with mock.patch.object(intake_svc, "_require_live_org_unit",
                               side_effect=intake_svc.WebIntakeError("unit inactive", 409)):
            with self.assertRaises(intake_svc.WebIntakeError) as ctx:
                intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertEqual(ctx.exception.status_code, 409)

    def test_patching_the_router_on_the_facade_reaches_a_submit(self):
        death = self._register_death()
        draft = intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       death_id=death.death_id)
        real = intake_svc.route_synced_submission
        with mock.patch.object(intake_svc, "route_synced_submission", wraps=real) as spy:
            intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertEqual(spy.call_count, 1)

    def test_patching_relevance_helpers_and_the_clock_on_the_facade_reaches_a_submit(self):
        death = self._register_death()
        draft = intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       death_id=death.death_id)
        with mock.patch.object(intake_svc, "derive_validation_errors", wraps=intake_svc.derive_validation_errors) as derive, \
                mock.patch.object(intake_svc, "strip_irrelevant_answers", wraps=intake_svc.strip_irrelevant_answers) as strip, \
                mock.patch.object(intake_svc, "_utcnow", wraps=intake_svc._utcnow) as clock:
            intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertGreaterEqual((derive.call_count, strip.call_count, clock.call_count), (1, 1, 1))


# The inherited intake tests run in their own module.
for _name in [n for n in dir(intake_tests.WebIntakeServiceTests) if n.startswith("test_")]:
    if not hasattr(SubmitAndReviseCharacterizationTests, _name) or getattr(
            SubmitAndReviseCharacterizationTests, _name) is getattr(intake_tests.WebIntakeServiceTests, _name):
        setattr(SubmitAndReviseCharacterizationTests, _name, None)
