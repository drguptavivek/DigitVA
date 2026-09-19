"""A migration must not import application code.

A migration that calls into ``app.*`` pins itself to what that code means
*today*, not what it meant when the migration was written. The ``mas_org_unit``
break came from historical migrations calling
``build_submission_analytics_core_mv_sql()``: the service grew columns, and the
old revisions silently started building a different view than the one they were
reviewed as building.

The 15 files in :data:`HISTORICAL_APP_IMPORTERS` are the pre-existing offenders,
frozen exactly as they are. They may be inlined (removing a pin), never
extended: the recorded import set per file is an upper bound, so adding a second
service call to a pinned migration fails here.

Pairs with ``tests/migrations/test_schema_drift.py``, which builds a throwaway
database from nothing but the migration chain (``alembic_upgrade("heads")``) and
compares it against the models. That test proves the chain still replays from
empty; this one proves it replays *meaning the same thing*. Neither is
sufficient alone -- drift only shows up there once the imported code has already
changed shape.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_no_app_imports_in_migrations.py -q
"""
import ast
import tempfile
import unittest
from pathlib import Path

VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"

FAILURE_ADVICE = (
    "A migration must not call application code: it pins itself to what that "
    "code means today. Inline the SQL."
)

# Frozen as of 2026-09-19. Every entry imports MV SQL builders from
# app.services.submission_analytics_mv; no migration imports app.models or any
# other app.* module.
HISTORICAL_APP_IMPORTERS = {
    # demographics MV rebuild after dropping the va_data column
    "080779a13b9f_drop_va_data_column.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_demographics_mv_sql",
    },
    # core MV rebuild adding the org-unit columns
    "2e1da5fbaa0a_core_mv_add_org_unit_columns.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_core_mv_sql",
    },
    # demographics MV rebuild adding va_narration_language
    "a1b3c5d7e9f0_add_va_narration_language_to_demographics_mv.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_demographics_mv_sql",
    },
    # demographics MV rebuild adding age_days, plus the MV name constant
    "ab8c9d0e1f2a_add_age_days_to_demographics_mv.py": {
        "app.services.submission_analytics_mv.DEMOGRAPHICS_MV_NAME",
        "app.services.submission_analytics_mv.build_submission_analytics_demographics_mv_sql",
    },
    # analytics MV rebuild adding cod_pending_upstream_review
    "b1c2d3e4f5a6_rebuild_analytics_mv_add_cod_pending_upstream_review.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_mv_sql",
    },
    # core MV rebuild taking the project from the active site
    "c6d7e8f9a0b1_core_mv_project_from_active_site.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_core_mv_sql",
    },
    # core MV rebuild taking the project from the form
    "c845df6e64f7_core_mv_project_from_form.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_core_mv_sql",
    },
    # analytics MV rebuild for the sync-runs index optimisation
    "cc77dd88ee99_optimise_analytics_mv_and_sync_runs_index.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_mv_sql",
    },
    # core MV rebuild adding the odk-missing flag
    "d3f1a7c92b64_core_mv_odk_missing_flag.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_core_mv_sql",
    },
    # demographics MV rebuild dropping the jsonb join, plus the MV name constant
    "e2f3a4b5c6d7_optimise_demographics_mv_drop_jsonb_join.py": {
        "app.services.submission_analytics_mv.DEMOGRAPHICS_MV_NAME",
        "app.services.submission_analytics_mv.build_submission_analytics_demographics_mv_sql",
    },
    # the split of one analytics MV into core, demographics and cod-detail
    "e95dc3d7c4f2_split_analytics_mv_into_three_focused_.py": {
        "app.services.submission_analytics_mv.build_submission_analytics_core_mv_sql",
        "app.services.submission_analytics_mv.build_submission_analytics_demographics_mv_sql",
        "app.services.submission_analytics_mv.build_submission_cod_detail_mv_sql",
    },
    # first creation of the cod-snapshot MV
    "f7c8d9e0f1a2_add_submission_cod_snapshot_mv.py": {
        "app.services.submission_analytics_mv.build_submission_cod_snapshot_mv_sql",
    },
    # cod-snapshot MV rebuild adding NQA and social-autopsy question columns
    "fa1b2c3d4e5f_expand_cod_snapshot_mv_with_nqa_and_social_autopsy_question_columns.py": {
        "app.services.submission_analytics_mv.build_submission_cod_snapshot_mv_sql",
    },
    # plain cod-snapshot MV rebuild
    "fb2c3d4e5f6a_rebuild_submission_cod_snapshot_mv.py": {
        "app.services.submission_analytics_mv.build_submission_cod_snapshot_mv_sql",
    },
    # cod-snapshot MV rebuild adding unique_id and survey_block
    "fc3d4e5f6a7b_add_unique_id_and_survey_block_to_cod_snapshot_mv.py": {
        "app.services.submission_analytics_mv.build_submission_cod_snapshot_mv_sql",
    },
}


def find_app_imports(path):
    """Return every ``app``/``app.*`` name a Python file imports.

    Parsed with ``ast`` rather than matched with a regex, and walked over the
    whole tree, so an import buried inside ``def upgrade()`` -- where most of
    these live -- counts the same as one at module level. ``from X import y``
    is recorded as ``X.y`` so that a file gaining a second imported symbol from
    the same module is visible as a change.

    Relative imports are ignored: a migration cannot be a package member here.
    """
    names = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "app" or alias.name.startswith("app."):
                    names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level == 0 and (module == "app" or module.startswith("app.")):
                for alias in node.names:
                    names.add(f"{module}.{alias.name}")
    return names


def scan_versions(directory):
    """Map filename -> imported app names, for every file that imports any."""
    found = {}
    for path in sorted(Path(directory).glob("*.py")):
        names = find_app_imports(path)
        if names:
            found[path.name] = names
    return found


class NoAppImportsInMigrationsTest(unittest.TestCase):
    """No database: this reads the migration sources only."""

    @classmethod
    def setUpClass(cls):
        cls.found = scan_versions(VERSIONS_DIR)

    def test_no_unpinned_migration_imports_app(self):
        offenders = {
            name: imports
            for name, imports in self.found.items()
            if name not in HISTORICAL_APP_IMPORTERS
        }
        self.assertEqual(
            offenders,
            {},
            "\n".join(
                f"{name} imports {', '.join(sorted(imports))}"
                for name, imports in sorted(offenders.items())
            )
            + "\n"
            + FAILURE_ADVICE,
        )

    def test_pinned_migrations_still_exist(self):
        missing = [
            name
            for name in HISTORICAL_APP_IMPORTERS
            if not (VERSIONS_DIR / name).is_file()
        ]
        self.assertEqual(
            missing,
            [],
            "Pinned migrations no longer exist; drop them from "
            f"HISTORICAL_APP_IMPORTERS: {missing}",
        )

    def test_pins_are_not_stale(self):
        stale = [
            name
            for name in HISTORICAL_APP_IMPORTERS
            if (VERSIONS_DIR / name).is_file() and name not in self.found
        ]
        self.assertEqual(
            stale,
            [],
            "These migrations no longer import app code -- good. Remove them "
            f"from HISTORICAL_APP_IMPORTERS so the pin cannot mask a relapse: {stale}",
        )

    def test_pinned_imports_have_not_grown(self):
        grown = {
            name: sorted(imports - HISTORICAL_APP_IMPORTERS[name])
            for name, imports in self.found.items()
            if name in HISTORICAL_APP_IMPORTERS
            and imports - HISTORICAL_APP_IMPORTERS[name]
        }
        self.assertEqual(
            grown,
            {},
            "\n".join(
                f"{name} gained {', '.join(added)}"
                for name, added in sorted(grown.items())
            )
            + "\nA pinned migration may be inlined, never extended. "
            + FAILURE_ADVICE,
        )


class CheckerBehaviourTest(unittest.TestCase):
    """Positive and negative controls for the checker itself.

    Without these, the suite above passes just as well if ``find_app_imports``
    silently stops finding anything.
    """

    def test_reports_a_migration_that_imports_a_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "abc123_bad_migration.py"
            path.write_text(
                'revision = "abc123"\n'
                'down_revision = "def456"\n'
                "\n"
                "\n"
                "def upgrade():\n"
                "    from app.services.x import y\n"
                "    op.execute(y())\n",
                encoding="utf-8",
            )
            self.assertEqual(
                scan_versions(tmp),
                {"abc123_bad_migration.py": {"app.services.x.y"}},
            )

    def test_ignores_a_migration_importing_only_alembic_and_sqlalchemy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "abc123_good_migration.py"
            path.write_text(
                "import sqlalchemy as sa\n"
                "from alembic import op\n"
                "\n"
                'revision = "abc123"\n'
                "\n"
                "\n"
                "def upgrade():\n"
                '    op.execute("CREATE MATERIALIZED VIEW v AS SELECT 1")\n',
                encoding="utf-8",
            )
            self.assertEqual(scan_versions(tmp), {})
