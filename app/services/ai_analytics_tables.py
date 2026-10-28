"""The temp tables AI questions read: what each holds and how it is scoped.

docs/policy/ai-analytics-questions.md, "What the generated SQL can read" and
"Tables, staff results and \"not captured\"". Each function returns the
SELECT a run turns into a transaction-local temp table of the same name
(``ai_analytics_sandbox``); a run builds only the tables its SQL names.

- ``ai_cube``: case counts in the caller's analytics scope (``dm_grant_scope``
  + ``_mv_scope_filter``), grouped by low-risk dimensions.
- ``ai_org_levels``: the level names of the caller's projects' hierarchies.
- ``ai_staff``: staff counts per project, site, org unit and role, no names;
  the grants on the caller's Users page (``authz.user_list_filter``) in the
  caller's projects.
- ``ai_coder``: named coder results per coder, project and month, for coders
  with finals or not-codeable marks on cases in the caller's case scope.

No table holds a ``va_sid``, case id, narrative or deceased detail. The
interviewer per case is not built: ``va_data_collector`` is ODK's free-text
``SubmitterName``, not an account, so it is listed as not captured.
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.mas_training import MapTrainingParticipant
from app.models.va_allocations import VaAllocations
from app.models.va_selectives import VaAccessRoles, VaAllocation, VaStatuses
from app.services.authz import user_list_filter
from app.services.data_management_service import dm_grant_scope
from app.services.submission_analytics_mv import (
    COD_SNAPSHOT_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    _mv_scope_filter,
)

CUBE = "ai_cube"
ORG_LEVELS = "ai_org_levels"
STAFF = "ai_staff"
CODER = "ai_coder"
# The order a run builds them in; the validator's allowed relation set.
TABLES = (CUBE, ORG_LEVELS, STAFF, CODER)

# Org level depths named as org_l1_name .. org_l7_name (dev trees are 6 deep).
ORG_DEPTHS = range(1, 8)
ORG_NAME_COLUMNS = tuple(f"org_l{d}_name" for d in ORG_DEPTHS)
# SmartVA likelihoods, strongest first: "Very Likely", "Likely",
# "Somewhat Likely", "Possible". Low means below "Likely".
SMARTVA_LOW_LIKELIHOODS = ("Somewhat Likely", "Possible")
UNKNOWN_CAUSE_SECTION = "Cause of death unknown"
FAST_FINAL_MINUTES = 3
# Sites listed for the model only up to this many (an admin on a large server).
MAX_SCOPE_SITES = 50

_core = sa.table(
    CORE_MV_NAME,
    sa.column("va_sid"),
    sa.column("project_id"),
    sa.column("site_id"),
    sa.column("org_unit_id"),
    sa.column("submission_month_start"),
    sa.column("workflow_state"),
    sa.column("odk_missing"),
    sa.column("odk_sync_issue_code"),
)
_demo = sa.table(
    DEMOGRAPHICS_MV_NAME,
    sa.column("va_sid"),
    sa.column("sex"),
    sa.column("analytics_age_band"),
)
_snap = sa.table(
    COD_SNAPSHOT_MV_NAME,
    sa.column("va_sid"),
    sa.column("authoritative_source"),
    sa.column("authoritative_who_bucket_section"),
    sa.column("authoritative_who_bucket"),
    sa.column("authoritative_icd"),
    sa.column("authoritative_saved_at"),
    sa.column("smartva_cause1_who_bucket"),
    sa.column("smartva_cause1_icd"),
    sa.column("smartva_likelihood1"),
    sa.column("nqa_rating"),
    sa.column("nqa_score"),
    sa.column("coder_step1_assessment_id"),
    sa.column("coder_final_assessment_id"),
    sa.column("coder_final_by"),
    sa.column("coder_final_saved_at"),
    sa.column("coder_final_icd"),
    sa.column("coder_final_icd11_stem"),
    sa.column("coder_final_who_bucket"),
    sa.column("coder_final_who_bucket_section"),
    sa.column("reviewer_final_assessment_id"),
    sa.column("reviewer_final_icd"),
    sa.column("reviewer_final_icd11_stem"),
)
_sub = sa.table("va_submissions", sa.column("va_sid"), sa.column("va_consent"),
                sa.column("va_narration_language"))


def _scope_filter(scope):
    return _mv_scope_filter(
        _core, sorted(scope.project_ids), scope.pairs, scope_unit_ids=scope.unit_subtree(),
    )


def _scope_projects(scope) -> list[str]:
    """Every project the caller's DM grants touch (training already removed)."""
    return sorted(scope.project_ids | {p for p, _ in scope.pairs} | scope.unit_project_ids)


def scope_places(user) -> dict:
    """The projects and sites in *user*'s AI table scope, for the
    model to match a question's wording against exact values (``digitva-g72d``).

    Projects: ``_scope_projects`` (id, name, nickname; never ``project_code``,
    which is not ``ai_cube.project_id``). Sites: the pairs of project and site
    grants, as ``_mv_scope_filter`` admits them; a unit grant lists none,
    because its cube holds only its subtree. Sites are left out past
    ``MAX_SCOPE_SITES``. The ``sites`` key is absent when empty.
    """
    scope = dm_grant_scope(user)
    projects = _scope_projects(scope)
    places = {"projects": [
        {"project_id": row.project_id, "name": row.project_name, "nickname": row.project_nickname}
        for row in db.session.execute(
            sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name,
                      VaProjectMaster.project_nickname)
            .where(VaProjectMaster.project_id.in_(projects))
            .order_by(VaProjectMaster.project_id)
        )
    ]}
    pairs = scope.active_pairs()
    # ponytail: past the cap the model gets no sites at all; send the sites of
    # the projects a question names if large servers need them.
    if pairs and len(pairs) <= MAX_SCOPE_SITES:
        names = dict(db.session.execute(
            sa.select(VaSiteMaster.site_id, VaSiteMaster.site_name)
            .where(VaSiteMaster.site_id.in_({site for _, site in pairs}))
        ).all())
        places["sites"] = [
            {"project_id": project, "site_id": site, "name": names.get(site)}
            for project, site in sorted(pairs)
        ]
    return places


def _unit_names():
    """One row per org unit: the names of the unit and its ancestors by level
    depth (``org_l<depth>_name``). Pre-aggregated so a join on it stays 1:1."""
    unit = MasOrgUnit.__table__.alias("u")
    anc = MasOrgUnit.__table__.alias("a")
    lvl = MasOrgLevel.__table__
    return (
        sa.select(
            unit.c.org_unit_id,
            *(sa.func.max(anc.c.unit_name).filter(lvl.c.depth == d).label(f"org_l{d}_name")
              for d in ORG_DEPTHS),
        )
        .select_from(
            unit.join(anc, sa.and_(anc.c.project_id == unit.c.project_id,
                                   anc.c.path.op("@>")(unit.c.path)))
            .join(lvl, lvl.c.org_level_id == anc.c.org_level_id)
        )
        .group_by(unit.c.org_unit_id)
        .subquery("unit_names")
    )


def _names(names) -> list:
    return [names.c[c] for c in ORG_NAME_COLUMNS]


def _month(column):
    return sa.cast(sa.func.date_trunc("month", column), sa.Date)


def cube_select(user) -> sa.Select:
    """``ai_cube`` for *user*: case counts inside their analytics scope.

    Every join is 1:1 per case, so the total equals the analytics API's.
    No va_sid, id, name, free text, raw age, date or staff identity may be
    added without a policy change first.
    """
    scope = dm_grant_scope(user)
    names = _unit_names()
    dm_review = (
        sa.select(VaDataManagerReview.va_sid, VaDataManagerReview.va_dmreview_reason)
        # At most one active row per case (uq_va_data_manager_review_active_sid).
        .where(VaDataManagerReview.va_dmreview_status == VaStatuses.active)
        .subquery("dm_review")
    )
    dimensions = (
        _core.c.project_id,
        _core.c.site_id,
        _core.c.submission_month_start.label("submission_month"),
        _demo.c.sex,
        _demo.c.analytics_age_band,
        _core.c.workflow_state,
        _snap.c.authoritative_source,
        _snap.c.authoritative_who_bucket_section,
        _snap.c.authoritative_who_bucket,
        _snap.c.authoritative_icd,
        _snap.c.smartva_cause1_who_bucket,
        _snap.c.nqa_rating,
        sa.func.lower(_sub.c.va_narration_language).label("narration_language"),
        _sub.c.va_consent.label("consent_mode"),
        _core.c.odk_sync_issue_code,
        dm_review.c.va_dmreview_reason.label("dm_not_codeable_reason"),
        *_names(names),
        _month(_snap.c.authoritative_saved_at).label("final_saved_month"),
        sa.cast(sa.func.date_trunc("week", _snap.c.authoritative_saved_at), sa.Date).label("final_saved_week"),
    )
    return (
        sa.select(
            *dimensions,
            sa.func.count().label("n"),
            sa.func.sum(_snap.c.nqa_score).label("nqa_score_sum"),
            sa.func.count(_snap.c.nqa_score).label("nqa_scored_n"),
        )
        # The demographics join is inner, as in the analytics API
        # (get_dm_kpi_from_mv), so cube totals equal its totals. The API's
        # totals never join the COD snapshot: an outer join keeps them equal
        # when the snapshot lags a refresh.
        .select_from(
            _core.join(_demo, _demo.c.va_sid == _core.c.va_sid)
            .join(_sub, _sub.c.va_sid == _core.c.va_sid)
            .outerjoin(_snap, _snap.c.va_sid == _core.c.va_sid)
            .outerjoin(dm_review, dm_review.c.va_sid == _core.c.va_sid)
            .outerjoin(names, names.c.org_unit_id == _core.c.org_unit_id)
        )
        .where(_scope_filter(scope))
        .group_by(*dimensions)
    )


def org_levels_select(user) -> sa.Select:
    """``ai_org_levels``: (project_id, depth, level_name) of the caller's projects."""
    projects = _scope_projects(dm_grant_scope(user))
    return (
        sa.select(MasOrgLevel.project_id, MasOrgLevel.depth, MasOrgLevel.level_name)
        .where(MasOrgLevel.project_id.in_(projects), MasOrgLevel.is_active.is_(True))
    )


def _utc_now():
    # Grant and allocation times are naive UTC; last_signed_in_at is aware.
    return sa.func.timezone("UTC", sa.func.now())


def staff_select(user) -> sa.Select:
    """``ai_staff``: counts of active users with active grants, no names.

    Scope: the grants on *user*'s Users page (``authz.user_list_filter``),
    whose project is one of the caller's DM projects. Each coder appears in a
    headcount row (``coding_language`` NULL) and once per coding language, so
    headcounts never double-count a multilingual coder.
    """
    grant, person = VaUserAccessGrants, VaUsers
    project = sa.func.coalesce(grant.project_id, VaProjectSites.project_id, MasOrgUnit.project_id)
    training = (
        # ponytail: a full aggregate of the small participants table; index
        # user_id if training rosters grow into the tens of thousands.
        sa.select(
            MapTrainingParticipant.user_id,
            sa.func.bool_or(MapTrainingParticipant.status == "active").label("in_training"),
            sa.func.bool_or(sa.and_(MapTrainingParticipant.status == "active",
                                    MapTrainingParticipant.onboarded_at.is_not(None)))
            .label("training_started"),
        )
        .group_by(MapTrainingParticipant.user_id)
        .subquery("training")
    )
    base = (
        sa.select(
            project.label("project_id"),
            VaProjectSites.site_id,
            grant.org_unit_id,
            sa.cast(grant.role, sa.Text).label("role"),
            grant.user_id,
            grant.grant_created_at,
            person.last_signed_in_at,
            person.email_verified,
            person.vacode_language,
            sa.func.coalesce(training.c.in_training, False).label("in_training"),
            sa.func.coalesce(training.c.training_started, False).label("training_started"),
        )
        .select_from(grant)
        .join(person, person.user_id == grant.user_id)
        .outerjoin(VaProjectSites, VaProjectSites.project_site_id == grant.project_site_id)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == grant.org_unit_id)
        .outerjoin(training, training.c.user_id == grant.user_id)
        .where(
            grant.grant_status == VaStatuses.active,
            person.user_status == VaStatuses.active,
            user_list_filter(user),
            project.in_(_scope_projects(dm_grant_scope(user))),
        )
        .subquery("staff_base")
    )
    names = _unit_names()
    now = sa.func.now()

    def users(condition=None):
        count = sa.func.count(sa.distinct(base.c.user_id))
        return count if condition is None else count.filter(condition)

    signed_in = base.c.last_signed_in_at
    metrics = (
        users().label("staff"),
        users(signed_in >= now - sa.text("interval '7 days'")).label("signed_in_7d"),
        users(signed_in >= now - sa.text("interval '30 days'")).label("signed_in_30d"),
        users(signed_in.is_(None)).label("never_signed_in"),
        users(base.c.grant_created_at >= _utc_now() - sa.text("interval '30 days'")).label("granted_30d"),
        users(sa.and_(
            base.c.grant_created_at < _utc_now() - sa.text("interval '30 days'"),
            sa.or_(signed_in.is_(None), signed_in < now - sa.text("interval '30 days'")),
        )).label("dormant_30d"),
        users(base.c.email_verified.is_(False)).label("unverified_email"),
        users(sa.and_(base.c.role == VaAccessRoles.coder.value,
                      sa.func.coalesce(sa.func.cardinality(base.c.vacode_language), 0) == 0))
        .label("no_coding_language"),
        users(base.c.in_training.is_(True)).label("in_training"),
        users(base.c.training_started.is_(True)).label("training_started"),
    )
    source = base.outerjoin(names, names.c.org_unit_id == base.c.org_unit_id)
    keys = (base.c.project_id, base.c.site_id, *_names(names), base.c.role)
    headcount = (
        sa.select(*keys, sa.cast(sa.null(), sa.Text).label("coding_language"), *metrics)
        .select_from(source)
        .group_by(*keys)
    )
    language = sa.func.lower(sa.func.unnest(base.c.vacode_language))
    languages = (
        sa.select(*keys, language.label("coding_language"), *metrics)
        .select_from(source)
        .where(base.c.role == VaAccessRoles.coder.value)
        .group_by(*keys, language)
    )
    return headcount.union_all(languages)


def coder_select(user) -> sa.Select:
    """``ai_coder``: one row per coder, project and month, named.

    Finals: each in-scope case's latest active coder final (the COD snapshot
    MV), counted in the month it was saved; a recode counts once. Not-codeable
    marks: every ``va_coder_review`` row on an in-scope case, active or later
    lifted, in the month it was made. Tester work is left out. Elapsed time
    runs from the coder's latest coding allocation of the case made at or
    before the final (training allocations excluded) to the final's save: it
    is elapsed time, not time on screen. DORIS counts read only ``status``,
    ``result.warning``, ``result.code`` and the provenance ``code`` and
    confirmation keys, never the report.
    """
    scope = dm_grant_scope(user)
    in_scope = _scope_filter(scope)
    final, step1 = VaFinalAssessments, VaInitialAssessments
    coder_id = _snap.c.coder_final_by
    alloc = (
        sa.select(VaAllocations.va_allocation_createdat.label("allocated_at"))
        .where(
            VaAllocations.va_sid == _core.c.va_sid,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocated_to == coder_id,
            VaAllocations.va_allocation_createdat <= _snap.c.coder_final_saved_at,
            VaAllocations.va_allocation_training.is_(False),
        )
        .order_by(VaAllocations.va_allocation_createdat.desc())
        .limit(1)
        .lateral("alloc")
    )
    minutes = sa.extract("epoch", _snap.c.coder_final_saved_at - alloc.c.allocated_at) / 60.0
    low = _snap.c.smartva_likelihood1.in_(SMARTVA_LOW_LIKELIHOODS)
    smartva_match = _snap.c.coder_final_who_bucket == _snap.c.smartva_cause1_who_bucket
    unknown = _snap.c.coder_final_who_bucket_section == UNKNOWN_CAUSE_SECTION
    neonate = _demo.c.analytics_age_band == "neonate"
    coder_code = sa.func.coalesce(_snap.c.coder_final_icd, _snap.c.coder_final_icd11_stem)
    reviewer_code = sa.func.coalesce(_snap.c.reviewer_final_icd, _snap.c.reviewer_final_icd11_stem)
    reviewed = _snap.c.reviewer_final_assessment_id.is_not(None)

    def doris(row, item):
        return {
            "rejected": row.doris_result["status"].astext == "rejected",
            "warning": sa.func.coalesce(row.doris_result["result"]["warning"].astext, "") != "",
            "age_sex": row.icd11_provenance[item]["age_restriction_confirmation"].is_not(None),
            "unknown": row.icd11_provenance[item]["causing_condition_unknown"].astext == "true",
        }

    fin, ini = doris(final, "conclusive"), doris(step1, "antecedent")
    # The saved final's code differs from DORIS's underlying cause.
    doris_code = final.doris_result["result"]["code"].astext
    doris_overridden = sa.and_(
        doris_code.is_not(None),
        final.icd11_provenance["conclusive"]["code"].astext.is_distinct_from(doris_code),
    )

    def count(condition):
        return sa.func.count().filter(condition)

    month = _month(_snap.c.coder_final_saved_at)
    finals = (
        sa.select(
            coder_id.label("user_id"),
            _core.c.project_id,
            month.label("month"),
            sa.func.count().label("finals"),
            sa.func.percentile_cont(0.5).within_group(minutes).label("median_alloc_to_final_min"),
            sa.func.sum(minutes).label("alloc_to_final_min_sum"),
            sa.func.count(alloc.c.allocated_at).label("timed_finals"),
            count(minutes < FAST_FINAL_MINUTES).label("finals_under_3_min"),
            count(_snap.c.smartva_cause1_who_bucket.is_not(None)).label("smartva_compared"),
            count(smartva_match).label("smartva_match"),
            count(sa.and_(low, _snap.c.smartva_cause1_who_bucket.is_not(None))).label("smartva_low_likelihood"),
            count(sa.and_(low, smartva_match)).label("smartva_match_low_likelihood"),
            count(_snap.c.coder_final_icd == _snap.c.smartva_cause1_icd).label("exact_icd_match"),
            count(reviewed).label("reviewer_finals"),
            count(sa.and_(reviewed, reviewer_code.is_distinct_from(coder_code))).label("reviewer_changed"),
            count(unknown).label("unknown_cause"),
            count(neonate).label("neonate_finals"),
            count(sa.and_(neonate, unknown)).label("neonate_unknown_cause"),
            count(final.doris_result.is_not(None)).label("doris_checked"),
            count(sa.or_(fin["rejected"], ini["rejected"])).label("doris_rejections"),
            count(sa.or_(fin["warning"], ini["warning"])).label("doris_warnings"),
            count(sa.or_(fin["age_sex"], ini["age_sex"])).label("age_sex_confirmations"),
            count(sa.or_(fin["unknown"], ini["unknown"])).label("causing_condition_unknown"),
            count(doris_overridden).label("doris_overridden"),
            sa.literal(0).label("not_codeable"),
        )
        .select_from(
            _core.join(_demo, _demo.c.va_sid == _core.c.va_sid)
            .join(_snap, _snap.c.va_sid == _core.c.va_sid)
            .join(final, final.va_finassess_id == _snap.c.coder_final_assessment_id)
            .outerjoin(step1, sa.and_(step1.va_iniassess_id == _snap.c.coder_step1_assessment_id,
                                      step1.va_iniassess_by == coder_id))
            .outerjoin(alloc, sa.true())
        )
        .where(in_scope, coder_id.is_not(None), final.is_tester.is_(False))
        .group_by(coder_id, _core.c.project_id, month)
    )
    marks_month = _month(VaCoderReview.va_creview_createdat)
    no_time = ("median_alloc_to_final_min", "alloc_to_final_min_sum")
    filler = [
        (sa.cast(sa.null(), sa.Float) if c.name in no_time else sa.literal(0)).label(c.name)
        for c in finals.selected_columns[3:-1]
    ]
    marks = (
        sa.select(
            VaCoderReview.va_creview_by.label("user_id"),
            _core.c.project_id,
            marks_month.label("month"),
            *filler,
            sa.func.count().label("not_codeable"),
        )
        .select_from(_core.join(VaCoderReview, VaCoderReview.va_sid == _core.c.va_sid))
        .where(in_scope, VaCoderReview.is_tester.is_(False))
        .group_by(VaCoderReview.va_creview_by, _core.c.project_id, marks_month)
    )
    work = finals.union_all(marks).subquery("work")
    summed = [c for c in work.c if c.name not in ("user_id", "project_id", "month")]
    unit = _coder_units()
    names = _unit_names()
    keys = (
        work.c.project_id,
        VaUsers.user_number.label("coder_number"),
        VaUsers.name.label("coder_name"),
        unit.c.site_id.label("coder_site_id"),
        *_names(names),
        work.c.month.label("month"),
    )
    return (
        sa.select(
            *keys,
            *(sa.func.max(c).label(c.name) if c.name == "median_alloc_to_final_min"
              else sa.func.sum(c).label(c.name) for c in summed),
        )
        .select_from(
            work.join(VaUsers, VaUsers.user_id == work.c.user_id)
            .outerjoin(unit, sa.and_(unit.c.user_id == work.c.user_id,
                                     unit.c.project_id == work.c.project_id))
            .outerjoin(names, names.c.org_unit_id == unit.c.org_unit_id)
        )
        .group_by(*keys)
    )


def _coder_units():
    """Each coder's unit per project: one active coder grant, a unit grant
    before a site grant, the oldest first."""
    grant = VaUserAccessGrants
    project = sa.func.coalesce(grant.project_id, VaProjectSites.project_id, MasOrgUnit.project_id)
    # ponytail: one unit per coder and project; a coder granted several
    # units shows the first. Add a unit grain if multi-unit coders matter.
    return (
        sa.select(grant.user_id, project.label("project_id"), VaProjectSites.site_id, grant.org_unit_id)
        .distinct(grant.user_id, project)
        .select_from(grant)
        .outerjoin(VaProjectSites, VaProjectSites.project_site_id == grant.project_site_id)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == grant.org_unit_id)
        .where(grant.role == VaAccessRoles.coder, grant.grant_status == VaStatuses.active)
        .order_by(grant.user_id, project, grant.org_unit_id.is_(None), grant.grant_created_at)
        .subquery("coder_unit")
    )


_BUILDERS = {CUBE: cube_select, ORG_LEVELS: org_levels_select, STAFF: staff_select, CODER: coder_select}


def build_selects(user, names) -> list[tuple[str, sa.Select]]:
    """(name, SELECT) for each table in *names*, in ``TABLES`` order."""
    return [(name, _BUILDERS[name](user)) for name in TABLES if name in names]
