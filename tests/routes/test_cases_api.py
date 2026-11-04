"""The shared case list: GET /api/v1/cases and /filter-options (digitva-pt0s).

Policy: docs/policy/case-list-views.md. Tree CLP01 (site CL01): DST > CH1 >
PH1 > SCA, SCB and CH1 > PH2 > SCC; CLS01 (site SM01) is a sites-mode project.
Every "absent" assertion first asserts that an in-scope sibling is present.
"""
import base64
import uuid
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa
from flask import g
from werkzeug.datastructures import MultiDict

from app import db, limiter
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocations,
    VaDeathRegister,
    VaFinalAssessments,
    VaFinalCodAuthority,
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
from app.services import register_pii_accessor
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


def _utc_day(days_ago):
    return datetime.now(UTC).date() - timedelta(days=days_ago)


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

        cls.dst = unit("DST", "district")
        cls.ch1 = unit("CH1", "chc", cls.dst)
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
        at_dst = (VaAccessScopeTypes.org_unit, cls.dst)
        at_ph1 = (VaAccessScopeTypes.org_unit, cls.ph1)
        cls.ian = user("ian", (R.interviewer, at_ph1))
        cls.rita = user("rita", (R.death_reporter, at_ph1))
        cls.sam = user("sam", (R.interview_supervisor, at_ph1))
        cls.wally = user("wally", (R.interviewer, whole))
        cls.cody = user("cody", (R.coder, whole))
        cls.dana = user("dana", (R.data_manager, at_dst))
        cls.pat = user("pat", (R.collaborator_pii, at_dst))
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
                va_sid=sid, va_form_id=f"{PROJECT}{SITE}01",
                org_unit_id=where.org_unit_id if where else None,
                org_unit_resolution="form_field" if where else None,
                va_submission_date=now, va_odk_updatedat=now,
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

    def test_supervising_roles_and_admin_see_names_as_pii_holders(self):
        # Owner, 2026-10-26: Tier 3 unit roles (interview_supervisor, unit data_manager)
        # and admin are PII holders; Tier 1 project_pi on an organization-tree project is Non-PII.
        a, e, f = (str(c.death_id) for c in (self.a, self.e, self.f))
        for who, case in ((self.sue, a), (self.sam, a), (self.dana, f), (self.admin, e)):
            row = self._ids(who).get(case)
            self.assertIsNotNone(row, who.email)
            self.assertIn("deceased_name", row, who.email)
        self.assertIn("coder_name", self._ids(self.dana)[f])
        self.assertIn("reporter_name", self._ids(self.sue)[a])
        pip_row = self._ids(self.pip).get(a)
        self.assertIsNotNone(pip_row)
        for field in ("deceased_name", *STAFF_FIELDS):
            self.assertNotIn(field, pip_row)
        with _redacted():
            for who, case in ((self.sue, a), (self.sam, a), (self.dana, f), (self.admin, e)):
                row = self._ids(who).get(case)
                self.assertIsNotNone(row, who.email)  # still in scope
                self.assertIn("unique_id", row)
                for field in ("deceased_name", *STAFF_FIELDS):
                    self.assertNotIn(field, row, who.email)
            # Field roles and collaborator_pii are not governed by the predicate.
            self.assertEqual(self._ids(self.ian)[a]["deceased_name"], "Asha Alpha")
            self.assertEqual(self._ids(self.pat)[e]["deceased_name"], "Esha Echo")

    def test_interview_supervisor_alone_sees_no_names(self):
        # Under the Three-Tier PII boundary (2026-10-26), Tier 3 interview_supervisor@org_unit
        # sees PII names, while Tier 1 project_pi@project sees no PII names.
        sam_row = self._ids(self.sam).get(str(self.a.death_id))
        self.assertIsNotNone(sam_row)
        self.assertEqual(sam_row["deceased_name"], "Asha Alpha")
        self.assertEqual(sam_row["reporter_name"], self.ian.name)
        pip_row = self._ids(self.pip).get(str(self.a.death_id))
        self.assertIsNotNone(pip_row)
        for field in ("deceased_name", *STAFF_FIELDS):
            self.assertNotIn(field, pip_row)

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
                      "?age_min=-1", "?age_max=999", "?age_min=" + "9" * 5000, "?sort=random", "?attention=all", "?source=paper", "?source=register,paper", "?project_id=" + "x" * 65,
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

    def _statements(self, run):
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            run()
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        return len(statements)

    def test_first_page_statement_count_is_pinned(self):
        """An admin's first page with counts. In a request the grant lookups
        are memoised (9 statements); outside one (Celery, CLI) every
        ``resolve_grants`` re-reads, so the count shows how often the reach is
        built: 112 when the page and the counts each built their own, 34 with
        the one built in ``case_list_page``."""
        self._login(str(self.admin.user_id))

        def request():
            response = self.client.get(f"{API}?preset=deaths")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["cases"])

        self.assertLessEqual(self._statements(request), 12)
        body = {}
        self._statements(lambda: body.update(case_list.case_list_page(self.admin, MultiDict())))
        self.assertTrue(body["cases"])
        self.assertLessEqual(self._statements(lambda: case_list.case_list_page(self.admin, MultiDict())), 40)

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


    # -- Statistics additions (2026-11-04) ---------------------------------------

    def _set_submission_day(self, case, days_ago):
        db.session.execute(sa.update(VaSubmissions).where(VaSubmissions.va_sid == case.va_sid)
                           .values(va_submission_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_ago)))
        db.session.commit()

    def _status(self, who, query):
        self._login(str(who.user_id))
        return self.client.get(f"{API}{query}")

    # -- project_id ------------------------------------------------------------

    def test_project_id_repeats_and_never_leaks_an_unreachable_project(self):
        both = self._get_or_make_user("cl.both@test.local", "CaseList123")
        for project_id in (PROJECT, SITES_PROJECT):
            db.session.add(VaUserAccessGrants(
                user_id=both.user_id, role=R.interviewer, scope_type=VaAccessScopeTypes.project,
                project_id=project_id, grant_status=VaStatuses.active, notes="case list"))
        db.session.commit()
        for query in (f"?project_id={PROJECT}&project_id={SITES_PROJECT}", f"?project_id={PROJECT},{SITES_PROJECT}"):
            rows = self._ids(both, query)
            self.assertTrue(self._in(self.a, rows), query)
            self.assertTrue(self._in(self.s, rows), query)
        one = self._ids(both, f"?project_id={SITES_PROJECT}")
        self.assertTrue(self._in(self.s, one))
        self.assertFalse(self._in(self.a, one))
        # ivy reaches CLS01 only: naming CLP01 as well adds nothing of it.
        body = self._get(self.ivy, f"?project_id={SITES_PROJECT}&project_id={PROJECT}")
        rows = {c["death_id"]: c for c in body["cases"]}
        self.assertTrue(self._in(self.s, rows))
        self.assertEqual({c["project_id"] for c in body["cases"]}, {SITES_PROJECT})
        self.assertEqual(body["counts"]["total"], len(rows))
        self.assertEqual(self._get(self.ivy, f"?project_id={PROJECT}")["cases"], [])

    def test_project_id_values_are_bounded(self):
        many = ",".join(f"P{i}" for i in range(case_list.PROJECTS_MAX + 1))
        self.assertEqual(self._status(self.dana, f"?project_id={many}").status_code, 400)
        self.assertEqual(self._status(self.dana, f"?project_id={'x' * 65}").status_code, 400)

    # -- submitted_from / submitted_to -----------------------------------------

    def test_submitted_range_filters_on_the_submission_day(self):
        self._set_submission_day(self.e, 20)
        day = _utc_day(20).isoformat()
        rows = self._ids(self.dana, f"?submitted_from={day}&submitted_to={day}")
        self.assertTrue(self._in(self.e, rows))
        self.assertFalse(self._in(self.f, rows))  # submitted today
        self.assertFalse(self._in(self.a, rows))  # no submission
        later = self._ids(self.dana, f"?submitted_from={_utc_day(19).isoformat()}")
        self.assertTrue(self._in(self.f, later))
        self.assertFalse(self._in(self.e, later))
        self.assertFalse(self._in(self.a, later))
        body = self._get(self.dana, f"?submitted_to={day}")
        self.assertEqual([c["death_id"] for c in body["cases"]], [str(self.e.death_id)])
        self.assertEqual(body["counts"]["total"], 1)
        self.assertEqual(self._status(self.dana, f"?submitted_from={day}&submitted_to={_utc_day(21)}").status_code, 400)
        self.assertEqual(self._status(self.dana, "?submitted_from=yesterday").status_code, 400)

    # -- overdue ----------------------------------------------------------------

    def test_overdue_interview_boundary_and_date_reported_fallback(self):
        late = self._register(self.ian, self.sca, deceased_name="Late Sixtyone", date_of_death=_utc_day(61).isoformat())
        edge = self._register(self.ian, self.sca, deceased_name="Edge Sixty", date_of_death=_utc_day(60).isoformat())
        undated_late = self._register(self.ian, self.sca, deceased_name="Undated Late")
        undated_edge = self._register(self.ian, self.sca, deceased_name="Undated Edge")
        now = datetime.now(UTC)
        # Only a draft_identity case may lack its date of death (ck_va_death_register_identity).
        for case, days in ((undated_late, 61), (undated_edge, 60)):
            db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == case.death_id)
                               .values(status="draft_identity", date_of_death=None,
                                       created_at=now - timedelta(days=days)))
        db.session.commit()
        rows = self._ids(self.dana, "?overdue=interview")
        self.assertTrue(self._in(late, rows))
        self.assertTrue(self._in(undated_late, rows))
        self.assertFalse(self._in(edge, rows))
        self.assertFalse(self._in(undated_edge, rows))
        self.assertFalse(self._in(self.a, rows))
        self.assertEqual(rows[str(late.death_id)]["overdue"], "interview")
        self.assertEqual(rows[str(late.death_id)]["days_waiting"], 61)
        self.assertEqual(rows[str(undated_late.death_id)]["days_waiting"], 61)
        everyone = self._ids(self.dana)
        self.assertIsNone(everyone[str(edge.death_id)]["overdue"])
        self.assertEqual(everyone[str(edge.death_id)]["days_waiting"], 60)
        self.assertEqual(everyone[str(undated_edge.death_id)]["days_waiting"], 60)
        # Counts honour the filter, as every other filter.
        body = self._get(self.dana, "?overdue=interview")
        self.assertEqual(body["counts"]["total"], len(body["cases"]))
        self.assertEqual(body["counts"]["reported"], 1)
        self.assertEqual(body["counts"]["interview_in_progress"], 1)
        self.assertEqual(self._status(self.dana, "?overdue=1").status_code, 400)

    def test_overdue_coding_boundary(self):
        late = self._submitted("ready_for_coding", self.ian, self.sca, deceased_name="Code Late")
        edge = self._submitted("ready_for_coding", self.ian, self.sca, deceased_name="Code Edge")
        self._set_submission_day(late, 16)
        self._set_submission_day(edge, 15)
        self._set_submission_day(self.f, 16)  # coding_in_progress
        self._set_submission_day(self.g, 40)  # coder_finalized: coded, never overdue
        body = self._get(self.dana, "?preset=coding&overdue=coding")
        rows = {c["death_id"]: c for c in body["cases"]}
        self.assertTrue(self._in(late, rows))
        self.assertTrue(self._in(self.f, rows))
        self.assertFalse(self._in(edge, rows))
        self.assertFalse(self._in(self.g, rows))
        self.assertEqual(rows[str(late.death_id)]["overdue"], "coding")
        self.assertEqual(rows[str(late.death_id)]["days_waiting"], 16)
        self.assertEqual(rows[str(self.f.death_id)]["status"], "in_coding")
        self.assertEqual(body["counts"]["submitted_awaiting_coding"], 1)
        self.assertEqual(body["counts"]["in_coding"], 1)
        self.assertEqual(body["counts"]["total"], 2)
        everyone = self._ids(self.dana, "?preset=coding")
        self.assertIsNone(everyone[str(edge.death_id)]["overdue"])
        self.assertEqual(everyone[str(edge.death_id)]["days_waiting"], 15)
        coded = self._ids(self.dana, "?status=coded")[str(self.g.death_id)]
        self.assertIsNone(coded["overdue"])
        self.assertIsNone(coded["days_waiting"])

    # -- submitted_at / coded_at --------------------------------------------------

    def _authority(self, case, effective_at):
        assessment = VaFinalAssessments(va_sid=case.va_sid, va_finassess_by=self.cody.user_id,
                                        va_conclusive_cod="I10 - Essential Hypertension")
        db.session.add(assessment)
        db.session.flush()
        authority = VaFinalCodAuthority(va_sid=case.va_sid, authoritative_final_assessment_id=assessment.va_finassess_id,
                                        authority_source_role="vacoder", authority_reason="final_cod_submitted",
                                        effective_at=effective_at)
        db.session.add(authority)
        db.session.commit()
        return authority

    def test_submitted_at_and_coded_at(self):
        self._set_submission_day(self.e, 3)
        submitted = db.session.scalar(sa.select(VaSubmissions.va_submission_date).where(VaSubmissions.va_sid == self.e.va_sid))
        effective = datetime(2026, 10, 1, 8, 30)
        self._authority(self.g, effective)
        later = self._submitted("coder_finalized", self.ian, self.sca, deceased_name="Coded Later")
        unset = self._authority(later, None)
        rows = self._ids(self.dana, "?status=coded,submitted_awaiting_coding")
        e, g = rows[str(self.e.death_id)], rows[str(self.g.death_id)]
        self.assertEqual(e["submitted_at"], submitted.replace(tzinfo=UTC).isoformat())
        self.assertIsNone(e["coded_at"])
        self.assertEqual(g["coded_at"], effective.replace(tzinfo=UTC).isoformat())
        self.assertEqual(rows[str(later.death_id)]["coded_at"], unset.created_at.replace(tzinfo=UTC).isoformat())
        a = self._ids(self.dana)[str(self.a.death_id)]
        self.assertIsNone(a["submitted_at"])
        self.assertIsNone(a["coded_at"])

    # -- collaborator register reach -------------------------------------------

    def test_plain_collaborator_sees_pending_register_rows_without_names_or_values(self):
        rows = self._ids(self.cole)
        self.assertTrue(self._in(self.e, rows))  # through the submission, as before
        self.assertTrue(self._in(self.a, rows))  # pending, no submission: the register reach
        a = rows[str(self.a.death_id)]
        self.assertEqual(a["status"], "reported")
        self.assertEqual(a["unit_name"], "Unit SCA")
        self.assertNotIn("deceased_name", a)
        self.assertNotIn("Asha", str(rows))
        for field in STAFF_FIELDS:
            self.assertNotIn(field, a)
        self.assertFalse(a["can_edit_identifiers"])
        self.assertTrue(all("value" not in i for i in a["identifiers"]))
        self.assertFalse(self._in(self.s, rows))  # another project
        # No identifier values from this reach, where a field role has them.
        self.assertIn(self.a.death_id, case_list.identifier_value_death_ids(self.ian, [self.a.death_id]))
        self.assertEqual(case_list.identifier_value_death_ids(self.cole, [self.a.death_id]), set())
        self.assertEqual(case_list.identifier_value_death_ids(self.pat, [self.a.death_id]), set())
        # No interview: the worklist stays closed to a collaborator.
        self._login(str(self.cole.user_id))
        self.assertEqual(self.client.get("/api/v1/intake/cases").status_code, 403)
        # The status counts include the pending deaths.
        self.assertGreaterEqual(self._get(self.cole)["counts"]["reported"], 1)
        self.assertIn(PROJECT, {p["project_id"] for p in self.client.get(f"{API}/filter-options").get_json()["projects"]})

    def test_collaborator_pii_sees_names_on_pending_register_rows(self):
        rows = self._ids(self.pat)
        self.assertTrue(self._in(self.a, rows))
        a = rows[str(self.a.death_id)]
        self.assertEqual(a["deceased_name"], "Asha Alpha")
        self.assertEqual(a["unit_name"], "Unit SCA")
        self.assertFalse(a["can_edit_identifiers"])
        for field in STAFF_FIELDS:
            self.assertNotIn(field, a)
        self.assertFalse(self._in(self.s, rows))
        with _redacted():
            redacted = self._ids(self.cole)
        self.assertTrue(self._in(self.a, redacted))

    def test_collaborator_unit_grant_reaches_only_its_subtree(self):
        mentor = self._get_or_make_user("cl.mentor@test.local", "CaseList123")
        db.session.add(VaUserAccessGrants(
            user_id=mentor.user_id, role=R.collaborator, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.ph2.org_unit_id, grant_status=VaStatuses.active, notes="case list"))
        db.session.commit()
        rows = self._ids(mentor)
        self.assertTrue(self._in(self.c, rows))  # SCC under PH2
        self.assertFalse(self._in(self.a, rows))  # SCA under PH1
        self.assertNotIn("deceased_name", rows[str(self.c.death_id)])

    def _collaborator(self, key, *scopes, public_demo=False):
        """A fresh collaborator with one grant per *scopes* entry: a project
        id, or a ``VaProjectSites`` row (a project_site grant)."""
        person = self._get_or_make_user(f"cl.{key}@test.local", "CaseList123")
        person.is_public_demo = public_demo
        for scope in scopes:
            where = ({"scope_type": VaAccessScopeTypes.project, "project_id": scope} if isinstance(scope, str)
                     else {"scope_type": VaAccessScopeTypes.project_site, "project_site_id": scope.project_site_id})
            db.session.add(VaUserAccessGrants(user_id=person.user_id, role=R.collaborator,
                                              grant_status=VaStatuses.active, notes="case list", **where))
        db.session.commit()
        return person

    def _second_site(self):
        """Site CL02 on CLP01 (active pair) and one pending death on it."""
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(site_id="CL02", site_name="Site CL02", site_abbr="CL02",
                                    site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now))
        db.session.flush()
        pair = VaProjectSites(project_id=PROJECT, site_id="CL02", project_site_status=VaStatuses.active,
                              project_site_registered_at=now, project_site_updated_at=now)
        db.session.add(pair)
        case = self._register(self.ian, self.sca, deceased_name="Other Site")
        db.session.flush()
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == case.death_id)
                           .values(site_id="CL02"))
        db.session.commit()
        return pair, case

    def test_collaborator_of_another_project_sees_nothing_of_this_one(self):
        other = self._collaborator("other", SITES_PROJECT)
        rows = self._ids(other)
        self.assertTrue(self._in(self.s, rows))
        for case in (self.a, self.c, self.e):
            self.assertFalse(self._in(case, rows))
        self.assertEqual(self._get(other, f"?project_id={PROJECT}")["counts"]["total"], 0)

    def test_collaborator_site_grant_reaches_only_its_site(self):
        pair, elsewhere = self._second_site()
        home = db.session.scalar(sa.select(VaProjectSites).where(VaProjectSites.project_id == PROJECT,
                                                                 VaProjectSites.site_id == SITE))
        at_site = self._collaborator("atsite", home)
        rows = self._ids(at_site)
        self.assertTrue(self._in(self.a, rows))
        self.assertFalse(self._in(elsewhere, rows))
        self.assertTrue(self._in(elsewhere, self._ids(self._collaborator("atcl02", pair))))

    def test_collaborator_reach_skips_an_inactive_project_site(self):
        pair, elsewhere = self._second_site()
        whole = self._collaborator("whole", PROJECT)
        self.assertTrue(self._in(elsewhere, self._ids(whole)))
        db.session.execute(sa.update(VaProjectSites).where(VaProjectSites.project_site_id == pair.project_site_id)
                           .values(project_site_status=VaStatuses.deactive))
        db.session.commit()
        rows = self._ids(whole)
        self.assertTrue(self._in(self.a, rows))
        self.assertFalse(self._in(elsewhere, rows))

    def test_collaborator_reach_keeps_the_training_project_out(self):
        both = self._collaborator("trainee", PROJECT, SITES_PROJECT)
        self.assertTrue(self._in(self.s, self._ids(both)))
        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=SITES_PROJECT):
            rows = self._ids(both)
            self.assertTrue(self._in(self.a, rows))
            self.assertFalse(self._in(self.s, rows))
            self.assertEqual(self._get(both, f"?project_id={SITES_PROJECT}")["counts"]["total"], 0)

    def test_public_demo_collaborator_gets_no_register_reach(self):
        self.assertTrue(self._in(self.a, self._ids(self._collaborator("real", PROJECT))))
        demo = self._collaborator("demo", PROJECT, public_demo=True)
        self.assertFalse(self._in(self.a, self._ids(demo)))

    def test_virtual_collaborator_grant_gets_no_register_reach(self):
        # No virtual collaborator grant is minted today (DEMO_VIRTUAL_ROLES):
        # this pins the guard should one ever be.
        from app.services.authz.grants import Grant, ResolvedGrants

        def area(virtual):
            grant = Grant(role=R.collaborator, scope_type=VaAccessScopeTypes.project, project_id=PROJECT,
                          virtual=virtual)
            return case_list._collaborator_area(
                self.cole, ResolvedGrants(user_id=self.cole.user_id, is_admin=False, grants=(grant,)))

        self.assertNotIsInstance(area(False), sa.sql.elements.False_)
        self.assertIsInstance(area(True), sa.sql.elements.False_)

    # -- source -----------------------------------------------------------------

    def test_source_filter_narrows_rows_and_counts(self):
        direct = self._register(self.ian, self.sca, deceased_name="Direct Start")
        odk = self._register(self.ian, self.sca, deceased_name="Odk Only")
        db.session.flush()
        for case, source in ((direct, "direct"), (odk, "odk")):
            db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == case.death_id)
                               .values(source=source))
        db.session.commit()
        reported = self._get(self.dana, "?source=register")
        rows = {c["death_id"]: c for c in reported["cases"]}
        self.assertTrue(self._in(self.a, rows))
        self.assertFalse(self._in(direct, rows))
        self.assertFalse(self._in(odk, rows))
        for query in ("?source=direct,odk", "?source=direct&source=odk"):
            body = self._get(self.dana, query)
            self.assertEqual({c["death_id"] for c in body["cases"]}, {str(direct.death_id), str(odk.death_id)})
            self.assertEqual(body["counts"]["total"], 2)
        self.assertEqual(self._get(self.dana)["counts"]["total"],
                         reported["counts"]["total"] + 2)

    # -- can_open / va_sid ----------------------------------------------------------

    def test_can_open_only_where_the_submission_is_viewable(self):
        e = str(self.e.death_id)
        for who in (self.dana, self.cole, self.cody, self.admin):
            row = self._ids(who)[e]
            self.assertTrue(row["can_open"], who.email)
            self.assertEqual(row["va_sid"], self.e.va_sid, who.email)
        # Field reach to a submitted case is not the submission's VIEW scope.
        theirs = self._ids(self.ian)
        self.assertIn(e, theirs)
        self.assertFalse(theirs[e]["can_open"])
        self.assertNotIn("va_sid", theirs[e])
        # A pending death has nothing to open, whoever looks.
        for who in (self.dana, self.cole, self.ian):
            a = self._ids(who)[str(self.a.death_id)]
            self.assertFalse(a["can_open"], who.email)
            self.assertNotIn("va_sid", a, who.email)

    def test_days_waiting_is_never_negative(self):
        ahead = self._register(self.ian, self.sca, deceased_name="Future Date")
        db.session.flush()
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == ahead.death_id)
                           .values(date_of_death=_utc_day(-5)))
        db.session.commit()
        row = self._ids(self.dana)[str(ahead.death_id)]
        self.assertEqual(row["days_waiting"], 0)
        self.assertIsNone(row["overdue"])

    # -- /intake/cases coding_status ----------------------------------------------

    def test_intake_rows_carry_the_coding_status(self):
        stuck = self._submitted("not_codeable_by_coder", self.ian, self.sca, deceased_name="Not Codeable")
        self._login(str(self.ian.user_id))
        rows = {r["death_id"]: r for r in self.client.get("/api/v1/intake/cases?limit=200").get_json()["cases"]}
        expected = {self.e: "awaiting_coding", self.f: "in_coding", self.g: "coded", stuck: "not_codeable", self.a: None}
        for case, status in expected.items():
            self.assertIn(str(case.death_id), rows)
            self.assertEqual(rows[str(case.death_id)]["coding_status"], status, case.unique_id)

    def test_reporter_only_intake_row_has_coding_status_but_no_interview(self):
        theirs = self._submitted("ready_for_coding", self.ian, self.sca, deceased_name="Reported Submitted")
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == theirs.death_id)
                           .values(registered_by=self.rita.user_id))
        db.session.commit()
        self._login(str(self.rita.user_id))
        rows = {r["death_id"]: r for r in self.client.get("/api/v1/intake/cases?limit=200").get_json()["cases"]}
        self.assertIn(str(theirs.death_id), rows)
        row = rows[str(theirs.death_id)]
        self.assertEqual(row["coding_status"], "awaiting_coding")
        self.assertFalse(row["can_interview"])
        self.assertNotIn("other_draft_active", row)
        self.assertNotIn("other_draft_started_at", row)


    # -- submissions with no register row (unregistered=1) --------------------------

    def _unregistered(self, workflow_state="ready_for_coding", unit=None, *, form=f"{PROJECT}{SITE}01",
                      gender="Female", age=50, days_ago=0, stamp=None):
        """A submission no register row names (an ODK-only interview). *stamp*:
        its created and updated time (naive UTC), else now."""
        sid = f"uuid:cl-un-{uuid.uuid4()}"
        now = datetime.now(UTC).replace(tzinfo=None)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=form, org_unit_id=unit.org_unit_id if unit else None,
            org_unit_resolution="form_field" if unit else None,
            va_submission_date=now - timedelta(days=days_ago), va_odk_updatedat=now,
            va_data_collector="cl-un", va_odk_reviewstate="reviewed", va_instance_name=sid,
            va_uniqueid_real=sid, va_uniqueid_masked=f"masked-{sid}", va_consent="yes",
            va_narration_language="English", va_deceased_age=age, va_deceased_gender=gender,
            va_summary=[], va_catcount={}, va_category_list=[],
            **({"va_created_at": stamp, "va_updated_at": stamp} if stamp else {}),
        ))
        db.session.flush()
        if workflow_state:
            db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state=workflow_state))
        db.session.commit()
        return sid

    def _rows(self, who, query):
        """``{death_id or "s:" + va_sid: row}`` of one page."""
        return {r["death_id"] or f"s:{r['va_sid']}": r for r in self._get(who, query)["cases"]}

    def test_unregistered_submission_is_listed_on_request_only(self):
        sid = self._unregistered(unit=self.sca)
        for query in ("?preset=deaths", "?preset=interview&status=submitted_awaiting_coding", "?preset=coding"):
            rows = self._rows(self.dana, f"{query}&unregistered=1&limit=200")
            self.assertTrue(self._in(self.e, rows), query)
            row = rows.get(f"s:{sid}")
            self.assertIsNotNone(row, query)
            self.assertIsNone(row["death_id"])
            self.assertEqual(row["va_sid"], sid)
            self.assertTrue(row["can_open"])
            self.assertNotIn("deceased_name", row)
            self.assertNotIn("reported_at", row)
            self.assertEqual(row["identifiers"], [])
            self.assertFalse(row["can_edit_identifiers"])
            self.assertEqual(row["unique_id"], f"masked-{sid}")
            self.assertEqual((row["project_id"], row["site_id"], row["source"]), (PROJECT, SITE, "odk"))
            self.assertEqual(row["deceased_sex"], "female")  # lowercased from "Female"
            self.assertEqual(row["age_years"], 50)
            self.assertEqual(row["status"], "submitted_awaiting_coding")
            self.assertIsNone(row["register_state"])
            self.assertIsNone(row["date_of_death"])
            self.assertEqual(row["unit_name"], "Unit SCA")
            self.assertEqual(row["interviewer_name"], "cl-un")  # a data manager with personal-data access
            # Flag off: the register rows only.
            plain = self._rows(self.dana, f"{query}&limit=200")
            self.assertTrue(self._in(self.e, plain), query)
            self.assertNotIn(f"s:{sid}", plain, query)
        # A coder reaches it by its VIEW scope, without the unit or staff names.
        coder = self._rows(self.cody, "?unregistered=1&limit=200")
        self.assertTrue(self._in(self.e, coder))
        self.assertIn(f"s:{sid}", coder)
        self.assertNotIn("unit_name", coder[f"s:{sid}"])
        self.assertNotIn("interviewer_name", coder[f"s:{sid}"])
        self.assertNotIn("name_recorded", coder[f"s:{sid}"])  # no personal-data access: nothing said
        # An interviewer has no VIEW scope on submissions.
        field = self._rows(self.ian, "?unregistered=1&limit=200")
        self.assertTrue(self._in(self.a, field))
        self.assertNotIn(f"s:{sid}", field)
        # Supervision stays one row per death; sue sees it elsewhere through her coder grant.
        self.assertIn(f"s:{sid}", self._rows(self.sue, "?unregistered=1&limit=200"))
        supervised = self._rows(self.sue, "?preset=supervision&attention=total&unregistered=1&limit=200")
        self.assertTrue(self._in(self.a, supervised))
        self.assertNotIn(f"s:{sid}", supervised)

    def test_unregistered_status_comes_from_the_workflow(self):
        expected = {
            self._unregistered("ready_for_coding", self.sca): "submitted_awaiting_coding",
            self._unregistered(None, self.sca): "submitted_awaiting_coding",
            self._unregistered("coding_in_progress", self.sca): "in_coding",
            self._unregistered("coder_finalized", self.sca): "coded",
            self._unregistered("not_codeable_by_coder", self.sca): "not_codeable",
            self._unregistered("consent_refused", self.sca): "refused",
        }
        rows = self._rows(self.dana, "?unregistered=1&limit=200")
        for sid, status in expected.items():
            self.assertEqual(rows[f"s:{sid}"]["status"], status, sid)

    def test_unregistered_coding_overdue_boundary(self):
        late = self._unregistered(unit=self.sca, days_ago=16)
        edge = self._unregistered(unit=self.sca, days_ago=15)
        body = self._get(self.dana, "?preset=coding&overdue=coding&unregistered=1&limit=200")
        rows = {r["death_id"] or f"s:{r['va_sid']}": r for r in body["cases"]}
        self.assertIn(f"s:{late}", rows)
        self.assertNotIn(f"s:{edge}", rows)
        self.assertEqual(rows[f"s:{late}"]["overdue"], "coding")
        self.assertEqual(rows[f"s:{late}"]["days_waiting"], 16)
        self.assertEqual(body["counts"]["submitted_awaiting_coding"], 1)
        everyone = self._rows(self.dana, "?preset=coding&unregistered=1&limit=200")
        self.assertIsNone(everyone[f"s:{edge}"]["overdue"])
        self.assertEqual(everyone[f"s:{edge}"]["days_waiting"], 15)
        # Never waiting for an interview.
        self.assertNotIn(f"s:{late}", self._rows(self.dana, "?overdue=interview&unregistered=1&limit=200"))

    def test_unregistered_filters(self):
        sid = self._unregistered(unit=self.sca, gender="Female", age=50)
        male = self._unregistered(unit=self.sca, gender="male", age=30)
        other = self._unregistered(form=f"{SITES_PROJECT}{SITES_SITE}01", gender="female")
        today, yesterday = _utc_day(0).isoformat(), _utc_day(1).isoformat()
        # Admin reaches every submission; a project or site filter picks one.
        for query in (f"?project_id={SITES_PROJECT}", f"?site_id={SITES_SITE}"):
            rows = self._rows(self.admin, f"{query}&unregistered=1&limit=200")
            self.assertIn(f"s:{other}", rows, query)
            self.assertNotIn(f"s:{sid}", rows, query)
        self.assertNotIn(f"s:{other}", self._rows(self.dana, "?unregistered=1&limit=200"))  # another project
        for query, present, absent in (
            ("sex=female", sid, male), ("sex=male", male, sid),
            ("age_min=40&age_max=60", sid, male), ("age_max=40", male, sid),
            (f"submitted_from={today}", sid, None), (f"submitted_to={yesterday}", None, sid),
            # reported_* bounds the submission day of a row with no register row.
            (f"reported_from={today}", sid, None), (f"reported_to={yesterday}", None, sid),
            ("source=odk", sid, None), ("source=register,odk", sid, None),
            (f"org_unit_id={self.sca.org_unit_id}", sid, None), (f"org_unit_id={self.scc.org_unit_id}", None, sid),
        ):
            rows = self._rows(self.dana, f"?{query}&unregistered=1&limit=200")
            if present:
                self.assertIn(f"s:{present}", rows, query)
            if absent:
                self.assertNotIn(f"s:{absent}", rows, query)
        # A register-only filter, or a source without odk, leaves them out.
        for query, sibling in (("source=register", self.a), ("state=registered", self.a),
                               (f"dod_from={_dod(30)}", self.a), ("identifier=missing", None),
                               ("visit_note=1", None)):
            body = self._get(self.dana, f"?{query}&unregistered=1&limit=200")
            rows = {r["death_id"] or f"s:{r['va_sid']}": r for r in body["cases"]}
            if sibling is not None:
                self.assertTrue(self._in(sibling, rows), query)
            self.assertNotIn(f"s:{sid}", rows, query)
            self.assertFalse(any(r["death_id"] is None for r in body["cases"]), query)
        # A unit filter is no membership probe for a coder, who sees no unit.
        self.assertIn(f"s:{sid}", self._rows(self.cody, "?unregistered=1&limit=200"))
        self.assertEqual(self._get(self.cody, f"?org_unit_id={self.sca.org_unit_id}&unregistered=1")["cases"], [])

    def test_unregistered_normalised_age_wins_unless_it_is_not_a_number(self):
        sid = self._unregistered(unit=self.sca, age=6)
        nan = self._unregistered(unit=self.sca, age=7)
        db.session.execute(sa.update(VaSubmissions).where(VaSubmissions.va_sid == sid)
                           .values(va_deceased_age_normalized_years=0.5))
        db.session.execute(sa.text("UPDATE va_submissions SET va_deceased_age_normalized_years = 'NaN' WHERE va_sid = :sid"),
                           {"sid": nan})
        db.session.commit()
        rows = self._rows(self.dana, "?unregistered=1&limit=200")
        self.assertEqual(rows[f"s:{sid}"]["age_years"], 0)
        self.assertEqual(rows[f"s:{nan}"]["age_years"], 7)

    def test_unregistered_rows_of_an_inactive_project_site_are_left_out(self):
        sid = self._unregistered(form=f"{SITES_PROJECT}{SITES_SITE}01")
        self.assertIn(f"s:{sid}", self._rows(self.admin, "?unregistered=1&limit=200"))
        db.session.execute(sa.update(VaProjectSites).where(
            VaProjectSites.project_id == SITES_PROJECT, VaProjectSites.site_id == SITES_SITE,
        ).values(project_site_status=VaStatuses.deactive))
        db.session.commit()
        after = self._get(self.admin, "?unregistered=1&limit=200")
        self.assertTrue(after["cases"])
        self.assertNotIn(sid, {r.get("va_sid") for r in after["cases"]})

    def test_unregistered_counts_add_to_the_register_counts(self):
        self._unregistered("ready_for_coding", self.sca)
        self._unregistered("coder_finalized", self.sca)
        self._unregistered("ready_for_coding", form=f"{SITES_PROJECT}{SITES_SITE}01")  # out of dana's scope
        plain = self._get(self.dana)["counts"]
        mixed = self._get(self.dana, "?unregistered=1")["counts"]
        self.assertEqual(mixed["total"], plain["total"] + 2)
        self.assertEqual(mixed["coded"], plain["coded"] + 1)
        self.assertEqual(mixed["submitted_awaiting_coding"], plain["submitted_awaiting_coding"] + 1)
        self.assertEqual(self._get(self.dana, "?unregistered=1&source=register")["counts"], self._get(
            self.dana, "?source=register")["counts"])

    def test_unregistered_paging_interleaves_without_gaps_or_repeats(self):
        stamp = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        tied = [self.a, self.b, self.c, self.d, self.e]
        db.session.execute(sa.update(VaDeathRegister).where(
            VaDeathRegister.death_id.in_([x.death_id for x in tied])).values(created_at=stamp, updated_at=stamp))
        db.session.commit()
        naive = stamp.replace(tzinfo=None)
        sids = [self._unregistered(unit=self.sca, stamp=naive) for _ in range(3)]
        sids += [self._unregistered(unit=self.sca, stamp=naive - timedelta(hours=1)),
                 self._unregistered(unit=self.sca, stamp=naive + timedelta(hours=1))]
        for sort in case_list.SORTS:
            base = f"?sort={sort}&unregistered=1"
            full_rows = self._get(self.dana, f"{base}&limit=200")["cases"]
            full = [r["death_id"] or f"s:{r['va_sid']}" for r in full_rows]
            self.assertTrue({f"s:{s}" for s in sids} | {str(x.death_id) for x in tied} <= set(full), sort)
            column = "created_at" if sort == "reported" else "updated_at"
            times = [datetime.fromisoformat(r[column]) for r in full_rows]
            self.assertEqual(times, sorted(times, reverse=sort != "oldest"), sort)
            for limit in (1, 2):
                seen, cursor = [], None
                for _ in range(len(full) + 2):
                    body = self._get(self.dana, f"{base}&limit={limit}" + (f"&cursor={cursor}" if cursor else ""))
                    seen += [r["death_id"] or f"s:{r['va_sid']}" for r in body["cases"]]
                    cursor = body["next_cursor"]
                    if not cursor:
                        break
                self.assertEqual(seen, full, (sort, limit))
                self.assertEqual(len(set(seen)), len(seen), (sort, limit))

    def test_a_register_only_cursor_still_pages_with_the_flag(self):
        self._unregistered(unit=self.sca)
        cursor = self._get(self.dana, "?sort=reported&limit=2")["next_cursor"]
        self.assertTrue(cursor)
        self.assertTrue(self._get(self.dana, f"?sort=reported&limit=2&unregistered=1&cursor={cursor}")["cases"])
        self._login(str(self.dana.user_id))
        for key in ("s:", "s:" + "x" * 65, "not-a-uuid"):
            raw = base64.urlsafe_b64encode(f"reported.0.{key}".encode()).decode().rstrip("=")
            response = self.client.get(f"{API}?sort=reported&unregistered=1&cursor={raw}")
            self.assertEqual(response.status_code, 400, key)
        # The register-only list never takes a submission key.
        raw = base64.urlsafe_b64encode(b"reported.0.s:uuid:x").decode().rstrip("=")
        self.assertEqual(self.client.get(f"{API}?sort=reported&cursor={raw}").status_code, 400)
        self.assertEqual(self.client.get(f"{API}?unregistered=maybe").status_code, 400)

    def test_first_page_statement_count_with_unregistered_is_pinned(self):
        """The flag adds exactly one statement to a first page holding register
        rows (the second count; 13 with ``test_first_page_statement_count_is_pinned``'s
        12), none per row, and none to a cursor page."""
        self._unregistered(unit=self.sca)
        self._login(str(self.admin.user_id))

        def request(query):
            def run():
                response = self.client.get(f"{API}{query}")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.get_json()["cases"])
            return run

        plain = self._statements(request("?preset=deaths&limit=50"))
        self.assertEqual(self._statements(request("?preset=deaths&unregistered=1&limit=50")), plain + 1)
        self.assertLessEqual(self._statements(request("?preset=deaths&unregistered=1")), 13)
        # A page of unregistered rows only reads no registration numbers.
        self.assertLessEqual(self._statements(request("?preset=deaths&unregistered=1&limit=1")), plain + 1)
        cursor = self._get(self.admin, "?preset=deaths&unregistered=1&limit=1")["next_cursor"]
        self._login(str(self.admin.user_id))
        self.assertLess(self._statements(request(f"?preset=deaths&unregistered=1&limit=1&cursor={cursor}")), plain)

    def test_the_export_stays_register_only(self):
        sid = self._unregistered(unit=self.sca)
        self.assertIn(f"s:{sid}", self._rows(self.dana, "?unregistered=1&limit=200"))
        self._login(str(self.dana.user_id))
        response = self.client.get(f"{API}/export.csv?unregistered=1")
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        self.assertIn(self.a.unique_id, text)
        self.assertNotIn(sid, text)

    # -- Statistics: the inactive project-site rule, interviewed, names, stage counts ----

    def _deactivated_site(self, case):
        """Moves *case* to a new project-site CLP01/CL02 that is not active
        (core UPDATE: the register row keeps everything else)."""
        now = datetime.now(UTC)
        db.session.add(VaSiteMaster(site_id="CL02", site_name="Site CL02", site_abbr="CL02",
                                    site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now))
        db.session.flush()
        db.session.add(VaProjectSites(project_id=PROJECT, site_id="CL02", project_site_status=VaStatuses.deactive,
                                      project_site_registered_at=now, project_site_updated_at=now))
        db.session.flush()
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == case.death_id)
                           .values(site_id="CL02"))
        db.session.commit()

    def test_a_deactivated_site_leaves_the_statistics_listing_not_supervision(self):
        self._deactivated_site(self.a)
        for query in ("?preset=deaths", "?preset=deaths&source=register", "?preset=deaths&state=registered"):
            stats = self._ids(self.dana, f"{query}&unregistered=1&limit=200")
            self.assertTrue(self._in(self.b, stats), query)
            self.assertFalse(self._in(self.a, stats), query)
        # Flag-off callers, supervision and its counts keep it.
        self.assertTrue(self._in(self.a, self._ids(self.dana, "?limit=200")))
        self.assertTrue(self._in(self.a, self._ids(self.sam, "?preset=supervision&attention=total&limit=200")))
        self.assertTrue(self._in(self.a, self._ids(
            self.sam, "?preset=supervision&attention=total&unregistered=1&limit=200")))
        counts = self._get(self.dana, "?unregistered=1")["counts"]
        self.assertEqual(counts["reported"] + 1, self._get(self.dana)["counts"]["reported"])

    def test_interviewed_lists_only_cases_with_a_submission(self):
        refused = self._register(self.ian, self.sca, deceased_name="Refused Register")
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == refused.death_id)
                           .values(status="refused"))
        consent = self._submitted("consent_refused", self.ian, self.sca, deceased_name="Consent Refused")
        db.session.commit()
        query = "?preset=interview&status=refused&unregistered=1&limit=200"
        every = self._ids(self.dana, query)
        self.assertTrue(self._in(refused, every))
        rows = self._ids(self.dana, f"{query}&interviewed=1")
        self.assertTrue(self._in(consent, rows))
        self.assertFalse(self._in(refused, rows))
        self.assertEqual(self._get(self.dana, f"{query}&interviewed=1")["counts"]["refused"], 1)
        self._login(str(self.dana.user_id))
        self.assertEqual(self.client.get(f"{API}?interviewed=maybe").status_code, 400)

    def test_interview_preset_default_lists_no_unregistered_row_but_counts_it(self):
        """``preset=interview`` without a status is the phone's interview
        worklist (awaiting an interview), which no submission is: the rows
        leave, the counts (status ignored) still hold them."""
        sid = self._unregistered(unit=self.sca)
        body = self._get(self.dana, "?preset=interview&unregistered=1&limit=200")
        self.assertTrue(self._in(self.a, {r["death_id"]: r for r in body["cases"]}))
        self.assertFalse(any(r["death_id"] is None for r in body["cases"]))
        self.assertNotIn(sid, {r.get("va_sid") for r in body["cases"]})
        plain = self._get(self.dana, "?preset=interview")["counts"]
        self.assertEqual(body["counts"]["submitted_awaiting_coding"], plain["submitted_awaiting_coding"] + 1)

    def test_export_prepare_drops_the_flag(self):
        from app.services import case_export_service as case_export
        sid = self._unregistered(unit=self.sca)
        self.assertIn(f"s:{sid}", self._rows(self.dana, "?unregistered=1&limit=200"))
        with self.app.test_request_context():
            plan, count = case_export.prepare(self.dana, MultiDict({"unregistered": "1"}))
            plain, plain_count = case_export.prepare(self.dana, MultiDict())
        self.assertFalse(plan.filters.unregistered)
        self.assertEqual(count, plain_count)
        self.assertGreater(count, 0)

    def test_names_and_staff_of_a_data_manager_without_personal_data_access(self):
        sid = self._unregistered(unit=self.sca)
        with _redacted():
            rows = self._rows(self.dana, "?unregistered=1&limit=200")
        register, submission = rows[str(self.e.death_id)], rows[f"s:{sid}"]
        for row in (register, submission):
            self.assertNotIn("deceased_name", row)
            self.assertNotIn("name_recorded", row)  # nothing said of a name the caller may not see
            self.assertNotIn("interviewer_name", row)
            self.assertEqual(row["unit_name"], "Unit SCA")  # the unit is not personal data
        # With access: the register name, and "not recorded" on the submission.
        rows = self._rows(self.dana, "?unregistered=1&limit=200")
        self.assertEqual(rows[str(self.e.death_id)]["deceased_name"], "Esha Echo")
        self.assertNotIn("name_recorded", rows[str(self.e.death_id)])
        self.assertIs(rows[f"s:{sid}"]["name_recorded"], False)
        self.assertEqual(rows[f"s:{sid}"]["interviewer_name"], "cl-un")

    def test_name_recorded_false_only_where_the_name_is_visible_and_empty(self):
        # As a direct interview's row before its identity step: no name recorded.
        blank = self._register(self.ian, self.sca, deceased_name="Blank")
        blank.status = "draft_identity"  # the identity CHECK allows no name only here
        blank.started_by_user_id = self.ian.user_id
        register_pii_accessor.write_fields(blank, {"deceased_name": None})
        db.session.commit()
        own = self._ids(self.ian, "?limit=200")
        self.assertTrue(self._in(self.a, own))
        self.assertIs(own[str(blank.death_id)]["name_recorded"], False)
        self.assertNotIn("name_recorded", own[str(self.a.death_id)])
        # A collaborator who sees no name hears nothing about it.
        cole = self._ids(self.cole, "?limit=200")
        self.assertTrue(self._in(self.a, cole))
        self.assertNotIn("name_recorded", cole[str(blank.death_id)])
        self.assertNotIn("deceased_name", cole[str(blank.death_id)])

    def _stage_fixture(self):
        """Two projects; register and unregistered rows; a deactivated site;
        a consent-refused interview and a register-refused death; overdue of
        both kinds; one interview before the period."""
        refused = self._register(self.ian, self.sca, deceased_name="Refused Register")
        db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.death_id == refused.death_id)
                           .values(status="refused"))
        self._submitted("consent_refused", self.ian, self.sca, deceased_name="Consent Refused")
        late = self._register(self.ian, self.sca, deceased_name="Late Interview", date_of_death=_dod(90))
        slow = self._submitted("ready_for_coding", self.ian, self.scb, deceased_name="Slow Coding")
        db.session.execute(sa.update(VaSubmissions).where(VaSubmissions.va_sid == slow.va_sid)
                           .values(va_submission_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=20)))
        db.session.commit()
        self._deactivated_site(self.b)
        for state, days in (("ready_for_coding", 0), ("coder_finalized", 1), ("consent_refused", 2),
                            ("not_codeable_by_coder", 3), ("ready_for_coding", 20), ("coding_in_progress", 40)):
            self._unregistered(state, self.sca, days_ago=days)
        self._unregistered(form=f"{SITES_PROJECT}{SITES_SITE}01", days_ago=1)
        return late, slow

    def _stage(self, who, query=""):
        self._login(str(who.user_id))
        response = self.client.get(f"{API}/stage-counts{query}")
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        return response.get_json()

    def _tab_totals(self, who, area, since):
        """The Statistics tabs' totals, as the client reads them: the chips
        summed from the counts, and the rows listed (every page)."""
        period = f"&reported_from={since}" if since else ""
        submitted = f"&submitted_from={since}" if since else ""
        interviews = ",".join(case_list.INTERVIEWED_STATUSES)
        codings = ",".join(case_list.CODING_STATUSES)
        shown = [s for s in case_list.COMBINED_STATUSES if s not in ("duplicate", "cancelled")]
        tabs = {
            "reported": (f"?preset=deaths{period}", shown),
            "interviewed": (f"?preset=interview&status={interviews}&interviewed=1{submitted}",
                            case_list.INTERVIEWED_STATUSES),
            "coded": (f"?preset=coding&status={codings}&interviewed=1{submitted}", ("coded",)),
            "overdue_interview": ("?preset=deaths&overdue=interview", shown),
            "overdue_coding": (f"?preset=coding&status={codings}&interviewed=1&overdue=coding", case_list.CODING_STATUSES),
        }
        totals = {}
        for name, (query, chips) in tabs.items():
            body = self._get(who, f"{query}{area}&unregistered=1&limit=200")
            counted = sum(body["counts"][s] for s in chips)
            if name != "coded":  # the Coded chip is a count; the others are the listed rows too
                self.assertIsNone(body["next_cursor"])
                self.assertEqual(len(body["cases"]), counted, (who.email, name, area))
            totals[name] = counted
        return totals

    def test_stage_counts_equal_the_tab_totals_for_every_role(self):
        late, slow = self._stage_fixture()
        since = _utc_day(30).isoformat()
        checked = 0
        for who, redacted in ((self.admin, False), (self.dana, False), (self.dana, True), (self.cody, False),
                              (self.cole, False), (self.pat, False), (self.ivy, False)):
            with mock.patch.object(case_list, "should_redact_pii", return_value=True) if redacted else _nothing():
                for period in (None, since):
                    stage_query = f"?reported_from={period}&submitted_from={period}" if period else "?"
                    reply = self._stage(who, stage_query)
                    self.assertEqual(reply["thresholds"], {"interview_days": 60, "coding_days": 15})
                    self.assertEqual(reply["total"], self._tab_totals(who, "", period), (who.email, period))
                    for project in (PROJECT, SITES_PROJECT):
                        expected = self._tab_totals(who, f"&project_id={project}", period)
                        got = reply["projects"].get(project, dict.fromkeys(case_list.STAGES, 0))
                        self.assertEqual(got, expected, (who.email, project, period))
                        checked += sum(expected.values())
                    narrowed = self._stage(who, f"{stage_query}&project_id={PROJECT}")
                    self.assertEqual(set(narrowed["projects"]) - {PROJECT}, set())
        self.assertGreater(checked, 0)
        # The fixture's numbers for the data manager (personal-data access), all time.
        dana = self._stage(self.dana)["projects"][PROJECT]
        self.assertGreaterEqual(dana["overdue_interview"], 1)
        self.assertGreaterEqual(dana["overdue_coding"], 3)  # slow, and two unregistered (20, 40 days)
        overdue = self._ids(self.dana, "?preset=deaths&overdue=interview&unregistered=1&limit=200")
        self.assertEqual(overdue[str(late.death_id)]["overdue"], "interview")
        self.assertGreaterEqual(overdue[str(late.death_id)]["days_waiting"], 90)
        # Admin and the coder reach the sites-mode project's unregistered row; the interviewer its register death.
        self.assertIn(SITES_PROJECT, self._stage(self.admin)["projects"])
        self.assertEqual(self._stage(self.ivy)["projects"][SITES_PROJECT]["reported"], 1)

    def test_stage_counts_take_two_statements_and_none_without_scope(self):
        self._unregistered(unit=self.sca)
        self._login(str(self.admin.user_id))
        self._stage(self.admin)  # warm
        with_scope = self._statements(lambda: self._stage(self.admin, f"?project_id={PROJECT}"))
        self.assertLessEqual(with_scope, 12)
        reply = self._stage(self.nobody)
        self.assertEqual(reply["projects"], {})
        self.assertEqual(reply["total"], dict.fromkeys(case_list.STAGES, 0))
        self._login(str(self.admin.user_id))
        self.assertEqual(self.client.get(f"{API}/stage-counts?reported_from=yesterday").status_code, 400)


@contextmanager
def _nothing():
    yield
