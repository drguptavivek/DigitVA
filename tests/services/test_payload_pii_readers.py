"""PII slice 1b part II-B: readers of a split payload (docs/kb/pii-slice-1b.md).

With ``PAYLOAD_PII_SPLIT_ENABLED`` on, a stored version's ``payload_data``
holds no sealed field; every reader that needs one joins the side row back in
(``joined_payload``, ``get_pii_many``) when the viewer may see PII. Each test
splits a payload, asserts the subject is present for the reader that may see
it, then asserts it is absent where it must not be.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    VaDeathRegister,
    VaSubmissions,
)
from app.services import case_content_service
from app.services import data_management_service as dm
from app.services import doris_context_service
from app.services import odk_case_service as odk_cases
from app.services import payload_pii_accessor as accessor
from app.services import reviewer_coding_service
from app.services import visit_note
from app.services.coding_service import render_va_coding_page
from app.services.doris_prefill import doris_prefill_from_payload
from app.services.field_mapping_service import PiiSetStatus
from app.services.pii_field_registry import PII_FIELDS
from app.services.submission_payload_version_service import (
    ensure_active_payload_version,
    get_active_payload_version,
    get_latest_pending_upstream_payload_version,
    joined_payload,
    write_payload_version,
)
from tests.base import BaseTestCase
from tests.services.test_data_management_service import DataManagementAcceptRejectTests
from tests.services.test_national_id_sync_rerun import create_form
from tests.test_odk_case_service import OdkCaseFixtureMixin

AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
NAME = "Sunita"
ADDRESS = "House 12, Ward 4, Mill Road"
REMARKS = "Family declined at the door"


class SplitReaderBase(BaseTestCase):
    FORM_ID = "PRD01RD0101"
    PROJECT_ID = "PRD01"
    SITE_ID = "RD01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def setUp(self):
        super().setUp()
        self._flag(True)

    def _flag(self, on: bool):
        previous = self.app.config.get("PAYLOAD_PII_SPLIT_ENABLED", False)
        self.app.config["PAYLOAD_PII_SPLIT_ENABLED"] = on
        self.addCleanup(self.app.config.__setitem__, "PAYLOAD_PII_SPLIT_ENABLED", previous)

    def _split_case(self, instance_id: str, *, consent="yes", **payload):
        """A submission whose active version was written split (flag on)."""
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        sub = VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=AT,
            va_odk_updatedat=AT.replace(tzinfo=None), va_data_collector="Collector", va_odk_reviewstate=None,
            va_consent=consent, va_narration_language="English", va_deceased_age=52,
            va_deceased_gender="female", va_uniqueid_masked="masked", va_summary=[], va_catcount={},
            va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        record = {
            "KEY": instance_id, "sid": sid, "form_def": self.FORM_ID, "SubmissionDate": AT.isoformat(),
            "updatedAt": AT.isoformat(), "Id10013": consent, "Id10019": "female", "Id10017": NAME,
            **payload,
        }
        version = ensure_active_payload_version(
            sub, payload_data=record, source_updated_at=sub.va_odk_updatedat, created_by_role="vasystem",
        )
        db.session.flush()
        self.assertIsNotNone(accessor.get_side_row(version))
        self.assertIn("Id10019", version.payload_data)  # subject present
        self.assertNotIn("Id10017", version.payload_data)
        return sub, version


class JoinedPayloadTests(SplitReaderBase):
    def test_joined_payload_returns_the_sealed_field_flag_on_and_payload_data_flag_off(self):
        _, version = self._split_case("uuid:prd-joined")
        self.assertEqual(joined_payload(version)["Id10017"], NAME)
        self.assertEqual(joined_payload(version)["Id10019"], "female")
        self._flag(False)
        self.assertNotIn("Id10017", joined_payload(version))  # exactly what is stored

    def test_a_viewer_who_may_see_pii_gets_the_sealed_field_and_a_redacting_viewer_never_decrypts(self):
        _, version = self._split_case("uuid:prd-viewer")
        full = case_content_service.viewer_source_payload(version, False)
        self.assertEqual(full["Id10017"], NAME)
        with mock.patch.object(case_content_service, "joined_payload") as opened:
            redacted = case_content_service.viewer_source_payload(version, True)
        opened.assert_not_called()
        self.assertEqual(redacted["Id10019"], "female")  # subject present
        self.assertNotIn("Id10017", redacted)
        self.assertIsNone(case_content_service.viewer_source_payload(None, False))

    def test_the_section_data_a_viewer_is_served_is_built_from_the_viewer_payload(self):
        sub, version = self._split_case("uuid:prd-section")
        captured = []

        def render(payload, *args, **kwargs):
            captured.append(payload)
            return {}

        confirmed = PiiSetStatus(confirmed=True, field_ids=frozenset(PII_FIELDS), owned_flagged_count=1)
        for redact in (False, True):
            captured.clear()
            with (
                mock.patch.object(case_content_service, "should_redact_pii", return_value=redact),
                mock.patch.object(case_content_service, "va_render_processcategorydata", side_effect=render),
                mock.patch.object(case_content_service, "build_submission_summary", return_value=[]),
                mock.patch.object(case_content_service, "va_get_render_datalevel", return_value={}),
                mock.patch.object(case_content_service, "flask_cache", get=mock.Mock(return_value=None)),
                mock.patch.object(case_content_service, "get_active_smartva", return_value=None),
                mock.patch.object(case_content_service.get_mapping_service(), "get_pii_set_status",
                                  return_value=confirmed),
            ):
                case_content_service.get_section_data(
                    va_submission=sub, active_version=version, form_type_code="WHO_2022_VA",
                    va_action="vacode", va_partial="vademographicdetails", category_config=None,
                    visible_category_codes=[], user=SimpleNamespace(),
                )
            self.assertTrue(captured)
            self.assertIn("Id10019", captured[0])
            self.assertEqual("Id10017" in captured[0], not redact)


class VisitNoteReaderTests(SplitReaderBase):
    def _note_case(self, instance_id, **extra):
        return self._split_case(
            instance_id, consent="no", visit_address=ADDRESS, visit_remarks=REMARKS, **extra
        )

    def _has_note(self, sid) -> bool:
        return bool(db.session.scalar(
            sa.select(sa.exists().where(
                VaSubmissions.va_sid == sid, visit_note.has_visit_note_condition()
            ))
        ))

    def test_presence_follows_the_sealed_address_with_no_date_and_no_decrypt(self):
        sub, version = self._note_case("uuid:prd-note-presence")
        self.assertNotIn("visit_address", version.payload_data)
        self.assertIn("visit_address", accessor.get_side_row(version).sealed)
        with mock.patch.object(accessor.pii_crypto, "open_record") as decrypt:
            self.assertTrue(self._has_note(sub.va_sid))
        decrypt.assert_not_called()
        empty, _ = self._split_case("uuid:prd-note-none", consent="no")
        self.assertFalse(self._has_note(empty.va_sid))

    def test_notes_for_opens_the_text_for_a_viewer_who_may_see_pii_only(self):
        a, _ = self._note_case("uuid:prd-note-a", visit_date="2026-10-01")
        b, _ = self._note_case("uuid:prd-note-b", visit_date="2026-10-02")
        sids = [a.va_sid, b.va_sid]
        with mock.patch.object(accessor, "get_pii_many", wraps=accessor.get_pii_many) as batch:
            full = visit_note.visit_notes_for(sids, redact_pii=False)
        self.assertEqual(batch.call_count, 1)  # one batch, no N+1
        self.assertEqual(full[a.va_sid]["address"], ADDRESS)
        self.assertEqual(full[b.va_sid]["remarks"], REMARKS)
        shown = visit_note.visit_note_for_viewer(full[a.va_sid], redact_pii=False)
        self.assertEqual(shown["address"], ADDRESS)

        with mock.patch.object(accessor, "get_pii_many") as batch:
            redacted = visit_note.visit_notes_for(sids, redact_pii=True)
        batch.assert_not_called()
        self.assertEqual(redacted[a.va_sid]["date"], "2026-10-01")  # the note still counts
        self.assertEqual(redacted[a.va_sid]["address"], "")
        self.assertNotIn(ADDRESS, repr(redacted))
        masked = visit_note.visit_note_for_viewer(redacted[a.va_sid], redact_pii=True)
        self.assertIsNone(masked["address"])

    def test_the_case_header_note_comes_from_the_joined_payload(self):
        sub, version = self._note_case("uuid:prd-note-header", visit_date="2026-10-01")
        category_service = mock.Mock()
        category_service.get_category_nav.return_value = []
        category_service.get_default_category_code.return_value = "vademographicdetails"
        for redact, expected in ((False, ADDRESS), (True, None)):
            with (
                mock.patch("app.services.viewer_pii_service.should_redact_pii", return_value=redact),
                mock.patch("app.services.category_rendering_service.get_category_rendering_service",
                           return_value=category_service),
                mock.patch("app.services.category_rendering_service.get_visible_category_codes",
                           return_value=["vademographicdetails"]),
                mock.patch("app.services.coding_service._count_attachments_per_category", return_value={}),
                mock.patch("app.services.coder_workflow_service.is_upstream_recode", return_value=False),
                mock.patch("app.services.demo_project_service.is_demo_training_submission", return_value=False),
                mock.patch("app.services.workflow.upstream_changes.get_latest_pending_upstream_change",
                           return_value=None),
                mock.patch("app.tasks.sync_tasks.run_open_submission_repair.delay"),
                mock.patch("flask.render_template", return_value="OK") as render,
            ):
                render_va_coding_page(sub, "vacode", "varesumecoding", "coder")
            note = render.call_args.kwargs["visit_note"]
            self.assertEqual(note["date"], "2026-10-01")  # subject present
            self.assertEqual(note["address"], expected)


class ReaderSitesTests(SplitReaderBase):
    def test_doris_prefill_reads_a_sealed_date_of_birth_for_a_viewer_who_may_see_pii(self):
        # An admin may flag the date of birth is_pii; the sealed set then holds it.
        sealed = frozenset(PII_FIELDS) | {"Id10021"}
        with mock.patch(
            "app.services.submission_payload_version_service.sealed_ids_for_sid", return_value=sealed
        ):
            sub, version = self._split_case("uuid:prd-doris", Id10020="yes", Id10021="1970-05-02")
        self.assertNotIn("Id10021", version.payload_data)
        self.assertNotIn("DateBirth", doris_prefill_from_payload(version.payload_data)[0].get("AdministrativeData", {}))
        prefill, _ = doris_context_service.doris_initial(None, sub, "masked_doris", False, version)
        self.assertEqual(prefill["AdministrativeData"]["DateBirth"], "1970-05-02")
        self.assertEqual(doris_context_service.doris_initial(None, sub, "masked_doris", True, version), ({}, {}))

    def test_reviewer_checks_use_the_joined_payload(self):
        sub, _ = self._split_case("uuid:prd-reviewer")
        seen = []
        project = SimpleNamespace(reviewer_social_autopsy_enabled=True)
        with (
            mock.patch("app.services.coding_service.get_project_for_submission", return_value=project),
            mock.patch(
                "app.services.category_rendering_service.get_visible_category_codes",
                side_effect=lambda payload, form_id: seen.append(payload) or [],
            ),
        ):
            reviewer_coding_service._reviewer_social_autopsy_required(sub.va_sid, sub)
        self.assertEqual(seen[0]["Id10017"], NAME)

    def test_the_prefill_record_of_a_saved_certificate_reads_the_joined_payload(self):
        sub, version = self._split_case("uuid:prd-snapshot")
        sub.active_payload_version_id = version.payload_version_id
        seen = []
        with mock.patch.object(
            reviewer_coding_service, "doris_prefill_record",
            side_effect=lambda payload, certificate: seen.append(payload) or {},
        ):
            reviewer_coding_service._doris_prefill_snapshot(
                SimpleNamespace(cod_entry_mode="doris", masked_cod_required=False), "digest", sub, {}
            )
        self.assertEqual(seen[0]["Id10017"], NAME)


class AcceptReaderTests(DataManagementAcceptRejectTests):
    FORM_ID = "PRD02DM0101"
    PROJECT_ID = "PRD02"
    SITE_ID = "DM02"

    def test_the_upstream_accept_projection_is_derived_from_the_joined_payload(self):
        va_sid = self._create_revoked_submission("pii-accept")
        pending = get_latest_pending_upstream_payload_version(va_sid)
        previous = self.app.config.get("PAYLOAD_PII_SPLIT_ENABLED", False)
        self.app.config["PAYLOAD_PII_SPLIT_ENABLED"] = True
        self.addCleanup(self.app.config.__setitem__, "PAYLOAD_PII_SPLIT_ENABLED", previous)
        write_payload_version(pending, {**pending.payload_data, "Id10017": NAME})
        db.session.flush()
        self.assertNotIn("Id10017", pending.payload_data)  # subject sealed
        seen = []
        real = dm.apply_payload_to_submission_summary
        with mock.patch.object(
            dm, "apply_payload_to_submission_summary",
            side_effect=lambda submission, payload, **kwargs: (seen.append(payload), real(submission, payload, **kwargs)),
        ):
            dm.dm_accept_upstream_change(self._create_dm_user(), va_sid)
        self.assertEqual(seen[0]["Id10017"], NAME)


class _Stop(Exception):
    pass


class SealedVisibilityTests(SplitReaderBase):
    """Category visibility is computed from the joined payload."""

    def _captured_visibility_payload(self, call):
        seen = []

        def capture(payload, form_id):
            seen.append(payload)
            raise _Stop

        with self.assertRaises(_Stop):
            call(capture)
        self.assertTrue(seen)
        return seen[0]

    def test_api_authorize_computes_visibility_from_the_joined_payload(self):
        from app.routes.api import va_case

        sub, _ = self._split_case("uuid:prd-vis-api")
        session = va_case._Session("view", False)
        with self.app.test_request_context("/?mode=view"):
            def call(capture):
                with (
                    mock.patch.object(va_case, "_authorize_view", return_value=session),
                    mock.patch.object(va_case, "get_visible_category_codes", side_effect=capture),
                ):
                    va_case._authorize(sub.va_sid)

            payload = self._captured_visibility_payload(call)
        self.assertEqual(payload["Id10019"], "female")  # subject present
        self.assertEqual(payload["Id10017"], NAME)

    def test_renderpartial_computes_visibility_from_the_joined_payload(self):
        import importlib
        va_form = importlib.import_module("app.routes.va_form")

        sub, _ = self._split_case("uuid:prd-vis-form")
        view = va_form.renderpartial
        while hasattr(view, "__wrapped__"):
            view = view.__wrapped__
        with self.app.test_request_context("/"):
            def call(capture):
                with (
                    mock.patch.object(va_form, "_require_partial_write"),
                    mock.patch.object(va_form, "get_visible_category_codes", side_effect=capture),
                ):
                    view(sub.va_sid, "vademographicdetails")

            payload = self._captured_visibility_payload(call)
        self.assertEqual(payload["Id10019"], "female")  # subject present
        self.assertEqual(payload["Id10017"], NAME)


class NoteRedactionRoutingTests(SplitReaderBase):
    def test_supervised_case_detail_passes_redact_pii_to_visit_notes_for(self):
        from app.routes.api import intake

        sub, _ = self._split_case(
            "uuid:prd-sup", consent="no", visit_address=ADDRESS, visit_remarks=REMARKS, visit_date="2026-10-01"
        )
        view = intake.supervised_case_detail
        while hasattr(view, "__wrapped__"):
            view = view.__wrapped__
        death = SimpleNamespace(va_sid=sub.va_sid)
        for redact in (False, True):
            with (
                self.app.test_request_context("/"),
                mock.patch.object(intake.intake_svc, "get_supervised_case", return_value=death),
                mock.patch.object(intake.intake_svc, "supervised_case_row", return_value=()),
                mock.patch.object(intake.intake_svc, "list_candidates", return_value=[]),
                mock.patch.object(intake, "_supervised_body", return_value={}),
                mock.patch.object(intake, "should_redact_pii", return_value=redact),
                mock.patch.object(intake, "visit_notes_for", wraps=intake.visit_notes_for) as notes,
            ):
                body = view("death-1").get_json()
            self.assertEqual(notes.call_args.kwargs["redact_pii"], redact)
            note = body["visit_note"]
            self.assertEqual(note["date"], "2026-10-01")  # subject present
            self.assertEqual(note["address"], None if redact else ADDRESS)
            self.assertEqual(note["remarks"], None if redact else REMARKS)


class DmReaderTests(DataManagementAcceptRejectTests):
    FORM_ID = "PRD03DM0101"
    PROJECT_ID = "PRD03"
    SITE_ID = "DM03"

    def _flag_on(self):
        previous = self.app.config.get("PAYLOAD_PII_SPLIT_ENABLED", False)
        self.app.config["PAYLOAD_PII_SPLIT_ENABLED"] = True
        self.addCleanup(self.app.config.__setitem__, "PAYLOAD_PII_SPLIT_ENABLED", previous)

    def test_dm_submissions_page_passes_redact_pii_to_visit_notes_for(self):
        va_sid = self._create_revoked_submission("pii-dmpage")
        self._flag_on()
        sub = db.session.get(VaSubmissions, va_sid)
        sub.va_consent = "no"
        active = get_active_payload_version(va_sid)
        write_payload_version(active, {
            **active.payload_data, "Id10013": "no", "visit_address": ADDRESS,
            "visit_remarks": REMARKS, "visit_date": "2026-10-01",
        })
        db.session.flush()
        self.assertNotIn("visit_address", active.payload_data)  # subject sealed
        user = self._create_dm_user()
        for redact in (False, True):
            with (
                mock.patch.object(dm, "should_redact_pii", return_value=redact),
                mock.patch.object(dm, "visit_notes_for", wraps=dm.visit_notes_for) as notes,
            ):
                rows = {r["va_sid"]: r for r in dm.dm_submissions_page(
                    user, project=self.PROJECT_ID, odk_sync="all", per_page=100)["data"]}
            self.assertIn(va_sid, rows)  # subject present
            self.assertEqual(notes.call_args.kwargs["redact_pii"], redact)
            note = rows[va_sid]["visit_note"]
            self.assertEqual(note["date"], "2026-10-01")
            self.assertEqual(note["address"], None if redact else ADDRESS)
            self.assertEqual(note["remarks"], None if redact else REMARKS)

    def test_keep_current_icd_reads_the_joined_pending_payload(self):
        va_sid = self._create_revoked_submission("pii-keep")
        pending = get_latest_pending_upstream_payload_version(va_sid)
        self._flag_on()
        write_payload_version(pending, {**pending.payload_data, "Id10017": NAME})
        db.session.flush()
        self.assertNotIn("Id10017", pending.payload_data)  # subject sealed
        seen = []
        real = dm.apply_payload_to_submission_summary
        with mock.patch.object(
            dm, "apply_payload_to_submission_summary",
            side_effect=lambda submission, payload, **kwargs: (seen.append(payload), real(submission, payload, **kwargs)),
        ):
            dm.dm_keep_current_icd_on_upstream_change(self._create_dm_user(), va_sid)
        self.assertEqual(seen[0]["Id10017"], NAME)


class GetPiiManyTests(SplitReaderBase):
    def test_empty_none_and_unsplit_inputs(self):
        self.assertEqual(accessor.get_pii_many([]), {})
        self.assertEqual(accessor.get_pii_many(x for x in ()), {})
        self.assertEqual(accessor.get_pii_many([None, None]), {})
        _, split = self._split_case("uuid:prd-many-a")
        opened = accessor.get_pii_many([None, split.payload_version_id])
        self.assertEqual(opened[split.payload_version_id]["Id10017"], NAME)
        db.session.delete(accessor.get_side_row(split))
        db.session.flush()
        self.assertEqual(accessor.get_pii_many([split.payload_version_id]), {})  # no side row: absent


class OdkBackfillReaderTests(OdkCaseFixtureMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        previous = self.app.config.get("PAYLOAD_PII_SPLIT_ENABLED", False)
        self.app.config["PAYLOAD_PII_SPLIT_ENABLED"] = True
        self.addCleanup(self.app.config.__setitem__, "PAYLOAD_PII_SPLIT_ENABLED", previous)

    def test_sync_reads_the_incoming_name_and_backfill_reads_the_sealed_one(self):
        self._tree()
        self._mapping()
        sid = self._sid("uuid:odk-split-backfill")
        self._sync([self._record("uuid:odk-split-backfill", org_phc_code="P01")])
        version = get_active_payload_version(sid)
        self.assertIn("Id10019", version.payload_data)  # subject present
        self.assertNotIn("Id10017", version.payload_data)
        (case,) = self._odk_cases(sid)
        self.assertEqual(case.deceased_name, "Asha Devi")  # the sync read the plaintext before the split

        db.session.execute(sa.delete(MapCaseTransition).where(MapCaseTransition.death_id == case.death_id))
        db.session.execute(sa.delete(VaDeathRegister).where(VaDeathRegister.va_sid == sid))
        db.session.commit()
        with mock.patch.object(odk_cases, "get_pii_many", wraps=odk_cases.get_pii_many) as batch:
            dry = odk_cases.backfill_odk_cases(project_id=self.PROJECT, dry_run=True)
            self.assertEqual((dry["created"], dry["identity_missing"]), (1, 0))
            real = odk_cases.backfill_odk_cases(project_id=self.PROJECT)
        self.assertEqual(batch.call_count, 2)  # one batch per chunk, not per row
        self.assertEqual(real["created"], 1)
        (rebuilt,) = self._odk_cases(sid)
        self.assertEqual(rebuilt.deceased_name, "Asha Devi")
        self.assertEqual(rebuilt.deceased_sex, "female")
