"""GET /api/v1/organization/me and /units/<org_unit_id>/people.

Rules under test live in app/services/organization_service.py (``my_organization``,
``unit_people``). Policy: docs/policy/organization-model.md, "Who sees worker
names" (name and cadre only, org-tree projects only).
"""
from datetime import UTC, datetime

from sqlalchemy import event

from app import db
from app.models import (
    MasOrgUnitWorker,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import organization_service as org
from tests.base import BaseTestCase

FORBIDDEN_KEYS = {"phone", "email", "worker_code", "user_id"}


def _project(project_id, name, *, org_tree):
    now = datetime.now(UTC)
    if db.session.get(VaProjectMaster, project_id) is None:
        db.session.add(
            VaProjectMaster(
                project_id=project_id,
                project_code=project_id,
                project_name=name,
                project_nickname=name,
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                project_structure_mode="organization" if org_tree else "sites",
            )
        )
        db.session.flush()


def _walk_keys(value):
    """Every dict key anywhere in a JSON value."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield key
            yield from _walk_keys(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk_keys(inner)


class MyOrganizationTests(BaseTestCase):
    PROJECT = "MYO01"
    OTHER_TREE = "MYO02"
    SITES = "MYSITE"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        _project(cls.PROJECT, "My Org Project", org_tree=True)
        _project(cls.OTHER_TREE, "My Org Other Tree", org_tree=True)
        _project(cls.SITES, "My Org Sites Project", org_tree=False)
        db.session.commit()

        org.seed_default_organization(cls.PROJECT)
        org.seed_default_organization(cls.OTHER_TREE)
        levels = {lv.level_code: lv for lv in org.list_levels(cls.PROJECT)}
        cls.district = org.create_unit(cls.PROJECT, org_level_id=levels["district"].org_level_id,
                                       unit_code="MD1", unit_name="My District")
        cls.chc = org.create_unit(cls.PROJECT, org_level_id=levels["chc"].org_level_id,
                                  parent_org_unit_id=cls.district.org_unit_id,
                                  unit_code="MC1", unit_name="My CHC")
        cls.chc_sibling = org.create_unit(cls.PROJECT, org_level_id=levels["chc"].org_level_id,
                                          parent_org_unit_id=cls.district.org_unit_id,
                                          unit_code="MC2", unit_name="My CHC Sibling")
        cls.phc = org.create_unit(cls.PROJECT, org_level_id=levels["phc"].org_level_id,
                                  parent_org_unit_id=cls.chc.org_unit_id,
                                  unit_code="MP1", unit_name="My PHC")
        cls.sub_a = org.create_unit(cls.PROJECT, org_level_id=levels["subcentre"].org_level_id,
                                    parent_org_unit_id=cls.phc.org_unit_id,
                                    unit_code="MS1", unit_name="My Sub-centre A")
        cls.sub_b = org.create_unit(cls.PROJECT, org_level_id=levels["subcentre"].org_level_id,
                                    parent_org_unit_id=cls.phc.org_unit_id,
                                    unit_code="MS2", unit_name="My Sub-centre B")
        cls.other_tree_district = org.create_unit(
            cls.OTHER_TREE, org_level_id={lv.level_code: lv for lv in org.list_levels(cls.OTHER_TREE)}["district"].org_level_id,
            unit_code="OD1", unit_name="Other District")

        cadres = {c.cadre_code: c for c in org.list_cadres(cls.PROJECT)}
        cls.cadre_cho = cadres["CHO"].cadre_id
        cls.cadre_mo = cadres["MO"].cadre_id

        cls.cho_user = cls._get_or_make_user("my.org.cho@test.local", "MyOrgUser123")
        cls.mo_user = cls._get_or_make_user("my.org.mo@test.local", "MyOrgUser123")
        cls.project_user = cls._get_or_make_user("my.org.project@test.local", "MyOrgUser123")
        cls.other_tree_user = cls._get_or_make_user("my.org.other@test.local", "MyOrgUser123")
        cls.sites_user = cls._get_or_make_user("my.org.sites@test.local", "MyOrgUser123")
        cls.none_user = cls._get_or_make_user("my.org.none@test.local", "MyOrgUser123")
        db.session.commit()

        # The CHO is on the roster of its own sub-centre, with a phone number
        # and a worker code that must never reach a reply.
        org.create_worker(cls.PROJECT, org_unit_id=cls.sub_a.org_unit_id, cadre_id=cls.cadre_cho,
                          worker_name="Meena Devi", worker_code="WCHO01", phone="9000000001")
        org.create_worker(cls.PROJECT, org_unit_id=cls.sub_a.org_unit_id, cadre_id=cls.cadre_cho,
                          worker_name="Ravi Peer", worker_code="WPEER1", phone="9000000002")
        org.create_worker(cls.PROJECT, org_unit_id=cls.phc.org_unit_id, cadre_id=cls.cadre_mo,
                          worker_name="Dr Anil", worker_code="WPHC01", phone="9000000003")
        org.create_worker(cls.PROJECT, org_unit_id=cls.chc.org_unit_id, cadre_id=cls.cadre_mo,
                          worker_name="Dr Chandra", worker_code="WCHC01", phone="9000000004")
        org.create_worker(cls.PROJECT, org_unit_id=cls.district.org_unit_id, cadre_id=cls.cadre_mo,
                          worker_name="Dr Dinesh", worker_code="WDST01", phone="9000000005")
        org.create_worker(cls.PROJECT, org_unit_id=cls.sub_b.org_unit_id, cadre_id=cls.cadre_cho,
                          worker_name="Sunita Kaur", worker_code="WSUB01", phone="9000000006")
        org.create_worker(cls.PROJECT, org_unit_id=cls.sub_b.org_unit_id, cadre_id=cls.cadre_cho,
                          worker_name="Farid Khan", worker_code="WSUB02", phone="9000000007")
        db.session.commit()

        cho_worker = db.session.execute(
            db.select(MasOrgUnitWorker).where(MasOrgUnitWorker.worker_code == "WCHO01")
        ).scalar_one()
        cho_worker.user_id = cls.cho_user.user_id
        db.session.commit()

    def _grant(self, user, role, **kwargs):
        db.session.add(VaUserAccessGrants(user_id=user.user_id, role=role,
                                          grant_status=VaStatuses.active, **kwargs))
        db.session.commit()

    def _get(self, path):
        return self.client.get(f"/api/v1/organization{path}")

    def _project_block(self, body, project_id):
        return next(p for p in body["projects"] if p["project_id"] == project_id)

    def _assert_no_contact_fields(self, body):
        keys = set(_walk_keys(body))
        self.assertFalse(keys & FORBIDDEN_KEYS, f"forbidden keys leaked: {keys & FORBIDDEN_KEYS}")
        text = str(body)
        for value in ("9000000001", "WCHO01", "my.org.cho@test.local"):
            self.assertNotIn(value, text)

    # -- CHO at a sub-centre ----------------------------------------------

    def test_sub_centre_cho_sees_own_unit_chain_above_and_peers(self):
        self._grant(self.cho_user, VaAccessRoles.interviewer,
                    scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.sub_a.org_unit_id,
                    cadre_id=self.cadre_cho)
        self._login(str(self.cho_user.user_id))

        response = self._get("/me")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        block = self._project_block(body, self.PROJECT)

        self.assertEqual(block["my_units"], [{
            "org_unit_id": str(self.sub_a.org_unit_id),
            "unit_name": "My Sub-centre A",
            "level_name": block["my_units"][0]["level_name"],
            "cadres": ["Community Health Officer"],
        }])
        self.assertEqual(set(block["my_units"][0]), {"org_unit_id", "unit_name", "level_name", "cadres"})
        self.assertIn("Meena Devi", str(body))  # names are present before absence is asserted
        # Above is root first: district, CHC, PHC.
        self.assertEqual([u["unit_name"] for u in block["above"]],
                         ["My District", "My CHC", "My PHC"])
        people_above = {u["unit_name"]: [p["name"] for p in u["people"]] for u in block["above"]}
        self.assertEqual(people_above["My District"], ["Dr Dinesh"])
        self.assertEqual(people_above["My PHC"], ["Dr Anil"])
        # My level: the sub-centre's roster, peers included.
        self.assertEqual(len(block["my_level"]), 1)
        self.assertEqual(sorted(p["name"] for p in block["my_level"][0]["people"]),
                         ["Meena Devi", "Ravi Peer"])
        self.assertEqual(block["my_level"][0]["people"][0]["cadre"], "Community Health Officer")
        # No children below a sub-centre.
        self.assertEqual(block["below"], [])
        self._assert_no_contact_fields(body)

    # -- MO at a PHC ---------------------------------------------------------

    def test_phc_mo_sees_sub_centres_below_with_counts(self):
        self._grant(self.mo_user, VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc.org_unit_id,
                    cadre_id=self.cadre_mo)
        self._login(str(self.mo_user.user_id))

        body = self._get("/me").get_json()
        block = self._project_block(body, self.PROJECT)
        below = {u["unit_name"]: u for u in block["below"]}
        self.assertEqual(set(below), {"My Sub-centre A", "My Sub-centre B"})
        self.assertIn("Dr Anil", str(body))  # the PHC's own roster is in the reply
        self.assertEqual(below["My Sub-centre A"]["people_count"], 2)
        self.assertEqual(below["My Sub-centre B"]["people_count"], 2)
        self.assertFalse(below["My Sub-centre A"]["has_children"])
        self.assertEqual(set(below["My Sub-centre A"]), {
            "org_unit_id", "unit_name", "level_name", "people_count", "has_children",
        })
        self._assert_no_contact_fields(body)

    def test_opening_a_child_lists_its_people(self):
        self._grant(self.mo_user, VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc.org_unit_id,
                    cadre_id=self.cadre_mo)
        self._login(str(self.mo_user.user_id))

        response = self._get(f"/units/{self.sub_b.org_unit_id}/people")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["unit"]["unit_name"], "My Sub-centre B")
        self.assertEqual(sorted(p["name"] for p in body["people"]), ["Farid Khan", "Sunita Kaur"])
        self.assertEqual(body["children"], [])
        self._assert_no_contact_fields(body)

    # -- access boundary -----------------------------------------------------

    def test_unit_in_another_project_is_404(self):
        self._grant(self.mo_user, VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc.org_unit_id,
                    cadre_id=self.cadre_mo)
        self._grant(self.other_tree_user, VaAccessRoles.interviewer,
                    scope_type=VaAccessScopeTypes.org_unit,
                    org_unit_id=self.other_tree_district.org_unit_id)
        self._login(str(self.other_tree_user.user_id))

        response = self._get(f"/units/{self.sub_a.org_unit_id}/people")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._get(f"/units/{self.sub_a.org_unit_id}/people").status_code, 404)

    def test_unknown_and_malformed_unit_ids_are_404(self):
        self._grant(self.mo_user, VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc.org_unit_id,
                    cadre_id=self.cadre_mo)
        self._login(str(self.mo_user.user_id))

        self.assertEqual(self._get("/units/not-a-uuid/people").status_code, 404)
        self.assertEqual(self._get(f"/units/{self.district.org_unit_id}0/people").status_code, 404)

    def test_user_with_no_grant_sees_no_projects(self):
        self._login(str(self.none_user.user_id))
        self.assertEqual(self._get("/me").get_json(), {"projects": []})

    def test_project_level_user_sees_roots_below_and_no_my_units(self):
        self._grant(self.project_user, VaAccessRoles.interviewer,
                    scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT)
        # A sites-mode project grant is not an org-tree project: omitted.
        self._grant(self.project_user, VaAccessRoles.interviewer,
                    scope_type=VaAccessScopeTypes.project, project_id=self.SITES)
        self._login(str(self.project_user.user_id))

        body = self._get("/me").get_json()
        self.assertEqual([p["project_id"] for p in body["projects"]], [self.PROJECT])
        block = body["projects"][0]
        self.assertEqual(block["my_units"], [])
        self.assertEqual(block["above"], [])
        self.assertEqual(block["my_level"], [])
        self.assertEqual([u["unit_name"] for u in block["below"]], ["My District"])
        self.assertEqual(block["below"][0]["people_count"], 1)
        self.assertTrue(block["below"][0]["has_children"])
        self._assert_no_contact_fields(body)

    def test_sites_only_user_gets_nothing(self):
        self._grant(self.sites_user, VaAccessRoles.interviewer,
                    scope_type=VaAccessScopeTypes.project, project_id=self.SITES)
        self._login(str(self.sites_user.user_id))
        self.assertEqual(self._get("/me").get_json(), {"projects": []})

    # -- query count ---------------------------------------------------------

    def test_query_count_does_not_grow_with_units(self):
        self._grant(self.mo_user, VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.org_unit, org_unit_id=self.phc.org_unit_id,
                    cadre_id=self.cadre_mo)
        statements = []

        def count(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", count)
        try:
            org.my_organization(self.mo_user)
            small = len(statements)
            statements.clear()
            levels = {lv.level_code: lv for lv in org.list_levels(self.PROJECT)}
            for i in range(4):
                sub = org.create_unit(self.PROJECT, org_level_id=levels["subcentre"].org_level_id,
                                      parent_org_unit_id=self.phc.org_unit_id,
                                      unit_code=f"MSX{i}", unit_name=f"Extra {i}")
                org.create_worker(self.PROJECT, org_unit_id=sub.org_unit_id, cadre_id=self.cadre_cho,
                                  worker_name=f"Extra Worker {i}")
            db.session.commit()
            statements.clear()
            org.my_organization(self.mo_user)
            large = len(statements)
        finally:
            event.remove(db.engine, "before_cursor_execute", count)

        self.assertGreater(small, 0)
        self.assertEqual(small, large)
