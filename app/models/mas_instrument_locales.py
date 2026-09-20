"""Instrument display languages and the strings that render them.

Policy: docs/policy/va-form-project-configuration.md ("Translation sources")
and docs/policy/va-web-form-options.md ("Adding a language").

A translation is *data*, not part of the instrument bundle. The instrument's
structure is pre-built and immutable (decision O1); a locale only supplies the
text shown for a question, hint, guidance note or choice. That is why these two
tables carry no structure of their own: ``item_key`` names something the
reference already has -- the curated reference form or a DigitVA layer -- and
an import can never create a question.

``en`` is the base locale of every bundled instrument. It needs no rows here
and is always served; every other locale is served to a form once ``is_active``
is set, which is an explicit administrative action. Coverage is reported but
decides nothing: an untranslated string is absent from the served payload, so
the form falls back to English for that string alone
(``app/services/instrument_translation_service.py``).

A locale must also be human-**approved** before it may be activated (decided
2026-09-20): ``lifecycle_state`` moves ``draft`` -> ``in_review`` ->
``approved``, only ``approved`` may be activated, and leaving ``approved``
while still active is refused -- both in
:func:`app.services.instrument_translation_service.set_locale_active` and by
``ck_mas_instrument_locales_active_requires_approved``.
"""

import uuid

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db

#: ``item_kind`` values. A question key is the question ``name``; a choice key
#: is ``list_name`` + ``/`` + the choice ``name``.
ITEM_KIND_QUESTION = "question"
ITEM_KIND_CHOICE = "choice"

#: ``field`` values, matching the XLSForm columns they come from.
FIELD_LABEL = "label"
FIELD_HINT = "hint"
FIELD_GUIDANCE = "guidance_hint"

#: ``source`` values. ``imported`` rows are overwritten by a re-import;
#: ``edited`` rows are an administrator's correction and are kept. ``machine``
#: rows are LLM-authored drafts awaiting a speaker's review (decided
#: 2026-09-20): they are overwritten by a re-import exactly like ``imported``
#: ones, excluded from what :func:`app.services.instrument_translation_service.export_translations`
#: serves, and excluded from coverage, until an administrator promotes one to
#: ``edited`` (accept-as-is) or edits its text.
SOURCE_IMPORTED = "imported"
SOURCE_EDITED = "edited"
SOURCE_MACHINE = "machine"

#: ``lifecycle_state`` values (decided 2026-09-20: a locale must not be served
#: to interviewers unless a human has approved it, and that approval must be
#: recorded). Every locale starts ``draft``; only ``approved`` may be
#: activated -- enforced both in :func:`app.services.instrument_translation_service.set_locale_active`
#: and by ``ck_mas_instrument_locales_active_requires_approved`` below.
LIFECYCLE_DRAFT = "draft"
LIFECYCLE_IN_REVIEW = "in_review"
LIFECYCLE_APPROVED = "approved"


class MasInstrumentLocales(db.Model):
    """One display language of one standard instrument."""

    __tablename__ = "mas_instrument_locales"
    __table_args__ = (
        sa.CheckConstraint(
            "is_active = false OR lifecycle_state = 'approved'",
            # The naming convention (app/__init__.py) already prefixes this
            # with "ck_%(table_name)s_"; passing the already-prefixed full
            # name here doubles it and Postgres truncates the result at 63
            # characters (digitva-we0). Pass only the discriminator.
            name="active_requires_approved",
        ),
    )

    instrument_code: so.Mapped[str] = so.mapped_column(
        sa.String(32), primary_key=True
    )
    locale_code: so.Mapped[str] = so.mapped_column(sa.String(16), primary_key=True)
    language_name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    # Human approval gate (decided 2026-09-20): a locale is servable only once
    # an administrator has reviewed it and moved it to "approved" -- coverage
    # still decides nothing. Leaving "approved" clears both fields; entering it
    # sets them (see set_locale_lifecycle_state).
    lifecycle_state: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default=LIFECYCLE_DRAFT,
        server_default=LIFECYCLE_DRAFT,
    )
    approved_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    approved_at: so.Mapped[object | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # The workbook this locale was imported from, as named in the policy doc's
    # "Translation sources" table, with its digest so a re-downloaded file that
    # changed underneath is visible.
    source_document: so.Mapped[str | None] = so.mapped_column(
        sa.String(255), nullable=True
    )
    source_sha256: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    imported_at: so.Mapped[object | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # Bumped on every import and every edit. A client caches a locale by this
    # number and revalidates against it, so an edit reaches an interviewer on
    # their next form without a rebuild.
    version: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=1, server_default="1"
    )
    updated_at: so.Mapped[object] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    def __repr__(self) -> str:
        return f"InstrumentLocale({self.instrument_code}/{self.locale_code})"


class MapInstrumentTranslations(db.Model):
    """One translated string of one instrument item in one locale."""

    __tablename__ = "map_instrument_translations"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["instrument_code", "locale_code"],
            ["mas_instrument_locales.instrument_code", "mas_instrument_locales.locale_code"],
            name="fk_map_instrument_translations_locale",
            ondelete="CASCADE",
        ),
    )

    # The five key columns are the primary key: one text per item, field and
    # locale, which is exactly the uniqueness an idempotent upsert needs. They
    # lead with instrument_code and locale_code, so serving a whole locale and
    # searching inside one both read this index.
    instrument_code: so.Mapped[str] = so.mapped_column(
        sa.String(32), primary_key=True
    )
    locale_code: so.Mapped[str] = so.mapped_column(sa.String(16), primary_key=True)
    item_kind: so.Mapped[str] = so.mapped_column(sa.String(16), primary_key=True)
    item_key: so.Mapped[str] = so.mapped_column(sa.String(255), primary_key=True)
    field: so.Mapped[str] = so.mapped_column(sa.String(32), primary_key=True)
    text: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    source: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default=SOURCE_IMPORTED,
        server_default=SOURCE_IMPORTED,
    )
    updated_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    updated_at: so.Mapped[object] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    def __repr__(self) -> str:
        return (
            f"InstrumentTranslation({self.instrument_code}/{self.locale_code}"
            f"/{self.item_kind}/{self.item_key}/{self.field})"
        )
