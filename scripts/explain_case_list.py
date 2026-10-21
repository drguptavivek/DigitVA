"""EXPLAIN (ANALYZE, BUFFERS) of the case list's queries for one user (digitva-pt0s).

The merge gate of docs/policy/case-list-views.md: run the page, counts and
tiles statements exactly as the API issues them and print each plan. Read-only.

    docker compose exec -T minerva_app_service uv run --no-sync \
        python scripts/explain_case_list.py [--email testadmin@digitva.com] [--preset deaths] [--limit 50]
"""
import argparse
import sys

import sqlalchemy as sa

from app import create_app, db
from app.models import VaDeathRegister, VaUsers
from config import Config

# Copies of one case spread over statuses and time; explicit death_number and a
# SYN- unique_id keep the sequence and the real ids untouched.
SYNTHETIC = """
INSERT INTO va_death_register (death_id, project_id, site_id, org_unit_id, death_number, unique_id,
    deceased_name, deceased_sex, age_years, date_of_death, status, registered_by, source, created_at, updated_at)
SELECT gen_random_uuid(), r.project_id, r.site_id, r.org_unit_id, 900000000 + g, 'SYN-' || g,
    'Synthetic', 'male', 60, current_date - 30,
    (ARRAY['registered', 'in_progress', 'submitted', 'paused', 'refused'])[g % 5 + 1], r.registered_by, 'register',
    now() - (g || ' minutes')::interval, now() - (g || ' minutes')::interval
FROM va_death_register r CROSS JOIN generate_series(1, :n) g WHERE r.death_id = CAST(:src AS uuid)
"""


def explain(label, run):
    """Run *run* once capturing its SELECT, then print that statement's plan."""
    captured = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            captured.append((statement, parameters))

    sa.event.listen(db.engine, "before_cursor_execute", capture)
    try:
        run()
    finally:
        sa.event.remove(db.engine, "before_cursor_execute", capture)
    # The list also runs small lookups (identifier types, org projects); the
    # case statement is the longest one that reads the register.
    statement, parameters = max((c for c in captured if "va_death_register" in c[0]), key=lambda c: len(c[0]))
    print(f"\n=== {label} ===")
    connection = db.session.connection()
    for (line,) in connection.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS) " + statement, parameters):
        print(line)


def main():
    app = create_app(Config)
    # Imported once the app exists: the services import each other in a cycle.
    from app.services import case_list_service as case_list
    from app.services.authz.supervision import supervised_case_condition
    from app.services.web_intake_service import supervision_tiles

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="testadmin@digitva.com")
    parser.add_argument("--preset", default="deaths", choices=case_list.PRESETS)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--synthetic-rows", type=int, default=0,
        help="insert this many copies of an in-scope case first, ANALYZE, explain, then ROLLBACK (the dev "
             "dataset is too small to show a plan's shape; nothing is kept)",
    )
    parser.add_argument(
        "--outside-rows", type=int, default=0,
        help="with --synthetic-rows: also copy a case of --outside-project this many times, interleaved in time, "
             "so the user's scope is a minority of the table (a narrow-scope check)",
    )
    parser.add_argument("--outside-project", default="DEMO01", help="a project the user has no grant in")
    parser.add_argument("--try-sql", help="run this DDL inside the rolled-back transaction before explaining "
                                          "(try an index without keeping it)")
    parser.add_argument("--jit-off", action="store_true",
                        help="SET LOCAL jit = off: the aggregate's cost is high enough to trigger JIT, "
                             "whose compile time (~250 ms here) can exceed the scan itself")
    args = parser.parse_args()
    with app.app_context():
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == args.email))
        if user is None:
            sys.exit("No such user.")
        if args.jit_off:
            db.session.execute(sa.text("SET LOCAL jit = off"))
        print("va_death_register rows:", db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)))
        filters = case_list.CaseFilters()
        if args.synthetic_rows:
            scoped = case_list.list_cases(user, preset=args.preset, filters=filters, limit=1)["cases"]
            if not scoped:
                sys.exit("No case in scope to copy.")
            db.session.execute(sa.text(SYNTHETIC), {"n": args.synthetic_rows, "src": scoped[0]["death_id"]})
            if args.outside_rows:
                outside = db.session.scalar(sa.select(VaDeathRegister.death_id).where(
                    VaDeathRegister.project_id == args.outside_project).limit(1))
                if outside is None:
                    sys.exit("No case in the outside project to copy.")
                db.session.execute(sa.text(SYNTHETIC.replace("'SYN-'", "'SYO-'").replace("900000000", "950000000")),
                                   {"n": args.outside_rows, "src": str(outside)})
            if args.try_sql:
                db.session.execute(sa.text(args.try_sql))
            db.session.execute(sa.text("ANALYZE va_death_register"))
            print("synthetic rows added (rolled back at the end):", args.synthetic_rows)
        explain("page", lambda: case_list.list_cases(user, preset=args.preset, filters=filters, limit=args.limit))
        explain("counts", lambda: case_list.case_list_counts(user, preset=args.preset, filters=filters))
        scope = supervised_case_condition(user)
        if not isinstance(scope, sa.sql.elements.False_):
            explain("tiles", lambda: supervision_tiles(scope))
        db.session.rollback()


if __name__ == "__main__":
    main()
