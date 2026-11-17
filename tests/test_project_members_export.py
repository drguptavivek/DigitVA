"""Roster "Export CSV": GET .../users-grid/members/export.csv gives the
project's roster people as ``name, email, phone``, which another project's
members import takes unchanged (docs/policy/dm-user-grant-management.md,
"Roster Members Export")."""
import csv
import io
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    MapProjectMember,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.models.auth_factors import AuthSecurityEvent
from app.models.mas_languages import MasLanguages
from tests.base import BaseTestCase


class ProjectMembersExportTests(BaseTestCase):
    A = "EXPA01"
    B = "EXPB01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        for project_id in (cls.A, cls.B):
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=f"Export {project_id}",
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, project_structure_mode="organization",
            ))
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English", is_active=True))
        db.session.flush()

        def grant(user, role, project_id):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
                project_id=project_id, grant_status=VaStatuses.active,
            ))

        cls.pi = cls._make_user("exp.pi@test.local", "ExpPi123")
        cls.dm = cls._make_user("exp.dm@test.local", "ExpDm123")
        cls.coder = cls._make_user("exp.coder@test.local", "ExpCoder123")
        grant(cls.pi, VaAccessRoles.project_pi, cls.A)
        grant(cls.dm, VaAccessRoles.data_manager, cls.A)
        grant(cls.coder, VaAccessRoles.coder, cls.A)
        cls.pi_b = cls._make_user("exp.pi.b@test.local", "ExpPiB123")
        grant(cls.pi_b, VaAccessRoles.project_pi, cls.B)
        cls.member = cls._make_user("exp.member@test.local", "ExpMember123")
        cls.member.name = "=SUM(A1) Member"
        cls.member.phone = "+91 98765 43210"
        cls.outsider = cls._make_user("exp.outsider@test.local", "ExpOut123")
        cls.outsider.name = "Outsider Person"
        cls.gone = cls._make_user("exp.gone@test.local", "ExpGone123")
        cls.gone.user_status = VaStatuses.deactive
        db.session.add_all([
            MapProjectMember(project_id=cls.A, user_id=cls.member.user_id),
            MapProjectMember(project_id=cls.A, user_id=cls.gone.user_id),
            MapProjectMember(project_id=cls.B, user_id=cls.outsider.user_id),
        ])
        db.session.commit()
        cls.pi_id, cls.dm_id, cls.coder_id = (str(u.user_id) for u in (cls.pi, cls.dm, cls.coder))
        cls.pi_b_id = str(cls.pi_b.user_id)

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _export(self, project_id=None):
        return self.client.get(f"/admin/api/projects/{project_id or self.A}/users-grid/members/export.csv")

    def _rows(self, response):
        return list(csv.reader(io.StringIO(response.get_data(as_text=True))))

    def test_admin_pi_and_dm_get_csv_with_exact_header(self):
        for user_id in (self.base_admin_id, self.pi_id, self.dm_id):
            self._login(user_id)
            response = self._export()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, "text/csv")
            self.assertEqual(response.get_data(as_text=True).splitlines()[0], "name,email,phone")

    def test_roster_person_present_outsider_and_deactivated_absent_formula_neutralised(self):
        self._login(self.pi_id)
        rows = self._rows(self._export())
        by_email = {row[1]: row for row in rows[1:]}
        self.assertIn("exp.member@test.local", by_email)
        # Formula prefix neutralised; phone in the ten-digit form the import accepts.
        self.assertEqual(by_email["exp.member@test.local"], ["'=SUM(A1) Member", "exp.member@test.local", "9876543210"])
        self.assertNotIn("exp.outsider@test.local", by_email)
        self.assertNotIn("exp.gone@test.local", by_email)

    def test_coder_and_other_projects_pi_are_refused(self):
        self._login(self.coder_id)
        self.assertEqual(self._export().status_code, 403)
        self._login(self.pi_b_id)
        self.assertEqual(self._export().status_code, 403)

    def test_round_trip_into_other_project_import_parses_every_row(self):
        self._login(self.pi_id)
        body = self._export().get_data(as_text=True)
        expected = len(self._rows(self._export())) - 1
        self.assertGreater(expected, 0)
        self._login(self.pi_b_id)
        response = self.client.post(
            f"/admin/api/projects/{self.B}/users-grid/members/import",
            data={"file": (io.BytesIO(body.encode("utf-8")), "export.csv"), "dry_run": "1"},
            content_type="multipart/form-data", headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = response.get_json()["rows"]
        self.assertEqual(len(rows), expected)
        self.assertEqual(response.get_json()["counts"]["refuse"], 0, rows)

    def test_audit_event_has_row_count_and_no_person_data(self):
        self._login(self.pi_id)
        before = db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "project_members_exported"))
        self.assertEqual(before, 0)
        count = len(self._rows(self._export())) - 1
        event = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "project_members_exported"
        )).all()[-1]
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "project_members_exported")), before + 1)
        self.assertEqual(str(event.actor_user_id), self.pi_id)
        self.assertEqual(event.detail, {"project_id": self.A, "rows": count})
