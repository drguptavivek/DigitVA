"""Tests for the /intake pages (app/routes/intake.py) and the /api/v1/intake JSON API
(app/routes/api/intake.py).

The route layer is thin, so these cover what only it can decide:
  - unauthenticated and non-interviewer callers are refused (401/403), with
    JSON for /api/v1/intake/* and a redirect/abort for the pages
  - browser-originated state changes require the X-CSRFToken header
  - the happy path: register a death -> start a draft -> save a
    section -> submit, each committing its own step
  - WebIntakeError maps to its status code and rolls the session back
"""
import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    MapUserNotification,
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
from app.services import organization_service as org
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase


def _page_context(client):
    """The scope list the dashboard renders for its script."""
    html = client.get("/intake/").get_data(as_text=True)
    found = re.search(r'<script id="intake-context" type="application/json">(.*?)</script>', html, re.S)
    assert found is not None
    return json.loads(found.group(1))


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
            "/api/v1/intake/drafts",
            json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID, **body},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["draft"]

    # ── authentication and role ────────────────────────────────────────────

    def test_api_requires_authentication_with_json_401(self):
        response = self.client.get("/api/v1/intake/cases")
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.get_json())

    def test_api_requires_the_interviewer_role(self):
        self._login(self.base_coder_id)
        response = self.client.get("/api/v1/intake/cases")
        self.assertEqual(response.status_code, 403)
        self.assertIn("interviewer", response.get_json()["error"])

        response = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(), headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 403)

    def test_pages_require_the_interviewer_role(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/intake/").status_code, 403)
        self.assertEqual(self.client.get("/intake/deaths/new").status_code, 403)

    def test_dashboard_renders_one_worklist_instead_of_the_two_old_lists(self):
        self._login(self.interviewer_id)
        response = self.client.get("/intake/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for marker in ('id="intake-worklist"', 'id="intake-tabs"', 'id="intake-mine"',
                       'id="intake-load-more"', 'js/intake/intake_worklist.js',
                       'id="intake-scope"', 'id="intake-new-death"', 'id="intake-new-direct"'):
            self.assertIn(marker, html)
        self.assertIn('data-user-tz="', html)
        for gone in ('id="intake-drafts"', 'id="intake-deaths"', "My drafts", "Registered deaths"):
            self.assertNotIn(gone, html)

    def test_pages_redirect_an_anonymous_visitor_to_login(self):
        response = self.client.get("/intake/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("valogin", response.headers["Location"])

    # ── CSRF ───────────────────────────────────────────────────────────────

    def test_state_changing_calls_require_the_csrf_header(self):
        self._login(self.interviewer_id)
        self.assertEqual(
            self.client.post("/api/v1/intake/deaths", json=self._death_payload()).status_code, 400
        )
        self.assertEqual(
            self.client.post(
                "/api/v1/intake/drafts",
                json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID},
            ).status_code,
            400,
        )
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), 0)

    def test_reads_do_not_require_the_csrf_header(self):
        self._login(self.interviewer_id)
        self.assertEqual(self.client.get("/api/v1/intake/cases").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/intake/drafts").status_code, 200)

    # ── page context (no bootstrap route: the page renders it) ─────────────

    def test_dashboard_renders_csrf_token_and_scope_for_its_script(self):
        self._login(self.interviewer_id)
        html = self.client.get("/intake/").get_data(as_text=True)
        found = re.search(r'id="intake-worklist" data-csrf="([^"]+)"', html)
        self.assertIsNotNone(found)
        context = _page_context(self.client)
        self.assertEqual(
            [(c["project_id"], c["site_id"]) for c in context],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        self.assertEqual(context[0]["web_intake_mode"], "both")
        self.assertEqual(self.client.get("/intake/api/bootstrap").status_code, 404)

    # ── case detail (digitva-p6fs.24) ──────────────────────────────────────

    def test_case_detail_is_for_interviewers_in_scope_with_full_contacts(self):
        url = f"/api/v1/intake/cases/{uuid.uuid4()}"
        self.assertEqual(self.client.get(url).status_code, 401)
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get(url).status_code, 403)

        self._login(self.interviewer_id)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/intake/cases/not-a-uuid").status_code, 404)
        created = self.client.post(
            "/api/v1/intake/deaths",
            json=self._death_payload(informant_name="Mohan Das", informant_phone="9876543210",
                                     address_village_ward="Ward 4", father_name="Hari Das"),
            headers=self._csrf_headers(),
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        death_id = created.get_json()["case"]["death_id"]

        response = self.client.get(f"/api/v1/intake/cases/{death_id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        case = response.get_json()["case"]
        self.assertEqual(case["informant"]["phone"], "9876543210")
        self.assertEqual(case["informant"]["name"], "Mohan Das")
        self.assertEqual(case["household_address"]["village_ward"], "Ward 4")
        # The detail's own fields carry no parents' names; its prefill, for an
        # interview started offline, keeps what it always carried.
        self.assertNotIn("Hari Das", json.dumps({k: v for k, v in case.items() if k != "prefill"}))
        self.assertEqual(case["prefill"]["answers"]["Id10007"], "Mohan Das")
        self.assertIsNone(case["my_draft_id"])
        self.assertNotIn("form", case["links"])
        self.assertEqual(case["links"]["start_interview"], "/api/v1/intake/drafts")
        self.assertEqual(case["links"]["visit"], f"/api/v1/intake/cases/{death_id}/visit")

        draft = self._start_draft(death_id=death_id)
        case = self.client.get(f"/api/v1/intake/cases/{death_id}").get_json()["case"]
        self.assertEqual(case["my_draft_id"], draft["draft_id"])
        self.assertEqual(case["links"]["form"], f"/intake/form/{draft['draft_id']}")
        self.assertEqual(case["state"], "in_progress")

    def test_browser_submit_after_a_teammate_won_replies_superseded_and_leaves_the_case(self):
        self._login(self.interviewer_id)
        death_id = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(), headers=self._csrf_headers(),
        ).get_json()["case"]["death_id"]
        other = self._get_or_make_user("api.parallel.other@test.local", "IntakeApi123")
        db.session.add(VaUserAccessGrants(
            user_id=other.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID, notes="parallel interviewer", grant_status=VaStatuses.active,
        ))
        db.session.flush()
        mine = self._start_draft(death_id=death_id)
        self._login(str(other.user_id))
        theirs = self._start_draft(death_id=death_id)
        self.assertNotEqual(mine["draft_id"], theirs["draft_id"])

        def completion(**data):
            return {"completion": {"valid": True, "issues": [], "data": {
                "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
                "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
                "narr_language": "english", **data}}}

        won = self.client.post(f"/api/v1/intake/drafts/{theirs['draft_id']}/submit",
                               json=completion(), headers=self._csrf_headers())
        self.assertEqual(won.status_code, 201, won.get_json())
        self._login(self.interviewer_id)
        late = self.client.post(f"/api/v1/intake/drafts/{mine['draft_id']}/submit",
                                json=completion(Id10017="Other"), headers=self._csrf_headers())
        self.assertEqual(late.status_code, 200, late.get_json())
        body = late.get_json()
        self.assertIsNone(body["va_sid"])
        self.assertIs(body["superseded"], True)
        self.assertIsNone(body["validation_err"])
        self.assertEqual(body["draft"]["status"], "superseded")
        case = db.session.get(VaDeathRegister, death_id)
        self.assertEqual((case.status, case.deceased_name, case.va_sid), ("submitted", "Bina Sahu", won.get_json()["va_sid"]))
        # The case detail still hides the winner's submission id from this interviewer.
        self.assertIsNone(self.client.get(f"/api/v1/intake/cases/{death_id}").get_json()["case"]["va_sid"])

    def test_parallel_interviewers_are_nudged_when_a_draft_starts_and_when_a_teammate_wins(self):
        self._login(self.interviewer_id)
        death_id = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(), headers=self._csrf_headers(),
        ).get_json()["case"]["death_id"]
        users = {}
        for name in ("a", "b", "c"):
            user = self._get_or_make_user(f"api.nudge.{name}@test.local", "IntakeApi123")
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
                project_id=self.PROJECT_ID, notes="nudge interviewer", grant_status=VaStatuses.active,
            ))
            users[name] = user
        db.session.flush()

        def rows(name):
            db.session.expire_all()
            return [
                (r.kind, r.project_id, str(r.death_id), str(r.draft_id), r.va_sid)
                for r in db.session.scalars(
                    sa.select(MapUserNotification).where(MapUserNotification.user_id == users[name].user_id)
                    .order_by(MapUserNotification.id))
            ]

        drafts = {}
        for name in ("a", "b", "c"):
            self._login(str(users[name].user_id))
            drafts[name] = self._start_draft(death_id=death_id)["draft_id"]
            self._start_draft(death_id=death_id)  # resuming one's own draft nudges nobody
        def started(name):
            return ("other_draft_started", self.PROJECT_ID, death_id, drafts[name], None)

        self.assertEqual(rows("a"), [started("a"), started("a")])  # b and c started after a
        self.assertEqual(rows("b"), [started("b")])  # c started after b
        self.assertEqual(rows("c"), [])

        self._login(str(users["c"].user_id))
        won = self.client.post(f"/api/v1/intake/drafts/{drafts['c']}/submit", headers=self._csrf_headers(), json={
            "completion": {"valid": True, "issues": [], "data": {
                "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
                "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
                "narr_language": "english"}}})
        self.assertEqual(won.status_code, 201, won.get_json())
        def closed(name):
            return ("case_submitted_by_other", self.PROJECT_ID, death_id, drafts[name], None)

        self.assertEqual(rows("a")[-1], closed("a"))
        self.assertEqual(rows("b")[-1], closed("b"))
        self.assertEqual((len(rows("a")), len(rows("b")), len(rows("c"))), (3, 2, 0))

        # Their late submit becomes a superseded copy: the case is already closed, nobody is told again.
        self._login(str(users["a"].user_id))
        late = self.client.post(f"/api/v1/intake/drafts/{drafts['a']}/submit", headers=self._csrf_headers(), json={
            "completion": {"valid": True, "issues": [], "data": {"Id10013": "yes", "narr_language": "english"}}})
        self.assertEqual(late.status_code, 200, late.get_json())
        self.assertEqual((len(rows("a")), len(rows("b")), len(rows("c"))), (3, 2, 0))

    def test_case_detail_carries_prefill_only_for_a_caller_who_may_start_or_resume(self):
        self._login(self.interviewer_id)
        created = self.client.post(
            "/api/v1/intake/deaths",
            json=self._death_payload(informant_name="Mohan Das", father_name="Hari Das"),
            headers=self._csrf_headers(),
        )
        death_id = created.get_json()["case"]["death_id"]
        # Startable: the registrant's own reply and detail carry the prefill.
        self.assertIn("prefill", created.get_json()["case"])
        self.assertEqual(self.client.get(f"/api/v1/intake/cases/{death_id}").get_json()["case"]["prefill"]["answers"]["Id10061"], "Hari Das")

        other = self._get_or_make_user("api.prefill.other@test.local", "IntakeApi123")
        db.session.add(VaUserAccessGrants(
            user_id=other.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID, notes="prefill rule interviewer", grant_status=VaStatuses.active,
        ))
        db.session.flush()
        self._login(str(other.user_id))
        detail = self.client.get(f"/api/v1/intake/cases/{death_id}").get_json()["case"]
        self.assertIn("prefill", detail)  # open case, no draft: any interviewer in scope may start it

        # Another interviewer's draft does not withhold it: both are prefilled, and the
        # other gets the warning (a flag and a time, never who).
        self._login(self.interviewer_id)
        draft = self._start_draft(death_id=death_id)
        mine = self.client.get(f"/api/v1/intake/cases/{death_id}").get_json()["case"]
        self.assertEqual(mine["my_draft_id"], draft["draft_id"])
        self.assertIn("prefill", mine)
        self._login(str(other.user_id))
        response = self.client.get(f"/api/v1/intake/cases/{death_id}")
        self.assertEqual(response.status_code, 200)
        held = response.get_json()["case"]
        self.assertEqual(held["unique_id"], mine["unique_id"])
        self.assertEqual(held["prefill"]["answers"]["Id10061"], "Hari Das")
        self.assertIs(held["other_draft_active"], True)
        self.assertIsNotNone(held["other_draft_started_at"])
        self.assertIsNone(held["my_draft_id"])
        self.assertNotIn(self.interviewer_id, json.dumps(held))
        self._login(self.interviewer_id)
        self.assertIs(self.client.get(f"/api/v1/intake/cases/{death_id}").get_json()["case"]["other_draft_active"], False)

        # A closed case: absent even for its registrant.
        self._login(self.interviewer_id)
        closed_id = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(father_name="Ram Das"), headers=self._csrf_headers(),
        ).get_json()["case"]["death_id"]
        db.session.get(VaDeathRegister, closed_id).status = "submitted"
        db.session.flush()
        closed = self.client.get(f"/api/v1/intake/cases/{closed_id}").get_json()["case"]
        self.assertEqual(closed["state"], "submitted")
        self.assertNotIn("prefill", closed)

    # ── happy path ─────────────────────────────────────────────────────────

    def test_register_list_start_save_and_submit(self):
        self._login(self.interviewer_id)

        response = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(), headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        death = response.get_json()["case"]
        self.assertTrue(death["unique_id"].startswith(f"{self.SITE_ID}-"))
        self.assertEqual(death["state"], "registered")

        listed = self.client.get(
            f"/api/v1/intake/deaths?project_id={self.PROJECT_ID}&site_id={self.SITE_ID}"
        ).get_json()["deaths"]
        self.assertIn(death["death_id"], [d["death_id"] for d in listed])

        draft = self._start_draft(death_id=death["death_id"])
        self.assertEqual(draft["death_id"], death["death_id"])
        self.assertEqual(draft["unique_id"], death["unique_id"])

        saved = self.client.patch(
            f"/api/v1/intake/drafts/{draft['draft_id']}",
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

        fetched = self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}").get_json()
        self.assertEqual(fetched["envelope"]["currentSection"], "background")
        self.assertEqual(fetched["envelope"]["data"]["Id10013"], "yes")

        submitted = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/submit",
            json={
                "completion": {
                    "valid": True,
                    "issues": [],
                    "data": {
                        "Id10013": "yes",
                        "Id10017": "Bina",
                        "Id10018": "Sahu",
                        "Id10019": "female",
                        # The calculated date of death (Id10023_a / _b).
                        "Id10023": (date.today() - timedelta(days=5)).isoformat(),
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
        self.assertIs(submitted.get_json()["superseded"], False)
        self.assertEqual(
            db.session.get(VaDeathRegister, death["death_id"]).status, "submitted"
        )
        # A submission whose answers don't disagree with the server's own
        # relevant/constraint re-derivation carries no validation_err entries.
        self.assertEqual(submitted.get_json()["validation_err"], [])

    def test_submit_returns_a_constraint_disagreement_without_refusing_the_submission(self):
        """beads digitva-cal.2: the server re-derives constraint itself and
        records a disagreement, but a client "valid: true" is still accepted
        -- see docs/policy/xform-expression-evaluator.md and the owner's
        accept-and-record decision on that bead."""
        self._login(self.interviewer_id)
        draft = self._start_draft()

        submitted = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/submit",
            json={
                "completion": {
                    "valid": True,
                    "issues": [],
                    "data": {
                        "Id10013": "yes",
                        "Id10017": "Bina",
                        "Id10018": "Sahu",
                        "Id10019": "female",
                        # The calculated date of death (Id10023_a / _b).
                        "Id10023": (date.today() - timedelta(days=5)).isoformat(),
                        "finalAgeInYears": "71",
                        "narr_language": "english",
                        # Id10021 (date of birth) is relevant once Id10020 is
                        # "yes", and its constraint is ". <= today()" -- a
                        # future date fails it even though the client claims
                        # the whole questionnaire is valid.
                        "Id10020": "yes",
                        "Id10021": "2099-01-01",
                    },
                }
            },
            headers=self._csrf_headers(),
        )
        self.assertEqual(submitted.status_code, 201, submitted.get_json())
        body = submitted.get_json()
        self.assertIn(
            {"question": "Id10021", "rule": "constraint"}, body["validation_err"]
        )
        # No answer value anywhere in the response -- these entries are
        # PII-free by design.
        self.assertNotIn("2099-01-01", submitted.get_data(as_text=True))

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

    def test_form_page_header_shows_names_with_codes_in_a_tooltip(self):
        """digitva-wdj: "Case id X · {project_id} / {site_id}" was meaningless
        to an interviewer; the header now shows the project/site names, and
        the codes move to a title tooltip instead of disappearing."""
        self._login(self.interviewer_id)
        draft = self._start_draft()
        body = self.client.get(f"/intake/form/{draft['draft_id']}").get_data(as_text=True)

        self.assertIn(f'title="{self.PROJECT_ID} / {self.SITE_ID}"', body)
        self.assertIn("Intake Api Project / Intake Api Site", body)

    def test_form_page_header_shows_org_unit_name_and_level_for_tree_projects(self):
        org.seed_default_organization(self.PROJECT_ID)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT_ID)}
        district = org.create_unit(
            self.PROJECT_ID,
            org_level_id=levels["district"].org_level_id,
            unit_code="HDR01",
            unit_name="Header District",
        )
        self._login(self.interviewer_id)
        draft = self._start_draft(org_unit_id=str(district.org_unit_id))
        body = self.client.get(f"/intake/form/{draft['draft_id']}").get_data(as_text=True)

        self.assertIn(f"{levels['district'].level_name} Header District", body)

    def test_form_page_pinned_summary_markup_and_prefill_seed_are_present(self):
        """The pinned deceased summary (name, date of death, age, sex) is
        seeded from the death-register prefill on load and kept live from
        draftStore.save() -- see docs/policy/web-intake.md."""
        self._login(self.interviewer_id)
        death = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(deceased_name="Bina Sahu"),
            headers=self._csrf_headers(),
        ).get_json()["case"]
        draft = self._start_draft(death_id=death["death_id"])
        body = self.client.get(f"/intake/form/{draft['draft_id']}").get_data(as_text=True)

        self.assertIn('id="wv-summary-bar"', body)
        self.assertIn('id="wv-sum-name"', body)
        self.assertIn('id="wv-sum-dod"', body)
        self.assertIn('id="wv-sum-age"', body)
        self.assertIn('id="wv-sum-sex"', body)
        # The seed reads PREFILL.deceased, embedded by the route from the
        # draft's own prefill (death-register derived).
        self.assertIn("Bina", body)
        self.assertIn("givenNames", body)
        # Updated live on every host draftStore.save() call, not on a timer
        # or a re-render.
        self.assertIn("updateSummary(summaryFromAnswers(draft.data));", body)
        self.assertIn('"digitva.intake.locale"', body)
        # Translations are fetched per locale from the serving endpoint and
        # applied client-side to a copy of the pre-built instrument (WP6).
        self.assertIn("/api/v1/instruments/", body)
        self.assertIn("applyTranslations(baseInstrument, translations, locale)", body)
        self.assertIn("js/intake/translations.js", body)
        # English beside the translation (digitva-mxn): a remembered toggle
        # in the locale bar, forced on for a locale under review.
        self.assertIn('"digitva.intake.showEnglish"', body)
        self.assertIn('label.textContent = "Show English";', body)
        self.assertIn('el.toggleAttribute("show-english"', body)
        self.assertIn("entry.under_review", body)
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
            "/api/v1/intake/deaths",
            json=self._death_payload(deceased_sex="other"),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 422)

        response = self.client.post(
            "/api/v1/intake/deaths",
            json=self._death_payload(project_id=self.BASE_PROJECT_ID, site_id=self.BASE_SITE_ID),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)

        self.assertEqual(
            self.client.get("/api/v1/intake/drafts/not-a-uuid").status_code, 404
        )
        self.assertEqual(
            self.client.get("/api/v1/intake/deaths").status_code, 400
        )

        draft = self._start_draft()
        response = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/submit",
            json={"completion": {"valid": False, "data": {"Id10013": "yes"}}},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 422)

    def test_an_incomplete_interview_is_stored_and_the_case_waits(self):
        """Decision 8: an invalid form with an incomplete interview_outcome and
        the minimum identity is accepted; the case goes to not_reachable."""
        self._login(self.interviewer_id)
        draft = self._start_draft()
        response = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/submit",
            json={"completion": {"valid": False, "data": {
                "Id10013": "yes",
                "Id10017": "Bina",
                "Id10018": "Sahu",
                "Id10019": "female",
                "Id10023": (date.today() - timedelta(days=5)).isoformat(),
                "interview_outcome": "respondent_unavailable",
            }}},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertIsNotNone(db.session.get(VaSubmissions, response.get_json()["va_sid"]))
        case = db.session.get(VaDeathRegister, draft["death_id"])
        self.assertEqual(case.status, "not_reachable")
        self.assertIsNone(case.va_sid)

    def test_a_rejected_registration_leaves_nothing_behind(self):
        self._login(self.interviewer_id)
        before = db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister))
        response = self.client.post(
            "/api/v1/intake/deaths",
            json=self._death_payload(date_of_death=(date.today() + timedelta(days=1)).isoformat()),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), before
        )

    # ── partial birth date and locked prefill (digitva-tld2, p6fs.9) ───────

    def test_register_api_accepts_and_returns_a_partial_birth_date(self):
        self._login(self.interviewer_id)
        response = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(date_of_birth_partial="1953"),
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["case"]["deceased"]["date_of_birth_partial"], "1953")
        both = self.client.post(
            "/api/v1/intake/deaths",
            json=self._death_payload(date_of_birth_partial="1953-02", date_of_birth="1953-02-11"),
            headers=self._csrf_headers(),
        )
        self.assertEqual(both.status_code, 422)

        draft = self._start_draft(death_id=response.get_json()["case"]["death_id"])
        prefill = self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}").get_json()["prefill"]
        self.assertEqual(
            (prefill["answers"]["Id10020"], prefill["answers"]["dob_precision"], prefill["answers"]["dob_year"]),
            ("no", "year", "1953-01-01"),
        )

    _TAMPERED = {
        "Id10010": "Someone Else", "Id10010b": "male",
        "Id10010c": "00000000-0000-0000-0000-000000000000", "Id10002": "veryl",
        "abha_number": "99999999999999",
    }

    def _locked_draft(self):
        """A draft locking the interviewer, an HIV area preset and ABHA;
        returns (draft json, authoritative locked values)."""
        self.interviewer.name = "Field Worker"
        self.interviewer.sex = "female"
        self.interviewer.year_of_birth = date.today().year - 45
        org.seed_default_organization(self.PROJECT_ID)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT_ID)}
        district = org.create_unit(
            self.PROJECT_ID, org_level_id=levels["district"].org_level_id,
            unit_code="LCK01", unit_name="Locked District",
        )
        org.set_unit_va_presets(self.PROJECT_ID, district.org_unit_id, hiv_mortality="high", malaria_mortality=None)
        self._login(self.interviewer_id)
        death = self.client.post(
            "/api/v1/intake/deaths",
            json=self._death_payload(org_unit_id=str(district.org_unit_id), abha_number="12345678901234"),
            headers=self._csrf_headers(),
        ).get_json()["case"]
        draft = self._start_draft(death_id=death["death_id"])
        return draft, {
            "Id10010": "Field Worker", "Id10010b": "female",
            "Id10010c": self.interviewer_id, "Id10002": "high", "abha_number": "12345678901234",
        }

    def _save(self, draft, sections):
        response = self.client.patch(
            f"/api/v1/intake/drafts/{draft['draft_id']}", json={"sections": sections}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}").get_json()["envelope"]["data"]

    def _submit(self, draft, data):
        answers = {
            "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
            "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
            "narr_language": "english", **data,
        }
        response = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/submit",
            json={"completion": {"valid": True, "issues": [], "data": answers}}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return db.session.scalar(sa.select(VaSubmissionPayloadVersion.payload_data).where(
            VaSubmissionPayloadVersion.va_sid == response.get_json()["va_sid"]))

    def test_draft_save_and_submit_overwrite_tampered_locked_answers(self):
        draft, authoritative = self._locked_draft()
        saved = self._save(draft, {"interviewer": dict(self._TAMPERED), "background": {"Id10007": "Ramesh"}})
        for name, value in authoritative.items():
            with self.subTest(step="save", name=name):
                self.assertEqual(saved[name], value)
        self.assertEqual(saved["Id10007"], "Ramesh")

        # Dropping a locked answer keeps it; clearing an unlocked one works.
        saved = self._save(draft, {"interviewer": {}, "background": {}})
        self.assertEqual({k: saved.get(k) for k in authoritative}, authoritative)
        self.assertNotIn("Id10007", saved)

        payload = self._submit(draft, dict(self._TAMPERED))
        for name, value in authoritative.items():
            with self.subTest(step="submit", name=name):
                self.assertEqual(payload[name], value)

    def test_browser_save_cannot_set_device_interview_times(self):
        draft, _authoritative = self._locked_draft()
        forged = "2099-01-01T00:00:00+00:00"
        response = self.client.patch(
            f"/api/v1/intake/drafts/{draft['draft_id']}",
            json={"sections": {}, "meta": {"startedAt": forged, "completedAt": forged, "updatedAt": forged}},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        meta = db.session.get(VaWebIntakeDraft, draft["draft_id"]).meta
        self.assertEqual(meta.get("updatedAt"), forged)  # the keep-list still applies
        self.assertNotIn("startedAt", meta)
        self.assertNotIn("completedAt", meta)

    def test_untampered_save_and_submit_are_unaffected(self):
        draft, authoritative = self._locked_draft()
        saved = self._save(draft, {"interviewer": {**authoritative, "Id10007": "Ramesh"}})
        self.assertEqual(saved, {**authoritative, "Id10007": "Ramesh"})
        payload = self._submit(draft, {**authoritative, "Id10007": "Ramesh"})
        self.assertEqual({k: payload[k] for k in authoritative}, authoritative)
        self.assertEqual(payload["Id10007"], "Ramesh")

    def test_discard_frees_the_death_for_a_new_draft(self):
        self._login(self.interviewer_id)
        death = self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(), headers=self._csrf_headers()
        ).get_json()["case"]
        draft = self._start_draft(death_id=death["death_id"])

        response = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/discard", headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["draft"]["status"], "discarded")
        self.assertEqual(db.session.get(VaDeathRegister, death["death_id"]).status, "registered")

        again = self._start_draft(death_id=death["death_id"])
        self.assertNotEqual(again["draft_id"], draft["draft_id"])

    # ── phone in-progress sync (digitva-xz83 part B) ───────────────────────

    def _case(self):
        self._login(self.interviewer_id)
        return self.client.post(
            "/api/v1/intake/deaths", json=self._death_payload(), headers=self._csrf_headers(),
        ).get_json()["case"]["death_id"]

    def _sync(self, case_id, answers, *, cid, saved_ago=0, clock_behind=0, base=None, **over):
        """A phone sync: the save is *saved_ago* seconds old on a device clock
        *clock_behind* seconds behind the server."""
        now = datetime.now(UTC)
        clock = now - timedelta(seconds=clock_behind)
        body = {
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_id": case_id,
            "client_draft_id": str(cid), "draft": {"startedAt": clock.isoformat(), "currentSection": "consented"},
            "answers_json": json.dumps(answers, separators=(",", ":")),
            "savedAt": (clock - timedelta(seconds=saved_ago)).isoformat(), "deviceClockAt": clock.isoformat(),
            "base_updated_at": base,
        }
        body.update(over)
        if "answers_sha256" not in body:
            body["answers_sha256"] = hashlib.sha256(body["answers_json"].encode()).hexdigest()
        return self.client.post("/api/v1/intake/drafts/sync", json=body, headers=self._csrf_headers())

    def _browser_save(self, draft_id, sections, **extra):
        return self.client.patch(
            f"/api/v1/intake/drafts/{draft_id}", json={"sections": sections, **extra}, headers=self._csrf_headers())

    def _rows(self, death_id, status=None):
        stmt = sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == uuid.UUID(str(death_id)), VaWebIntakeDraft.user_id == self.interviewer.user_id)
        if status:
            stmt = stmt.where(VaWebIntakeDraft.status == status)
        return db.session.scalars(stmt).all()

    def _answers(self, draft):
        db.session.refresh(draft)
        return {k: v for sec in draft.sections for k, v in sec.data.items()}

    def test_sync_creates_the_draft_from_a_phone_and_a_resend_is_a_no_op(self):
        death_id, cid = self._case(), uuid.uuid4()
        first = self._sync(death_id, {"Id10013": "yes", "Id10019": "female"}, cid=cid)
        self.assertEqual(first.status_code, 200, first.get_json())
        body = first.get_json()
        self.assertEqual((body["kept"], body["conflict"], body["message"]), ("incoming", False, None))
        self.assertNotIn("envelope", body)
        (draft,) = self._rows(death_id)
        self.assertEqual((draft.status, draft.client_draft_id), ("draft", None))  # never matches find_device_upload
        self.assertEqual(body["answers_sha256"], draft.answers_sha256)
        self.assertEqual(self._answers(draft), {"Id10013": "yes", "Id10019": "female"})
        self.assertEqual(db.session.get(VaDeathRegister, death_id).status, "in_progress")
        self.assertEqual(body["draft"]["updated_at"], draft.updated_at.isoformat())

        again = self._sync(death_id, {"Id10013": "yes", "Id10019": "female"}, cid=cid)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["draft"], body["draft"])
        self.assertEqual(len(self._rows(death_id)), 1)

    def test_the_definition_slice_identity_persists_through_sync_and_is_echoed(self):
        death_id = self._case()
        sha = "ab" * 32
        identity = {"instrumentVersion": "2026100501-aaaaaaaaaa", "definitionSha256": sha,
                    "definitionExtensions": ["abha", "medical_records"]}
        envelope = {"startedAt": datetime.now(UTC).isoformat(), "currentSection": "consented", **identity}
        response = self._sync(death_id, {"Id10013": "yes"}, cid=uuid.uuid4(), draft=envelope)
        self.assertEqual(response.status_code, 200, response.get_json())
        (draft,) = self._rows(death_id)
        self.assertEqual({k: draft.meta[k] for k in identity}, identity)
        got = self.client.get(f"/api/v1/intake/drafts/{draft.draft_id}").get_json()["envelope"]
        self.assertEqual({k: got[k] for k in identity}, identity)
        # A browser save may carry it too, and a draft without it echoes none.
        later = {"definitionSha256": "cd" * 32, "definitionExtensions": []}
        self.assertEqual(self._browser_save(draft.draft_id, {}, meta=later).status_code, 200)
        got = self.client.get(f"/api/v1/intake/drafts/{draft.draft_id}").get_json()["envelope"]
        self.assertEqual((got["definitionSha256"], got["definitionExtensions"]), ("cd" * 32, []))
        plain = self._start_draft(death_id=self._case())
        self.assertNotIn(
            "definitionSha256", self.client.get(f"/api/v1/intake/drafts/{plain['draft_id']}").get_json()["envelope"])

    def test_a_malformed_definition_slice_identity_is_refused_and_stores_nothing(self):
        death_id = self._case()
        for bad in (
            {"definitionSha256": "XYZ"}, {"definitionSha256": 5}, {"definitionExtensions": "abha"},
            {"definitionExtensions": ["Bad Name"]}, {"definitionExtensions": ["a"] * 17},
        ):
            response = self._sync(death_id, {"Id10013": "yes"}, cid=uuid.uuid4(),
                                  draft={"startedAt": datetime.now(UTC).isoformat(), **bad})
            self.assertEqual(response.status_code, 422, bad)
        self.assertEqual(self._rows(death_id), [])
        draft = self._start_draft(death_id=death_id)
        self.assertEqual(
            self._browser_save(draft["draft_id"], {}, meta={"definitionSha256": "nope"}).status_code, 422)

    def test_phone_newer_than_the_browser_wins_and_keeps_the_browser_version(self):
        death_id = self._case()
        draft = self._start_draft(death_id=death_id)
        self._browser_save(draft["draft_id"], {"background": {"Id10019": "male", "Id10017": "Web"}})
        response = self._sync(death_id, {"Id10019": "female"}, cid=uuid.uuid4())
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        self.assertEqual((body["kept"], body["conflict"]), ("incoming", True))
        self.assertIn("also edited on another device", body["message"])
        live = db.session.get(VaWebIntakeDraft, uuid.UUID(draft["draft_id"]))
        self.assertEqual(self._answers(live), {"Id10019": "female"})
        (old,) = self._rows(death_id, "replaced")
        self.assertEqual((old.meta["source"], old.meta["replacedDraftId"], old.client_draft_id),
                         ("web", draft["draft_id"], None))
        self.assertEqual(self._answers(old), {"Id10019": "male", "Id10017": "Web"})
        self.assertEqual(len(self._rows(death_id, "draft")), 1)

    def test_a_phone_that_saw_the_current_version_continues_it_without_conflict(self):
        death_id = self._case()
        draft = self._start_draft(death_id=death_id)
        saved = self._browser_save(draft["draft_id"], {"background": {"Id10019": "male"}}).get_json()["draft"]
        response = self._sync(death_id, {"Id10019": "female"}, cid=uuid.uuid4(), base=saved["updated_at"])
        body = response.get_json()
        self.assertEqual((body["kept"], body["conflict"]), ("incoming", False))
        self.assertEqual(self._rows(death_id, "replaced"), [])

    def test_browser_newer_than_the_phone_is_kept_and_the_phone_version_goes_to_history(self):
        death_id, cid = self._case(), uuid.uuid4()
        first = self._sync(death_id, {"Id10019": "female"}, cid=cid).get_json()
        self._browser_save(first["draft"]["draft_id"], {"background": {"Id10019": "male"}},
                           if_updated_at=first["draft"]["updated_at"])
        later = uuid.uuid4()
        response = self._sync(death_id, {"Id10019": "undetermined"}, cid=later, saved_ago=3600,
                              base=first["draft"]["updated_at"])
        body = response.get_json()
        self.assertEqual((body["kept"], body["conflict"]), ("server", True))
        self.assertEqual(body["envelope"]["data"]["Id10019"], "male")
        self.assertIsNone(body["answers_sha256"])  # content is the browser's now
        (old,) = self._rows(death_id, "replaced")
        self.assertEqual((old.meta["source"], old.meta["clientDraftId"]), ("device", str(later)))
        self.assertEqual(self._answers(old), {"Id10019": "undetermined"})
        # A resend of the losing sync does not pile up history.
        self._sync(death_id, {"Id10019": "undetermined"}, cid=later, saved_ago=3600, base=first["draft"]["updated_at"])
        self.assertEqual(len(self._rows(death_id, "replaced")), 1)

    def _aged_browser_draft(self, seconds):
        death_id = self._case()
        draft = self._start_draft(death_id=death_id)
        self._browser_save(draft["draft_id"], {"background": {"Id10019": "male"}})
        row = db.session.get(VaWebIntakeDraft, uuid.UUID(draft["draft_id"]))
        row.updated_at = datetime.now(UTC) - timedelta(seconds=seconds)
        db.session.commit()
        return death_id

    def test_clock_skew_is_corrected_before_the_two_versions_are_compared(self):
        # Raw, the phone's save (10 min behind, 5 s old) predates the browser's
        # save a minute ago; corrected it is 5 s old on the server's clock.
        death_id = self._aged_browser_draft(60)
        skewed = self._sync(death_id, {"Id10019": "female"}, cid=uuid.uuid4(), saved_ago=5, clock_behind=600)
        self.assertEqual(skewed.get_json()["kept"], "incoming")
        # The same save on a correct clock is genuinely older: the browser wins.
        death_id = self._aged_browser_draft(60)
        honest = self._sync(death_id, {"Id10019": "female"}, cid=uuid.uuid4(), saved_ago=605)
        self.assertEqual(honest.get_json()["kept"], "server")

    def test_a_bad_hash_or_time_is_422_and_stores_nothing(self):
        death_id = self._case()
        cid = uuid.uuid4()
        cases = [
            ({"answers_sha256": "0" * 64}, "answers_hash_invalid"),
            ({"answers_sha256": None}, "answers_hash_required"),
            ({"savedAt": "2026-10-04 10:00:00"}, "invalid_interview"),
            ({"savedAt": None}, "invalid_interview"),
            ({"deviceClockAt": None}, "invalid_interview"),
            ({"base_updated_at": "yesterday"}, "invalid_interview"),
            ({"draft": {"startedAt": "10:00"}}, "invalid_interview"),
        ]
        for over, code in cases:
            response = self._sync(death_id, {"Id10019": "female"}, cid=cid, **over)
            self.assertEqual((response.status_code, response.get_json()["code"]), (422, code), over)
        self.assertEqual(self._rows(death_id), [])
        self.assertEqual(db.session.get(VaDeathRegister, death_id).status, "registered")
        missing = self._sync(death_id, {}, cid=cid, death_id=None)
        self.assertEqual(missing.status_code, 400)

    def test_a_closed_case_refuses_the_sync(self):
        death_id = self._case()
        draft = self._start_draft(death_id=death_id)
        submitted = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/submit", headers=self._csrf_headers(),
            json={"completion": {"valid": True, "issues": [], "data": {
                "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
                "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
                "narr_language": "english"}}})
        self.assertEqual(submitted.status_code, 201, submitted.get_json())
        response = self._sync(death_id, {"Id10019": "male"}, cid=uuid.uuid4())
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "conflict"))
        self.assertEqual(len(self._rows(death_id)), 1)

    def test_a_stale_browser_save_is_409_draft_stale_and_writes_nothing(self):
        death_id = self._case()
        draft = self._start_draft(death_id=death_id)
        before = draft["updated_at"]
        self._sync(death_id, {"Id10019": "female"}, cid=uuid.uuid4())
        stale = self._browser_save(draft["draft_id"], {"background": {"Id10019": "male"}}, if_updated_at=before)
        self.assertEqual((stale.status_code, stale.get_json()["code"]), (409, "draft_stale"))
        self.assertIn("also edited on another device", stale.get_json()["error"])
        live = db.session.get(VaWebIntakeDraft, uuid.UUID(draft["draft_id"]))
        self.assertEqual(self._answers(live), {"Id10019": "female"})
        current = self.client.get(f"/api/v1/intake/drafts/{draft['draft_id']}").get_json()["draft"]["updated_at"]
        fresh = self._browser_save(draft["draft_id"], {"background": {"Id10019": "male"}}, if_updated_at=current)
        self.assertEqual(fresh.status_code, 200, fresh.get_json())
        # Without if_updated_at a save works as before.
        self.assertEqual(self._browser_save(draft["draft_id"], {"background": {"Id10019": "male"}}).status_code, 200)
        self.assertEqual(self._browser_save(draft["draft_id"], {}, if_updated_at="garbage").status_code, 400)

    def test_a_stale_tab_cannot_submit_and_opening_the_form_does_not_date_the_draft(self):
        death_id = self._case()
        draft = self._start_draft(death_id=death_id)
        before = draft["updated_at"]
        # A locale-only save (what opening the form sends) writes no answer.
        opened = self.client.patch(
            f"/api/v1/intake/drafts/{draft['draft_id']}",
            json={"sections": {}, "meta": {"locale": "en"}, "if_updated_at": before},
            headers=self._csrf_headers(),
        )
        self.assertEqual(opened.status_code, 200, opened.get_json())
        self.assertEqual(opened.get_json()["draft"]["updated_at"], before)
        self._sync(death_id, {"Id10019": "female"}, cid=uuid.uuid4())
        stale = self.client.post(
            f"/api/v1/intake/drafts/{draft['draft_id']}/submit",
            json={"if_updated_at": before, "completion": {"valid": True, "issues": [], "data": {"Id10019": "male"}}},
            headers=self._csrf_headers(),
        )
        self.assertEqual((stale.status_code, stale.get_json()["code"]), (409, "draft_stale"))
        live = db.session.get(VaWebIntakeDraft, uuid.UUID(draft["draft_id"]))
        self.assertEqual((live.status, live.va_sid), ("draft", None))

    def test_a_browser_key_overrides_the_phones_value_with_no_section_merge(self):
        death_id = self._case()
        synced = self._sync(death_id, {"Id10019": "female", "Id10017": "Bina"}, cid=uuid.uuid4()).get_json()
        draft_id = synced["draft"]["draft_id"]
        self.assertEqual(
            self._browser_save(draft_id, {"background": {"Id10019": "male"}},
                               if_updated_at=synced["draft"]["updated_at"]).status_code, 200)
        fetched = self.client.get(f"/api/v1/intake/drafts/{draft_id}").get_json()
        self.assertEqual(fetched["envelope"]["data"], {"Id10019": "male", "Id10017": "Bina"})
        live = db.session.get(VaWebIntakeDraft, uuid.UUID(draft_id))
        self.assertIsNone(live.answers_sha256)
        device = next(sec for sec in live.sections if sec.section_name == "device")
        self.assertEqual(device.data, {"Id10017": "Bina"})

    def test_the_final_upload_after_syncs_completes_the_same_draft(self):
        death_id, cid = self._case(), uuid.uuid4()
        answers = {"Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
                   "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
                   "narr_language": "english"}
        self._sync(death_id, {"Id10013": "yes"}, cid=cid)
        self._sync(death_id, answers, cid=cid, saved_ago=1)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id == cid)), 0)
        (draft,) = self._rows(death_id)
        text = json.dumps(answers, separators=(",", ":"))
        response = self.client.post("/api/v1/intake/submissions", headers=self._csrf_headers(), json={
            "client_draft_id": str(cid), "project_id": self.PROJECT_ID, "site_id": self.SITE_ID,
            "death_id": death_id, "draft": {"startedAt": datetime.now(UTC).isoformat()},
            "completion": {"valid": True, "issues": []}, "answers_json": text,
            "answers_sha256": hashlib.sha256(text.encode()).hexdigest()})
        self.assertEqual(response.status_code, 201, response.get_json())
        rows = self._rows(death_id)
        self.assertEqual([(r.draft_id, r.status, r.client_draft_id) for r in rows], [(draft.draft_id, "submitted", cid)])


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
        self.assertEqual(self.client.get("/api/v1/intake/cases").status_code, 403)

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
        context = _page_context(self.client)
        self.assertEqual(
            [(c["project_id"], c["site_id"]) for c in context],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        started = self.client.post(
            "/api/v1/intake/drafts",
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
        context = _page_context(self.client)
        self.assertEqual(
            [(c["project_id"], c["site_id"]) for c in context],
            [(self.PROJECT_ID, self.SITE_ID)],
        )
        self.assertEqual(
            [u["unit_code"] for u in context[0]["org_units"]], ["WBP01"]
        )

    def test_the_role_gate_stays_shut_without_any_interviewer_grant(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get("/api/v1/intake/cases").status_code, 403)
