"""The death_reporter role (digitva-t6q): registers deaths without interviewing.

Policy: docs/policy/web-intake.md, "Death reporters". Tree RPD01 (site RP01):
DST > CH1 > PH1 > SCA, SCB and CH1 > PH2 > SCC, with the default level x
cadre grid (ANM may report deaths at a sub-centre, CHO may not). Every
"absent" assertion first asserts that an in-scope sibling is present.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import org_grant_service
from app.services import organization_service as org
from app.services import web_intake_service as intake_svc
from app.services.authz import invalidate
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase

R = VaAccessRoles
PROJECT, SITE = "RPD01", "RP01"
API = "/api/v1/intake"
ACCESS = "/api/v1/me/access"


class DeathReporterTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=PROJECT, project_code=PROJECT, project_name=PROJECT, project_nickname=PROJECT,
            project_status=VaStatuses.active, project_registered_at=now, project_updated_at=now,
            web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=SITE, site_name=SITE, site_abbr=SITE, site_status=VaStatuses.active,
            site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=PROJECT, site_id=SITE, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(PROJECT, SITE)
        db.session.add(VaForms(
            form_id=f"{PROJECT}{SITE}01", project_id=PROJECT, site_id=SITE, odk_form_id="ODK_RPD",
            odk_project_id="7", form_type="WHO VA 2022", form_source="odk", form_status=VaStatuses.active,
            form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()

        org.seed_default_organization(PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(PROJECT)}

        def unit(code, level, parent=None):
            return org.create_unit(
                PROJECT, org_level_id=levels[level].org_level_id,
                parent_org_unit_id=parent.org_unit_id if parent else None, unit_code=code, unit_name=code,
            )

        dst = unit("DST", "district")
        ch1 = unit("CH1", "chc", dst)
        cls.ph1, cls.ph2 = unit("PH1", "phc", ch1), unit("PH2", "phc", ch1)
        cls.sca, cls.scb = unit("SCA", "subcentre", cls.ph1), unit("SCB", "subcentre", cls.ph1)
        cls.scc = unit("SCC", "subcentre", cls.ph2)
        cls.levels = levels
        cls.cadres = {c.cadre_code: c for c in org.list_cadres(PROJECT)}

        # Registers (and, for the completion test, interviews) anywhere: a project grant.
        cls.interviewer = cls._user("interviewer", (R.interviewer, None))
        cls.reporter = cls._user("reporter", (R.death_reporter, cls.sca))
        cls.reporter_ph1 = cls._user("reporter.ph1", (R.death_reporter, cls.ph1))
        # Reports at SCA, interviews at SCB only.
        cls.both = cls._user("both", (R.death_reporter, cls.sca), (R.interviewer, cls.scb))
        db.session.commit()

    @classmethod
    def _user(cls, key, *grants):
        user = cls._get_or_make_user(f"rpd.{key}@test.local", "Reporter123")
        for role, unit in grants:
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, grant_status=VaStatuses.active,
                scope_type=VaAccessScopeTypes.org_unit if unit else VaAccessScopeTypes.project,
                org_unit_id=unit.org_unit_id if unit else None,
                project_id=None if unit else PROJECT,
            ))
        return user

    # -- helpers ----------------------------------------------------------------

    def _payload(self, unit, **overrides):
        body = {
            "project_id": PROJECT, "site_id": SITE, "org_unit_id": str(unit.org_unit_id),
            "deceased_name": "Reporter Case", "deceased_sex": "female", "age_years": 70,
            "date_of_death": (date.today() - timedelta(days=4)).isoformat(),
        }
        body.update(overrides)
        return body

    def _register(self, user, unit, **overrides):
        self._login(str(user.user_id))
        response = self.client.post(API + "/deaths", json=self._payload(unit, **overrides),
                                    headers=self._csrf_headers())
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["case"]

    def _patch(self, user, death_id, body):
        self._login(str(user.user_id))
        return self.client.patch(f"{API}/deaths/{death_id}", json=body, headers=self._csrf_headers())

    def _list(self, user, query=""):
        self._login(str(user.user_id))
        return self.client.get(f"{API}/deaths{query}")

    def _complete_interview(self, death_id):
        death = db.session.get(VaDeathRegister, uuid.UUID(death_id))
        draft = intake_svc.start_draft(
            self.interviewer, project_id=PROJECT, site_id=SITE, death_id=death.death_id)
        intake_svc.submit_draft(draft, self.interviewer, completion={"valid": True, "issues": [], "data": {
            "Id10013": "yes", "Id10017": "Reporter", "Id10018": "Case", "Id10019": "female",
            "Id10023": (date.today() - timedelta(days=4)).isoformat(), "finalAgeInYears": "70",
            "narr_language": "english",
        }})
        db.session.commit()
        db.session.refresh(death)
        self.assertEqual(death.status, "submitted")

    # -- the grant-time cadre gate ------------------------------------------------

    def test_a_death_reporter_grant_needs_a_cadre_with_the_report_deaths_flag(self):
        validate = org_grant_service.validate_org_unit_grant
        # Allowed: the ANM has the flag at a sub-centre.
        unit, cadre = validate(role=R.death_reporter, org_unit_id=self.sca.org_unit_id,
                               cadre_id=self.cadres["ANM"].cadre_id)
        self.assertEqual((unit.unit_code, cadre.cadre_code), ("SCA", "ANM"))
        # Refused: no cadre, and a cadre without the flag (the CHO interviews).
        for cadre_id, message in ((None, "requires a cadre"), (self.cadres["CHO"].cadre_id, "may not report deaths")):
            with self.assertRaises(org.OrganizationError) as ctx:
                validate(role=R.death_reporter, org_unit_id=self.sca.org_unit_id, cadre_id=cadre_id)
            self.assertIn(message, str(ctx.exception))
        # The flag is the whole gate: turning it on admits the CHO.
        org.upsert_level_cadre(
            PROJECT, org_level_id=self.levels["subcentre"].org_level_id, cadre_id=self.cadres["CHO"].cadre_id,
            can_fill_va_form=True, can_code_va_form=False, can_report_deaths=True)
        validate(role=R.death_reporter, org_unit_id=self.sca.org_unit_id, cadre_id=self.cadres["CHO"].cadre_id)

    def test_the_role_is_unit_scope_only(self):
        self.assertIn(R.death_reporter, org_grant_service.ROLES_ALLOWING_ORG_UNIT)
        self._login(str(self.base_admin_user.user_id))
        body = {"user_id": str(self.reporter.user_id), "role": "death_reporter",
                "scope_type": "project", "project_id": PROJECT}
        response = self.client.post("/admin/api/access-grants", json=body, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("cannot use project scope", response.get_json()["error"])

    # -- registering --------------------------------------------------------------

    def test_a_reporter_registers_a_death_in_its_unit_and_gets_no_interview_links(self):
        case = self._register(self.reporter, self.sca, informant_name="Mohan", father_name="Hari")
        death = db.session.get(VaDeathRegister, uuid.UUID(case["death_id"]))
        self.assertEqual((death.registered_by, death.status, death.source), (self.reporter.user_id, "registered", "register"))
        self.assertTrue(case["registered_by_me"])
        # Nothing about other interviewers' drafts; the state stays.
        self.assertNotIn("other_draft_active", case)
        self.assertNotIn("other_draft_started_at", case)
        self.assertEqual(case["state"], "registered")
        # Update is the only link; no prefill (the interview's input) and no interview, attempts or visit.
        self.assertEqual(case["links"], {"update": f"{API}/deaths/{case['death_id']}"})
        self.assertNotIn("prefill", case)
        # The same registration by an interviewer is unchanged: prefill and the interview links.
        interviewed = self._register(self.interviewer, self.sca, informant_name="Mohan")
        self.assertIn("prefill", interviewed)
        self.assertIn("start_interview", interviewed["links"])

    def test_registration_is_held_to_the_reporters_reach_and_the_projects_mode(self):
        self._login(str(self.reporter.user_id))
        for unit in (self.scb, self.scc):  # a sibling and another branch
            response = self.client.post(API + "/deaths", json=self._payload(unit), headers=self._csrf_headers())
            self.assertEqual(response.status_code, 403, (unit.unit_code, response.get_json()))
        # A grant at PH1 reaches both sub-centres below it, SCC it does not.
        self._register(self.reporter_ph1, self.scb)
        self._login(str(self.reporter_ph1.user_id))
        response = self.client.post(API + "/deaths", json=self._payload(self.scc), headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)
        # Direct mode keeps no death register: nobody registers.
        project = db.session.get(VaProjectMaster, PROJECT)
        project.web_intake_mode = "direct"
        db.session.commit()
        response = self.client.post(API + "/deaths", json=self._payload(self.sca), headers=self._csrf_headers())
        self.assertEqual(response.status_code, 403)

    def test_a_resent_registration_with_the_same_client_id_returns_the_same_case(self):
        client_id = str(uuid.uuid4())
        first = self._register(self.reporter, self.sca, client_death_id=client_id)
        response = self.client.post(
            API + "/deaths", json=self._payload(self.sca, client_death_id=client_id), headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["death_id"], first["death_id"])

    # -- no interviewing, no worklist ------------------------------------------------

    def test_the_new_death_page_offers_the_questionnaire_start_only_to_an_interviewer(self):
        start = 'id="death-save-start"'
        self._login(str(self.interviewer.user_id))
        self.assertIn(start, self.client.get("/intake/deaths/new").get_data(as_text=True))
        self._login(str(self.reporter.user_id))
        page = self.client.get("/intake/deaths/new").get_data(as_text=True)
        self.assertNotIn(start, page)
        self.assertIn('id="death-save"', page)

    def test_a_reporter_cannot_interview_log_visits_or_open_a_case(self):
        case = self._register(self.reporter, self.sca)
        death_id = case["death_id"]
        self._login(str(self.reporter.user_id))
        headers = self._csrf_headers()
        calls = (
            ("get", f"/cases/{death_id}", None),
            ("get", f"/cases/{death_id}/possible-duplicates", None),
            ("post", f"/cases/{death_id}/attempts", {"outcome": "no_answer"}),
            ("post", f"/cases/{death_id}/visit", {"next_visit_at": None}),
            ("post", f"/cases/{death_id}/pause", {"reason": "other"}),
            ("post", f"/cases/{death_id}/flags", {"kind": "cancel", "reason": "x"}),
            ("get", "/drafts", None),
            ("post", "/drafts", {"project_id": PROJECT, "site_id": SITE, "death_id": death_id}),
            ("post", "/drafts/sync", {"project_id": PROJECT}),
            ("post", "/submissions", {"project_id": PROJECT}),
            ("post", "/outstanding", {}),
            ("get", f"/projects/{PROJECT}/prefill-policy", None),
            ("get", "/supervision/cases", None),
        )
        for method, path, body in calls:
            response = getattr(self.client, method)(API + path, **({"json": body, "headers": headers} if body is not None or method == "post" else {}))
            self.assertEqual(response.status_code, 403, (method, path, response.get_json()))
        # Nothing was written by the refused calls.
        death = db.session.get(VaDeathRegister, uuid.UUID(death_id))
        db.session.refresh(death)
        self.assertEqual((death.status, death.next_visit_at, death.pending_flag), ("registered", None, None))

    def test_holding_both_roles_does_not_lend_one_role_the_others_cases(self):
        # BOTH reports at SCA and interviews at SCB only.
        case = self._register(self.both, self.sca)
        death_id = uuid.UUID(case["death_id"])
        with self.assertRaises(intake_svc.WebIntakeError) as ctx:
            intake_svc.get_death(self.both, death_id)  # interviewer reach: SCB only
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self._patch(self.both, death_id, {"remarks": "ok"}).status_code, 200)
        # The interviewer routes still refuse the case it reaches only as a reporter.
        self._login(str(self.both.user_id))
        self.assertEqual(self.client.get(f"{API}/cases/{death_id}").status_code, 404)
        headers = self._csrf_headers()
        response = self.client.post(f"{API}/cases/{death_id}/visit", json={"next_visit_at": None}, headers=headers)
        self.assertEqual(response.status_code, 404)

    # -- the reporter's list ----------------------------------------------------------

    def test_the_list_holds_only_the_deaths_the_reporter_registered_within_reach(self):
        mine = [self._register(self.reporter, self.sca, deceased_name=f"Mine {n}")["death_id"] for n in range(3)]
        # Present siblings: an interviewer's death in the same unit, and a colleague's.
        self._register(self.interviewer, self.sca, deceased_name="Interviewer's")
        theirs = self._register(self.reporter_ph1, self.sca, deceased_name="Colleague's")["death_id"]
        other_unit = self._register(self.reporter_ph1, self.scb, deceased_name="Elsewhere")["death_id"]

        response = self._list(self.reporter)
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        ids = [d["death_id"] for d in body["deaths"]]
        self.assertEqual(sorted(ids), sorted(mine))
        self.assertIsNone(body["next_cursor"])
        self.assertTrue(all(d["va_sid"] is None for d in body["deaths"]))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        # The wider reporter sees its own two (one at each sub-centre), not the first reporter's.
        ids = {d["death_id"] for d in self._list(self.reporter_ph1).get_json()["deaths"]}
        self.assertEqual(ids, {theirs, other_unit})

    def test_the_list_is_paged_newest_first_and_narrows_by_project_and_site(self):
        made = [self._register(self.reporter, self.sca, deceased_name=f"Page {n}")["death_id"] for n in range(3)]
        first = self._list(self.reporter, "?limit=2").get_json()
        self.assertEqual(len(first["deaths"]), 2)
        self.assertIsNotNone(first["next_cursor"])
        second = self._list(self.reporter, f"?limit=2&cursor={first['next_cursor']}").get_json()
        self.assertIsNone(second["next_cursor"])
        paged = [d["death_id"] for d in first["deaths"] + second["deaths"]]
        self.assertEqual(sorted(paged), sorted(made))
        self.assertEqual(len(set(paged)), 3)
        self.assertEqual(paged, list(reversed(made)))  # newest first
        self.assertEqual(self._list(self.reporter, f"?project_id={PROJECT}&site_id={SITE}").status_code, 200)
        for query in ("?limit=abc", "?cursor=bad"):
            self.assertEqual(self._list(self.reporter, query).status_code, 400, query)
        self.assertEqual(self._list(self.reporter, "?project_id=NOPE01").status_code, 403)
        # The page size is clamped, not trusted.
        self.assertEqual(self._list(self.reporter, "?limit=100000").status_code, 200)

    def _cases(self, user, query=""):
        self._login(str(user.user_id))
        return self.client.get(f"{API}/cases{query}")

    def test_the_case_list_holds_a_reporters_own_deaths_within_reach_only(self):
        # The shared deaths list (docs/policy/case-list-views.md) reads /cases.
        mine = self._register(self.reporter, self.sca, deceased_name="Mine")["death_id"]
        colleague = self._register(self.reporter_ph1, self.sca, deceased_name="Colleague's")["death_id"]
        interviewer = self._register(self.interviewer, self.sca, deceased_name="Interviewer's")["death_id"]
        response = self._cases(self.reporter)
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = {row["death_id"]: row for row in response.get_json()["cases"]}
        self.assertIn(mine, rows)
        self.assertNotIn(colleague, rows)
        self.assertNotIn(interviewer, rows)
        row = rows[mine]
        self.assertTrue(row["registered_by_me"])
        self.assertFalse(row["can_interview"])
        self.assertNotIn("other_draft_active", row)
        self.assertNotIn("other_draft_started_at", row)
        self.assertEqual(response.get_json()["counts"], {"registered": 1})
        # Project narrowing takes the reporter's projects; another is refused.
        self.assertEqual(self._cases(self.reporter, f"?project_id={PROJECT}").status_code, 200)
        self.assertEqual(self._cases(self.reporter, "?project_id=NOPE01").status_code, 403)
        # A grant moved to another branch no longer reaches its own death.
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.reporter.user_id))
        grant.org_unit_id = self.scc.org_unit_id
        db.session.commit()
        invalidate(self.reporter.user_id)
        response = self._cases(self.reporter)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(mine, {row["death_id"] for row in response.get_json()["cases"]})

    def test_the_case_list_unions_both_roles_without_lending_the_interview(self):
        # BOTH reports at SCA and interviews at SCB only.
        reported = self._register(self.both, self.sca, deceased_name="Reported")["death_id"]
        sibling = self._register(self.interviewer, self.sca, deceased_name="Not theirs")["death_id"]
        in_reach = self._register(self.interviewer, self.scb, deceased_name="Interviewed")["death_id"]
        rows = {row["death_id"]: row for row in self._cases(self.both).get_json()["cases"]}
        self.assertIn(in_reach, rows)
        self.assertTrue(rows[in_reach]["can_interview"])
        self.assertIn("other_draft_active", rows[in_reach])
        self.assertIn(reported, rows)
        self.assertFalse(rows[reported]["can_interview"])
        self.assertNotIn("other_draft_active", rows[reported])
        self.assertNotIn(sibling, rows)
        # An interviewer's list is unchanged: every case in reach, interview allowed.
        rows = {row["death_id"]: row for row in self._cases(self.interviewer).get_json()["cases"]}
        self.assertTrue({reported, sibling, in_reach} <= set(rows))
        self.assertTrue(all(row["can_interview"] for row in rows.values()))

    def test_case_rows_carry_the_gps_fix_only_where_the_caller_sees_contact_details(self):
        # The card's map link (docs/current-state/api-v1.md, GET /intake/cases).
        gps = {"latitude": 12.971599, "longitude": 77.594566}
        mine = self._register(self.reporter, self.sca, deceased_name="Mine GPS", **gps)["death_id"]
        theirs = self._register(self.interviewer, self.sca, deceased_name="Theirs GPS", **gps)["death_id"]

        # An interviewer (personal-data access) gets the fix on every case in reach.
        rows = {row["death_id"]: row for row in self._cases(self.interviewer).get_json()["cases"]}
        self.assertIn(mine, rows)
        self.assertEqual((rows[mine]["latitude"], rows[mine]["longitude"]), (12.971599, 77.594566))
        self.assertEqual(rows[theirs]["latitude"], 12.971599)

        # A reporter lists, and so locates, only its own deaths.
        rows = {row["death_id"]: row for row in self._cases(self.reporter).get_json()["cases"]}
        self.assertIn(mine, rows)
        self.assertEqual(rows[mine]["longitude"], 77.594566)
        self.assertNotIn(theirs, rows)

        # A caller without personal-data access keeps the fix of its own
        # registrations only (the case detail's rule), never of the team's.
        with patch("app.services.web_intake_service.should_redact_pii", return_value=True):
            rows = {row["death_id"]: row for row in self._cases(self.interviewer).get_json()["cases"]}
        self.assertIn(mine, rows)
        self.assertNotIn("latitude", rows[mine])
        self.assertNotIn("longitude", rows[mine])
        self.assertIn(theirs, rows)
        self.assertEqual(rows[theirs]["latitude"], 12.971599)

    def test_case_rows_carry_no_gps_fix_once_the_project_has_no_organization_tree(self):
        # Owner, 2026-10-20: coordinates in rows only in organization projects.
        death = self._register(self.interviewer, self.sca, deceased_name="Treeless GPS",
                               latitude=12.5, longitude=77.5)["death_id"]
        rows = {row["death_id"]: row for row in self._cases(self.interviewer).get_json()["cases"]}
        self.assertEqual(rows[death]["latitude"], 12.5)
        active = sa.select(MasOrgLevel.org_level_id).where(
            MasOrgLevel.project_id == PROJECT, MasOrgLevel.is_active.is_(True))
        level_ids = list(db.session.scalars(active))
        self.assertTrue(level_ids)
        levels = sa.update(MasOrgLevel).where(MasOrgLevel.org_level_id.in_(level_ids))
        db.session.execute(levels.values(is_active=False))
        db.session.commit()
        try:
            rows = {row["death_id"]: row for row in self._cases(self.interviewer).get_json()["cases"]}
            self.assertIn(death, rows)
            self.assertNotIn("latitude", rows[death])
            self.assertNotIn("longitude", rows[death])
        finally:
            db.session.execute(levels.values(is_active=True))
            db.session.commit()

    def _detail_address(self, user, death_id):
        self._login(str(user.user_id))
        response = self.client.get(f"{API}/cases/{death_id}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["case"]["household_address"]

    def _register_rows(self, user):
        response = self._list(user, f"?project_id={PROJECT}&site_id={SITE}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return {d["death_id"]: d for d in response.get_json()["deaths"]}

    def test_the_case_detail_and_register_list_carry_the_gps_fix_by_the_rows_rule(self):
        # Owner, 2026-10-20: organization project, and personal-data access or
        # the caller's own registration (docs/policy/web-intake.md).
        gps = {"latitude": 12.971599, "longitude": 77.594566}
        mine = self._register(self.reporter, self.sca, deceased_name="Mine Detail GPS", **gps)["death_id"]
        theirs = self._register(self.interviewer, self.sca, deceased_name="Theirs Detail GPS", **gps)["death_id"]
        gps_keys = ("latitude", "longitude", "accuracy_m", "captured_at")

        # An interviewer with personal-data access: every case's fix.
        self.assertEqual(self._detail_address(self.interviewer, mine)["latitude"], 12.971599)
        self.assertEqual(self._register_rows(self.interviewer)[mine]["longitude"], 77.594566)
        # The reporter's own list keeps its own fix (its edit form reads it).
        reported = {d["death_id"]: d for d in self._list(self.reporter).get_json()["deaths"]}
        self.assertEqual(reported[mine]["latitude"], 12.971599)

        # Without personal-data access: only the caller's own registration.
        with patch("app.services.web_intake_service.should_redact_pii", return_value=True):
            other = self._detail_address(self.interviewer, mine)
            own = self._detail_address(self.interviewer, theirs)
            rows = self._register_rows(self.interviewer)
        self.assertIn("address", other)
        self.assertEqual(own["latitude"], 12.971599)
        self.assertEqual(rows[theirs]["latitude"], 12.971599)
        self.assertIn(mine, rows)
        for key in gps_keys:
            self.assertNotIn(key, other)
            self.assertNotIn(key, rows[mine])

        # No organization tree: no fix of another's registration, even with
        # personal-data access; the caller's own keeps its fix.
        active = sa.select(MasOrgLevel.org_level_id).where(
            MasOrgLevel.project_id == PROJECT, MasOrgLevel.is_active.is_(True))
        level_ids = list(db.session.scalars(active))
        self.assertTrue(level_ids)
        levels = sa.update(MasOrgLevel).where(MasOrgLevel.org_level_id.in_(level_ids))
        db.session.execute(levels.values(is_active=False))
        db.session.commit()
        try:
            other = self._detail_address(self.interviewer, mine)
            own = self._detail_address(self.interviewer, theirs)
            rows = self._register_rows(self.interviewer)
        finally:
            db.session.execute(levels.values(is_active=True))
            db.session.commit()
        self.assertIn("address", other)
        self.assertEqual(own["latitude"], 12.971599)
        self.assertEqual(rows[theirs]["latitude"], 12.971599)
        self.assertIn(mine, rows)
        for key in gps_keys:
            self.assertNotIn(key, other)
            self.assertNotIn(key, rows[mine])

    def test_the_supervision_list_never_carries_the_gps_fix(self):
        death = self._register(self.interviewer, self.sca, deceased_name="Supervised GPS",
                               latitude=12.5, longitude=77.5)["death_id"]
        supervisor = self._user("supervisor.gps", (R.interview_supervisor, self.ph1))
        db.session.commit()
        self._login(str(supervisor.user_id))
        response = self.client.get(f"{API}/supervision/cases")
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = {row["death_id"]: row for row in response.get_json()["cases"]}
        self.assertIn(death, rows)
        self.assertNotIn("latitude", rows[death])
        self.assertNotIn("longitude", rows[death])

    def test_an_interviewer_keeps_the_register_list_unchanged(self):
        case = self._register(self.reporter, self.sca)
        self._login(str(self.interviewer.user_id))
        self.assertEqual(self.client.get(f"{API}/deaths").status_code, 400)  # project_id and site_id required
        body = self.client.get(f"{API}/deaths?project_id={PROJECT}&site_id={SITE}").get_json()
        self.assertIn(case["death_id"], {d["death_id"] for d in body["deaths"]})
        self.assertNotIn("next_cursor", body)

    def test_the_reporters_list_query_is_index_backed(self):
        db.session.execute(sa.text("SET LOCAL enable_seqscan = off"))
        plan = "\n".join(db.session.execute(sa.text(
            "EXPLAIN SELECT * FROM va_death_register WHERE registered_by = :u "
            "ORDER BY updated_at DESC, death_id DESC LIMIT 51"), {"u": self.reporter.user_id}).scalars().all())
        self.assertIn("ix_va_death_register_registered_by", plan)
        # Rows come out of the index in order: no Sort node.
        self.assertNotIn("Sort", plan)

    # -- correcting -------------------------------------------------------------------

    def test_a_reporter_corrects_its_own_death_until_an_interview_is_completed(self):
        case = self._register(self.reporter, self.sca, remarks="first")
        death_id = case["death_id"]
        response = self._patch(self.reporter, death_id, {"remarks": "fixed", "deceased_name": "Corrected"})
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()["case"]
        self.assertEqual((body["remarks"], body["deceased"]["name"]), ("fixed", "Corrected"))
        self.assertEqual(body["links"], {"update": f"{API}/deaths/{death_id}"})
        # The existing rules apply unchanged: validation and staleness.
        bad = self._patch(self.reporter, death_id, {"deceased_sex": "robot"})
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (422, "invalid_death"))
        stale = self._patch(self.reporter, death_id, {"remarks": "y", "if_updated_at": "2020-01-01T00:00:00+00:00"})
        self.assertEqual((stale.status_code, stale.get_json()["code"]), (409, "death_stale"))

        self._complete_interview(death_id)
        refused = self._patch(self.reporter, death_id, {"remarks": "too late"})
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (409, "case_completed"))
        death = db.session.get(VaDeathRegister, uuid.UUID(death_id))
        self.assertNotEqual(death.remarks, "too late")

    def test_a_reporter_cannot_correct_a_death_it_did_not_register_or_cannot_reach(self):
        interviewers = self._register(self.interviewer, self.sca, remarks="keep")["death_id"]
        colleagues = self._register(self.reporter_ph1, self.sca, remarks="keep")["death_id"]
        # Present first: the reporter's own death in the same unit is correctable.
        own = self._register(self.reporter, self.sca)["death_id"]
        self.assertEqual(self._patch(self.reporter, own, {"remarks": "mine"}).status_code, 200)
        for death_id in (interviewers, colleagues, str(uuid.uuid4())):
            self.assertEqual(self._patch(self.reporter, death_id, {"remarks": "x"}).status_code, 404, death_id)
        for death_id in (interviewers, colleagues):
            self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(death_id)).remarks, "keep")
        # Out of reach: the grant moves to another branch, so even its own death reads as 404.
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.reporter.user_id))
        grant.org_unit_id = self.scc.org_unit_id
        db.session.commit()
        invalidate(self.reporter.user_id)
        self.assertEqual(self._patch(self.reporter, own, {"remarks": "x"}).status_code, 404)
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(own)).remarks, "mine")

    # -- /me/access -------------------------------------------------------------------

    @staticmethod
    def _project(body):
        return next(p for p in body["projects"] if p["project_id"] == PROJECT)

    def _access(self, user):
        self._login(str(user.user_id))
        return self.client.get(ACCESS).get_json()

    def test_me_access_offers_register_death_to_a_reporter_without_interview_rights(self):
        body = self._access(self.reporter)
        project = self._project(body)
        self.assertEqual(body["roles"], ["death_reporter"])
        self.assertEqual(project["actions"]["interview"], [])
        register = project["actions"]["register_death"]
        self.assertEqual([e["site_id"] for e in register], [SITE])
        self.assertEqual([u["unit_code"] for u in register[0]["org_units"]], ["SCA"])
        self.assertEqual(register[0]["web_intake_mode"], "both")
        self.assertEqual(project["sites"][0]["roles"], ["death_reporter"])
        self.assertTrue(body["account"]["device_access"])
        # Registering needs no personal-data lift: the role is outside the PII allowlist.
        self.assertFalse(body["account"]["pii_visible"])
        units = {u["unit_code"]: u for u in project["units"]}
        self.assertEqual(units["SCA"]["roles"], ["death_reporter"])
        self.assertNotIn("SCB", units)  # a sibling is neither reached nor an ancestor

    def test_me_access_register_death_follows_the_same_reach_for_an_interviewer(self):
        project = self._project(self._access(self.interviewer))
        self.assertEqual(project["actions"]["register_death"], project["actions"]["interview"])
        self.assertEqual([e["site_id"] for e in project["actions"]["register_death"]], [SITE])
        # Both roles: register_death is the union reach, interview the interviewer's alone.
        both = self._project(self._access(self.both))
        interview_units = {u["unit_code"] for e in both["actions"]["interview"] for u in e["org_units"]}
        register_units = {u["unit_code"] for e in both["actions"]["register_death"] for u in e["org_units"]}
        self.assertEqual((interview_units, register_units), ({"SCB"}, {"SCA", "SCB"}))

    def test_me_access_register_death_is_empty_when_the_project_keeps_no_death_register(self):
        project = db.session.get(VaProjectMaster, PROJECT)
        project.web_intake_mode = "direct"
        db.session.commit()
        for user in (self.reporter, self.interviewer):
            body = self._access(user)
            self.assertEqual(self._project(body)["actions"]["register_death"], [], user.email)
        # A reporter has nothing to collect with, so the app sign-in check is closed too.
        self.assertFalse(self._access(self.reporter)["account"]["device_access"])
        self.assertTrue(self._access(self.interviewer)["account"]["device_access"])

    def test_the_unit_picker_answers_a_reporters_own_reach(self):
        self._login(str(self.reporter.user_id))
        response = self.client.get(f"/api/v1/organization/{PROJECT}/units?role=death_reporter")
        self.assertEqual(response.status_code, 200, response.get_json())
        selectable = {u["unit_code"] for u in response.get_json()["units"] if u["selectable"]}
        self.assertEqual(selectable, {"SCA"})
        self._login(str(self.interviewer.user_id))
        self.assertEqual(self.client.get(f"/api/v1/organization/{PROJECT}/units?role=death_reporter").status_code, 403)

    # -- both roles ----------------------------------------------------------------

    def test_a_both_roles_user_lists_what_they_registered_as_a_reporter(self):
        # BOTH reports at SCA and interviews at SCB only.
        reported = self._register(self.both, self.sca, deceased_name="Reported")["death_id"]
        interviewed = self._register(self.both, self.scb, deceased_name="Interviewed")["death_id"]
        self._login(str(self.both.user_id))
        # Without the parameter: the interviewer list (project and site required).
        self.assertEqual(self.client.get(f"{API}/deaths").status_code, 400)
        response = self.client.get(f"{API}/deaths?registered=mine")
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()
        # The reporter's reach is SCA only, so the SCB death is not listed (present first: SCA is).
        self.assertEqual([d["death_id"] for d in body["deaths"]], [reported])
        self.assertIn("next_cursor", body)
        self.assertNotEqual(reported, interviewed)
        self.assertEqual(self.client.get(f"{API}/deaths?registered=all").status_code, 400)
        # An interviewer with no reporter grant gets no such list.
        self._login(str(self.interviewer.user_id))
        self.assertEqual(self.client.get(f"{API}/deaths?registered=mine").status_code, 400)
        # A reporter-only user keeps it as the default.
        self.assertEqual(self._list(self.reporter, "?registered=mine").status_code, 200)

    def test_a_both_roles_reply_is_reporter_shaped_only_where_they_do_not_interview(self):
        as_reporter = self._register(self.both, self.sca)
        self.assertEqual(as_reporter["links"], {"update": f"{API}/deaths/{as_reporter['death_id']}"})
        self.assertNotIn("prefill", as_reporter)
        self.assertNotIn("other_draft_active", as_reporter)
        # Where the interviewer grant reaches the case, the full interview body.
        as_interviewer = self._register(self.both, self.scb)
        self.assertIn("prefill", as_interviewer)
        self.assertIn("start_interview", as_interviewer["links"])
        self.assertIn("other_draft_active", as_interviewer)
        # The correction reply follows the same rule.
        fixed = self._patch(self.both, as_reporter["death_id"], {"remarks": "r"}).get_json()["case"]
        self.assertEqual(list(fixed["links"]), ["update"])
        fixed = self._patch(self.both, as_interviewer["death_id"], {"remarks": "i"}).get_json()["case"]
        self.assertIn("start_interview", fixed["links"])

    def test_the_register_project_refusal_names_registering_not_interviewing(self):
        self._login(str(self.reporter.user_id))
        response = self.client.post(
            API + "/deaths", json=self._payload(self.sca, project_id="NOPE01"), headers=self._csrf_headers())
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "project_forbidden"))
        self.assertIn("register deaths", response.get_json()["error"])
        self._login(str(self.interviewer.user_id))
        response = self.client.get(f"{API}/cases?project_id=NOPE01")
        self.assertEqual(response.status_code, 403)
        self.assertIn("interviewer access", response.get_json()["error"])
