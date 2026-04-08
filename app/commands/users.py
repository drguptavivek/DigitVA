"""
CLI commands for operational user management.

Usage:
  flask users list
  flask users search --query="admin"
  flask users list-grants --email=user@example.com
  flask users create --email=user@example.com --name="Example User" --password="Secret123"
  flask users reset-password --email=user@example.com --password="NewSecret123"
  flask users grant-admin --email=user@example.com
  flask users revoke-admin --email=user@example.com
  flask users set-status --email=user@example.com --status=deactive
"""
import click
import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.utils.password_policy import password_error_message


@click.group("users")
def users_group():
    """User management commands."""
    pass


def _get_user_by_email(email: str) -> VaUsers | None:
    normalized_email = email.strip().lower()
    return db.session.scalar(
        sa.select(VaUsers).where(VaUsers.email == normalized_email)
    )


@users_group.command("search")
@click.option("--query", required=True, help="Case-insensitive name or email fragment.")
def search_users(query):
    """Search users by email or display name."""
    term = f"%{query.strip()}%"
    rows = db.session.execute(
        sa.select(
            VaUsers.email,
            VaUsers.name,
            VaUsers.user_status,
            VaUsers.landing_page,
        )
        .where(
            sa.or_(
                VaUsers.email.ilike(term),
                VaUsers.name.ilike(term),
            )
        )
        .order_by(VaUsers.email)
    ).all()

    if not rows:
        click.echo(f"No users matched: {query.strip()}")
        return

    click.echo("email | name | status | landing_page")
    click.echo("-" * 72)
    for row in rows:
        click.echo(
            f"{row.email} | {row.name} | "
            f"{row.user_status.value} | {row.landing_page}"
        )


@users_group.command("list")
def list_users():
    """List users with current status and admin access state."""
    rows = db.session.execute(
        sa.select(
            VaUsers.email,
            VaUsers.name,
            VaUsers.user_status,
            VaUsers.landing_page,
            VaUsers.pw_reset_t_and_c,
            sa.exists().where(
                VaUserAccessGrants.user_id == VaUsers.user_id,
                VaUserAccessGrants.role == VaAccessRoles.admin,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
                VaUserAccessGrants.grant_status == VaStatuses.active,
            ).label("is_admin"),
        )
        .order_by(VaUsers.email)
    ).all()

    if not rows:
        click.echo("No users found.")
        return

    click.echo("email | name | status | landing_page | onboarded | admin")
    click.echo("-" * 72)
    for row in rows:
        click.echo(
            f"{row.email} | {row.name} | {row.user_status.value} | "
            f"{row.landing_page} | {str(row.pw_reset_t_and_c).lower()} | "
            f"{'yes' if row.is_admin else 'no'}"
        )


@users_group.command("list-grants")
@click.option("--email", help="Optional user email to restrict output.")
def list_grants(email):
    """List access grants, optionally filtered to a single user."""
    project_sites = sa.orm.aliased(VaProjectSites)
    stmt = (
        sa.select(
            VaUsers.email,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_id,
            project_sites.project_id.label("scope_project_id"),
            project_sites.site_id.label("scope_site_id"),
            VaUserAccessGrants.grant_status,
        )
        .join(VaUserAccessGrants, VaUserAccessGrants.user_id == VaUsers.user_id)
        .outerjoin(
            project_sites,
            project_sites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .order_by(
            VaUsers.email,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_id,
            project_sites.project_id,
            project_sites.site_id,
        )
    )
    if email:
        stmt = stmt.where(VaUsers.email == email.strip().lower())

    rows = db.session.execute(stmt).all()
    if not rows:
        if email:
            click.echo(f"No grants found for: {email.strip().lower()}")
        else:
            click.echo("No grants found.")
        return

    click.echo("email | role | scope | project_id | site_id | status")
    click.echo("-" * 88)
    for row in rows:
        scope_project_id = row.project_id or row.scope_project_id or ""
        scope_site_id = row.scope_site_id or ""
        click.echo(
            f"{row.email} | {row.role.value} | {row.scope_type.value} | "
            f"{scope_project_id} | {scope_site_id} | "
            f"{row.grant_status.value}"
        )


@users_group.command("create")
@click.option("--email", required=True, help="User email address.")
@click.option("--name", required=True, help="Display name.")
@click.option("--password", required=True, help="Initial password.")
@click.option(
    "--landing-page",
    default="coder",
    show_default=True,
    help="Initial landing page.",
)
@click.option(
    "--timezone",
    default="Asia/Kolkata",
    show_default=True,
    help="User timezone.",
)
@click.option(
    "--language",
    "languages",
    multiple=True,
    help="Repeat to add one or more vacode languages.",
)
@click.option(
    "--email-verified/--email-unverified",
    default=False,
    show_default=True,
    help="Set whether the email is already verified.",
)
def create_user(
    email,
    name,
    password,
    landing_page,
    timezone,
    languages,
    email_verified,
):
    """Create a user without assigning grants.

    CLI-created users are always forced through first-login password reset.
    """
    normalized_email = email.strip().lower()
    if _get_user_by_email(normalized_email):
        click.echo(f"User already exists: {normalized_email}")
        raise SystemExit(1)
    pw_err = password_error_message(password)
    if pw_err:
        click.echo(pw_err)
        raise SystemExit(1)

    user = VaUsers(
        email=normalized_email,
        name=name.strip(),
        vacode_language=list(languages) or ["English"],
        vacode_formcount=0,
        permission={},
        landing_page=landing_page.strip(),
        pw_reset_t_and_c=False,
        email_verified=email_verified,
        timezone=timezone.strip(),
        user_status=VaStatuses.active,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    click.echo(f"Created user: {user.email}")
    click.echo(f"  user_id: {user.user_id}")
    click.echo(f"  landing_page: {user.landing_page}")
    click.echo("  password_reset_required: true")


@users_group.command("reset-password")
@click.option("--email", required=True, help="User email address.")
@click.option("--password", required=True, help="New password.")
@click.option(
    "--onboarded/--require-password-change",
    default=None,
    help="Optionally update the post-reset onboarding flag.",
)
def reset_password(email, password, onboarded):
    """Reset a user's password."""
    user = _get_user_by_email(email)
    if user is None:
        click.echo(f"User not found: {email.strip().lower()}")
        raise SystemExit(1)
    pw_err = password_error_message(password)
    if pw_err:
        click.echo(pw_err)
        raise SystemExit(1)

    user.set_password(password)
    if onboarded is not None:
        user.pw_reset_t_and_c = onboarded
    db.session.commit()

    click.echo(f"Password reset for: {user.email}")
    click.echo(f"  onboarded: {str(user.pw_reset_t_and_c).lower()}")


@users_group.command("grant-admin")
@click.option("--email", required=True, help="User email address.")
def grant_admin(email):
    """Grant or reactivate the global admin grant for a user."""
    user = _get_user_by_email(email)
    if user is None:
        click.echo(f"User not found: {email.strip().lower()}")
        raise SystemExit(1)

    grant = db.session.scalar(
        sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.role == VaAccessRoles.admin,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
        )
    )
    if grant is None:
        grant = VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope,
            grant_status=VaStatuses.active,
            notes="created via users CLI",
        )
        db.session.add(grant)
    else:
        grant.grant_status = VaStatuses.active

    user.landing_page = "admin"
    db.session.commit()

    click.echo(f"Admin grant active for: {user.email}")


@users_group.command("revoke-admin")
@click.option("--email", required=True, help="User email address.")
def revoke_admin(email):
    """Deactivate the global admin grant for a user."""
    user = _get_user_by_email(email)
    if user is None:
        click.echo(f"User not found: {email.strip().lower()}")
        raise SystemExit(1)

    grant = db.session.scalar(
        sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.role == VaAccessRoles.admin,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
        )
    )
    if grant is None:
        click.echo(f"Admin grant not found: {user.email}")
        raise SystemExit(1)

    grant.grant_status = VaStatuses.deactive
    db.session.commit()

    click.echo(f"Admin grant revoked for: {user.email}")


@users_group.command("set-status")
@click.option("--email", required=True, help="User email address.")
@click.option(
    "--status",
    type=click.Choice([status.value for status in VaStatuses], case_sensitive=True),
    required=True,
    help="Target user status.",
)
def set_status(email, status):
    """Update a user's active/deactive status."""
    user = _get_user_by_email(email)
    if user is None:
        click.echo(f"User not found: {email.strip().lower()}")
        raise SystemExit(1)

    user.user_status = VaStatuses(status)
    db.session.commit()
    click.echo(f"Updated user status: {user.email} -> {user.user_status.value}")


def init_app(app):
    """Register user CLI commands with the Flask app."""
    app.cli.add_command(users_group)
