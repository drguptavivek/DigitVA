"""Second characterization of ``bulk_apply_project_users_grid`` (digitva-r8nh.14 slice 2).

Pins what the first file leaves open, on the code before the operation string
dispatch became an OPERATIONS registry: every key of ``_BULK_ROLE_MAP``, the
order in which validation stages fire (unknown operation, scope, inactive user),
the order of DB writes and audit rows across a multi-user and multi-operation
apply, and the state left behind when a batch fails part-way (the service
flushes but never commits or rolls back; the caller owns the transaction).
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnitWorker,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import org_grid
from app.services import organization_service as org
from tests.base import BaseTestCase


class BulkApplyOperationsCharacterizationTests(BaseTestCase):
    PROJECT = "GRDOP1"

    def setUp(self):
        super().setUp()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=self.PROJECT, project_code=self.PROJECT, project_name="Grid operations",
            project_nickname=self.PROJECT, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
        ))
        db.session.flush()
        org.seed_default_organization(self.PROJECT)
        levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
        cadres = {c.cadre_code: c for c in org.list_cadres(self.PROJECT)}
        self.chc_level_id = levels["chc"].org_level_id
        dist = org.create_unit(self.PROJECT, org_level_id=levels["district"].org_level_id,
                               unit_code="OD1", unit_name="Op D1")
        self.c1 = org.create_unit(self.PROJECT, org_level_id=self.chc_level_id,
                                  parent_org_unit_id=dist.org_unit_id, unit_code="OC1", unit_name="Op C1")
        self.c2 = org.create_unit(self.PROJECT, org_level_id=self.chc_level_id,
                                  parent_org_unit_id=dist.org_unit_id, unit_code="OC2", unit_name="Op C2")
        self.admin = db.session.get(VaUsers, uuid.UUID(str(self.base_admin_id)))
        self.u1 = self._make_user("grid.op.u1@test.local", "GridOp123")
        self.u2 = self._make_user("grid.op.u2@test.local", "GridOp123")
        self.u3 = self._make_user("grid.op.u3@test.local", "GridOp123")  # no placement
        self.mo = cadres["MO"]
        for code, user, unit in (("OW1", self.u1, self.c1), ("OW2", self.u2, self.c2)):
            db.session.add(MasOrgUnitWorker(
                project_id=self.PROJECT, org_unit_id=unit.org_unit_id, cadre_id=self.mo.cadre_id,
                user_id=user.user_id, worker_code=code, worker_name=code, is_active=True,
            ))
        db.session.flush()

    def _apply(self, users, operation, scope_mode="own", actor=None, **extra):
        payload = {"user_ids": [str(u.user_id) for u in users], "operation": operation,
                   "scope_mode": scope_mode, **extra}
        return org.bulk_apply_project_users_grid(self.PROJECT, payload, actor=actor or self.admin)

    def _grant_rows(self, user):
        return sorted(
            (g.role.value, g.scope_type.value, g.grant_status.value)
            for g in db.session.scalars(
                sa.select(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id)).all())

    def _clear_grants(self, user):
        # Role aliases (coder / coder_pii ...) share a role, so start each from none.
        db.session.execute(sa.delete(VaUserAccessGrants).where(VaUserAccessGrants.user_id == user.user_id))
        db.session.flush()
        db.session.expire_all()

    # -- every key of the role map --------------------------------------

    def test_every_role_operation_at_project_scope(self):
        expected = {
            "coder": "coder", "coder_non_pii": "coder", "coder_pii": "coder",
            "reviewer": "reviewer", "reviewer_non_pii": "reviewer", "reviewer_pii": "reviewer",
            "coding_tester": "coding_tester", "viewer_non_pii": "collaborator",
            "collaborator": "collaborator", "viewer_pii": "collaborator_pii",
            "collaborator_pii": "collaborator_pii", "data_manager": "data_manager",
            "project_pi": "project_pi", "interviewer": "interviewer",
        }
        # site_pi / in_charge fan out to project sites (none here); the other two
        # roles are unit-scoped only.
        self.assertEqual(
            set(expected) | {"in_charge", "site_pi", "interview_supervisor", "death_reporter"},
            set(org._BULK_ROLE_MAP))
        for operation, role in expected.items():
            with self.subTest(operation=operation):
                self._clear_grants(self.u3)
                summary, changed = self._apply([self.u3], operation, "project")
                self.assertEqual(summary["grants_created"], 1)
                self.assertEqual([action for _d, action in changed], ["grant_created"])
                self.assertEqual(changed[0][0]["role"], role)
                self.assertIn((role, "project", "active"), self._grant_rows(self.u3))
        for operation in ("in_charge", "site_pi"):
            with self.subTest(operation=operation), self.assertRaises(org.OrganizationError) as ctx:
                self._apply([self.u3], operation, "project")
            self.assertIn("no sites configured", str(ctx.exception))
        for operation in ("interview_supervisor", "death_reporter"):
            with self.subTest(operation=operation), self.assertRaises(org.OrganizationError) as ctx:
                self._apply([self.u3], operation, "project")
            self.assertIn("unit-scoped", str(ctx.exception))

    def test_every_role_operation_at_own_unit_scope(self):
        # MO at a CHC may code; the other cadre flags are checked per role.
        # project_pi ignores scope_mode and is granted project-wide.
        refused = {"interview_supervisor": "may not supervise interviews",
                   "death_reporter": "may not report deaths"}
        for operation, (roles, _revoke) in org._BULK_ROLE_MAP.items():
            with self.subTest(operation=operation):
                self._clear_grants(self.u1)
                if operation in refused:
                    with self.assertRaises(org.OrganizationError) as ctx:
                        self._apply([self.u1], operation, "own")
                    self.assertIn(refused[operation], str(ctx.exception))
                    continue
                summary, changed = self._apply([self.u1], operation, "own")
                self.assertEqual(summary["grants_created"], 1)
                self.assertEqual(changed[0][0]["role"], roles[0].value)
                self.assertEqual(
                    changed[0][0]["scope_type"], "project" if operation == "project_pi" else "org_unit")

    # -- validation order -------------------------------------------------

    def test_unknown_operation_fires_after_scope_and_inactive_checks(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u1], "nonsense", "custom")
        self.assertIn("target unit", str(ctx.exception))
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u1], "nonsense", f"level:{uuid.uuid4()}")
        self.assertIn("no active units", str(ctx.exception))
        self.u1.user_status = VaStatuses.deactive
        db.session.flush()
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u1], "nonsense", "own")
        self.assertIn("inactive", str(ctx.exception))
        self.u1.user_status = VaStatuses.active
        db.session.flush()
        # An unplaced single user is not resolved for an unknown operation.
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u3], "nonsense", "own")
        self.assertIn("Unknown bulk operation 'nonsense'", str(ctx.exception))
        self.assertEqual(self._grant_rows(self.u3), [])

    def test_operation_is_stripped_but_case_sensitive(self):
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u1], "Coder", "project")
        self.assertIn("Unknown bulk operation 'Coder'", str(ctx.exception))
        summary, _ = self._apply([self.u1], "  coder  ", "project")
        self.assertEqual((summary["operation"], summary["grants_created"]), ("coder", 1))

    def test_stages_that_skip_scope_and_inactive_validation(self):
        # Account status ignores scope_mode and runs before any preload.
        summary, _ = self._apply([self.u3], "deactivate_users", "bogus")
        self.assertEqual(summary["accounts_updated"], 1)
        self.u3.user_status = VaStatuses.active
        self._apply([self.u3], "collaborator", "project")
        self.u3.user_status = VaStatuses.deactive
        db.session.flush()
        # An inactive user: revokes still run, grants are refused.
        summary, _ = self._apply([self.u3], "revoke_pii", "project")
        self.assertEqual(summary["grants_revoked"], 0)
        summary, _ = self._apply([self.u3], "revoke_coder", "project")
        self.assertEqual(summary["grants_revoked"], 0)
        # revoke_all does not validate scope inputs (custom with no ids is fine).
        summary, _ = self._apply([self.u3], "revoke_all", "custom")
        self.assertEqual(summary["grants_revoked"], 1)
        for operation in ("collaborator", "cadre_defaults"):
            with self.assertRaises(org.OrganizationError) as ctx:
                self._apply([self.u3], operation, "project")
            self.assertIn("inactive", str(ctx.exception))
        # revoke_pii / revoke_coder do validate them.
        for operation in ("revoke_pii", "revoke_coder"):
            with self.assertRaises(org.OrganizationError) as ctx:
                self._apply([self.u3], operation, "custom")
            self.assertIn("target unit", str(ctx.exception))
            with self.assertRaises(org.OrganizationError) as ctx:
                self._apply([self.u3], operation, "bogus")
            self.assertIn("no home unit placement", str(ctx.exception))

    def test_non_admin_actor_is_refused_before_any_write(self):
        with self.assertRaises(org.OrganizationError):
            self._apply([self.u2], "coder", "own", actor=self.u1)
        self.assertEqual(self._grant_rows(self.u2), [])
        with self.assertRaises(org.OrganizationError):
            self._apply([self.u2], "activate_users", "own", actor=self.u1)

    # -- ordering of writes and audit rows --------------------------------

    def _record_writes(self, fn):
        statements = []

        def listener(_conn, _cursor, statement, *_a):
            verb = statement.split(None, 1)[0].upper()
            if verb in ("INSERT", "UPDATE", "DELETE"):
                words = statement.split()
                table = words[2 if verb == "INSERT" else 1].strip('"')
                statements.append((verb, table))

        sa.event.listen(db.engine, "before_cursor_execute", listener)
        try:
            result = fn()
            db.session.flush()
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", listener)
        return result, statements

    def test_multi_user_apply_orders_writes_and_audit_rows_by_request_order(self):
        (summary, changed), writes = self._record_writes(
            lambda: self._apply([self.u2, self.u1], "coder", "own"))
        self.assertEqual(summary["grants_created"], 2)
        self.assertEqual([d["user_id"] for d, _a in changed], [self.u2.user_id, self.u1.user_id])
        self.assertEqual([d["org_unit_id"] for d, _a in changed], [self.c2.org_unit_id, self.c1.org_unit_id])
        self.assertEqual(writes, [("INSERT", "va_user_access_grants")] * 2)

    def test_multi_operation_sequence_leaves_the_exact_audit_trail(self):
        trail = []
        for operation, scope in (("coder", "all_user_level"), ("reviewer", "own"), ("coder", "own"),
                                 ("collaborator", "project"), ("viewer_pii", "project"),
                                 ("revoke_coder", "own"), ("revoke_all", "own")):
            summary, changed = self._apply([self.u1], operation, scope)
            trail.append((operation, scope, summary["grants_created"], summary["grants_reactivated"],
                          summary["grants_revoked"], sorted(a for _d, a in changed)))
        self.assertEqual(trail, [
            ("coder", "all_user_level", 2, 0, 0, ["grant_created", "grant_created"]),
            ("reviewer", "own", 1, 0, 0, ["grant_created"]),
            ("coder", "own", 0, 0, 1, ["grant_revoked"]),
            ("collaborator", "project", 1, 0, 0, ["grant_created"]),
            ("viewer_pii", "project", 1, 0, 0, ["grant_created"]),
            ("revoke_coder", "own", 0, 0, 2, ["grant_revoked", "grant_revoked"]),
            ("revoke_all", "own", 0, 0, 2, ["grant_revoked"] * 2),
        ])
        self.assertEqual({r[2] for r in self._grant_rows(self.u1)}, {"deactive"})

    def test_grant_then_paired_revoke_order_within_one_apply(self):
        self._apply([self.u3], "viewer_pii", "project")
        (summary, changed), writes = self._record_writes(
            lambda: self._apply([self.u3], "collaborator", "project"))
        # grant the role first, then revoke the paired collaborator_pii.
        self.assertEqual([(d["role"], a) for d, a in changed],
                         [("collaborator", "grant_created"), ("collaborator_pii", "grant_revoked")])
        self.assertEqual(writes, [("INSERT", "va_user_access_grants"), ("UPDATE", "va_user_access_grants")])

    # -- partial failure ---------------------------------------------------

    def test_failure_mid_batch_leaves_earlier_flushed_rows_and_returns_nothing(self):
        anm = next(c for c in org.list_cadres(self.PROJECT) if c.cadre_code == "ANM")
        db.session.add(MasOrgUnitWorker(
            project_id=self.PROJECT, org_unit_id=self.c2.org_unit_id, cadre_id=anm.cadre_id,
            user_id=self.u3.user_id, worker_code="OW3", worker_name="OW3", is_active=True,
        ))
        db.session.flush()
        with self.assertRaises(org.OrganizationError) as ctx:
            self._apply([self.u1, self.u3], "coder", "own")
        self.assertIn("not defined at level", str(ctx.exception))
        # The service neither commits nor rolls back: u1's grant is still in the session.
        self.assertEqual(self._grant_rows(self.u1), [("coder", "org_unit", "active")])
        self.assertEqual(self._grant_rows(self.u3), [])

    def test_public_names_stay_importable_from_both_modules(self):
        for name in ("bulk_apply_project_users_grid", "_BULK_ROLE_MAP", "get_project_users_grid"):
            self.assertIs(getattr(org, name), getattr(org_grid, name))
