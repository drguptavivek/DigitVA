"""Load-test setup for DigitVA: users, grants and bearer tokens, minted server-side.

Run INSIDE the app container (nothing is signed in over HTTP, so the
10/min/IP sign-in limits never apply):

  docker exec -i <container> uv run --no-sync python - < lt_setup.py
  docker compose exec -T minerva_app_service uv run --no-sync python - < lt_setup.py

Env: LT_PROJECT (TRN01), LT_INTERVIEWERS (100), LT_CODERS (100),
LT_PASSWORD (random when unset: the tokens drive the load), LT_OUT (/tmp/lt_tokens.json), LT_CLEANUP=1,
LT_CODER_LANGS ("english,hindi": the narration languages coders are offered).

Setup is idempotent: an existing lt+ user is reused (and reactivated), its
grant is made active, and its previous lt devices are revoked before a fresh
device and session are minted, so rerunning never piles up live devices.
Cleanup revokes the lt devices, releases held coding allocations and
DEACTIVATES the lt users and their grants. Nothing is ever deleted.
Prints counts only; the token file is the one place secrets are written.
"""
import json
import os
import secrets
import uuid
from datetime import timedelta

import sqlalchemy as sa
from werkzeug.security import generate_password_hash

from app import create_app, db
from app.models import (
    AuthDevice,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import device_auth_service as devices
from app.services.coder_workflow_service import AllocationError, release_own_coding_allocation
from app.services.org_grant_service import projects_with_org_tree
from app.services.user_account_service import creation_other
from app.services.web_intake_service import interviewer_context

PROJECT = os.environ.get("LT_PROJECT", "TRN01").strip().upper()
N_INT = int(os.environ.get("LT_INTERVIEWERS", "100"))
N_COD = int(os.environ.get("LT_CODERS", "100"))
PASSWORD = os.environ.get("LT_PASSWORD") or secrets.token_urlsafe(24)
OUT = os.environ.get("LT_OUT", "/tmp/lt_tokens.json")
CLEANUP = os.environ.get("LT_CLEANUP") == "1"
# Coders are only offered cases in their languages; TRN01's pool is mostly Hindi.
CODER_LANGS = [x.strip().lower() for x in os.environ.get("LT_CODER_LANGS", "english,hindi").split(",") if x.strip()]
DEVICE_PREFIX = "lt-"
EMAIL_LIKE = "lt+%@digitva.com"


def find_admin() -> VaUsers:
    """An active global admin: the recorded actor of codes and revokes."""
    candidates = db.session.scalars(
        sa.select(VaUsers)
        .join(VaUserAccessGrants, VaUserAccessGrants.user_id == VaUsers.user_id)
        .where(
            VaUserAccessGrants.role == VaAccessRoles.admin,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUsers.user_status == VaStatuses.active,
        )
        .order_by(VaUsers.user_created_at)
    ).all()
    for user in candidates:
        if user.is_admin():
            return user
    raise SystemExit("no active global admin found")


def lt_devices(live_only: bool = True) -> list[AuthDevice]:
    query = sa.select(AuthDevice).where(AuthDevice.name.like(DEVICE_PREFIX + "%"))
    if live_only:
        query = query.where(AuthDevice.revoked_at.is_(None))
    return list(db.session.scalars(query))


def cleanup() -> None:
    admin = find_admin()
    revoked = sessions = 0
    for device in lt_devices():
        sessions += devices.revoke_device(device, actor=admin)
        revoked += 1
    db.session.commit()

    users = list(db.session.scalars(sa.select(VaUsers).where(VaUsers.email.like(EMAIL_LIKE))))
    released = 0
    for user in users:
        try:
            release_own_coding_allocation(user)
            released += 1
        except AllocationError:
            db.session.rollback()  # none held
    ids = [u.user_id for u in users]
    grants = db.session.execute(
        sa.update(VaUserAccessGrants)
        .where(VaUserAccessGrants.user_id.in_(ids), VaUserAccessGrants.grant_status == VaStatuses.active)
        .values(grant_status=VaStatuses.deactive)
    ).rowcount if ids else 0
    deactivated = 0
    for user in users:
        if user.user_status == VaStatuses.active:
            user.user_status = VaStatuses.deactive
            deactivated += 1
    db.session.commit()
    print(f"cleanup: devices_revoked={revoked} sessions_ended={sessions} "
          f"allocations_released={released} grants_deactivated={grants} users_deactivated={deactivated}")


def ensure_user(email: str, name: str, landing: str, password_hash: str, languages: list[str]) -> VaUsers:
    user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
    if user is None:
        user = VaUsers(
            user_id=uuid.uuid4(), name=name, email=email, vacode_language=languages,
            vacode_formcount=0, permission={}, landing_page=landing,
            pw_reset_t_and_c=True, email_verified=True, other=creation_other("seed"),
        )
        user.password = password_hash
        db.session.add(user)
    else:
        user.user_status = VaStatuses.active
        user.vacode_language = languages
        user.pw_reset_t_and_c = True
        user.email_verified = True
    db.session.flush()
    return user


def ensure_grant(user: VaUsers, role: VaAccessRoles, admin: VaUsers) -> None:
    grant = db.session.scalar(sa.select(VaUserAccessGrants).where(
        VaUserAccessGrants.user_id == user.user_id, VaUserAccessGrants.role == role,
        VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
        VaUserAccessGrants.project_id == PROJECT,
    ))
    if grant is None:
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
            project_id=PROJECT, grant_status=VaStatuses.active, created_by_user_id=admin.user_id,
            notes="load test",
        ))
    else:
        grant.grant_status = VaStatuses.active
    db.session.flush()


def leaf_units() -> list[str]:
    """Active org units with no active child: where an interview is filed."""
    rows = db.session.execute(
        sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.path).where(
            MasOrgUnit.project_id == PROJECT, MasOrgUnit.is_active.is_(True))
    ).all()
    paths = {str(p) for _, p in rows}
    return sorted(
        str(uid) for uid, p in rows
        if not any(o.startswith(str(p) + ".") for o in paths)
    )


def main() -> None:
    project = db.session.get(VaProjectMaster, PROJECT)
    if project is None or project.project_status != VaStatuses.active:
        raise SystemExit(f"project {PROJECT} not found or not active")
    if CLEANUP:
        return cleanup()

    admin = find_admin()
    password_hash = generate_password_hash(PASSWORD)
    for device in lt_devices():  # fresh devices each run; stale ones must not stay live
        devices.revoke_device(device, actor=admin)

    people = [(f"lt+i{n}@digitva.com", f"LT Interviewer {n}", "intake", VaAccessRoles.interviewer, "interviewer")
              for n in range(1, N_INT + 1)]
    people += [(f"lt+c{n}@digitva.com", f"LT Coder {n}", "coder", VaAccessRoles.coding_tester, "coder")
               for n in range(1, N_COD + 1)]
    users = []
    for email, name, landing, role, kind in people:
        user = ensure_user(email, name, landing, password_hash, CODER_LANGS if kind == "coder" else ["english"])
        ensure_grant(user, role, admin)
        users.append((user, kind))
    db.session.commit()

    has_tree = bool(projects_with_org_tree({PROJECT}))
    units = leaf_units() if has_tree else []
    if has_tree and not units:
        raise SystemExit("project has an organization tree but no active unit")

    code = None
    left = 0
    out = []
    n_int = 0
    for user, kind in users:
        site_id = unit_id = None
        if kind == "interviewer":
            entries = [c for c in interviewer_context(user) if c["project_id"] == PROJECT]
            if not entries:
                raise SystemExit(f"{user.email}: no interviewer context in {PROJECT} (web intake off? no active form?)")
            site_id = entries[0]["site_id"]
            if has_tree:
                unit_id = units[n_int % len(units)]
            elif entries[0]["org_units"]:
                unit_id = entries[0]["org_units"][0]["org_unit_id"]
            n_int += 1
        if left == 0:
            row, code = devices.create_enrolment_code(
                PROJECT, actor=admin, expires_in_minutes=180, max_uses=devices.ENROLMENT_MAX_USES)
            left = devices.ENROLMENT_MAX_USES
        device, device_secret = devices.enrol_device(
            code, device_name=f"{DEVICE_PREFIX}{user.email.split('@')[0][3:]}", platform="android", app_version="lt")
        left -= 1
        issued, _ = devices._open_authorized_session(device, user)
        # Stagger expiry over 6-15 min: tokens minted together would all hit the
        # 30/min/IP refresh limit at the same moment.
        issued.session.access_expires_at = devices._now() + timedelta(seconds=360 + (len(out) * 37) % 540)
        out.append({
            "email": user.email, "role": kind,
            "access_token": issued.access_token, "refresh_token": issued.refresh_token,
            "device_id": str(device.device_id), "device_secret": device_secret,
            "project_id": PROJECT, "site_id": site_id, "org_unit_id": unit_id,
        })
        if len(out) % 50 == 0:
            db.session.commit()
    db.session.commit()

    fd = os.open(OUT, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(out, fh)
    print(f"setup: project={PROJECT} interviewers={n_int} coders={len(out) - n_int} "
          f"org_tree={has_tree} leaf_units={len(units)} tokens_file={OUT}")


app = create_app()
with app.app_context():
    main()
