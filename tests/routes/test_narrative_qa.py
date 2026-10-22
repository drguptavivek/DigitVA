from datetime import datetime, timezone
import uuid

from flask import Response

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
)
from app.routes.va_form import _apply_partial_cache_policy
from app.services.submission_payload_version_service import ensure_active_payload_version
from tests.base import BaseTestCase


class TestNarrativeQaRoute(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = f"NQ{_RUN_SUFFIX}"
    BASE_SITE_ID = f"Q{_RUN_SUFFIX[:3]}"
    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        scoped_email = f"{local_part}.{cls.BASE_PROJECT_ID.lower()}@{domain}"
        return super()._make_user(scoped_email, password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        project = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        cls._ensure_base_research_project_and_site()

        form = VaForms(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="NQA_FORM",
            odk_project_id="1",
            form_type="WHO 2022 VA",
            form_status=VaStatuses.active,
            form_registered_at=datetime.now(timezone.utc),
            form_updated_at=datetime.now(timezone.utc),
        )
        db.session.add(form)

        submission = VaSubmissions(
            va_sid=f"uuid:test-nqa-{cls.BASE_PROJECT_ID.lower()}{cls.BASE_SITE_ID.lower()}01",
            va_form_id=form.form_id,
            va_submission_date=datetime.now(timezone.utc),
            va_odk_updatedat=datetime.now(timezone.utc),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="NQA-1",
            va_uniqueid_real="NQA-1",
            va_uniqueid_masked="NQA-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=60,
            va_deceased_gender="Male",
            va_summary=[],
            va_catcount={},
            va_category_list=["vanarrationanddocuments"],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission,
            payload_data={"sid": submission.va_sid},
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        # The admin demo allocation start_demo_allocation would have written.
        db.session.add(
            VaAllocations(
                va_sid=submission.va_sid,
                va_allocated_to=cls.base_admin_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.commit()
        cls.sid = submission.va_sid

    def test_save_nqa_creates_assessment_and_audit_entry(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={
                "va_actiontype": "vademo_start_coding",
                "length": 2,
                "pos_symptoms": 2,
                "neg_symptoms": 1,
                "chronology": 1,
                "doc_review": 1,
                "comorbidity": 1,
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        nqa = db.session.scalar(
            db.select(VaNarrativeAssessment).where(
                VaNarrativeAssessment.va_sid == self.sid,
                VaNarrativeAssessment.va_nqa_by == self.base_admin_user.user_id,
            )
        )
        self.assertIsNotNone(nqa)
        self.assertEqual(nqa.va_nqa_score, 8)
        self.assertIsNotNone(nqa.payload_version_id)

        audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == self.sid,
                VaSubmissionsAuditlog.va_audit_action
                == "narrative quality assessment saved",
            )
        )
        self.assertIsNotNone(audit)

    def test_save_after_payload_change_creates_new_current_payload_row(self):
        self._login(self.base_admin_id)
        payload = {
            "va_actiontype": "vademo_start_coding",
            "length": 2,
            "pos_symptoms": 2,
            "neg_symptoms": 1,
            "chronology": 1,
            "doc_review": 1,
            "comorbidity": 1,
        }
        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json=payload,
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        submission = db.session.get(VaSubmissions, self.sid)
        first_payload_version_id = submission.active_payload_version_id

        submission.va_odk_updatedat = datetime.now(timezone.utc)
        new_payload_version = ensure_active_payload_version(
            submission,
            payload_data={"changed": True},
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        db.session.commit()

        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={**payload, "length": 3},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        rows = db.session.scalars(
            db.select(VaNarrativeAssessment)
            .where(
                VaNarrativeAssessment.va_sid == self.sid,
                VaNarrativeAssessment.va_nqa_by == self.base_admin_user.user_id,
            )
            .order_by(VaNarrativeAssessment.va_nqa_createdat.asc())
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].payload_version_id, first_payload_version_id)
        self.assertEqual(rows[0].va_nqa_status, VaStatuses.deactive)
        self.assertEqual(rows[1].payload_version_id, new_payload_version.payload_version_id)
        self.assertEqual(rows[1].va_nqa_status, VaStatuses.active)

    def test_final_assessment_waits_for_nqa(self):
        # Class-shared submission: start without an NQA whatever ran before.
        db.session.execute(db.delete(VaNarrativeAssessment).where(VaNarrativeAssessment.va_sid == self.sid))
        db.session.commit()
        self._login(self.base_admin_id)
        url = f"/vaform/{self.sid}/vafinalasses?action=vacode&actiontype=vademo_start_coding"

        response = self.client.get(url)
        body = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("data-nqa-required", body)
        self.assertNotIn("Save final assessment", body)

        saved = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={"va_actiontype": "vademo_start_coding", "length": 2, "pos_symptoms": 2,
                  "neg_symptoms": 1, "chronology": 1, "doc_review": 1, "comorbidity": 1},
            headers=self._csrf_headers(),
        )
        self.assertEqual(saved.status_code, 200)
        body = self.client.get(url).get_data(as_text=True)
        self.assertNotIn("data-nqa-required", body)

    def test_cod_assessment_partial_is_not_http_cached_in_coding_mode(self):
        response = _apply_partial_cache_policy(
            Response("ok", status=200),
            "vacodassessment",
            "vacode",
        )

        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)

    def test_narration_partial_is_not_http_cached_in_coding_mode(self):
        response = _apply_partial_cache_policy(
            Response("ok", status=200),
            "vanarrationanddocuments",
            "vacode",
        )

        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)

    # -- digitva-en2g: coding scope and allocation gate the coder write --

    _NQA_BODY = {
        "length": 2,
        "pos_symptoms": 2,
        "neg_symptoms": 1,
        "chronology": 1,
        "doc_review": 1,
        "comorbidity": 1,
    }

    def _nqa_count(self, user_id):
        return len(
            db.session.scalars(
                db.select(VaNarrativeAssessment.va_nqa_id).where(
                    VaNarrativeAssessment.va_sid == self.sid,
                    VaNarrativeAssessment.va_nqa_by == user_id,
                )
            ).all()
        )

    def _post_nqa(self, actiontype):
        return self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={"va_actiontype": actiontype, **self._NQA_BODY},
            headers=self._csrf_headers(),
        )

    def _drop_admin_allocation(self):
        db.session.execute(
            db.update(VaAllocations)
            .where(VaAllocations.va_allocated_to == self.base_admin_user.user_id)
            .values(va_allocation_status=VaStatuses.deactive)
        )
        db.session.commit()

    def _coder(self, *, in_scope):
        coder = self._make_user(f"en2g.{uuid.uuid4().hex[:8]}@test.local", "Coder@123")
        if in_scope:
            project_site_id = db.session.scalar(
                db.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == self.BASE_PROJECT_ID,
                    VaProjectSites.site_id == self.BASE_SITE_ID,
                )
            )
            self.assertIsNotNone(project_site_id)
            grant = VaUserAccessGrants(
                user_id=coder.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                grant_status=VaStatuses.active,
            )
        else:
            # A coder grant on another project's site: the coder role holds,
            # the coding scope does not reach this submission.
            suffix = uuid.uuid4().hex[:4].upper()
            db.session.add(
                VaProjectMaster(
                    project_id=f"OX{suffix}",
                    project_code=f"OX{suffix}",
                    project_name="Other Project",
                    project_nickname="Other",
                    project_status=VaStatuses.active,
                )
            )
            db.session.add(
                VaSiteMaster(
                    site_id=suffix,
                    site_name="Other Site",
                    site_abbr=suffix,
                    site_status=VaStatuses.active,
                )
            )
            db.session.flush()
            other_site = VaProjectSites(
                project_id=f"OX{suffix}",
                site_id=suffix,
                project_site_status=VaStatuses.active,
            )
            db.session.add(other_site)
            db.session.add(
                VaResearchProjects(
                    project_id=f"OX{suffix}",
                    project_code=f"OX{suffix}",
                    project_name="Other Project",
                    project_nickname="Other",
                    project_status=VaStatuses.active,
                )
            )
            db.session.flush()
            db.session.add(
                VaSites(
                    site_id=suffix,
                    project_id=f"OX{suffix}",
                    site_name="Other Site",
                    site_abbr=suffix,
                    site_status=VaStatuses.active,
                )
            )
            db.session.flush()
            db.session.add(
                VaForms(
                    form_id=f"OX{suffix}{suffix}01",
                    project_id=f"OX{suffix}",
                    site_id=suffix,
                    odk_form_id="OTHER_FORM",
                    odk_project_id="1",
                    form_type="WHO 2022 VA",
                    form_status=VaStatuses.active,
                )
            )
            db.session.flush()
            grant = VaUserAccessGrants(
                user_id=coder.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=other_site.project_site_id,
                grant_status=VaStatuses.active,
            )
        db.session.add(grant)
        db.session.add(
            VaAllocations(
                va_sid=self.sid,
                va_allocated_to=coder.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.commit()
        return coder

    def test_admin_demo_save_on_a_real_submission_needs_its_allocation(self):
        self._drop_admin_allocation()
        self._login(self.base_admin_id)
        before = self._nqa_count(self.base_admin_user.user_id)

        response = self._post_nqa("vademo_start_coding")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "no_allocation")
        self.assertEqual(self._nqa_count(self.base_admin_user.user_id), before)

    def test_admin_demo_save_on_a_demo_submission_needs_no_allocation(self):
        self._drop_admin_allocation()
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.demo_training_enabled = True
        db.session.commit()
        self._login(self.base_admin_id)

        response = self._post_nqa("vademo_start_coding")

        self.assertEqual(response.status_code, 200)
        self.assertGreater(self._nqa_count(self.base_admin_user.user_id), 0)

    def test_coder_with_allocation_but_outside_coding_scope_is_refused(self):
        coder = self._coder(in_scope=False)
        self._login(str(coder.user_id))

        response = self._post_nqa("vastartcoding")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "forbidden")
        self.assertEqual(
            response.get_json()["error"],
            "This submission is outside your coding scope.",
        )
        self.assertEqual(self._nqa_count(coder.user_id), 0)

    def test_coder_with_scope_and_allocation_saves(self):
        coder = self._coder(in_scope=True)
        self._login(str(coder.user_id))

        response = self._post_nqa("vastartcoding")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._nqa_count(coder.user_id), 1)

    def test_coder_demo_save_on_a_demo_submission_passes_the_scope_check(self):
        # Coding on a demo-training project comes from the virtual demo grant.
        coder = self._coder(in_scope=False)
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.demo_training_enabled = True
        db.session.commit()
        self._login(str(coder.user_id))

        response = self._post_nqa("vademo_start_coding")

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(self._nqa_count(coder.user_id), 1)
