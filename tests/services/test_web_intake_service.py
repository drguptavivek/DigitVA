"""Tests for app.services.web_intake_service.

Covers the rules the web intake path owns (docs/policy/web-intake.md):
  - project ``web_intake_mode`` gates the death register and direct entry
  - interviewer scope is enforced on every entry point
  - a registered death gets a unique id from the death-number sequence
  - drafts save section-wise and reassemble into the package's envelope
  - submitting a draft creates a ``va_submissions`` row with an active payload
    version and lands in ``smartva_pending`` when consent is valid
  - the web ``va_forms`` row is never enumerated by ODK runtime form sync
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaUserAccessGrants,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.models.va_submission_payload_versions import PAYLOAD_VERSION_STATUS_ACTIVE
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import (
    _ensure_legacy_project_site_rows,
    ensure_web_runtime_form,
    sync_runtime_forms_from_site_mappings,
)
from app.services.workflow.definition import WORKFLOW_SMARTVA_PENDING
from app.services.workflow.state_store import get_submission_workflow_state
from tests.base import BaseTestCase


class WebIntakeServiceTests(BaseTestCase):
    """Project WIT01/WI01 runs web intake in ``both`` mode."""

    PROJECT_ID = "WIT01"
    SITE_ID = "WI01"
    ODK_FORM_ID = "WIT01WI0101"

    # Another project-site the interviewer has no grant on.
    OTHER_PROJECT_ID = "WIT02"
    OTHER_SITE_ID = "WI02"
    OTHER_FORM_ID = "WIT02WI0201"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        for project_id, name in ((cls.PROJECT_ID, "Web Intake Test"), (cls.OTHER_PROJECT_ID, "Web Intake Other")):
            db.session.add(VaProjectMaster(
                project_id=project_id,
                project_code=project_id,
                project_name=name,
                project_nickname=name,
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                web_intake_mode="both",
            ))
        for site_id, name in ((cls.SITE_ID, "Web Intake Site"), (cls.OTHER_SITE_ID, "Web Intake Other Site")):
            db.session.add(VaSiteMaster(
                site_id=site_id,
                site_name=name,
                site_abbr=site_id,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
        db.session.flush()

        for project_id, site_id in ((cls.PROJECT_ID, cls.SITE_ID), (cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID)):
            db.session.add(VaProjectSites(
                project_id=project_id,
                site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            ))
        db.session.flush()

        for project_id, site_id in ((cls.PROJECT_ID, cls.SITE_ID), (cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID)):
            _ensure_legacy_project_site_rows(project_id, site_id)
        db.session.flush()

        # An ODK form exists alongside the web form, as it does for a project
        # that collects both ways. Interviewer grants resolve through va_forms.
        for form_id, project_id, site_id in (
            (cls.ODK_FORM_ID, cls.PROJECT_ID, cls.SITE_ID),
            (cls.OTHER_FORM_ID, cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID),
        ):
            db.session.add(VaForms(
                form_id=form_id,
                project_id=project_id,
                site_id=site_id,
                odk_form_id=f"ODK_{form_id}",
                odk_project_id="7",
                form_type="WHO VA 2022",
                form_source="odk",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.flush()

        cls.interviewer = cls._get_or_make_user("web.interviewer@test.local", "WebIntake123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT_ID,
            notes="web intake test grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _set_mode(self, mode, project_id=None):
        project = db.session.get(VaProjectMaster, project_id or self.PROJECT_ID)
        project.web_intake_mode = mode
        db.session.flush()

    def _register_death(self, **overrides):
        fields = {
            "deceased_name": "Asha Devi",
            "deceased_sex": "female",
            "date_of_death": (date.today() - timedelta(days=10)).isoformat(),
            "age_years": 62,
        }
        fields.update(overrides)
        return intake_svc.register_death(
            self.interviewer,
            project_id=self.PROJECT_ID,
            site_id=self.SITE_ID,
            **fields,
        )

    def _completion(self, **extra):
        data = {
            "Id10013": "yes",
            "Id10019": "female",
            "finalAgeInYears": "62",
            "narr_language": "english",
        }
        data.update(extra.pop("data", {}))
        completion = {"valid": True, "issues": [], "data": data}
        completion.update(extra)
        return completion

    # ── mode and scope ─────────────────────────────────────────────────────

    def test_get_web_intake_mode_off_for_unknown_or_inactive_project(self):
        self.assertEqual(intake_svc.get_web_intake_mode("NOPE01"), "off")
        self.assertEqual(intake_svc.get_web_intake_mode(self.PROJECT_ID), "both")

    def test_interviewer_context_lists_only_granted_enabled_project_sites(self):
        context = intake_svc.interviewer_context(self.interviewer)
        self.assertEqual(
            [(e["project_id"], e["site_id"]) for e in context],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        self.assertEqual(context[0]["web_intake_mode"], "both")
        self.assertEqual(context[0]["org_units"], [])

    def test_interviewer_context_drops_project_when_intake_is_off(self):
        self._set_mode("off")
        self.assertEqual(intake_svc.interviewer_context(self.interviewer), [])

    def test_register_death_rejects_ungranted_project_site(self):
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.register_death(
                self.interviewer,
                project_id=self.OTHER_PROJECT_ID,
                site_id=self.OTHER_SITE_ID,
                deceased_name="X",
                deceased_sex="male",
                date_of_death=date.today().isoformat(),
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_register_death_rejected_when_mode_is_direct_only(self):
        self._set_mode("direct")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            self._register_death()
        self.assertEqual(ctx.exception.status_code, 403)

    def test_start_draft_without_death_rejected_when_mode_is_death_register(self):
        self._set_mode("death_register")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.start_draft(
                self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
            )
        self.assertEqual(ctx.exception.status_code, 403)

    # ── death register ─────────────────────────────────────────────────────

    def test_register_death_allocates_unique_id_from_sequence(self):
        first = self._register_death()
        second = self._register_death(deceased_name="Ram Kumar", deceased_sex="male")

        self.assertTrue(first.unique_id.startswith(f"{self.SITE_ID}-"))
        self.assertEqual(first.unique_id, f"{self.SITE_ID}-{first.death_number:06d}")
        self.assertNotEqual(first.unique_id, second.unique_id)
        self.assertGreater(second.death_number, first.death_number)
        self.assertEqual(first.status, "registered")
        self.assertEqual(first.registered_by, self.interviewer.user_id)

    def test_register_death_validates_dates_sex_and_age(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(date_of_death=tomorrow)
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(deceased_sex="other")
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(age_years=500)
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(
                date_of_birth=date.today().isoformat(),
                date_of_death=(date.today() - timedelta(days=10)).isoformat(),
            )
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(deceased_name="   ")

    def test_register_death_validates_abha_identifiers(self):
        death = self._register_death(abha_number="12-3456-7890-1234", abha_address="asha.devi@abdm")
        self.assertEqual(death.abha_number, "12-3456-7890-1234")
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(abha_number="1234")
        with self.assertRaises(intake_svc.WebIntakeError):
            self._register_death(abha_address="asha@example.com")

    def test_list_deaths_is_scoped_and_filtered_by_status(self):
        death = self._register_death()
        rows = intake_svc.list_deaths(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        self.assertIn(death.death_id, [r.death_id for r in rows])
        self.assertEqual(
            intake_svc.list_deaths(
                self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                status="va_submitted",
            ),
            [],
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.list_deaths(
                self.interviewer, project_id=self.OTHER_PROJECT_ID, site_id=self.OTHER_SITE_ID
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_get_death_404_for_unknown_id(self):
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.get_death(self.interviewer, uuid.uuid4())
        self.assertEqual(ctx.exception.status_code, 404)

    # ── drafts ─────────────────────────────────────────────────────────────

    def test_start_draft_direct_creates_web_form_and_own_unique_id(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        form = db.session.get(VaForms, draft.form_id)
        self.assertEqual(form.form_source, "web")
        self.assertEqual((form.project_id, form.site_id), (self.PROJECT_ID, self.SITE_ID))
        self.assertNotEqual(form.form_id, self.ODK_FORM_ID)
        self.assertIsNone(draft.death_id)
        self.assertEqual(draft.status, "draft")
        self.assertTrue(draft.unique_id.startswith(f"{self.SITE_ID}-"))

        # A second draft reuses the same web form row.
        again = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        self.assertEqual(again.form_id, draft.form_id)
        self.assertNotEqual(again.unique_id, draft.unique_id)

    def test_start_draft_from_death_prefills_and_marks_in_progress(self):
        death = self._register_death(
            date_of_birth=(date.today() - timedelta(days=365 * 62)).isoformat(),
            abha_number="12345678901234",
        )
        draft = intake_svc.start_draft(
            self.interviewer,
            project_id=self.PROJECT_ID,
            site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        self.assertEqual(draft.unique_id, death.unique_id)
        self.assertEqual(draft.death_id, death.death_id)
        self.assertEqual(death.status, "va_in_progress")
        self.assertEqual(draft.prefill["deceased"]["givenNames"], "Asha")
        self.assertEqual(draft.prefill["deceased"]["surname"], "Devi")
        self.assertEqual(draft.prefill["deceased"]["sex"], "female")
        self.assertEqual(draft.prefill["answers"]["abha_number"], "12345678901234")
        self.assertEqual(draft.prefill["lockedQuestionNames"], ["abha_number"])

    def test_start_draft_from_death_returns_the_existing_draft(self):
        death = self._register_death()
        first = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        second = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        self.assertEqual(first.draft_id, second.draft_id)

    def test_start_draft_rejects_another_interviewers_draft_for_the_same_death(self):
        other = self._get_or_make_user("web.interviewer2@test.local", "WebIntake123")
        db.session.add(VaUserAccessGrants(
            user_id=other.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID,
            notes="second interviewer",
            grant_status=VaStatuses.active,
        ))
        db.session.flush()
        death = self._register_death()
        intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.start_draft(
                other, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                death_id=death.death_id,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_get_draft_is_owner_only(self):
        other = self._get_or_make_user("web.interviewer3@test.local", "WebIntake123")
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.get_draft(other, draft.draft_id)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_save_draft_sections_merges_per_section_and_envelope_reassembles(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        written = intake_svc.save_draft_sections(
            draft,
            sections={"consent": {"Id10013": "yes"}, "background": {"Id10019": "female"}},
            meta={"schemaVersion": 1, "formVersion": "2022", "instrumentVersion": "1.2.3"},
            current_section="background",
        )
        self.assertEqual(written, 2)

        # Re-saving one section replaces only that section's answers.
        intake_svc.save_draft_sections(
            draft, sections={"background": {"Id10019": "male", "Id10020": "2024"}}
        )
        rows = {s.section_name: s.data for s in draft.sections}
        self.assertEqual(rows["consent"], {"Id10013": "yes"})
        self.assertEqual(rows["background"], {"Id10019": "male", "Id10020": "2024"})

        envelope = intake_svc.load_draft_envelope(draft)
        self.assertEqual(envelope["id"], str(draft.draft_id))
        self.assertEqual(envelope["currentSection"], "background")
        self.assertEqual(envelope["instrumentId"], intake_svc.INSTRUMENT_ID)
        self.assertEqual(envelope["instrumentVersion"], "1.2.3")
        self.assertEqual(
            envelope["data"], {"Id10013": "yes", "Id10019": "male", "Id10020": "2024"}
        )

    def test_save_draft_sections_rejects_bad_shapes(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(draft, sections=["consent"])
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(draft, sections={"bad name!": {}})
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(draft, sections={"consent": "yes"})
        with self.assertRaises(intake_svc.WebIntakeError):
            intake_svc.save_draft_sections(
                draft, sections={}, current_section="not a section"
            )

    def test_discard_draft_releases_the_death_back_to_registered(self):
        death = self._register_death()
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        intake_svc.discard_draft(draft)
        self.assertEqual(draft.status, "discarded")
        self.assertEqual(death.status, "registered")
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.get_draft(self.interviewer, draft.draft_id, for_update=True)
        self.assertEqual(ctx.exception.status_code, 409)

    # ── submission ─────────────────────────────────────────────────────────

    def test_submit_draft_creates_submission_payload_version_and_workflow_state(self):
        death = self._register_death()
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            death_id=death.death_id,
        )
        submission = intake_svc.submit_draft(
            draft, self.interviewer, completion=self._completion()
        )

        self.assertEqual(submission.va_form_id, draft.form_id)
        self.assertEqual(submission.va_uniqueid_real, draft.unique_id)
        self.assertEqual(submission.va_consent, "yes")
        self.assertEqual(submission.va_data_collector, self.interviewer.name)

        self.assertEqual(draft.status, "submitted")
        self.assertEqual(draft.va_sid, submission.va_sid)
        self.assertTrue(draft.client_valid)
        self.assertIsNotNone(draft.submitted_at)
        self.assertEqual(death.status, "va_submitted")
        self.assertEqual(death.va_sid, submission.va_sid)

        version = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == submission.va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        self.assertIsNotNone(version)
        self.assertEqual(version.payload_data["intake_source"], "web")
        self.assertEqual(version.payload_data["unique_id"], draft.unique_id)
        self.assertEqual(version.payload_data["death_register_id"], str(death.death_id))

        # No attachments -> the attachment step is skipped straight to SmartVA.
        self.assertEqual(
            get_submission_workflow_state(submission.va_sid), WORKFLOW_SMARTVA_PENDING
        )

    def test_submit_draft_requires_valid_completion_and_consent(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(draft, self.interviewer, completion={})
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(
                draft, self.interviewer, completion=self._completion(valid=False)
            )
        self.assertEqual(ctx.exception.status_code, 422)

        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(
                draft, self.interviewer, completion=self._completion(data={"Id10013": ""})
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_submit_draft_is_rejected_twice(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.submit_draft(draft, self.interviewer, completion=self._completion())
        self.assertEqual(ctx.exception.status_code, 409)

    def test_build_web_payload_lifts_attachment_answers_out_of_the_payload(self):
        draft = intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID
        )
        payload, references = intake_svc.build_web_payload(
            draft,
            {
                "Id10013": "yes",
                "death_certificate": "who-va-attachment:abc123",
            },
            self.interviewer,
            submitted_at=datetime.now(timezone.utc),
        )
        self.assertEqual(references, {"death_certificate": "who-va-attachment:abc123"})
        self.assertIsNone(payload["death_certificate"])
        self.assertEqual(payload["AttachmentsExpected"], 1)
        self.assertEqual(payload["intake_source"], "web")
        self.assertEqual(payload["Site"], self.SITE_ID)
        self.assertEqual(payload["form_def"], draft.form_id)

    # ── the web form and ODK sync ──────────────────────────────────────────

    def test_web_form_is_not_enumerated_or_rewritten_by_odk_runtime_sync(self):
        web_form = ensure_web_runtime_form(self.PROJECT_ID, self.SITE_ID)
        db.session.add(MapProjectSiteOdk(
            project_id=self.PROJECT_ID,
            site_id=self.SITE_ID,
            odk_project_id=7,
            odk_form_id=f"ODK_{self.ODK_FORM_ID}",
        ))
        db.session.flush()

        synced = sync_runtime_forms_from_site_mappings()

        self.assertNotIn(web_form.form_id, [f.form_id for f in synced])
        db.session.refresh(web_form)
        self.assertEqual(web_form.form_source, "web")
        self.assertEqual(web_form.odk_form_id, "WEB_WHOVA2022")
        self.assertEqual(web_form.odk_project_id, "0")
