"""
Idempotent seed command — safe to run on fresh DB or after test-data restore.

Usage:
  flask seed              # seed bootstrap data (runs on every boot)
  flask seed --test       # also create test users (dev/staging only)
  flask seed test-project # build test project TST001 (dev/staging only)
"""
import os
import secrets
import uuid
import click
import sqlalchemy as sa
from app import db
from app.services.user_account_service import creation_other


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
    _seed_missing_translation_sources()
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
        other=creation_other("seed"),
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


def _seed_missing_translation_sources():
    """Import documented questionnaire sources that have not been installed.

    The importer owns no transaction boundary: a source error rolls back the
    batch here and aborts seed, so a restart cannot leave half a source set.
    """
    from app.services.instrument_translation_source_catalog import (
        bootstrap_missing_sources,
    )

    try:
        report = bootstrap_missing_sources()
    except Exception:
        db.session.rollback()
        raise
    if report.imported:
        db.session.commit()
        click.echo(
            f"  [ok]   translation sources imported ({len(report.imported)} locales, "
            f"{report.written} strings)"
        )
    else:
        click.echo(
            f"  [skip] translation sources already established "
            f"({len(report.skipped)} locales)"
        )


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
            other=creation_other("seed"),
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

# ICD-11 pairs with DORIS entry (the project check constraint).
_TST_ICD_CLASSIFICATION = "icd11"
_TST_COD_ENTRY_MODE = "doris"
#: Central-office answers for Id10002 (HIV) and Id10003 (malaria), set on the
#: root unit so the whole tree inherits them. Id10004 (season) stays asked.
_TST_PRESET_UNIT = "DH01"
_TST_VA_PRESET = "low"

#: Levels, cadres and grid come from the district reference model
#: (organization_service.seed_default_organization). TST001 has no villages,
#: so its village level is deactivated (it was mandatory in older templates
#: and stays deactivated on reseed).
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
    # No site_pi: it is not held at a unit (the project PI covers every district).
    ("test.cs.dh01", "intake", "DH01", "CS", ("interview_supervisor",)),
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
    # Register deaths but never interview; the app is their only surface, so
    # the web landing page falls through to the home page.
    ("test.anm.sc01", "intake", "SC01", "ANM", ("death_reporter",)),
    ("test.mpw.sc04", "intake", "SC04", "MPW", ("death_reporter",)),
    # One login for every surface: project-scope coder and reviewer (pick and
    # choose coding), a unit-scope death reporter (SC01 ANM) and supervisor
    # (PHC01 MO), since those two roles need a cadre the grid permits. The
    # same person repeats across rows; the first row sets the landing page.
    ("test.all", "coder", None, None, ("coder", "reviewer")),
    ("test.all", "coder", "SC01", "ANM", ("death_reporter",)),
    ("test.all", "coder", "PHC01", "MO", ("interview_supervisor",)),
)

#: (email local part, existing classical project, role): project-scope grants
#: in sites projects, written when the project exists (e.g. SADEMO in dev).
_TST_CLASSICAL_GRANTS = (("test.all", "SADEMO", "coder"),)


def _tst_email(local: str) -> str:
    return f"{local}@digitva.com"


@seed_group.command("test-project")
@click.option(
    "--staging",
    is_flag=True,
    default=False,
    help="Staging mode: allows a non-debug app (also needs DIGITVA_ALLOW_TEST_SEED=1), "
    "needs --actor-email, and creates no admin or project_pi account.",
)
@click.option(
    "--actor-email",
    default=None,
    help="Staging only: an active global admin recorded as the actor of every grant.",
)
def seed_test_project(staging, actor_email):
    """Build test project TST001 with its tree, grid and a user in every role.

    Dev/staging only, never part of `seed run`. Idempotent: existing rows are
    found by natural key and reactivated, never deleted or duplicated;
    existing users keep their password, profile and status (a deactivated
    one gets no grants and is listed). Grants go through the
    project user import service, so the level x cadre rules are enforced.

    Dev (no --staging) seeds testadmin as actor and TST001 PI, and gives new
    users the shared documented password. --staging (real users) uses the
    --actor-email admin instead, skips testadmin, every project_pi grant and
    the SADEMO grant, and gives each new user a random password that is
    never shown or kept; the operator sets real passwords afterwards.
    """
    from flask import current_app

    from app.services import organization_service as org
    from app.services import project_user_import_service as user_import

    staging_allowed = staging and os.environ.get("DIGITVA_ALLOW_TEST_SEED") == "1"
    if not (current_app.debug or current_app.testing or staging_allowed):
        raise click.ClickException(
            "test-project creates test accounts; it runs only "
            "on a debug or testing app, or with --staging and DIGITVA_ALLOW_TEST_SEED=1."
        )

    from app.models import VaUsers

    if actor_email is not None and not staging:
        # Dev mode's actor is the seeded testadmin; a second actor would be ambiguous.
        raise click.ClickException("--actor-email applies only with --staging.")
    if staging:
        if not actor_email:
            raise click.ClickException("--staging needs --actor-email (an active global admin).")
        actor = db.session.scalar(
            sa.select(VaUsers).where(VaUsers.email == actor_email.strip().lower())
        )
        if actor is None or not actor.is_active or not actor.is_admin():
            raise click.ClickException(
                "--actor-email must name an active user with an active global admin grant."
            )
    else:
        _seed_admin()
        actor = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "testadmin@digitva.com"))
    try:
        summary = _build_test_project(org, user_import, actor, staging=staging)
    except (org.OrganizationError, user_import.ProjectUserImportError, ValueError) as exc:
        db.session.rollback()
        raise click.ClickException(f"{TEST_PROJECT_ID}: {exc}")
    db.session.commit()
    _log_test_project_grants(summary.pop("audit"), summary.pop("actor_user_id"))
    for key, value in summary.items():
        click.echo(f"  {key:10s} {value}")


def _build_test_project(org, user_import, actor, *, staging: bool) -> dict:
    """Write everything in the caller's transaction; return counts for the summary.

    *actor* is the global admin recorded on the import and audit. *staging*
    drops project_pi from the roster (and any user left with no role), the
    testadmin PI grant and the SADEMO grant, and gives new users a random
    password instead of TEST_PROJECT_PASSWORD.
    """
    from app.models import (
        MasOrgUnitWorker, VaAccessRoles, VaAccessScopeTypes, VaProjectMaster,
        VaStatuses, VaUserAccessGrants, VaUsers,
    )
    from app.routes.admin import _project_has_in_progress_coding, _with_web_project_defaults

    summary = {}
    roster = _TST_USERS
    if staging:
        # Owner rule: no project admin is created or granted on staging.
        roster = tuple(
            (local, landing, unit_code, cadre_code, kept)
            for local, landing, unit_code, cadre_code, roles in _TST_USERS
            if (kept := tuple(role for role in roles if role != "project_pi"))
        )

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
            icd_classification=_TST_ICD_CLASSIFICATION,
            cod_entry_mode=_TST_COD_ENTRY_MODE,
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
        # A rerun moves an older ICD-10 TST001 to ICD-11 + DORIS, under the
        # admin route's own guard: never while coding is in progress.
        if (project.icd_classification, project.cod_entry_mode) != (
            _TST_ICD_CLASSIFICATION, _TST_COD_ENTRY_MODE,
        ):
            if _project_has_in_progress_coding(TEST_PROJECT_ID):
                summary["cod"] = (
                    f"kept {project.icd_classification}/{project.cod_entry_mode} "
                    "(coding in progress)"
                )
            else:
                project.icd_classification = _TST_ICD_CLASSIFICATION
                project.cod_entry_mode = _TST_COD_ENTRY_MODE
                summary["cod"] = "updated to icd11/doris"
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
    for code in {cadre_code for *_rest, cadre_code, _roles in roster if cadre_code}:
        if not cadres[code].is_active:
            org.update_cadre(TEST_PROJECT_ID, cadres[code].cadre_id, is_active=True)
    summary["tree"] = (
        f"{len(levels)} levels, {len(units)} units, "
        f"{len(org.list_level_cadres(TEST_PROJECT_ID))} grid rows"
    )

    # Central-office area presets (Id10002/Id10003) on the root unit, which
    # every descendant inherits. Only an unset field is filled, so a value
    # an admin set by hand survives a rerun.
    own = org.get_unit_va_presets(TEST_PROJECT_ID, units[_TST_PRESET_UNIT].org_unit_id)
    hiv = own.hiv_mortality if own else None
    malaria = own.malaria_mortality if own else None
    if hiv is None or malaria is None:
        org.set_unit_va_presets(
            TEST_PROJECT_ID,
            units[_TST_PRESET_UNIT].org_unit_id,
            hiv_mortality=hiv or _TST_VA_PRESET,
            malaria_mortality=malaria or _TST_VA_PRESET,
            actor_id=actor.user_id,
        )
        summary["presets"] = f"{_TST_PRESET_UNIT}: Id10002/Id10003 = {_TST_VA_PRESET}"
    else:
        summary["presets"] = f"{_TST_PRESET_UNIT}: already set"

    # Users: created like _seed_test_users (verified, onboarded, no forced
    # reset). An existing user keeps password, profile and status: a
    # deactivated account may have been disabled on purpose, so it is never
    # reactivated here; its grants are skipped and it is listed.
    emails = [_tst_email(local) for local, *_ in roster]
    users = {
        u.email: u
        for u in db.session.scalars(sa.select(VaUsers).where(VaUsers.email.in_(emails)))
    }
    created_users = 0
    for local, landing, *_ in roster:
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
            other=creation_other("seed"),
        )
        # Staging: unknown to anyone; never echoed, logged or stored in clear.
        user.set_password(secrets.token_urlsafe(32) if staging else TEST_PROJECT_PASSWORD)
        db.session.add(user)
        users[email] = user
        created_users += 1
    db.session.flush()
    summary["users"] = f"{created_users} created, {len(users) - created_users} existing"

    # Workers: the person-holds-cadre-at-unit record, grant or not.
    created_workers = 0
    for local, _landing, unit_code, cadre_code, _roles in roster:
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
    grant_specs = ([] if staging else [("testadmin@digitva.com", "project_pi", None, None)]) + [
        (_tst_email(local), role, unit_code, cadre_code)
        for local, _landing, unit_code, cadre_code, roles in roster
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
    plan = user_import.prepare(TEST_PROJECT_ID, rows, actor=actor)
    _new_users, audit, _codes = user_import.apply(TEST_PROJECT_ID, plan, actor_user_id=actor.user_id)
    written, total = len(audit), len(plan)
    # Sites projects: the import is organization-only, so write the one
    # project-scope grant the way the admin panel does (admin.py grants).
    for local, project_id, role in () if staging else _TST_CLASSICAL_GRANTS:
        user = users[_tst_email(local)]
        if db.session.get(VaProjectMaster, project_id) is None or user.user_status != VaStatuses.active:
            continue
        total += 1
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.role == VaAccessRoles(role),
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id == project_id,
        ))
        if grant is None:
            grant = VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles(role),
                scope_type=VaAccessScopeTypes.project, project_id=project_id,
                grant_status=VaStatuses.active, created_by_user_id=actor.user_id,
            )
            db.session.add(grant)
            action = "grant_created"
        elif grant.grant_status != VaStatuses.active:
            grant.grant_status = VaStatuses.active
            action = "grant_reactivated"
        else:
            continue
        db.session.flush()
        audit.append((dict(user_id=user.user_id, grant_id=grant.grant_id, role=role,
                           scope_type="project", org_unit_id=None, cadre_id=None,
                           project_id=project_id), action))
        written += 1
    summary["grants"] = f"{written} written, {total - written} already in place"
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
            scope_type=grant["scope_type"], project_id=grant.get("project_id", TEST_PROJECT_ID),
            org_unit_id=grant["org_unit_id"], cadre_id=grant["cadre_id"],
        )


def init_app(app):
    app.cli.add_command(seed_group)
