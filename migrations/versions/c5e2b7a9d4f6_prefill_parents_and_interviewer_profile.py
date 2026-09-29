"""Parents' names on the death register; interviewer year of birth and sex.

digitva-vzk.1: optional ``father_name`` / ``mother_name`` on
``va_death_register`` prefill WHO ``Id10061`` / ``Id10062``.
digitva-vzk.3: optional ``year_of_birth`` / ``sex`` on ``va_users`` prefill
and lock ``Id10010a`` / ``Id10010b``. All four are personal data, nullable,
validated in the app (no CHECK), never filtered on (no index). Additive;
downgrade drops the four columns.

Revision ID: c5e2b7a9d4f6
Revises: a8d4f1c7e3b9
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c5e2b7a9d4f6"
down_revision = "a8d4f1c7e3b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("va_death_register", sa.Column("father_name", sa.Text(), nullable=True))
    op.add_column("va_death_register", sa.Column("mother_name", sa.Text(), nullable=True))
    op.add_column("va_users", sa.Column("year_of_birth", sa.Integer(), nullable=True))
    op.add_column("va_users", sa.Column("sex", sa.String(length=16), nullable=True))


def downgrade():
    op.drop_column("va_users", "sex")
    op.drop_column("va_users", "year_of_birth")
    op.drop_column("va_death_register", "mother_name")
    op.drop_column("va_death_register", "father_name")
