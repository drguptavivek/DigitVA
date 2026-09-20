"""Demote Odia and Kannada pending a speaker's review of mislabelled strings.

Revision ID: c8e4a1f7b209
Revises: 120f783ea138
Create Date: 2026-09-20

digitva-fb5. Some translated question labels carry a *different* question's
wording, so an interviewer reads one question while the answer is stored
against another. Confirmed by copy-paste proof in ``OD01_ICMRVA`` (Odia
``Id10192`` repeats ``Id10191``) and ``KA01_DS`` (Kannada ``Id10471`` repeats
``Id10470``), and by reading the Odia for a contiguous ``Id10191``-``Id10195``
shift. See ``docs/current-state/translation-label-code-mismatches.md``.

The owner decided 2026-09-20 to stop serving these two locales until a reader
of each language has reviewed them. That is what the lifecycle is for: a
translation can be complete and fluent and still be attached to the wrong
question, and coverage -- which counts presence, never correctness -- reports
both locales as well translated.

Scope: Odia and Kannada only. The other eleven locales stay approved and
active. Nine more workbooks carry label lines with a mismatched code, but
those are a stale code on the row's own text, which misleads nobody; only
these two have wording proven to belong to another question.

ODK collection is unaffected. Those forms carry their own labels, and their
cells are packed (English and translation together), so an interviewer there
still sees the correct English line.

Idempotent: the UPDATE only matches a locale still ``approved``, so a re-run
changes nothing. Reversible: the prior state of each affected row is captured
into ``_mig_c8e4a1f7b209_prior_locale_state`` first and ``downgrade`` restores
it, because otherwise a downgrade could not know whether a locale had been
approved, by whom, or whether it had been active. ``_mig_`` is excluded from
drift detection by ``app/schema_filters.py``.

Deliberately does NOT correct the strings. The rows are ``imported`` from
workbooks DigitVA does not own; a correction belongs in the admin string
editor, where it becomes ``edited`` and so outranks any future re-import.
"""
from alembic import op
import sqlalchemy as sa


revision = "c8e4a1f7b209"
down_revision = "120f783ea138"
branch_labels = None
depends_on = None

LOCALES = ("or", "kn")
CAPTURE = "_mig_c8e4a1f7b209_prior_locale_state"


def upgrade():
    bind = op.get_bind()

    op.execute(
        sa.text(
            f"""
            CREATE TABLE IF NOT EXISTS {CAPTURE} (
                instrument_code       varchar NOT NULL,
                locale_code           varchar NOT NULL,
                lifecycle_state       varchar NOT NULL,
                is_active             boolean NOT NULL,
                approved_by_user_id   uuid,
                approved_at           timestamptz,
                PRIMARY KEY (instrument_code, locale_code)
            )
            """
        )
    )

    # Capture only on the first run: a second upgrade must not overwrite the
    # original state with the already-demoted one.
    op.execute(
        sa.text(
            f"""
            INSERT INTO {CAPTURE}
                (instrument_code, locale_code, lifecycle_state, is_active,
                 approved_by_user_id, approved_at)
            SELECT instrument_code, locale_code, lifecycle_state, is_active,
                   approved_by_user_id, approved_at
              FROM mas_instrument_locales
             WHERE locale_code IN :locales
               AND lifecycle_state = 'approved'
            ON CONFLICT (instrument_code, locale_code) DO NOTHING
            """
        ).bindparams(sa.bindparam("locales", value=LOCALES, expanding=True))
    )

    # is_active and lifecycle_state move together: the CHECK constraint
    # ck_mas_instrument_locales_active_requires_approved refuses a row that
    # leaves 'approved' while still active, so clearing the flag in the same
    # statement is what keeps this legal.
    result = bind.execute(
        sa.text(
            """
            UPDATE mas_instrument_locales
               SET is_active           = false,
                   lifecycle_state     = 'in_review',
                   approved_by_user_id = NULL,
                   approved_at         = NULL
             WHERE locale_code IN :locales
               AND lifecycle_state = 'approved'
            """
        ).bindparams(sa.bindparam("locales", value=LOCALES, expanding=True))
    )
    print(f"demoted {result.rowcount} locale(s) to in_review: {', '.join(LOCALES)}")


def downgrade():
    op.execute(
        sa.text(
            f"""
            UPDATE mas_instrument_locales AS m
               SET lifecycle_state     = p.lifecycle_state,
                   is_active           = p.is_active,
                   approved_by_user_id = p.approved_by_user_id,
                   approved_at         = p.approved_at
              FROM {CAPTURE} AS p
             WHERE m.instrument_code = p.instrument_code
               AND m.locale_code     = p.locale_code
            """
        )
    )
    op.execute(sa.text(f"DROP TABLE IF EXISTS {CAPTURE}"))
