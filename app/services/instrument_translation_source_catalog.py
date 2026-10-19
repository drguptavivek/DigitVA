"""Documented questionnaire translation sources and bootstrap import.

The source list mirrors the reviewed provenance table in
``docs/policy/va-form-project-configuration.md``.  Keeping it as code makes
startup deterministic without parsing Markdown at runtime.

``bootstrap_missing_sources`` deliberately leaves transaction ownership to its
caller.  It takes a PostgreSQL transaction-scoped advisory lock, inspects all
locale metadata in one batch, validates the pending workbooks, and then imports
the eligible locales.  A caller must commit the complete batch or roll it back
on error; the transaction-scoped lock is released automatically by either.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import (
    LIFECYCLE_APPROVED,
    SOURCE_EDITED,
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services.instrument_translation_service import (
    BASE_INSTRUMENT_CODE,
    WORKBOOK_DIR,
    ImportReport,
    InstrumentTranslationError,
    import_translations,
    read_workbook_items,
)


@dataclass(frozen=True)
class TranslationSource:
    locale_code: str
    language_name: str
    workbook: str


@dataclass(frozen=True)
class BootstrapLocaleResult:
    locale_code: str
    language_name: str
    workbook: str
    status: str
    written: int = 0
    version: int | None = None
    reason: str | None = None


@dataclass(frozen=True)
class BootstrapReport:
    instrument_code: str
    locales: tuple[BootstrapLocaleResult, ...]

    @property
    def imported(self) -> tuple[BootstrapLocaleResult, ...]:
        return tuple(row for row in self.locales if row.status == "imported")

    @property
    def skipped(self) -> tuple[BootstrapLocaleResult, ...]:
        return tuple(row for row in self.locales if row.status == "skipped")

    @property
    def written(self) -> int:
        return sum(row.written for row in self.imported)


# Explicit 2026-10-19 catalogue.  Do not derive this from the policy Markdown
# at runtime: deployment must fail loudly if a documented source is absent.
TRANSLATION_SOURCE_CATALOG: tuple[TranslationSource, ...] = (
    TranslationSource("hi", "Hindi", "ND01_ICMRVA_WHOVA2022.xlsx"),
    TranslationSource("ta", "Tamil", "JIPMER_DS_WHOVA2022.xlsx"),
    TranslationSource("kn", "Kannada", "KA01_DS_WHOVA2022.xlsx"),
    TranslationSource("mr", "Marathi", "KEM_VAADU_WHOVA2022.xlsx"),
    TranslationSource("ml", "Malayalam", "KL01_DS_WHOVA2022.xlsx"),
    TranslationSource("kha", "Khasi", "ML01_ICMRVA_WHOVA2022.xlsx"),
    TranslationSource("or", "Odia", "OD01_ICMRVA_WHOVA2022.xlsx"),
    TranslationSource("bn", "Bangla", "TR01_DS_WHOVA2022.xlsx"),
    TranslationSource("fr", "French", "2022whova_xls_form_for_odk_multilingual.xlsx"),
    TranslationSource("pt", "Portuguese", "2022whova_xls_form_for_odk_multilingual.xlsx"),
    TranslationSource("ar", "Arabic", "2022whova_xls_form_for_odk_multilingual.xlsx"),
    TranslationSource("sw", "Swahili", "2022whova_xls_form_for_odk_multilingual.xlsx"),
    TranslationSource("es", "Spanish", "2022whova_xls_form_for_odk_multilingual.xlsx"),
)

_LOCK_NAME = "digitva.instrument_translation_source_bootstrap"


def _source_path(source: TranslationSource) -> Path:
    return WORKBOOK_DIR / source.workbook


def _take_bootstrap_lock() -> None:
    """Serialize bootstrap batches using a PostgreSQL transaction lock.

    ``pg_advisory_xact_lock`` blocks until acquired and releases with the
    current transaction.  We intentionally do not fall back to Redis or a
    process-local lock: startup processes may run on different hosts.
    """

    db.session.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": _LOCK_NAME},
    )


def _metadata(instrument_code: str) -> tuple[dict[str, MasInstrumentLocales], set[str]]:
    rows = db.session.scalars(
        sa.select(MasInstrumentLocales).where(
            MasInstrumentLocales.instrument_code == instrument_code
        )
    ).all()
    edited_locales = set(
        db.session.scalars(
            sa.select(MapInstrumentTranslations.locale_code)
            .where(
                MapInstrumentTranslations.instrument_code == instrument_code,
                MapInstrumentTranslations.source == SOURCE_EDITED,
            )
            .distinct()
        ).all()
    )
    return {row.locale_code: row for row in rows}, edited_locales


def bootstrap_missing_sources(
    instrument_code: str = BASE_INSTRUMENT_CODE,
    *,
    cross_check: bool = False,
) -> BootstrapReport:
    """Import the documented source for each eligible missing locale.

    The function never commits or rolls back.  A missing or malformed source
    raises before any eligible locale is written, and callers must roll back
    the transaction on any exception to preserve all-or-nothing semantics.
    """

    instrument_code = (instrument_code or "").strip().upper()
    _take_bootstrap_lock()
    locales, edited_locales = _metadata(instrument_code)

    pending: list[TranslationSource] = []
    results: list[BootstrapLocaleResult] = []
    for source in TRANSLATION_SOURCE_CATALOG:
        row = locales.get(source.locale_code)
        reason = None
        if row is not None and row.source_document:
            reason = "source_document already recorded"
        elif source.locale_code in edited_locales:
            reason = "locale has edited translation strings"
        elif row is not None and row.is_active:
            reason = "locale is active"
        elif row is not None and row.lifecycle_state == LIFECYCLE_APPROVED:
            reason = "locale is approved"

        if reason:
            results.append(
                BootstrapLocaleResult(
                    source.locale_code,
                    source.language_name,
                    source.workbook,
                    "skipped",
                    reason=reason,
                    version=row.version if row is not None else None,
                )
            )
        else:
            pending.append(source)

    # Validate every pending source before importing any one locale.  This is
    # what makes a corrupt later workbook fail without a partial batch even for
    # callers that accidentally inspect the session before rolling back.
    for source in pending:
        path = _source_path(source)
        if not path.exists():
            raise InstrumentTranslationError(
                f"Documented translation source is missing for {source.locale_code}: {path}"
            )
        try:
            read_workbook_items(path)
        except Exception as exc:  # pandas may surface BadZipFile directly
            raise InstrumentTranslationError(
                f"Documented translation source is invalid for {source.locale_code}: {exc}"
            ) from exc

    for source in pending:
        report: ImportReport = import_translations(
            instrument_code,
            source.locale_code,
            _source_path(source),
            cross_check=cross_check,
            language_name=source.language_name,
        )
        row = db.session.get(MasInstrumentLocales, (instrument_code, source.locale_code))
        results.append(
            BootstrapLocaleResult(
                source.locale_code,
                source.language_name,
                source.workbook,
                "imported",
                written=report.written,
                version=None if cross_check or row is None else row.version,
            )
        )

    return BootstrapReport(instrument_code, tuple(results))
