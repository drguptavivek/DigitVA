"""Give existing web and device submissions their ``finalAgeInYears`` (digitva-wsab).

``finalAgeInYears`` is an ND01 site-workbook calculate the WHO workbook behind
the web and app forms lacks, so those payloads never carried it and
``va_submissions.va_deceased_age`` was 0 for every one. The server now sets it
at submit (``who_age_normalization.derive_final_age_in_years``; frozen copy below); this adds it
to the stored payload of the existing ones and recomputes the age projection
columns (``va_deceased_age`` and the normalized days / years / source).

Scope: the active payload version of each submission whose ``va_sid`` starts
``web-`` (the id ``build_web_payload`` gives web and device submissions) and
whose payload has no non-blank ``finalAgeInYears``. ODK rows are never
touched. The key is not sealed (``NEVER_SEALED_FIELDS``) and is in
``VOLATILE_PAYLOAD_KEYS``, so the payload is edited in place: no new version,
no fingerprint or PII side-row change. Batched by version id.

Recovery: the old projection values of every changed row go to
``_mig_e7b2c4d8f1a3_final_age`` (kept after the upgrade; dropped by the
downgrade). Downgrade removes the key from exactly those payloads and restores
those values. Take a database backup before upgrading on production. Processes
that cache section data (``invalidate_section_data_cache``) hold the old
payload until restarted. The analytics MV reads ``va_deceased_age``; refresh it
afterwards.

Revision ID: e7b2c4d8f1a3
Revises: d6a1f3b8c2e4
Create Date: 2026-10-23
"""
import json
import math
from collections import namedtuple
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e7b2c4d8f1a3"
down_revision = "d6a1f3b8c2e4"
branch_labels = None
depends_on = None

AUDIT = "_mig_e7b2c4d8f1a3_final_age"
BATCH = 500

# Frozen copy, as of 2026-10-23, of app/services/who_age_normalization.py
# (derive_final_age_in_years, normalize_who_2022_age and helpers). A migration
# must not import app code; later changes to the service do not alter this one.
_DAYS_PER_MONTH = Decimal("30.4375")
_DAYS_PER_YEAR = Decimal("365.25")
_TRUE_VALUES = {"1", "1.0", "true", "True"}
NormalizedWhoAge = namedtuple(
    "NormalizedWhoAge",
    "legacy_age_years normalized_age_days normalized_age_years normalized_age_source",
)


def _parse_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        if value.is_nan():
            return None
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return None
        return Decimal(str(value))

    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = Decimal(raw)
    except InvalidOperation:
        return None
    if parsed.is_nan():
        return None
    return parsed


def derive_final_age_in_years(payload):
    """ND01 ``finalAgeInYears``: ``ageInYears``, else ``ageInYears2``, else "000"."""
    payload = payload or {}
    for key in ("ageInYears", "ageInYears2"):
        value = payload.get(key)
        if value is None or isinstance(value, bool):
            continue
        if str(value).strip() in ("", "NaN", "nan"):
            continue
        return str(value)
    return "000"


def _flag_is_true(value):
    return str(value).strip() in _TRUE_VALUES


def normalize_who_2022_age(va_submission):
    """Choose one WHO 2022 age source using policy precedence."""
    payload = va_submission or {}

    age_neonate_hours = _parse_decimal(payload.get("age_neonate_hours"))
    age_neonate_days = _parse_decimal(payload.get("age_neonate_days"))
    age_in_days = _parse_decimal(payload.get("ageInDays"))
    age_in_months = _parse_decimal(payload.get("ageInMonths"))
    age_in_years = _parse_decimal(payload.get("ageInYears"))
    age_in_years2 = _parse_decimal(payload.get("ageInYears2"))
    final_age_years = _parse_decimal(payload.get("finalAgeInYears"))

    normalized_age_source = None
    if age_neonate_hours is not None:
        normalized_age_source = "age_neonate_hours"
    elif age_neonate_days is not None:
        normalized_age_source = "age_neonate_days"
    elif _flag_is_true(payload.get("isNeonatal")) and age_in_days is not None:
        normalized_age_source = "ageInDays"
    elif _flag_is_true(payload.get("isChild")) and age_in_days is not None:
        normalized_age_source = "ageInDays"
    elif _flag_is_true(payload.get("isChild")) and age_in_months is not None:
        normalized_age_source = "ageInMonths"
    elif _flag_is_true(payload.get("isChild")) and age_in_years is not None:
        normalized_age_source = "ageInYears"
    elif _flag_is_true(payload.get("isChild")) and age_in_years2 is not None:
        normalized_age_source = "ageInYears2"
    elif _flag_is_true(payload.get("isChild")) and final_age_years is not None:
        normalized_age_source = "finalAgeInYears"
    elif _flag_is_true(payload.get("isAdult")) and age_in_years is not None:
        normalized_age_source = "ageInYears"
    elif _flag_is_true(payload.get("isAdult")) and age_in_years2 is not None:
        normalized_age_source = "ageInYears2"
    elif _flag_is_true(payload.get("isAdult")) and final_age_years is not None:
        normalized_age_source = "finalAgeInYears"
    elif age_in_years is not None:
        normalized_age_source = "ageInYears"
    elif age_in_days is not None:
        normalized_age_source = "ageInDays"
    elif age_in_months is not None:
        normalized_age_source = "ageInMonths"
    elif age_in_years2 is not None:
        normalized_age_source = "ageInYears2"
    elif final_age_years is not None:
        normalized_age_source = "finalAgeInYears"

    normalized_age_days = None
    normalized_age_years = None
    if normalized_age_source == "age_neonate_hours":
        normalized_age_days = Decimal("0")
        normalized_age_years = Decimal("0")
    elif normalized_age_source == "age_neonate_days":
        normalized_age_days = age_neonate_days
        normalized_age_years = age_neonate_days / _DAYS_PER_YEAR
    elif normalized_age_source == "ageInDays":
        normalized_age_days = age_in_days
        normalized_age_years = age_in_days / _DAYS_PER_YEAR
    elif normalized_age_source == "ageInMonths":
        normalized_age_days = age_in_months * _DAYS_PER_MONTH
        normalized_age_years = age_in_months / Decimal("12")
    elif normalized_age_source == "ageInYears":
        normalized_age_days = age_in_years * _DAYS_PER_YEAR
        normalized_age_years = age_in_years
    elif normalized_age_source == "ageInYears2":
        normalized_age_days = age_in_years2 * _DAYS_PER_YEAR
        normalized_age_years = age_in_years2
    elif normalized_age_source == "finalAgeInYears":
        normalized_age_days = final_age_years * _DAYS_PER_YEAR
        normalized_age_years = final_age_years

    legacy_age_years = int(final_age_years) if final_age_years is not None else 0
    return NormalizedWhoAge(
        legacy_age_years=legacy_age_years,
        normalized_age_days=normalized_age_days,
        normalized_age_years=normalized_age_years,
        normalized_age_source=normalized_age_source,
    )


def upgrade():
    bind = op.get_bind()
    op.create_table(
        AUDIT,
        sa.Column("payload_version_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("va_sid", sa.String(64), nullable=False),
        sa.Column("old_age", sa.Integer(), nullable=False),
        sa.Column("old_days", sa.Numeric()),
        sa.Column("old_years", sa.Numeric()),
        sa.Column("old_source", sa.String()),
    )
    select = sa.text(
        "SELECT v.payload_version_id, v.va_sid, v.payload_data, s.va_deceased_age, "
        "s.va_deceased_age_normalized_days, s.va_deceased_age_normalized_years, s.va_deceased_age_source "
        "FROM va_submission_payload_versions v JOIN va_submissions s ON s.va_sid = v.va_sid "
        "WHERE v.version_status = 'active' AND v.va_sid LIKE 'web-%' "
        "AND COALESCE(v.payload_data->>'finalAgeInYears', '') = '' "
        "AND v.payload_version_id > :last ORDER BY v.payload_version_id LIMIT :n FOR UPDATE OF v, s"
    )
    last = "00000000-0000-0000-0000-000000000000"
    while True:
        rows = bind.execute(select, {"last": last, "n": BATCH}).mappings().all()
        if not rows:
            break
        for row in rows:
            last = str(row["payload_version_id"])
            payload = dict(row["payload_data"])
            payload["finalAgeInYears"] = derive_final_age_in_years(payload)
            age = normalize_who_2022_age(payload)
            bind.execute(sa.text(
                f"INSERT INTO {AUDIT} VALUES (:id, :sid, :age, :days, :years, :source)"
            ), {"id": row["payload_version_id"], "sid": row["va_sid"], "age": row["va_deceased_age"],
                "days": row["va_deceased_age_normalized_days"], "years": row["va_deceased_age_normalized_years"],
                "source": row["va_deceased_age_source"]})
            bind.execute(sa.text(
                "UPDATE va_submission_payload_versions SET payload_data = payload_data || CAST(:patch AS jsonb) "
                "WHERE payload_version_id = :id"
            ), {"patch": json.dumps({"finalAgeInYears": payload["finalAgeInYears"]}), "id": row["payload_version_id"]})
            bind.execute(sa.text(
                "UPDATE va_submissions SET va_deceased_age = :age, va_deceased_age_normalized_days = :days, "
                "va_deceased_age_normalized_years = :years, va_deceased_age_source = :source WHERE va_sid = :sid"
            ), {"age": age.legacy_age_years, "days": age.normalized_age_days, "years": age.normalized_age_years,
                "source": age.normalized_age_source, "sid": row["va_sid"]})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE va_submission_payload_versions v SET payload_data = v.payload_data - 'finalAgeInYears' "
        f"FROM {AUDIT} a WHERE a.payload_version_id = v.payload_version_id"
    ))
    bind.execute(sa.text(
        "UPDATE va_submissions s SET va_deceased_age = a.old_age, va_deceased_age_normalized_days = a.old_days, "
        "va_deceased_age_normalized_years = a.old_years, va_deceased_age_source = a.old_source "
        f"FROM {AUDIT} a WHERE a.va_sid = s.va_sid"
    ))
    op.drop_table(AUDIT)
