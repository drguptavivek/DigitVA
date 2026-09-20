"""Which schema objects Alembic is allowed to compare against the models.

Used by ``migrations/env.py`` (autogenerate and ``flask db check``) and by
``tests/migrations/test_schema_drift.py``, so both see exactly the same diff.
"""

# Owned by the Celery beat scheduler (celery-sqlalchemy-scheduler). These tables
# live in the same database but Celery creates and migrates them.
#
# Filtering by the `celery_` table-name prefix — rather than by "absent from
# target_metadata" — keeps drift detection honest: a table this app used to own
# and that silently vanished from the models still shows up as a real diff.
EXTERNAL_TABLE_PREFIXES = ("celery_",)

# Defined at runtime by the Flask-Session extension, not by an app model, so its
# shape follows the extension's version rather than anything this repo controls.
EXTERNAL_TABLE_NAMES = frozenset({"va_sessions"})

# Owned by a migration, not by a model: a migration that overwrites existing data
# captures what it overwrote here so its own ``downgrade`` can put it back, which
# means the table has to outlive the upgrade. It is deliberately not a model --
# nothing in the application reads it -- so autogenerate would otherwise report
# it as a table to drop.
#
# Prefix-based for the same reason as EXTERNAL_TABLE_PREFIXES above: a name this
# app is supposed to own cannot hide behind the rule by accident, because owning
# it would mean not calling it ``_mig_``.
MIGRATION_TABLE_PREFIXES = ("_mig_",)


def _is_external_table_name(table_name: str | None) -> bool:
    if not table_name:
        return False
    return (
        table_name.startswith(EXTERNAL_TABLE_PREFIXES)
        or table_name.startswith(MIGRATION_TABLE_PREFIXES)
        or table_name in EXTERNAL_TABLE_NAMES
    )


def include_object(object_, name, type_, reflected, compare_to):
    """Alembic ``include_object`` hook: drop externally-owned schema objects.

    Indexes, constraints and columns are judged by their table, so an object
    belonging to an excluded table is excluded with it.
    """
    if type_ == "table":
        return not _is_external_table_name(name)
    table = getattr(object_, "table", None)
    if table is not None:
        return not _is_external_table_name(table.name)
    return True
