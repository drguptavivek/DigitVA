"""Declarative registry of payload fields that carry personal data.

Why this exists
---------------
``MasFieldDisplayConfig.is_pii`` has been on the model since the field-mapping
tables were added, and ``FieldMappingService.get_pii_field_ids()`` reads it to
redact the data-manager CSV export
(``data_management_service._filter_export_payload``). Nothing ever set the flag
to ``True``: the WHO_2022_VA rows are seeded from
``resource/mapping/mapping_labels.xlsx``, which has no ``is_pii`` column, so the
redaction set was always empty and the export relied entirely on the hardcoded
``CSV_EXPORT_OMIT_PAYLOAD_FIELDS`` list.

That list covers identifiers and attachment slots but not the questionnaire's
own name fields, so deceased/respondent/parent names and the national
identification number were exported. Web intake then added ``abha_number`` and
``abha_address`` to the payload, which are national health identifiers.

Applies by field_id, not by form type
--------------------------------------
An earlier version of this registry keyed the PII list by form type code and
only ever populated ``WHO_2022_VA``. ``WHO_2022_VA_SOCIAL`` has its own
``mas_field_display_config`` rows, cloned once from ``WHO_2022_VA`` when the
form type was created and never resynced, so its copies of ``Id10073``
(national identification number) and five other fields stayed ``is_pii =
false`` — an export of that form type's submissions (86% of the total in one
deployment) still included the national ID. These field ids are WHO instrument
ids and mean the same thing in any WHO-derived form type, so binding the
registry to one form type code was the bug, not a feature: ``PII_FIELDS``
below is applied to every active form type unconditionally, with no
predicate checking that the form type is WHO-shaped. This is fail-safe
pre-creation, not an oversight: creating the row already flagged means that
when the real field later arrives through ODK sync, ``sync_selected``'s
existing-row guard finds it already ``is_pii = True`` and leaves it alone —
the field can never exist in a live-but-unflagged state, even momentarily.
Gating creation behind a predicate (e.g. "only for form types that already
carry a registered field") would remove that guarantee, since safety would
then depend entirely on the ``fields_added`` gate at the ODK sync call sites
firing correctly every time. Unconditional creation trades a conditional
safety property for a guaranteed one.

The visible cost of that trade: a future non-WHO form type (a PHMRC import,
say) gets three redaction-only rows created for fields it does not have
(``Id10073``, ``abha_number``, ``abha_address``). Those rows have NULL
category/subcategory so they never render on the coding screen and never
leak anything — they show up as noise in the admin field list's unmapped
bucket.

The larger cost is that those three rows are *not* an answer about that form
type. The questionnaire's own name and identifier fields carry different
field ids and stay unflagged, and an empty flag set reads as "nothing here is
personal data" rather than "nobody has looked". So the set is treated as
**unconfirmed** until at least one field the form type owns — a mapped row, an
ODK-synced row, any row this registry did not create — is flagged ``is_pii``.
Unconfirmed fails closed: a viewer without PII sees no payload at all and the
exports withhold the payload, and the admin field-mapping panel carries a
standing warning until someone flags an owned field. See
``FieldMappingService.get_pii_set_status`` and
``docs/policy/access-control-model.md``.

Two kinds of row, per form type
--------------------------------
1. **Mapped fields** already have a ``mas_field_display_config`` row for that
   form type; applying the registry only sets ``is_pii``/``pii_type`` on it.
2. **Unmapped fields** get a row created with ``category_code``/
   ``subcategory_code`` left NULL.

   The NULL subcategory is load-bearing. ``_build_fieldsitepi`` requires
   ``subcategory_code IS NOT NULL`` to render a field, so a created row is
   visible to redaction (``_build_pii_set_status`` keys on ``is_pii`` alone,
   regardless of ``is_active`` — see below) and invisible to the coding
   screen. Flagging a field never changes what a coder sees.

   Of the fifteen fields below, twelve already have a category and
   subcategory from the coder-facing mapping: ``Id10007``, ``Id10010``,
   ``Id10010c``, ``Id10017``, ``Id10018``, ``Id10055``, ``Id10057``,
   ``Id10061``, ``Id10062``, ``Id10070``, ``Id10071`` and ``Id10072`` are real
   mapped rows and only get their PII flag set here. Only ``Id10073``,
   ``abha_number`` and ``abha_address`` are genuinely unmapped and get a
   redaction-only row created.

``is_active`` is a display concern, not a redaction one. ``is_active`` governs
whether ``_build_fieldsitepi`` shows a field on the coding screen;
``is_pii``/``_build_pii_set_status`` governs export redaction and does not
consult ``is_active`` at all. Applying this registry therefore never touches
``is_active`` on a row it updates — doing so used to force-reactivate a field
an operator had deliberately deactivated, resurrecting it onto the coding
screen as a side effect of fixing redaction. Rows the registry *creates* are
still created active: they have no category/subcategory, so ``is_active``
never lets them render regardless.

Marking a field here affects export redaction only. It does not hide anything
from the coding screen beyond what was already hidden, and it does not change
what the interviewer enters — collection is deliberately unmasked.

See ``docs/policy/web-intake.md`` and ``docs/policy/field-data-collection.md``.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa

from app import db
from app.models.va_field_mapping import MasFieldDisplayConfig, MasFormTypes

log = logging.getLogger(__name__)


# pii_type is descriptive, used for admin display only; redaction keys on
# is_pii alone. These are the values already in use on the WHO_2022_VA rows,
# kept rather than replaced with a finer vocabulary so the admin panel stays
# consistent.
PII_TYPE_NAME = "name"
PII_TYPE_LOCATION = "location"
PII_TYPE_IDENTIFIER = "identifier"
PII_TYPE_DATE = "date"


# field_id -> pii_type. Applied to every active form type unconditionally
# (see module docstring) — not scoped to one form type code, and not gated
# on the form type already having any of these WHO instrument field ids.
#
# Most of this list already carried is_pii on WHO_2022_VA in the live
# database, set by hand through the admin field-mapping panel. Nothing in the
# seed path reproduces that, so a fresh install or a mapping reseed starts
# with no flags at all; recording them here makes the set reproducible. The
# genuinely new entries are Id10010c, Id10073 and the two ABHA fields.
#
# Categorical questions that merely narrow a person down (Id10052 citizenship,
# Id10058 place-of-death category) are not listed: they are coding inputs and
# carry no direct identifier. Structured geography (survey_state,
# survey_district, org_<level>_code) is likewise not listed — it is operational
# location, while Id10055/Id10057 are free text down to the village.
PII_FIELDS: dict[str, str] = {
    # --- Already flagged in the live database; listed for reproducibility ---
    "Id10007": PII_TYPE_NAME,  # full name of VA respondent
    "Id10010": PII_TYPE_NAME,  # name of VA interviewer
    "Id10017": PII_TYPE_NAME,  # first/given name(s) of the deceased
    "Id10018": PII_TYPE_NAME,  # surname(s) of the deceased
    "Id10061": PII_TYPE_NAME,  # full name of the father
    "Id10062": PII_TYPE_NAME,  # full name of the mother
    "Id10055": PII_TYPE_LOCATION,  # place of death, free text
    "Id10057": PII_TYPE_LOCATION,  # where the death occurred, free text to village
    "Id10070": PII_TYPE_IDENTIFIER,  # death registration number
    "Id10071": PII_TYPE_DATE,  # date of death registration
    "Id10072": PII_TYPE_IDENTIFIER,  # death certificate identifier
    # --- Missing until now ---
    "Id10010c": PII_TYPE_IDENTIFIER,  # ID of VA interviewer
    "Id10073": PII_TYPE_IDENTIFIER,  # national identification number of deceased
    # --- DigitVA extension fields (web intake) ---
    "abha_number": PII_TYPE_IDENTIFIER,
    "abha_address": PII_TYPE_IDENTIFIER,
}


def apply_pii_field_registry(form_type_code: str | None = None) -> dict[str, int]:
    """Flag every registered PII field across all active form types, or one.

    ``PII_FIELDS`` is a field_id -> pii_type mapping, not a per-form-type one:
    it is applied to every active ``MasFormTypes`` row (or, when
    ``form_type_code`` is given, to that one form type only, active or not —
    tests and one-off backfills rely on this). For each form type, a field
    already mapped gets its ``is_pii``/``pii_type`` set; a field with no row
    gets a redaction-only row created.

    Idempotent: safe to rerun after a mapping reseed, which is when rows can be
    recreated with ``is_pii`` back at its ``False`` default. Returns counts of
    rows updated and created. The caller owns the transaction.
    """
    totals = {"updated": 0, "created": 0, "unchanged": 0}

    query = sa.select(MasFormTypes)
    if form_type_code:
        query = query.where(
            MasFormTypes.form_type_code == form_type_code.strip().upper()
        )
    else:
        query = query.where(MasFormTypes.is_active == True)  # noqa: E712

    form_types = db.session.scalars(query).all()
    if not form_types:
        log.warning(
            "pii registry | no matching form type for %s", form_type_code or "(all active)"
        )
        return totals

    for form_type in form_types:
        existing = {
            row.field_id: row
            for row in db.session.scalars(
                sa.select(MasFieldDisplayConfig).where(
                    MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                    MasFieldDisplayConfig.field_id.in_(list(PII_FIELDS)),
                )
            )
        }

        form_created = form_updated = form_unchanged = 0

        for field_id, pii_type in PII_FIELDS.items():
            row = existing.get(field_id)
            if row is None:
                # Unmapped field: create a redaction-only row. category_code and
                # subcategory_code stay NULL so the coding screen never renders
                # it (see the module docstring).
                db.session.add(
                    MasFieldDisplayConfig(
                        form_type_id=form_type.form_type_id,
                        field_id=field_id,
                        is_pii=True,
                        pii_type=pii_type,
                        is_active=True,
                        is_custom=True,
                    )
                )
                form_created += 1
                continue

            if row.is_pii and row.pii_type:
                # Already flagged and classified. pii_type is the operator's to
                # set from the admin panel, so an existing value is never
                # replaced with the registry's — the registry decides *whether*
                # a field is PII, not how someone chose to label it.
                form_unchanged += 1
                continue

            row.is_pii = True
            row.pii_type = row.pii_type or pii_type
            # is_active is a display flag, not a redaction one: leave it as the
            # operator set it. Forcing it true here would resurrect a
            # deliberately deactivated field onto the coding screen as a side
            # effect of fixing redaction.
            form_updated += 1

        totals["created"] += form_created
        totals["updated"] += form_updated
        totals["unchanged"] += form_unchanged

        log.info(
            "pii registry | %s | created=%d updated=%d unchanged=%d",
            form_type.form_type_code,
            form_created,
            form_updated,
            form_unchanged,
        )

    if totals["created"] or totals["updated"]:
        # The PII set is version-checked per call, so other workers see this
        # change without a restart (see field_mapping_service's docstring).
        # Clearing here still saves the calling process one rebuild, and the
        # other caches on the service do rely on it.
        from app.services.field_mapping_service import get_mapping_service

        get_mapping_service().clear_cache()

    return totals
