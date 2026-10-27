"""Outcome, equity, coverage and critical-path KPIs (digitva-r5s0 step 2, groups f and g).

docs/policy/kpis.md: O-UNK, D-QG-09, EQ-01, EQ-02, AD-FCOD, AD-COV, D-WF-02
and the "Critical-path view". The compute functions are called directly, as
MCP will; the training exclusion goes through the route, since training is
dropped when the scope is resolved. Each assertion of an absence is preceded
by the subject's presence.

Fixture (setUpClass, the MVs are built over it once):

* OUT01, ODK only, tree D1 (> B1, B2), D2, D3, site OU01:
  B1 5 female / 20 male, 3 male finals (I21);
  B2 15 female / 10 male / 3 unknown sex, one female final with no authority row;
  D2 15 female / 15 male, 30 finals: 22 R54 (unknown section), 8 I21; 20 of
  them reviewed: 2 reviewer R54 on a coder I21 (disagree), 1 reviewer I22 on
  a coder I21 (same bucket, agree);
  D3 4 female / 4 male, 2 of the males not codeable by the coder.
* REG01, death register (web intake ``both``), site RG01: 20 female reported
  (15 interviewed), 20 male (8 interviewed), 1 unknown, plus a duplicate and
  a cancelled row; 5 waiting registered cases are over 30 days old.
* TRK01, the training project: 10 female cases.
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaFinalCodAuthority,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
)
from app.models.va_final_assessments import VaFinalAssessments
from app.models.va_reviewer_final_assessments import VaReviewerFinalAssessments
from app.routes.api.dm_kpi.dm_kpi_critical_path import compute_dwf02
from app.routes.api.dm_kpi.dm_kpi_outcomes import (
    compute_adcov,
    compute_adfcod,
    compute_dqg09,
    compute_eq01,
    compute_eq02,
    compute_ounk,
)
from app.routes.api.dm_kpi.dm_kpi_scope import DmScope
from app.services.submission_analytics_mv import (
    COD_SNAPSHOT_MV_NAME,
    CORE_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_cod_snapshot_mv_sql,
)
from tests.base import BaseTestCase

ODK, REG, TRAIN, PATH = "OUT01", "REG01", "TRK01", "CPT01"
SITES = {ODK: "OU01", REG: "RG01", TRAIN: "TK01", PATH: "CP01"}


class DmKpiOutcomesTests(BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls.forms = {}
        for project_id, site_id in SITES.items():
            for model in (VaResearchProjects, VaProjectMaster):
                db.session.add(model(
                    project_id=project_id, project_code=project_id,
                    project_name=project_id, project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now,
                ))
            db.session.flush()
            db.session.add(VaSiteMaster(
                site_id=site_id, site_abbr=site_id, site_name=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
            db.session.add(VaSites(
                site_id=site_id, project_id=project_id, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
            db.session.flush()
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
            cls.forms[project_id] = f"{project_id}{site_id}01"
            db.session.add(VaForms(
                form_id=cls.forms[project_id], project_id=project_id, site_id=site_id,
                odk_form_id=f"OUT_{project_id}", odk_project_id="77", form_type="WHO VA 2022",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
        db.session.get(VaProjectMaster, REG).web_intake_mode = "both"
        db.session.flush()

        cls.units = {}
        for project_id, codes in ((ODK, ("D1", "D1.B1", "D1.B2", "D2", "D3")), (PATH, ("P1", "P2", "P3"))):
            level = MasOrgLevel(project_id=project_id, level_code="L1", level_name="District", depth=1)
            db.session.add(level)
            db.session.flush()
            for code in codes:
                parent = cls.units.get((project_id, code.rsplit(".", 1)[0])) if "." in code else None
                unit = MasOrgUnit(
                    project_id=project_id, org_level_id=level.org_level_id,
                    parent_org_unit_id=parent.org_unit_id if parent else None,
                    unit_code=code.split(".")[-1], unit_name=f"Unit {code}", path=code,
                    created_at=now, updated_at=now,
                )
                db.session.add(unit)
                db.session.flush()
                cls.units[(project_id, code)] = unit

        cls._seed_buckets()
        cls.coder = cls._make_user(f"out.coder.{uuid.uuid4().hex[:8]}@test.local", "OutCoder123")
        cls.reviewer = cls._make_user(f"out.reviewer.{uuid.uuid4().hex[:8]}@test.local", "OutRev123")

        def cases(unit, sex, count, **kw):
            return [cls._submission(ODK, unit, sex, **kw) for _ in range(count)]

        b1_male = cases("D1.B1", "male", 20)
        cases("D1.B1", "female", 5)
        cases("D1.B2", "male", 10)
        cases("D1.B2", "Unknown", 2)
        cases("D1.B2", "undetermined", 1)
        b2_female = cases("D1.B2", "Female", 15)
        d2 = cases("D2", "female", 15) + cases("D2", "male", 15)
        cases("D3", "female", 4)
        cases("D3", "male", 2)
        cases("D3", "male", 2, state="not_codeable_by_coder")
        for sid in b1_male[:3]:
            cls._final(sid, "I21")
        cls._final(b2_female[0], "I21", authority=False)
        for i, sid in enumerate(d2):
            cls._final(sid, "R54" if i < 22 else "I21")
        # Reviewed: d2[22:] are coder I21; 2 reviewer R54 (disagree), 1 I22 (agree).
        for i, sid in enumerate(d2[10:30]):
            coder_cod = "R54" if i < 12 else "I21"
            reviewer_cod = {12: "R54", 13: "R54", 14: "I22"}.get(i, coder_cod)
            db.session.add(VaReviewerFinalAssessments(
                va_sid=sid, va_rfinassess_by=cls.reviewer.user_id, va_conclusive_cod=reviewer_cod,
                va_rfinassess_status=VaStatuses.active,
            ))

        for sex, reported, interviewed in (("female", 20, 15), ("male", 20, 8), ("unknown", 1, 0)):
            for i in range(reported):
                sid = cls._submission(REG, None, sex) if i < interviewed else None
                old = sex == "female" and i >= reported - 5
                cls._register(sex, sid, created_at=now - timedelta(days=40 if old else 2))
        cls._register("female", None, status="duplicate")
        cls._register("male", None, status="cancelled")
        for _ in range(10):
            cls._submission(TRAIN, None, "female")
        db.session.flush()

        for mv in (COD_SNAPSHOT_MV_NAME, CORE_MV_NAME):
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
        db.session.execute(sa.text(build_submission_cod_snapshot_mv_sql(icd11_buckets=True)))
        db.session.commit()

    # -- fixtures ----------------------------------------------------------

    @classmethod
    def _seed_buckets(cls):
        scheme = MasCodBucketScheme(
            scheme_code="WHO_2022_VA_2026", scheme_name="WHO 2026", mapping_version=1, is_active=True,
        )
        db.session.add(scheme)
        db.session.flush()
        for section, leaf, codes in (
            ("Cause of death unknown", "Senility", ("R54",)),
            ("Diseases of the circulatory system", "Acute myocardial infarction", ("I21", "I22")),
        ):
            parent = MasCodBucketNode(
                scheme_id=scheme.scheme_id, node_type="category", node_code=section[:20],
                node_label=section, sort_order=1,
            )
            child = MasCodBucketNode(
                scheme_id=scheme.scheme_id, node_type="field", parent=parent,
                node_code=leaf[:20], node_label=leaf, sort_order=1,
            )
            db.session.add_all([parent, child])
            db.session.flush()
            for code in codes:
                db.session.add(MapIcdCodBucket(
                    scheme_id=scheme.scheme_id, icd_code=code, node_id=child.node_id, is_active=True,
                ))
        db.session.flush()

    @classmethod
    def _submission(cls, project_id, unit_code, sex, *, state=None, events=()):
        sid = f"uuid:out-{uuid.uuid4()}"
        now = datetime.now(UTC)
        unit = cls.units.get((project_id, unit_code))
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=cls.forms[project_id], va_submission_date=now - timedelta(days=3),
            va_odk_updatedat=now, va_data_collector="out", va_odk_reviewstate="approved",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes",
            va_narration_language="English", va_deceased_age=50, va_deceased_gender=sex,
            va_summary=[], va_catcount={}, va_category_list=[],
            org_unit_id=unit.org_unit_id if unit else None,
            org_unit_resolution="form_field" if unit else None,
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state=state or "ready_for_coding", workflow_reason="test",
            workflow_updated_by_role="vasystem",
        ))
        for transition, previous, current, at, reason in events:
            db.session.add(VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id=transition, previous_state=previous,
                current_state=current, event_created_at=at, transition_reason=reason,
            ))
        return sid

    @classmethod
    def _final(cls, sid, cod, *, authority=True):
        final = VaFinalAssessments(
            va_sid=sid, va_finassess_by=cls.coder.user_id, va_conclusive_cod=cod,
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(final)
        db.session.flush()
        db.session.execute(sa.update(VaSubmissionWorkflow).where(
            VaSubmissionWorkflow.va_sid == sid
        ).values(workflow_state="coder_finalized"))
        if authority:
            db.session.add(VaFinalCodAuthority(
                va_sid=sid, authoritative_final_assessment_id=final.va_finassess_id,
            ))

    @classmethod
    def _register(cls, sex, sid, *, status=None, created_at=None):
        number = 880000 + db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister))
        db.session.add(VaDeathRegister(
            project_id=REG, site_id=SITES[REG], death_number=number, unique_id=f"RG01-{number}",
            va_sid=sid, registered_by=cls.base_admin_user.user_id, source="register",
            status=status or ("submitted" if sid else "registered"),
            deceased_name="Case", deceased_sex=sex, date_of_death=datetime.now(UTC).date(),
            created_at=created_at or datetime.now(UTC),
        ))
        db.session.flush()

    def _scope(self, *projects, unit=None):
        if unit:
            return DmScope(pairs=[], unit_ids=[str(self.units[(ODK, unit)].org_unit_id)],
                           unit_project_ids=(ODK,))
        return DmScope(pairs=sorted((p, SITES[p]) for p in projects), unit_ids=[],
                       grant_project_ids=tuple(projects))

    # -- O-UNK ---------------------------------------------------------------

    def test_unknown_cause_share_counts_authoritative_finals_in_the_unknown_section(self):
        result = compute_ounk(self._scope(ODK))
        # 33 authoritative finals (the final with no authority row is out); 22 R54.
        self.assertEqual((result["finals"], result["unknown"]), (33, 22))
        self.assertEqual(result["rate"], 66.7)

    def test_unknown_cause_icd_breakdown_names_senility(self):
        result = compute_ounk(self._scope(ODK), by="icd")
        self.assertFalse(result["hidden"])
        self.assertEqual(result["rows"], [
            {"label": "R54", "coded_count": 22, "suppressed": False, "percent": 100.0},
        ])

    def test_rates_are_null_under_twenty(self):
        b1 = compute_ounk(self._scope(unit="D1"))
        self.assertEqual(b1["finals"], 3)  # the subject is there
        self.assertIsNone(b1["rate"])
        self.assertTrue(compute_ounk(self._scope(unit="D1"), by="icd")["hidden"])
        dqg = compute_dqg09(self._scope(unit="D1"))
        self.assertEqual(dqg["reviewed"], 0)
        self.assertIsNone(dqg["rate"])

    # -- D-QG-09 -------------------------------------------------------------

    def test_disagreement_compares_who_2026_buckets(self):
        result = compute_dqg09(self._scope(ODK))
        # I21 against I22 is one bucket, so agrees; the two I21 against R54 differ.
        self.assertEqual(result, {"reviewed": 20, "disagreements": 2, "rate": 10.0})

    # -- EQ-01 ---------------------------------------------------------------

    def test_female_share_excludes_unknown_sex_but_counts_it(self):
        result = compute_eq01(self._scope(ODK))
        self.assertEqual((result["female"], result["male"], result["unknown"]), (39, 49, 3))
        self.assertEqual(result["share"], round(100 * 39 / 88, 1))
        units = {u["unit_name"]: u for u in result["units"]}
        # D1 is B1 + B2: 20 female of 50 known, against D2's 50%.
        self.assertEqual((units["Unit D1"]["share"], units["Unit D1"]["unknown"]), (40.0, 3))
        self.assertEqual(units["Unit D1"]["peer_median"], 50.0)
        self.assertEqual(units["Unit D1"]["gap_pp"], -10.0)
        self.assertEqual(units["Unit D2"]["gap_pp"], 10.0)
        # D3 has 8 known cases: counts only, and no part in the others' median.
        self.assertEqual(units["Unit D3"]["female"], 4)
        self.assertIsNone(units["Unit D3"]["share"])
        self.assertIsNone(units["Unit D3"]["gap_pp"])

    def test_peers_stay_inside_the_grant(self):
        units = {u["unit_name"]: u for u in compute_eq01(self._scope(unit="D1"))["units"]}
        self.assertEqual(units["Unit D1.B1"]["share"], 20.0)
        self.assertEqual(units["Unit D1.B2"]["share"], 60.0)
        self.assertEqual(units["Unit D1.B1"]["gap_pp"], -40.0)
        self.assertNotIn("Unit D2", units)
        self.assertNotIn("Unit D1", units)

    # -- AD-FCOD / EQ-02 -----------------------------------------------------

    def test_final_cause_coverage_over_codeable_cases(self):
        result = compute_adfcod(self._scope(ODK))
        # 91 cases, 2 not codeable by the coder; 33 finals with authority.
        self.assertEqual(result, {"codeable": 89, "final": 33, "rate": round(100 * 33 / 89, 1)})

    def test_female_male_final_cause_gap(self):
        result = compute_eq02(self._scope(ODK))
        rows = {r["sex"]: r for r in result["rows"]}
        self.assertEqual((rows["female"]["codeable"], rows["female"]["final"]), (39, 15))
        self.assertEqual((rows["male"]["codeable"], rows["male"]["final"]), (47, 18))
        self.assertEqual(rows["unknown"]["codeable"], 3)
        self.assertEqual(result["gap_pp"], round(round(1500 / 39, 1) - round(1800 / 47, 1), 1))
        self.assertIsNone(result["register"])

    def test_register_half_of_the_gap_by_deceased_sex(self):
        register = compute_eq02(self._scope(REG))["register"]
        rows = {r["sex"]: r for r in register["rows"]}
        self.assertEqual((rows["female"]["reported"], rows["female"]["interviewed"]), (20, 15))
        self.assertEqual(rows["unknown"]["reported"], 1)
        self.assertEqual(register["gap_pp"], 35.0)

    # -- AD-COV --------------------------------------------------------------

    def test_register_coverage_and_the_wait_over_thirty_days(self):
        result = compute_adcov(self._scope(REG))
        self.assertTrue(result["applicable"])
        # Duplicate and cancelled rows are not reported deaths.
        self.assertEqual((result["deaths_reported"], result["interviewed"]), (41, 23))
        self.assertEqual(result["rate"], round(100 * 23 / 41, 1))
        self.assertEqual(result["pending_over_30_days"], 5)

    def test_register_coverage_is_not_applicable_for_odk_only_projects(self):
        self.assertTrue(compute_adcov(self._scope(ODK, REG))["applicable"])
        self.assertEqual(compute_adcov(self._scope(ODK)), {"applicable": False})

    # -- training ------------------------------------------------------------

    def test_training_is_excluded(self):
        both = compute_eq01(self._scope(ODK, TRAIN))
        self.assertEqual(both["female"], 49)  # the training cases exist
        dm = self._make_user(f"out.dm.{uuid.uuid4().hex[:8]}@test.local", "OutDm12345")
        for project_id in (ODK, TRAIN):
            db.session.add(VaUserAccessGrants(
                user_id=dm.user_id, role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project, project_id=project_id,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()
        self._login(str(dm.user_id))
        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=TRAIN):
            response = self.client.get("/api/v1/analytics/dm-kpi/outcomes/female-share")
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["female"], 39)

    # -- D-WF-02 critical path -----------------------------------------------

    def _path_case(self, unit, ready_hours, *, screening_hours=None, demo=False, sent_back=False):
        t = datetime.now(UTC) - timedelta(days=5)
        events = []
        if screening_hours is not None:
            events.append(("sync_new_payload_routed", None, "screening_pending", t, None))
            t += timedelta(hours=screening_hours)
            events.append(("screening_passed", "screening_pending", "smartva_pending", t, None))
        else:
            events.append(("sync_new_payload_routed", None, "smartva_pending", t, None))
        if demo:
            events.append(("demo_started", "smartva_pending", "smartva_pending", t, None))
        t += timedelta(minutes=30)
        events.append(("smartva_completed", "smartva_pending", "ready_for_coding", t, None))
        t += timedelta(hours=ready_hours)
        events.append(("coding_started", "ready_for_coding", "coding_in_progress", t, None))
        t += timedelta(hours=1)
        events.append(("coder_finalized", "coding_in_progress", "coder_finalized", t, None))
        if sent_back:
            t += timedelta(hours=1)
            events.append(("send_back", "coder_finalized", "finalized_upstream_changed", t,
                           "sent_back_for_revision"))
            t += timedelta(hours=6)
            events.append(("interviewer_revision", "finalized_upstream_changed", "smartva_pending", t, None))
        self._submission(PATH, unit, "female", state="coder_finalized", events=events)

    def _path_scope(self):
        return DmScope(pairs=[(PATH, SITES[PATH])], unit_ids=[], grant_project_ids=(PATH,))

    def test_critical_path_dominant_stage_and_bottleneck_against_peers(self):
        for unit, ready in (("P1", 2), ("P2", 2), ("P3", 10)):
            for _ in range(20):
                self._path_case(unit, ready)
        # Five long screenings in P1: under 20, so neither dominant nor a bottleneck.
        for _ in range(5):
            self._path_case("P1", 2, screening_hours=100)
        self._path_case("P1", 500, demo=True)
        self._path_case("P2", 2, sent_back=True)
        db.session.commit()

        result = compute_dwf02(self._path_scope(), 30)
        stages = {s["stage"]: s for s in result["stages"]}
        self.assertEqual(stages["screening_pending"]["p50_hours"], 100.0)  # present, n 5
        self.assertEqual(stages["ready_for_coding"]["n"], 66)  # the demo case is out
        self.assertEqual(stages["sent_back_for_revision"]["n"], 1)
        self.assertEqual(stages["sent_back_for_revision"]["p50_hours"], 6.0)
        self.assertEqual(result["dominant"], "ready_for_coding")
        self.assertNotIn("median_share", stages["screening_pending"])

        units = {u["unit_name"]: u for u in result["units"]}
        self.assertEqual(units["Unit P3"]["bottleneck"], {"stage": "ready_for_coding", "gap_hours": 8.0})
        p1 = {s["stage"]: s for s in units["Unit P1"]["stages"]}
        self.assertEqual(p1["screening_pending"]["n"], 5)
        self.assertIsNone(p1["screening_pending"]["gap_hours"])
        self.assertIsNone(units["Unit P1"]["bottleneck"])
        self.assertEqual(result["bottleneck"]["unit_name"], "Unit P3")
        self.assertEqual(result["end_segments"]["death_to_interview_n"], 0)

    def test_routes_serve_each_kpi_and_refuse_an_unknown_by(self):
        dm = self._make_user(f"out.dm2.{uuid.uuid4().hex[:8]}@test.local", "OutDm12345")
        db.session.add(VaUserAccessGrants(
            user_id=dm.user_id, role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project, project_id=ODK, grant_status=VaStatuses.active,
        ))
        db.session.commit()
        self._login(str(dm.user_id))
        base = "/api/v1/analytics/dm-kpi"
        for path in ("outcomes/unknown-cause?by=icd", "outcomes/disagreement", "outcomes/female-final-gap",
                     "outcomes/final-cause-coverage?by=sex", "outcomes/register-coverage",
                     "critical-path/?days=7"):
            response = self.client.get(f"{base}/{path}")
            self.assertEqual(response.status_code, 200, path)
        self.assertEqual(self.client.get(f"{base}/outcomes/register-coverage").get_json(), {"applicable": False})
        self.assertEqual(self.client.get(f"{base}/outcomes/unknown-cause?by=sex").status_code, 400)
        self.assertEqual(self.client.get(f"{base}/outcomes/disagreement?by=unit").status_code, 400)
        self.assertEqual(self.client.get(f"{base}/critical-path/?days=0").status_code, 400)
        # The old coders path is the same bucket comparison, not the COD text one.
        self.assertEqual(
            self.client.get(f"{base}/coders/disagreement").get_json(),
            self.client.get(f"{base}/outcomes/disagreement").get_json(),
        )
