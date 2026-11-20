"""The printable WHO-form certificate of a coded org-project case
(docs/policy/cod-certificate-export.md). Each refusal is checked after the
case is shown open, so no 404 is a fixture that never worked."""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaReviewerFinalAssessments,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.cod_certificate_service import interval_text
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase

NAME = "Zorabel Quillfeather"
CERT = {"Part1": [
    {"Conditions": [{"Text": "Septic shock", "Code": "1G41", "LinearizationURI": "u", "Interval": "P3D"}]},
    {"Conditions": [{"Text": "Pneumonia", "Code": "CA40.Z", "LinearizationURI": "u", "Interval": "P2W"}]},
], "Part2": {"Conditions": [{"Text": "Diabetes", "Code": "5A14", "LinearizationURI": "u"}]}}


class CodCertificateTests(BaseTestCase):
    PROJECT_ID = "CERT01"
    SITE_ID = "CT01"
    FORM_ID = "CERT01CT0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Certificate project",
            project_nickname=cls.PROJECT_ID, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now,
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name=cls.SITE_ID, site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_CERT", odk_project_id="7", form_type="WHO VA 2022",
            form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        cls.level = MasOrgLevel(project_id=cls.PROJECT_ID, level_code="DIST", level_name="District", depth=1)
        db.session.add(cls.level)
        # In a tree project PII needs a unit-scoped grant; admin sees it everywhere.
        cls.pii_viewer = cls.base_admin_user
        cls.plain_viewer = cls._get_or_make_user("cert.plain@test.local", "Certificate123")
        cls.other_viewer = cls._get_or_make_user("cert.other@test.local", "Certificate123")
        cls.coder = cls._get_or_make_user("cert.coder@test.local", "Certificate123")
        for user, role, project in (
            (cls.plain_viewer, VaAccessRoles.collaborator, cls.PROJECT_ID),
            (cls.other_viewer, VaAccessRoles.collaborator_pii, cls.BASE_PROJECT_ID),
        ):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, notes="cert", grant_status=VaStatuses.active,
                scope_type=VaAccessScopeTypes.project, project_id=project,
            ))
        db.session.commit()

    def _case(self, state="coder_finalized", cert=CERT, reviewer=False):
        sid = f"uuid:cert-{uuid.uuid4()}"
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="cert", va_odk_reviewstate="reviewed",
            va_instance_name=sid, va_uniqueid_real=f"REAL-{sid[-6:]}", va_uniqueid_masked=f"MASK-{sid[-6:]}",
            va_consent="yes", va_narration_language="English", va_deceased_age=50,
            va_deceased_gender="female", va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state=state))
        number = db.session.scalar(sa.select(sa.func.coalesce(sa.func.max(VaDeathRegister.death_number), 0))) + 1
        db.session.add(VaDeathRegister(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_number=number,
            unique_id=f"CERT-{uuid.uuid4().hex[:12]}", deceased_name=NAME, deceased_sex="female", age_years=50, date_of_death=datetime.now(UTC).date(), place_of_death="Hospital X",
            informant_name="Respondent Rao", registered_by=self.coder.user_id, source="register", va_sid=sid,
        ))
        coder_final = VaFinalAssessments(
            va_sid=sid, va_finassess_by=self.coder.user_id, va_conclusive_cod="1B10 Tuberculosis",
            doris_certificate=cert, va_finassess_status=VaStatuses.active,
        )
        db.session.add(coder_final)
        db.session.flush()
        if reviewer:
            db.session.add(VaReviewerFinalAssessments(
                va_sid=sid, va_rfinassess_by=self.coder.user_id, va_conclusive_cod="CA40.Z Pneumonia",
                doris_certificate={"Part1": [{"Conditions": [{"Text": "Lung infection"}]}]},
                supersedes_coder_final_assessment_id=coder_final.va_finassess_id,
                va_rfinassess_status=VaStatuses.active,
            ))
        db.session.commit()
        return sid

    def _get(self, user, sid):
        self._login(str(user.user_id))
        return self.client.get(f"/coding/area/{sid}/certificate")

    def test_coder_final_renders_part1_part2_and_underlying_cause(self):
        sid = self._case()
        reply = self._get(self.pii_viewer, sid)
        self.assertEqual(reply.status_code, 200)
        body = reply.get_data(as_text=True)
        for text in ("Septic shock", "1G41", "3 days", "Pneumonia", "2 weeks", "Diabetes", "1B10 Tuberculosis",
                     "not reviewed", "Not a legal death certificate", "Certificate project", "Download PDF"):
            self.assertIn(text, body)
        self.assertIn("no-store", reply.headers["Cache-Control"])
        audit = db.session.scalars(sa.select(VaSubmissionsAuditlog).where(
            VaSubmissionsAuditlog.va_sid == sid, VaSubmissionsAuditlog.va_audit_action == "cod_certificate_viewed")).all()
        self.assertEqual(len(audit), 1)

    def test_reviewer_final_wins(self):
        sid = self._case(state="reviewer_finalized", reviewer=True)
        body = self._get(self.pii_viewer, sid).get_data(as_text=True)
        self.assertIn("CA40.Z Pneumonia", body)
        self.assertIn("Lung infection", body)
        self.assertIn("reviewer changed the cause", body)
        self.assertNotIn("Septic shock", body)
        self.assertNotIn("1B10 Tuberculosis", body)

    def test_final_without_part1_prints_blank_lines_and_the_cause(self):
        sid = self._case(cert=None)
        body = self._get(self.pii_viewer, sid).get_data(as_text=True)
        self.assertIn("1B10 Tuberculosis", body)
        self.assertEqual(body.count('class="blank"'), 5)

    def test_pii_for_a_pii_grant_and_blank_for_a_plain_viewer(self):
        sid = self._case()
        self.assertEqual(db.session.scalar(sa.select(VaDeathRegister.deceased_name).where(VaDeathRegister.va_sid == sid)), NAME)
        with_pii = self._get(self.pii_viewer, sid).get_data(as_text=True)
        for text in (NAME, "Hospital X", "Respondent Rao", f"REAL-{sid[-6:]}", self.coder.name):
            self.assertIn(text, with_pii)
        plain = self._get(self.plain_viewer, sid)
        self.assertEqual(plain.status_code, 200)
        body = plain.get_data(as_text=True)
        for text in (NAME, "Hospital X", "Respondent Rao", f"REAL-{sid[-6:]}", self.coder.name):
            self.assertNotIn(text, body)
        self.assertIn(f"MASK-{sid[-6:]}", body)
        self.assertIn("Septic shock", body)

    def test_not_available_cases_are_404_after_open_is_proven(self):
        sid = self._case()
        self.assertEqual(self._get(self.pii_viewer, sid).status_code, 200)
        self.assertEqual(self._get(self.other_viewer, sid).status_code, 404, "out of scope")
        self.assertEqual(self._get(self.pii_viewer, "uuid:no-such-case").status_code, 404)

        uncoded = self._case(state="ready_for_coding")
        self.assertEqual(self._get(self.pii_viewer, uncoded).status_code, 404)

        withdrawn = self._case()
        self.assertEqual(self._get(self.plain_viewer, withdrawn).status_code, 200)
        register = db.session.scalar(sa.select(VaDeathRegister).where(VaDeathRegister.va_sid == withdrawn))
        register.consent_withdrawn_at = datetime.now(UTC)
        db.session.commit()
        self.assertEqual(self._get(self.plain_viewer, withdrawn).status_code, 404)
        # A certificate is a use of the data: withdrawal stops it for admin too
        # (the admin's sealed view is for audit, not for issuing documents).
        self.assertEqual(self._get(self.pii_viewer, withdrawn).status_code, 404)

    def test_non_org_project_is_404(self):
        sid = self._case()
        self.assertEqual(self._get(self.pii_viewer, sid).status_code, 200)
        self.level.is_active = False
        db.session.commit()
        try:
            self.assertEqual(self._get(self.pii_viewer, sid).status_code, 404)
        finally:
            self.level.is_active = True
            db.session.commit()

    def test_condition_text_is_escaped(self):
        cert = {"Part1": [{"Conditions": [{"Text": "<script>alert(1)</script>"}]}]}
        body = self._get(self.pii_viewer, self._case(cert=cert)).get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", body)

    def test_interval_text(self):
        self.assertEqual(interval_text("P1D"), "1 day")
        self.assertEqual(interval_text("P1Y6M"), "1 year, 6 months")
        self.assertEqual(interval_text("PT5H"), "5 hours")
        self.assertEqual(interval_text("soon"), "soon")
        self.assertEqual(interval_text(None), "")

    def test_workspace_view_flags_a_coded_org_case(self):
        sid = self._case()
        self._login(str(self.plain_viewer.user_id))
        body = self.client.get(f"/api/v1/va/{sid}/workspace?mode=view").get_json()
        self.assertIs(body["case"]["certificate_available"], True)
        uncoded = self._case(state="ready_for_coding")
        body = self.client.get(f"/api/v1/va/{uncoded}/workspace?mode=view").get_json()
        self.assertIs(body["case"]["certificate_available"], False)
