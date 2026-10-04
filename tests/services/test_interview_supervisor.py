"""The ``interview_supervisor`` grant role (digitva-vzk.5).

Decisions 12 and 14-17 in .tasks/2026-09-28-interviewer-worklist.md; policy:
docs/policy/web-intake.md, "Supervisors". Covers:
  - the write-time cadre check (flag on the level x cadre row) and unit-only
    scope, in the grant service, the admin API, the DB CHECK and the user import
  - ``is_interview_supervisor_for``: subtree yes, sibling no, other project no,
    data_manager grants supervise, other roles do not
  - each supervisor power allowed for a supervisor and refused (403) for a
    plain interviewer; confirming a coded submission as a duplicate needs a
    data_manager grant
  - the supervisor API: listing, 404 outside scope, CSRF
  - audit rows naming the grant and cadre relied on, the narrowest-grant
    choice, the supervision page and the direct duplicate mark (digitva-vzk.8)
"""
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseTransition,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services import case_transition_service as cases
from app.services import org_grant_service as og
from app.services import organization_service as org
from app.services import project_user_import_service as user_import
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase


def _dod(days=10):
    return (date.today() - timedelta(days=days)).isoformat()


class InterviewSupervisorTests(BaseTestCase):
    PROJECT_ID = "SUP01"
    SITE_ID = "SP01"
    OTHER_PROJECT_ID = "SUP02"
    OTHER_SITE_ID = "SP02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        pairs = ((cls.PROJECT_ID, cls.SITE_ID), (cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID))
        for project_id, site_id in pairs:
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, web_intake_mode="both",
                project_structure_mode="organization",
            ))
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in pairs:
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in pairs:
            _ensure_legacy_project_site_rows(project_id, site_id)
            db.session.add(VaForms(
                form_id=f"{project_id}{site_id}01", project_id=project_id, site_id=site_id,
                odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022",
                form_source="odk", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        db.session.flush()

        # District > CHC C1 > PHC P1 > Sub-centre S1, and a sibling CHC C2.
        org.seed_default_organization(cls.PROJECT_ID)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.PROJECT_ID)}
        cls.cadres = {c.cadre_code: c for c in org.list_cadres(cls.PROJECT_ID)}

        def unit(level, code, parent=None):
            return org.create_unit(
                cls.PROJECT_ID, org_level_id=levels[level].org_level_id, unit_code=code,
                unit_name=f"Unit {code}", parent_org_unit_id=parent.org_unit_id if parent else None,
            )

        district = unit("district", "SD1")
        cls.c1 = unit("chc", "SC1", district)
        cls.p1 = unit("phc", "SP1", cls.c1)
        cls.s1 = unit("subcentre", "SS1", cls.p1)
        cls.c2 = unit("chc", "SC2", district)
        cls.phc_level_id = levels["phc"].org_level_id
        # MO may supervise at a PHC (decision 12); the template leaves it off.
        org.upsert_level_cadre(
            cls.PROJECT_ID, org_level_id=cls.phc_level_id, cadre_id=cls.cadres["MO"].cadre_id,
            can_fill_va_form=False, can_code_va_form=True, can_supervise_interviews=True,
        )

        def grant(user, role, **scope):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, notes="supervisor test",
                grant_status=VaStatuses.active, **scope,
            ))

        cls.ian = cls._get_or_make_user("sup.ian@test.local", "Supervise123")
        cls.sam = cls._get_or_make_user("sup.sam@test.local", "Supervise123")
        cls.dana = cls._get_or_make_user("sup.dana@test.local", "Supervise123")
        cls.cody = cls._get_or_make_user("sup.cody@test.local", "Supervise123")
        for project_id in (cls.PROJECT_ID, cls.OTHER_PROJECT_ID):
            grant(cls.ian, VaAccessRoles.interviewer,
                  scope_type=VaAccessScopeTypes.project, project_id=project_id)
        # Sam supervises P1's subtree and holds no interviewer grant (decision 17).
        grant(cls.sam, VaAccessRoles.interview_supervisor, scope_type=VaAccessScopeTypes.org_unit,
              org_unit_id=cls.p1.org_unit_id, cadre_id=cls.cadres["MO"].cadre_id)
        grant(cls.dana, VaAccessRoles.data_manager,
              scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID)
        # A coder at P1 supervises nothing (decision 15).
        grant(cls.cody, VaAccessRoles.coder, scope_type=VaAccessScopeTypes.org_unit,
              org_unit_id=cls.p1.org_unit_id, cadre_id=cls.cadres["MO"].cadre_id)
        # Vera holds three covering grants of different width (narrowest-grant
        # choice, digitva-vzk.8); Olga manages only the other project.
        cls.vera = cls._get_or_make_user("sup.vera@test.local", "Supervise123")
        cls.olga = cls._get_or_make_user("sup.olga@test.local", "Supervise123")
        grant(cls.vera, VaAccessRoles.data_manager,
              scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID)
        grant(cls.vera, VaAccessRoles.data_manager,
              scope_type=VaAccessScopeTypes.org_unit, org_unit_id=cls.c1.org_unit_id)
        grant(cls.vera, VaAccessRoles.interview_supervisor, scope_type=VaAccessScopeTypes.org_unit,
              org_unit_id=cls.p1.org_unit_id, cadre_id=cls.cadres["MO"].cadre_id)
        grant(cls.olga, VaAccessRoles.data_manager,
              scope_type=VaAccessScopeTypes.project, project_id=cls.OTHER_PROJECT_ID)
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _register(self, unit=None, **overrides):
        fields = {"deceased_name": "Asha Devi", "deceased_sex": "female", "date_of_death": _dod()}
        fields.update(overrides)
        return intake_svc.register_death(
            self.ian, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
            org_unit_id=str((unit or self.s1).org_unit_id), **fields,
        )

    def _submitted_with_workflow(self, workflow_state):
        case = self._register()
        sid = f"uuid:sup-{uuid.uuid4()}"
        now = datetime.now(UTC)
        db.session.add(VaSubmissions(
            va_sid=sid, va_form_id=f"{self.PROJECT_ID}{self.SITE_ID}01", va_submission_date=now,
            va_odk_updatedat=now, va_data_collector="sup", va_odk_reviewstate="reviewed",
            va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid, va_consent="yes",
            va_narration_language="English", va_deceased_age=50, va_deceased_gender="male",
            va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        db.session.add(VaSubmissionWorkflow(va_sid=sid, workflow_state=workflow_state))
        case.va_sid = sid
        cases.transition(case, "in_progress", actor=self.ian, action="test")
        cases.transition(case, "submitted", actor=self.ian, action="test")
        return case

    def _grant_row(self, **kwargs):
        return VaUserAccessGrants(user_id=self.ian.user_id, grant_status=VaStatuses.active, **kwargs)

    # ── write-time check ───────────────────────────────────────────────────

    def test_a_supervisor_grant_needs_a_cadre_flagged_to_supervise_at_the_level(self):
        unit, cadre = og.validate_org_unit_grant(
            role=VaAccessRoles.interview_supervisor, org_unit_id=self.p1.org_unit_id,
            cadre_id=self.cadres["MO"].cadre_id,
        )
        self.assertEqual((unit.org_unit_id, cadre.cadre_code), (self.p1.org_unit_id, "MO"))

        # MO is placed at CHC too, but not flagged to supervise there.
        with self.assertRaisesRegex(org.OrganizationError, "may not supervise interviews"):
            og.validate_org_unit_grant(
                role=VaAccessRoles.interview_supervisor, org_unit_id=self.c1.org_unit_id,
                cadre_id=self.cadres["MO"].cadre_id,
            )
        with self.assertRaisesRegex(org.OrganizationError, "requires a cadre"):
            og.validate_org_unit_grant(
                role=VaAccessRoles.interview_supervisor, org_unit_id=self.p1.org_unit_id,
            )
        # CHO is placed at PHC without the flag.
        with self.assertRaisesRegex(org.OrganizationError, "may not supervise interviews"):
            og.validate_org_unit_grant(
                role=VaAccessRoles.interview_supervisor, org_unit_id=self.p1.org_unit_id,
                cadre_id=self.cadres["CHO"].cadre_id,
            )

    def test_the_grid_flag_is_kept_when_a_caller_omits_it(self):
        row = org.upsert_level_cadre(
            self.PROJECT_ID, org_level_id=self.phc_level_id, cadre_id=self.cadres["MO"].cadre_id,
            can_fill_va_form=True, can_code_va_form=True,
        )
        self.assertTrue(row.can_supervise_interviews)
        row = org.upsert_level_cadre(
            self.PROJECT_ID, org_level_id=self.phc_level_id, cadre_id=self.cadres["MO"].cadre_id,
            can_fill_va_form=True, can_code_va_form=True, can_supervise_interviews=False,
        )
        self.assertFalse(row.can_supervise_interviews)
        exported = {(r["level_code"], r["cadre_code"]): r
                    for r in org.export_organization_rows(self.PROJECT_ID)["level_cadres"]}
        self.assertIn("can_supervise_interviews", exported[("phc", "MO")])
        self.assertFalse(exported[("phc", "MO")]["can_supervise_interviews"])

    def test_a_supervisor_grant_is_unit_scoped_only(self):
        self._login(str(self.base_admin_id))
        response = self.client.post(
            "/admin/api/access-grants",
            json={"user_id": str(self.ian.user_id), "role": "interview_supervisor",
                  "scope_type": "project", "project_id": self.PROJECT_ID},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertIn("cannot use project scope", response.get_json()["error"])

        response = self.client.post(
            "/admin/api/access-grants",
            json={"user_id": str(self.ian.user_id), "role": "interview_supervisor",
                  "scope_type": "org_unit", "org_unit_id": str(self.p1.org_unit_id),
                  "cadre_id": str(self.cadres["MO"].cadre_id)},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())

        # The database refuses it too.
        with self.assertRaises(sa.exc.IntegrityError):
            with db.session.begin_nested():
                db.session.add(self._grant_row(
                    role=VaAccessRoles.interview_supervisor,
                    scope_type=VaAccessScopeTypes.project, project_id=self.OTHER_PROJECT_ID,
                ))
                db.session.flush()

    def test_the_user_import_holds_supervisors_to_a_flagged_unit_cadre(self):
        def row(**kw):
            base = {"email": "sup.ian@test.local", "name": "", "role": "interview_supervisor",
                    "org_unit_code": "SP1", "cadre_code": "MO", "language_codes": "", "phone": "",
                    "_line_number": 2}
            base.update(kw)
            return base

        plan = user_import.prepare(self.PROJECT_ID, [row()], actor=self.base_admin_user)
        self.assertEqual(plan[0]["role"], VaAccessRoles.interview_supervisor)
        for bad, message in (
            (row(org_unit_code="", cadre_code=""), "requires an organization unit"),
            (row(cadre_code="CHO"), "permitted to supervise interviews"),
            (row(org_unit_code="SC1"), "permitted to supervise interviews"),
        ):
            with self.assertRaisesRegex(user_import.ProjectUserImportError, message):
                user_import.prepare(self.PROJECT_ID, [bad], actor=self.base_admin_user)

    # ── the predicate ──────────────────────────────────────────────────────

    def test_supervision_reaches_the_grant_subtree_only(self):
        in_subtree = self._register(unit=self.s1)
        at_unit = self._register(unit=self.p1)
        sibling = self._register(unit=self.c2)
        above = self._register(unit=self.c1)
        self.assertTrue(cases.is_interview_supervisor_for(self.sam, in_subtree))
        self.assertTrue(cases.is_interview_supervisor_for(self.sam, at_unit))
        self.assertFalse(cases.is_interview_supervisor_for(self.sam, sibling))
        self.assertFalse(cases.is_interview_supervisor_for(self.sam, above))

        # Another project's case, even pointing at a unit in the subtree.
        other = intake_svc.register_death(
            self.ian, project_id=self.OTHER_PROJECT_ID, site_id=self.OTHER_SITE_ID,
            deceased_name="Ravi", deceased_sex="male", date_of_death=_dod(),
        )
        other.org_unit_id = self.s1.org_unit_id
        db.session.flush()
        self.assertFalse(cases.is_interview_supervisor_for(self.sam, other))

    def test_data_managers_supervise_and_other_roles_do_not(self):
        case = self._register(unit=self.c2)
        self.assertTrue(cases.is_interview_supervisor_for(self.dana, case))
        for user in (self.ian, self.cody):
            self.assertFalse(cases.is_interview_supervisor_for(user, case))
        in_subtree = self._register(unit=self.s1)
        self.assertTrue(cases.is_interview_supervisor_for(self.sam, in_subtree))
        self.assertFalse(cases.is_interview_supervisor_for(self.cody, in_subtree))

    def test_a_revoked_grant_or_closed_project_supervises_nothing(self):
        case = self._register()
        self.assertTrue(cases.is_interview_supervisor_for(self.sam, case))
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.sam.user_id,
            VaUserAccessGrants.role == VaAccessRoles.interview_supervisor,
        ))
        grant.grant_status = VaStatuses.deactive
        db.session.flush()
        self.assertFalse(cases.is_interview_supervisor_for(self.sam, case))
        grant.grant_status = VaStatuses.active
        db.session.get(VaProjectMaster, self.PROJECT_ID).project_status = VaStatuses.deactive
        db.session.flush()
        self.assertFalse(cases.is_interview_supervisor_for(self.sam, case))
        self.assertFalse(cases.is_interview_supervisor_for(self.dana, case))

    def test_the_role_gate_opens_on_the_grant_alone(self):
        self.assertTrue(self.sam.is_interview_supervisor())
        self.assertFalse(self.sam.is_interviewer())
        self.assertFalse(self.ian.is_interview_supervisor())

    # ── powers ─────────────────────────────────────────────────────────────

    def test_a_supervisor_resolves_flags_an_interviewer_cannot(self):
        kept = self._register()
        dup = self._register(deceased_name="Asha D")
        cases.flag_case(dup, actor=self.ian, kind="duplicate", duplicate_of=kept, reason="same")
        self.assertEqual(dup.pending_flag, "duplicate")
        for confirm in (True, False):
            with self.assertRaises(cases.WebIntakeError) as ctx:
                cases.resolve_flag(dup, actor=self.ian, confirm=confirm)
            self.assertEqual(ctx.exception.status_code, 403)
        cases.resolve_flag(dup, actor=self.sam, confirm=True, reason="same death")
        self.assertEqual((dup.status, dup.duplicate_of_death_id), ("duplicate", kept.death_id))

        other = self._register(deceased_name="Asha Dei")
        cases.flag_case(other, actor=self.ian, kind="cancel", reason="registered in error")
        cases.resolve_flag(other, actor=self.sam, confirm=False, reason="real death")
        self.assertEqual((other.status, other.pending_flag), ("registered", None))

    def test_a_supervisor_cancels_an_interview_an_interviewer_cannot(self):
        case = self._register()
        cases.transition(case, "in_progress", actor=self.ian, action="test")
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.transition(case, "cancelled", actor=self.ian, action="supervisor_cancel")
        self.assertEqual(ctx.exception.status_code, 403)
        cases.transition(case, "cancelled", actor=self.sam, action="supervisor_cancel", reason="wrong")
        self.assertEqual(case.status, "cancelled")

    def test_a_supervisor_reopens_a_terminal_case_an_interviewer_cannot(self):
        case = self._register()
        cases.transition(case, "cancelled", actor=self.ian, action="cancel_registration")
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.reopen(case, actor=self.ian, reason="real")
        self.assertEqual(ctx.exception.status_code, 403)
        cases.reopen(case, actor=self.sam, reason="real")
        self.assertEqual(case.status, "registered")

    def test_confirming_a_coded_submission_as_duplicate_needs_a_data_manager(self):
        kept = self._register()
        coded = self._submitted_with_workflow("coder_finalized")
        cases.flag_case(coded, actor=self.ian, kind="duplicate", duplicate_of=kept)
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.resolve_flag(coded, actor=self.sam, confirm=True)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(coded.status, "submitted")
        cases.resolve_flag(coded, actor=self.dana, confirm=True)
        self.assertEqual(coded.status, "duplicate")

        # Not yet coded: any supervisor may confirm.
        uncoded = self._submitted_with_workflow("ready_for_coding")
        cases.flag_case(uncoded, actor=self.ian, kind="duplicate", duplicate_of=kept)
        cases.resolve_flag(uncoded, actor=self.sam, confirm=True)
        self.assertEqual(uncoded.status, "duplicate")

    def test_a_submitted_case_without_a_workflow_row_fails_closed(self):
        kept = self._register()
        case = self._register(deceased_name="Asha D")
        cases.transition(case, "in_progress", actor=self.ian, action="test")
        cases.transition(case, "submitted", actor=self.ian, action="test")
        self.assertIsNone(case.va_sid)
        cases.flag_case(case, actor=self.ian, kind="duplicate", duplicate_of=kept)
        with self.assertRaises(cases.WebIntakeError) as ctx:
            cases.resolve_flag(case, actor=self.sam, confirm=True)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_a_supervisors_own_flag_waits_when_the_data_manager_rule_stops_them(self):
        kept = self._register()
        coded = self._submitted_with_workflow("reviewer_finalized")
        cases.flag_case(coded, actor=self.sam, kind="duplicate", duplicate_of=kept)
        self.assertEqual((coded.status, coded.pending_flag), ("submitted", "duplicate"))

        other = self._register(deceased_name="Asha D")
        cases.flag_case(other, actor=self.sam, kind="duplicate", duplicate_of=kept)
        self.assertEqual((other.status, other.pending_flag), ("duplicate", None))

    # ── API ────────────────────────────────────────────────────────────────

    def test_the_supervisor_list_shows_scope_with_staff_names(self):
        pending = intake_svc.start_draft(
            self.ian, project_id=self.PROJECT_ID, site_id=self.SITE_ID, org_unit_id=str(self.s1.org_unit_id),
        )
        inside = self._register()
        sibling = self._register(unit=self.c2)
        db.session.commit()
        self._login(str(self.sam.user_id))
        response = self.client.get("/api/v1/intake/supervision/cases")
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = {r["death_id"]: r for r in response.get_json()["cases"]}
        self.assertIn(str(inside.death_id), rows)
        # "Details pending" is visible to supervisors (decision 11).
        self.assertIn(str(pending.death_id), rows)
        self.assertTrue(rows[str(pending.death_id)]["details_pending"])
        self.assertNotIn(str(sibling.death_id), rows)
        row = rows[str(inside.death_id)]
        self.assertEqual(row["registered_by_name"], self.ian.name)
        self.assertIn("deceased_name", row)
        self.assertNotIn("informant_phone", row)
        self.assertNotIn("address", row)

        for query in ("flagged=maybe", "state=va_submitted", "limit=ten", "cursor=zzz"):
            self.assertEqual(self.client.get(f"/api/v1/intake/supervision/cases?{query}").status_code, 400)

    def test_the_supervisor_api_refuses_plain_interviewers(self):
        case = self._register()
        db.session.commit()
        self._login(str(self.ian.user_id))
        self.assertEqual(self.client.get("/api/v1/intake/supervision/cases").status_code, 403)
        response = self.client.post(
            f"/api/v1/intake/supervision/cases/{case.death_id}/cancel",
            json={"reason": "x"}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(db.session.get(VaDeathRegister, case.death_id).status, "registered")

    def test_supervisor_posts_need_csrf_and_read_out_of_scope_as_not_found(self):
        inside = self._register()
        sibling = self._register(unit=self.c2)
        db.session.commit()
        self._login(str(self.sam.user_id))
        url = f"/api/v1/intake/supervision/cases/{inside.death_id}/cancel"

        self.assertEqual(self.client.post(url, json={"reason": "wrong"}).status_code, 400)
        self.assertEqual(db.session.get(VaDeathRegister, inside.death_id).status, "registered")

        response = self.client.post(
            f"/api/v1/intake/supervision/cases/{sibling.death_id}/cancel",
            json={"reason": "wrong"}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            f"/api/v1/intake/supervision/cases/{uuid.uuid4()}/reopen",
            json={"reason": "x"}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 404)

        response = self.client.post(url, json={"reason": "wrong"}, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["state"], "cancelled")

        response = self.client.post(
            f"/api/v1/intake/supervision/cases/{inside.death_id}/reopen",
            json={"reason": "real death"}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["state"], "registered")

    def test_resolving_a_flag_through_the_api(self):
        case = self._register()
        cases.flag_case(case, actor=self.ian, kind="cancel", reason="registered in error")
        db.session.commit()
        self._login(str(self.sam.user_id))
        url = f"/api/v1/intake/supervision/cases/{case.death_id}/resolve-flag"
        self.assertEqual(
            self.client.post(url, json={"confirm": "yes"}, headers=self._csrf_headers()).status_code, 400
        )
        response = self.client.post(url, json={"confirm": True, "reason": "error"}, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["state"], "cancelled")

    def test_reactivating_a_grant_rechecks_the_cadre_flag(self):
        row = self._grant_row(
            role=VaAccessRoles.interview_supervisor, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=self.p1.org_unit_id, cadre_id=self.cadres["MO"].cadre_id,
        )
        row.grant_status = VaStatuses.deactive
        db.session.add(row)
        db.session.commit()
        self._login(str(self.base_admin_id))
        url = f"/admin/api/access-grants/{row.grant_id}/toggle"

        # While MO may supervise at PHC, re-activation works (and toggles back off).
        self.assertEqual(self.client.post(url, headers=self._csrf_headers()).status_code, 200)
        self.assertEqual(self.client.post(url, headers=self._csrf_headers()).status_code, 200)

        org.upsert_level_cadre(
            self.PROJECT_ID, org_level_id=self.phc_level_id, cadre_id=self.cadres["MO"].cadre_id,
            can_fill_va_form=False, can_code_va_form=True, can_supervise_interviews=False,
        )
        db.session.commit()
        try:
            response = self.client.post(url, headers=self._csrf_headers())
            self.assertEqual(response.status_code, 400, response.get_json())
            self.assertIn("may not supervise interviews", response.get_json()["error"])
            db.session.refresh(row)
            self.assertEqual(row.grant_status, VaStatuses.deactive)
        finally:
            org.upsert_level_cadre(
                self.PROJECT_ID, org_level_id=self.phc_level_id, cadre_id=self.cadres["MO"].cadre_id,
                can_fill_va_form=False, can_code_va_form=True, can_supervise_interviews=True,
            )
            db.session.commit()

    def test_supervisor_actions_return_no_identifiers(self):
        case = self._register()
        cases.flag_case(case, actor=self.ian, kind="cancel", reason="registered in error")
        db.session.commit()
        self._login(str(self.sam.user_id))
        response = self.client.post(
            f"/api/v1/intake/supervision/cases/{case.death_id}/resolve-flag",
            json={"confirm": False, "reason": "not an error"}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        body = response.get_json()["case"]
        self.assertEqual(body["unique_id"], case.unique_id)
        self.assertIn("registered_by_name", body)  # the supervisor list's row, not the interviewer's detail
        for key in ("informant", "informant_phone", "informant_phone_masked", "address", "abha_number", "prefill", "links"):
            self.assertNotIn(key, body)

    # ── audit grant and cadre, supervision page (digitva-vzk.8) ────────────

    def _grant_id(self, user, role, **scope):
        return db.session.scalar(sa.select(VaUserAccessGrants.grant_id).filter_by(
            user_id=user.user_id, role=role, **scope))

    def _audit_rows(self, case):
        return {
            row.action: row
            for row in db.session.scalars(
                sa.select(MapCaseTransition).where(MapCaseTransition.death_id == case.death_id)
            )
        }

    def test_supervisor_audit_rows_name_the_grant_and_cadre_and_team_moves_do_not(self):
        sam_grant = self._grant_id(self.sam, VaAccessRoles.interview_supervisor, org_unit_id=self.p1.org_unit_id)
        mo = self.cadres["MO"].cadre_id
        started = self._register()
        cases.transition(started, "in_progress", actor=self.ian, action="interview_started")
        cases.transition(started, "cancelled", actor=self.sam, action="supervisor_cancel", reason="error")
        cases.reopen(started, actor=self.sam, reason="real death")
        rows = self._audit_rows(started)
        for action in ("supervisor_cancel", "reopen"):
            self.assertIn(action, rows)
            self.assertEqual((rows[action].authorizing_grant_id, rows[action].authorizing_cadre_id), (sam_grant, mo))
        self.assertIn("interview_started", rows)
        self.assertIsNone(rows["interview_started"].authorizing_grant_id)
        self.assertIsNone(rows["created"].authorizing_cadre_id)

        rejected = self._register()
        cases.flag_case(rejected, actor=self.ian, kind="cancel", reason="registered in error")
        cases.resolve_flag(rejected, actor=self.sam, confirm=False, reason="not an error")
        rows = self._audit_rows(rejected)
        self.assertEqual(rows["reject_cancel"].authorizing_grant_id, sam_grant)
        self.assertIn("flag_cancel", rows)
        self.assertIsNone(rows["flag_cancel"].authorizing_grant_id)

        kept, duplicate = self._register(), self._register()
        cases.flag_case(duplicate, actor=self.sam, kind="duplicate", duplicate_of=kept)
        rows = self._audit_rows(duplicate)
        self.assertEqual(db.session.get(VaDeathRegister, duplicate.death_id).status, "duplicate")
        self.assertEqual(rows["flag_duplicate"].authorizing_grant_id, sam_grant)
        self.assertEqual(rows["confirm_duplicate"].authorizing_grant_id, sam_grant)

        # The registrant cancelling their own case needs no supervision.
        own = self._register()
        cases.transition(own, "cancelled", actor=self.ian, action="registrant_cancel", reason="error")
        rows = self._audit_rows(own)
        self.assertIn("registrant_cancel", rows)
        self.assertIsNone(rows["registrant_cancel"].authorizing_grant_id)
        self.assertIsNone(rows["registrant_cancel"].authorizing_cadre_id)

    def test_the_narrowest_covering_grant_is_the_one_relied_on(self):
        supervisor = self._grant_id(self.vera, VaAccessRoles.interview_supervisor, org_unit_id=self.p1.org_unit_id)
        unit_dm = self._grant_id(self.vera, VaAccessRoles.data_manager, org_unit_id=self.c1.org_unit_id)
        project_dm = self._grant_id(self.vera, VaAccessRoles.data_manager, project_id=self.PROJECT_ID)
        in_s1, in_c1, in_c2 = self._register(), self._register(unit=self.c1), self._register(unit=self.c2)
        self.assertEqual(tuple(cases.supervising_grant(self.vera, in_s1)), (supervisor, self.cadres["MO"].cadre_id))
        self.assertEqual(tuple(cases.supervising_grant(self.vera, in_c1)), (unit_dm, None))
        self.assertEqual(tuple(cases.supervising_grant(self.vera, in_c2)), (project_dm, None))
        self.assertIsNone(cases.supervising_grant(self.sam, in_c2))

    def test_confirming_a_coded_duplicate_names_the_data_manager_grant(self):
        unit_dm = self._grant_id(self.vera, VaAccessRoles.data_manager, org_unit_id=self.c1.org_unit_id)
        kept = self._register()
        coded = self._submitted_with_workflow("coder_finalized")
        cases.flag_case(coded, actor=self.ian, kind="duplicate", duplicate_of=kept)
        cases.resolve_flag(coded, actor=self.vera, confirm=True)
        row = self._audit_rows(coded)["confirm_duplicate"]
        # Vera's P1 supervisor grant is narrower, but the rule needs a data_manager grant.
        self.assertEqual((row.authorizing_grant_id, row.authorizing_cadre_id), (unit_dm, None))

    def test_the_supervision_page_opens_for_supervisors_and_data_managers_only(self):
        for user in (self.sam, self.dana):
            self._login(str(user.user_id))
            response = self.client.get("/intake/supervision")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"intake_supervision.js", response.data)
            self.assertIn(b'href="/intake/supervision"', response.data)
        self._login(str(self.ian.user_id))
        self.assertEqual(self.client.get("/intake/supervision").status_code, 403)
        self.assertNotIn(b'href="/intake/supervision"', self.client.get("/intake/").data)

    def test_a_data_manager_with_nothing_to_supervise_gets_an_empty_list(self):
        self._register()
        db.session.commit()
        self._login(str(self.dana.user_id))
        self.assertTrue(self.client.get("/api/v1/intake/supervision/cases").get_json()["cases"])
        self._login(str(self.olga.user_id))
        response = self.client.get("/api/v1/intake/supervision/cases")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"cases": [], "counts": {}, "next_cursor": None})

    def test_supervised_rows_carry_no_informant_phone(self):
        self._register(informant_phone="9876543210")
        db.session.commit()
        self._login(str(self.sam.user_id))
        row = self.client.get("/api/v1/intake/supervision/cases").get_json()["cases"][0]
        self.assertIn("registered_by_name", row)
        for key in ("informant_phone_masked", "informant_phone_2_masked", "informant_phone", "address"):
            self.assertNotIn(key, row)

    def test_a_supervisor_marks_a_duplicate_directly(self):
        kept, duplicate = self._register(), self._register()
        sibling = self._register(unit=self.c2)
        db.session.commit()
        self._login(str(self.sam.user_id))
        url = f"/api/v1/intake/supervision/cases/{duplicate.death_id}/duplicate"
        body = {"duplicate_of": str(kept.death_id), "reason": "same death"}

        self.assertEqual(self.client.post(url, json=body).status_code, 400)  # no CSRF token
        response = self.client.post(url, json={"duplicate_of": str(sibling.death_id)}, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 404)
        response = self.client.post(
            f"/api/v1/intake/supervision/cases/{sibling.death_id}/duplicate",
            json={"duplicate_of": str(kept.death_id)}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.post(url, json={}, headers=self._csrf_headers()).status_code, 400)
        self.assertEqual(db.session.get(VaDeathRegister, duplicate.death_id).status, "registered")

        response = self.client.post(url, json=body, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["state"], "duplicate")
        stored = db.session.get(VaDeathRegister, duplicate.death_id)
        db.session.refresh(stored)
        self.assertEqual(stored.duplicate_of_death_id, kept.death_id)
        rows = self._audit_rows(stored)
        self.assertEqual(
            rows["confirm_duplicate"].authorizing_grant_id,
            self._grant_id(self.sam, VaAccessRoles.interview_supervisor, org_unit_id=self.p1.org_unit_id),
        )

    def test_a_direct_duplicate_mark_on_a_coded_case_waits_for_a_data_manager(self):
        kept = self._register()
        coded = self._submitted_with_workflow("coder_finalized")
        db.session.commit()
        self._login(str(self.sam.user_id))
        response = self.client.post(
            f"/api/v1/intake/supervision/cases/{coded.death_id}/duplicate",
            json={"duplicate_of": str(kept.death_id)}, headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["case"]["pending_flag"], "duplicate")
        self.assertEqual(response.get_json()["case"]["state"], "submitted")

    # ── the In-charge and project_pi (digitva-0wc stage 5) ─────────────────

    def _user_with(self, key, role, **scope):
        user = self._get_or_make_user(f"sup.{key}@test.local", "Supervise123")
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, grant_status=VaStatuses.active, **scope,
        ))
        db.session.flush()
        return user

    def test_an_in_charge_supervises_its_subtree_and_not_the_siblings(self):
        incharge = self._user_with("incharge", VaAccessRoles.site_pi,
                                   scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.c1.org_unit_id)
        in_subtree, sibling = self._register(unit=self.s1), self._register(unit=self.c2)
        self.assertTrue(incharge.is_interview_supervisor())
        self.assertTrue(cases.is_interview_supervisor_for(incharge, in_subtree))
        self.assertFalse(cases.is_interview_supervisor_for(incharge, sibling))
        listed = set(db.session.scalars(
            sa.select(VaDeathRegister.death_id).where(cases.supervised_case_condition(incharge))
        ))
        self.assertIn(in_subtree.death_id, listed)
        self.assertNotIn(sibling.death_id, listed)

        self._login(str(incharge.user_id))
        self.assertEqual(self.client.get("/intake/supervision").status_code, 200)

    def test_an_in_charge_ranks_with_a_supervisor_at_equal_depth(self):
        # Two grants on P1: an In-charge and a unit data manager. The In-charge
        # ranks with interview_supervisor, before the data manager.
        user = self._user_with("rank", VaAccessRoles.site_pi,
                               scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.p1.org_unit_id)
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.data_manager, grant_status=VaStatuses.active,
            scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.p1.org_unit_id,
        ))
        db.session.flush()
        incharge = self._grant_id(user, VaAccessRoles.site_pi, org_unit_id=self.p1.org_unit_id)
        self.assertEqual(cases.supervising_grant(user, self._register()).grant_id, incharge)

    def test_an_in_charge_confirms_a_coded_duplicate_as_a_data_manager_would(self):
        incharge = self._user_with("incharge.dup", VaAccessRoles.site_pi,
                                   scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.c1.org_unit_id)
        kept = self._register()
        coded = self._submitted_with_workflow("coder_finalized")
        cases.flag_case(coded, actor=self.ian, kind="duplicate", duplicate_of=kept)
        cases.resolve_flag(coded, actor=incharge, confirm=True)
        row = self._audit_rows(coded)["confirm_duplicate"]
        self.assertEqual(
            row.authorizing_grant_id,
            self._grant_id(incharge, VaAccessRoles.site_pi, org_unit_id=self.c1.org_unit_id),
        )

    def test_project_pi_on_a_tree_project_supervises_the_whole_project(self):
        pi = self._user_with("pi.tree", VaAccessRoles.project_pi,
                             scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT_ID)
        case = self._register(unit=self.c2)
        self.assertTrue(pi.is_interview_supervisor())
        self.assertTrue(cases.is_interview_supervisor_for(pi, case))
        self.assertEqual(
            cases.supervising_grant(pi, case).grant_id,
            self._grant_id(pi, VaAccessRoles.project_pi, project_id=self.PROJECT_ID),
        )
        # SUP02 has no tree: its project_pi supervises nothing there.
        other_pi = self._user_with("pi.site", VaAccessRoles.project_pi,
                                   scope_type=VaAccessScopeTypes.project, project_id=self.OTHER_PROJECT_ID)
        other = intake_svc.register_death(
            self.ian, project_id=self.OTHER_PROJECT_ID, site_id=self.OTHER_SITE_ID,
            deceased_name="Ravi", deceased_sex="male", date_of_death=_dod(),
        )
        self.assertFalse(other_pi.is_interview_supervisor())
        self.assertFalse(cases.is_interview_supervisor_for(other_pi, other))
        # The listing predicate agrees: the tree PI lists its project only.
        listed = set(db.session.scalars(
            sa.select(VaDeathRegister.death_id).where(cases.supervised_case_condition(pi))))
        self.assertIn(case.death_id, listed)
        self.assertNotIn(other.death_id, listed)
        self.assertFalse(set(db.session.scalars(
            sa.select(VaDeathRegister.death_id).where(cases.supervised_case_condition(other_pi)))))

    def test_a_classical_site_pi_supervises_nothing(self):
        # A pair site_pi is outside the supervising roles.
        project_site_id = db.session.scalar(sa.select(VaProjectSites.project_site_id).filter_by(
            project_id=self.PROJECT_ID, site_id=self.SITE_ID))
        site_pi = self._user_with("sitepi.pair", VaAccessRoles.site_pi,
                                  scope_type=VaAccessScopeTypes.project_site, project_site_id=project_site_id)
        case = self._register()
        self.assertTrue(site_pi.is_site_pi())
        self.assertFalse(site_pi.is_interview_supervisor())
        self.assertFalse(cases.is_interview_supervisor_for(site_pi, case))

    def test_the_user_import_accepts_an_in_charge_with_a_unit_code_only(self):
        def row(**kw):
            base = {"email": "sup.ian@test.local", "name": "", "role": "site_pi",
                    "org_unit_code": "SC1", "cadre_code": "", "language_codes": "", "phone": "",
                    "_line_number": 2}
            base.update(kw)
            return base

        plan = user_import.prepare(self.PROJECT_ID, [row()], actor=self.base_admin_user)
        self.assertEqual(plan[0]["role"], VaAccessRoles.site_pi)
        self.assertEqual(plan[0]["unit"].org_unit_id, self.c1.org_unit_id)
        with self.assertRaisesRegex(user_import.ProjectUserImportError, "requires an organization unit"):
            user_import.prepare(self.PROJECT_ID, [row(org_unit_code="")], actor=self.base_admin_user)
