"""The PII field registry and the redaction it drives.

Covers the two properties the design depends on: a flagged field is visible to
export redaction, and it is still invisible to the coding screen. Also covers
the regression that motivated the field_id -> form_type restructure: a
registry scoped to one form type left every other form type's copy of the
same fields unredacted.
"""

import sqlalchemy as sa

from app import db
from app.models import MasFieldDisplayConfig, MasFormTypes
from app.services.data_management_service import _filter_export_payload
from app.services.field_mapping_service import PiiSetStatus, get_mapping_service
from app.services.form_type_service import get_form_type_service
from app.services.odk_schema_sync_service import get_sync_service
from app.services.pii_field_registry import PII_FIELDS, apply_pii_field_registry
from tests.base import BaseTestCase


FORM_TYPE_CODE = "WHO_2022_VA"


class PiiFieldRegistryTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.form_type = db.session.scalar(
            sa.select(MasFormTypes).where(MasFormTypes.form_type_code == FORM_TYPE_CODE)
        )
        if self.form_type is None:
            self.form_type = MasFormTypes(
                form_type_code=FORM_TYPE_CODE,
                form_type_name="WHO 2022 VA",
                is_active=True,
            )
            db.session.add(self.form_type)
            db.session.flush()
        get_mapping_service().clear_cache()

    def tearDown(self):
        get_mapping_service().clear_cache()
        super().tearDown()

    def _config_for(self, field_id, form_type=None):
        form_type = form_type or self.form_type
        return db.session.scalar(
            sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                MasFieldDisplayConfig.field_id == field_id,
            )
        )

    def test_creates_redaction_only_rows_for_unmapped_fields(self):
        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        row = self._config_for("Id10017")  # given name(s) of the deceased
        self.assertIsNotNone(row, "expected a config row for the deceased's given name")
        self.assertTrue(row.is_pii)
        self.assertEqual(row.pii_type, "name")
        self.assertTrue(row.is_active)
        # Load-bearing: _build_fieldsitepi requires a non-NULL subcategory, so a
        # NULL one keeps the field out of the coding screen entirely.
        self.assertIsNone(row.subcategory_code)
        self.assertIsNone(row.category_code)

    def test_flags_the_abha_identifiers_web_intake_adds(self):
        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        for field_id in ("abha_number", "abha_address"):
            row = self._config_for(field_id)
            self.assertIsNotNone(row, f"expected a config row for {field_id}")
            self.assertTrue(row.is_pii)
            self.assertEqual(row.pii_type, "identifier")

    def test_flags_an_existing_mapped_row_without_disturbing_its_mapping(self):
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=self.form_type.form_type_id,
                field_id="Id10057",
                category_code="vademographicdetails",
                subcategory_code="place",
                short_label="Where the death occurred",
                is_active=True,
            )
        )
        db.session.flush()

        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        row = self._config_for("Id10057")
        self.assertTrue(row.is_pii)
        self.assertEqual(row.pii_type, "location")
        # The mapping itself is untouched: flagging is not unmapping.
        self.assertEqual(row.category_code, "vademographicdetails")
        self.assertEqual(row.subcategory_code, "place")
        self.assertEqual(row.short_label, "Where the death occurred")

    def test_preserves_a_classification_an_operator_already_chose(self):
        """pii_type is the admin panel's to set; the registry only adds is_pii."""
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=self.form_type.form_type_id,
                field_id="Id10057",
                category_code="vademographicdetails",
                subcategory_code="general",
                is_pii=True,
                pii_type="somebody_elses_label",
                is_active=True,
            )
        )
        db.session.flush()

        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        self.assertEqual(self._config_for("Id10057").pii_type, "somebody_elses_label")

    def test_is_idempotent(self):
        first = apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()
        second = apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        self.assertEqual(first["created"], len(PII_FIELDS))
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["unchanged"], len(PII_FIELDS))

        count = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                MasFieldDisplayConfig.field_id.in_(list(PII_FIELDS)),
            )
        )
        self.assertEqual(count, len(PII_FIELDS))

    def test_reapplies_after_a_mapping_reseed_clears_the_flag(self):
        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()
        row = self._config_for("Id10073")
        row.is_pii = False
        row.pii_type = None
        db.session.flush()

        totals = apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        self.assertEqual(totals["updated"], 1)
        self.assertTrue(self._config_for("Id10073").is_pii)

    def test_get_pii_field_ids_sees_every_registered_field(self):
        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()
        get_mapping_service().clear_cache()

        pii_ids = get_mapping_service().get_pii_field_ids(FORM_TYPE_CODE)

        self.assertEqual(set(PII_FIELDS) - pii_ids, set())

    def test_flagged_fields_are_not_rendered_on_the_coding_screen(self):
        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()
        get_mapping_service().clear_cache()

        rendered = set()
        for subcategories in get_mapping_service().get_fieldsitepi(FORM_TYPE_CODE).values():
            for fields in subcategories.values():
                rendered.update(fields)

        leaked = rendered & set(PII_FIELDS)
        self.assertEqual(leaked, set(), f"PII fields reached the coding screen: {leaked}")

    # --- Regression coverage for the field_id -> form_type restructure ---

    def test_flag_lands_on_every_form_type_holding_the_field_not_just_one(self):
        """The bug this whole change fixes: a second form type cloned from
        WHO_2022_VA (e.g. WHO_2022_VA_SOCIAL) has its own config rows for the
        same field ids. Applying the registry with no form_type_code must flag
        every active form type's copy, not only the first one it finds.
        """
        other = MasFormTypes(
            form_type_code="WHO_2022_VA_SOCIAL",
            form_type_name="WHO 2022 VA (social autopsy)",
            is_active=True,
        )
        db.session.add(other)
        db.session.flush()

        # Both form types carry their own unflagged copy of the national ID
        # field, the way a clone made before WHO_2022_VA was ever flagged
        # would.
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=self.form_type.form_type_id,
                field_id="Id10073",
                is_active=True,
            )
        )
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=other.form_type_id,
                field_id="Id10073",
                is_active=True,
            )
        )
        db.session.flush()

        # Applying for all active form types (no form_type_code) must reach
        # both.
        apply_pii_field_registry()
        db.session.flush()

        self.assertTrue(self._config_for("Id10073", self.form_type).is_pii)
        self.assertTrue(self._config_for("Id10073", other).is_pii)

    def test_a_pii_field_that_is_deactivated_stays_in_the_redaction_set(self):
        """is_active governs the coding screen, not redaction. A field marked
        PII must stay redacted even after being deactivated.
        """
        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        row = self._config_for("Id10073")
        row.is_active = False
        db.session.flush()
        get_mapping_service().clear_cache()

        pii_ids = get_mapping_service().get_pii_field_ids(FORM_TYPE_CODE)

        self.assertIn("Id10073", pii_ids)

    def test_applying_the_registry_does_not_reactivate_a_deactivated_row(self):
        """The registry used to force is_active=True on every row it touched,
        which could resurrect a field an operator had deliberately turned off
        onto the coding screen. Flagging a field for redaction must not flip
        its display flag.
        """
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=self.form_type.form_type_id,
                field_id="Id10057",
                category_code="vademographicdetails",
                subcategory_code="place",
                is_active=False,
            )
        )
        db.session.flush()

        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        row = self._config_for("Id10057")
        self.assertTrue(row.is_pii)
        self.assertFalse(row.is_active, "applying the registry reactivated a deactivated row")


class ExportRedactionTests(BaseTestCase):
    """_filter_export_payload is the one consumer of the PII set."""

    def test_drops_flagged_fields_and_keeps_clinical_answers(self):
        payload = {
            "Id10017": "Given",
            "Id10018": "Surname",
            "Id10073": "1234-5678-9012",
            "abha_number": "12-3456-7890-1234",
            "abha_address": "someone@abdm",
            "Id10019": "female",  # sex: a coding input, never redacted
            "Id10022": "yes",
        }

        filtered = _filter_export_payload(
            payload,
            form_id="TF01",
            pii_status_by_form={
                "TF01": PiiSetStatus(
                    confirmed=True,
                    field_ids=frozenset(PII_FIELDS),
                    owned_flagged_count=len(PII_FIELDS),
                )
            },
        )

        self.assertNotIn("Id10017", filtered)
        self.assertNotIn("Id10018", filtered)
        self.assertNotIn("Id10073", filtered)
        self.assertNotIn("abha_number", filtered)
        self.assertNotIn("abha_address", filtered)
        self.assertEqual(filtered["Id10019"], "female")
        self.assertEqual(filtered["Id10022"], "yes")


class FormTypeCloneTests(BaseTestCase):
    """A form type created after this change must not start unredacted."""

    def setUp(self):
        super().setUp()
        self.source = db.session.scalar(
            sa.select(MasFormTypes).where(MasFormTypes.form_type_code == FORM_TYPE_CODE)
        )
        if self.source is None:
            self.source = MasFormTypes(
                form_type_code=FORM_TYPE_CODE,
                form_type_name="WHO 2022 VA",
                is_active=True,
            )
            db.session.add(self.source)
            db.session.flush()
        get_mapping_service().clear_cache()

    def tearDown(self):
        get_mapping_service().clear_cache()
        super().tearDown()

    def test_cloning_an_unflagged_form_type_flags_the_clone_immediately(self):
        # Source rows are unflagged, the way WHO_2022_VA was before it was
        # ever flagged and WHO_2022_VA_SOCIAL was cloned from it.
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=self.source.form_type_id,
                field_id="Id10073",
                is_active=True,
                is_pii=False,
            )
        )
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=self.source.form_type_id,
                field_id="Id10017",
                category_code="vademographicdetails",
                subcategory_code="respondent",
                is_active=True,
                is_pii=False,
            )
        )
        db.session.flush()

        new_ft = get_form_type_service().duplicate_form_type(
            FORM_TYPE_CODE, "WHO_2022_VA_CLONE_TEST", "Clone under test"
        )

        cloned_id_row = db.session.scalar(
            sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == new_ft.form_type_id,
                MasFieldDisplayConfig.field_id == "Id10073",
            )
        )
        cloned_name_row = db.session.scalar(
            sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == new_ft.form_type_id,
                MasFieldDisplayConfig.field_id == "Id10017",
            )
        )
        self.assertIsNotNone(cloned_id_row)
        self.assertTrue(
            cloned_id_row.is_pii,
            "clone was not flagged by the registry without a seed run",
        )
        self.assertTrue(cloned_name_row.is_pii)


class OdkSyncRegistrationTests(BaseTestCase):
    """A form type born through ODK schema sync must not start unredacted.

    ``register_form_type`` creates a form type with zero field rows. Before
    an admin ever runs ``flask seed run`` again, an ODK schema sync can
    register a brand-new field row for a national-ID-shaped field such as
    ``Id10073``. That row must come out flagged without any seed run, or the
    data-manager CSV export includes it until someone thinks to reseed.
    """

    def setUp(self):
        super().setUp()
        self.form_type = MasFormTypes(
            form_type_code="WHO_2022_VA_ODK_SYNC_TEST",
            form_type_name="ODK sync test form type",
            is_active=True,
        )
        db.session.add(self.form_type)
        db.session.flush()
        get_mapping_service().clear_cache()

    def tearDown(self):
        get_mapping_service().clear_cache()
        super().tearDown()

    def test_sync_selected_flags_a_newly_registered_national_id_field(self):
        # The form type starts with no field rows at all — the state
        # register_form_type leaves it in.
        self.assertIsNone(
            db.session.scalar(
                sa.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == "Id10073",
                )
            )
        )

        stats = get_sync_service().sync_selected(
            self.form_type.form_type_code,
            {
                "new_fields": [
                    {
                        "field_id": "Id10073",
                        "field_type": "string",
                        "odk_label": "National identification number",
                    }
                ]
            },
        )

        self.assertEqual(stats["errors"], [])
        row = db.session.scalar(
            sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "Id10073",
            )
        )
        self.assertIsNotNone(row, "expected sync_selected to register the field")
        self.assertTrue(
            row.is_pii,
            "field registered by ODK sync was not flagged by the PII registry",
        )

    def test_sync_form_choices_flags_a_newly_registered_national_id_field(self):
        # sync_form_choices, not sync_selected, is the branch flask odk-sync
        # and the admin sync route actually call. It registers new fields
        # from an ODK XLSForm download rather than an admin-selected list.
        self.assertIsNone(
            db.session.scalar(
                sa.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                    MasFieldDisplayConfig.field_id == "Id10073",
                )
            )
        )

        from unittest.mock import patch

        sync_service = get_sync_service()
        stub_fields = [
            {
                "name": "Id10073",
                "type": "string",
                "label": {"default": "National identification number"},
            }
        ]
        with patch.object(sync_service, "_fetch_from_xlsx", return_value=stub_fields):
            stats = sync_service.sync_form_choices(
                self.form_type.form_type_code,
                odk_project_id=1,
                odk_form_id="who_2022_va",
                client=object(),
            )

        self.assertEqual(stats["errors"], [])
        row = db.session.scalar(
            sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "Id10073",
            )
        )
        self.assertIsNotNone(row, "expected sync_form_choices to register the field")
        self.assertTrue(
            row.is_pii,
            "field registered by sync_form_choices was not flagged by the PII registry",
        )


class SeedWiringTests(BaseTestCase):
    """The registry is only as good as the path that applies it.

    The flag was inert for a long time precisely because nothing in the seed
    path set it: a fresh install or a mapping reseed produced an empty PII set
    and the export fell back to a hardcoded list that does not cover the
    questionnaire's name fields. A control everyone believes is on, that is
    off, is worse than no control. These guard the wiring, not the registry.
    """

    def test_seed_run_applies_the_pii_flags(self):
        """Removing the step from the seed pipeline must fail a test."""
        from unittest.mock import patch

        import app.commands.seed as seed_cmd

        with (
            patch.object(seed_cmd, "_seed_languages"),
            patch.object(seed_cmd, "_seed_admin"),
            patch.object(seed_cmd, "_seed_form_types"),
            patch.object(seed_cmd, "_seed_who_2022_va_fields"),
            patch.object(seed_cmd, "_seed_pii_flags") as applied,
        ):
            seed_cmd.seed_run.callback(test=False)

        self.assertTrue(
            applied.called,
            "flask seed run no longer applies the PII field registry; a fresh "
            "install would export unredacted name fields",
        )

    def test_flags_are_restored_after_a_mapping_reseed_clears_them(self):
        """A reseed rewrites field rows with is_pii back at its default."""
        from unittest.mock import patch

        import app.commands.seed as seed_cmd

        form_type = db.session.scalar(
            sa.select(MasFormTypes).where(MasFormTypes.form_type_code == FORM_TYPE_CODE)
        )
        if form_type is None:
            form_type = MasFormTypes(
                form_type_code=FORM_TYPE_CODE, form_type_name="WHO 2022 VA", is_active=True
            )
            db.session.add(form_type)
            db.session.flush()

        apply_pii_field_registry(FORM_TYPE_CODE)
        db.session.flush()

        db.session.execute(
            sa.update(MasFieldDisplayConfig)
            .where(MasFieldDisplayConfig.form_type_id == form_type.form_type_id)
            .values(is_pii=False, pii_type=None)
        )
        db.session.flush()
        get_mapping_service().clear_cache()
        self.assertEqual(get_mapping_service().get_pii_field_ids(FORM_TYPE_CODE), set())

        # The seed step commits; inside the suite's savepoint, flush instead.
        with patch.object(db.session, "commit", db.session.flush):
            seed_cmd._seed_pii_flags()
        get_mapping_service().clear_cache()

        restored = get_mapping_service().get_pii_field_ids(FORM_TYPE_CODE)
        self.assertNotEqual(restored, set(), "a reseed left the PII set empty")
        self.assertIn("Id10073", restored)
