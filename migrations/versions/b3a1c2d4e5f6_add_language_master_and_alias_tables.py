"""Add language master and alias tables

Revision ID: b3a1c2d4e5f6
Revises: 74a27485dacf
Create Date: 2026-03-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'b3a1c2d4e5f6'
down_revision = '74a27485dacf'
branch_labels = None
depends_on = None

# Canonical languages and their known ODK aliases
_LANGUAGES = [
    ("bangla",     "Bangla",     ["bangla", "bengali", "bn", "Bengali", "Bangla"]),
    ("english",    "English",    ["english", "en", "English", "eng"]),
    ("hindi",      "Hindi",      ["hindi", "hi", "Hindi", "hin"]),
    ("kannada",    "Kannada",    ["kannada", "kn", "Kannada", "kan"]),
    ("malayalam",  "Malayalam",  ["malayalam", "ml", "Malayalam", "mal"]),
    ("marathi",    "Marathi",    ["marathi", "mr", "Marathi", "mar"]),
    ("tamil",      "Tamil",      ["tamil", "ta", "Tamil", "tam"]),
    ("telugu",     "Telugu",     ["telugu", "te", "Telugu", "tel"]),
    ("gujarati",   "Gujarati",   ["gujarati", "gu", "Gujarati", "guj"]),
    ("odia",       "Odia",       ["odia", "or", "Odia", "ori", "oriya", "Oriya"]),
    ("punjabi",    "Punjabi",    ["punjabi", "pa", "Punjabi", "pan"]),
    ("assamese",   "Assamese",   ["assamese", "as", "Assamese", "asm"]),
    ("urdu",       "Urdu",       ["urdu", "ur", "Urdu", "urd"]),
    ("khasi",      "Khasi",      ["khasi", "kha", "Khasi"]),
]


def upgrade():
    # Create mas_languages
    op.create_table(
        'mas_languages',
        sa.Column('language_code', sa.String(length=32), nullable=False),
        sa.Column('language_name', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.PrimaryKeyConstraint('language_code'),
    )

    # Create map_language_aliases
    op.create_table(
        'map_language_aliases',
        sa.Column('alias', sa.String(length=64), nullable=False),
        sa.Column('language_code', sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint('alias'),
        sa.ForeignKeyConstraint(['language_code'], ['mas_languages.language_code']),
    )
    op.create_index(
        'ix_map_language_aliases_language_code',
        'map_language_aliases',
        ['language_code'],
    )

    # Seed canonical languages and aliases
    lang_table = sa.table(
        'mas_languages',
        sa.column('language_code', sa.String),
        sa.column('language_name', sa.String),
        sa.column('is_active', sa.Boolean),
    )
    alias_table = sa.table(
        'map_language_aliases',
        sa.column('alias', sa.String),
        sa.column('language_code', sa.String),
    )

    for code, name, aliases in _LANGUAGES:
        op.execute(lang_table.insert().values(
            language_code=code, language_name=name, is_active=True,
        ))
        seen = set()
        for a in aliases:
            a_lower = a.lower()
            if a_lower not in seen:
                seen.add(a_lower)
                op.execute(alias_table.insert().values(
                    alias=a_lower, language_code=code,
                ))
            # Also insert original case if different
            if a != a_lower and a not in seen:
                seen.add(a)
                op.execute(alias_table.insert().values(
                    alias=a, language_code=code,
                ))

    # Normalize existing va_submissions.va_narration_language values
    # Update any raw value that has a matching alias to its canonical code
    op.execute(sa.text("""
        UPDATE va_submissions s
        SET va_narration_language = a.language_code
        FROM map_language_aliases a
        WHERE lower(s.va_narration_language) = lower(a.alias)
          AND s.va_narration_language != a.language_code
    """))

    # Normalize existing va_users.vacode_language array values
    # For each canonical language, update array elements that match any alias
    conn = op.get_bind()
    for code, _name, aliases in _LANGUAGES:
        for alias in aliases:
            if alias.lower() != code:
                conn.execute(sa.text("""
                    UPDATE va_users
                    SET vacode_language = array_replace(vacode_language, :alias, :code)
                    WHERE :alias = ANY(vacode_language)
                """), {"alias": alias, "code": code})
                # Also handle lowercase variant
                if alias != alias.lower():
                    conn.execute(sa.text("""
                        UPDATE va_users
                        SET vacode_language = array_replace(vacode_language, :alias, :code)
                        WHERE :alias = ANY(vacode_language)
                    """), {"alias": alias.lower(), "code": code})


def downgrade():
    op.drop_index('ix_map_language_aliases_language_code', table_name='map_language_aliases')
    op.drop_table('map_language_aliases')
    op.drop_table('mas_languages')
