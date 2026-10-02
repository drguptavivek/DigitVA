"""Stage-0 shadow: the old helpers and the authz module agree (digitva-0wc, design 7).

On the shared fixtures, for coder, reviewer and data-manager viewing, the
checks the routes compose today and ``can`` / ``scope_filter`` give the
same answer for every submission, except where the design deliberately
changes behaviour. Those rows are listed in ``DELIBERATE`` with the audit
finding (.tasks/digitva-0wc-access-matrix-current.md) they close. Any other
disagreement fails.

Old compositions, as the routes call them today:
- coder pick (coder_workflow_service.allocate_pick_form):
  (has_va_form_access(coder) or is_coding_tester(form))
  and (tester_covers_submission or submission_within_org_scope(coder))
- coder view shell (coding.view_submission):
  (has_va_form_access(coder) or tester_covers)
  and (tester_covers or submission_within_org_view_scope(coder))
- coder pool (coder_workflow_service._available_submission_filters):
  form in coder | tester forms AND _org_unit_scope_filter(user)
- reviewer start / view (reviewer_coding_service, reviewing.view_submission):
  has_va_form_access(reviewer) and submission_within_org_scope(reviewer)
- reviewer list (reviewing.dashboard): reviewer forms AND _org_unit_scope_filter(reviewer)
- data manager (data_management.view_submission, triage):
  has_data_manager_submission_access(project, site, org_unit)

Delete this file in stage 7 with the old helpers.
"""
import sqlalchemy as sa

from app import db
from app.models import VaAccessRoles, VaForms, VaSubmissions
from app.services.authz import Action, can, scope_filter
from app.services.coder_workflow_service import (
    _org_unit_scope_filter,
    tester_covers_submission,
)
from app.services.org_grant_service import (
    submission_within_org_scope,
    submission_within_org_view_scope,
)
from tests.authz.fixture import SIDS, AuthzFixtureMixin
from tests.base import BaseTestCase

CODERS = ["coder_ta", "coder_ta_s1", "coder_c1", "coder_p1", "coder_tb", "coder_f1",
          "coder_sp", "coder_sp1", "tester_ta", "tester_c1", "tester_sp",
          "closed_coder", "nobody"]
REVIEWERS = ["reviewer_ta", "reviewer_c1", "reviewer_p1", "reviewer_sp1"]
DATA_MANAGERS = ["dm_ta", "dm_ta_s1", "dm_c1", "dm_sp", "dm_sp1", "admin"]

TREE_A = ["ta-d1", "ta-c1", "ta-p1", "ta-sc1", "ta-p2", "ta-d2", "ta-unr", "ta-s2"]

# (user, check, sid) -> the audit finding / decision the change closes. In
# every listed row the old answer is False and the new one True.
DELIBERATE = {
    # F15: a project-scope coding_tester on a tree project got an empty pool
    # (the list filter added tester units only); pick and view already let
    # them in. Closed: the tester is exempt from the scope level everywhere.
    **{("tester_ta", "pool", sid): "F15" for sid in TREE_A},
    # F7: reviewer viewing followed the coding scope, so a view_only reviewer
    # could open nothing. Closed: viewing is the wider right.
    **{("reviewer_ta", "view", sid): "F7" for sid in TREE_A},
    **{("reviewer_c1", "view", sid): "F7" for sid in ["ta-c1", "ta-p1", "ta-sc1", "ta-p2"]},
    # F11: admin passed the DM role gate and then failed every per-submission
    # check. Closed: admin bypasses VIEW and TRIAGE, closed projects included.
    **{("admin", check, sid): "F11" for check in ("dm_view", "dm_triage") for sid in SIDS},
    # digitva-6zq / F14: the demo-training project is open to every user for
    # coding, so viewing it is open too (VIEW is the union of the viewing
    # lenses, the demo coder's included); a data manager's old DM check
    # never covered demo. TRIAGE stays refused (never data_manager on demo).
    **{(dm, "dm_view", "dm-1"): "6zq/F14" for dm in DATA_MANAGERS if dm != "admin"},
    # Narrowing, stage 3: the per-submission DM check reached forms on a
    # deactivated (project, site) pair while the DM grid, exports and KPI
    # cards did not. Now both stop at the inactive pair.
    ("dm_sp", "dm_view", "sp-4"): "inactive pair",
    ("dm_sp", "dm_triage", "sp-4"): "inactive pair",
}


class ShadowOldHelpersTests(AuthzFixtureMixin, BaseTestCase):

    def _form(self, sid):
        return db.session.execute(
            sa.select(VaForms.form_id, VaForms.project_id, VaForms.site_id,
                      VaSubmissions.org_unit_id)
            .join(VaSubmissions, VaSubmissions.va_form_id == VaForms.form_id)
            .where(VaSubmissions.va_sid == sid)
        ).one()

    def _old_list(self, user, forms, role):
        if not forms:
            return set()
        return self.scoped_sids(sa.and_(
            VaSubmissions.va_form_id.in_(sorted(forms)), _org_unit_scope_filter(user, role)
        ))

    def _coder_rows(self, key):
        user = self.users[key]
        coder = VaAccessRoles.coder
        coder_forms = user.get_coder_va_forms()
        tester_forms = user.get_coding_tester_va_forms()
        old_pool = self._old_list(user, coder_forms | tester_forms, "coder")
        new_pool = self.scoped_sids(scope_filter(user, Action.CODE))
        for sid in SIDS:
            form = self._form(sid).form_id
            covers = tester_covers_submission(user, sid, form)
            has_coder_form = form in coder_forms
            yield "code", sid, (
                (has_coder_form or form in tester_forms)
                and (covers or submission_within_org_scope(user, sid, coder))
            ), can(user, Action.CODE, sid).allowed
            yield "view", sid, (
                (has_coder_form or covers)
                and (covers or submission_within_org_view_scope(user, sid, coder))
            ), can(user, Action.VIEW, sid).allowed
            yield "pool", sid, sid in old_pool, sid in new_pool

    def _reviewer_rows(self, key):
        user = self.users[key]
        reviewer = VaAccessRoles.reviewer
        forms = user.get_reviewer_va_forms()
        old_list = self._old_list(user, forms, "reviewer")
        new_list = self.scoped_sids(scope_filter(user, Action.REVIEW))
        for sid in SIDS:
            old = self._form(sid).form_id in forms and submission_within_org_scope(
                user, sid, reviewer
            )
            yield "review", sid, old, can(user, Action.REVIEW, sid).allowed
            yield "view", sid, old, can(user, Action.VIEW, sid).allowed
            yield "list", sid, sid in old_list, sid in new_list

    def _dm_rows(self, key):
        user = self.users[key]
        for sid in SIDS:
            row = self._form(sid)
            old = user.has_data_manager_submission_access(
                row.project_id, row.site_id, row.org_unit_id
            )
            yield "dm_view", sid, old, can(user, Action.VIEW, sid).allowed
            yield "dm_triage", sid, old, can(user, Action.TRIAGE, sid).allowed

    def test_old_and_new_agree_except_where_the_design_changes_behaviour(self):
        checked = 0
        differ = {}
        for keys, rows in ((CODERS, self._coder_rows), (REVIEWERS, self._reviewer_rows),
                           (DATA_MANAGERS, self._dm_rows)):
            for key in keys:
                for check, sid, old, new in rows(key):
                    checked += 1
                    if bool(old) != bool(new):
                        differ[(key, check, sid)] = (bool(old), bool(new))
        self.assertGreater(checked, 500)
        unexpected = {k: v for k, v in differ.items() if k not in DELIBERATE}
        self.assertEqual(unexpected, {}, "old and new disagree outside DELIBERATE")
        missing = set(DELIBERATE) - set(differ)
        self.assertEqual(missing, set(), "listed as deliberate but they agree")
        narrowed = {k for k, why in DELIBERATE.items() if why == "inactive pair"}
        self.assertTrue(all(
            v == ((True, False) if k in narrowed else (False, True))
            for k, v in differ.items()
        ))
