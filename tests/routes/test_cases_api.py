"""The shared case list: GET /api/v1/cases and /filter-options (digitva-pt0s).

Policy: docs/policy/case-list-views.md. Tree CLP01 (site CL01): DST > CH1 >
PH1 > SCA, SCB and CH1 > PH2 > SCC; CLS01 (site SM01) is a sites-mode project.
Every "absent" assertion first asserts that an in-scope sibling is present.
"""
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa
from flask import g

from app import db, limiter
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocations,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.va_selectives import VaAllocation
from app.services import case_list_service as case_list
from app.services import case_transition_service as transitions
from app.services import organization_service as org
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase

R = VaAccessRoles
PROJECT, SITE = "CLP01", "CL01"
SITES_PROJECT, SITES_SITE = "CLS01", "SM01"
API = "/api/v1/cases"
STAFF_FIELDS = ("reporter_name", "interviewer_name", "coder_name")


@contextmanager
def _redacted():
    """The caller loses personal-data access (``should_redact_pii`` true)."""
    with mock.patch.object(case_list, "should_redact_pii", return_value=True):
        yield


def _dod(days):
    return (date.today() - timedelta(days=days)).isoformat()


class CaseListTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id, site_id, mode in ((PROJECT, SITE, "organization"), (SITES_PROJECT, SITES_SITE, "sites")):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Project {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active, project_registered_at=now,
                project_updated_at=now, web_intake_mode="both", project_structure_mode=mode,
            ))
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id, site_status=VaStatuses.active,
                site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in ((PROJECT, SITE), (SITES_PROJECT, SITES_SITE)):
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            db.session.flush()
            _ensure_legacy_project_site_rows(project_id, site_id)
            db.session.add(VaForms(
                form_id=f"{project_id}{site_id}01", project_id=project_id, site_id=site_id,
                odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
        db.session.flush()

        org.seed_default_organization(PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(PROJECT)}
        cls.cadres = {c.cadre_code: c for c in org.list_cadres(PROJECT)}

        def unit(code, level, parent=None):
            return org.create_unit(
                PROJECT, org_level_id=levels[level].org_level_id, unit_code=code, unit_name=f"Unit {code}",
                parent_org_unit_id=parent.org_unit_id if parent else None,
            )

        dst = unit("DST", "district")
        cls.ch1 = unit("CH1", "chc", dst)
        cls.ph1, cls.ph2 = unit("PH1", "phc", cls.ch1), unit("PH2", "phc", cls.ch1)
        cls.sca, cls.scb = unit("SCA", "subcentre", cls.ph1), unit("SCB", "subcentre", cls.ph1)
        cls.scc = unit("SCC", "subcentre", cls.ph2)
        org.upsert_level_cadre(
            PROJECT, org_level_id=levels["phc"].org_level_id, cadre_id=cls.cadres["MO"].cadre_id,
            can_fill_va_form=False, can_code_va_form=True, can_supervise_interviews=True,
        )

        def user(key, *grants):
            person = cls._get_or_make_user(f"cl.{key}@test.local", "CaseList123")
            for role, scope in grants:
                kind, target = scope
                row = {"scope_type": kind}
                if kind == VaAccessScopeTypes.org_unit:
                    row["org_unit_id"] = target.org_unit_id
                else:
                    row["project_id"] = target
                if role == R.interview_supervisor:
                    row["cadre_id"] = cls.cadres["MO"].cadre_id
                db.session.add(VaUserAccessGrants(
                    user_id=person.user_id, role=role, grant_status=VaStatuses.active, notes="case list", **row))
            return person

        whole = (VaAccessScopeTypes.project, PROJECT)
        at_ph1 = (VaAccessScopeTypes.org_unit, cls.ph1)
        cls.ian = user("ian", (R.interviewer, at_ph1))
        cls.rita = user("rita", (R.death_reporter, at_ph1))
        cls.sam = user("sam", (R.interview_supervisor, at_ph1))
        cls.wally = user("wally", (R.interviewer, whole))
        cls.cody = user("cody", (R.coder, whole))
        cls.dana = user("dana", (R.data_manager, whole))
        cls.pat = user("pat", (R.collaborator_pii, whole))
        cls.cole = user("cole", (R.collaborator, whole))
        cls.sue = user("sue", (R.interview_supervisor, at_ph1), (R.coder, whole))  # supervisor with PII access
        cls.pip = user("pip", (R.project_pi, whole))
        cls.vera = user("vera", (R.interviewer, at_ph1), (R.coder, whole))
        cls.ivy = user("ivy", (R.interviewer, (VaAccessScopeTypes.project, SITES_PROJECT)))
        cls.nobody = user("nobody")
        cls.admin = db.session.get(VaUsers, uuid.UUID(cls.base_admin_id))
        db.session.commit()

        def register(who, where, **fields):
            project_id, site_id = (SITES_PROJECT, SITES_SITE) if where is None else (PROJECT, SITE)
            fields = {"deceased_name": "Name", "deceased_sex": "female", "age_years": 60, "date_of_death": _dod(10)} | fields
            return intake_svc.register_death(
                who, project_id=project_id, site_id=site_id,
                org_unit_id=str(where.org_unit_id) if where else None, **fields)

        def submitted(workflow_state, registrar, where, **fields):
            case = register(registrar, where, **fields)
            sid = f"uuid:cl-{uuid.uuid4()}"
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=f"{PROJECT}{SITE}01", va_submission_date=now, va_odk_updatedat=now,
                va_data_collector="cl", va_odk_reviewstate="reviewed", va_instance_name=sid,
                va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes", va_narration_language="English",
                va_deceased_age=50, va_deceased_gender="male", va_summary=[], va_catcount={}, va_category_list=[],
            ))
            db.session.flush()
            db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state=workflow_state))
            case.va_sid = sid
            transitions.transition(case, "in_progress", actor=registrar, action="test")
            transitions.transition(case, "submitted", actor=registrar, action="test")
            return case

        cls._register, cls._submitted = staticmethod(register), staticmethod(submitted)
        fix = {"latitude": 28.61, "longitude": 77.2, "accuracy_m": 5.0, "captured_at": now}
        cls.a = register(cls.ian, cls.sca, deceased_name="Asha Alpha", age_years=62)
        cls.b = register(cls.wally, cls.scb, deceased_name="Bimal Beta", deceased_sex="male", age_years=40,
                         date_of_death=_dod(5))
        cls.c = register(cls.wally, cls.scc, deceased_name="Chitra Gamma")
        cls.d = register(cls.rita, cls.sca, deceased_name="Dev Delta")
        cls.e = submitted("ready_for_coding", cls.ian, cls.sca, deceased_name="Esha Echo", deceased_sex="male",
                          age_years=70)
        cls.f = submitted("coding_in_progress", cls.wally, cls.scb, deceased_name="Farhan Foxtrot")
        cls.g = submitted("coder_finalized", cls.ian, cls.sca, deceased_name="Gita Golf")
        cls.h = register(cls.ian, cls.sca, deceased_name="Hari Hotel")
        cls.i = register(cls.ian, cls.sca, deceased_name="Indu India")
        cls.j = register(cls.ian, cls.sca, deceased_name="Jai Juliet")
        cls.k = register(cls.ian, cls.sca, deceased_name="Kiran Kilo")
        cls.s = register(cls.ivy, None, deceased_name="Sita Sierra")
        for case in (cls.a, cls.b, cls.d, cls.e, cls.s):
            for key, value in fix.items():
                setattr(case, key, value)
        cls.h.status = "paused"
        cls.h.next_visit_at = now - timedelta(days=2)
        cls.i.status, cls.i.duplicate_of_death_id = "duplicate", cls.a.death_id
        cls.j.status = "cancelled"
        cls.k.pending_flag = "duplicate"
        db.session.add(VaAllocations(
            va_sid=cls.f.va_sid, va_allocated_to=cls.cody.user_id, va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.active))
        db.session.flush()
        # Kiran waited longest (core UPDATE: the ORM would reset updated_at).
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == cls.k.death_id)
                           .values(updated_at=now - timedelta(days=5)))
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()

    # -- helpers ---------------------------------------------------------------

    def _get(self, who, query=""):
        self._login(str(who.user_id))
        response = self.client.get(f"{API}{query}")
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()

    def _ids(self, who, query=""):
        return {c["death_id"]: c for c in self._get(who, query)["cases"]}

    def _in(self, case, ids):
        return str(case.death_id) in ids

    # -- scope per role ---------------------------------------------------------

    def test_interviewer_reaches_the_unit_subtree_not_a_sibling_phc(self):
        rows = self._ids(self.ian)
        self.assertTrue(self._in(self.a, rows))
        self.assertTrue(self._in(self.b, rows))  # registered by someone else, same subtree
        self.assertFalse(self._in(self.c, rows))  # PH2
        self.assertFalse(self._in(self.s, rows))  # another project
        self.assertNotIn("Chitra", str(rows))

    def test_death_reporter_sees_only_its_own_registrations(self):
        rows = self._ids(self.rita)
        self.assertTrue(self._in(self.d, rows))
        self.assertFalse(self._in(self.a, rows))  # same unit, registered by ian

    def test_supervisor_reaches_its_unit_subtree(self):
        rows = self._ids(self.sam)
        self.assertTrue(self._in(self.a, rows))
        self.assertFalse(self._in(self.c, rows))

    def test_coder_reaches_submitted_cases_only(self):
        rows = self._ids(self.cody)
        self.assertTrue(self._in(self.e, rows))
        self.assertTrue(self._in(self.f, rows))
        self.assertFalse(self._in(self.a, rows))  # registered, no submission yet

    def test_data_manager_reaches_the_project_not_another_one(self):
        rows = self._ids(self.dana)
        for case in (self.a, self.c, self.e):
            self.assertTrue(self._in(case, rows))
        self.assertFalse(self._in(self.s, rows))

    def test_admin_reaches_cases_with_a_submission(self):
        rows = self._ids(self.admin)
        self.assertTrue(self._in(self.e, rows))
        self.assertIn("deceased_name", rows[str(self.e.death_id)])

    def test_two_predicates_give_the_wider_fields(self):
        coder_only = self._ids(self.cody)[str(self.e.death_id)]
        both = self._ids(self.vera)[str(self.e.death_id)]  # interviewer at PH1 and coder
        self.assertNotIn("deceased_name", coder_only)
        self.assertEqual(both["deceased_name"], "Esha Echo")
        self.assertEqual(both["unit_name"], "Unit SCA")

    def test_no_grant_is_an_empty_page_not_a_refusal(self):
        body = self._get(self.nobody)
        self.assertEqual(body["cases"], [])
        self.assertEqual(body["counts"]["total"], 0)
        self.assertNotIn("tiles", body)
        self.assertIsNone(body["next_cursor"])
        self.assertEqual(self._get(self.nobody, "?preset=supervision")["cases"], [])

    def test_out_of_scope_ids_narrow_to_nothing_and_are_not_echoed(self):
        self.assertTrue(self._in(self.a, self._ids(self.ian)))
        for query in (f"?org_unit_id={self.scc.org_unit_id}", f"?project_id={SITES_PROJECT}"):
            body = self._get(self.ian, query)
            self.assertEqual(body["cases"], [], query)
        self._login(str(self.ian.user_id))
        text = self.client.get(f"{API}?org_unit_id={self.scc.org_unit_id}").get_data(as_text=True)
        self.assertNotIn(str(self.scc.org_unit_id), text)

    def test_unit_filter_does_not_reveal_membership_to_a_coder(self):
        # A coder reaches the case through submissions only: no unit field,
        # so a unit filter must not act as a membership probe.
        self.assertTrue(self._in(self.e, self._ids(self.cody)))
        body = self._get(self.cody, f"?org_unit_id={self.sca.org_unit_id}")
        self.assertEqual(body["cases"], [])
        self.assertEqual(body["counts"]["total"], 0)

    # -- field visibility ---------------------------------------------------------

    def test_names_and_units_by_reach(self):
        e = str(self.e.death_id)
        for who, name, unit in ((self.ian, True, True), (self.sue, True, True), (self.pat, True, True),
                                (self.dana, True, True), (self.cole, False, True), (self.cody, False, False)):
            row = self._ids(who).get(e)
            self.assertIsNotNone(row, who.email)
            self.assertEqual("deceased_name" in row, name, who.email)
            self.assertEqual("unit_name" in row, unit, who.email)
            self.assertEqual("org_unit_id" in row, unit, who.email)
            self.assertEqual(row["unique_id"], self.e.unique_id)  # always
            self.assertEqual(row["age_years"], 70)
            self.assertEqual(row["status"], "submitted_awaiting_coding")

    def test_staff_names_by_role(self):
        a = str(self.a.death_id)
        self.assertEqual(self._ids(self.dana)[a]["reporter_name"], self.ian.name)
        self.assertEqual(self._ids(self.sue)[a]["reporter_name"], self.ian.name)
        theirs = self._ids(self.ian)
        self.assertEqual(theirs[a]["reporter_name"], self.ian.name)  # own registration
        self.assertNotIn("reporter_name", theirs[str(self.b.death_id)])  # wally's
        self.assertTrue(theirs[a]["registered_by_me"])
        for who in (self.cody, self.cole, self.pat):
            row = self._ids(who).get(str(self.e.death_id))
            self.assertIsNotNone(row)
            for field in STAFF_FIELDS:
                self.assertNotIn(field, row, who.email)
        self.assertEqual(self._ids(self.dana)[str(self.f.death_id)]["coder_name"], self.cody.name)

    def test_supervising_roles_and_admin_need_pii_access_for_names(self):
        # Owner, 2026-10-20: no PII bypass for admin; names are omitted, rows stay.
        a, e, f = (str(c.death_id) for c in (self.a, self.e, self.f))
        for who, case in ((self.sue, a), (self.pip, a), (self.dana, f), (self.admin, e)):
            row = self._ids(who).get(case)
            self.assertIsNotNone(row, who.email)
            self.assertIn("deceased_name", row, who.email)
        self.assertIn("coder_name", self._ids(self.dana)[f])
        self.assertIn("reporter_name", self._ids(self.sue)[a])
        with _redacted():
            for who, case in ((self.sue, a), (self.pip, a), (self.dana, f), (self.admin, e)):
                row = self._ids(who).get(case)
                self.assertIsNotNone(row, who.email)  # still in scope
                self.assertIn("unique_id", row)
                for field in ("deceased_name", *STAFF_FIELDS):
                    self.assertNotIn(field, row, who.email)
            # Field roles and collaborator_pii are not governed by the predicate.
            self.assertEqual(self._ids(self.ian)[a]["deceased_name"], "Asha Alpha")
            self.assertEqual(self._ids(self.pat)[e]["deceased_name"], "Esha Echo")

    def test_interview_supervisor_alone_sees_no_names(self):
        row = self._ids(self.sam).get(str(self.a.death_id))
        self.assertIsNotNone(row)
        for field in ("deceased_name", *STAFF_FIELDS):
            self.assertNotIn(field, row)

    def test_location_follows_decision_six(self):
        a, b = str(self.a.death_id), str(self.b.death_id)
        ian = self._ids(self.ian)
        self.assertEqual((ian[a]["latitude"], ian[a]["longitude"]), (28.61, 77.2))
        self.assertIn("latitude", ian[b])  # an interviewer is not redacted: others' cases too
        rita = self._ids(self.rita)[str(self.d.death_id)]  # redacted, but its own registration
        self.assertIn("latitude", rita)
        e = str(self.e.death_id)
        self.assertIn("latitude", self._ids(self.vera)[e])  # interviewer reach, and also a coder
        self.assertNotIn("latitude", self._ids(self.sam)[a])  # supervisor: redacted
        for who in (self.cody, self.cole, self.dana, self.pat):  # reached without a field reach
            row = self._ids(who)[e]
            self.assertNotIn("latitude", row, who.email)
            self.assertNotIn("longitude", row, who.email)
        # Sites mode: never, not even for the interviewer who registered it.
        mine = self._ids(self.ivy)[str(self.s.death_id)]
        self.assertEqual(mine["deceased_name"], "Sita Sierra")
        self.assertNotIn("latitude", mine)
        # Never on supervision rows.
        flagged = self._ids(self.sam, "?preset=supervision&attention=total")
        self.assertTrue(self._in(self.a, flagged))
        self.assertTrue(all("latitude" not in row for row in flagged.values()))

    def test_no_informant_data_in_any_row(self):
        for who in (self.ian, self.dana, self.sam):
            for row in self._ids(who).values():
                for key in row:
                    self.assertNotIn("informant", key)
                    self.assertNotIn("phone", key)
                    self.assertNotIn("address", key)

    # -- presets, status, filters ---------------------------------------------------

    def test_deaths_preset_leaves_out_duplicate_and_cancelled_unless_asked(self):
        rows = self._ids(self.dana)
        self.assertTrue(self._in(self.a, rows))
        self.assertFalse(self._in(self.i, rows))
        self.assertFalse(self._in(self.j, rows))
        asked = self._ids(self.dana, "?status=duplicate&status=cancelled")
        self.assertEqual({r["status"] for r in asked.values()}, {"duplicate", "cancelled"})
        self.assertTrue(self._in(self.i, asked) and self._in(self.j, asked))

    def test_interview_and_coding_presets_default_filters(self):
        interview = self._ids(self.dana, "?preset=interview")
        self.assertTrue(self._in(self.a, interview) and self._in(self.h, interview))
        self.assertFalse(self._in(self.e, interview))
        coding = self._ids(self.dana, "?preset=coding")
        self.assertTrue(self._in(self.e, coding) and self._in(self.f, coding))
        self.assertFalse(self._in(self.g, coding))  # coded
        self.assertFalse(self._in(self.a, coding))
        every = self._ids(self.dana, "?preset=coding&status=coded")
        self.assertEqual({r["status"] for r in every.values()}, {"coded"})

    def test_combined_status_for_every_workflow_state(self):
        from app.services.workflow.definition import ALL_WORKFLOW_STATES
        expected = {
            "screening_pending": "submitted_awaiting_coding", "attachment_sync_pending": "submitted_awaiting_coding",
            "smartva_pending": "submitted_awaiting_coding", "ready_for_coding": "submitted_awaiting_coding",
            "coding_in_progress": "in_coding", "coder_step1_saved": "in_coding",
            "reviewer_coding_in_progress": "in_coding", "coder_finalized": "coded", "reviewer_eligible": "coded",
            "reviewer_finalized": "coded", "finalized_upstream_changed": "coded",
            "not_codeable_by_coder": "not_codeable", "not_codeable_by_data_manager": "not_codeable",
            "consent_refused": "refused",
        }
        self.assertEqual(set(expected), set(ALL_WORKFLOW_STATES))
        made = {state: self._submitted(state, self.wally, self.scb).death_id for state in expected}
        rows = self._ids(self.dana, "?limit=200&status=" + "&status=".join(case_list.COMBINED_STATUSES))
        for state, death_id in made.items():
            self.assertEqual(rows[str(death_id)]["status"], expected[state], state)
        # The register's own states.
        by_register = {"registered": "reported", "scheduled": "interview_pending", "paused": "interview_pending",
                       "not_reachable": "interview_pending", "in_progress": "interview_in_progress",
                       "draft_identity": "interview_in_progress", "refused": "refused",
                       "duplicate": "duplicate", "cancelled": "cancelled"}
        for state, status in by_register.items():
            case = self._register(self.wally, self.scb)
            case.status = state
            db.session.flush()
            row = self._ids(self.dana, "?limit=200&status=" + status)[str(case.death_id)]
            self.assertEqual((row["status"], row["register_state"]), (status, state))

    def test_counts_equal_the_rows_a_status_filter_returns(self):
        body = self._get(self.dana)
        counts = body["counts"]
        self.assertGreater(counts["reported"], 0)
        self.assertEqual(counts["total"], sum(counts[s] for s in case_list.COMBINED_STATUSES))
        for status in case_list.COMBINED_STATUSES:
            rows = self._get(self.dana, f"?status={status}&limit=200")["cases"]
            self.assertEqual(len(rows), counts[status], status)
            self.assertTrue(all(r["status"] == status for r in rows))
        # Counts ignore the status filter, keep the others.
        narrowed = self._get(self.dana, f"?status=coded&project_id={SITES_PROJECT}")["counts"]
        self.assertEqual(narrowed["total"], 0)
        self.assertEqual(self._get(self.dana, "?status=coded")["counts"], counts)

    def test_each_filter(self):
        def ids(query, who=None):
            return set(self._ids(who or self.dana, query + "&limit=200"))

        a, b, c, e = (str(x.death_id) for x in (self.a, self.b, self.c, self.e))
        self.assertTrue({a, b} <= ids(f"?project_id={PROJECT}"))
        self.assertNotIn(str(self.s.death_id), ids(f"?project_id={PROJECT}"))
        self.assertIn(a, ids(f"?site_id={SITE}"))
        self.assertEqual(ids(f"?site_id={SITES_SITE}"), set())
        subtree = ids(f"?org_unit_id={self.ph1.org_unit_id}")
        self.assertTrue({a, b} <= subtree)
        self.assertNotIn(c, subtree)
        self.assertEqual(ids(f"?org_unit_id={self.scc.org_unit_id}"), {c})
        self.assertIn(c, ids(f"?org_unit_id={self.ch1.org_unit_id}"))
        self.assertTrue({a, b, e} <= ids("?state=registered&state=submitted"))
        self.assertIn(str(self.h.death_id), ids("?state=paused"))
        self.assertNotIn(a, ids("?state=paused"))
        self.assertIn(b, ids(f"?dod_from={_dod(6)}&dod_to={_dod(5)}"))  # end inclusive
        self.assertNotIn(a, ids(f"?dod_from={_dod(6)}&dod_to={_dod(5)}"))
        self.assertIn(a, ids(f"?dod_to={_dod(10)}"))
        self.assertNotIn(b, ids(f"?dod_to={_dod(10)}"))
        utc_today = datetime.now(UTC).date()  # the service filters UTC days
        today = utc_today.isoformat()
        self.assertIn(a, ids(f"?reported_from={today}&reported_to={today}"))  # inclusive end
        tomorrow = (utc_today + timedelta(days=1)).isoformat()
        self.assertNotIn(a, ids(f"?reported_from={tomorrow}"))
        self.assertNotIn(a, ids(f"?reported_to={(utc_today - timedelta(days=1)).isoformat()}"))
        self.assertIn(b, ids("?sex=male"))
        self.assertNotIn(a, ids("?sex=male"))
        self.assertIn(a, ids("?age_min=62&age_max=62"))
        self.assertNotIn(b, ids("?age_min=62"))
        self.assertIn(b, ids("?age_max=40"))

    def test_supervision_preset_tiles_order_and_extra_cases(self):
        body = self._get(self.sam, "?preset=supervision")
        rows = body["cases"]
        flagged = [r for r in rows if r["death_id"] == str(self.k.death_id)]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["reason"], "resolve_flag")
        self.assertEqual(flagged[0]["pending_flag"], "duplicate")
        self.assertIn("waiting_since", flagged[0])
        self.assertEqual({r["reason"] for r in rows}, {"resolve_flag"})  # the default: needs my decision
        self.assertEqual(body["tiles"]["needs_decision"], 1)
        self.assertEqual(body["tiles"]["overdue"], 1)  # Hari
        self.assertGreaterEqual(body["tiles"]["total"], 8)
        everything = self._get(self.sam, "?preset=supervision&attention=total&limit=200")["cases"]
        stamps = [r["updated_at"] for r in everything]
        self.assertEqual(stamps, sorted(stamps))  # oldest first
        self.assertEqual(everything[0]["death_id"], str(self.k.death_id))
        by_id = {r["death_id"]: r for r in everything}
        self.assertEqual(by_id[str(self.i.death_id)]["reason"], "reopen")
        self.assertEqual(by_id[str(self.j.death_id)]["reason"], "reopen")
        self.assertEqual(by_id[str(self.h.death_id)]["reason"], "overdue")
        # Duplicate and cancelled show up in no other preset by default.
        others = self._ids(self.sam)
        self.assertTrue(self._in(self.a, others))
        self.assertFalse(self._in(self.i, others) or self._in(self.j, others))
        overdue = self._ids(self.sam, "?preset=supervision&attention=overdue")
        self.assertEqual(set(overdue), {str(self.h.death_id)})
        # Tiles ride along in any preset for a supervisor, never for others.
        self.assertIn("tiles", self._get(self.sam))
        self.assertNotIn("tiles", self._get(self.ian))
        self.assertEqual(self._get(self.ian, "?preset=supervision")["cases"], [])

    def test_supervision_preset_is_empty_under_device_credentials(self):
        with self.app.test_request_context("/"):
            g.bearer_auth = True
            page = case_list.list_cases(
                self.sam, preset="supervision", filters=case_list.CaseFilters(attention="total"))
        self.assertEqual(page["cases"], [])
        self.assertTrue(self._in(self.a, self._ids(self.sam, "?preset=supervision&attention=total")))

    # -- paging -----------------------------------------------------------------

    def test_cursor_continuity_in_every_order(self):
        for sort in case_list.SORTS:
            full = [r["death_id"] for r in self._get(self.dana, f"?sort={sort}&limit=200")["cases"]]
            self.assertGreater(len(full), 5)
            seen, cursor = [], None
            for _ in range(len(full) + 2):
                body = self._get(self.dana, f"?sort={sort}&limit=3" + (f"&cursor={cursor}" if cursor else ""))
                seen += [r["death_id"] for r in body["cases"]]
                cursor = body["next_cursor"]
                if not cursor:
                    break
            self.assertEqual(seen, full, sort)
            self.assertEqual(len(set(seen)), len(seen))

    def test_cursor_continuity_with_equal_timestamps(self):
        # Equal created_at/updated_at force the death_id tie-break (core UPDATE:
        # the ORM would reset updated_at). Rolled back by the test's isolation.
        stamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        tied = [self.a, self.b, self.c, self.d, self.e]
        db.session.execute(sa.update(VaDeathRegister).where(
            VaDeathRegister.death_id.in_([x.death_id for x in tied])).values(created_at=stamp, updated_at=stamp))
        db.session.flush()
        for sort in case_list.SORTS:
            full = [r["death_id"] for r in self._get(self.dana, f"?sort={sort}&limit=200")["cases"]]
            self.assertTrue({str(x.death_id) for x in tied} <= set(full), sort)
            for limit in (1, 2):
                seen, cursor = [], None
                for _ in range(len(full) + 2):
                    body = self._get(self.dana, f"?sort={sort}&limit={limit}" + (f"&cursor={cursor}" if cursor else ""))
                    seen += [r["death_id"] for r in body["cases"]]
                    cursor = body["next_cursor"]
                    if not cursor:
                        break
                self.assertEqual(seen, full, (sort, limit))
                self.assertEqual(len(set(seen)), len(seen), (sort, limit))

    def test_counts_and_tiles_ride_the_first_page_only(self):
        first = self._get(self.sam, "?preset=supervision&attention=total&limit=1")
        self.assertIn("counts", first)
        self.assertIn("tiles", first)
        self.assertTrue(first["next_cursor"])
        later = self._get(self.sam, f"?preset=supervision&attention=total&limit=1&cursor={first['next_cursor']}")
        self.assertTrue(later["cases"])
        self.assertNotIn("counts", later)
        self.assertNotIn("tiles", later)

    def test_reported_at_only_for_register_cases(self):
        direct = self._register(self.wally, self.scb)
        direct.source = "direct"
        db.session.flush()
        rows = self._ids(self.dana, "?limit=200")
        self.assertEqual(rows[str(self.a.death_id)]["source"], "register")
        self.assertEqual(rows[str(self.a.death_id)]["reported_at"], rows[str(self.a.death_id)]["created_at"])
        self.assertEqual(rows[str(direct.death_id)]["source"], "direct")
        self.assertNotIn("reported_at", rows[str(direct.death_id)])

    def test_a_cursor_never_crosses_orders_and_bad_input_is_a_400(self):
        cursor = self._get(self.dana, "?sort=reported&limit=2")["next_cursor"]
        self.assertTrue(cursor)
        self._login(str(self.dana.user_id))
        for query in (f"?sort=updated&cursor={cursor}", "?cursor=nonsense", "?preset=other", "?status=other",
                      "?dod_from=2026-13-01", "?dod_from=20261020", "?reported_from=yesterday",
                      "?org_unit_id=abc", "?limit=many", "?sex=other", f"?dod_from={_dod(1)}&dod_to={_dod(3)}",
                      "?age_min=-1", "?age_max=999", "?age_min=" + "9" * 5000, "?sort=random", "?attention=all", "?project_id=" + "x" * 65,
                      f"?org_unit_id={uuid.uuid4()}&org_unit_id={uuid.uuid4()}"):
            response = self.client.get(f"{API}{query}")
            self.assertEqual(response.status_code, 400, query)
            self.assertEqual(response.get_json()["code"], "invalid_request")
            self.assertNotIn("nonsense", response.get_data(as_text=True))

    def test_limit_is_clamped(self):
        body = self._get(self.dana, "?limit=100000")
        self.assertLessEqual(len(body["cases"]), case_list.WORKLIST_PAGE_MAX)
        self.assertEqual(len(self._get(self.dana, "?limit=0")["cases"]), 1)

    def test_statement_count_does_not_grow_with_the_page(self):
        def count(limit):
            statements = []

            def record(conn, cursor, statement, parameters, context, executemany):
                statements.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                self.assertTrue(self._get(self.dana, f"?limit={limit}")["cases"])
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            return len(statements)

        count(1)  # warm the per-request caches the first call fills
        self.assertEqual(count(1), count(50))
        # A cursor page skips the counts and tiles statements.
        cursor = self._get(self.dana, "?limit=1")["next_cursor"]
        statements = []

        def record(conn, cursor_, statement, parameters, context, executemany):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            self._get(self.dana, f"?limit=1&cursor={cursor}")
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertLess(len(statements), count(1))
        self.assertGreater(len(self._get(self.dana, "?limit=50")["cases"]), 5)

    # -- the other endpoints ------------------------------------------------------

    def test_filter_options_stay_inside_the_scope(self):
        self._login(str(self.ian.user_id))
        options = self.client.get(f"{API}/filter-options").get_json()
        self.assertEqual([p["project_id"] for p in options["projects"]], [PROJECT])
        self.assertEqual(options["sites"][0]["site_name"], f"Site {SITE}")
        names = {u["unit_name"] for u in options["units"]}
        self.assertIn("Unit SCA", names)
        self.assertNotIn("Unit SCC", names)
        self.assertNotIn("people", options)
        self._login(str(self.dana.user_id))
        wide = self.client.get(f"{API}/filter-options").get_json()
        self.assertIn("Unit SCC", {u["unit_name"] for u in wide["units"]})
        self._login(str(self.cody.user_id))
        coder = self.client.get(f"{API}/filter-options").get_json()
        self.assertEqual(coder["units"], [])
        self._login(str(self.nobody.user_id))
        self.assertEqual(self.client.get(f"{API}/filter-options").get_json()["projects"], [])

    def test_gets_need_no_csrf_and_nothing_else_is_allowed(self):
        self._login(str(self.ian.user_id))
        self.assertEqual(self.client.get(API).status_code, 200)
        self.assertEqual(self.client.post(API, json={}, headers=self._csrf_headers()).status_code, 405)
        if hasattr(g, "_login_user"):
            del g._login_user  # Flask-Login's per-context cache of the signed-in user
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get(API).status_code, 401)

    def test_the_existing_intake_lists_are_unchanged(self):
        self._login(str(self.ian.user_id))
        cases = self.client.get("/api/v1/intake/cases").get_json()
        row = next(r for r in cases["cases"] if r["death_id"] == str(self.a.death_id))
        self.assertIn("state", row)
        self.assertNotIn("register_state", row)
        self.assertEqual(row["deceased_name"], "Asha Alpha")
        self.assertEqual(set(cases), {"cases", "counts", "next_cursor"})
        deaths = self.client.get(f"/api/v1/intake/deaths?project_id={PROJECT}&site_id={SITE}")
        self.assertEqual(deaths.status_code, 200)
        self.assertIn("deaths", deaths.get_json())
