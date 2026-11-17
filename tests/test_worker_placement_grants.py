"""Worker placement changes replace unit roles (dm-user-grant-management.md,
"Placement changes replace unit roles"): PATCH .../workers/<id>."""
from datetime import UTC, datetime
from unittest.mock import patch

from app import db
from app.models import VaAccessRoles as R
from app.models import VaAccessScopeTypes as S
from app.models import VaProjectMaster, VaStatuses, VaUserAccessGrants
from app.services import organization_service as org
from tests.base import BaseTestCase


class WorkerPlacementGrantTests(BaseTestCase):
    PROJECT = "PLGR01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT, project_code=cls.PROJECT, project_name="Placement Grants",
            project_nickname="PlGr", project_status=VaStatuses.active, project_registered_at=now,
            project_updated_at=now, project_structure_mode="organization",
        ))
        db.session.commit()
        org.seed_default_organization(cls.PROJECT)
        district = {lv.level_code: lv for lv in org.list_levels(cls.PROJECT)}["district"]
        cls.d1, cls.d2, cls.d3 = (
            org.create_unit(cls.PROJECT, org_level_id=district.org_level_id, unit_code=f"PLD{i}", unit_name=f"Pl D{i}")
            for i in (1, 2, 3)
        )
        cls.cadres = {c.cadre_code: c for c in org.list_cadres(cls.PROJECT)}
        cls.dm = cls._make_user("pl.dm@test.local", "Staff123!x")
        db.session.add(VaUserAccessGrants(user_id=cls.dm.user_id, role=R.data_manager, scope_type=S.project,
                                          project_id=cls.PROJECT, grant_status=VaStatuses.active))
        db.session.commit()

    def _grant(self, user, role, unit=None):
        g = VaUserAccessGrants(
            user_id=user.user_id, role=role, grant_status=VaStatuses.active,
            scope_type=S.org_unit if unit else S.project,
            org_unit_id=unit.org_unit_id if unit else None,
            project_id=None if unit else self.PROJECT,
            cadre_id=self.cadres["SN"].cadre_id if unit else None,
        )
        db.session.add(g)
        return g

    def _setup_person(self, email):
        """An SN at D1 holding interviewer@D1, coder@D3 and project collaborator."""
        person = self._make_user(email, "Person123!x")
        worker = org.create_worker(self.PROJECT, org_unit_id=self.d1.org_unit_id,
                                   cadre_id=self.cadres["SN"].cadre_id, worker_name="Pl Person",
                                   user=str(person.user_id))
        grants = {
            "d1": self._grant(person, R.interviewer, self.d1),
            "d3": self._grant(person, R.coder, self.d3),
            "proj": self._grant(person, R.collaborator),
        }
        db.session.commit()
        return person, worker, grants

    def _patch(self, worker, body):
        with patch("app.logging.va_logger.log_grant_action") as audit:
            resp = self.client.patch(f"/admin/api/organization/{self.PROJECT}/workers/{worker.worker_id}",
                                     json=body, headers=self._csrf_headers())
        db.session.expire_all()
        return resp, audit

    def _status(self, grant):
        return db.session.get(VaUserAccessGrants, grant.grant_id).grant_status

    def _active_unit_roles(self, person, unit):
        return sorted(g.role.value for g in db.session.query(VaUserAccessGrants).filter_by(
            user_id=person.user_id, org_unit_id=unit.org_unit_id, grant_status=VaStatuses.active))

    def test_move_unit_replaces_old_unit_roles_with_new_defaults(self):
        self._login(str(self.base_admin_id))
        person, worker, grants = self._setup_person("pl.move@test.local")
        self.assertEqual(self._active_unit_roles(person, self.d1), ["interviewer"])
        resp, audit = self._patch(worker, {"org_unit_id": str(self.d2.org_unit_id)})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self._status(grants["d1"]), VaStatuses.deactive)
        self.assertEqual(self._active_unit_roles(person, self.d2), ["interviewer"])
        self.assertEqual(self._status(grants["d3"]), VaStatuses.active)
        self.assertEqual(self._status(grants["proj"]), VaStatuses.active)
        body = resp.get_json()["grants"]
        self.assertEqual(body["revoked"], [{"role": "interviewer", "unit_code": "PLD1", "unit_name": "Pl D1"}])
        self.assertEqual(body["granted"], [{"role": "interviewer", "unit_code": "PLD2", "unit_name": "Pl D2"}])
        self.assertEqual(sorted(c.kwargs["action"] for c in audit.call_args_list),
                         ["grant_created", "grant_toggled_inactive"])

    def test_cadre_change_at_same_unit(self):
        self._login(str(self.base_admin_id))
        person, worker, grants = self._setup_person("pl.cadre@test.local")
        resp, _ = self._patch(worker, {"cadre_id": str(self.cadres["MO"].cadre_id)})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self._status(grants["d1"]), VaStatuses.deactive)
        self.assertEqual(self._active_unit_roles(person, self.d1), ["coder", "reviewer"])
        self.assertEqual(self._status(grants["d3"]), VaStatuses.active)

    def test_deactivate_revokes_unit_roles_and_reactivate_restores_none(self):
        self._login(str(self.base_admin_id))
        person, worker, grants = self._setup_person("pl.off@test.local")
        resp, audit = self._patch(worker, {"is_active": False})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self._status(grants["d1"]), VaStatuses.deactive)
        self.assertEqual(self._status(grants["d3"]), VaStatuses.active)
        self.assertEqual(self._status(grants["proj"]), VaStatuses.active)
        self.assertEqual([c.kwargs["action"] for c in audit.call_args_list], ["grant_toggled_inactive"])
        resp, _ = self._patch(worker, {"is_active": True})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._active_unit_roles(person, self.d1), [])
        self.assertEqual(resp.get_json()["grants"], {"revoked": [], "granted": []})

    def test_data_manager_refused_when_one_grant_is_out_of_reach(self):
        person, worker, grants = self._setup_person("pl.dmref@test.local")
        site_pi = self._grant(person, R.site_pi, self.d1)
        db.session.commit()
        self._login(str(self.dm.user_id))
        resp, audit = self._patch(worker, {"org_unit_id": str(self.d2.org_unit_id)})
        self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertIn("site_pi", resp.get_json()["error"])
        self.assertEqual(self._status(grants["d1"]), VaStatuses.active)
        self.assertEqual(self._status(site_pi), VaStatuses.active)
        self.assertEqual(self._active_unit_roles(person, self.d2), [])
        self.assertEqual(db.session.get(type(worker), worker.worker_id).org_unit_id, self.d1.org_unit_id)
        audit.assert_not_called()

    def test_data_manager_moves_when_every_grant_is_in_reach(self):
        person, worker, grants = self._setup_person("pl.dmok@test.local")
        self._login(str(self.dm.user_id))
        resp, _ = self._patch(worker, {"org_unit_id": str(self.d2.org_unit_id)})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self._status(grants["d1"]), VaStatuses.deactive)
        self.assertEqual(self._active_unit_roles(person, self.d2), ["interviewer"])

    def _second_placement(self, person, unit, cadre="SN"):
        w = org.create_worker(self.PROJECT, org_unit_id=unit.org_unit_id, cadre_id=self.cadres[cadre].cadre_id,
                              worker_name="Pl Person 2", user=str(person.user_id))
        db.session.commit()
        return w

    def test_two_placements_defaults_go_to_the_moved_worker(self):
        self._login(str(self.base_admin_id))
        person, worker, grants = self._setup_person("pl.two@test.local")
        other = self._second_placement(person, self.d3)
        # The moved worker's code sorts after the other's, so it is not primary.
        other.worker_code, worker.worker_code = "A0001", "Z0001"
        db.session.commit()
        resp, _ = self._patch(worker, {"org_unit_id": str(self.d2.org_unit_id)})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self._active_unit_roles(person, self.d2), ["interviewer"])
        self.assertEqual(self._active_unit_roles(person, self.d3), ["coder"])

    def test_other_placement_at_old_unit_keeps_its_roles(self):
        self._login(str(self.base_admin_id))
        person, worker, grants = self._setup_person("pl.same@test.local")
        self._second_placement(person, self.d1)
        resp, _ = self._patch(worker, {"is_active": False})
        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertEqual(self._status(grants["d1"]), VaStatuses.active)
        self.assertEqual(resp.get_json()["grants"], {"revoked": [], "granted": []})

    def test_relink_with_move_is_refused(self):
        self._login(str(self.base_admin_id))
        person, worker, grants = self._setup_person("pl.relink@test.local")
        other = self._make_user("pl.relink2@test.local", "Person123!x")
        db.session.commit()
        resp, audit = self._patch(worker, {"user": str(other.user_id), "org_unit_id": str(self.d2.org_unit_id)})
        self.assertEqual(resp.status_code, 400, resp.get_json())
        self.assertIn("separate saves", resp.get_json()["error"])
        self.assertEqual(self._status(grants["d1"]), VaStatuses.active)
        w = db.session.get(type(worker), worker.worker_id)
        self.assertEqual((w.user_id, w.org_unit_id), (person.user_id, self.d1.org_unit_id))
        audit.assert_not_called()
