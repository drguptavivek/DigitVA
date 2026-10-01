"""
Idempotent seed command — safe to run on fresh DB or after test-data restore.

Usage:
  flask seed              # seed bootstrap data (runs on every boot)
  flask seed --test       # also create test users (dev/staging only)
  flask seed test-project # build test project TST001 (dev/staging only)
"""
import os
import uuid
import click
import sqlalchemy as sa
from app import db


@click.group("seed")
def seed_group():
    """Database seed commands."""
    pass


@seed_group.command("run")
@click.option("--test", is_flag=True, default=False, help="Also create test users.")
def seed_run(test):
    """Seed bootstrap data. Safe to run repeatedly."""
    _seed_languages()
    _seed_admin()
    _seed_form_types()
    _seed_who_2022_va_fields()
    _seed_pii_flags()
    _seed_va_cause_definitions()
    if test:
        _seed_test_users()


_SEED_LANGUAGES = [
    ("bangla",     "Bangla",     ["bangla", "bengali", "bn"]),
    ("english",    "English",    ["english", "en", "eng"]),
    ("hindi",      "Hindi",      ["hindi", "hi", "hin"]),
    ("kannada",    "Kannada",    ["kannada", "kn", "kan"]),
    ("malayalam",  "Malayalam",  ["malayalam", "ml", "mal"]),
    ("marathi",    "Marathi",    ["marathi", "mr", "mar"]),
    ("tamil",      "Tamil",      ["tamil", "ta", "tam"]),
    ("telugu",     "Telugu",     ["telugu", "te", "tel"]),
    ("gujarati",   "Gujarati",   ["gujarati", "gu", "guj"]),
    ("odia",       "Odia",       ["odia", "or", "ori", "oriya"]),
    ("punjabi",    "Punjabi",    ["punjabi", "pa", "pan"]),
    ("assamese",   "Assamese",   ["assamese", "as", "asm"]),
    ("urdu",       "Urdu",       ["urdu", "ur", "urd"]),
    ("khasi",      "Khasi",      ["khasi", "kha"]),
]


def _seed_languages():
    """Populate canonical languages and ODK alias mappings."""
    from app.models.mas_languages import MasLanguages, MapLanguageAliases

    added = 0
    for code, name, aliases in _SEED_LANGUAGES:
        existing = db.session.get(MasLanguages, code)
        if existing:
            continue
        lang = MasLanguages(language_code=code, language_name=name, is_active=True)
        db.session.add(lang)
        for alias in aliases:
            if not db.session.get(MapLanguageAliases, alias):
                db.session.add(MapLanguageAliases(alias=alias, language_code=code))
        added += 1

    if added:
        db.session.commit()
        click.echo(f"  [ok]   seeded {added} language(s) with aliases")
    else:
        click.echo("  [skip] languages already seeded")


def _seed_admin():
    """Create the default admin user if it doesn't exist."""
    from app.models import VaUsers, VaUserAccessGrants, VaAccessRoles, VaAccessScopeTypes, VaStatuses

    email = "testadmin@digitva.com"
    existing = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
    if existing:
        click.echo(f"  [skip] admin user already exists: {email}")
        return

    user = VaUsers(
        user_id=uuid.uuid4(),
        name="Test Admin",
        email=email,
        vacode_language=["english"],
        vacode_formcount=0,
        permission={},
        landing_page="admin",
        pw_reset_t_and_c=True,
        email_verified=True,
    )
    user.set_password("Admin@123")
    db.session.add(user)
    db.session.flush()

    grant = VaUserAccessGrants(
        user_id=user.user_id,
        role=VaAccessRoles.admin,
        scope_type=VaAccessScopeTypes.global_scope,
        grant_status=VaStatuses.active,
    )
    db.session.add(grant)
    db.session.commit()
    click.echo(f"  [ok]   created admin user: {email}")


def _seed_form_types():
    """Register built-in form types if not already present."""
    from app.services.form_type_service import get_form_type_service
    service = get_form_type_service()

    FORM_TYPES = [
        {
            "code": "WHO_2022_VA",
            "name": "WHO 2022 VA Form",
            "description": "World Health Organization 2022 Verbal Autopsy Form",
            # The bundled standard instrument this form type layers on; the
            # web form selects its questionnaire by this code.
            "base_instrument_code": "WHO_2022_VA",
        },
    ]

    for ft in FORM_TYPES:
        existing = service.get_form_type(ft["code"])
        if existing:
            click.echo(f"  [skip] form type already exists: {ft['code']}")
        else:
            service.register_form_type(
                form_type_code=ft["code"],
                form_type_name=ft["name"],
                description=ft["description"],
                base_instrument_code=ft["base_instrument_code"],
            )
            click.echo(f"  [ok]   registered form type: {ft['code']}")


def _seed_who_2022_va_fields():
    """Populate field mapping tables for WHO_2022_VA from the Excel source files."""
    from app.models import MasFieldDisplayConfig, MasFormTypes
    import sqlalchemy as sa

    # Check if fields already exist for WHO_2022_VA
    form_type = db.session.scalar(
        sa.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
    )
    if form_type:
        count = db.session.scalar(
            sa.select(sa.func.count()).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id
            )
        )
        if count and count > 0:
            click.echo(f"  [skip] WHO_2022_VA fields already populated ({count} fields)")
            return

    from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator
    click.echo("  [run]  migrating WHO_2022_VA fields from Excel...")
    migrator = Who2022VaMigrator()
    success = migrator.run()
    if success:
        click.echo("  [ok]   WHO_2022_VA field mapping populated")
    else:
        click.echo("  [warn] WHO_2022_VA field migration reported errors — check logs")


def _seed_pii_flags():
    """Flag payload fields that carry personal data.

    Always runs: the Excel source has no is_pii column, so a mapping reseed
    resets the flag to its default. Idempotent — see
    app/services/pii_field_registry.py.
    """
    from app.services.pii_field_registry import apply_pii_field_registry

    totals = apply_pii_field_registry()
    db.session.commit()
    if totals["created"] or totals["updated"]:
        click.echo(
            f"  [ok]   PII flags applied (created {totals['created']}, "
            f"updated {totals['updated']})"
        )
    else:
        click.echo(f"  [skip] PII flags already set ({totals['unchanged']} fields)")


def _seed_va_cause_definitions():
    """Load the WHO VA cause definitions from the shipped seed JSON.

    Idempotent; never overwrites a row an admin edited. The migration seeds
    the same file, so this only fills gaps (e.g. a create_all database).
    """
    from app.services.va_cause_definition_service import (
        import_va_definitions,
        load_seed_rows,
    )

    result = import_va_definitions(load_seed_rows())
    if result.inserted or result.updated:
        click.echo(
            f"  [ok]   VA cause definitions (inserted {result.inserted}, "
            f"updated {result.updated}, kept edited {result.skipped_edited})"
        )
    else:
        click.echo("  [skip] VA cause definitions already loaded")


def _seed_test_users():
    """
    Create the 5 test coder users.
    These are normally present in test_data.sql; this is a fallback for fresh-DB dev.
    """
    from app.models import (
        VaUsers, VaUserAccessGrants, VaAccessRoles, VaAccessScopeTypes,
        VaStatuses, VaProjectSites,
    )

    TEST_CODERS = [
        {"name": "Test Coder NC01", "email": "test.coder.nc01@gmail.com", "site_code": "UNSW01NC0101", "languages": ["english", "hindi"]},
        {"name": "Test Coder NC02", "email": "test.coder.nc02@gmail.com", "site_code": "ICMR01NC0201", "languages": ["english", "hindi"]},
        {"name": "Test Coder KA01", "email": "test.coder.ka01@gmail.com", "site_code": "UNSW01KA0101", "languages": ["english", "hindi"]},
        {"name": "Test Coder KL01", "email": "test.coder.kl01@gmail.com", "site_code": "UNSW01KL0101", "languages": ["english"]},
        {"name": "Test Coder TR01", "email": "test.coder.tr01@gmail.com", "site_code": "UNSW01TR0101", "languages": ["english", "bengali"]},
    ]

    for spec in TEST_CODERS:
        existing = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == spec["email"]))
        if existing:
            click.echo(f"  [skip] test user already exists: {spec['email']}")
            continue

        site = db.session.scalar(
            sa.select(VaProjectSites).where(VaProjectSites.project_site_code == spec["site_code"])
        )
        if site is None:
            click.echo(f"  [warn] site {spec['site_code']} not found, skipping {spec['email']}")
            continue

        user = VaUsers(
            user_id=uuid.uuid4(),
            name=spec["name"],
            email=spec["email"],
            vacode_language=spec["languages"],
            vacode_formcount=30,
            permission={"coder": [spec["site_code"]]},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
        )
        user.set_password("Aiims@123")
        db.session.add(user)
        db.session.flush()

        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.coder,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=site.project_site_id,
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.commit()
        click.echo(f"  [ok]   created test user: {spec['email']}")


# ── flask seed test-project ─────────────────────────────────────────────────
# Roster, tree and grid: docs/current-state/test-project-tst001.md.

TEST_PROJECT_ID = "TST001"
TEST_PROJECT_PASSWORD = "Aiims@123"

#: Levels, cadres and grid come from the district reference model
#: (organization_service.seed_default_organization). TST001 has no villages,
#: so its mandatory village level is deactivated to keep the project ready.
_TST_UNUSED_LEVEL = "village"

#: (unit_code, unit_name, level_code, parent_unit_code), parents first.
_TST_UNITS = (
    ("DH01", "District Hospital", "district", None),
    ("CHC01", "Community Health Centre", "chc", "DH01"),
    ("PHC01", "PHC-AAM 1", "phc", "CHC01"),
    ("PHC02", "PHC-AAM 2", "phc", "CHC01"),
    *((f"SC0{n}", f"SC-AAM {n}", "subcentre", "PHC01" if n <= 3 else "PHC02") for n in range(1, 7)),
)

#: (email local part, landing_page, unit_code, cadre_code, roles). No unit
#: means project scope. Landing pages are the values VaUsers.landing_url
#: honours; each is one the user's roles actually open.
_TST_USERS = (
    ("test.pi", "admin", None, None, ("project_pi",)),
    ("test.dm", "data_manager", None, None, ("data_manager",)),
    ("test.faculty", "data_manager", None, None, ("collaborator_pii", "coding_tester")),
    ("test.resident", "data_manager", None, None, ("collaborator_pii", "coding_tester")),
    ("test.cs.dh01", "sitepi", "DH01", "CS", ("site_pi", "interview_supervisor")),
    ("test.dpm.dh01", "data_manager", "DH01", "DPM", ("data_manager",)),
    ("test.depi.dh01", "data_manager", "DH01", "DEPI", ("collaborator_pii",)),
    ("test.mo.dh01", "coder", "DH01", "MO", ("coder",)),
    ("test.rev.dh01", "reviewer", "DH01", "MO", ("reviewer",)),
    ("test.sn.dh01", "intake", "DH01", "SN", ("interviewer",)),
    ("test.smo.chc01", "reviewer", "CHC01", "SMO", ("interview_supervisor", "reviewer")),
    ("test.mo.chc01", "coder", "CHC01", "MO", ("coder",)),
    ("test.bpm.chc01", "data_manager", "CHC01", "BPM", ("data_manager",)),
    ("test.sn.chc01", "intake", "CHC01", "SN", ("interviewer",)),
    ("test.mo.phc01", "coder", "PHC01", "MO", ("interview_supervisor", "coder")),
    ("test.mo.phc02", "coder", "PHC02", "MO", ("interview_supervisor", "coder")),
    *((f"test.cho.sc0{n}", "intake", f"SC0{n}", "CHO", ("interviewer",)) for n in range(1, 7)),
    # Account and cadre at the unit, deliberately no grant: a future
    # death_reporter role is meant to cover them.
    ("test.anm.sc01", "intake", "SC01", "ANM", ()),
    ("test.mpw.sc04", "intake", "SC04", "MPW", ()),
)


def _tst_email(local: str) -> str:
    return f"{local}@digitva.com"


@seed_group.command("test-project")
@click.option(
    "--staging",
    is_flag=True,
    default=False,
    help="Allow a non-debug app; also needs DIGITVA_ALLOW_TEST_SEED=1 in the environment.",
)
def seed_test_project(staging):
    """Build test project TST001 with its tree, grid and a user in every role.

    Dev/staging only, never part of `seed run`. Idempotent: existing rows are
    found by natural key and reactivated, never deleted or duplicated;
    existing users keep their password, profile and status (a deactivated
    one gets no grants and is listed). Grants go through the
    project user import service, so the level x cadre rules are enforced.
    """
    from flask import current_app

    from app.services import organization_service as org
    from app.services import project_user_import_service as user_import

    staging_allowed = staging and os.environ.get("DIGITVA_ALLOW_TEST_SEED") == "1"
    if not (current_app.debug or current_app.testing or staging_allowed):
        raise click.ClickException(
            "test-project creates accounts with a shared password; it runs only "
            "on a debug or testing app, or with --staging and DIGITVA_ALLOW_TEST_SEED=1."
        )

    _seed_admin()
    try:
        summary = _build_test_project(org, user_import)
    except (org.OrganizationError, user_import.ProjectUserImportError, ValueError) as exc:
        db.session.rollback()
        raise click.ClickException(f"{TEST_PROJECT_ID}: {exc}")
    db.session.commit()
    _log_test_project_grants(summary.pop("audit"), summary.pop("actor_user_id"))
    for key, value in summary.items():
        click.echo(f"  {key:10s} {value}")


def _build_test_project(org, user_import) -> dict:
    """Write everything in the caller's transaction; return counts for the summary."""
    from app.models import MasOrgUnitWorker, VaProjectMaster, VaStatuses, VaUsers
    from app.routes.admin import _with_web_project_defaults

    summary = {}

    # Project: created as the Projects panel creates a web organization
    # project, then given its automatic site and web form.
    project = db.session.get(VaProjectMaster, TEST_PROJECT_ID)
    if project is None:
        defaults = _with_web_project_defaults({})
        form_type_id = defaults.pop("web_intake_form_type_id", None)
        project = VaProjectMaster(
            project_id=TEST_PROJECT_ID,
            project_code=TEST_PROJECT_ID,
            project_name="Intake Test",
            project_nickname="Intake Test",
            project_status=VaStatuses.active,
            project_structure_mode="organization",
            web_intake_mode="both",
            web_intake_form_type_id=uuid.UUID(form_type_id) if form_type_id else None,
            icd_classification="icd10",
            cod_entry_mode="simple",
            masked_cod_required=True,
            reviewer_social_autopsy_enabled=False,
            **defaults,
        )
        db.session.add(project)
        db.session.flush()
        summary["project"] = "created"
    else:
        project.project_status = VaStatuses.active
        summary["project"] = "exists"
    org.require_organization_mode(TEST_PROJECT_ID)
    site = org.ensure_organization_site(TEST_PROJECT_ID)
    summary["site"] = site.site_id

    org.seed_default_organization(TEST_PROJECT_ID)
    levels = {lv.level_code: lv for lv in org.list_levels(TEST_PROJECT_ID, include_inactive=True)}
    used = {level_code for _code, _name, level_code, _parent in _TST_UNITS} | {_TST_UNUSED_LEVEL}
    if missing := sorted(used - levels.keys()):
        # The template skips a level whose depth another code already holds.
        raise org.OrganizationError(
            f"level(s) {', '.join(missing)} missing; another level holds the template depth."
        )
    for code in used - {_TST_UNUSED_LEVEL}:
        if not levels[code].is_active:
            org.update_level(TEST_PROJECT_ID, levels[code].org_level_id, is_active=True)
    if levels[_TST_UNUSED_LEVEL].is_active:
        org.update_level(TEST_PROJECT_ID, levels[_TST_UNUSED_LEVEL].org_level_id, is_active=False)

    units = {}
    for code, name, level_code, parent_code in _TST_UNITS:
        unit = org.find_unit_by_code(TEST_PROJECT_ID, code)
        if unit is None:
            unit = org.create_unit(
                TEST_PROJECT_ID,
                org_level_id=levels[level_code].org_level_id,
                unit_code=code,
                unit_name=name,
                parent_org_unit_id=units[parent_code].org_unit_id if parent_code else None,
            )
        elif not unit.is_active:
            org.set_unit_active(TEST_PROJECT_ID, unit.org_unit_id, True)
        units[code] = unit

    cadres = {c.cadre_code: c for c in org.list_cadres(TEST_PROJECT_ID, include_inactive=True)}
    for code in {cadre_code for *_rest, cadre_code, _roles in _TST_USERS if cadre_code}:
        if not cadres[code].is_active:
            org.update_cadre(TEST_PROJECT_ID, cadres[code].cadre_id, is_active=True)
    summary["tree"] = (
        f"{len(levels)} levels, {len(units)} units, "
        f"{len(org.list_level_cadres(TEST_PROJECT_ID))} grid rows"
    )

    # Users: created like _seed_test_users (verified, onboarded, no forced
    # reset). An existing user keeps password, profile and status: a
    # deactivated account may have been disabled on purpose, so it is never
    # reactivated here; its grants are skipped and it is listed.
    emails = [_tst_email(local) for local, *_ in _TST_USERS]
    users = {
        u.email: u
        for u in db.session.scalars(sa.select(VaUsers).where(VaUsers.email.in_(emails)))
    }
    created_users = 0
    for local, landing, *_ in _TST_USERS:
        email = _tst_email(local)
        if email in users:
            continue
        user = VaUsers(
            user_id=uuid.uuid4(),
            name="Test " + " ".join(part.upper() for part in local.split(".")[1:]),
            email=email,
            vacode_language=["english"],
            vacode_formcount=0,
            permission={},
            landing_page=landing,
            timezone="Asia/Kolkata",
            pw_reset_t_and_c=True,
            email_verified=True,
        )
        user.set_password(TEST_PROJECT_PASSWORD)
        db.session.add(user)
        users[email] = user
        created_users += 1
    db.session.flush()
    summary["users"] = f"{created_users} created, {len(users) - created_users} existing"

    # Workers: the person-holds-cadre-at-unit record, grant or not.
    created_workers = 0
    for local, _landing, unit_code, cadre_code, _roles in _TST_USERS:
        if unit_code is None:
            continue
        worker_code = local.upper().replace(".", "_")
        worker = db.session.scalar(
            sa.select(MasOrgUnitWorker).where(
                MasOrgUnitWorker.project_id == TEST_PROJECT_ID,
                MasOrgUnitWorker.worker_code == worker_code,
            )
        )
        if worker is None:
            org.create_worker(
                TEST_PROJECT_ID,
                org_unit_id=units[unit_code].org_unit_id,
                cadre_id=cadres[cadre_code].cadre_id,
                worker_name=users[_tst_email(local)].name,
                worker_code=worker_code,
                user=_tst_email(local),
            )
            created_workers += 1
        elif not worker.is_active:
            org.update_worker(TEST_PROJECT_ID, worker.worker_id, is_active=True)
    summary["workers"] = f"{created_workers} created"

    # Grants: through the project user import, the admin panel's own path.
    inactive = sorted(
        email for email, user in users.items() if user.user_status != VaStatuses.active
    )
    if inactive:
        summary["skipped"] = "deactivated, no grants: " + ", ".join(inactive)
    grant_specs = [("testadmin@digitva.com", "project_pi", None, None)] + [
        (_tst_email(local), role, unit_code, cadre_code)
        for local, _landing, unit_code, cadre_code, roles in _TST_USERS
        for role in roles
        if _tst_email(local) not in inactive
    ]
    rows = [
        {
            "_line_number": number,
            "email": email,
            "name": "",
            "role": role,
            "org_unit_code": unit_code or "",
            "cadre_code": cadre_code or "",
            "language_codes": "",
            "phone": "",
        }
        for number, (email, role, unit_code, cadre_code) in enumerate(grant_specs, start=1)
    ]
    actor = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "testadmin@digitva.com"))
    plan = user_import.prepare(TEST_PROJECT_ID, rows, is_admin=True)
    _new_users, audit = user_import.apply(TEST_PROJECT_ID, plan, actor_user_id=actor.user_id)
    summary["grants"] = f"{len(audit)} written, {len(plan) - len(audit)} already in place"
    summary["audit"] = audit
    summary["actor_user_id"] = actor.user_id
    return summary


def _log_test_project_grants(audit, actor_user_id) -> None:
    """grants.log lines for what the import wrote, as the import route writes them."""
    from app.logging.va_logger import log_grant_action

    for grant, action in audit:
        log_grant_action(
            action=action, actor_user_id=actor_user_id, actor_role="admin",
            target_user_id=grant["user_id"], grant_id=grant["grant_id"], role=grant["role"],
            scope_type=grant["scope_type"], project_id=TEST_PROJECT_ID,
            org_unit_id=grant["org_unit_id"], cadre_id=grant["cadre_id"],
        )


def init_app(app):
    app.cli.add_command(seed_group)
