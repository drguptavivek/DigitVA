"""Tests for the /intake pages and JSON API (app/routes/intake.py).

The route layer is thin, so these cover what only it can decide:
  - unauthenticated and non-interviewer callers are refused (401/403), with
    JSON for /intake/api/* and a redirect/abort for the pages
  - browser-originated state changes require the X-CSRFToken header
  - the happy path: bootstrap -> register a death -> start a draft -> save a
    section -> submit, each committing its own step
  - WebIntakeError maps to its status code and rolls the session back
"""
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.services import organization_service as org
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase


class IntakeApiTests(BaseTestCase):
    PROJECT_ID = "WIA01"
    SITE_ID = "WA01"
    ODK_FORM_ID = "WIA01WA0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="Intake Api Project",
            project_nickname="IntakeApi",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
            web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="Intake Api Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        db.session.add(VaForms(
            form_id=cls.ODK_FORM_ID,
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            odk_form_id="ODK_INTAKE_API",
            odk_project_id="7",
            form_type="WHO VA 2022",
            form_source="odk",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.flush()

        cls.interviewer = cls._get_or_make_user("api.interviewer@test.local", "IntakeApi123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT_ID,
            notes="intake api test grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

        cls.interviewer_id = str(cls.interviewer.user_id)

    # ── helpers ────────────────────────────────────────────────────────────

    def _death_payload(self, **overrides):
        payload = {
            "project_id": self.PROJECT_ID,
            "site_id": self.SITE_ID,
            "deceased_name": "Bina Sahu",
            "deceased_sex": "female",
            "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            "age_years": 71,
        }
        payload.update(overrides)
        return payload

    def _start_draft(self, **body):
        response = self.client.post(
            "/intake/api/drafts",
            json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID, **body},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["draft"]

    # ── authentication and role ────────────────────────────────────────────

    def test_api_requires_authentication_with_json_401(self):
        response = self.client.get("/intake/api/bootstrap")
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.get_json())

    def test_api_requires_the_interviewer_role(self):
        self._login(self.base_coder_id)
        response = self.client.get("/intake/api/bootstrap")
        self.assertEqual(response.status_code, 403)
        self.assertIn("interviewer", response.get_json()["error"])

        response = self.client.post(
            "/intake/api/deaths", json=self._death_payload(), headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 403)

    def test_pages_require_the_interviewer_role(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/intake/").status_code, 403)
        self.assertEqual(self.client.get("/intake/deaths/new").status_code, 403)

    def test_pages_redirect_an_anonymous_visitor_to_login(self):
        response = self.client.get("/intake/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("valogin", response.headers["Location"])

    # ── CSRF ───────────────────────────────────────────────────────────────

    def test_state_changing_calls_require_the_csrf_header(self):
        self._login(self.interviewer_id)
        self.assertEqual(
            self.client.post("/intake/api/deaths", json=self._death_payload()).status_code, 400
        )
        self.assertEqual(
            self.client.post(
                "/intake/api/drafts",
                json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID},
            ).status_code,
            400,
        )
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), 0)

    def test_reads_do_not_require_the_csrf_header(self):
        self._login(self.interviewer_id)
        self.assertEqual(self.client.get("/intake/api/bootstrap").status_code, 200)
        self.assertEqual(self.client.get("/intake/api/drafts").status_code, 200)

    # ── bootstrap ──────────────────────────────────────────────────────────

    def test_bootstrap_returns_csrf_token_user_and_scope(self):
        self._login(self.interviewer_id)
        body = self.client.get("/intake/api/bootstrap").get_json()

        self.assertEqual(body["csrf_header_name"], "X-CSRFToken")
        self.assertTrue(body["csrf_token"])
        self.assertEqual(body["user"]["user_id"], self.interviewer_id)
        self.assertEqual(
            [(c["project_id"], c["site_id"]) for c in body["context"]],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        self.assertEqual(body["context"][0]["web_intake_mode"], "both")

    # ── happy path ─────────────────────────────────────────────────────────

    def test_register_list_start_save_and_submit(self):
        self._login(self.interviewer_id)

        response = self.client.post(
            "/intake/api/deaths", json=self._death_payload(), headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        death = response.get_json()["death"]
        self.assertTrue(death["unique_id"].startswith(f"{self.SITE_ID}-"))
        self.assertEqual(death["status"], "registered")

        listed = self.client.get(
            f"/intake/api/deaths?project_id={self.PROJECT_ID}&site_id={self.SITE_ID}"
        ).get_json()["deaths"]
        self.assertIn(death["death_id"], [d["death_id"] for d in listed])

        draft = self._start_draft(death_id=death["death_id"])
        self.assertEqual(draft["death_id"], death["death_id"])
        self.assertEqual(draft["unique_id"], death["unique_id"])

        saved = self.client.patch(
            f"/intake/api/drafts/{draft['draft_id']}",
            json={
                "sections": {"consent": {"Id10013": "yes"}, "background": {"Id10019": "female"}},
                "current_section": "background",
                "meta": {"schemaVersion": 1, "formVersion": "2022"},
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(saved.get_json()["saved_sections"], 2)
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(VaWebIntakeDraftSection)
                .where(VaWebIntakeDraftSection.draft_id == draft["draft_id"])
            ),
            2,
        )

        fetched = self.client.get(f"/intake/api/drafts/{draft['draft_id']}").get_json()
        self.assertEqual(fetched["envelope"]["currentSection"], "background")
        self.assertEqual(fetched["envelope"]["data"]["Id10013"], "yes")

        submitted = self.client.post(
            f"/intake/api/drafts/{draft['draft_id']}/submit",
            json={
                "completion": {
                    "valid": True,
                    "issues": [],
                    "data": {
                        "Id10013": "yes",
                        "Id10019": "female",
                        "finalAgeInYears": "71",
                        "narr_language": "english",
                    },
                }
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(submitted.status_code, 201, submitted.get_json())
        va_sid = submitted.get_json()["va_sid"]
        self.assertIsNotNone(db.session.get(VaSubmissions, va_sid))
        self.assertEqual(submitted.get_json()["draft"]["status"], "submitted")
        self.assertEqual(
            db.session.get(VaDeathRegister, death["death_id"]).status, "va_submitted"
        )

    def test_form_page_takes_its_locale_and_instrument_from_form_options(self):
        """The rendered page must not decide anything the project owns.

        Contract: docs/policy/va-web-form-options.md. The locale used to be
        hardcoded ``"en"`` in the template; it now comes from
        ``/api/v1/organization/<project_id>/form-options``, which the page can
        only call because the draft JSON carries ``project_id``, narrowed by
        the interviewer's own remembered choice.
        """
        self._login(self.interviewer_id)
        draft = self._start_draft()
        body = self.client.get(f"/intake/form/{draft['draft_id']}").get_data(as_text=True)

        self.assertNotIn('setAttribute("locale", "en")', body)
        self.assertIn("const locale = workingLocale(options);", body)
        # The attribute is set by applyLocale, alongside the instrument copy
        # that carries that locale's translations.
        self.assertIn('el.setAttribute("locale", locale);', body)
        # The working language is chosen from what the project serves and
        # remembered per browser, never stored server-side.
        self.assertIn("options.available_locales", body)
        self.assertIn('"digitva.intake.locale"', body)
        # Translations are fetched per locale from the serving endpoint and
        # applied client-side to a copy of the pre-built instrument (WP6).
        self.assertIn("/api/v1/instruments/", body)
        self.assertIn("applyTranslations(baseInstrument, translations, locale)", body)
        self.assertIn("js/intake/translations.js", body)
        # The per-section autosave map must follow the selected instrument too,
        # or a second INSTRUMENTS entry would be split by WHO 2022's sections.
        self.assertNotIn("const instrument = WhoVa.whoVa2022Instrument", body)
        self.assertIn("sectionOf = sectionMapFor(chosenInstrument)", body)
        # A form type is a layer on a standard instrument, so the instrument is
        # resolved from the served instrument_code, never from form_type_code.
        self.assertNotIn(
            "INSTRUMENT_FACTORIES[defaultFormType.form_type_code]", body
        )
        self.assertIn(
            "INSTRUMENT_FACTORIES[defaultFormType.instrument_code]", body
        )
        # The layers a project enabled decide what the instrument carries, so
        # the factory is called with the served list rather than the all-on
        # constant (digitva-thr).
        self.assertIn("buildInstrument(options.enabled_extensions || [])", body)
        self.assertIn("/form-options", body)
        self.assertIn(f'"project_id": "{self.PROJECT_ID}"', body)

    def test_form_page_renders_for_the_owner_and_404s_for_anyone_else(self):
        self._login(self.interviewer_id)
        draft = self._start_draft()
        self.assertEqual(self.client.get(f"/intake/form/{draft['draft_id']}").status_code, 200)

        other = self._get_or_make_user("api.interviewer2@test.local", "IntakeApi123")
        db.session.add(VaUserAccessGrants(
            user_id=other.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID,
            notes="second intake api interviewer",
            grant_status=VaStatuses.active,
        ))
        db.session.flush()
        self._login(str(other.user_id))
        self.assertEqual(self.client.get(f"/intake/form/{draft['draft_id']}").status_code, 404)

    # ── error mapping ──────────────────────────────────────────────────────

    def test_service_errors_map_to_their_status_codes(self):
        self._login(self.interviewer_id)

        response = self.client.post(
            "/intake/api/deaths",
            json=self._death_payload(deceased_sex="other"),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)

        response = self.client.post(
            "/intake/api/deaths",
            json=self._death_payload(project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)

        self.assertEqual(
            self.client.get("/intake/api/drafts/not-a-uuid").status_code, 404
        )
        self.assertEqual(
            self.client.get("/intake/api/deaths").status_code, 400
        )

        draft = self._start_draft()
        response = self.client.post(
            f"/intake/api/drafts/{draft['draft_id']}/submit",
            json={"completion": {"valid": False, "data": {"Id10013": "yes"}}},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_a_rejected_registration_leaves_nothing_behind(self):
        self._login(self.interviewer_id)
        before = db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister))
        response = self.client.post(
            "/intake/api/deaths",
            json=self._death_payload(date_of_death=(date.today() + timedelta(days=1)).isoformat()),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), before
        )

    def test_discard_frees_the_death_for_a_new_draft(self):
        self._login(self.interviewer_id)
        death = self.client.post(
            "/intake/api/deaths", json=self._death_payload(), headers=self._csrf_headers()
        ).get_json()["death"]
        draft = self._start_draft(death_id=death["death_id"])

        response = self.client.post(
            f"/intake/api/drafts/{draft['draft_id']}/discard", headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["draft"]["status"], "discarded")
        self.assertEqual(db.session.get(VaDeathRegister, death["death_id"]).status, "registered")

        again = self._start_draft(death_id=death["death_id"])
        self.assertNotEqual(again["draft_id"], draft["draft_id"])


class WebOnlyProjectIntakeTests(BaseTestCase):
    """A project that collects only on the web, plus a unit-scoped interviewer.

    Both cases turn on the interviewer role gate: ``is_interviewer()`` resolves
    through ``va_forms``, which a web-only project has no ODK mapping to
    populate, and which unit-scoped grants never reach.
    """

    PROJECT_ID = "WIB01"
    SITE_ID = "WB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="Web Only Project",
            project_nickname="WebOnly",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
            web_intake_mode="off",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="Web Only Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)

        # Deliberately no va_forms row: there is no ODK mapping for this project.
        cls.interviewer = cls._get_or_make_user("weponly.interviewer@test.local", "WebOnly123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project,
            project_id=cls.PROJECT_ID,
            notes="web-only interviewer grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        cls.interviewer_id = str(cls.interviewer.user_id)

    def _web_forms(self):
        return db.session.scalars(
            sa.select(VaForms).where(
                VaForms.project_id == self.PROJECT_ID, VaForms.form_source == "web"
            )
        ).all()

    def test_enabling_web_intake_materializes_the_web_form_for_active_sites(self):
        # Before: no form at all, so the interviewer cannot even reach /intake/.
        self.assertEqual(self._web_forms(), [])
        self._login(self.interviewer_id)
        self.assertEqual(self.client.get("/intake/api/bootstrap").status_code, 403)

        self._login(self.base_admin_id)
        response = self.client.put(
            f"/admin/api/projects/{self.PROJECT_ID}",
            json={"web_intake_mode": "both"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["project"]["web_intake_mode"], "both")

        forms = self._web_forms()
        self.assertEqual([f.site_id for f in forms], [self.SITE_ID])
        self.assertEqual(forms[0].form_status, VaStatuses.active)

        # After: the same interviewer is now in scope and can start a draft.
        self._login(self.interviewer_id)
        body = self.client.get("/intake/api/bootstrap").get_json()
        self.assertEqual(
            [(c["project_id"], c["site_id"]) for c in body["context"]],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        started = self.client.post(
            "/intake/api/drafts",
            json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID},
            headers=self._csrf_headers(),
        )
        self.assertEqual(started.status_code, 201, started.get_json())
        self.assertEqual(started.get_json()["draft"]["form_id"], forms[0].form_id)

    def test_enabling_web_intake_is_idempotent(self):
        self._login(self.base_admin_id)
        for _ in range(2):
            self.client.put(
                f"/admin/api/projects/{self.PROJECT_ID}",
                json={"web_intake_mode": "direct"},
                headers=self._csrf_headers(),
            )
        self.assertEqual(len(self._web_forms()), 1)

    def test_switching_web_intake_off_creates_no_form(self):
        self._login(self.base_admin_id)
        response = self.client.put(
            f"/admin/api/projects/{self.PROJECT_ID}",
            json={"web_intake_mode": "off"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._web_forms(), [])

    def test_a_unit_scoped_grant_alone_opens_the_interviewer_role_gate(self):
        org.seed_default_organization(self.PROJECT_ID)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT_ID)}
        district = org.create_unit(
            self.PROJECT_ID,
            org_level_id=levels["district"].org_level_id,
            unit_code="WBD01",
            unit_name="Web Only District",
        )
        chc = org.create_unit(
            self.PROJECT_ID,
            org_level_id=levels["chc"].org_level_id,
            parent_org_unit_id=district.org_unit_id,
            unit_code="WBC01",
            unit_name="Web Only CHC",
        )
        unit = org.create_unit(
            self.PROJECT_ID,
            org_level_id=levels["phc"].org_level_id,
            parent_org_unit_id=chc.org_unit_id,
            unit_code="WBP01",
            unit_name="Web Only PHC",
        )
        unit_user = self._get_or_make_user("webonly.unit@test.local", "WebOnly123")
        db.session.add(VaUserAccessGrants(
            user_id=unit_user.user_id,
            role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=unit.org_unit_id,
            grant_status=VaStatuses.active,
        ))
        project = db.session.get(VaProjectMaster, self.PROJECT_ID)
        project.web_intake_mode = "both"
        db.session.commit()

        # The user holds no project or project_site grant, so no va_forms row
        # resolves for them; the role gate must still let them through.
        self.assertEqual(unit_user.get_interviewer_va_forms(), set())
        self.assertTrue(unit_user.is_interviewer())

        self._login(str(unit_user.user_id))
        body = self.client.get("/intake/api/bootstrap").get_json()
        self.assertEqual(
            [(c["project_id"], c["site_id"]) for c in body["context"]],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        self.assertEqual(
            [u["unit_code"] for u in body["context"][0]["org_units"]], ["WBP01"]
        )

    def test_the_role_gate_stays_shut_without_any_interviewer_grant(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/intake/api/bootstrap").status_code, 403)
