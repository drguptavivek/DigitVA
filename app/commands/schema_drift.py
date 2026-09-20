"""CLI command comparing a live database against the migration chain.

``tests/migrations/test_schema_drift.py`` and ``flask db check`` both answer
"do the migrations and the models agree?" by building a throwaway database
from the migration chain and diffing it against ``db.metadata`` with
Alembic's autogenerate. Neither ever looks at a database anyone actually
runs, and autogenerate does not compare CHECK constraint text at all (see
digitva-88e / fd232fab5987) -- a live database can drift from its own
migration history and nothing here would notice.

This command answers the other question: is the database this process is
actually pointed at what its migration history says it should be? It builds
the same throwaway migration-chain database the drift test does, then diffs
it against the live target on the three categories autogenerate silently
ignores: CHECK constraint names and text, column defaults, and enum member
lists. Read-only on the target -- it only ever SELECTs there; it creates and
drops nothing but its own scratch reference database.

Deliberately not compared: table/column/index presence and types (already
covered by autogenerate via ``flask db check``), row data, and anything
outside ``public`` schema tables the app owns (celery's and Flask-Session's
tables are excluded the same way ``schema_filters.py`` excludes them
everywhere else).
"""

import os
import re
import sys

import click
import sqlalchemy as sa

from app.schema_filters import _is_external_table_name

REFERENCE_DB_SUFFIX = "_schema_drift_ref"

# Strips a trailing ``::type`` or ``::type[]`` cast.
_CAST_RE = re.compile(r"::\s*[A-Za-z_][A-Za-z0-9_ ]*(\[\])?")
# Parens directly wrapping a single, comma-free token -- e.g. the ``(...)``
# left behind once a cast inside it is stripped: ``('x')`` -> ``'x'``.
_PAREN_SINGLE_RE = re.compile(r"\(([^(),]+)\)")


def _strip_doubled_parens(text):
    """Collapse an outer paren whose entire content is one inner paren pair.

    ``ANY ((ARRAY[...]))`` and ``ANY (ARRAY[...])`` are the same expression;
    the extra wrap is left behind when a whole-array cast (``(...)::text[]``)
    is stripped by ``_CAST_RE`` but the surrounding ``ANY (...)`` parens
    were already there. Unlike ``_PAREN_SINGLE_RE`` this content may contain
    commas (an ``ARRAY[a, b]`` literal), so it is only safe to strip when the
    inner pair exactly fills the outer one -- found by matching parens with a
    stack rather than by regex, since regex cannot track nesting depth.
    """
    while True:
        stack = []
        pairs = {}
        for idx, ch in enumerate(text):
            if ch == "(":
                stack.append(idx)
            elif ch == ")" and stack:
                pairs[stack.pop()] = idx
        redundant = next(
            (
                (open_idx, close_idx)
                for open_idx, close_idx in pairs.items()
                if text[open_idx + 1 : open_idx + 2] == "("
                and pairs.get(open_idx + 1) == close_idx - 1
            ),
            None,
        )
        if redundant is None:
            return text
        open_idx, close_idx = redundant
        text = text[:open_idx] + text[open_idx + 1 : close_idx] + text[close_idx + 1 :]


def _normalize_sql(text):
    """Collapse the cast/paren spellings Postgres treats as equivalent.

    The same semantic CHECK or DEFAULT can render as
    ``ARRAY[('x'::varchar)::text]`` in one database and
    ``ARRAY['x'::varchar]::text[]`` in another, depending on how the object
    was created -- not because the rule differs (digitva-88e). Stripping
    type casts and then repeatedly unwrapping redundant parens (single
    comma-free tokens, and outer pairs that exactly double an inner pair)
    makes both forms compare equal without parsing SQL. Column/table naming,
    whitespace and operator spelling (``IN`` vs. ``= ANY``, which Postgres
    itself normalizes to the latter) are left as Postgres renders them.
    """
    if text is None:
        return None
    stripped = _CAST_RE.sub("", text)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    previous = None
    while previous != stripped:
        previous = stripped
        stripped = _PAREN_SINGLE_RE.sub(r"\1", stripped)
        stripped = _strip_doubled_parens(stripped)
    return stripped


def _check_constraints(conn):
    """{(table, name): normalized_def} for every app-owned CHECK constraint."""
    rows = conn.execute(
        sa.text(
            "SELECT conrelid::regclass::text AS table_name, conname, "
            "pg_get_constraintdef(oid) AS condef "
            "FROM pg_constraint WHERE contype = 'c'"
        )
    ).all()
    return {
        (row.table_name, row.conname): _normalize_sql(row.condef)
        for row in rows
        if not _is_external_table_name(row.table_name)
    }


def _column_defaults(conn):
    """{(table, column): normalized_default} for every app-owned default."""
    rows = conn.execute(
        sa.text(
            "SELECT table_name, column_name, column_default "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND column_default IS NOT NULL"
        )
    ).all()
    return {
        (row.table_name, row.column_name): _normalize_sql(row.column_default)
        for row in rows
        if not _is_external_table_name(row.table_name)
    }


def _enum_members(conn):
    """{enum_type_name: [members in declared order]} for every enum type."""
    rows = conn.execute(
        sa.text(
            "SELECT t.typname, e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "ORDER BY t.typname, e.enumsortorder"
        )
    ).all()
    members = {}
    for row in rows:
        members.setdefault(row.typname, []).append(row.enumlabel)
    return members


def _diff_mapping(reference, target, describe):
    """Report keys and values that differ between two ``{key: value}`` maps."""
    diffs = []
    for key in sorted(set(reference) | set(target), key=repr):
        if key not in target:
            diffs.append(f"{describe(key)}: missing on target (reference has it)")
        elif key not in reference:
            diffs.append(f"{describe(key)}: extra on target (not in migration chain)")
        elif reference[key] != target[key]:
            diffs.append(
                f"{describe(key)}: differs\n"
                f"    reference: {reference[key]!r}\n"
                f"    target:    {target[key]!r}"
            )
    return diffs


def _build_reference_database(target_url):
    """Create and migrate a scratch database from the chain alone; return its URL."""
    reference_db_name = f"{target_url.database}{REFERENCE_DB_SUFFIX}"
    reference_url = target_url.set(database=reference_db_name)

    admin_engine = sa.create_engine(
        target_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{reference_db_name}"'))
            conn.execute(sa.text(f'CREATE DATABASE "{reference_db_name}"'))
    finally:
        admin_engine.dispose()

    import tempfile

    from flask_migrate import upgrade as alembic_upgrade

    from app import create_app
    from config import Config

    class ReferenceConfig(Config):
        SQLALCHEMY_DATABASE_URI = reference_url.render_as_string(hide_password=False)
        CELERY = {**Config.CELERY, "beat_dburi": SQLALCHEMY_DATABASE_URI}
        # A second create_app() call redeclares the va_sessions model against
        # the same shared SQLAlchemy metadata; Flask-Session's "sqlalchemy"
        # backend would collide on that (InvalidRequestError: Table
        # 'va_sessions' is already defined). "filesystem" sidesteps it, same
        # as TestConfig does for the same reason.
        SESSION_TYPE = "filesystem"
        SESSION_FILE_DIR = os.path.join(
            tempfile.gettempdir(), "digitva_schema_drift_flask_session"
        )

    # celery_init_app (inside create_app) makes the new Celery instance the
    # process-global default, which would otherwise leak into whatever this
    # CLI process does afterwards. Restore the previous default/current app
    # once the reference app has been built.
    from celery import _state as celery_state

    previous_default = celery_state.default_app
    previous_current = getattr(celery_state._tls, "current_app", None)
    try:
        reference_app = create_app(ReferenceConfig)
    finally:
        celery_state.default_app = previous_default
        celery_state._tls.current_app = previous_current

    with reference_app.app_context():
        alembic_upgrade(revision="heads")
        # Otherwise the reference app's own pooled connection keeps the
        # database open and the later DROP DATABASE fails with
        # "database is being accessed by other users".
        from app import db as reference_db

        reference_db.engine.dispose()

    return reference_url


def _drop_reference_database(target_url, reference_url):
    admin_engine = sa.create_engine(
        target_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        with admin_engine.connect() as conn:
            conn.execute(
                sa.text(f'DROP DATABASE IF EXISTS "{reference_url.database}"')
            )
    finally:
        admin_engine.dispose()


@click.group("schema")
def schema_group():
    """Schema-integrity commands."""
    pass


@schema_group.command("drift-check")
def drift_check():
    """Compare this app's live database against a fresh replay of the migration chain.

    Read-only on the target: builds a scratch database with ``flask db
    upgrade`` alone, diffs it against the live database on CHECK constraints,
    column defaults and enum members, then drops the scratch database.
    Prints every difference found and exits non-zero if there is at least
    one, so it can gate a deploy.
    """
    from app import db

    target_url = db.engine.url
    reference_url = _build_reference_database(target_url)
    try:
        reference_engine = sa.create_engine(reference_url)
        try:
            with reference_engine.connect() as ref_conn:
                reference_checks = _check_constraints(ref_conn)
                reference_defaults = _column_defaults(ref_conn)
                reference_enums = _enum_members(ref_conn)
        finally:
            reference_engine.dispose()

        with db.engine.connect() as target_conn:
            target_checks = _check_constraints(target_conn)
            target_defaults = _column_defaults(target_conn)
            target_enums = _enum_members(target_conn)
    finally:
        _drop_reference_database(target_url, reference_url)

    diffs = []
    diffs += _diff_mapping(
        reference_checks, target_checks, lambda k: f"CHECK {k[0]}.{k[1]}"
    )
    diffs += _diff_mapping(
        reference_defaults, target_defaults, lambda k: f"DEFAULT {k[0]}.{k[1]}"
    )
    diffs += _diff_mapping(reference_enums, target_enums, lambda k: f"ENUM {k}")

    if not diffs:
        click.echo("No drift: target database matches the migration chain.")
        return

    click.echo(f"{len(diffs)} difference(s) between the target database and the migration chain:")
    for diff in diffs:
        click.echo(f"- {diff}")
    sys.exit(1)


def init_app(app):
    """Register schema-integrity CLI commands with the Flask app."""
    app.cli.add_command(schema_group)
