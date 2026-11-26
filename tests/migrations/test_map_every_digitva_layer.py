"""``f3c9d1a7b5e2`` makes the WHO_2022_VA field mapping cover every DigitVA
layer (digitva-l2dg).

Builds a throwaway database at the previous head with a small, deliberately
differing mapping for both form types (and a third form type that must not be
touched), upgrades, checks the target rows, the named-field decisions, the
engine answer labels (existing WHO_2022_VA_SOCIAL ODK labels kept) and the
untouched rows, downgrades (both form types' rows, their choice rows and the
category tables come back exactly), then upgrades again with
WHO_2022_VA_SOCIAL emptied (skipped). The frozen labels are checked against
the engine's composed definition and the workbook seed.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_map_every_digitva_layer.py -q
"""
import importlib.util
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_l2dg_layer_mig"

PREVIOUS_HEAD = "e7a4c2f9b1d3"
REVISION = "f3c9d1a7b5e2"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations/versions/f3c9d1a7b5e2_map_every_digitva_layer_on_who_2022_va.py"
)
BACKUP = "_mig_bak_field_display_config_f3c9d1a7b5e2"
CHOICE_BACKUP = "_mig_bak_choice_mappings_f3c9d1a7b5e2"
LEDGER = "_mig_f3c9d1a7b5e2_inserted"


def _migration_module():
    spec = importlib.util.spec_from_file_location("l2dg_migration", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class LayerMappingMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(hide_password=False)


def _admin_execute(*statements):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{MIGRATION_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"',
    )


FORM_TYPE_SQL = (
    "INSERT INTO mas_form_types (form_type_id, form_type_code, form_type_name, mapping_version, "
    "is_active, created_at, updated_at, base_instrument_code) "
    "VALUES (:id, :code, :code, 1, true, now(), now(), 'WHO_2022_VA')"
)
FIELD_SQL = (
    "INSERT INTO mas_field_display_config (config_id, form_type_id, field_id, category_code, "
    "subcategory_code, short_label, full_label, field_type, flip_color, is_info, summary_include, "
    "is_pii, pii_type, display_order, is_active, is_custom, created_at, updated_at) "
    "VALUES (gen_random_uuid(), :ft, :field_id, :cat, :sub, :label, :label, :type, false, false, "
    "false, :pii, :pii_type, :ord, true, :custom, '2026-01-01', '2026-01-01')"
)
CATEGORY_SQL = (
    "INSERT INTO mas_category_order (category_order_id, form_type_id, category_code, category_name, "
    "display_order, is_active) VALUES (gen_random_uuid(), :ft, 'vademographicdetails', 'Demo', 2, true)"
)
DISPLAY_SQL = (
    "INSERT INTO mas_category_display_config (category_display_config_id, form_type_id, category_code, "
    "display_label, nav_label, display_order, render_mode, created_at, updated_at) "
    "VALUES (gen_random_uuid(), :ft, 'vademographicdetails', 'Demo', 'Demo', 2, 'table_sections', now(), now())"
)
CHOICE_SQL = (
    "INSERT INTO mas_choice_mappings (choice_id, form_type_id, field_id, choice_value, choice_label, "
    "display_order, is_active, synced_at, created_at, updated_at) "
    "VALUES (gen_random_uuid(), :ft, :field_id, :value, :label, :ord, true, '2026-01-01', "
    "'2026-01-01', '2026-01-01')"
)
SUBCATEGORY_SQL = (
    "INSERT INTO mas_subcategory_order (subcategory_order_id, form_type_id, category_code, "
    "subcategory_code, subcategory_name, display_order, is_active, render_mode) "
    "VALUES (gen_random_uuid(), :ft, 'vademographicdetails', :sub, :sub, :ord, true, 'default')"
)


def _field(ft, field_id, cat=None, sub=None, label=None, type_=None, pii=False, pii_type=None,
           order=1, custom=False):
    return {"ft": ft, "field_id": field_id, "cat": cat, "sub": sub, "label": label, "type": type_,
            "pii": pii, "pii_type": pii_type, "ord": Decimal(order), "custom": custom}


def _seed(db, who, social, other):
    for form_type_id, code in ((who, "WHO_2022_VA"), (social, "WHO_2022_VA_SOCIAL"), (other, "PHMRC_TEST")):
        db.session.execute(sa.text(FORM_TYPE_SQL), {"id": form_type_id, "code": code})
    rows = []
    for ft in (who, social):
        rows += [
            _field(ft, "Id10021", "vademographicdetails", "general", "(Id10021) Birth date", "date", order=21),
            _field(ft, "Id10186", "vaabdominalsymptoms", "bleeding", "(Id10186) Blood", "select_one", order=231),
            _field(ft, "Id10233", "vaskinmucosalsymptoms", "skin_rash", "(Id10233) Skin rash", "select_one", order=287),
            # An admin edit the migration must leave alone.
            _field(ft, "Id10019", "vademographicdetails", "general", "Sex (edited by an admin)", "select_one", order=33),
        ]
    rows += [
        _field(who, "Id10023", "vademographicdetails", "general", "(Id10023) Death date", "calculate", order=22),
        _field(who, "Id10010c", "vainterviewdetails", "va_interviewer", "(Id10010c) ID", "text", True, "staff_id", 4),
        _field(who, "Id10073", pii=True, pii_type="identifier", order=0, custom=True),
        # Already present on WHO with an admin's label: kept, not duplicated.
        _field(who, "sa01", "social_autopsy", "social-autopsy", "Insurance (admin label)", "select_one", order=10),
        _field(social, "Id10023", "vademographicdetails", "general", "(Id10023) Death date", "calculate", True, "date", 22),
        _field(social, "Id10010c", "vainterviewdetails", "va_interviewer", "(Id10010c) ID", "text", True, "identifier", 4),
        # Present but unflagged: the owner decision flags it.
        _field(social, "social_group", "vademographicdetails", "equity", "Group", "select_one", order=63),
        _field(other, "Id10023", "general", "general", "Other form's death date", "date", True, "date", 1),
    ]
    db.session.execute(sa.text(FIELD_SQL), rows)
    db.session.execute(sa.text(CHOICE_SQL), [
        # SOCIAL's ODK label for a value the engine labels "None": kept.
        {"ft": social, "field_id": "sa01", "value": "6", "label": "Others", "ord": 6},
        # A site-specific ODK value the engine never emits: kept.
        {"ft": social, "field_id": "sa01", "value": "99", "label": "Site value", "ord": 7},
        # Not a labelled field, and another form type's row: neither is touched.
        {"ft": who, "field_id": "Id10019", "value": "female", "label": "Female", "ord": 2},
        {"ft": other, "field_id": "sa01", "value": "1", "label": "Other form", "ord": 1},
    ])
    for ft in (who, social):
        db.session.execute(sa.text(CATEGORY_SQL), {"ft": ft})
        db.session.execute(sa.text(DISPLAY_SQL), {"ft": ft})
        for order, sub in enumerate(("general", "risk_factors"), start=1):
            db.session.execute(sa.text(SUBCATEGORY_SQL), {"ft": ft, "sub": sub, "ord": order})


def _snapshot(db):
    """Every mapping row the migration may touch, as comparable tuples."""
    out = {}
    for table, key in (
        ("mas_field_display_config", "config_id"),
        ("mas_category_order", "category_order_id"),
        ("mas_category_display_config", "category_display_config_id"),
        ("mas_subcategory_order", "subcategory_order_id"),
        ("mas_choice_mappings", "choice_id"),
    ):
        out[table] = [tuple(row) for row in db.session.execute(sa.text(f"SELECT * FROM {table} ORDER BY {key}"))]
    return out


def _row(db, ft, field_id):
    return db.session.execute(sa.text(
        "SELECT * FROM mas_field_display_config WHERE form_type_id = :ft AND field_id = :f"
    ), {"ft": ft, "f": field_id}).mappings().one_or_none()


def _field_ids(db, ft):
    return set(db.session.scalars(sa.text(
        "SELECT field_id FROM mas_field_display_config WHERE form_type_id = :ft"
    ), {"ft": ft}))


def _choices(db, ft):
    """``{(field_id, value): row}`` of one form type's choice rows."""
    return {
        (row["field_id"], row["choice_value"]): dict(row)
        for row in db.session.execute(sa.text(
            "SELECT * FROM mas_choice_mappings WHERE form_type_id = :ft"
        ), {"ft": ft}).mappings()
    }


def _tables(db):
    return set(db.session.scalars(sa.text(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE '\\_mig\\_%f3c9d1a7b5e2%'"
    )))


class MapEveryDigitvaLayerMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_completes_both_mappings_and_downgrade_restores_them_exactly(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        migration = _migration_module()
        target_ids = {row["field_id"] for row in migration._target_rows()}
        self.assertEqual(len(target_ids), 108 + 11 + 19)
        who, social, other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(LayerMappingMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                _seed(db, who, social, other)
                db.session.commit()
                before = _snapshot(db)
                untouched_before = {ft: dict(_row(db, ft, "Id10019")) for ft in (who, social)}
                sa01_before = dict(_row(db, who, "sa01"))
                choices_before = {ft: _choices(db, ft) for ft in (who, social, other)}
                other_before = dict(_row(db, other, "Id10023"))
                db.session.remove()

                alembic_upgrade(revision=REVISION)

                # Both form types now hold every target row, once.
                for ft in (who, social):
                    ids = _field_ids(db, ft)
                    self.assertTrue(target_ids <= ids, sorted(target_ids - ids))
                    self.assertEqual(db.session.scalar(sa.text(
                        "SELECT count(*) - count(DISTINCT field_id) FROM mas_field_display_config "
                        "WHERE form_type_id = :ft"
                    ), {"ft": ft}), 0)

                # Placements and flags of inserted rows.
                dob = _row(db, who, "dob_precision")
                self.assertEqual((dob["category_code"], dob["subcategory_code"], dob["display_order"]),
                                 ("vademographicdetails", "general", Decimal("21.10")))
                self.assertFalse(dob["is_pii"])
                for ft in (who, social):
                    vulnerable = _row(db, ft, "vulnerable_group_custody")
                    self.assertTrue(vulnerable["is_pii"])
                    self.assertEqual(vulnerable["pii_type"], "identifier")
                    self.assertFalse(vulnerable["summary_include"])
                    residence = _row(db, ft, "residence_type")
                    self.assertFalse(residence["is_pii"])
                    self.assertEqual(residence["subcategory_code"], "equity")
                self.assertTrue(_row(db, who, "sa02")["is_info"])
                self.assertIsNone(_row(db, who, "today")["category_code"])
                # The present-but-unflagged equity row is flagged, nothing else about it changes.
                group = _row(db, social, "social_group")
                self.assertEqual((group["is_pii"], group["pii_type"], group["short_label"]),
                                 (True, "identifier", "Group"))

                # Named decisions, on both form types.
                for ft in (who, social):
                    death = _row(db, ft, "Id10023")
                    self.assertEqual((death["is_pii"], death["pii_type"]), (False, None))
                    self.assertEqual(_row(db, ft, "Id10010c")["pii_type"], "staff_id")
                    self.assertEqual(_row(db, ft, "Id10186")["subcategory_code"], "diarrhoea")
                    self.assertEqual(_row(db, ft, "Id10233")["display_order"], Decimal("10"))
                # Id10073 gains SOCIAL's label and type; is_custom is not decided.
                national_id = _row(db, who, "Id10073")
                self.assertEqual(national_id["short_label"], migration.ID10073_LABEL)
                self.assertEqual(national_id["full_label"], migration.ID10073_LABEL)
                self.assertEqual(national_id["field_type"], "text")
                self.assertTrue(national_id["is_custom"])
                # A missing named field is not created (the PII registry owns Id10073's row).
                self.assertIsNone(_row(db, social, "Id10073"))

                # Untouched rows stay byte for byte, updated_at included.
                for ft in (who, social):
                    self.assertEqual(dict(_row(db, ft, "Id10019")), untouched_before[ft])
                self.assertEqual(dict(_row(db, who, "sa01")), sa01_before)
                self.assertEqual(dict(_row(db, other, "Id10023")), other_before)
                self.assertEqual(_field_ids(db, other), {"Id10023"})

                # The categories the inserted rows need.
                for ft in (who, social):
                    subs = set(db.session.scalars(sa.text(
                        "SELECT category_code || '/' || subcategory_code FROM mas_subcategory_order "
                        "WHERE form_type_id = :ft"
                    ), {"ft": ft}))
                    self.assertIn("vademographicdetails/equity", subs)
                    self.assertIn("social_autopsy/social-autopsy", subs)
                    self.assertEqual(db.session.scalar(sa.text(
                        "SELECT display_order FROM mas_category_display_config "
                        "WHERE form_type_id = :ft AND category_code = 'social_autopsy'"
                    ), {"ft": ft}), 3)
                self.assertEqual(db.session.scalar(sa.text(f"SELECT count(*) FROM {BACKUP}")),
                                 len(before["mas_field_display_config"]) - 1)

                # Engine answer labels: every one on WHO_2022_VA; on SOCIAL the
                # missing ones only, the existing ODK rows byte for byte.
                engine = {(row["field_id"], row["choice_value"]): row for row in migration._choice_rows()}
                self.assertEqual(len(engine), 168)
                who_choices, social_choices = _choices(db, who), _choices(db, social)
                for key, expected in engine.items():
                    self.assertEqual(
                        (who_choices[key]["choice_label"], who_choices[key]["display_order"],
                         who_choices[key]["is_active"]),
                        (expected["choice_label"], expected["display_order"], True),
                        key,
                    )
                self.assertEqual(who_choices[("sa01", "6")]["choice_label"], "None")
                self.assertEqual(who_choices[("Id10019", "female")], choices_before[who][("Id10019", "female")])
                self.assertEqual(social_choices[("sa01", "6")], choices_before[social][("sa01", "6")])
                self.assertEqual(social_choices[("sa01", "99")], choices_before[social][("sa01", "99")])
                self.assertEqual(social_choices[("sa01", "3")]["choice_label"], "Ayushman Bharat")
                self.assertEqual(set(social_choices), set(engine) | {("sa01", "99")})
                self.assertEqual(_choices(db, other), choices_before[other])
                self.assertEqual(db.session.scalar(sa.text(f"SELECT count(*) FROM {CHOICE_BACKUP}")), 2)
                self.assertEqual(db.session.scalar(sa.text(
                    f"SELECT count(*) FROM {LEDGER} WHERE table_name = 'mas_choice_mappings'"
                )), 168 + 167)
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertEqual(_snapshot(db), before)
                self.assertEqual(_tables(db), set())
                db.session.remove()

                # Re-upgrade with WHO_2022_VA_SOCIAL unseeded: it is skipped.
                db.session.execute(sa.text(
                    "DELETE FROM mas_field_display_config WHERE form_type_id = :ft"
                ), {"ft": social})
                db.session.commit()
                alembic_upgrade(revision=REVISION)
                self.assertEqual(_field_ids(db, social), set())
                self.assertTrue(target_ids <= _field_ids(db, who))
                self.assertEqual(_choices(db, social), choices_before[social])
                self.assertEqual(len(_choices(db, who)), 168 + 1)
                self.assertEqual(_tables(db), {BACKUP, CHOICE_BACKUP, LEDGER})
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


class EngineChoiceLabelsTest(unittest.TestCase):
    """The migration's frozen answer labels are the engine's: every select field
    of its sa*, equity and DORIS-support rows, with the composed definition's
    values and English labels in form order."""

    def test_frozen_labels_equal_the_composed_definition(self):
        import json

        migration = _migration_module()
        composed = json.loads(
            (Path(__file__).resolve().parents[2] / "app/data/who-va-2022.composed.json").read_text(encoding="utf-8")
        )
        questions = {question["name"]: question for question in composed["questions"]}
        # The uncategorised ODK helper rows are not a layer's questions.
        selects = {row["field_id"] for row in migration._target_rows()
                   if row["category_code"] is not None and row["field_type"].startswith("select")}
        self.assertEqual(selects, set(migration.ENGINE_CHOICE_FIELDS))
        expected = [
            {"field_id": field_id, "choice_value": choice["value"], "choice_label": choice["label"]["en"],
             "display_order": order}
            for field_id in migration.ENGINE_CHOICE_FIELDS
            for order, choice in enumerate(questions[field_id]["choices"], start=1)
        ]
        self.assertEqual(migration._choice_rows(), expected)
        self.assertEqual(len(expected), 168)


if __name__ == "__main__":
    unittest.main()


from tests.base import BaseTestCase  # noqa: E402  (BaseTestCase needs the session app)


class LayerMappingSeedParityTest(BaseTestCase):
    """A fresh install seeded from the workbook carries the rows the migration
    adds, with the same values, so a migrated database and a new one agree.

    Compared on every column the migration writes. ``odk_label`` and the
    timestamps are provenance, not mapping, and are not compared.
    """

    def test_workbook_seed_matches_the_migration_rows_and_decisions(self):
        from app import db
        from app.models import MasCategoryDisplayConfig, MasFieldDisplayConfig, MasFormTypes
        from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator

        migration = _migration_module()
        Who2022VaMigrator().run()
        form_type = db.session.scalar(
            sa.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )
        seeded = {
            row.field_id: row
            for row in db.session.scalars(
                sa.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id
                )
            )
        }
        columns = (
            "category_code", "subcategory_code", "short_label", "full_label", "field_type",
            "age_group", "is_info", "is_pii", "pii_type", "display_order",
        )
        target = migration._target_rows()
        self.assertEqual(len(target), 138)
        for expected in target:
            row = seeded.get(expected["field_id"])
            self.assertIsNotNone(row, expected["field_id"])
            self.assertEqual(
                {column: getattr(row, column) for column in columns},
                {column: expected[column] for column in columns},
                expected["field_id"],
            )
            self.assertEqual(
                (row.summary_label, row.flip_color, row.summary_include, row.is_active, row.is_custom),
                (None, False, False, True, False),
                expected["field_id"],
            )

        self.assertEqual((seeded["Id10023"].is_pii, seeded["Id10023"].pii_type), (False, None))
        self.assertEqual(seeded["Id10010c"].pii_type, "staff_id")
        self.assertEqual(seeded["Id10186"].subcategory_code, "diarrhoea")
        self.assertEqual(seeded["Id10073"].short_label, migration.ID10073_LABEL)
        self.assertEqual(seeded["Id10073"].full_label, migration.ID10073_LABEL)
        self.assertEqual(seeded["Id10073"].field_type, "text")
        for field_id, order in migration.SKIN_RASH_ORDER.items():
            self.assertEqual(seeded[field_id].display_order, Decimal(order))
        self.assertIsNotNone(db.session.scalar(
            sa.select(MasCategoryDisplayConfig).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
                MasCategoryDisplayConfig.category_code == "social_autopsy",
            )
        ))

    def test_workbook_seed_carries_the_migration_choice_labels(self):
        from app import db
        from app.models import MasChoiceMappings, MasFormTypes
        from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator

        migration = _migration_module()
        Who2022VaMigrator().run()
        form_type_id = db.session.scalar(
            sa.select(MasFormTypes.form_type_id).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )
        seeded = [
            {"field_id": row.field_id, "choice_value": row.choice_value,
             "choice_label": row.choice_label, "display_order": row.display_order}
            for row in db.session.scalars(
                sa.select(MasChoiceMappings)
                .where(
                    MasChoiceMappings.form_type_id == form_type_id,
                    MasChoiceMappings.field_id.in_(migration.ENGINE_CHOICE_FIELDS),
                )
                .order_by(MasChoiceMappings.field_id, MasChoiceMappings.display_order)
            )
        ]
        expected = sorted(migration._choice_rows(), key=lambda row: (row["field_id"], row["display_order"]))
        self.assertEqual(seeded, expected)
        # "None" is a label, not a missing cell.
        self.assertIn({"field_id": "sa01", "choice_value": "6", "choice_label": "None", "display_order": 6}, seeded)
