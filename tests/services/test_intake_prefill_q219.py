"""Prefill locks after the 2026-10-03 owner decision (digitva-q219).

Interviewer age (Id10010a) is neither prefilled nor locked; the deceased's
registered age is prefilled and locked (server-enforced by overwrite, as
every locked prefill is, docs/policy/web-intake.md "Locked prefill"); the
date of birth, exact or partial, stays editable; a draft whose stored
prefill has no ``lockedQuestionNames`` is recomputed from the case.
"""
from datetime import UTC, date, datetime, timedelta

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaUserAccessGrants,
)
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase

AGE_NAMES = {"age_group", "age_adult", "age_child_unit", "age_child_years", "age_child_months", "age_child_days"}


class IntakePrefillQ219Tests(BaseTestCase):
    PROJECT_ID = "Q2191"
    SITE_ID = "Q219"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Q219 Prefill",
            project_nickname="Q219", project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Q219 Site", site_abbr=cls.SITE_ID,
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
            form_id="Q2191Q21901", project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_Q2191", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        cls.interviewer = cls._get_or_make_user("q219.interviewer@test.local", "Q219Intake123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID,
            notes="q219 test grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.interviewer.name = "Field Worker"
        self.interviewer.sex = "female"
        self.interviewer.year_of_birth = date.today().year - 40

    def _start(self, **overrides):
        fields = {
            "deceased_name": "Asha Devi", "deceased_sex": "female",
            "date_of_death": (date.today() - timedelta(days=10)).isoformat(), "age_years": 62,
        }
        fields.update(overrides)
        death = intake_svc.register_death(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, **fields)
        return intake_svc.start_draft(
            self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id,
        )

    def _submit(self, draft, answers):
        data = {
            "Id10013": "yes", "Id10017": "Asha", "Id10018": "Devi", "Id10019": "female",
            "Id10023": (date.today() - timedelta(days=10)).isoformat(), "finalAgeInYears": "62",
            "narr_language": "english", **answers,
        }
        submission = intake_svc.submit_draft(
            draft, self.interviewer, completion={"valid": True, "issues": [], "data": data},
        )
        return db.session.get(VaSubmissionPayloadVersion, submission.active_payload_version_id).payload_data

    # ── interviewer age ────────────────────────────────────────────────────

    def test_interviewer_age_is_neither_prefilled_nor_locked(self):
        prefill = self._start().prefill
        self.assertEqual(prefill["interviewer"]["sex"], "female")
        self.assertNotIn("age", prefill["interviewer"])
        self.assertIn("Id10010c", prefill["lockedQuestionNames"])
        self.assertNotIn("Id10010a", prefill["lockedQuestionNames"])

    def test_interviewer_age_entered_in_the_interview_is_kept(self):
        payload = self._submit(self._start(), {"Id10010a": 33})
        self.assertEqual(payload["Id10010a"], 33)

    def test_a_stored_lock_list_naming_id10010a_no_longer_enforces_it(self):
        legacy = {"lockedQuestionNames": ["Id10010a", "Id10010c"], "interviewer": {"age": 40, "id": "u-1"}}
        self.assertEqual(intake_svc._locked_answers(legacy), {"Id10010c": "u-1"})

    # ── deceased's registered age ──────────────────────────────────────────

    def test_registered_adult_age_is_prefilled_and_locked(self):
        prefill = self._start().prefill
        self.assertEqual(prefill["deceased"]["ageInYears"], 62)
        self.assertEqual({k: prefill["answers"][k] for k in ("age_group", "age_adult")},
                         {"age_group": "adult", "age_adult": 62})
        self.assertTrue({"age_group", "age_adult"} <= set(prefill["lockedQuestionNames"]))
        self.assertNotIn("Id10020", prefill["lockedQuestionNames"])

    def test_registered_child_age_is_prefilled_and_locked(self):
        prefill = self._start(age_years=5).prefill
        locked = set(prefill["lockedQuestionNames"])
        self.assertTrue({"age_group", "age_child_unit", "age_child_years"} <= locked)
        self.assertEqual(prefill["answers"]["age_child_years"], 5)
        self.assertNotIn("age_adult", locked)

    def test_submit_that_changes_the_age_stores_the_registered_age(self):
        payload = self._submit(self._start(), {"Id10020": "no", "age_group": "child", "age_adult": 30})
        self.assertEqual((payload["age_group"], payload["age_adult"]), ("adult", 62))

    def test_submit_with_the_unchanged_age_stores_it(self):
        payload = self._submit(self._start(), {"Id10020": "no", "age_group": "adult", "age_adult": 62})
        self.assertEqual((payload["age_group"], payload["age_adult"]), ("adult", 62))

    def test_draft_save_that_changes_the_age_keeps_the_registered_age(self):
        draft = self._start()
        intake_svc.save_draft_sections(draft, sections={"background": {"Id10020": "no", "age_adult": 30}})
        self.assertEqual(draft.sections[0].data, {"Id10020": "no", "age_adult": 62})

    def test_registration_without_age_locks_nothing_age_related(self):
        prefill = self._start(age_years=None).prefill
        self.assertIn("Id10010c", prefill["lockedQuestionNames"])
        self.assertFalse(AGE_NAMES & set(prefill["lockedQuestionNames"]))
        self.assertFalse(AGE_NAMES & set(prefill["answers"]))

    def test_age_zero_locks_nothing_age_related(self):
        prefill = self._start(age_years=0).prefill
        self.assertIn("Id10010c", prefill["lockedQuestionNames"])
        self.assertFalse(AGE_NAMES & set(prefill["lockedQuestionNames"]))

    # ── date of birth stays editable ───────────────────────────────────────

    def test_partial_birth_date_is_prefilled_and_editable(self):
        draft = self._start(date_of_birth_partial="1962", age_years=62)
        self.assertEqual(draft.prefill["answers"]["dob_year"], "1962-01-01")
        self.assertFalse({"Id10020", "dob_precision", "dob_year", "dob_month_year"}
                         & set(draft.prefill["lockedQuestionNames"]))
        payload = self._submit(draft, {
            "Id10020": "no", "dob_precision": "month_year", "dob_month_year": "1962-03-01",
            "age_group": "adult", "age_adult": 62,
        })
        self.assertEqual((payload["dob_precision"], payload["dob_month_year"]), ("month_year", "1962-03-01"))
        self.assertEqual(payload["age_adult"], 62)

    def test_exact_birth_date_is_prefilled_editable_and_locks_no_age(self):
        dob = date.today() - timedelta(days=365 * 62)
        draft = self._start(date_of_birth=dob.isoformat(), age_years=62)
        self.assertEqual(draft.prefill["deceased"]["dateOfBirth"], dob.isoformat())
        self.assertFalse(AGE_NAMES & set(draft.prefill["lockedQuestionNames"]))
        changed = (dob - timedelta(days=40)).isoformat()
        payload = self._submit(draft, {"Id10020": "yes", "Id10021": changed})
        self.assertEqual(payload["Id10021"], changed)

    # ── legacy drafts: no lockedQuestionNames ──────────────────────────────

    def test_legacy_draft_save_still_enforces_the_age(self):
        draft = self._start()
        draft.prefill = {"answers": {}}  # saved before lockedQuestionNames existed
        intake_svc.save_draft_sections(draft, sections={"background": {"age_group": "adult", "age_adult": 30}})
        self.assertEqual(draft.sections[0].data["age_adult"], 62)
        self.assertEqual(draft.prefill, {"answers": {}})

    def test_legacy_draft_submit_still_enforces_the_age(self):
        draft = self._start()
        draft.prefill = {}
        payload = self._submit(draft, {"Id10020": "no", "age_group": "adult", "age_adult": 30})
        self.assertEqual(payload["age_adult"], 62)

    def test_draft_with_an_older_lock_list_still_enforces_the_age(self):
        draft = self._start()
        # Saved before the age lock: a list that names only the interviewer.
        draft.prefill = {"lockedQuestionNames": ["Id10010a", "Id10010c"], "answers": {}}
        payload = self._submit(draft, {"Id10020": "no", "age_group": "adult", "age_adult": 30})
        self.assertEqual(payload["age_adult"], 62)
