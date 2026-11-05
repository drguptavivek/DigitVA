"""map_submission_cod_bucket equals the live COD bucket derivation.

Every read path is run twice over one fixture, once forced live (layer (a) as
a subquery) and once from the built table, and the two must be identical.
The fixture covers the alias, unmapped, inactive-mapping and inactive-node
paths on ICD-10 and ICD-11, an age-band gap and overlap, two schemes with
different bands, a confirmed duplicate, a submission missing in ODK and a
site whose project-site pair is inactive.

Run (inside Docker)::

    docker compose exec -T -e TEST_DATABASE_URL=... minerva_app_service \\
        uv run --no-sync python -m pytest tests/services/test_cod_bucket_materialization.py -q
"""
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MapIcd10LegacyReportingAlias,
    MapIcdCodBucket,
    MapSubmissionCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasCodBucketSchemeAgeBand,
    MasIcd11Mms,
    MasIcd1020192,
    MasOrgLevel,
    MasOrgUnit,
    VaDeathRegister,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.services import cod_bucket_mapping_service as service
from app.services.cod_bucket_materialization import rebuild_all_active, rebuild_scheme
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.odk_retirement_service import MISSING_IN_ODK
from app.services.submission_analytics_mv import (
    COD_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
    refresh_submission_analytics_mv,
)
from tests.base import BaseTestCase

PROJECT_ID = "CODMT1"
SITE_A = "CMA1"
SITE_B = "CMB1"
FORM_A = f"{PROJECT_ID}{SITE_A}01"
FORM_B = f"{PROJECT_ID}{SITE_B}01"
SCHEME_A = "TEST_CODMAT_A"
SCHEME_B = "TEST_CODMAT_B"


def _live_source(scheme):
    return service._cod_bucket_resolved_rows(scheme).subquery("cod_bucket_resolved")


class CodBucketMaterializationTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        for model in (VaResearchProjects, VaProjectMaster):
            db.session.add(model(
                project_id=PROJECT_ID, project_code=PROJECT_ID, project_name="COD materialization",
                project_nickname="CodMat", project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now,
            ))
        db.session.flush()
        for site_id, status in ((SITE_A, VaStatuses.active), (SITE_B, VaStatuses.deactive)):
            db.session.add(VaSites(
                site_id=site_id, project_id=PROJECT_ID, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
            db.session.flush()
            db.session.add(VaProjectSites(
                project_site_id=uuid.uuid4(), project_id=PROJECT_ID, site_id=site_id,
                project_site_status=status, project_site_registered_at=now, project_site_updated_at=now,
            ))
        db.session.flush()
        for form_id, site_id in ((FORM_A, SITE_A), (FORM_B, SITE_B)):
            db.session.add(VaForms(
                form_id=form_id, project_id=PROJECT_ID, site_id=site_id,
                odk_form_id=f"CODMAT_{site_id}", odk_project_id="78", form_type="WHO VA 2022",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
        level = MasOrgLevel(project_id=PROJECT_ID, level_code="L1", level_name="District", depth=1)
        db.session.add(level)
        db.session.flush()
        cls.unit = MasOrgUnit(
            org_unit_id=uuid.uuid4(), project_id=PROJECT_ID, org_level_id=level.org_level_id,
            unit_code="U1", unit_name="Unit One", path="U1", is_active=True,
        )
        db.session.add(cls.unit)
        db.session.commit()
        cls.unit_id = cls.unit.org_unit_id

        for mv in (COD_MV_NAME, DEMOGRAPHICS_MV_NAME, CORE_MV_NAME, "va_submission_analytics_mv"):
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql()))
        db.session.execute(sa.text(f"CREATE UNIQUE INDEX ix_test_codmat_core ON {CORE_MV_NAME} (va_sid)"))
        db.session.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
        db.session.execute(sa.text(f"CREATE UNIQUE INDEX ix_test_codmat_demo ON {DEMOGRAPHICS_MV_NAME} (va_sid)"))
        db.session.execute(sa.text(build_submission_cod_detail_mv_sql(include_icd11=True)))
        db.session.execute(sa.text(f"CREATE UNIQUE INDEX ix_test_codmat_cod ON {COD_MV_NAME} (va_sid)"))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            for mv in (COD_MV_NAME, DEMOGRAPHICS_MV_NAME, CORE_MV_NAME, "va_submission_analytics_mv"):
                db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
            db.session.commit()
        finally:
            super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.now = datetime.now(timezone.utc)
        self.scheme_a = self._seed_scheme_a()
        self.scheme_b = self._seed_scheme_b()
        self._seed_catalogue()
        self._seed_submissions()
        db.session.commit()
        refresh_submission_analytics_mv(concurrently=False)

    # ------------------------------------------------------------------ fixture

    def _band(self, scheme, scope, label, lo, lo_unit, hi, hi_unit, sort_order):
        db.session.add(MasCodBucketSchemeAgeBand(
            scheme_id=scheme.scheme_id, age_scope=scope, age_label=label,
            min_age_value=lo, min_age_unit=lo_unit, max_age_value=hi, max_age_unit=hi_unit,
            level_count=2, sort_order=sort_order, is_active=True,
        ))

    def _node(self, scheme, scope, code, label, *, parent=None, node_type="field", sort_order=1, active=True):
        node = MasCodBucketNode(
            scheme_id=scheme.scheme_id, age_scope=scope, node_type=node_type, node_code=code,
            node_label=label, parent=parent, sort_order=sort_order, is_active=active,
        )
        db.session.add(node)
        db.session.flush()
        return node

    def _map(self, scheme, scope, code, node, *, classification="icd10", active=True):
        db.session.add(MapIcdCodBucket(
            scheme_id=scheme.scheme_id, age_scope=scope, icd_classification=classification,
            icd_code=code, node_id=node.node_id, is_active=active,
        ))

    def _seed_scheme_a(self):
        """Three scoped bands with an SRS-style gap (28 days to 1 month) and
        overlap (4 to 5 years); ICD-10 and native ICD-11 rows."""
        scheme = MasCodBucketScheme(
            scheme_code=SCHEME_A, scheme_name="CodMat A", mapping_version=1, is_active=True,
            icd11_method="native",
        )
        db.session.add(scheme)
        db.session.flush()
        self._band(scheme, "neonate", "Neonate", 0, "days", 28, "days", 1)
        self._band(scheme, "child_1_59m", "Child", 1, "months", 5, "years", 2)
        self._band(scheme, "adult_over5y", "Adult", 4, "years", 120, "years", 3)
        adult = "adult_over5y"
        category = self._node(scheme, adult, "all", "All causes", node_type="category")
        self.heart = self._node(scheme, adult, "heart", "Heart", parent=category, sort_order=1)
        self.dengue = self._node(scheme, adult, "dengue", "Dengue", parent=category, sort_order=2)
        sepsis = self._node(scheme, adult, "sepsis", "Sepsis", parent=category, sort_order=3)
        far = self._node(scheme, adult, "far", "Far ancestor", parent=category, sort_order=4)
        dormant = self._node(scheme, adult, "dormant", "Dormant", parent=category, sort_order=5, active=False)
        child_heart = self._node(scheme, "child_1_59m", "child_heart", "Child heart")
        self._map(scheme, adult, "I21", self.heart)
        self._map(scheme, adult, "A97", self.dengue)
        self._map(scheme, adult, "K35", self.heart, active=False)
        # ICD-10 path: an inactive node still matches (the live rule).
        self._map(scheme, adult, "E11", dormant)
        self._map(scheme, "child_1_59m", "I21", child_heart)
        self._map(scheme, adult, "1G40", sepsis, classification="icd11")
        self._map(scheme, adult, "1G00", far, classification="icd11")
        # ICD-11 path: an inactive node is skipped and the walk goes on up.
        self._map(scheme, adult, "1G41", dormant, classification="icd11")
        db.session.flush()
        return scheme

    def _seed_scheme_b(self):
        """One all-ages band and ICD-10 rows only: detail sections, no walk."""
        scheme = MasCodBucketScheme(
            scheme_code=SCHEME_B, scheme_name="CodMat B", mapping_version=1, is_active=True,
        )
        db.session.add(scheme)
        db.session.flush()
        self._band(scheme, None, "All ages", 0, "days", 120, "years", 1)
        category = self._node(scheme, None, "all", "All causes", node_type="category")
        everything = self._node(scheme, None, "everything", "Everything", parent=category)
        self._map(scheme, None, "I21", everything)
        self._map(scheme, None, "A97", everything)
        db.session.flush()
        return scheme

    def _seed_catalogue(self):
        if db.session.get(MasIcd1020192, "A97") is None:
            db.session.add(MasIcd1020192(
                code="A97", title="Dengue", node_type="category", semantic_level="three_character",
                sort_order=1, parent_code=None, chapter_code="I", chapter_title="Infectious",
                block_code="A92-A99", block_title="Viral fevers", three_character_code="A97",
                three_character_title="Dengue", has_children=False, is_leaf=True,
                is_three_character_code=True, is_detailed_code=False, is_coding_selectable=True,
                sex_selectable="both", age_group_selectable="all", policy_status="allowed",
                source_version="2019-test", source_path="tests",
            ))
            db.session.flush()
        if db.session.get(MapIcd10LegacyReportingAlias, "A90") is None:
            db.session.add(MapIcd10LegacyReportingAlias(legacy_code="A90", reporting_code="A97"))
        base = "http://id.who.int/icd/release/11/mms/test-codmat"
        for code, uri, parent_uri in (
            ("1G00", f"{base}/1g00", None),
            (None, f"{base}/block", f"{base}/1g00"),
            ("1G40", f"{base}/1g40", f"{base}/block"),
            ("1G40.0", f"{base}/1g40-0", f"{base}/1g40"),
            ("1G41", f"{base}/1g41", f"{base}/block"),
            ("1G41.0", f"{base}/1g41-0", f"{base}/1g41"),
        ):
            db.session.add(MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE, linearization_uri=uri, parent_linearization_uri=parent_uri,
                code=code, title=code or "Block", class_kind="category" if code else "block",
                source_version="test",
            ))

    def _submission(self, sid, icd, *, years=None, days=None, gender="male", form_id=FORM_A,
                    submitted_at=None, sync_issue_code=None, org_unit_id=None):
        submitted_at = submitted_at or self.now
        normalized_years = Decimal(str(years)) if years is not None else Decimal(days) / Decimal("365.25")
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=form_id, va_submission_date=submitted_at, va_odk_updatedat=submitted_at,
            va_data_collector="collector", va_odk_reviewstate="approved", va_instance_name=sid,
            va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes", va_narration_language="English",
            va_deceased_age=0, va_deceased_age_normalized_days=normalized_years * Decimal("365.25"),
            va_deceased_age_normalized_years=normalized_years, va_deceased_age_source="test",
            va_deceased_gender=gender, va_sync_issue_code=sync_issue_code, va_summary=[], va_catcount={},
            va_category_list=[], org_unit_id=org_unit_id,
            org_unit_resolution="form_field" if org_unit_id else None,
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(
            va_sid=sid, workflow_state="coder_finalized", workflow_reason="test",
            workflow_updated_by_role="vasystem",
        ))
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=self.base_coder_user.user_id, va_conclusive_cod=icd,
            va_finassess_status=VaStatuses.active, va_finassess_createdat=submitted_at,
            va_finassess_updatedat=submitted_at,
        ))

    def _case(self, sid, number, *, status, date_of_death):
        db.session.add(VaDeathRegister(
            project_id=PROJECT_ID, site_id=SITE_A, death_number=number, unique_id=f"CODMAT-{number}",
            deceased_name="Test Case", deceased_sex="male", date_of_death=date_of_death,
            registered_by=self.base_coder_user.user_id, status=status, va_sid=sid,
        ))

    def _seed_submissions(self):
        old = self.now - timedelta(days=800)
        self._submission("uuid:cm-i21", "I21 Acute MI", years=52)
        self._submission("uuid:cm-alias", "A90 Dengue fever", years=40, gender="Female")
        self._submission("uuid:cm-unmapped", "J18 Pneumonia", years=60, gender="unknown")
        self._submission("uuid:cm-inactive-map", "K35 Appendicitis", years=30, gender="female")
        self._submission("uuid:cm-inactive-node10", "E11 Diabetes", years=70, gender="")
        self._submission("uuid:cm-icd11-exact", "1G40 Sepsis", years=45)
        self._submission("uuid:cm-icd11-ancestor", "1G40.0 Child of sepsis", years=45, gender=" Male ")
        self._submission("uuid:cm-icd11-postcoord", "1G40.0&XN8Q/1G41 Post-coordinated", years=46)
        self._submission("uuid:cm-icd11-inactive-node", "1G41.0 Under a dormant node", years=50)
        self._submission("uuid:cm-overlap", "I21 Acute MI", years=4.5, gender="undetermined")
        self._submission("uuid:cm-gap", "I21 Acute MI", days=29)
        self._submission("uuid:cm-neonate", "I21 Acute MI", days=10)
        self._submission("uuid:cm-duplicate", "I21 Acute MI", years=52)
        self._case("uuid:cm-duplicate", 997001, status="duplicate", date_of_death=old.date())
        self._submission("uuid:cm-missing", "I21 Acute MI", years=52, sync_issue_code=MISSING_IN_ODK)
        self._submission("uuid:cm-site-b-unit", "I21 Acute MI", years=52, form_id=FORM_B,
                         org_unit_id=self.unit_id)
        self._submission("uuid:cm-site-a-unit", "A97 Dengue", years=33, org_unit_id=self.unit_id)
        self._submission("uuid:cm-dated", "I21 Acute MI", years=61, submitted_at=old)
        self._case("uuid:cm-dated", 997002, status="submitted",
                   date_of_death=(old - timedelta(days=400)).date())

    # ------------------------------------------------------------------ helpers

    FILTERS = {
        "none": {},
        "project": {"project_id": PROJECT_ID},
        "site": {"site_id": SITE_A},
        "form": {"form_id": FORM_A},
        "male": {"gender": "male"},
        "female": {"gender": "female"},
        "unknown": {"gender": "unknown"},
        "dates": "dates",
        "unit_subtree": "units",
        "pair_scope": {"allowed_project_site_pairs": {(PROJECT_ID, SITE_A)}},
    }

    def _filters(self):
        for name, value in self.FILTERS.items():
            if value == "dates":
                value = {"submission_date_from": (self.now - timedelta(days=1)).date(),
                         "submission_date_to": self.now.date() + timedelta(days=1)}
            elif value == "units":
                value = {"allowed_project_site_pairs": set(), "allowed_org_unit_ids": {self.unit_id}}
            yield name, value

    def _reports(self, scheme_code, filters):
        out = {}
        for collapse in (True, False):
            out[f"aggregates_{collapse}"] = service.aggregate_coded_submissions_by_bucket(
                scheme_code=scheme_code, collapse_scope=collapse, **filters)
            out[f"unmatched_{collapse}"] = service.summarize_unmatched_coded_submissions_by_bucket(
                scheme_code=scheme_code, collapse_scope=collapse, **filters)
            out[f"unmatched_icds_{collapse}"] = service.list_unmatched_coded_submission_icds_by_bucket(
                scheme_code=scheme_code, collapse_scope=collapse, **filters)
        out["breakdowns"] = service.summarize_cod_bucket_reporting_breakdowns(scheme_code=scheme_code, **filters)
        out["csv"] = service.export_cod_bucket_reporting_csv(scheme_code=scheme_code, **filters)
        scope = {k: v for k, v in filters.items() if k in ("allowed_project_site_pairs", "allowed_org_unit_ids")}
        out["causes"] = service.count_coded_submissions_by_cause(
            scheme_code=scheme_code, project_id=PROJECT_ID,
            death_date_from=(self.now - timedelta(days=1000)).date(), **scope)
        return json.loads(json.dumps(out, default=str))

    def _all_reports(self):
        return {
            (scheme_code, name): self._reports(scheme_code, filters)
            for scheme_code in (SCHEME_A, SCHEME_B)
            for name, filters in self._filters()
        }

    def _table_rows(self, scheme):
        return {
            (row.va_sid, row.age_scope): row
            for row in db.session.scalars(
                sa.select(MapSubmissionCodBucket).where(MapSubmissionCodBucket.scheme_id == scheme.scheme_id)
            )
        }

    # ------------------------------------------------------------------ tests

    def test_an_edit_stops_serving_rows_built_before_it(self):
        """The stamp is cleared in the edit's own transaction, so reads fall
        back to live derivation until the rebuild lands."""
        from app.services.cod_bucket_materialization import rebuild_scheme

        rebuild_scheme(self.scheme_a.scheme_id)
        db.session.refresh(self.scheme_a)
        self.assertIsNotNone(self.scheme_a.reporting_rows_built_at)
        band = db.session.scalars(
            sa.select(MasCodBucketSchemeAgeBand).where(
                MasCodBucketSchemeAgeBand.scheme_id == self.scheme_a.scheme_id
            )
        ).first()
        self.assertIsNotNone(band)
        band.sort_order = (band.sort_order or 0) + 1
        db.session.flush()
        db.session.refresh(self.scheme_a)
        self.assertIsNone(self.scheme_a.reporting_rows_built_at)
        db.session.rollback()
        db.session.refresh(self.scheme_a)
        self.assertIsNotNone(self.scheme_a.reporting_rows_built_at)

    def test_table_reports_equal_live_reports(self):
        with patch.object(service, "_reporting_source", _live_source):
            live = self._all_reports()
        rebuild_all_active()
        db.session.expire_all()
        self.assertIsNotNone(db.session.get(MasCodBucketScheme, self.scheme_a.scheme_id).reporting_rows_built_at)
        # Built: the reports must not touch the live derivation at all.
        with patch.object(service, "_cod_bucket_resolved_rows", side_effect=AssertionError("live read")):
            table = self._all_reports()

        unfiltered = live[(SCHEME_A, "none")]
        self.assertTrue(unfiltered["aggregates_True"])
        self.assertTrue(unfiltered["unmatched_True"])
        self.assertTrue(unfiltered["unmatched_icds_True"])
        self.assertGreater(unfiltered["breakdowns"]["matched_total"], 0)
        self.assertGreater(unfiltered["causes"][0], 0)
        self.assertGreater(len(unfiltered["csv"].splitlines()), 1)
        for name, _ in self._filters():
            self.assertTrue(live[(SCHEME_A, name)]["csv"].count("\n") > 1, name)
        for key in live:
            self.assertEqual(table[key], live[key], key)

    def test_rows_follow_the_live_predicates(self):
        rebuild_scheme(self.scheme_a.scheme_id)
        rows = self._table_rows(self.scheme_a)
        node = {key: row.node_id for key, row in rows.items()}
        adult = "adult_over5y"
        self.assertEqual(node[("uuid:cm-alias", adult)], self.dengue.node_id)
        self.assertEqual(rows[("uuid:cm-alias", adult)].reporting_icd, "A97")
        self.assertIsNone(node[("uuid:cm-unmapped", adult)])
        self.assertIsNone(node[("uuid:cm-inactive-map", adult)])
        # The asymmetry: ICD-10 keeps an inactive node, ICD-11 walks past it.
        dormant = db.session.scalar(sa.select(MasCodBucketNode.node_id).where(MasCodBucketNode.node_code == "dormant"))
        far = db.session.scalar(sa.select(MasCodBucketNode.node_id).where(
            MasCodBucketNode.node_code == "far", MasCodBucketNode.scheme_id == self.scheme_a.scheme_id))
        self.assertEqual(node[("uuid:cm-inactive-node10", adult)], dormant)
        self.assertEqual(node[("uuid:cm-icd11-inactive-node", adult)], far)
        self.assertEqual(rows[("uuid:cm-icd11-ancestor", adult)].reporting_icd, "1G40")
        self.assertEqual(rows[("uuid:cm-icd11-postcoord", adult)].final_icd, "1G40.0")
        # Overlap: two rows; gap: none; neonate: kept unmatched.
        self.assertIn(("uuid:cm-overlap", "child_1_59m"), rows)
        self.assertIn(("uuid:cm-overlap", adult), rows)
        self.assertNotIn("uuid:cm-gap", {sid for sid, _ in rows})
        self.assertIsNone(node[("uuid:cm-neonate", "neonate")])
        self.assertFalse(rows[("uuid:cm-duplicate", adult)].is_reportable)
        self.assertFalse(rows[("uuid:cm-missing", adult)].is_reportable)
        self.assertTrue(rows[("uuid:cm-i21", adult)].is_reportable)
        dated = rows[("uuid:cm-dated", adult)]
        self.assertLess(dated.event_date, dated.submission_date)
        # The all-ages scheme has the gap death and no ICD-11 match.
        rebuild_scheme(self.scheme_b.scheme_id)
        rows_b = self._table_rows(self.scheme_b)
        self.assertIn(("uuid:cm-gap", None), rows_b)
        self.assertIsNone(rows_b[("uuid:cm-icd11-exact", None)].node_id)

    def test_diff_sync_changes_only_differing_rows_and_rerun_is_idempotent(self):
        first = rebuild_scheme(self.scheme_a.scheme_id)
        self.assertGreater(first["inserted"], 0)
        before = {key: row.computed_at for key, row in self._table_rows(self.scheme_a).items()}
        again = rebuild_scheme(self.scheme_a.scheme_id)
        self.assertEqual((again["inserted"], again["updated"], again["deleted"]), (0, 0, 0))

        mapping = db.session.scalar(sa.select(MapIcdCodBucket).where(
            MapIcdCodBucket.scheme_id == self.scheme_a.scheme_id, MapIcdCodBucket.icd_code == "A97"))
        mapping.node_id = self.heart.node_id
        db.session.commit()
        changed = rebuild_scheme(self.scheme_a.scheme_id)
        self.assertEqual((changed["inserted"], changed["updated"], changed["deleted"]), (0, 2, 0))
        db.session.expire_all()
        after = self._table_rows(self.scheme_a)
        moved = {("uuid:cm-alias", "adult_over5y"), ("uuid:cm-site-a-unit", "adult_over5y")}
        for key, row in after.items():
            if key in moved:
                self.assertEqual(row.node_id, self.heart.node_id)
                self.assertGreaterEqual(row.computed_at, before[key])
            else:
                self.assertEqual(row.computed_at, before[key], key)

        mapping.is_active = False
        db.session.commit()
        self.assertEqual(rebuild_scheme(self.scheme_a.scheme_id)["updated"], 2)
        self.assertIsNone(self._table_rows(self.scheme_a)[("uuid:cm-alias", "adult_over5y")].node_id)

    def test_admin_edits_queue_a_rebuild_after_commit_only(self):
        with patch.dict(self.app.config, {"COD_BUCKET_REBUILD_ON_COMMIT": True}), \
                patch("app.tasks.sync_tasks.rebuild_cod_bucket_scheme_task.delay") as scheme_task, \
                patch("app.tasks.sync_tasks.rebuild_cod_bucket_rows_task.delay") as all_task:
            db.session.commit()
            scheme_task.reset_mock()
            all_task.reset_mock()

            mapping = db.session.scalar(sa.select(MapIcdCodBucket).where(
                MapIcdCodBucket.scheme_id == self.scheme_a.scheme_id, MapIcdCodBucket.icd_code == "I21",
                MapIcdCodBucket.age_scope == "adult_over5y"))
            mapping.node_id = self.dengue.node_id
            db.session.flush()
            # Flushed is not committed: nothing is queued yet.
            scheme_task.assert_not_called()
            db.session.commit()
            scheme_task.assert_called_once_with(str(self.scheme_a.scheme_id))
            all_task.assert_not_called()

            db.session.add(MapIcd10LegacyReportingAlias(legacy_code="A91", reporting_code="A97"))
            db.session.commit()
            all_task.assert_called_once_with()

        rebuild_scheme(self.scheme_a.scheme_id)
        row = self._table_rows(self.scheme_a)[("uuid:cm-i21", "adult_over5y")]
        self.assertEqual(row.node_id, self.dengue.node_id)

    def test_deactivating_a_scheme_removes_its_rows_and_stamp(self):
        rebuild_scheme(self.scheme_a.scheme_id)
        self.assertTrue(self._table_rows(self.scheme_a))
        scheme = db.session.get(MasCodBucketScheme, self.scheme_a.scheme_id)
        scheme.is_active = False
        db.session.commit()
        result = rebuild_scheme(self.scheme_a.scheme_id)
        self.assertGreater(result["deleted"], 0)
        self.assertEqual(self._table_rows(self.scheme_a), {})
        db.session.expire_all()
        self.assertIsNone(db.session.get(MasCodBucketScheme, self.scheme_a.scheme_id).reporting_rows_built_at)

    def test_inactive_scheme_is_refused_400_by_the_report_api(self):
        scheme = db.session.get(MasCodBucketScheme, self.scheme_b.scheme_id)
        scheme.is_active = False
        db.session.commit()
        self._login(str(self.base_admin_user.user_id))
        for path in ("aggregates", "export.csv"):
            response = self.client.get(f"/api/v1/cod-buckets/{path}?scheme_code={SCHEME_B}")
            self.assertEqual(response.status_code, 400, path)
            self.assertEqual(response.get_json()["code"], "unknown_scheme")

    def test_rebuild_takes_the_per_scheme_advisory_lock(self):
        """A rebuild waits for a holder of its scheme's lock: with a short
        lock_timeout it fails instead, and succeeds once the lock is free."""
        other = sa.create_engine(db.engine.url)
        try:
            with other.connect() as holder:
                holder.execute(
                    sa.text("SELECT pg_advisory_lock(hashtext(:name))"),
                    {"name": f"map_submission_cod_bucket:{self.scheme_a.scheme_id}"},
                )
                db.session.execute(sa.text("SET LOCAL lock_timeout = '200ms'"))
                with self.assertRaises(sa.exc.OperationalError):
                    rebuild_scheme(self.scheme_a.scheme_id)
                # Another scheme's lock is a different key.
                self.assertGreater(rebuild_scheme(self.scheme_b.scheme_id)["rows"], 0)
                holder.execute(sa.text("SELECT pg_advisory_unlock_all()"))
            self.assertGreater(rebuild_scheme(self.scheme_a.scheme_id)["rows"], 0)
        finally:
            other.dispose()

    def test_read_paths_issue_a_fixed_number_of_flat_statements(self):
        rebuild_all_active()
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        expected = {
            "aggregates": 3,
            "unmatched": 3,
            "unmatched_icds": 5,
            "breakdowns": 2,
            "csv": 4,
            "causes": 3,
        }
        calls = {
            "aggregates": lambda: service.aggregate_coded_submissions_by_bucket(
                scheme_code=SCHEME_A, collapse_scope=True),
            "unmatched": lambda: service.summarize_unmatched_coded_submissions_by_bucket(
                scheme_code=SCHEME_A, collapse_scope=True),
            "unmatched_icds": lambda: service.list_unmatched_coded_submission_icds_by_bucket(
                scheme_code=SCHEME_A, collapse_scope=True),
            "breakdowns": lambda: service.summarize_cod_bucket_reporting_breakdowns(scheme_code=SCHEME_A),
            "csv": lambda: service.export_cod_bucket_reporting_csv(scheme_code=SCHEME_A),
            "causes": lambda: service.count_coded_submissions_by_cause(
                scheme_code=SCHEME_A, project_id=PROJECT_ID),
        }
        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            counts = {}
            for name, call in calls.items():
                statements.clear()
                self.assertTrue(call(), name)
                counts[name] = len(statements)
                for statement in statements:
                    self.assertNotIn("RECURSIVE", statement.upper(), name)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(counts, expected)

    def test_collapsed_reports_answer_at_bucket_level_only(self):
        """The /aggregates route asks for collapse_scope=True: its rows carry
        no project, site or form and stay within one row per (age band,
        bucket node) for the main and detail sections, however many forms the
        scope spans."""
        rebuild_all_active()
        per_form = service.aggregate_coded_submissions_by_bucket(scheme_code=SCHEME_A)
        self.assertTrue(per_form)
        self.assertIn("form_id", per_form[0])
        rows = service.aggregate_coded_submissions_by_bucket(scheme_code=SCHEME_A, collapse_scope=True)
        self.assertTrue(rows)
        for row in rows:
            for key in ("project_id", "site_id", "form_id"):
                self.assertNotIn(key, row)
        bands = db.session.scalar(sa.select(sa.func.count()).select_from(MasCodBucketSchemeAgeBand)
                                  .where(MasCodBucketSchemeAgeBand.scheme_id == self.scheme_a.scheme_id))
        nodes = db.session.scalar(sa.select(sa.func.count()).select_from(MasCodBucketNode)
                                  .where(MasCodBucketNode.scheme_id == self.scheme_a.scheme_id))
        self.assertLessEqual(len(rows), 2 * bands * nodes)

