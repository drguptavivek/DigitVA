"""A death-register case for a VA interviewed in ODK only (digitva-l8y3).

Policy: docs/policy/web-intake.md, "Cases for ODK-only interviews". The ODK
sync calls ``ensure_case_for_odk_submission`` for each submission it routes in
a tree project, so "deaths reported" counts every death the system knows, not
only web-intake ones. ``backfill_odk_cases`` (``flask web-intake
backfill-odk-cases``) does the same for submissions that arrived earlier.
"""

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    MapCaseTransition,
    MasOrgUnit,
    VaDeathRegister,
    VaForms,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaWebIntakeDraft,
)
from app.services.org_grant_service import projects_with_org_tree
from app.services.payload_pii_accessor import get_pii_many, split_enabled
from app.services.payload_pii_split import join_payload
from app.services.web_intake_service import (
    _allocate_unique_id,
    _birth_age_from_answers,
    _identity_from_answers,
)

log = logging.getLogger(__name__)

#: The "ODK sync" service account that owns these cases. Migration
#: ``k8p4r2w6y3f1`` inserts it with this id; it cannot sign in.
ODK_SYNC_USER_ID = uuid.UUID("a906d0c7-cff9-43bf-ab59-cabaf703535a")

CASE_STATE = "submitted"
ODK_SID_INDEX = "uq_va_death_register_odk_va_sid"
#: Rows per backfill transaction: short commits, bounded memory.
BACKFILL_CHUNK = 200
_IDENTITY_KEYS = ("deceased_name", "deceased_sex", "date_of_death")


def _identity_or_none(payload: dict) -> dict | None:
    """The case's identity from the ODK answers, or None unless all three are given."""
    identity = _identity_from_answers(payload)
    return identity if all(identity.get(key) for key in _IDENTITY_KEYS) else None


def _is_lost_race(exc: Exception) -> bool:
    """True when *exc* is the va_sid unique index: another run made the case first."""
    return isinstance(exc, IntegrityError) and ODK_SID_INDEX in str(exc.orig)


def _log_case_failure(va_sid, exc: Exception) -> None:
    """Log a case that was not created. Only va_sid and the error class: the text can carry values."""
    if _is_lost_race(exc):
        log.info("ODK case not created, one exists for this submission | va_sid=%s", va_sid)
        return
    log.warning(
        "ODK case failed, submission still synced | va_sid=%s | error=%s",
        va_sid, type(exc).__name__,
    )


def _has_case_or_draft(va_sid) -> bool:
    """True when the submission already has a death-register case or an intake draft."""
    # One round trip for both checks; this runs for every routed submission.
    has_case, has_draft = db.session.execute(sa.select(
        sa.exists().where(VaDeathRegister.va_sid == va_sid),
        sa.exists().where(VaWebIntakeDraft.va_sid == va_sid),
    )).one()
    return has_case or has_draft


def _insert_case(*, va_sid, org_unit_id, project_id, site_id, payload, identity) -> VaDeathRegister:
    """Insert the case and its 'created' audit row; raises on any failure.

    The caller owns the savepoint, so a raise rolls back only this case.
    """
    unit = db.session.get(MasOrgUnit, org_unit_id) if org_unit_id else None
    number, unique_id = _allocate_unique_id(unit.unit_code if unit else site_id)
    case = VaDeathRegister(
        project_id=project_id,
        site_id=site_id,
        org_unit_id=org_unit_id,
        death_number=number,
        unique_id=unique_id,
        va_sid=va_sid,
        registered_by=ODK_SYNC_USER_ID,
        source="odk",
        status=CASE_STATE,
        **identity,
        **_birth_age_from_answers(payload, identity["date_of_death"]),
    )
    db.session.add(case)
    db.session.flush()
    db.session.add(MapCaseTransition(
        death_id=case.death_id,
        action="created",
        from_state=None,
        to_state=CASE_STATE,
        actor_user_id=ODK_SYNC_USER_ID,
    ))
    log.info("ODK case created | project=%s | unique_id=%s", project_id, unique_id)
    return case


def ensure_case_for_odk_submission(submission, va_form, payload: dict) -> VaDeathRegister | None:
    """Create the ODK-only case for *submission* unless it has one; return it or None.

    *payload* is the ODK answers the sync just stored; the caller has routed
    *submission*, so its unit is final. Returns None (no case) for a non-ODK
    form, a submission that already has a case or an intake draft, answers
    without name, sex and date of death, or any failure. A failure rolls back
    only this savepoint and is logged by va_sid, so the form's sync still commits.
    """
    if va_form.form_source != "odk":
        return None
    va_sid = submission.va_sid
    try:
        with db.session.begin_nested():
            if _has_case_or_draft(va_sid):
                return None
            identity = _identity_or_none(payload)
            if identity is None:
                log.info("ODK case skipped, identity incomplete | va_sid=%s", va_sid)
                return None
            return _insert_case(
                va_sid=va_sid,
                org_unit_id=submission.org_unit_id,
                project_id=va_form.project_id,
                site_id=va_form.site_id,
                payload=payload,
                identity=identity,
            )
    except Exception as exc:
        _log_case_failure(va_sid, exc)
        return None


def sync_case_unit(submission) -> None:
    """Point the submission's ODK case at the submission's unit after a routing write.

    Only 'odk' cases follow: an app case keeps the unit its registrar chose. A
    submission with no ODK case updates zero rows. Callers commit.
    """
    db.session.execute(
        sa.update(VaDeathRegister)
        .where(VaDeathRegister.va_sid == submission.va_sid, VaDeathRegister.source == "odk")
        .values(org_unit_id=submission.org_unit_id)
    )


def backfill_odk_cases(*, project_id: str | None = None, dry_run: bool = False) -> dict:
    """Give each ODK submission of a tree project without a case one; return counts.

    Keyset-paged by va_sid in chunks of BACKFILL_CHUNK, each committed alone.
    A dry run writes nothing and reports what a real run would create. Units
    are not re-routed: the stored ``org_unit_id`` is used.
    """
    counts = {"created": 0, "linked": 0, "identity_missing": 0, "failed": 0}
    tree = projects_with_org_tree({project_id} if project_id else None)
    if not tree:
        return counts
    linked = sa.or_(
        sa.exists().where(VaDeathRegister.va_sid == VaSubmissions.va_sid),
        sa.exists().where(VaWebIntakeDraft.va_sid == VaSubmissions.va_sid),
    ).label("linked")
    query = (
        sa.select(
            VaSubmissions.va_sid,
            VaSubmissions.org_unit_id,
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.active_payload_version_id,
            VaSubmissionPayloadVersion.payload_data,
            linked,
        )
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(
            VaSubmissionPayloadVersion,
            VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
        )
        .where(VaForms.form_source == "odk", VaForms.project_id.in_(sorted(tree)))
        .order_by(VaSubmissions.va_sid)
    )
    after = ""
    while True:
        rows = db.session.execute(
            query.where(VaSubmissions.va_sid > after).limit(BACKFILL_CHUNK)
        ).all()
        if not rows:
            break
        # The name (Id10017/Id10018) is sealed with the flag on: open the
        # chunk's side rows in one query, for the unlinked rows only.
        sealed = (
            get_pii_many(row.active_payload_version_id for row in rows if not row.linked)
            if split_enabled()
            else {}
        )
        for row in rows:
            if row.linked:
                counts["linked"] += 1
                continue
            payload = join_payload(row.payload_data, sealed.get(row.active_payload_version_id))
            identity = _identity_or_none(payload)
            if identity is None:
                counts["identity_missing"] += 1
                continue
            if dry_run:
                counts["created"] += 1
                continue
            try:
                with db.session.begin_nested():
                    _insert_case(
                        va_sid=row.va_sid,
                        org_unit_id=row.org_unit_id,
                        project_id=row.project_id,
                        site_id=row.site_id,
                        payload=payload,
                        identity=identity,
                    )
            except Exception as exc:
                _log_case_failure(row.va_sid, exc)
                if not _is_lost_race(exc):
                    counts["failed"] += 1
                continue
            counts["created"] += 1
        if not dry_run:
            db.session.commit()
        after = rows[-1].va_sid
    return counts
