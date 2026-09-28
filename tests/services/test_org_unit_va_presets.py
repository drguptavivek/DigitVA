"""Area VA presets (Id10002/Id10003): resolution and admin management.

Rules under test: ``app.services.org_grant_service.resolve_unit_va_presets``
(nearest-ancestor inheritance, resolved independently per field, one query)
and ``app.services.organization_service`` (get/set/clear the unit's own row).
Policy: docs/policy/web-intake.md ("Area VA presets"). Precedent:
tests/services/test_org_unit_coding_gates.py.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster, VaStatuses
from app.services import org_grant_service as og
from app.services import organization_service as org
from tests.base import BaseTestCase

_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class OrgUnitVaPresetsTests(BaseTestCase):
    PROJECT = f"VP{_RUN_SUFFIX}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT,
                project_code=cls.PROJECT,
                project_name="VA Preset Project",
                project_nickname="VaPreset",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()

        # District D01 > CHC C01 > PHC P01 > Sub-centre S01, plus sibling CHC C02.
        org.seed_default_organization(cls.PROJECT)
        lv = {level.level_code: level for level in org.list_levels(cls.PROJECT)}
        cls.district = org.create_unit(
            cls.PROJECT, org_level_id=lv["district"].org_level_id,
            unit_code="D01", unit_name="District One",
        )
        cls.chc = org.create_unit(
            cls.PROJECT, org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=cls.district.org_unit_id, unit_code="C01", unit_name="Yelahanka CHC",
        )
        cls.phc = org.create_unit(
            cls.PROJECT, org_level_id=lv["phc"].org_level_id,
            parent_org_unit_id=cls.chc.org_unit_id, unit_code="P01", unit_name="Yelahanka PHC",
        )
        cls.subcentre = org.create_unit(
            cls.PROJECT, org_level_id=lv["subcentre"].org_level_id,
            parent_org_unit_id=cls.phc.org_unit_id, unit_code="S01", unit_name="Yelahanka Sub-centre",
        )
        cls.sibling_chc = org.create_unit(
            cls.PROJECT, org_level_id=lv["chc"].org_level_id,
            parent_org_unit_id=cls.district.org_unit_id, unit_code="C02", unit_name="Sibling CHC",
        )
        db.session.commit()

    # -- resolution -----------------------------------------------------

    def test_own_value_wins_over_inherited(self):
        org.set_unit_va_presets(self.PROJECT, self.chc.org_unit_id, hiv_mortality="high", malaria_mortality=None)
        org.set_unit_va_presets(self.PROJECT, self.phc.org_unit_id, hiv_mortality="low", malaria_mortality=None)
        db.session.commit()

        resolved = og.resolve_unit_va_presets([self.phc.org_unit_id])

        self.assertEqual(resolved[self.phc.org_unit_id]["hiv_mortality"]["value"], "low")
        self.assertEqual(resolved[self.phc.org_unit_id]["hiv_mortality"]["source_unit_id"], self.phc.org_unit_id)

    def test_inherited_from_parent(self):
        org.set_unit_va_presets(self.PROJECT, self.phc.org_unit_id, hiv_mortality="high", malaria_mortality="low")
        db.session.commit()

        resolved = og.resolve_unit_va_presets([self.subcentre.org_unit_id])

        entry = resolved[self.subcentre.org_unit_id]
        self.assertEqual(entry["hiv_mortality"]["value"], "high")
        self.assertEqual(entry["hiv_mortality"]["source_unit_id"], self.phc.org_unit_id)
        self.assertEqual(entry["hiv_mortality"]["source_unit_name"], "Yelahanka PHC")
        self.assertEqual(entry["malaria_mortality"]["value"], "low")

    def test_inherited_from_grandparent_skips_ungated_parent(self):
        org.set_unit_va_presets(self.PROJECT, self.district.org_unit_id, hiv_mortality="veryl", malaria_mortality=None)
        db.session.commit()

        resolved = og.resolve_unit_va_presets([self.subcentre.org_unit_id])

        self.assertEqual(resolved[self.subcentre.org_unit_id]["hiv_mortality"]["value"], "veryl")
        self.assertEqual(
            resolved[self.subcentre.org_unit_id]["hiv_mortality"]["source_unit_id"], self.district.org_unit_id
        )

    def test_fields_resolve_independently_from_different_ancestors(self):
        # CHC sets malaria only; PHC (its child) sets hiv only. Sub-centre
        # must inherit hiv from PHC (nearer) and malaria from CHC (further),
        # never mixing the nearest row's missing field with a default.
        org.set_unit_va_presets(self.PROJECT, self.chc.org_unit_id, hiv_mortality=None, malaria_mortality="high")
        org.set_unit_va_presets(self.PROJECT, self.phc.org_unit_id, hiv_mortality="low", malaria_mortality=None)
        db.session.commit()

        entry = og.resolve_unit_va_presets([self.subcentre.org_unit_id])[self.subcentre.org_unit_id]

        self.assertEqual(entry["hiv_mortality"]["value"], "low")
        self.assertEqual(entry["hiv_mortality"]["source_unit_id"], self.phc.org_unit_id)
        self.assertEqual(entry["malaria_mortality"]["value"], "high")
        self.assertEqual(entry["malaria_mortality"]["source_unit_id"], self.chc.org_unit_id)

    def test_no_value_on_any_ancestor_is_simply_absent(self):
        resolved = og.resolve_unit_va_presets([self.sibling_chc.org_unit_id])

        self.assertEqual(resolved.get(self.sibling_chc.org_unit_id, {}), {})

    def test_resolve_va_presets_keys_by_question_name(self):
        org.set_unit_va_presets(self.PROJECT, self.phc.org_unit_id, hiv_mortality="high", malaria_mortality="low")
        db.session.commit()

        answers = og.resolve_va_presets(self.phc.org_unit_id)

        self.assertEqual(answers, {"Id10002": "high", "Id10003": "low"})

    def test_resolve_va_presets_empty_when_nothing_configured(self):
        self.assertEqual(og.resolve_va_presets(self.sibling_chc.org_unit_id), {})

    def test_resolution_is_a_single_query_regardless_of_unit_count(self):
        org.set_unit_va_presets(self.PROJECT, self.district.org_unit_id, hiv_mortality="high", malaria_mortality="low")
        db.session.commit()
        # Read every id before starting the listener: after commit() these
        # ORM objects are expired, and .org_unit_id would otherwise trigger
        # its own refresh SELECT per object -- a test artifact, not a cost
        # resolve_unit_va_presets itself incurs.
        unit_ids = [
            self.district.org_unit_id, self.chc.org_unit_id, self.phc.org_unit_id,
            self.subcentre.org_unit_id, self.sibling_chc.org_unit_id,
        ]

        statements = []

        def record(conn, cursor, statement, parameters, ctx, executemany):
            statements.append(statement)

        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            og.resolve_unit_va_presets(unit_ids)
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(len(statements), 1)

    # -- admin management -------------------------------------------------

    def test_set_validates_value(self):
        with self.assertRaises(org.OrganizationError):
            org.set_unit_va_presets(self.PROJECT, self.phc.org_unit_id, hiv_mortality="bogus", malaria_mortality=None)

    def test_set_then_clear_removes_the_row(self):
        org.set_unit_va_presets(self.PROJECT, self.phc.org_unit_id, hiv_mortality="high", malaria_mortality="low")
        db.session.commit()
        self.assertIsNotNone(org.get_unit_va_presets(self.PROJECT, self.phc.org_unit_id))

        cleared = org.clear_unit_va_presets(self.PROJECT, self.phc.org_unit_id)
        db.session.commit()

        self.assertTrue(cleared)
        self.assertIsNone(org.get_unit_va_presets(self.PROJECT, self.phc.org_unit_id))

    def test_clear_of_unset_unit_returns_false(self):
        self.assertFalse(org.clear_unit_va_presets(self.PROJECT, self.sibling_chc.org_unit_id))
