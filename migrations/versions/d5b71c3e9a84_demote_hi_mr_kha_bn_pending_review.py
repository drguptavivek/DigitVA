"""Demote Hindi, Marathi, Khasi and Bangla pending a speaker's review.

Revision ID: d5b71c3e9a84
Revises: c8e4a1f7b209
Create Date: 2026-09-21

digitva-fb5, continuing c8e4a1f7b209 (Odia and Kannada). Twelve audits read
both halves of every packed cell in the ten deployed workbooks -- the English
reference and its translation sit in the same cell, so the translation can be
judged against the text it claims to render. Each locale below was demoted for
a different reason, recorded here because "four more locales demoted" is not
the same finding four times:

**Hindi** -- eight confirmed defects clustered in the maternal-death block.
``Id10305`` renders "pregnant *and not yet* in labour" as "pregnant *or* in
labour", inverting the connective and dropping the exclusion. ``Id10317``
("How many babies was she pregnant with?") is rendered as a yes/no question
while its answers remain singleton/twins/triplets. ``Id10304`` drops "in the
first 3 months of pregnancy". ``Id10487`` is truncated mid-clause. Hindi is
the most deployed ICMR language, which is an argument for care, not for
leaving it.

**Marathi** -- three duration-unit choice lists are each shifted onto their
neighbour: in ``units_5`` "Days" reads as hours, "Weeks" as days, and "Months"
as "doesn't know", which also makes "Months" and "Doesn't know" identical to
the interviewer. ``M_H_M_DK`` and ``units_4`` are shifted the same way. These
lists back the "for how long" questions across the illness history, so the
label picked does not match the value stored. Also ``Id10024`` asks the year
of *birth* where the English asks the year of *death*.

**Bangla** -- two cells, both high-stakes. ``YES_NO_REF``'s "Yes" contains
Malayalam (``ഉയർന്ന``, "high") rather than Bangla, on four live questions. The
consent text substitutes "a death in the last six months" for "within my
family or close relative", telling a respondent a different scope than the
English of the same cell.

**Khasi** -- not for its defect count but for unverifiability. Roughly 98% of
its text could not be judged by any reviewer available to us, and four real
defects surfaced in the 2% that could be checked mechanically, including a
stated upload limit of 10 where the English says 30 and a certificate
reference pointing at line 1b where the English says Part II. Serving text
nobody has reviewed is what the lifecycle exists to prevent; DigitVA already
treats Khasi as a special case by excluding it from the machine-translated
layer strings.

Malayalam and Tamil were audited to the same depth and stay approved: one
defect each, Malayalam's in a hidden ``calculate`` field and Tamil's a single
dropped "daily" qualifier, both at rates an order of magnitude below the above.

After this, six of thirteen locales are in_review; ar, es, fr, pt and sw come
from WHO's own multilingual workbook rather than a site workbook and were not
in this audit's scope.

ODK collection is unaffected throughout: those forms carry their own labels,
packed with the English, so an interviewer there still sees the English line.

Same shape as c8e4a1f7b209: idempotent (the UPDATE matches only a locale still
``approved``), reversible (prior state captured first), and ``_mig_`` is
excluded from drift detection by ``app/schema_filters.py``. It does not correct
any string -- the rows are imported from workbooks DigitVA does not own, so a
correction belongs in the admin string editor where it becomes ``edited`` and
outranks a re-import.
"""
from alembic import op
import sqlalchemy as sa


revision = "d5b71c3e9a84"
down_revision = "c8e4a1f7b209"
branch_labels = None
depends_on = None

LOCALES = ("hi", "mr", "kha", "bn")
CAPTURE = "_mig_d5b71c3e9a84_prior_locale_state"


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

    # is_active and lifecycle_state move in one statement: the CHECK constraint
    # refuses a row that leaves 'approved' while still active.
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
    # Report what changed, not what was asked for: a locale row may be absent
    # (Khasi is not seeded by the chain -- see 7134cb5dc7b6) or already
    # demoted, and a count that disagrees with the list reads as a bug.
    demoted = [
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT locale_code FROM mas_instrument_locales
                 WHERE locale_code IN :locales AND lifecycle_state = 'in_review'
                 ORDER BY locale_code
                """
            ).bindparams(sa.bindparam("locales", value=LOCALES, expanding=True))
        )
    ]
    print(
        f"requested {', '.join(LOCALES)}; demoted {result.rowcount} now "
        f"({', '.join(demoted) or 'none'} are in_review)"
    )


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
