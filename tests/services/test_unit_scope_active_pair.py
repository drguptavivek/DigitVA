"""Unit-grant analytics and COD counts stop at a deactivated pair (digitva-26pg).

A data_manager (or In-charge) unit grant reaches the submissions routed into
its subtree, but -- exactly as the grid (``_dm_visible_forms_condition``,
authz ``scope_filter``) -- only while the form's (project, site) pair in
``va_project_sites`` is active. The analytics MV filter
(``_mv_scope_filter``) and the COD bucket report
(``_cod_bucket_aggregate_base_subquery``) apply the same ``authz.active_pair``
rule to the unit branch. Policy: docs/policy/access-control-model.md.

Fixture: the coding-scope tree project; PHC A holds one submission on the
active CS01 pair and one on the deactivated CS09 pair.
"""
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    MasCodBucketScheme,
    MasCodBucketSchemeAgeBand,
    VaFinalAssessments,
    VaStatuses,
    VaSubmissions,
)
from app.services.authz import subtree_select
from app.services.cod_bucket_mapping_service import (
    AGE_SCOPE_ADULT_OVER5Y,
    _cod_bucket_aggregate_base_subquery,
)
from app.services.submission_analytics_mv import (
    COD_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    _core_table_with_org_unit,
    _mv_scope_filter,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
    refresh_submission_analytics_mv,
)
from tests.base import BaseTestCase
from tests.test_unit_scoped_dm_tester import UnitScopeFixture

ACTIVE_SID = "csc-pair-active"
INACTIVE_SID = "csc-pair-inactive"
SIDS = (ACTIVE_SID, INACTIVE_SID)
SCHEME_CODE = "TEST_UNIT_ACTIVE_PAIR"
_MVS = (COD_MV_NAME, DEMOGRAPHICS_MV_NAME, CORE_MV_NAME, "va_submission_analytics_mv")


class UnitScopeActivePairTests(UnitScopeFixture, BaseTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for mv in _MVS:
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
        db.session.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
        db.session.execute(sa.text(build_submission_cod_detail_mv_sql(include_icd11=True)))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        try:
            for mv in _MVS:
                db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
            db.session.commit()
        finally:
            super().tearDownClass()

    def setUp(self):
        super().setUp()
        _, _, _, self.phc_a, _ = self._tree()
        self._inactive_pair_form()
        self._coded(ACTIVE_SID, self.FORM_ID)
        self._coded(INACTIVE_SID, self.INACTIVE_PAIR_FORM_ID)
        refresh_submission_analytics_mv(concurrently=False)

    def _coded(self, sid, form_id):
        """A submission in PHC A on *form_id* with a coder final COD (adult)."""
        self._sub(sid, unit=self.phc_a, form_id=form_id)
        submission = db.session.get(VaSubmissions, sid)
        submission.va_deceased_age_normalized_years = Decimal("42")
        submission.va_deceased_age_normalized_days = Decimal("42") * Decimal("365.25")
        db.session.add(VaFinalAssessments(
            va_sid=sid, va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21-Acute myocardial infarction",
            va_finassess_status=VaStatuses.active,
        ))
        db.session.commit()

    def _unit_subtree(self):
        # As production passes it (DmGrantScope.unit_subtree): unexecuted.
        return subtree_select([self.phc_a.org_unit_id])

    # -- analytics MV --------------------------------------------------------

    def _mv_sids(self, scoped):
        core = _core_table_with_org_unit()
        stmt = sa.select(core.c.va_sid).where(core.c.va_sid.in_(SIDS))
        if scoped:
            stmt = stmt.where(
                _mv_scope_filter(core, [], set(), scope_unit_ids=self._unit_subtree())
            )
        return set(db.session.scalars(stmt))

    def test_mv_unit_scope_skips_a_subtree_submission_on_a_deactivated_pair(self):
        self.assertEqual(self._mv_sids(scoped=False), set(SIDS))
        self.assertEqual(self._mv_sids(scoped=True), {ACTIVE_SID})

    # -- COD buckets ---------------------------------------------------------

    def _seed_scheme(self):
        """An active scheme whose adult band covers the fixture's age 42."""
        scheme = MasCodBucketScheme(
            scheme_code=SCHEME_CODE, scheme_name="Unit active pair",
            mapping_version=1, is_active=True,
        )
        db.session.add(scheme)
        db.session.flush()
        db.session.add(MasCodBucketSchemeAgeBand(
            scheme_id=scheme.scheme_id, age_scope=AGE_SCOPE_ADULT_OVER5Y,
            age_label="Adult / Over 5 Years", min_age_value=5, min_age_unit="years",
            max_age_value=120, max_age_unit="years", level_count=2, sort_order=1,
            is_active=True,
        ))
        db.session.commit()

    def _cod_sids(self, **scope):
        _, base = _cod_bucket_aggregate_base_subquery(scheme_code=SCHEME_CODE, **scope)
        return set(db.session.scalars(
            sa.select(base.c.va_sid).where(base.c.va_sid.in_(SIDS))
        ))

    def test_cod_unit_scope_skips_a_subtree_submission_on_a_deactivated_pair(self):
        self._seed_scheme()
        self.assertEqual(self._cod_sids(), set(SIDS))
        self.assertEqual(
            self._cod_sids(
                allowed_project_site_pairs=set(),
                allowed_org_unit_ids={self.phc_a.org_unit_id},
            ),
            {ACTIVE_SID},
        )
