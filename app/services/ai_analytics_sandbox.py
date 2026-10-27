"""Run model-written SQL over the AI tables, the caller's aggregates.

docs/policy/ai-analytics-questions.md. Each run, in one transaction on a
connection of its own (released when the run ends):

1. As the app user, under the statement timeout, build the
   transaction-local temp tables the SQL names, and only those, out of
   ``ai_cube``, ``ai_org_levels``, ``ai_staff`` and ``ai_coder``
   (``ai_analytics_tables``: each scoped to the caller, compiled by
   SQLAlchemy, so the cube's retired-submission and confirmed-duplicate
   exclusions come with it).
2. Grant ``digitva_ai_reader`` SELECT on exactly those, make the transaction READ ONLY,
   ``SET LOCAL ROLE digitva_ai_reader`` and cap ``statement_timeout``.
3. Run the SQL through ``digitva_ai_run(text, integer)`` (migration
   a9e4c7f2b3d6): a SECURITY DEFINER function owned by the reader, with
   ``work_mem`` capped at 16MB and ``temp_file_limit`` at 256MB (a role-level
   setting would not apply under SET ROLE). It streams the rows and raises
   SQLSTATE 54D01 once their JSON passes ``AI_OUTPUT_MAX_BYTES``, so a huge
   result never reaches the app; the second argument may only lower that cap
   (tests use it). PostgreSQL
   refuses to change ``role`` inside one, so ``set_config('role', ...)``
   cannot climb back to the app user; a bare ``SET LOCAL ROLE`` alone would
   allow that, because SET ROLE is checked against the session user.
4. Roll back: the temp tables, the grants and every SET LOCAL go with it. Then
   ``pg_advisory_unlock_all()`` as the app user: a session-level advisory lock
   survives a rollback and would otherwise ride the connection back into the
   pool.

The reader needs no grant on the temp schema: it can read a table there it
has SELECT on (checked by tests/services/test_ai_analytics_sandbox.py).

Before any of that, ``validate_sql`` parses the SQL with PostgreSQL's own
parser (pglast) and accepts only a plain SELECT over those tables that calls
allowlisted functions: the database caps time, rows and privileges, but not
one value's memory, and ``repeat('a', 900000000)`` needs no privilege. ``check_sql_text``
is a cheap first filter in front of it. Result rows are never logged.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from pglast import ast, enums, parse_sql, visitors
from pglast.parser import ParseError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.expression import ClauseElement, Executable

from app import db
from app.services import ai_analytics_tables as tables
from app.services.ai_analytics_tables import ORG_NAME_COLUMNS, TABLES, cube_select  # noqa: F401

READER_ROLE = "digitva_ai_reader"
ROW_LIMIT = 500
MAX_SQL_LENGTH = 4000
STATEMENT_TIMEOUT_MS = 5000
# Mirrors the 1048576 in digitva_ai_run (a test checks); bytes of row JSON.
AI_OUTPUT_MAX_BYTES = 1_048_576
OUTPUT_TOO_LARGE_SQLSTATE = "54D01"

# Kept identical to the frozen copy in migration a9e4c7f2b3d6 (a test checks).
# The newline before ") q" keeps a trailing "--" comment from swallowing the
# LIMIT; an unterminated "/*" is a syntax error.
READER_SETUP_SQL = r"""
DO $$
BEGIN
    CREATE ROLE digitva_ai_reader NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
DO $$
BEGIN
    EXECUTE format('GRANT digitva_ai_reader TO %I', current_user);
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
DO $$
BEGIN
    GRANT SET ON PARAMETER temp_file_limit TO digitva_ai_reader;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
DROP FUNCTION IF EXISTS digitva_ai_run(text);
CREATE OR REPLACE FUNCTION digitva_ai_run(query text, max_bytes integer DEFAULT 1048576)
RETURNS SETOF json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET work_mem = '16MB'
SET temp_file_limit = '256MB'
AS $fn$
DECLARE
    r json;
    total bigint := 0;
    cap bigint := least(max_bytes, 1048576);
BEGIN
    FOR r IN EXECUTE 'SELECT to_json(q) FROM (' || query || E'\n) q LIMIT 501' LOOP
        total := total + octet_length(r::text);
        IF total > cap THEN
            RAISE EXCEPTION 'The result is larger than % bytes.', cap USING ERRCODE = '54D01';
        END IF;
        RETURN NEXT r;
    END LOOP;
END
$fn$;
ALTER FUNCTION digitva_ai_run(text, integer) OWNER TO digitva_ai_reader;
REVOKE ALL ON FUNCTION digitva_ai_run(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION digitva_ai_run(text, integer) TO digitva_ai_reader;
"""

_SQL_START = re.compile(r"\s*(select|with)\b", re.IGNORECASE)

# What validate_sql lets through. Everything not listed is refused.
MAX_STRING_CONSTANT = 200
# 1e131000::text is 131001 digits from an 8-character literal, so the
# exponent is bounded as well as the length.
MAX_NUMERIC_CONSTANT = 20
# Every FROM reference (an AI table, a WITH name or a subquery, at any depth): a
# cross join of many copies spills to disk long before the timeout, and each
# level of a nested subquery can square a numeric value.
MAX_RELATIONS = 4
MAX_CTES = 8
ALLOWED_FUNCTIONS = frozenset({
    # aggregates (percentile_* only WITHIN GROUP)
    "count", "sum", "avg", "min", "max", "bool_and", "bool_or",
    "percentile_cont", "percentile_disc",
    # scalar
    "round", "abs", "date_trunc", "extract", "date_part", "to_char", "lower", "upper",
    # window
    "rank", "dense_rank", "row_number", "lag", "lead", "ntile",
})
ALLOWED_CAST_TYPES = frozenset({
    "int", "int2", "int4", "int8", "integer", "smallint", "bigint",
    "numeric", "decimal", "float4", "float8", "real",
    "text", "varchar", "date", "bool", "boolean", "interval",
})
# Arithmetic, comparison and LIKE. No "||": a CTE chain of s || s doubles a
# string per line, a memory bomb without any function.
_ALLOWED_OPERATORS = frozenset({
    "=", "<>", "<", ">", "<=", ">=", "+", "-", "*", "/", "%", "~~", "~~*", "!~~", "!~~*",
})
_ALLOWED_EXPR_KINDS = frozenset({
    enums.A_Expr_Kind.AEXPR_OP, enums.A_Expr_Kind.AEXPR_IN, enums.A_Expr_Kind.AEXPR_LIKE,
    enums.A_Expr_Kind.AEXPR_ILIKE, enums.A_Expr_Kind.AEXPR_BETWEEN,
    enums.A_Expr_Kind.AEXPR_NOT_BETWEEN, enums.A_Expr_Kind.AEXPR_NULLIF,
    enums.A_Expr_Kind.AEXPR_DISTINCT, enums.A_Expr_Kind.AEXPR_NOT_DISTINCT,
})
_ALLOWED_DATETIME_VALUES = frozenset({
    enums.SQLValueFunctionOp.SVFOP_CURRENT_DATE,
    enums.SQLValueFunctionOp.SVFOP_CURRENT_TIMESTAMP,
    enums.SQLValueFunctionOp.SVFOP_CURRENT_TIMESTAMP_N,
    enums.SQLValueFunctionOp.SVFOP_LOCALTIMESTAMP,
    enums.SQLValueFunctionOp.SVFOP_LOCALTIMESTAMP_N,
})
_ALLOWED_SUBLINKS = frozenset({
    enums.SubLinkType.EXISTS_SUBLINK, enums.SubLinkType.ANY_SUBLINK,
    enums.SubLinkType.EXPR_SUBLINK,
})
# Node classes a plain SELECT over the AI tables produces. Anything else (a function
# in FROM, a locking clause, INTO, arrays, XML, row constructors, ...) is refused.
_ALLOWED_NODES = frozenset({
    ast.RawStmt, ast.SelectStmt, ast.ResTarget, ast.ColumnRef, ast.A_Star,
    ast.A_Const, ast.String, ast.Integer, ast.Float, ast.Boolean,
    ast.A_Expr, ast.BoolExpr, ast.NullTest, ast.BooleanTest, ast.CaseExpr, ast.CaseWhen,
    ast.CoalesceExpr, ast.MinMaxExpr, ast.FuncCall, ast.TypeCast, ast.TypeName,
    ast.RangeVar, ast.RangeSubselect, ast.JoinExpr, ast.Alias, ast.SortBy,
    ast.WithClause, ast.CommonTableExpr, ast.SubLink, ast.WindowDef, ast.GroupingSet,
    ast.SQLValueFunction,
})


class SandboxError(Exception):
    """A run that did not return rows.

    ``code`` is ``invalid_sql`` (text or parser check), ``timeout``,
    ``result_too_large`` (over ``AI_OUTPUT_MAX_BYTES``) or ``db_error``; ``message`` is safe to show the user. ``model_message`` is
    what the model may see on its retry: the SQLSTATE and the primary message
    with every quoted value replaced by ``<value>``, so no data value from the
    database reaches the provider.
    """

    def __init__(self, code: str, message: str, model_message: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.model_message = model_message or message


@dataclass(frozen=True)
class SandboxResult:
    columns: list[str]
    rows: list[dict]
    truncated: bool


_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")


def redact_quoted(message: str) -> str:
    """*message* with each ``"..."`` and ``'...'`` replaced by ``<value>``."""
    return _QUOTED.sub("<value>", message)


def check_sql_text(sql) -> str:
    """First filter: one statement starting with SELECT or WITH, bounded."""
    if not isinstance(sql, str) or not sql.strip():
        raise SandboxError("invalid_sql", "The query is empty.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SandboxError("invalid_sql", "The query is too long.")
    if ";" in sql:
        raise SandboxError("invalid_sql", "The query must be one statement with no semicolon.")
    if not _SQL_START.match(sql):
        raise SandboxError("invalid_sql", "The query must start with SELECT or WITH.")
    return sql.strip()


def _refuse(message: str):
    raise SandboxError("invalid_sql", f"The query is not allowed: {message}.")


def _last_name(names) -> str:
    """The unqualified name of a ``pg_catalog``-qualified or bare identifier list."""
    parts = [n.sval for n in names]
    if len(parts) > 2 or (len(parts) == 2 and parts[0] != "pg_catalog"):
        _refuse("names may not carry a schema")
    return parts[-1].lower()


class _Checker(visitors.Visitor):
    """Walks every node of the parse tree; raises ``SandboxError`` on the first refusal."""

    def __init__(self):
        self.ctes: set[str] = set()
        self.relations: list[ast.RangeVar] = []
        self.subselects = 0

    def visit(self, ancestors, node):
        if type(node) not in _ALLOWED_NODES:
            _refuse(f"{type(node).__name__} is not supported")
        check = getattr(self, f"_check_{type(node).__name__}", None)
        if check is not None:
            check(node)

    def _check_SelectStmt(self, node):
        if node.intoClause is not None or node.lockingClause:
            _refuse("SELECT INTO and locking clauses are not supported")

    def _check_WithClause(self, node):
        if node.recursive:
            _refuse("WITH RECURSIVE is not supported")

    def _check_CommonTableExpr(self, node):
        name = node.ctename.lower()
        # Every catalog relation starts with pg_; a CTE so named but out of
        # scope where it is read would fall through to the catalog.
        if name.startswith("pg_"):
            _refuse("a WITH name may not start with pg_")
        self.ctes.add(name)

    def _check_RangeVar(self, node):
        if node.schemaname or node.catalogname:
            _refuse("tables may not carry a schema")
        self.relations.append(node)

    def _check_RangeSubselect(self, node):
        # Counted too: nested FROM subqueries can square a value per level
        # with no table at the bottom.
        self.subselects += 1

    def _check_A_Const(self, node):
        if isinstance(node.val, ast.String) and len(node.val.sval) > MAX_STRING_CONSTANT:
            _refuse(f"text constants are limited to {MAX_STRING_CONSTANT} characters")
        # Integers past int4 arrive as Float too.
        if isinstance(node.val, ast.Float):
            text = node.val.fval
            try:
                exponent = Decimal(text).adjusted()
            except InvalidOperation:  # 0x/0o/0b forms: plain decimals only
                _refuse("numeric constants must be plain decimals")
            if len(text) > MAX_NUMERIC_CONSTANT or abs(exponent) > MAX_NUMERIC_CONSTANT:
                _refuse(f"numeric constants are limited to {MAX_NUMERIC_CONSTANT} digits")

    def _check_SortBy(self, node):
        if node.useOp and (len(node.useOp) != 1 or node.useOp[0].sval not in _ALLOWED_OPERATORS):
            _refuse("that ORDER BY USING operator is not supported")

    def _check_A_Expr(self, node):
        if node.kind not in _ALLOWED_EXPR_KINDS:
            _refuse("that operator form is not supported")
        if node.kind == enums.A_Expr_Kind.AEXPR_OP:
            if len(node.name) != 1 or node.name[0].sval not in _ALLOWED_OPERATORS:
                _refuse(f"the operator {' '.join(n.sval for n in node.name)} is not supported")

    def _check_FuncCall(self, node):
        name = _last_name(node.funcname)
        if name not in ALLOWED_FUNCTIONS:
            _refuse(f"the function {name} is not supported")
        if node.func_variadic:
            _refuse("VARIADIC is not supported")
        if name.startswith("percentile_") and not node.agg_within_group:
            _refuse(f"{name} needs WITHIN GROUP")
        # to_char's output grows with its format; nested formats compound it.
        if name == "to_char" and not (
            node.args and len(node.args) == 2
            and isinstance(node.args[1], ast.A_Const) and isinstance(node.args[1].val, ast.String)
        ):
            _refuse("to_char needs a text constant as its format")

    def _check_TypeName(self, node):
        if node.setof or node.pct_type or node.arrayBounds:
            _refuse("that cast is not supported")
        name = _last_name(node.names)
        if name not in ALLOWED_CAST_TYPES:
            _refuse(f"casts to {name} are not supported")

    def _check_GroupingSet(self, node):
        if node.kind == enums.GroupingSetKind.GROUPING_SET_CUBE:
            _refuse("GROUP BY CUBE is not supported")

    def _check_SubLink(self, node):
        if node.subLinkType not in _ALLOWED_SUBLINKS:
            _refuse("that subquery form is not supported")

    def _check_SQLValueFunction(self, node):
        if node.op not in _ALLOWED_DATETIME_VALUES:
            _refuse("only CURRENT_DATE and CURRENT_TIMESTAMP are supported")

    def _check_ColumnRef(self, node):
        if len(node.fields) > 2:
            _refuse("column names may not carry a schema")


def validate_sql(sql) -> str:
    """Accept *sql* only as one plain SELECT over the AI tables; return it stripped.

    ``_validate`` does the work; this is its public face for callers that only
    need the check.
    """
    return _validate(sql)[0]


def _validate(sql) -> tuple[str, frozenset[str]]:
    """(*sql* stripped, the ``TABLES`` it reads), or ``SandboxError``.

    The text check runs first. Then PostgreSQL's parser: exactly one SELECT
    (no INTO, locking or WITH RECURSIVE), only ``TABLES`` and the query's own
    WITH names in FROM, only ``ALLOWED_FUNCTIONS``, casts to
    ``ALLOWED_CAST_TYPES``, text constants of at most 200 characters, numeric
    constants of at most 20 characters and exponent, at most ``MAX_RELATIONS``
    FROM references and ``MAX_CTES`` WITH names. Raises
    ``SandboxError("invalid_sql", ...)``. Never touches the database.
    """
    sql = check_sql_text(sql)
    try:
        statements = parse_sql(sql)
    except ParseError as exc:
        message = str(exc.args[0]) if exc.args else "syntax error"
        raise SandboxError(
            "invalid_sql", f"The query could not be read: {message}.",
            model_message=f"42601: {redact_quoted(message)}",
        ) from None
    if len(statements) != 1 or not isinstance(statements[0].stmt, ast.SelectStmt):
        _refuse("it must be exactly one SELECT")
    checker = _Checker()
    checker(statements[0])
    if len(checker.relations) + checker.subselects > MAX_RELATIONS:
        _refuse(f"it may name tables in FROM at most {MAX_RELATIONS} times")
    if len(checker.ctes) > MAX_CTES:
        _refuse(f"it may have at most {MAX_CTES} WITH names")
    names = {relation.relname.lower() for relation in checker.relations} - checker.ctes
    if not names <= set(TABLES):
        _refuse(f"it may read only {', '.join(TABLES)}")
    return sql, frozenset(names)


class _CreateTempTable(Executable, ClauseElement):
    inherit_cache = False

    def __init__(self, name, select):
        self.name = name
        self.select = select


@compiles(_CreateTempTable)
def _compile_create_temp_table(element, compiler, **kw):
    # The name is one of TABLES, never text from the query.
    return f"CREATE TEMP TABLE {element.name} ON COMMIT DROP AS " + compiler.process(element.select, **kw)


@contextmanager
def _sandbox_connection():
    """A pooled connection of the sandbox's own, returned when the run ends.

    Tests patch this to the session's connection, where their fixtures live;
    ``_cube_transaction`` then works inside a savepoint.
    """
    with db.engine.connect() as conn:
        yield conn


@contextmanager
def _cube_transaction(conn, builds):
    """Open a transaction on *conn* holding a temp table per (name, SELECT)
    of *builds* (``ai_analytics_tables.build_selects``).

    Each build runs under the statement timeout. Yields *conn* still as the
    app user. Always rolls back, then releases any session-level advisory lock
    taken inside (a rollback does not); if that fails the connection is
    invalidated rather than pooled.
    """
    trans = conn.begin_nested() if conn.in_transaction() else conn.begin()
    try:
        conn.execute(sa.text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT_MS}ms'"))
        for name, select in builds:
            if name not in TABLES:
                raise ValueError(f"{name} is not an AI table")
            conn.execute(_CreateTempTable(name, select))
        yield conn
    finally:
        trans.rollback()
        try:
            conn.execute(sa.text("SELECT pg_advisory_unlock_all()"))
        except sa.exc.DBAPIError:
            conn.invalidate()
            raise


def _become_reader(conn, builds, statement_timeout_ms: int) -> None:
    for name, _select in builds:
        conn.execute(sa.text(f"GRANT SELECT ON {name} TO {READER_ROLE}"))
    # READ ONLY may be set after the transaction's first write; only the
    # change back to read-write is refused once a snapshot exists.
    conn.execute(sa.text("SET LOCAL TRANSACTION READ ONLY"))
    conn.execute(sa.text(f"SET LOCAL ROLE {READER_ROLE}"))
    conn.execute(sa.text(f"SET LOCAL statement_timeout = '{int(statement_timeout_ms)}ms'"))


def run_query(sql, user, *, statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
              output_max_bytes: int = AI_OUTPUT_MAX_BYTES) -> SandboxResult:
    """Run *sql* over *user*'s AI tables as ``digitva_ai_reader``.

    Every caller (model answers, saved queries, built-in reports, catalog
    entries) comes through here, so through ``validate_sql``. Only the tables
    the SQL names are built, each scoped to *user*. Returns at most
    ``ROW_LIMIT`` rows, ``truncated`` when there were more. The database
    refuses a result over *output_max_bytes* (never above
    ``AI_OUTPUT_MAX_BYTES``). Raises ``SandboxError``.
    """
    sql, names = _validate(sql)
    builds = tables.build_selects(user, names)
    with _sandbox_connection() as conn:
        return _run(conn, builds, sql, int(statement_timeout_ms), int(output_max_bytes))


def _run(conn, builds, sql: str, statement_timeout_ms: int,
         output_max_bytes: int = AI_OUTPUT_MAX_BYTES) -> SandboxResult:
    """The database half of ``run_query``, with no parser check (tests call it
    directly to prove the database limits hold on their own)."""
    try:
        with _cube_transaction(conn, builds):
            _become_reader(conn, builds, statement_timeout_ms)
            result = conn.execute(
                sa.text("SELECT * FROM digitva_ai_run(:query, :max_bytes)"),
                {"query": sql, "max_bytes": output_max_bytes},
            )
            rows = [row[0] for row in result.fetchmany(ROW_LIMIT + 1)]
    except sa.exc.DBAPIError as exc:
        raise _sandbox_error(exc) from None
    truncated = len(rows) > ROW_LIMIT
    rows = rows[:ROW_LIMIT]
    columns = list(rows[0]) if rows else []
    return SandboxResult(columns=columns, rows=rows, truncated=truncated)


def explain_query(sql, user) -> None:
    """``EXPLAIN`` *sql* as ``digitva_ai_reader`` over *user*'s AI tables.

    For catalog generation: names, types and privileges are checked without
    running the query. *sql* has passed ``validate_sql`` first, so it is one
    plain SELECT and may be prefixed with EXPLAIN. Raises ``SandboxError``.
    """
    sql, names = _validate(sql)
    builds = tables.build_selects(user, names)
    try:
        with _sandbox_connection() as conn, _cube_transaction(conn, builds):
            _become_reader(conn, builds, STATEMENT_TIMEOUT_MS)
            # The driver formats the statement: a literal % (modulo, LIKE) must be %%.
            conn.exec_driver_sql("EXPLAIN " + sql.replace("%", "%%"))
    except sa.exc.DBAPIError as exc:
        raise _sandbox_error(exc) from None


# Columns of ai_cube a chart category may be broken down from (the drawer).
# ai_staff and ai_coder share the project, site and org_l*_name names, so a
# category of theirs opens the cases of the same place.
DRILL_COLUMNS = (
    "project_id", "site_id", "submission_month", "sex", "analytics_age_band",
    "workflow_state", "authoritative_source", "authoritative_who_bucket_section",
    "authoritative_who_bucket", "authoritative_icd", "smartva_cause1_who_bucket", "nqa_rating",
    "narration_language", "consent_mode", "odk_sync_issue_code", "dm_not_codeable_reason",
    *ORG_NAME_COLUMNS, "final_saved_month", "final_saved_week",
)
DRILL_BY = ("sex", "analytics_age_band", "workflow_state")
DRILL_NONE = "(none)"


def breakdown(user, column: str, value: str) -> dict[str, list[tuple[str | None, int]]]:
    """Counts of one chart category of *user*'s ``ai_cube`` by sex, age band
    and workflow state: {dimension: [(value, n), ...]}.

    Server-authored SQL, run as the app user inside the cube's transaction
    before any role switch: *column* comes from ``DRILL_COLUMNS`` (anything
    else raises ValueError), *value* is bound; ``"(none)"`` means NULL.
    Aggregates only, never a submission.
    """
    if column not in DRILL_COLUMNS:
        raise ValueError("not a drill column")
    cube = sa.table(tables.CUBE, sa.column(column), sa.column("n"), *(sa.column(c) for c in DRILL_BY))
    target = cube.c[column]
    match = target.is_(None) if value == DRILL_NONE else sa.cast(target, sa.Text) == value
    out = {}
    builds = tables.build_selects(user, {tables.CUBE})
    with _sandbox_connection() as conn, _cube_transaction(conn, builds):
        for dim in DRILL_BY:
            rows = conn.execute(
                sa.select(cube.c[dim], sa.func.sum(cube.c.n))
                .where(match)
                .group_by(cube.c[dim])
                .order_by(sa.func.sum(cube.c.n).desc())
            ).all()
            out[dim] = [(key, int(n)) for key, n in rows]
    return out


def _sandbox_error(exc: sa.exc.DBAPIError) -> SandboxError:
    orig = exc.orig
    sqlstate = getattr(orig, "pgcode", None) or "XX000"
    if sqlstate == "57014":
        return SandboxError("timeout", "The query took longer than 5 seconds.")
    if sqlstate == OUTPUT_TOO_LARGE_SQLSTATE:
        return SandboxError(
            "result_too_large", "The result is too large to show. Ask for fewer rows or columns."
        )
    diag = getattr(orig, "diag", None)
    message = getattr(diag, "message_primary", None) or "The query could not run."
    return SandboxError("db_error", message, model_message=f"{sqlstate}: {redact_quoted(message)}")
