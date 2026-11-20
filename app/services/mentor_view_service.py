"""Mentor view: per-coder progress in one district, drill-down, feedback notes.

Policy: docs/policy/mentor-view.md (digitva-oux5). Who may look is decided
here, per request, from live rows:

- an active member of an active mentoring institute attached (active link)
  to the district;
- a ``data_manager`` grant at org_unit scope at or above the district, or a
  ``site_pi`` grant there that ``ResolvedGrants.oversees`` (the In-charge;
  a mentor member's site_pi is not);
- an admin, every district.

Project-scope grants never open it: district scope is not project scope.
A user with no such district is refused (403, which is where a coder-only
user lands); a district outside the caller's set is 404. Names and the
drill-down need ``should_redact_pii`` to pass for the district's project;
otherwise coders are "Coder N" with no ids. Every count and case row is
also ANDed with ``scope_filter(viewer, Action.VIEW)``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app import db
from app.logging.va_logger import log_mentor_institute_action
from app.models import (
    MapMentorInstituteOrgUnit,
    MapMentorInstituteUser,
    MasMentorInstitute,
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaCoderFeedbackNote,
    VaCoderReview,
    VaCodingEpisode,
    VaFinalAssessments,
    VaProjectMaster,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.va_coder_feedback_notes import NOTE_MAX_LENGTH
from app.services import authz, training_scope
from app.services.area_dashboard_service import PERIOD_DAYS, period_start
from app.services.authz.actions import Action
from app.services.authz.consulted import mark_consulted
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
from app.services.final_cod_authority_service import (
    EPISODE_STATUS_COMPLETED,
    EPISODE_TYPE_RECODE,
)
from app.services.mentor_institute_service import active_member_ids_select
from app.services.notification_service import MENTOR_FEEDBACK, notify
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.viewer_pii_service import should_redact_pii

MAX_CODERS = 500
CASE_PAGE_SIZE = 100
FEEDBACK_PAGE_SIZE = 50
READY_STATE = "ready_for_coding"
_BASIS_ORDER = ("mentor", "data_manager", "site_pi", "admin")


class MentorViewNotFound(Exception):
    """A district, coder, case or note outside the caller's reach (404)."""


class MentorViewForbidden(Exception):
    """The caller may not use this part of the Mentor view (403)."""


@dataclass(frozen=True)
class District:
    project_id: str
    project_name: str
    org_unit_id: uuid.UUID
    code: str
    name: str
    path: str
    bases: tuple[str, ...]           # why the caller sees it, in _BASIS_ORDER
    institute_ids: tuple[uuid.UUID, ...] = ()

    def holds(self, project_id: str, path: str | None) -> bool:
        return project_id == self.project_id and path is not None and (
            path == self.path or path.startswith(self.path + ".")
        )


# ---------------------------------------------------------------------------
# Districts
# ---------------------------------------------------------------------------

def _district_rows(project_ids=None, unit_ids=None):
    """Active district units of active non-training projects. A district is a
    unit at the project's ``district`` level, or at depth 1 when the project
    has none (``mentor_institute_service._district_unit``)."""
    district_level = sa.exists(sa.select(1).where(
        MasOrgLevel.project_id == MasOrgUnit.project_id,
        MasOrgLevel.level_code == "district",
        MasOrgLevel.is_active.is_(True),
    ))
    level = aliased(MasOrgLevel)
    stmt = (
        sa.select(
            MasOrgUnit.org_unit_id, MasOrgUnit.project_id, MasOrgUnit.unit_code,
            MasOrgUnit.unit_name, sa.cast(MasOrgUnit.path, sa.Text).label("path"),
            VaProjectMaster.project_name,
        )
        .join(level, level.org_level_id == MasOrgUnit.org_level_id)
        .join(VaProjectMaster, VaProjectMaster.project_id == MasOrgUnit.project_id)
        .where(
            MasOrgUnit.is_active.is_(True),
            level.is_active.is_(True),
            VaProjectMaster.project_status == VaStatuses.active,
            VaProjectMaster.project_id.is_distinct_from(training_scope.training_project_id()),
            sa.or_(
                level.level_code == "district",
                sa.and_(level.depth == 1, ~district_level),
            ),
        )
        .order_by(VaProjectMaster.project_id, MasOrgUnit.unit_name)
    )
    if project_ids is not None:
        stmt = stmt.where(MasOrgUnit.project_id.in_(sorted(project_ids)))
    if unit_ids is not None:
        stmt = stmt.where(MasOrgUnit.org_unit_id.in_(sorted(unit_ids)))
    return db.session.execute(stmt).all()


def _mentor_links(user_id) -> dict[uuid.UUID, list[uuid.UUID]]:
    """district id -> institute ids, for the user's active memberships."""
    rows = db.session.execute(
        sa.select(MapMentorInstituteOrgUnit.org_unit_id, MasMentorInstitute.institute_id)
        .join(MasMentorInstitute,
              MasMentorInstitute.institute_id == MapMentorInstituteOrgUnit.institute_id)
        .join(MapMentorInstituteUser,
              MapMentorInstituteUser.institute_id == MasMentorInstitute.institute_id)
        .where(
            MapMentorInstituteUser.user_id == user_id,
            MapMentorInstituteUser.is_active.is_(True),
            MasMentorInstitute.is_active.is_(True),
            MapMentorInstituteOrgUnit.is_active.is_(True),
        )
    ).all()
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for unit_id, institute_id in rows:
        links.setdefault(unit_id, []).append(institute_id)
    return links


def _overseeing_unit_grants(g) -> list:
    """org_unit data_manager grants and In-charge site_pi grants."""
    return [
        grant for grant in g.of(
            (VaAccessRoles.data_manager, VaAccessRoles.site_pi),
            scope_types=(VaAccessScopeTypes.org_unit,), virtual=False,
        )
        if grant.role == VaAccessRoles.data_manager or g.oversees(grant)
    ]


def viewer_districts(user) -> list[District]:
    """Every district *user* may open in the Mentor view (two or three queries)."""
    mark_consulted()  # the decision for every Mentor view request is made here
    if getattr(user, "is_public_demo", False):
        return []
    g = authz.resolve_grants(user)
    links = _mentor_links(user.user_id)
    unit_grants = _overseeing_unit_grants(g)
    if g.is_admin:
        rows = _district_rows()
    else:
        rows = []
        if links:
            rows += _district_rows(unit_ids=links)
        if unit_grants:
            seen = {row.org_unit_id for row in rows}
            rows += [
                row for row in _district_rows(project_ids={x.project_id for x in unit_grants})
                if row.org_unit_id not in seen
            ]
    districts = []
    for row in rows:
        bases = set()
        if row.org_unit_id in links:
            bases.add("mentor")
        for grant in unit_grants:
            if grant.covers_unit(row.project_id, row.path):
                bases.add(grant.role.value)
        if g.is_admin:
            bases.add("admin")
        if bases:
            districts.append(District(
                project_id=row.project_id, project_name=row.project_name,
                org_unit_id=row.org_unit_id, code=row.unit_code, name=row.unit_name,
                path=row.path, bases=tuple(b for b in _BASIS_ORDER if b in bases),
                institute_ids=tuple(links.get(row.org_unit_id, ())),
            ))
    return districts


def _parse_uuid(raw) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError):
        raise MentorViewNotFound() from None


def resolve_district(user, raw_district_id) -> District:
    """The caller's district *raw_district_id*. Raises MentorViewForbidden
    when the caller has no district at all, MentorViewNotFound otherwise."""
    districts = viewer_districts(user)
    if not districts:
        raise MentorViewForbidden(
            "The mentor view is for mentoring institutes, district data managers and In-charges."
        )
    district_id = _parse_uuid(raw_district_id)
    for district in districts:
        if district.org_unit_id == district_id:
            return district
    raise MentorViewNotFound()


def names_visible(user, district: District) -> bool:
    """The one name gate: coder names and case lists follow ``should_redact_pii``."""
    return not should_redact_pii(user, project_id=district.project_id)


# ---------------------------------------------------------------------------
# Scope building blocks
# ---------------------------------------------------------------------------

def _district_path(district: District):
    return (
        sa.select(MasOrgUnit.path)
        .where(MasOrgUnit.org_unit_id == district.org_unit_id)
        .scalar_subquery()
    )


def _case_scope(user, district: District):
    """Submissions in the district that the viewer may VIEW, live in ODK and
    not a confirmed duplicate."""
    subtree = sa.select(MasOrgUnit.org_unit_id).where(
        MasOrgUnit.project_id == district.project_id,
        MasOrgUnit.path.op("<@")(_district_path(district)),
    )
    return sa.and_(
        VaSubmissions.org_unit_id.in_(subtree),
        authz.scope_filter(user, Action.VIEW),
        submission_is_in_odk(VaSubmissions),
        not_confirmed_duplicate_condition(VaSubmissions.va_sid),
    )


def _district_coders(district: District, coder_id=None) -> list:
    """(user_id, name, last_signed_in_at) of active users with an active
    coder grant at a unit in or above the district, mentor members excepted.
    Sorted by name, capped at ``MAX_CODERS + 1`` to detect truncation."""
    unit = aliased(MasOrgUnit)
    path = _district_path(district)
    stmt = (
        sa.select(VaUsers.user_id, VaUsers.name, VaUsers.last_signed_in_at)
        .join(VaUserAccessGrants, VaUserAccessGrants.user_id == VaUsers.user_id)
        .join(unit, unit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .where(
            VaUserAccessGrants.role == VaAccessRoles.coder,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUsers.user_status == VaStatuses.active,
            unit.project_id == district.project_id,
            unit.is_active.is_(True),
            sa.or_(unit.path.op("<@")(path), unit.path.op("@>")(path)),
            VaUsers.user_id.not_in(active_member_ids_select()),
        )
        .distinct()
        .order_by(VaUsers.name, VaUsers.user_id)
        .limit(MAX_CODERS + 1)
    )
    if coder_id is not None:
        stmt = stmt.where(VaUsers.user_id == coder_id)
    return db.session.execute(stmt).all()


def _since(period: str, district: District):
    if period not in PERIOD_DAYS:
        raise ValueError(period)
    return period_start(period, district.project_id)


# ---------------------------------------------------------------------------
# Per-coder table
# ---------------------------------------------------------------------------

def _coded_counts(scope, coder_ids, since) -> dict:
    fa, rfa = VaFinalAssessments, VaReviewerFinalAssessments
    stmt = (
        sa.select(
            fa.va_finassess_by,
            # Distinct: "one active row per case" is unique only for rows with a payload version.
            sa.func.count(sa.distinct(fa.va_sid)),
            sa.func.count(sa.distinct(rfa.va_sid)).filter(rfa.va_conclusive_cod == fa.va_conclusive_cod),
            sa.func.count(sa.distinct(rfa.va_sid)).filter(rfa.va_conclusive_cod != fa.va_conclusive_cod),
        )
        .join(VaSubmissions, VaSubmissions.va_sid == fa.va_sid)
        .outerjoin(rfa, sa.and_(
            rfa.va_sid == fa.va_sid, rfa.va_rfinassess_status == VaStatuses.active,
        ))
        .where(
            fa.va_finassess_by.in_(coder_ids),
            fa.va_finassess_status == VaStatuses.active,
            fa.is_tester.is_(False),
            scope,
        )
        .group_by(fa.va_finassess_by)
    )
    if since is not None:
        stmt = stmt.where(fa.va_finassess_createdat >= since)
    return {row[0]: row[1:] for row in db.session.execute(stmt)}


def _not_codeable_counts(scope, coder_ids, since) -> dict:
    cr = VaCoderReview
    stmt = (
        sa.select(cr.va_creview_by, sa.func.count())
        .join(VaSubmissions, VaSubmissions.va_sid == cr.va_sid)
        .where(
            cr.va_creview_by.in_(coder_ids),
            cr.va_creview_status == VaStatuses.active,
            cr.is_tester.is_(False),
            scope,
        )
        .group_by(cr.va_creview_by)
    )
    if since is not None:
        stmt = stmt.where(cr.va_creview_createdat >= since)
    return dict(db.session.execute(stmt).all())


def _recode_counts(scope, coder_ids, since) -> dict:
    """Completed recodes only (owner decision 4)."""
    ep = VaCodingEpisode
    stmt = (
        sa.select(ep.started_by, sa.func.count())
        .join(VaSubmissions, VaSubmissions.va_sid == ep.va_sid)
        .where(
            ep.started_by.in_(coder_ids),
            ep.episode_type == EPISODE_TYPE_RECODE,
            ep.episode_status == EPISODE_STATUS_COMPLETED,
            scope,
        )
        .group_by(ep.started_by)
    )
    if since is not None:
        stmt = stmt.where(ep.completed_at >= since)
    return dict(db.session.execute(stmt).all())


def _ready_counts(user, district: District, coder_ids) -> dict:
    """Cases now ``ready_for_coding`` in the district under each coder's own
    coder grant units (current state, never period-filtered). The grant
    subtree only: coding-scope level, gates and language are not applied.
    Applies the confirmed-duplicate rule through ``_case_scope``, restated
    here for the reader guard: not_confirmed_duplicate_condition."""
    grant_unit = aliased(MasOrgUnit)
    case_unit = aliased(MasOrgUnit)
    stmt = (
        sa.select(VaUserAccessGrants.user_id, sa.func.count(sa.distinct(VaSubmissions.va_sid)))
        .select_from(VaUserAccessGrants)
        .join(grant_unit, grant_unit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .join(case_unit, sa.and_(
            case_unit.project_id == grant_unit.project_id,
            case_unit.path.op("<@")(grant_unit.path),
        ))
        .join(VaSubmissions, VaSubmissions.org_unit_id == case_unit.org_unit_id)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(
            VaUserAccessGrants.user_id.in_(coder_ids),
            VaUserAccessGrants.role == VaAccessRoles.coder,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaSubmissionWorkflow.workflow_state == READY_STATE,
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
            _case_scope(user, district),
        )
        .group_by(VaUserAccessGrants.user_id)
    )
    return dict(db.session.execute(stmt).all())


def district_summary(district: District) -> dict:
    return {
        "district_id": str(district.org_unit_id), "code": district.code, "name": district.name,
        "project_id": district.project_id, "project_name": district.project_name,
    }


def coder_table(user, raw_district_id, period: str) -> dict:
    """The per-coder table for one district: five grouped queries, whatever
    the number of coders. Rows sort by name, or, when names are hidden, by
    user id, so "Coder N" cannot be mapped back by sorting a known roster.
    There is no total row."""
    district = resolve_district(user, raw_district_id)
    since = _since(period, district)
    visible = names_visible(user, district)
    coders = _district_coders(district)
    truncated = len(coders) > MAX_CODERS
    coders = coders[:MAX_CODERS]
    if not visible:
        coders.sort(key=lambda row: row.user_id)
    ids = [row.user_id for row in coders]
    rows = []
    if ids:
        scope = _case_scope(user, district)
        coded = _coded_counts(scope, ids, since)
        not_codeable = _not_codeable_counts(scope, ids, since)
        recodes = _recode_counts(scope, ids, since)
        ready = _ready_counts(user, district, ids)
        for number, coder in enumerate(coders, start=1):
            coded_n, agreed, changed = coded.get(coder.user_id, (0, 0, 0))
            row = {
                "label": coder.name if visible else f"Coder {number}",
                "ready": ready.get(coder.user_id, 0),
                "coded": coded_n,
                "reviewed_agreed": agreed,
                "reviewed_changed": changed,
                "not_codeable": not_codeable.get(coder.user_id, 0),
                "recodes": recodes.get(coder.user_id, 0),
                "last_active": (
                    coder.last_signed_in_at.date().isoformat()
                    if visible and coder.last_signed_in_at else None
                ),
            }
            # An id names nobody: it lets a mentor without names open the
            # coder's cases and write a note (owner 2026-11-20).
            row["coder_id"] = str(coder.user_id)
            rows.append(row)
    return {
        "district": district_summary(district),
        "period": period,
        "names_visible": visible,
        "coders": rows,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# Drill-down
# ---------------------------------------------------------------------------

def parse_cursor(raw: str | None):
    """``"<iso timestamp>|<va_sid>"`` or None; ValueError when malformed."""
    if not raw:
        return None
    stamp, sep, sid = raw.partition("|")
    if not sep or not sid or len(sid) > 64:
        raise ValueError(raw)
    # Naive for va_finassess_createdat (a timestamp without zone), aware for notes.
    return datetime.fromisoformat(stamp), sid


def _cursor(when: datetime, key) -> str:
    return f"{when.isoformat()}|{key}"


def _pseudonym(district: District, coder_user_id) -> str:
    """The coder table's "Coder N" for a viewer without names (numbered in
    user-id order, as there)."""
    ids = sorted(row.user_id for row in _district_coders(district)[:MAX_CODERS])
    return f"Coder {ids.index(coder_user_id) + 1}" if coder_user_id in ids else "Coder"


def _district_coder(district: District, raw_coder_id):
    rows = _district_coders(district, coder_id=_parse_uuid(raw_coder_id))
    if not rows:
        raise MentorViewNotFound()
    return rows[0]


def _note_json(note, author_name, institute_name, viewer, can_retract: bool) -> dict:
    return {
        "note_id": str(note.note_id),
        "va_sid": note.va_sid,
        "body": note.body,
        "created_at": note.created_at.isoformat(),
        "read": note.read_at is not None,
        "author_name": author_name,
        "author_basis": note.author_basis,
        "institute_name": institute_name,
        "mine": note.author_user_id == viewer.user_id,
        "can_retract": can_retract,
    }


def _notes_select():
    author = aliased(VaUsers)
    return (
        sa.select(VaCoderFeedbackNote, author.name, MasMentorInstitute.institute_name)
        .join(author, author.user_id == VaCoderFeedbackNote.author_user_id)
        .outerjoin(MasMentorInstitute,
                   MasMentorInstitute.institute_id == VaCoderFeedbackNote.institute_id)
        .where(VaCoderFeedbackNote.retracted_at.is_(None))
    )


def coder_cases(user, raw_district_id, raw_coder_id, period: str, after: str | None) -> dict:
    """One page of the coder's coded cases in the district, newest first,
    keyset on (coded_at, va_sid), with the live notes on each row (one IN
    query). Audited to grants.log; no case text in the line."""
    district = resolve_district(user, raw_district_id)
    since = _since(period, district)
    coder = _district_coder(district, raw_coder_id)
    label = coder.name if names_visible(user, district) else _pseudonym(district, coder.user_id)
    cursor = parse_cursor(after)
    fa, rfa = VaFinalAssessments, VaReviewerFinalAssessments
    stmt = (
        sa.select(fa.va_sid, fa.va_finassess_createdat, fa.va_conclusive_cod,
                  rfa.va_conclusive_cod.label("reviewer_cod"))
        .join(VaSubmissions, VaSubmissions.va_sid == fa.va_sid)
        .outerjoin(rfa, sa.and_(
            rfa.va_sid == fa.va_sid, rfa.va_rfinassess_status == VaStatuses.active,
        ))
        .where(
            fa.va_finassess_by == coder.user_id,
            fa.va_finassess_status == VaStatuses.active,
            fa.is_tester.is_(False),
            _case_scope(user, district),
        )
        .order_by(fa.va_finassess_createdat.desc(), fa.va_sid.desc())
        .limit(CASE_PAGE_SIZE + 1)
    )
    if since is not None:
        stmt = stmt.where(fa.va_finassess_createdat >= since)
    if cursor is not None:
        stmt = stmt.where(sa.tuple_(fa.va_finassess_createdat, fa.va_sid) < sa.tuple_(*cursor))
    rows = db.session.execute(stmt).all()
    more = len(rows) > CASE_PAGE_SIZE
    rows = rows[:CASE_PAGE_SIZE]

    notes: dict[str, list] = {}
    if rows:
        can_retract_all = _may_retract_in(user, district)
        for note, author_name, institute_name in db.session.execute(
            _notes_select()
            .where(
                VaCoderFeedbackNote.va_sid.in_([row.va_sid for row in rows]),
                VaCoderFeedbackNote.coder_user_id == coder.user_id,
            )
            .order_by(VaCoderFeedbackNote.created_at)
        ).all():
            notes.setdefault(note.va_sid, []).append(_note_json(
                note, author_name, institute_name, user,
                can_retract_all or note.author_user_id == user.user_id,
            ))

    cases = []
    for row in rows:
        if row.reviewer_cod is None:
            outcome = "not_reviewed"
        elif row.reviewer_cod == row.va_conclusive_cod:
            outcome = "agreed"
        else:
            outcome = "changed"
        cases.append({
            "va_sid": row.va_sid,
            "coded_at": row.va_finassess_createdat.isoformat(),
            "final_cod": row.reviewer_cod or row.va_conclusive_cod,
            "review_outcome": outcome,
            "notes": notes.get(row.va_sid, []),
        })
    log_mentor_institute_action(
        action="mentor_case_list_opened", actor_user_id=user.user_id,
        district=district.org_unit_id, coder=coder.user_id, period=period, rows=len(cases),
    )
    return {
        "district": district_summary(district),
        "coder": {"coder_id": str(coder.user_id), "name": label},
        "period": period,
        "cases": cases,
        "next": _cursor(rows[-1].va_finassess_createdat, rows[-1].va_sid) if more else None,
    }


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def _may_retract_in(user, district: District) -> bool:
    """Admin, or a data manager / In-charge whose grant covers the district
    (owner decision 6); the author is checked separately."""
    return "admin" in district.bases or "data_manager" in district.bases or "site_pi" in district.bases


def _audit(note: VaCoderFeedbackNote, user, role: str, action: str, operation: str) -> None:
    db.session.add(VaSubmissionsAuditlog(
        va_sid=note.va_sid, va_audit_byrole=role, va_audit_by=user.user_id,
        va_audit_operation=operation, va_audit_action=action, va_audit_entityid=note.note_id,
    ))


def clean_body(raw) -> str:
    """The note text, 1 to NOTE_MAX_LENGTH characters; ValueError otherwise."""
    body = raw.strip() if isinstance(raw, str) else ""
    if not body or len(body) > NOTE_MAX_LENGTH:
        raise ValueError("A note is 1 to 2000 characters.")
    return body


def create_note(user, va_sid: str, raw_body) -> dict:
    """Write a note on *va_sid* for its active final coder, audit it and
    notify the coder, in one transaction. The author must pass the
    drill-down test on the case's district and ``can(VIEW)`` on the case."""
    districts = viewer_districts(user)
    if not districts:
        raise MentorViewForbidden("Only mentor view users may write notes.")
    body = clean_body(raw_body)
    case = db.session.execute(
        sa.select(
            VaSubmissions.va_sid, MasOrgUnit.project_id,
            sa.cast(MasOrgUnit.path, sa.Text).label("path"),
            VaFinalAssessments.va_finassess_by,
        )
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaSubmissions.org_unit_id)
        .join(VaFinalAssessments, sa.and_(
            VaFinalAssessments.va_sid == VaSubmissions.va_sid,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
            VaFinalAssessments.is_tester.is_(False),
        ))
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    district = case and next(
        (d for d in districts if d.holds(case.project_id, case.path)), None
    )
    # The same scope as the drill-down list: a retired or duplicate case the
    # list hides cannot take a note either.
    if district is None or not db.session.scalar(
        sa.select(sa.literal(True)).where(VaSubmissions.va_sid == va_sid, _case_scope(user, district))
    ):
        raise MentorViewNotFound()
    _district_coder(district, case.va_finassess_by)
    basis = district.bases[0]
    note = VaCoderFeedbackNote(
        note_id=uuid.uuid4(), va_sid=va_sid, coder_user_id=case.va_finassess_by,
        author_user_id=user.user_id, author_basis=basis,
        institute_id=district.institute_ids[0] if basis == "mentor" else None,
        project_id=district.project_id, org_unit_id=district.org_unit_id, body=body,
        created_at=datetime.now(UTC),
    )
    db.session.add(note)
    db.session.flush()
    _audit(note, user, basis, "mentor_note_created", "c")
    notify([case.va_finassess_by], MENTOR_FEEDBACK, project_id=district.project_id, va_sid=va_sid)
    db.session.commit()
    institute = db.session.get(MasMentorInstitute, note.institute_id) if note.institute_id else None
    return _note_json(note, user.name, institute and institute.institute_name, user, True)


def retract_note(user, raw_note_id) -> dict:
    """Soft-delete a live note: its author, an admin, or a data manager /
    In-charge covering its district. Anyone else gets 404."""
    mark_consulted()
    note = db.session.get(VaCoderFeedbackNote, _parse_uuid(raw_note_id))
    if note is None or note.retracted_at is not None:
        raise MentorViewNotFound()
    role = "author"
    if note.author_user_id != user.user_id:
        district = next(
            (d for d in viewer_districts(user) if d.org_unit_id == note.org_unit_id), None
        )
        if district is None or not _may_retract_in(user, district):
            raise MentorViewNotFound()
        role = next(b for b in district.bases if b != "mentor")
    note.retracted_at = datetime.now(UTC)
    note.retracted_by = user.user_id
    _audit(note, user, role, "mentor_note_retracted", "d")
    db.session.commit()
    return {"note_id": str(note.note_id), "retracted": True}


def my_feedback(user, va_sid: str | None = None, after: str | None = None) -> dict:
    """The caller's own live notes, newest first, one page, plus the unread
    count. Only notes whose coder is the caller; a cursor is
    ``"<created_at>|<note_id>"``."""
    mark_consulted()  # own rows only: coder_user_id is the caller
    cursor = parse_cursor(after)
    stmt = (
        _notes_select()
        .where(VaCoderFeedbackNote.coder_user_id == user.user_id)
        .order_by(VaCoderFeedbackNote.created_at.desc(), VaCoderFeedbackNote.note_id.desc())
        .limit(FEEDBACK_PAGE_SIZE + 1)
    )
    if va_sid:
        stmt = stmt.where(VaCoderFeedbackNote.va_sid == va_sid)
    if cursor is not None:
        when, key = cursor
        stmt = stmt.where(sa.tuple_(VaCoderFeedbackNote.created_at, VaCoderFeedbackNote.note_id)
                          < sa.tuple_(when, _parse_uuid(key)))
    rows = db.session.execute(stmt).all()
    more = len(rows) > FEEDBACK_PAGE_SIZE
    rows = rows[:FEEDBACK_PAGE_SIZE]
    unread = db.session.scalar(
        sa.select(sa.func.count()).select_from(VaCoderFeedbackNote).where(
            VaCoderFeedbackNote.coder_user_id == user.user_id,
            VaCoderFeedbackNote.retracted_at.is_(None),
            VaCoderFeedbackNote.read_at.is_(None),
        )
    )
    notes = [_note_json(note, name, institute, user, False) for note, name, institute in rows]
    return {
        "notes": notes,
        "unread_count": unread,
        "next": _cursor(rows[-1][0].created_at, rows[-1][0].note_id) if more else None,
    }


def mark_read(user, raw_note_id) -> dict:
    """One-way read mark on one of the caller's own live notes."""
    mark_consulted()
    note = db.session.get(VaCoderFeedbackNote, _parse_uuid(raw_note_id))
    if note is None or note.coder_user_id != user.user_id or note.retracted_at is not None:
        raise MentorViewNotFound()
    if note.read_at is None:
        note.read_at = datetime.now(UTC)
        db.session.commit()
    return {"note_id": str(note.note_id), "read": True}
