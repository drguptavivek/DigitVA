"""``assess_web_intake_readiness`` says what is missing, one setting at a time.

WP2 of docs/planning/web-capture-project-configuration-plan.md; the rule is
docs/policy/web-intake.md, "Ready for web capture".

The main test walks a project from "nothing configured" to ready, and after
every step asserts both the check that was just satisfied *and* that it was
failing before — the present-before-absent rule of
docs/policy/test-harness.md, applied to a service whose whole job is to
report an absence.
"""
from datetime import UTC, datetime

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import organization_service as org
from app.services.runtime_form_sync_service import ensure_web_forms_for_project
from app.services.web_intake_readiness_service import (
    CHECK_CODES,
    WebIntakeReadinessError,
    assess_web_intake_readiness,
)
from tests.base import BaseTestCase


class WebIntakeReadinessServiceTests(BaseTestCase):
    """A project built step by step, checked after every step."""

    PROJECT_ID = "WRD001"
    SITE_ID = "WR01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        # WHO_2022_VA must exist for the fallback questionnaire to resolve:
        # active, with a base instrument and a confirmed PII set.
        cls.form_type = cls._ensure_form_type("WHO_2022_VA", "WHO VA 2022")
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Web Readiness Project",
                project_nickname="WebReady",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                web_intake_mode="off",
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id=cls.SITE_ID,
                site_name="Web Readiness Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        cls.interviewer = cls._get_or_make_user(
            "web.readiness.interviewer@test.local", "WebReady123"
        )
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _check(self, code):
        result = assess_web_intake_readiness(self.PROJECT_ID)
        by_code = {check["code"]: check for check in result["checks"]}
        self.assertIn(code, by_code, f"{code} is not reported at all")
        return by_code[code]

    def _status(self, code):
        return self._check(code)["status"]

    def _project(self):
        return db.session.get(VaProjectMaster, self.PROJECT_ID)

    def _add_site(self):
        now = datetime.now(UTC)
        db.session.add(
            VaProjectSites(
                project_id=self.PROJECT_ID,
                site_id=self.SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.flush()

    def _add_level_and_unit(self):
        level = org.create_level(
            self.PROJECT_ID, level_code="district", level_name="District", depth=1
        )
        db.session.flush()
        return level

    # ── shape ──────────────────────────────────────────────────────────────

    def test_reports_every_check_in_the_documented_order(self):
        result = assess_web_intake_readiness(self.PROJECT_ID)
        self.assertEqual(result["project_id"], self.PROJECT_ID)
        self.assertEqual(
            [check["code"] for check in result["checks"]], list(CHECK_CODES)
        )
        for check in result["checks"]:
            self.assertIn(check["status"], {"ok", "warn", "fail"})
            self.assertTrue(check["message"])

    def test_unknown_project_is_not_a_silently_empty_report(self):
        with self.assertRaises(WebIntakeReadinessError):
            assess_web_intake_readiness("NOSUCH")

    def test_ready_is_false_while_any_check_fails(self):
        result = assess_web_intake_readiness(self.PROJECT_ID)
        self.assertFalse(result["ready"])
        self.assertTrue(
            any(check["status"] == "fail" for check in result["checks"]),
            "ready was false with nothing failing",
        )

    # ── the walk ───────────────────────────────────────────────────────────

    def test_each_setting_clears_its_own_check_and_the_project_becomes_ready(self):
        # 1. Nothing configured: the four settings that stop an interview fail.
        self.assertEqual(self._status("mode"), "fail")
        self.assertEqual(self._status("sites"), "fail")
        self.assertEqual(self._status("web_forms"), "fail")
        self.assertEqual(self._status("form_type"), "fail")
        self.assertEqual(self._status("interviewers"), "fail")
        # No tree yet: legacy routing is a warning, not a failure.
        self.assertEqual(self._status("org_tree"), "warn")

        # 2. Switch web intake on. The fallback questionnaire resolves with it.
        self._project().web_intake_mode = "direct"
        db.session.flush()
        self.assertEqual(self._status("mode"), "ok")
        self.assertEqual(self._status("form_type"), "ok")

        # 3. Give the project a site.
        self._add_site()
        self.assertEqual(self._status("sites"), "ok")
        # Still no web form row: a site alone is not a questionnaire.
        self.assertEqual(self._status("web_forms"), "fail")

        # 4. Materialize the web forms.
        ensure_web_forms_for_project(self.PROJECT_ID)
        db.session.flush()
        self.assertEqual(self._status("web_forms"), "ok")

        # 5. Grant somebody the interviewer role on the project.
        db.session.add(
            VaUserAccessGrants(
                user_id=self.interviewer.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT_ID,
                notes="readiness test grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.flush()
        self.assertEqual(self._status("interviewers"), "ok")

        # 6. A display language the instrument has no translations for.
        self._project().web_intake_available_locales = ["en", "zz"]
        db.session.flush()
        self.assertEqual(self._status("locales"), "warn")
        self._project().web_intake_available_locales = ["en"]
        db.session.flush()
        self.assertEqual(self._status("locales"), "ok")

        # 7. An organization tree with no units routes nothing.
        level = self._add_level_and_unit()
        self.assertEqual(self._status("org_tree"), "fail")
        # A tree also means the questionnaire is expected to carry the level's
        # code field, and that only project-scoped interviewers is worth saying.
        geography = self._check("geography_fields")
        self.assertEqual(geography["status"], "warn")
        # Named, so the check cannot pass through the "field list could not be
        # verified" branch and look like it measured the instrument.
        self.assertIn("org_district_code", geography["message"])
        self.assertEqual(self._status("interviewers"), "warn")

        unit = org.create_unit(
            self.PROJECT_ID,
            org_level_id=level.org_level_id,
            unit_code="D1",
            unit_name="District One",
        )
        db.session.flush()
        self.assertEqual(self._status("org_tree"), "ok")

        # 8. A unit-scoped interviewer grant narrows what may be attributed.
        db.session.add(
            VaUserAccessGrants(
                user_id=self.interviewer.user_id,
                role=VaAccessRoles.interviewer,
                scope_type=VaAccessScopeTypes.org_unit,
                org_unit_id=unit.org_unit_id,
                notes="readiness test unit grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.flush()
        self.assertEqual(self._status("interviewers"), "ok")

        # 9. Unit-scoped coding with random allocation hands a coder cases from
        #    outside their units.
        project = self._project()
        project.coding_scope_level_id = level.org_level_id
        project.coding_intake_mode = "random_form_allocation"
        db.session.flush()
        self.assertEqual(self._status("coding_scope"), "fail")
        project.coding_intake_mode = "pick_and_choose"
        db.session.flush()
        self.assertEqual(self._status("coding_scope"), "ok")

        # 10. Nothing fails any more.
        result = assess_web_intake_readiness(self.PROJECT_ID)
        failing = [c["code"] for c in result["checks"] if c["status"] == "fail"]
        self.assertEqual(failing, [], f"still failing: {failing}")
        self.assertTrue(result["ready"])

    def test_a_deactivated_project_is_never_ready(self):
        project = self._project()
        project.web_intake_mode = "direct"
        db.session.flush()
        self.assertEqual(self._status("mode"), "ok")

        project.project_status = VaStatuses.deactive
        db.session.flush()
        self.assertEqual(self._status("mode"), "fail")
        self.assertFalse(assess_web_intake_readiness(self.PROJECT_ID)["ready"])

    def test_a_web_form_carrying_another_questionnaire_is_reported_as_drift(self):
        """An existing web form keeps its type; the check is where that shows.

        ``ensure_web_runtime_form`` deliberately never rewrites a live row's
        form type, so a project that changes its questionnaire keeps collecting
        the old one on sites that already have a form.
        """
        project = self._project()
        project.web_intake_mode = "direct"
        self._add_site()
        ensure_web_forms_for_project(self.PROJECT_ID)
        db.session.flush()
        self.assertEqual(self._status("web_forms"), "ok")

        other = self._ensure_form_type("WRD_OTHER", "Readiness Other Form")
        project.web_intake_form_type_id = other.form_type_id
        db.session.flush()
        self.assertEqual(self._status("web_forms"), "warn")
