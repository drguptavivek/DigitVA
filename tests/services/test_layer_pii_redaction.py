"""PII rules for the DigitVA layer fields (digitva-l2dg, owner 2026-11-26).

``social_group`` and every ``vulnerable_group*`` answer are personal data and
redacted for a viewer without PII access; ``residence_type``,
``health_coverage`` and the ``refusal_*`` profile are not; the date of death
``Id10023`` stays visible to that viewer on both WHO form types.
"""

import sqlalchemy as sa

from app import db
from app.models import MasFieldDisplayConfig
from app.services.case_content_service import payload_for_viewer
from app.services.field_mapping_service import get_mapping_service
from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator
from app.services.pii_field_registry import sealed_field_ids
from tests.base import BaseTestCase
from tests.migrations.test_map_every_digitva_layer import _migration_module

PAYLOAD = {
    "Id10023": "2026-01-02",
    "social_group": "sc",
    "vulnerable_group": "custody",
    "vulnerable_group_child_no_care": "no",
    "vulnerable_group_female_head": "no",
    "vulnerable_group_elderly_alone": "no",
    "vulnerable_group_gender_minority": "no",
    "vulnerable_group_custody": "yes",
    "residence_type": "rural",
    "health_coverage": "pmjay",
    "refusal_age_group": "adult",
    "refusal_sex": "male",
}
PERSONAL = {key for key in PAYLOAD if key == "social_group" or key.startswith("vulnerable_group")}


class LayerFieldPiiTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        get_mapping_service().clear_cache()

    def tearDown(self):
        get_mapping_service().clear_cache()
        super().tearDown()

    def _prepare(self, code):
        """WHO_2022_VA as a fresh install seeds it; WHO_2022_VA_SOCIAL with the
        rows migration f3c9d1a7b5e2 adds and an unflagged Id10023 (the state
        the migration leaves)."""
        if code == "WHO_2022_VA":
            Who2022VaMigrator().run()
        else:
            form_type = self._ensure_form_type(code)
            have = set(db.session.scalars(
                sa.select(MasFieldDisplayConfig.field_id).where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id
                )
            ))
            rows = [
                {"field_id": "Id10023", "category_code": "vademographicdetails",
                 "subcategory_code": "general", "is_pii": False, "pii_type": None},
                *_migration_module()._target_rows(),
            ]
            for row in rows:
                if row["field_id"] not in have:
                    db.session.add(MasFieldDisplayConfig(
                        form_type_id=form_type.form_type_id,
                        field_id=row["field_id"],
                        category_code=row["category_code"],
                        subcategory_code=row["subcategory_code"],
                        is_pii=row["is_pii"],
                        pii_type=row["pii_type"],
                    ))
            db.session.flush()
        get_mapping_service().clear_cache()

    def test_equity_identity_answers_are_redacted_and_the_death_date_is_not(self):
        for code in ("WHO_2022_VA", "WHO_2022_VA_SOCIAL"):
            with self.subTest(form_type=code):
                self._prepare(code)
                full = payload_for_viewer(dict(PAYLOAD), code, redact_pii=False)
                self.assertEqual(set(full), set(PAYLOAD))  # the subject is present

                redacted = payload_for_viewer(dict(PAYLOAD), code, redact_pii=True)
                self.assertEqual(set(redacted), set(PAYLOAD) - PERSONAL)
                self.assertEqual(redacted["Id10023"], "2026-01-02")

    def test_the_equity_identity_answers_are_sealed_and_the_death_date_never(self):
        self._prepare("WHO_2022_VA")
        sealed = sealed_field_ids("WHO_2022_VA")
        self.assertTrue(PERSONAL <= sealed, sorted(PERSONAL - sealed))
        self.assertNotIn("Id10023", sealed)
        self.assertNotIn("residence_type", sealed)
        self.assertNotIn("health_coverage", sealed)
