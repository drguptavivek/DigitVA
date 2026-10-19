"""Focused checks for the documented translation-source bootstrap."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import (
    LIFECYCLE_APPROVED,
    LIFECYCLE_IN_REVIEW,
    SOURCE_EDITED,
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services import instrument_translation_source_catalog as catalog
from app.services.instrument_translation_service import (
    BASE_INSTRUMENT_CODE,
    InstrumentTranslationError,
)
from tests.base import BaseTestCase


class TranslationSourceBootstrapTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(
            sa.delete(MapInstrumentTranslations).where(
                MapInstrumentTranslations.instrument_code == BASE_INSTRUMENT_CODE
            )
        )
        db.session.execute(
            sa.delete(MasInstrumentLocales).where(
                MasInstrumentLocales.instrument_code == BASE_INSTRUMENT_CODE
            )
        )
        db.session.flush()

    @property
    def source(self):
        return catalog.TRANSLATION_SOURCE_CATALOG[0]

    def _catalog(self, *sources):
        return patch.object(catalog, "TRANSLATION_SOURCE_CATALOG", tuple(sources))

    def test_catalog_has_all_thirteen_sources_and_real_files(self):
        self.assertEqual(len(catalog.TRANSLATION_SOURCE_CATALOG), 13)
        self.assertEqual(
            {source.locale_code for source in catalog.TRANSLATION_SOURCE_CATALOG},
            {"hi", "ta", "kn", "mr", "ml", "kha", "or", "bn", "fr", "pt", "ar", "sw", "es"},
        )
        for source in catalog.TRANSLATION_SOURCE_CATALOG:
            self.assertTrue((catalog.WORKBOOK_DIR / source.workbook).is_file())

    def test_real_source_import_is_idempotent_and_preserves_version_on_rerun(self):
        with self._catalog(self.source):
            first = catalog.bootstrap_missing_sources()
            db.session.commit()
            self.assertEqual([row.status for row in first.locales], ["imported"])
            locale = db.session.get(MasInstrumentLocales, (BASE_INSTRUMENT_CODE, "hi"))
            version = locale.version

            second = catalog.bootstrap_missing_sources()
            self.assertEqual(second.skipped[0].reason, "source_document already recorded")
            self.assertEqual(
                db.session.get(MasInstrumentLocales, (BASE_INSTRUMENT_CODE, "hi")).version,
                version,
            )

    def test_each_protection_flag_skips_without_reimport(self):
        protected = (
            MasInstrumentLocales(
                instrument_code=BASE_INSTRUMENT_CODE,
                locale_code="hi",
                language_name="Hindi",
                lifecycle_state=LIFECYCLE_APPROVED,
                is_active=False,
                version=7,
            ),
        )
        db.session.add(protected[0])
        db.session.flush()
        with self._catalog(self.source):
            report = catalog.bootstrap_missing_sources()
        self.assertEqual(report.skipped[0].reason, "locale is approved")
        self.assertEqual(report.skipped[0].version, 7)

        db.session.delete(protected[0])
        db.session.flush()
        active = MasInstrumentLocales(
            instrument_code=BASE_INSTRUMENT_CODE,
            locale_code="hi",
            language_name="Hindi",
            lifecycle_state=LIFECYCLE_APPROVED,
            is_active=True,
            version=8,
        )
        db.session.add(active)
        db.session.flush()
        with self._catalog(self.source):
            report = catalog.bootstrap_missing_sources()
        self.assertEqual(report.skipped[0].reason, "locale is active")

    def test_edited_string_protects_the_whole_locale(self):
        locale = MasInstrumentLocales(
            instrument_code=BASE_INSTRUMENT_CODE,
            locale_code="hi",
            language_name="Hindi",
            lifecycle_state=LIFECYCLE_IN_REVIEW,
            is_active=False,
        )
        db.session.add(locale)
        db.session.flush()
        db.session.add(
            MapInstrumentTranslations(
                instrument_code=BASE_INSTRUMENT_CODE,
                locale_code="hi",
                item_kind="question",
                item_key="Q1",
                field="label",
                text="Reviewed",
                source=SOURCE_EDITED,
            )
        )
        db.session.flush()
        with self._catalog(self.source):
            report = catalog.bootstrap_missing_sources()
        self.assertEqual(report.skipped[0].reason, "locale has edited translation strings")

    def test_missing_source_is_preflighted_before_any_locale_is_written(self):
        missing = catalog.TranslationSource("ta", "Tamil", "does-not-exist.xlsx")
        with self._catalog(self.source, missing):
            with self.assertRaises(InstrumentTranslationError):
                catalog.bootstrap_missing_sources()
        db.session.rollback()
        self.assertIsNone(db.session.get(MasInstrumentLocales, (BASE_INSTRUMENT_CODE, "hi")))

    def test_corrupt_source_is_preflighted_before_any_locale_is_written(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "broken.xlsx"
            path.write_bytes(b"not an xlsx")
            broken = catalog.TranslationSource("ta", "Tamil", path.name)
            with patch.object(catalog, "WORKBOOK_DIR", Path(temp_dir)), self._catalog(
                broken, self.source
            ):
                with self.assertRaises(InstrumentTranslationError):
                    catalog.bootstrap_missing_sources()
        db.session.rollback()
        self.assertIsNone(db.session.get(MasInstrumentLocales, (BASE_INSTRUMENT_CODE, "hi")))

    def test_lock_is_postgres_transaction_scoped(self):
        statements = []
        original = db.session.execute

        def capture(statement, *args, **kwargs):
            statements.append(str(statement))
            return original(statement, *args, **kwargs)

        with patch.object(db.session, "execute", side_effect=capture):
            with self._catalog():
                catalog.bootstrap_missing_sources()
        self.assertTrue(any("pg_advisory_xact_lock" in statement for statement in statements))

    def test_cli_reports_batch_counts(self):
        with self._catalog(self.source):
            result = self.app.test_cli_runner().invoke(
                args=["instrument-translations", "import-missing-sources"]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("imported=1 skipped=0", result.output)

    def test_seed_and_boot_use_the_batch_command(self):
        seed_text = Path("app/commands/seed.py").read_text(encoding="utf-8")
        boot_text = Path("boot.sh").read_text(encoding="utf-8")
        self.assertIn("_seed_missing_translation_sources()", seed_text)
        self.assertIn("flask instrument-translations import-missing-sources", boot_text)
