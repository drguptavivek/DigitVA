"""Serializers: the dict shapes the web and device APIs return.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaDeathRegister,
    VaProjectMaster,
    VaSiteMaster,
    VaUsers,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.services import (
    org_grant_service,
    register_pii_accessor,
)
from app.services.web_intake import facade
from app.services.web_intake.register import (
    LOCATION_FIELDS,
)
from app.services.web_intake.scope import (
    _code_now_unit_ok,
    self_coding_project_ids,
)


def gps_projects(user: VaUsers, project_ids: set[str]) -> set[str]:
    """The projects among *project_ids* where *user* sees the GPS fix of a
    death someone else registered: organization projects
    (``projects_with_org_tree``) and only those where the caller has
    personal-data access (``pii_scope``, per project). One grant read and one org-tree read, so
    call it once per request, not per row. ``shows_gps`` adds the reporter's
    own registrations (owner, 2026-10-20; docs/policy/web-intake.md)."""
    pii = facade().pii_scope(user)
    visible = {p for p in project_ids if pii.sees(p)} if project_ids else set()
    if not visible:
        return set()
    return org_grant_service.projects_with_org_tree(visible)


def shows_gps(user: VaUsers, death: VaDeathRegister, visible_projects: set[str]) -> bool:
    """Whether a case detail or register row for *death* carries its GPS fix:
    *death* is in one of *visible_projects* (``gps_projects``), or *user*
    registered it, in any project, so the registration's edit form keeps the
    fix its reporter captured."""
    return death.registered_by == user.user_id or death.project_id in visible_projects


def _serialize_location(death: VaDeathRegister, show_gps: bool, values: dict) -> dict:
    """The GPS fix, for the serializers that already carry the address; the
    keys are omitted (not null) when *show_gps* is False (``shows_gps``).
    *values* are the opened register attributes."""
    if not show_gps:
        return {}
    return {
        "latitude": values["latitude"],
        "longitude": values["longitude"],
        "accuracy_m": values["accuracy_m"],
        "captured_at": death.captured_at.isoformat() if death.captured_at else None,
    }


def _register_values(death: VaDeathRegister, register: dict | None, only) -> dict:
    """The opened sealed attributes of *death* named in *only*: *register*
    when the caller opened a whole page (``open_register_pii``, one unwrap a
    row), else opened here. A viewer who may not see an attribute leaves it
    out of *only*, so it is never decrypted."""
    return register if register is not None else register_pii_accessor.current_values(death, only)


def without_location(names=register_pii_accessor.SEALED_ATTRS) -> tuple:
    return tuple(n for n in names if n not in LOCATION_FIELDS)


_without_location = without_location  # the earlier name: this module and tests still use it


def serialize_death(death: VaDeathRegister, *, show_gps: bool = False, register: dict | None = None) -> dict:
    """One register row. The GPS fix (``latitude``, ``longitude``,
    ``accuracy_m``, ``captured_at``) only when *show_gps* (``shows_gps``).
    *register*: the row's opened attributes when the caller opened a page of
    rows (``open_register_pii``); else opened here."""
    values = _register_values(
        death, register, register_pii_accessor.SEALED_ATTRS if show_gps else _without_location())
    return {
        "death_id": str(death.death_id),
        "project_id": death.project_id,
        "site_id": death.site_id,
        "org_unit_id": str(death.org_unit_id) if death.org_unit_id else None,
        "unique_id": death.unique_id,
        "deceased_name": values["deceased_name"],
        "deceased_sex": death.deceased_sex,
        "abha_number": values["abha_number"],
        "abha_address": values["abha_address"],
        "date_of_birth": death.date_of_birth.isoformat() if death.date_of_birth else None,
        "date_of_birth_partial": death.date_of_birth_partial,
        "age_years": death.age_years,
        "date_of_death": death.date_of_death.isoformat() if death.date_of_death else None,
        "place_of_death": values["place_of_death"],
        "address": values["address"],
        "address_house_street": values["address_house_street"],
        "address_village_ward": values["address_village_ward"],
        "address_landmark": values["address_landmark"],
        **_serialize_location(death, show_gps, values),
        "informant_name": values["informant_name"],
        "father_name": values["father_name"],
        "mother_name": values["mother_name"],
        "informant_phone": values["informant_phone"],
        "informant_phone_2": values["informant_phone_2"],
        "remarks": values["remarks"],
        "next_visit_at": death.next_visit_at.isoformat() if death.next_visit_at else None,
        "last_contact_at": death.last_contact_at.isoformat() if death.last_contact_at else None,
        "status": death.status,
        "source": death.source,
        "pending_flag": death.pending_flag,
        "va_sid": death.va_sid,
        "created_at": death.created_at.isoformat(),
    }


def _code_now(user: VaUsers, death: VaDeathRegister, my_submission: bool, ready_for_coding: bool | None) -> bool:
    return bool(
        my_submission and ready_for_coding and death.project_id in self_coding_project_ids(user)
        and _code_now_unit_ok(user, death.project_id, death.org_unit_id)
    )


def serialize_worklist_row(user: VaUsers, death: VaDeathRegister, unit_name: str | None,
                           my_draft_id: uuid.UUID | None, other_draft_started_at: datetime | None = None,
                           my_submission: bool = False, other_complete_interview: bool = False,
                           ready_for_coding: bool | None = False, other_draft_started_by: str | None = None,
                           register: dict | None = None) -> dict:
    """One worklist row (browser and device lists). *register*: the row's
    opened ``deceased_name`` when the caller opened the page (one unwrap a
    row); phone presence comes from the ``has_*`` flags, nothing else opens. No informant name or
    address, and no phone digits (only ``has_informant_phone`` booleans): the
    list shows who died, not how to reach the family. ``va_sid`` only for the interviewer whose draft
    became the submission (*my_submission*): the interview form is its
    interviewer's own. ``other_draft_active`` / ``other_draft_started_at`` /
    ``other_draft_started_by`` warn that another interviewer holds an open
    draft, when the earliest one started and that interviewer's name (owner,
    2026-11-05: names are an operational need inside the organisation);
    ``other_complete_interview`` that a second complete interview of the case
    exists (a supervisor may choose it), never whose. ``code_now``: the caller's
    own submission is ``ready_for_coding`` in a self-coding project where they
    code, so "Code now" works (``coder_workflow_service.allocate_own_case``)."""
    values = _register_values(death, register, ("deceased_name",))
    return {
        "death_id": str(death.death_id),
        "unique_id": death.unique_id,
        "project_id": death.project_id,
        "site_id": death.site_id,
        "org_unit_id": str(death.org_unit_id) if death.org_unit_id else None,
        "unit_name": unit_name,
        "source": death.source,
        "state": death.status,
        "details_pending": death.status == "draft_identity",
        "deceased_name": values["deceased_name"],
        "deceased_sex": death.deceased_sex,
        "age_years": death.age_years,
        "date_of_death": death.date_of_death.isoformat() if death.date_of_death else None,
        "pending_flag": death.pending_flag,
        "next_visit_at": death.next_visit_at.isoformat() if death.next_visit_at else None,
        "last_contact_at": death.last_contact_at.isoformat() if death.last_contact_at else None,
        "has_informant_phone": bool(death.has_informant_phone),
        "has_informant_phone_2": bool(death.has_informant_phone_2),
        "registered_by_me": death.registered_by == user.user_id,
        "started_by_me": death.started_by_user_id == user.user_id,
        # Someone started the case (no name: who holds it is supervisor-only).
        "started": death.started_by_user_id is not None,
        "my_draft_id": str(my_draft_id) if my_draft_id else None,
        "other_draft_active": other_draft_started_at is not None,
        "other_draft_started_at": other_draft_started_at.isoformat() if other_draft_started_at else None,
        "other_draft_started_by": other_draft_started_by if other_draft_started_at else None,
        "va_sid": death.va_sid if my_submission else None,
        "other_complete_interview": bool(other_complete_interview),
        "code_now": _code_now(user, death, my_submission, ready_for_coding),
        "created_at": death.created_at.isoformat(),
        "updated_at": death.updated_at.isoformat(),
    }


#: Never in a case detail (``serialize_case_detail``): they come only in the
#: API's ``prefill`` to a caller who may start the interview.
_CASE_DETAIL_HIDDEN = ("abha_number", "abha_address", "father_name", "mother_name")


def serialize_case_detail(user: VaUsers, death: VaDeathRegister, unit_name: str | None,
                          my_draft_id: uuid.UUID | None, other_draft_started_at: datetime | None = None,
                          my_submission: bool = False, other_complete_interview: bool = False,
                          ready_for_coding: bool | None = False, other_draft_started_by: str | None = None,
                          register: dict | None = None) -> dict:
    """One case for the case page and the device detail: the worklist row's
    case fields plus the full contact details (informant name, both phones,
    household address, remarks). Never ABHA, parents' names, other users' ids
    or client ids: the ABHA and parents' names come only in the API's
    ``prefill`` (``case_prefill``), only to a caller who may start or resume
    the interview (docs/policy/web-intake.md, "Single-case detail"). The
    submission id (``va_sid``) only to the interviewer whose draft became the
    submission (*my_submission*); ``other_draft_active``,
    ``other_draft_started_at``, ``other_draft_started_by`` and
    ``other_complete_interview`` as in
    ``serialize_worklist_row``, as is ``code_now``. The household address's
    GPS fix only where ``shows_gps`` allows it; otherwise its keys are
    absent. *register*: the row's opened attributes, if the caller has them;
    ABHA and parents' names, and the fix without ``show_gps``, are never
    opened here."""
    show_gps = facade().shows_gps(user, death, gps_projects(user, {death.project_id}))
    values = _register_values(death, register, tuple(
        n for n in register_pii_accessor.SEALED_ATTRS
        if n not in _CASE_DETAIL_HIDDEN and (show_gps or n not in LOCATION_FIELDS)))
    return {
        "death_id": str(death.death_id),
        "unique_id": death.unique_id,
        "project_id": death.project_id,
        "site_id": death.site_id,
        "org_unit_id": str(death.org_unit_id) if death.org_unit_id else None,
        "unit_name": unit_name,
        "source": death.source,
        "state": death.status,
        "details_pending": death.status == "draft_identity",
        "pending_flag": death.pending_flag,
        "deceased": {
            "name": values["deceased_name"],
            "sex": death.deceased_sex,
            "age_years": death.age_years,
            "date_of_birth": death.date_of_birth.isoformat() if death.date_of_birth else None,
            "date_of_birth_partial": death.date_of_birth_partial,
            "date_of_death": death.date_of_death.isoformat() if death.date_of_death else None,
            "place_of_death": values["place_of_death"],
        },
        "household_address": {
            "address": values["address"],
            "house_street": values["address_house_street"],
            "village_ward": values["address_village_ward"],
            "landmark": values["address_landmark"],
            **_serialize_location(death, show_gps, values),
        },
        "informant": {
            "name": values["informant_name"],
            "phone": values["informant_phone"],
            "phone_2": values["informant_phone_2"],
        },
        "remarks": values["remarks"],
        "next_visit_at": death.next_visit_at.isoformat() if death.next_visit_at else None,
        "last_contact_at": death.last_contact_at.isoformat() if death.last_contact_at else None,
        "registered_by_me": death.registered_by == user.user_id,
        "started_by_me": death.started_by_user_id == user.user_id,
        "my_draft_id": str(my_draft_id) if my_draft_id else None,
        "other_draft_active": other_draft_started_at is not None,
        "other_draft_started_at": other_draft_started_at.isoformat() if other_draft_started_at else None,
        "other_draft_started_by": other_draft_started_by if other_draft_started_at else None,
        "va_sid": death.va_sid if my_submission else None,
        "other_complete_interview": bool(other_complete_interview),
        "code_now": _code_now(user, death, my_submission, ready_for_coding),
        "created_at": death.created_at.isoformat(),
        "updated_at": death.updated_at.isoformat(),
    }


#: The sealed attributes a supervision row opens (where the caller sees PII).
SUPERVISED_ROW_PII = ("deceased_name", "address_village_ward")


def serialize_supervised_row(user: VaUsers, death: VaDeathRegister, unit_name: str | None,
                             registered_by_name: str | None, started_by_name: str | None,
                             other_complete_interview: bool = False, register: dict | None = None) -> dict:
    """A worklist row plus who registered and started the case (staff identity,
    decision 13), without the informant's phones: the supervisor list does not
    contact families. ``other_complete_interview``: a candidate to choose
    exists (``choose_interview``). The deceased, registrant and starter names
    and the household's ``village_ward`` are null where *user* has no
    personal-data access in the case's project (``pii_scope``; web-intake.md
    item 14), and are then never opened. *register*: the row's opened
    ``deceased_name`` and ``address_village_ward`` when the caller opened the
    page; else opened here."""
    named = facade().pii_scope(user).sees(death.project_id)
    if not named:
        register = {"deceased_name": None, "address_village_ward": None}
    elif register is None:
        register = register_pii_accessor.current_values(death, SUPERVISED_ROW_PII)
    row = serialize_worklist_row(user, death, unit_name, None, other_complete_interview=other_complete_interview,
                                 register=register)
    for key in ("my_draft_id", "has_informant_phone", "has_informant_phone_2",
                "other_draft_active", "other_draft_started_at", "other_draft_started_by", "code_now"):
        row.pop(key)
    # Supervisors oversee every interview in scope, so they keep every va_sid
    # (the submitter-only rule is the interviewer lists').
    row["va_sid"] = death.va_sid
    row["village_ward"] = register.get("address_village_ward") or None
    row["registered_by_name"] = registered_by_name if named else None
    row["started_by_name"] = started_by_name if named else None
    row["duplicate_of_death_id"] = str(death.duplicate_of_death_id) if death.duplicate_of_death_id else None
    # Only an admin reaches a withdrawn case here (get_supervised_case).
    row["consent_withdrawn"] = death.consent_withdrawn_at is not None
    return row


def serialize_draft(draft: VaWebIntakeDraft, *, sections_saved: int | None = None) -> dict:
    """One draft. *sections_saved*: the count already fetched for a list
    (``serialize_drafts``); otherwise the draft's sections are loaded."""
    return {
        "draft_id": str(draft.draft_id),
        "project_id": draft.project_id,
        "site_id": draft.site_id,
        "org_unit_id": str(draft.org_unit_id) if draft.org_unit_id else None,
        "death_id": str(draft.death_id) if draft.death_id else None,
        "form_id": draft.form_id,
        "unique_id": draft.unique_id,
        "current_section": draft.current_section,
        "status": draft.status,
        "va_sid": draft.va_sid,
        "sections_saved": len(draft.sections) if sections_saved is None else sections_saved,
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }


def serialize_drafts(drafts: list[VaWebIntakeDraft]) -> list[dict]:
    """``GET /drafts`` rows: ``serialize_draft`` plus the case's
    ``deceased_name``, ``deceased_sex``, ``age_years`` and ``date_of_death``
    (the caller's own drafts, whose answers already hold them; None for a
    direct start without a case) so the list can filter like the worklist.
    Two queries for the whole list, not a lazy sections load per row."""
    if not drafts:
        return []
    counts = dict(db.session.execute(
        sa.select(VaWebIntakeDraftSection.draft_id, sa.func.count())
        .where(VaWebIntakeDraftSection.draft_id.in_([d.draft_id for d in drafts]))
        .group_by(VaWebIntakeDraftSection.draft_id)
    ).all())
    death_ids = {d.death_id for d in drafts if d.death_id}
    cases = {c.death_id: c for c in db.session.scalars(
        sa.select(VaDeathRegister).where(VaDeathRegister.death_id.in_(death_ids))
    )} if death_ids else {}
    # The name is sealed on a sealed row: open it for the page's rows (no
    # query, one unwrap a sealed row).
    names = {k: v["deceased_name"] for k, v in register_pii_accessor.open_register_pii(
        cases.values(), only=("deceased_name",)).items()}
    rows = []
    for d in drafts:
        case = cases.get(d.death_id)
        rows.append(dict(
            serialize_draft(d, sections_saved=counts.get(d.draft_id, 0)),
            deceased_name=names.get(d.death_id),
            deceased_sex=case.deceased_sex if case else None,
            age_years=case.age_years if case else None,
            date_of_death=case.date_of_death.isoformat() if case and case.date_of_death else None,
        ))
    return rows


def resolve_draft_display_names(draft: VaWebIntakeDraft) -> dict:
    """Project, site and (if any) org-unit/level names for the intake form
    header (digitva-wdj) -- names instead of the bare codes it used to show.

    One query for a single draft: not folded into ``serialize_draft`` because
    that is also called once per row of ``serialize_drafts``, where adding a join
    here would turn into an N+1.
    """
    row = db.session.execute(
        sa.select(
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
            MasOrgUnit.unit_name,
            MasOrgLevel.level_name,
        )
        .select_from(VaProjectMaster)
        # Project and site are unrelated tables (each narrowed to one row by
        # the WHERE below), so the join has no natural ON of its own.
        .join(VaSiteMaster, sa.true())
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == draft.org_unit_id)
        .outerjoin(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(VaProjectMaster.project_id == draft.project_id, VaSiteMaster.site_id == draft.site_id)
    ).one_or_none()
    if row is None:
        return {"project_name": draft.project_id, "site_name": draft.site_id, "org_unit_name": None, "org_level_name": None}
    project_name, site_name, unit_name, level_name = row
    return {
        "project_name": project_name,
        "site_name": site_name,
        "org_unit_name": unit_name,
        "org_level_name": level_name,
    }
