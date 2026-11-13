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


def _seed_password(documented: str):
    """Return (password, show_once).

    The documented dev passwords apply only on a debug or testing app; any
    other app (staging, production) gets a random one, so a publicly reachable
    deployment never carries a password written in the docs.
    """
    from flask import current_app

    if current_app.debug or current_app.testing:
        return documented, False
    return secrets.token_urlsafe(16), True


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
    password, show_once = _seed_password("Admin@123")
    user.set_password(password)
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
    if show_once:
        # Terminal only, never logged; same as `flask users reset-password`.
        click.echo(f"  password (shown once): {password}")


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
        # Random and not shown off dev; the operator uses `flask users reset-password`.
        user.set_password(_seed_password("Aiims@123")[0])
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
TEST_PROJECT_2_ID = "TST002"
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
    # A second interviewer in scope of SC01 cases (the other-interviewer warning).
    ("test.cho.sc02", "intake", "SC01", "CHO", ("interviewer",)),
    # Register deaths but never interview; the app is their only surface, so
    # the web landing page falls through to the home page.
    ("test.anm.sc01", "intake", "SC01", "ANM", ("death_reporter",)),
    ("test.mpw.sc04", "intake", "SC04", "MPW", ("death_reporter",)),
    # One login for every surface: project-scope coder, reviewer and data
    # manager (pick and choose coding, Data, Users), a unit-scope death
    # reporter and interviewer (SC01 ANM: its grid row permits both) and
    # supervisor (PHC01 MO), since those roles need a cadre the grid permits. The
    # same person repeats across rows; the first row sets the landing page.
    ("test.all", "coder", None, None, ("coder", "reviewer", "data_manager")),
    ("test.all", "coder", "SC01", "ANM", ("death_reporter", "interviewer")),
    ("test.all", "coder", "PHC01", "MO", ("interview_supervisor",)),
)

#: Projects the command builds, in order; the first is the one whose summary
#: prints without a heading. masked_cod_required false is single-step coding.
#: narrative_qa_enabled turns the narrative quality assessment on;
#: social_autopsy_enabled also adds the social_autopsy form layer the
#: questionnaire collects (enabled_extensions derives from it), and the
#: reviewer switch follows it. classical_grants: the SADEMO grants below.
_TST_PROJECTS = (
    {"project_id": TEST_PROJECT_ID, "name": "Intake Test", "masked_cod_required": True,
     "narrative_qa_enabled": False, "social_autopsy_enabled": False, "classical_grants": True},
    {"project_id": TEST_PROJECT_2_ID, "name": "Intake Test (single-step)", "masked_cod_required": False,
     "narrative_qa_enabled": True, "social_autopsy_enabled": True, "classical_grants": False},
)

#: (email local part, existing classical project, role): project-scope grants
#: in sites projects, written when the project exists (e.g. SADEMO in dev).
_TST_CLASSICAL_GRANTS = (("test.all", "SADEMO", "coder"), ("test.all", "SADEMO", "reviewer"))


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
    """Build test projects TST001 (masked two-step coding) and TST002 (single-step,
    narrative QA and social autopsy on), each with tree, grid and a user in every role.

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
    from app.services.consent_service import ConsentError

    summaries = []
    for spec in _TST_PROJECTS:
        try:
            summaries.append(_build_test_project(org, user_import, actor, spec, staging=staging))
        except (org.OrganizationError, user_import.ProjectUserImportError, ConsentError, ValueError) as exc:
            db.session.rollback()
            raise click.ClickException(f"{spec['project_id']}: {exc}")
    db.session.commit()
    for spec, summary in zip(_TST_PROJECTS, summaries):
        _log_test_project_grants(summary.pop("audit"), summary.pop("actor_user_id"), spec["project_id"])
        if spec["project_id"] != TEST_PROJECT_ID:
            click.echo(f"{spec['project_id']}")
        for key, value in summary.items():
            click.echo(f"  {key:10s} {value}")


def _build_test_project(org, user_import, actor, spec: dict, *, staging: bool) -> dict:
    """Write everything in the caller's transaction; return counts for the summary.

    *spec* is one _TST_PROJECTS entry (id, names, coding mode, NQA and Social
    Autopsy switches); it applies only when the project is created, so a
    rerun keeps values set by hand. *actor* is the global admin recorded on
    the import and audit. *staging*
    drops project_pi from the roster (and any user left with no role), the
    testadmin PI grant and the SADEMO grant, and gives new users a random
    password instead of TEST_PROJECT_PASSWORD.
    """
    from app.models import (
        MasOrgUnitWorker, VaAccessRoles, VaAccessScopeTypes, VaProjectMaster,
        VaStatuses, VaUserAccessGrants, VaUsers,
    )
    from app.routes.admin import _project_has_in_progress_coding, _with_web_project_defaults
    from app.services import mentor_institute_service

    project_id = spec["project_id"]
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
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        defaults = _with_web_project_defaults({})
        form_type_id = defaults.pop("web_intake_form_type_id", None)
        defaults.pop("social_autopsy_enabled", None)  # the spec sets it
        project = VaProjectMaster(
            project_id=project_id,
            project_code=project_id,
            project_name=spec["name"],
            project_nickname=spec["name"],
            project_status=VaStatuses.active,
            project_structure_mode="organization",
            web_intake_mode="both",
            web_intake_form_type_id=uuid.UUID(form_type_id) if form_type_id else None,
            icd_classification=_TST_ICD_CLASSIFICATION,
            cod_entry_mode=_TST_COD_ENTRY_MODE,
            masked_cod_required=spec["masked_cod_required"],
            narrative_qa_enabled=spec["narrative_qa_enabled"],
            social_autopsy_enabled=spec["social_autopsy_enabled"],
            reviewer_social_autopsy_enabled=spec["social_autopsy_enabled"],
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
            if _project_has_in_progress_coding(project_id):
                summary["cod"] = (
                    f"kept {project.icd_classification}/{project.cod_entry_mode} "
                    "(coding in progress)"
                )
            else:
                project.icd_classification = _TST_ICD_CLASSIFICATION
                project.cod_entry_mode = _TST_COD_ENTRY_MODE
                summary["cod"] = "updated to icd11/doris"
    org.require_organization_mode(project_id)
    site = org.ensure_organization_site(project_id)
    summary["site"] = site.site_id

    org.seed_default_organization(project_id)
    levels = {lv.level_code: lv for lv in org.list_levels(project_id, include_inactive=True)}
    used = {level_code for _code, _name, level_code, _parent in _TST_UNITS} | {_TST_UNUSED_LEVEL}
    if missing := sorted(used - levels.keys()):
        # The template skips a level whose depth another code already holds.
        raise org.OrganizationError(
            f"level(s) {', '.join(missing)} missing; another level holds the template depth."
        )
    for code in used - {_TST_UNUSED_LEVEL}:
        if not levels[code].is_active:
            org.update_level(project_id, levels[code].org_level_id, is_active=True)
    if levels[_TST_UNUSED_LEVEL].is_active:
        org.update_level(project_id, levels[_TST_UNUSED_LEVEL].org_level_id, is_active=False)

    units = {}
    for code, name, level_code, parent_code in _TST_UNITS:
        unit = org.find_unit_by_code(project_id, code)
        if unit is None:
            unit = org.create_unit(
                project_id,
                org_level_id=levels[level_code].org_level_id,
                unit_code=code,
                unit_name=name,
                parent_org_unit_id=units[parent_code].org_unit_id if parent_code else None,
            )
        elif not unit.is_active:
            org.set_unit_active(project_id, unit.org_unit_id, True)
        units[code] = unit

    cadres = {c.cadre_code: c for c in org.list_cadres(project_id, include_inactive=True)}
    for code in {cadre_code for *_rest, cadre_code, _roles in roster if cadre_code}:
        if not cadres[code].is_active:
            org.update_cadre(project_id, cadres[code].cadre_id, is_active=True)
    summary["tree"] = (
        f"{len(levels)} levels, {len(units)} units, "
        f"{len(org.list_level_cadres(project_id))} grid rows"
    )

    # Central-office area presets (Id10002/Id10003) on the root unit, which
    # every descendant inherits. Only an unset field is filled, so a value
    # an admin set by hand survives a rerun.
    own = org.get_unit_va_presets(project_id, units[_TST_PRESET_UNIT].org_unit_id)
    hiv = own.hiv_mortality if own else None
    malaria = own.malaria_mortality if own else None
    if hiv is None or malaria is None:
        org.set_unit_va_presets(
            project_id,
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
                MasOrgUnitWorker.project_id == project_id,
                MasOrgUnitWorker.worker_code == worker_code,
            )
        )
        if worker is None:
            org.create_worker(
                project_id,
                org_unit_id=units[unit_code].org_unit_id,
                cadre_id=cadres[cadre_code].cadre_id,
                worker_name=users[_tst_email(local)].name,
                worker_code=worker_code,
                user=_tst_email(local),
            )
            created_workers += 1
        elif not worker.is_active:
            org.update_worker(project_id, worker.worker_id, is_active=True)
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
    # A mentoring institute member (set up by hand) may hold only grants inside
    # the districts the institute covers; leave out what the import would refuse.
    refused = set()
    for email, role, unit_code, _cadre_code in grant_specs:
        user = users.get(email)
        if user is None:
            continue
        try:
            mentor_institute_service.check_mentor_grant(
                user.user_id, VaAccessRoles(role), units[unit_code] if unit_code else None
            )
        except org.OrganizationError:
            refused.add(email)
    grant_specs = [spec for spec in grant_specs if spec[0] not in refused]
    if refused:
        summary["mentors"] = "institute staff, no grants here: " + ", ".join(sorted(refused))
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
    plan = user_import.prepare(project_id, rows, actor=actor)
    _new_users, audit, _codes = user_import.apply(project_id, plan, actor_user_id=actor.user_id)
    written, total = len(audit), len(plan)
    # Sites projects: the import is organization-only, so write the one
    # project-scope grant the way the admin panel does (admin.py grants).
    for local, classical_id, role in () if staging or not spec["classical_grants"] else _TST_CLASSICAL_GRANTS:
        user = users[_tst_email(local)]
        if db.session.get(VaProjectMaster, classical_id) is None or user.user_status != VaStatuses.active:
            continue
        total += 1
        grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.role == VaAccessRoles(role),
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id == classical_id,
        ))
        if grant is None:
            grant = VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles(role),
                scope_type=VaAccessScopeTypes.project, project_id=classical_id,
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
                           project_id=classical_id), action))
        written += 1
    summary["grants"] = f"{written} written, {total - written} already in place"
    from app.services import consent_service

    summary["consent"] = consent_service.apply_default_consent(actor, project_id)
    summary["audit"] = audit
    summary["actor_user_id"] = actor.user_id
    return summary


def _log_test_project_grants(audit, actor_user_id, project_id=TEST_PROJECT_ID) -> None:
    """grants.log lines for what the import wrote, as the import route writes them."""
    from app.logging.va_logger import log_grant_action

    for grant, action in audit:
        log_grant_action(
            action=action, actor_user_id=actor_user_id, actor_role="admin",
            target_user_id=grant["user_id"], grant_id=grant["grant_id"], role=grant["role"],
            scope_type=grant["scope_type"], project_id=grant.get("project_id", project_id),
            org_unit_id=grant["org_unit_id"], cadre_id=grant["cadre_id"],
        )


#: (role key, landing_page, unit_code, cadre_code, roles) for one e2e run on
#: TST001. "all" mirrors test.all; the unit rows need a cadre the grid permits.
_E2E_ROSTER = (
    ("all", "coder", None, None, ("coder", "reviewer", "data_manager")),
    ("all", "coder", "SC01", "ANM", ("death_reporter", "interviewer")),
    ("all", "coder", "PHC01", "MO", ("interview_supervisor",)),
    ("interviewer", "intake", "SC01", "CHO", ("interviewer",)),
    ("coder", "coder", None, None, ("coder",)),
    # Single-role users, and a second interviewer and coder for concurrency flows.
    ("interviewer2", "intake", "SC01", "CHO", ("interviewer",)),
    ("coder2", "coder", None, None, ("coder",)),
    ("reporter", "intake", "SC01", "ANM", ("death_reporter",)),
    ("supervisor", "intake", "PHC01", "MO", ("interview_supervisor",)),
    ("reviewer", "coder", None, None, ("reviewer",)),
    ("datamgr", "data_manager", None, None, ("data_manager",)),
)
#: The same shape for TST002 (single-step coding): the coders, and one
#: interviewer so the suite can create TST002 cases.
_E2E_ROSTER_T2 = (
    ("all", "coder", None, None, ("coder",)),
    ("coder", "coder", None, None, ("coder",)),
    ("coder2", "coder", None, None, ("coder",)),
    ("interviewer_t2", "intake", "SC01", "CHO", ("interviewer",)),
)
_E2E_PROJECTS = ((TEST_PROJECT_ID, _E2E_ROSTER), (TEST_PROJECT_2_ID, _E2E_ROSTER_T2))
_E2E_DOMAIN = "digitva.test"


def _e2e_email(run_id: str, key: str) -> str:
    return f"e2e.{run_id}.{key}@{_E2E_DOMAIN}"


def _e2e_default_out() -> str:
    from flask import current_app

    return os.path.join(os.path.dirname(current_app.root_path), "private", "e2e-users.json")


def _require_dev_app(command: str) -> None:
    """Refuse anything but a debug or testing app (no staging opt-in)."""
    from flask import current_app

    if not (current_app.debug or current_app.testing):
        raise click.ClickException(
            f"e2e-users {command} manages throwaway test accounts; it runs only on a debug or testing app."
        )


@seed_group.group("e2e-users")
def e2e_users_group():
    """Throwaway TST001 and TST002 accounts for one Maestro run (dev/test only)."""


@e2e_users_group.command("create")
@click.option("--out", "out_path", default=None, help="Credentials file (default private/e2e-users.json).")
def e2e_users_create(out_path):
    """Create a fresh e2e user set on TST001 and TST002 and write its credentials to a local file.

    Each run gets new emails (e2e.<run>.<role>@digitva.test) and one random
    password, so phones never hit the per-user device cap. Grants go through
    the project user import and grants.log like `seed test-project`. Only
    emails and the file path are printed; the password lives only in the file.
    """
    import json
    from datetime import UTC, datetime

    from app.models import MasCadre, VaProjectMaster, VaUsers
    from app.services import organization_service as org
    from app.services import project_user_import_service as user_import

    _require_dev_app("create")
    for project_id, _roster in _E2E_PROJECTS:
        if db.session.get(VaProjectMaster, project_id) is None:
            raise click.ClickException(f"{project_id} missing; run `flask seed test-project` first.")
    _seed_admin()
    actor = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "testadmin@digitva.com"))
    run_id = datetime.now(UTC).strftime("%y%m%d%H%M") + secrets.token_hex(2)
    password = secrets.token_urlsafe(18)
    emails = {}
    try:
        for key, landing, *_ in (*_E2E_ROSTER, *_E2E_ROSTER_T2):
            if key in emails:
                continue
            user = VaUsers(
                user_id=uuid.uuid4(),
                name=f"E2E {run_id} {key}",
                email=_e2e_email(run_id, key),
                vacode_language=["english"],
                vacode_formcount=0,
                permission={},
                landing_page=landing,
                timezone="Asia/Kolkata",
                pw_reset_t_and_c=True,
                email_verified=True,
                other=creation_other("seed"),
            )
            user.set_password(password)
            db.session.add(user)
            emails[key] = user.email
        db.session.flush()
        audit = []
        for project_id, roster in _E2E_PROJECTS:
            # Workers: the person-holds-cadre-at-unit record the unit grants pair with.
            for key, _landing, unit_code, cadre_code, _roles in roster:
                if unit_code is None:
                    continue
                unit = org.find_unit_by_code(project_id, unit_code)
                cadre = db.session.scalar(sa.select(MasCadre).where(
                    MasCadre.project_id == project_id, MasCadre.cadre_code == cadre_code,
                ))
                if unit is None or cadre is None:
                    raise click.ClickException(f"{project_id} lacks {unit_code}/{cadre_code}; rerun `flask seed test-project`.")
                org.create_worker(
                    project_id, org_unit_id=unit.org_unit_id, cadre_id=cadre.cadre_id,
                    worker_name=f"E2E {run_id} {key}",
                    worker_code=f"E2E_{run_id}_{key[:3]}{key[-3:]}_{unit_code}".upper(), user=emails[key],
                )
            rows = [
                {"_line_number": n, "email": emails[key], "name": "", "role": role,
                 "org_unit_code": unit_code or "", "cadre_code": cadre_code or "",
                 "language_codes": "", "phone": ""}
                for n, (key, role, unit_code, cadre_code) in enumerate(
                    ((k, r, u, c) for k, _l, u, c, roles in roster for r in roles), start=1
                )
            ]
            plan = user_import.prepare(project_id, rows, actor=actor)
            _new, project_audit, _codes = user_import.apply(project_id, plan, actor_user_id=actor.user_id)
            audit.append((project_id, project_audit))
    except (org.OrganizationError, user_import.ProjectUserImportError, ValueError) as exc:
        db.session.rollback()
        raise click.ClickException(f"e2e users: {exc}")
    db.session.commit()
    for project_id, project_audit in audit:
        _log_test_project_grants(project_audit, actor.user_id, project_id)

    out_path = out_path or _e2e_default_out()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump({"run_id": run_id, "project_id": TEST_PROJECT_ID, "project_ids": [p for p, _r in _E2E_PROJECTS], "password": password,
                   "users": emails}, fh, indent=2)
    click.echo(f"  run        {run_id}")
    for key, email in emails.items():
        click.echo(f"  {key:10s} {email}")
    click.echo(f"  grants     {sum(len(a) for _p, a in audit)} written")
    click.echo(f"  file       {out_path}")


@e2e_users_group.command("teardown")
@click.option("--run", "run_id", default=None, help="Only this run id (default: every e2e run).")
@click.option("--older-than-hours", type=click.FloatRange(min=0), default=None,
              help="Only accounts created more than N hours ago.")
def e2e_users_teardown(run_id, older_than_hours):
    """Revoke the devices, end the sessions and deactivate e2e accounts.

    Devices are revoked through device_auth_service.revoke_device and the
    TST001 and TST002 grants (both projects) through the users-grid revoke_all path (grants.log), both with the
    seeded admin as actor. Rows are kept, so work the accounts made
    stays. Idempotent: a rerun finds nothing active and changes nothing.
    """
    from datetime import UTC, datetime, timedelta

    from app.models import AuthDevice, AuthDeviceSession, VaStatuses, VaUsers
    from app.services import device_auth_service
    from app.services import organization_service as org
    from app.services import project_user_import_service as user_import

    _require_dev_app("teardown")
    if run_id is not None and not run_id.isalnum():
        raise click.ClickException("--run must be the alphanumeric run id `create` printed.")
    _seed_admin()
    actor = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == "testadmin@digitva.com"))
    pattern = f"e2e.{run_id or '%'}.%@{_E2E_DOMAIN}"
    query = sa.select(VaUsers).where(VaUsers.email.like(pattern))
    if older_than_hours is not None:
        query = query.where(VaUsers.user_created_at < datetime.now(UTC) - timedelta(hours=older_than_hours))
    users = db.session.scalars(query).all()
    user_ids = [u.user_id for u in users]
    devices = db.session.scalars(
        sa.select(AuthDevice).where(
            AuthDevice.revoked_at.is_(None),
            AuthDevice.device_id.in_(
                sa.select(AuthDeviceSession.device_id).where(AuthDeviceSession.user_id.in_(user_ids))
            ),
        )
    ).all() if user_ids else []
    ended = sum(device_auth_service.revoke_device(d, actor=actor, reason="e2e_teardown") for d in devices)
    # Grants: the users-grid "revoke_all" path the admin panel uses, audited
    # after commit by finalize_apply. Its batch cap is 500 users.
    changed_by_project = {}
    for project_id, _roster in _E2E_PROJECTS:
        changed_by_project[project_id] = []
        for start in range(0, len(user_ids), 500):
            try:
                _summary, changed = org.bulk_apply_project_users_grid(
                    project_id,
                    {"user_ids": [str(uid) for uid in user_ids[start:start + 500]], "operation": "revoke_all"},
                    actor=actor,
                )
            except org.OrganizationError as exc:
                db.session.rollback()
                raise click.ClickException(f"{project_id}: {exc}")
            changed_by_project[project_id] += changed
    changed_grants = [g for grants in changed_by_project.values() for g in grants]
    # Cases the accounts registered or started, still open: cancelled through the case
    # transition path (audited, rows kept), so the To do lists do not fill with test cases.
    # Refused cases have no cancel transition and are left as they are.
    from app.models import VaDeathRegister
    from app.services import case_transition_service as case_svc
    WebIntakeError = case_svc.WebIntakeError

    open_cases = db.session.scalars(sa.select(VaDeathRegister).where(
        VaDeathRegister.status.in_(("draft_identity", "registered", "scheduled", "in_progress", "paused")),
        sa.or_(VaDeathRegister.registered_by.in_(user_ids), VaDeathRegister.started_by_user_id.in_(user_ids)),
    )).all() if user_ids else []
    cancelled = 0
    for case in open_cases:
        try:
            case_svc.transition(case, "cancelled", actor=actor, action="e2e_teardown", reason="e2e teardown")
            cancelled += 1
        except WebIntakeError:
            pass
    deactivated = 0
    for user in users:
        if user.user_status != VaStatuses.deactive:
            user.user_status = VaStatuses.deactive
            user.bump_session_version()  # ends web sessions and remember cookies
            deactivated += 1
    db.session.commit()
    for project_id, grants in changed_by_project.items():
        if grants:
            user_import.finalize_apply(
                project_id, actor_user_id=actor.user_id, actor_role="admin",
                changed_grants=grants, invitations=[],
            )
    click.echo(f"  matched    {len(users)} e2e account(s)")
    click.echo(f"  devices    {len(devices)} revoked, {ended} session(s) ended")
    click.echo(f"  grants     {len(changed_grants)} revoked")
    click.echo(f"  users      {deactivated} deactivated")
    click.echo(f"  cases      {cancelled} of {len(open_cases)} open case(s) cancelled")


def init_app(app):
    app.cli.add_command(seed_group)
