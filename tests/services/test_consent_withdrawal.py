"""A respondent's consent withdrawal on a submitted case (digitva-4gu7).

Policy: docs/policy/consent-withdrawal.md. ``WithdrawnCaseExclusionTests``
reruns every reader test of ``ConfirmedDuplicateExclusionTests`` (pool,
SmartVA, DM grid and exports, reporting counts, named-submission refusal,
allocation revocation) with "confirm" = record a withdrawal and "reopen" =
admin undo, each presence first. The route tests below cover who may act,
the seal, the audit rows and CSRF.
"""
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    MasOrgLevel,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaConsentWithdrawal,
    VaDeathRegister,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import consent_withdrawal_service as withdrawal_svc
from app.services.area_dashboard_service import _reported_deaths
from app.services.duplicate_exclusion import WITHDRAWN_MESSAGE, excluded_message
from tests.routes.test_dm_kpi_confirmed_duplicates import DmKpiConfirmedDuplicateTests
from tests.services.test_duplicate_exclusion import ConfirmedDuplicateExclusionTests

URL = "/api/v1/intake/supervision/cases/{}/consent-withdrawal"
BODY = {"requested_by": "informant's son", "requested_on": date.today().isoformat(), "channel": "phone",
        "note": "Called the site office."}


class WithdrawnCaseExclusionTests(ConfirmedDuplicateExclusionTests):
    PROJECT_ID = "WDRX01"
    SITE_ID = "WX01"
    FORM_ID = "WDRX01WX0101"
    REFUSAL_MESSAGE = WITHDRAWN_MESSAGE

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.other_dm = cls._get_or_make_user("wdrx.otherdm@test.local", "Withdraw123")
        # A data manager of another project: out of scope for these cases.
        db.session.add(VaUserAccessGrants(
            user_id=cls.other_dm.user_id, role=VaAccessRoles.data_manager, notes="wdrx",
            grant_status=VaStatuses.active, scope_type=VaAccessScopeTypes.project,
            project_id=cls.BASE_PROJECT_ID,
        ))
        db.session.commit()

    def _confirm(self, case):
        withdrawal_svc.record(self.dana, case, dict(BODY))
        db.session.commit()
        self.assertIsNotNone(case.consent_withdrawn_at)

    def _reopen(self, case):
        withdrawal_svc.undo(self.base_admin_user, case, "recorded on the wrong case")
        db.session.commit()
        self.assertIsNone(case.consent_withdrawn_at)
        self.assertEqual(case.status, "submitted")

    # ── service rules ──────────────────────────────────────────────────────

    def test_the_refusal_names_the_withdrawal(self):
        case = self._case("ready_for_coding")
        self._confirm(case)
        self.assertEqual(excluded_message(case.va_sid), WITHDRAWN_MESSAGE)

    def test_area_reported_deaths_exclude_a_withdrawn_case(self):
        case = self._case("ready_for_coding")

        def counted():
            return db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister).where(
                _reported_deaths(self.PROJECT_ID), VaDeathRegister.death_id == case.death_id)) == 1

        self._assert_excluded_while_confirmed(case, counted)

    def test_only_a_submitted_case_takes_a_withdrawal_and_only_once(self):
        case = self._case("ready_for_coding")
        self._confirm(case)
        with self.assertRaises(withdrawal_svc.WebIntakeError) as twice:
            withdrawal_svc.record(self.dana, case, dict(BODY))
        self.assertEqual(twice.exception.status_code, 409)
        db.session.rollback()
        with self.assertRaises(withdrawal_svc.WebIntakeError) as not_submitted:
            withdrawal_svc.record(self.dana, self.kept, dict(BODY))
        self.assertEqual(not_submitted.exception.status_code, 409)
        db.session.rollback()

    def test_bad_fields_are_refused(self):
        case = self._case("ready_for_coding")
        future = (date.today() + timedelta(days=2)).isoformat()
        for body in ({**BODY, "requested_by": " "}, {**BODY, "channel": "fax"},
                     {**BODY, "requested_on": future}, {**BODY, "note": "x" * 2001}):
            with self.assertRaises(withdrawal_svc.WebIntakeError) as refused:
                withdrawal_svc.record(self.dana, case, body)
            self.assertEqual(refused.exception.status_code, 422)
            db.session.rollback()
        self.assertIsNone(case.consent_withdrawn_at)

    # ── routes ─────────────────────────────────────────────────────────────

    def _post(self, user, case, body=None, suffix=""):
        self._login(str(user.user_id))
        return self.client.post(URL.format(case.death_id) + suffix, json=body if body is not None else BODY,
                                headers=self._csrf_headers())

    def test_who_may_record(self):
        case = self._case("ready_for_coding")
        self.assertEqual(self._post(self.coder, case).status_code, 403)
        self.assertEqual(self._post(self.other_dm, case).status_code, 404)
        self.assertIsNone(db.session.get(VaDeathRegister, case.death_id).consent_withdrawn_at)
        reply = self._post(self.dana, case)
        self.assertEqual((reply.status_code, reply.get_json()), (200, {"consent_withdrawn": True}))

    def test_project_data_manager_records_on_a_non_tree_and_a_tree_project(self):
        case = self._case("ready_for_coding")
        self.assertTrue(withdrawal_svc.can_record(self.dana, case))
        self.assertFalse(withdrawal_svc.can_record(self.other_dm, case))
        ids = [case.death_id]
        self.assertEqual(withdrawal_svc.recordable_ids(self.dana, ids), {case.death_id})
        self.assertEqual(withdrawal_svc.recordable_ids(self.other_dm, ids), set())
        self.assertEqual(withdrawal_svc.recordable_ids(self.coder, ids), set())
        self.assertEqual(self._post(self.dana, case).status_code, 200, "non-tree project")

        level = MasOrgLevel(project_id=self.PROJECT_ID, level_code="DIST", level_name="District", depth=1)
        db.session.add(level)
        db.session.commit()
        try:
            tree_case = self._case("ready_for_coding")
            self.assertTrue(withdrawal_svc.can_record(self.dana, tree_case))
            self.assertEqual(withdrawal_svc.recordable_ids(self.dana, [tree_case.death_id]), {tree_case.death_id})
            self.assertEqual(self._post(self.dana, tree_case).status_code, 200, "tree project")
            self.assertEqual(self._post(self.other_dm, self._case("ready_for_coding")).status_code, 404)
        finally:
            db.session.delete(level)
            db.session.commit()

    LIST_URL = "/api/v1/admin/consent-withdrawals"

    def _list(self, user, query=""):
        self._login(str(user.user_id))
        return self.client.get(self.LIST_URL + query)

    def test_admin_list_has_no_person_text_hides_undone_and_is_admin_only(self):
        case = self._case("ready_for_coding")
        self.assertEqual(self._post(self.dana, case).status_code, 200)
        self.assertEqual(self._list(self.dana).status_code, 403)
        self.assertEqual(self._list(self.coder).status_code, 403)

        reply = self._list(self.base_admin_user, f"?project_id={self.PROJECT_ID}")
        self.assertEqual(reply.status_code, 200)
        mine = [r for r in reply.get_json()["withdrawals"] if r["death_id"] == str(case.death_id)]
        self.assertEqual(len(mine), 1)
        row = mine[0]
        self.assertEqual((row["unique_id"], row["project_id"], row["channel"], row["recorded_by_name"], row["undone"]),
                         (case.unique_id, self.PROJECT_ID, "phone", self.dana.name, False))
        self.assertEqual(row["requested_on"], BODY["requested_on"])
        self.assertNotIn("requested_by", row)
        self.assertNotIn("son", str(reply.get_json()))
        self.assertEqual(self._list(self.base_admin_user, "?project_id=NOPE99").get_json()["withdrawals"], [])

        self.assertEqual(self._post(self.base_admin_user, case, {"reason": "mistake"}, "/undo").status_code, 200)
        gone = self._list(self.base_admin_user, f"?project_id={self.PROJECT_ID}").get_json()["withdrawals"]
        self.assertNotIn(str(case.death_id), [r["death_id"] for r in gone])
        shown = self._list(self.base_admin_user, f"?project_id={self.PROJECT_ID}&include_undone=1").get_json()
        self.assertIn((str(case.death_id), True), [(r["death_id"], r["undone"]) for r in shown["withdrawals"]])

    def test_admin_list_pages_with_a_bounded_keyset_cursor(self):
        cases = [self._case("ready_for_coding") for _ in range(3)]
        for case in cases:
            self.assertEqual(self._post(self.dana, case).status_code, 200)
        query = f"?project_id={self.PROJECT_ID}&limit=2"
        first = self._list(self.base_admin_user, query).get_json()
        self.assertEqual(len(first["withdrawals"]), 2)
        self.assertEqual(first["withdrawals"][0]["death_id"], str(cases[2].death_id), "newest first")
        second = self._list(self.base_admin_user, f"{query}&cursor={quote(first['next_cursor'])}").get_json()
        self.assertEqual([r["death_id"] for r in second["withdrawals"]][:1], [str(cases[0].death_id)])
        self.assertIsNone(second["next_cursor"])
        self.assertEqual(self._list(self.base_admin_user, "?cursor=junk").status_code, 400)
        self.assertEqual(self._list(self.base_admin_user, "?limit=x").status_code, 400)
        clamped = self._list(self.base_admin_user, "?limit=100000")
        self.assertEqual(clamped.status_code, 200)
        self.assertLessEqual(len(clamped.get_json()["withdrawals"]), withdrawal_svc.LIST_LIMIT_MAX)

    def test_record_audit_seal_and_admin_undo(self):
        case = self._case("ready_for_coding")
        detail = f"/api/v1/intake/supervision/cases/{case.death_id}"
        self._login(str(self.dana.user_id))
        self.assertEqual(self.client.get(detail).status_code, 200, "the DM sees the case before")
        self.assertEqual(self._post(self.dana, case).status_code, 200)

        row = db.session.scalar(sa.select(VaConsentWithdrawal).where(VaConsentWithdrawal.death_id == case.death_id))
        self.assertEqual((row.requested_by, row.channel, row.recorded_by), ("informant's son", "phone", self.dana.user_id))
        audit = db.session.scalars(sa.select(MapCaseTransition).where(
            MapCaseTransition.death_id == case.death_id, MapCaseTransition.action == "consent_withdrawn")).all()
        self.assertEqual(len(audit), 1)
        self.assertNotIn("son", audit[0].reason or "")

        # Sealed: the DM no longer reaches it; the admin does, audited.
        self._login(str(self.dana.user_id))
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self._post(self.dana, case, {"reason": "mistake"}, "/undo").status_code, 403)
        self._login(str(self.base_admin_user.user_id))
        reply = self.client.get(detail)
        self.assertEqual(reply.status_code, 200)
        body = reply.get_json()["case"]
        self.assertTrue(body["consent_withdrawn"])
        self.assertEqual(body["consent_withdrawal"]["requested_by"], "informant's son")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).where(
            MapCaseTransition.death_id == case.death_id,
            MapCaseTransition.action == "consent_withdrawn_case_viewed")), 1)

        self.assertEqual(self._post(self.base_admin_user, case, {}, "/undo").status_code, 422)
        undone = self._post(self.base_admin_user, case, {"reason": "wrong case"}, "/undo")
        self.assertEqual(undone.status_code, 200)
        self.assertFalse(undone.get_json()["case"]["consent_withdrawn"])
        db.session.refresh(row)
        self.assertEqual((row.undo_reason, row.undone_by), ("wrong case", self.base_admin_user.user_id))
        self._login(str(self.dana.user_id))
        self.assertEqual(self.client.get(detail).status_code, 200, "back for the DM after undo")

    def test_an_admin_records_and_gets_the_sealed_row_back(self):
        case = self._case("ready_for_coding")
        reply = self._post(self.base_admin_user, case)
        self.assertEqual(reply.status_code, 200)
        self.assertTrue(reply.get_json()["case"]["consent_withdrawn"])
        too_long = self._post(self.base_admin_user, case, {"reason": "x" * (withdrawal_svc.UNDO_REASON_MAX + 1)}, "/undo")
        self.assertEqual(too_long.status_code, 422)
        at_limit = self._post(self.base_admin_user, case, {"reason": "x" * withdrawal_svc.UNDO_REASON_MAX}, "/undo")
        self.assertEqual(at_limit.status_code, 200)

    def test_csrf_is_required(self):
        case = self._case("ready_for_coding")
        previous = self.app.config.get("WTF_CSRF_ENABLED")
        self.app.config["WTF_CSRF_ENABLED"] = True
        try:
            self._login(str(self.dana.user_id))
            refused = self.client.post(URL.format(case.death_id), json=BODY)
            self.assertIn(refused.status_code, (400, 403))
            self.assertEqual(self._post(self.dana, case).status_code, 200)
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = previous


class DmKpiWithdrawnCaseTests(DmKpiConfirmedDuplicateTests):
    """Every DM KPI endpoint test, the second submission now a submitted
    case whose consent was withdrawn instead of a duplicate."""

    FORM_ID = f"{DmKpiConfirmedDuplicateTests.BASE_PROJECT_ID}{DmKpiConfirmedDuplicateTests.BASE_SITE_ID}09"
    LIVE_SID = "uuid:dm-kpi-wdr-live"
    RETIRED_SID = "uuid:dm-kpi-wdr-withdrawn"

    @classmethod
    def _seed_submission(cls, sid, now, sync_issue_code):
        super()._seed_submission(sid, now, sync_issue_code)
        if sid == cls.RETIRED_SID:
            db.session.execute(sa.update(VaDeathRegister).where(VaDeathRegister.va_sid == sid).values(
                status="submitted", consent_withdrawn_at=datetime.now(UTC), death_number=880002,
                unique_id="DMKPI-WDR-1"))
            db.session.flush()
