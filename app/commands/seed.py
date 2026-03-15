"""
Idempotent seed command — safe to run on fresh DB or after test-data restore.

Usage:
  flask seed              # seed bootstrap data (runs on every boot)
  flask seed --test       # also create test users (dev/staging only)
"""
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


def init_app(app):
    app.cli.add_command(seed_group)
