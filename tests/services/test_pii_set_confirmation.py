"""A form type's PII set must be confirmed before anything is exported from it.

``apply_pii_field_registry`` creates redaction-only rows for every form type,
so "this form type has is_pii rows" says nothing about whether anyone has
considered its PII set. The derived signal is an is_pii row on a field the
form type *owns* — mapped, ODK-synced, or otherwise not registry-created.
Until then the viewer render and the submissions CSV export withhold the
payload rather than trust an answer nobody gave. The SmartVA input export is
the documented exemption: it is a processing feed, so it keeps stripping only
the flagged fields. See docs/policy/access-control-model.md, "The PII set
must be confirmed per form type".

Harness rule (docs/policy/test-harness.md): every "absent after" assertion
below is preceded by the matching "present before".
"""

import sqlalchemy as sa

from app import db
from app.models import MasFieldDisplayConfig
from app.services.data_management_service import _filter_export_payload
from app.services.field_mapping_service import PiiSetStatus, get_mapping_service
from app.services.form_type_service import get_form_type_service
from app.services.pii_field_registry import PII_FIELDS, apply_pii_field_registry
from tests.base import BaseTestCase


class PiiSetConfirmationTests(BaseTestCase):
    """The derived confirmation rule."""

    def setUp(self):
        super().setUp()
        get_mapping_service().clear_cache()

    def tearDown(self):
        get_mapping_service().clear_cache()
        super().tearDown()

    def _register(self, code, name):
        form_type = get_form_type_service().register_form_type(code, name)
        db.session.flush()
        return form_type

    def _config_for(self, form_type, field_id):
        return db.session.scalar(
            sa.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                MasFieldDisplayConfig.field_id == field_id,
            )
        )

    def test_registry_only_form_type_is_unconfirmed_but_not_empty(self):
        """A PHMRC-shaped import: every row the registry created, none of its
        own. Unconfirmed — and the set is still non-empty, so a caller cannot
        mistake "unconfirmed" for "no PII fields"."""
        form_type = self._register("PHMRCTEST_VA", "PHMRC Test Form")
        apply_pii_field_registry("PHMRCTEST_VA")
        db.session.flush()

        # Present before: the registry really did create rows here.
        created = self._config_for(form_type, "Id10073")
        self.assertIsNotNone(created, "expected the registry to create Id10073")
        self.assertTrue(created.is_pii)
        self.assertTrue(created.is_custom)
        self.assertIsNone(created.subcategory_code)
        self.assertIsNone(created.odk_label)

        status = get_mapping_service().get_pii_set_status("PHMRCTEST_VA")
        self.assertEqual(status.owned_flagged_count, 0)
        self.assertFalse(status.confirmed)
        self.assertEqual(
            get_mapping_service().get_pii_field_ids("PHMRCTEST_VA"),
            set(PII_FIELDS),
            "an unconfirmed set must still report the ids it does carry",
        )

    def test_a_mapped_flagged_field_confirms_the_set(self):
        """WHO-shaped: Id10017 is a real mapped row, so flagging it is this
        form type's own answer about its own field."""
        form_type = self._register("WHOSHAPED_VA", "WHO Shaped Test Form")
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=form_type.form_type_id,
                field_id="Id10017",
                category_code="cat1",
                subcategory_code="sub1",
                short_label="Given name",
                is_active=True,
            )
        )
        db.session.flush()

        # Present before: unconfirmed until the registry flags the mapped row.
        self.assertFalse(get_mapping_service().is_pii_set_confirmed("WHOSHAPED_VA"))

        apply_pii_field_registry("WHOSHAPED_VA")
        db.session.flush()

        status = get_mapping_service().get_pii_set_status("WHOSHAPED_VA")
        self.assertTrue(status.confirmed)
        self.assertEqual(status.owned_flagged_count, 1)
        self.assertIn("Id10017", status.field_ids)

    def test_flagging_one_owned_field_flips_an_unconfirmed_set(self):
        """How an admin confirms the set: flag one field the form owns, in
        the field-mapping panel. Here that field arrived through ODK sync, so
        it carries an odk_label."""
        form_type = self._register("PHMRCFLAG_VA", "PHMRC Flag Test Form")
        apply_pii_field_registry("PHMRCFLAG_VA")
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=form_type.form_type_id,
                field_id="phmrc_name_of_deceased",
                odk_label="Name of the deceased",
                is_pii=False,
                is_active=True,
                is_custom=True,
            )
        )
        db.session.flush()

        # Present before: an owned field exists but is not flagged yet.
        self.assertFalse(get_mapping_service().is_pii_set_confirmed("PHMRCFLAG_VA"))

        owned = self._config_for(form_type, "phmrc_name_of_deceased")
        owned.is_pii = True
        db.session.flush()

        status = get_mapping_service().get_pii_set_status("PHMRCFLAG_VA")
        self.assertTrue(status.confirmed)
        self.assertEqual(status.owned_flagged_count, 1)
        self.assertIn("phmrc_name_of_deceased", status.field_ids)

    def test_unknown_form_type_is_unconfirmed(self):
        status = get_mapping_service().get_pii_set_status("NO_SUCH_FORM_TYPE")
        self.assertFalse(status.confirmed)
        self.assertEqual(status.field_ids, frozenset())
        self.assertEqual(status.owned_flagged_count, 0)


class PiiSetExportWithholdingTests(BaseTestCase):
    """_filter_export_payload fails closed on an unconfirmed form type."""

    PAYLOAD = {
        "Id10017": "Jane",          # flagged personal data
        "Id10019": "female",        # a coding input, never redacted
    }

    def test_unconfirmed_form_withholds_every_payload_field(self):
        confirmed = PiiSetStatus(
            confirmed=True, field_ids=frozenset({"Id10017"}), owned_flagged_count=1
        )
        unconfirmed = PiiSetStatus(
            confirmed=False, field_ids=frozenset({"Id10017"}), owned_flagged_count=0
        )

        # Present before: with a confirmed set this payload exports a value
        # for both fields' form, minus the flagged one.
        kept = _filter_export_payload(
            self.PAYLOAD, form_id="TF01", pii_status_by_form={"TF01": confirmed}
        )
        self.assertNotIn("Id10017", kept)
        self.assertEqual(kept["Id10019"], "female")

        withheld = _filter_export_payload(
            self.PAYLOAD, form_id="TF01", pii_status_by_form={"TF01": unconfirmed}
        )
        self.assertEqual(withheld, {})

    def test_smartva_input_export_strips_but_does_not_withhold(self):
        """The one exemption: the SmartVA input export is a data_manager/admin
        processing feed, so withholding would make SmartVA unusable on any new
        questionnaire. It strips the flagged field and keeps the rest."""
        unconfirmed = PiiSetStatus(
            confirmed=False, field_ids=frozenset({"Id10017"}), owned_flagged_count=0
        )

        # Present before: both fields are in the payload going in.
        self.assertIn("Id10017", self.PAYLOAD)
        self.assertIn("Id10019", self.PAYLOAD)

        kept = _filter_export_payload(
            self.PAYLOAD,
            form_id="TF01",
            pii_status_by_form={"TF01": unconfirmed},
            withhold_unconfirmed=False,
        )
        self.assertNotIn("Id10017", kept)
        self.assertEqual(kept["Id10019"], "female")

    def test_unresolvable_form_withholds_every_payload_field(self):
        """A form whose form type could not be resolved is not a licence to
        export its payload."""
        self.assertEqual(
            _filter_export_payload(
                self.PAYLOAD, form_id="TF99", pii_status_by_form={}
            ),
            {},
        )


class PiiSetCacheVersionTests(BaseTestCase):
    """The set is version-checked, so another worker's edit is not missed.

    These tests deliberately never call clear_cache(): that is the point.
    """

    def setUp(self):
        super().setUp()
        get_mapping_service().clear_cache()
        self.form_type = get_form_type_service().register_form_type(
            "PIICACHE_VA", "PII Cache Test Form"
        )
        db.session.add_all(
            [
                MasFieldDisplayConfig(
                    form_type_id=self.form_type.form_type_id,
                    field_id="cache_name",
                    category_code="cat1",
                    subcategory_code="sub1",
                    is_pii=True,
                    is_active=True,
                ),
                MasFieldDisplayConfig(
                    form_type_id=self.form_type.form_type_id,
                    field_id="cache_symptom",
                    category_code="cat1",
                    subcategory_code="sub1",
                    is_pii=False,
                    is_active=True,
                ),
            ]
        )
        db.session.flush()

    def tearDown(self):
        get_mapping_service().clear_cache()
        super().tearDown()

    def test_a_flag_set_elsewhere_is_picked_up_without_clear_cache(self):
        before = get_mapping_service().get_pii_field_ids("PIICACHE_VA")
        self.assertEqual(before, {"cache_name"})
        self.assertNotIn("cache_symptom", before)

        stale_updated_at = db.session.scalar(
            sa.select(MasFieldDisplayConfig.updated_at).where(
                MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "cache_symptom",
            )
        )
        db.session.execute(
            sa.update(MasFieldDisplayConfig)
            .where(
                MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "cache_symptom",
            )
            .values(is_pii=True)
        )
        db.session.flush()

        # The version depends on updated_at moving, so assert it did rather
        # than let a silent onupdate regression read as a cache bug.
        moved_updated_at = db.session.scalar(
            sa.select(MasFieldDisplayConfig.updated_at).where(
                MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "cache_symptom",
            )
        )
        self.assertGreater(moved_updated_at, stale_updated_at)

        self.assertIn(
            "cache_symptom",
            get_mapping_service().get_pii_field_ids("PIICACHE_VA"),
            "a flag set by another worker was served from a stale cache",
        )

    def test_a_deleted_flagged_row_is_picked_up_without_clear_cache(self):
        """The case max(updated_at) alone would miss: deleting a row does not
        move it, which is why the version carries the row count too."""
        before = get_mapping_service().get_pii_field_ids("PIICACHE_VA")
        self.assertIn("cache_name", before)

        db.session.execute(
            sa.delete(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == self.form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "cache_name",
            )
        )
        db.session.flush()

        after = get_mapping_service().get_pii_set_status("PIICACHE_VA")
        self.assertNotIn("cache_name", after.field_ids)
        self.assertFalse(
            after.confirmed,
            "removing the only owned flagged row must unconfirm the set",
        )
