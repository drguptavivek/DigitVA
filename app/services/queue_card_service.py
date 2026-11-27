"""The queue case card's additive keys (owner 2026-11-27).

``add_card_keys`` sets them on one page of Coding or Review queue rows in two
queries (plus ``coding_names``'s own when names are asked for), whatever the
page's size:

- ``unit_name`` (the submission's org unit; null without one), ``site_name``
  (the form's site) and ``project_nickname`` (``project_nickname``, else
  ``project_name``): the card's place line, never a code. Only on a row of a
  project where the caller has personal-data access (``pii_scope``, owner
  2026-11-27; docs/policy/case-list-views.md); absent otherwise, so the card
  draws no place line.
- ``va_deceased_age_normalized_days`` (a number or null): the age chip.
- ``date_of_death`` (ISO date or null): the earliest date of death of the
  case's live register rows (not duplicate, not cancelled), the rule of
  ``cod_bucket_mapping_service``'s ``event_date``. An ODK submission has one
  only when the sync could make its case (name, sex and a date of death);
  for a year-only answer that case holds 1 July of that year
  (``web_intake.drafts._approximate_date_of_death``).
- ``first_coded_at`` / ``last_coded_at`` (tz-aware UTC ISO or null) and
  ``recoded`` (bool): one coder's earliest and latest final COD on the case,
  any status (a new final deactivates the earlier one and keeps it,
  ``coder_cod_service``), tester and demo output excluded; ``recoded`` when
  that coder has more than one. The coder is *coder_id* (a coder's own
  history), else the author of the case's active final, else the latest
  coder: several coders' finals on one case (a training standard case) never
  read as a recode. A recode by another coder (an admin override) therefore
  shows as that coder's first coding.
- ``deceased_name`` only with *names*, through ``coding_names`` (the
  PII-gated coding-screen rule): absent for a row the caller may not name.

The keys are always set afresh (a cached row never keeps an old value); the
pick list's own ``deceased_name`` is left as it is (it is not asked for names).
"""
from datetime import UTC

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaDeathRegister,
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
)
from app.services.viewer_pii_service import pii_scope

_DEAD_CASE_STATES = ("duplicate", "cancelled")
_PLACE_KEYS = ("unit_name", "site_name", "project_nickname")


def _utc_iso(value):
    return value.replace(tzinfo=UTC).isoformat() if value else None


def add_card_keys(user, rows: list[dict], *, names: bool = False, coder_id=None) -> list[dict]:
    """Set the card keys on *rows* (dicts with ``va_sid``) in place; returns *rows*.
    *coder_id* scopes the coding dates to that coder's finals."""
    sids = list(dict.fromkeys(row["va_sid"] for row in rows))
    if not sids:
        return rows
    # The page's submissions with their place names and the grouped register deaths, bounded by the same sids.
    deaths = (
        sa.select(VaDeathRegister.va_sid, sa.func.min(VaDeathRegister.date_of_death).label("died"))
        .where(VaDeathRegister.va_sid.in_(sids), VaDeathRegister.status.not_in(_DEAD_CASE_STATES))
        .group_by(VaDeathRegister.va_sid)
        .subquery()
    )
    # Per (case, coder): their first and latest final, how many, and whether one is the case's active final.
    codings = db.session.execute(
        sa.select(
            VaFinalAssessments.va_sid,
            VaFinalAssessments.va_finassess_by,
            sa.func.min(VaFinalAssessments.va_finassess_createdat),
            sa.func.max(VaFinalAssessments.va_finassess_createdat),
            sa.func.count(),
            sa.func.bool_or(VaFinalAssessments.va_finassess_status == VaStatuses.active),
        )
        .where(
            VaFinalAssessments.va_sid.in_(sids),
            VaFinalAssessments.is_tester.is_(False),
            VaFinalAssessments.demo_expires_at.is_(None),
        )
        .group_by(VaFinalAssessments.va_sid, VaFinalAssessments.va_finassess_by)
    ).all()
    coding_of: dict[str, tuple] = {}
    for sid, by, first, last, count, active in codings:
        if coder_id is not None:
            if by == coder_id:
                coding_of[sid] = (first, last, count)
            continue
        rank = (bool(active), last)
        if sid not in coding_of or rank > coding_of[sid][3]:
            coding_of[sid] = (first, last, count, rank)
    found = {
        r.va_sid: r
        for r in db.session.execute(
            sa.select(
                VaSubmissions.va_sid,
                MasOrgUnit.unit_name,
                VaSiteMaster.site_name,
                sa.func.coalesce(
                    sa.func.nullif(sa.func.trim(VaProjectMaster.project_nickname), ""),
                    VaProjectMaster.project_name,
                ).label("project_nickname"),
                sa.cast(VaSubmissions.va_deceased_age_normalized_days, sa.Float).label("age_days"),
                deaths.c.died,
            )
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaSubmissions.org_unit_id)
            .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaForms.site_id)
            .outerjoin(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
            .outerjoin(deaths, deaths.c.va_sid == VaSubmissions.va_sid)
            .where(VaSubmissions.va_sid.in_(sids))
        )
    }
    pii = pii_scope(user)
    if names:
        from app.services.case_list_service import coding_names

        named = coding_names(user, sids)
    for row in rows:
        sid = row["va_sid"]
        found_row = found.get(sid)
        if pii.sees(row.get("project_id")):
            row["unit_name"] = found_row.unit_name if found_row else None
            row["site_name"] = found_row.site_name if found_row else None
            row["project_nickname"] = found_row.project_nickname if found_row else None
        else:
            for key in _PLACE_KEYS:
                row.pop(key, None)
        row["va_deceased_age_normalized_days"] = found_row.age_days if found_row else None
        row["date_of_death"] = found_row.died.isoformat() if found_row and found_row.died else None
        first, last, count = coding_of.get(sid, (None, None, 0))[:3]
        row["first_coded_at"] = _utc_iso(first)
        row["last_coded_at"] = _utc_iso(last)
        row["recoded"] = count > 1
        if names and named.get(sid):
            row["deceased_name"] = named[sid]
        elif names:
            row.pop("deceased_name", None)
    return rows
