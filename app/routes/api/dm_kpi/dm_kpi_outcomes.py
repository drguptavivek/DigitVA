"""DM KPI — Outcome, Equity and Coverage (digitva-r5s0 step 2, groups f and g).

Blueprint prefix: ``/api/v1/analytics/dm-kpi/outcomes``

KPIs served (docs/policy/kpis.md):
  O-UNK    Unknown Cause Share (``by=icd``: the ICD codes inside the section)
  D-QG-09  Coder-Reviewer Disagreement Rate, at the WHO 2026 bucket
  EQ-01    Female Share Against Peers
  EQ-02    Female-Male Final Cause Gap (plus the register half)
  AD-FCOD  Final Cause Coverage
  AD-COV   Reported-Death Interview Coverage (death-register projects only)

Sources:
  - va_submission_cod_snapshot_mv (WHO 2026 buckets of each final)
  - va_final_cod_authority (``area_dashboard_service._has_final_cod``)
  - va_death_register (``area_dashboard_service._case_count_columns``)

Every count is scoped by ``DmScope.sql()``, with retired submissions and
confirmed duplicates excluded; training is excluded when the scope is
resolved (``dm_scope`` drops the training project's grants). A rate is None
when its denominator is under ``PERCENT_MIN_WHOLE``. "Authoritative final"
means an authority row naming a final (``_has_final_cod``), never the
snapshot MV's latest-active fallback, so O-UNK's base is a subset of the
``_has_final_cod`` cases (AD-FCOD also drops the not-codeable states).

Peers (EQ-01 and the D-WF-02 bottleneck): the children of the viewer's grant
roots, never a unit above the grant (``peer_units_sql``).
"""

from __future__ import annotations

import logging
from statistics import median

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import db
from app.decorators import role_required
from app.models import (
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaSubmissions,
    VaSubmissionWorkflow,
)
from app.routes.api.dm_kpi.dm_kpi_scope import DmScope, cached_kpi, dm_scope
from app.routes.api.request_helpers import error as api_error
from app.services.ai_analytics_tables import UNKNOWN_CAUSE_SECTION
from app.services.area_dashboard_service import (
    CANCELLED_CASE_STATUS,
    PERCENT_MIN_WHOLE,
    _case_count_columns,
    _has_final_cod,
    suppress_causes,
)
from app.services.duplicate_exclusion import (
    DUPLICATE_CASE_STATUS,
    not_confirmed_duplicate_condition,
    not_confirmed_duplicate_sql,
)
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql, submission_is_in_odk
from app.services.submission_analytics_mv import COD_SNAPSHOT_MV_NAME
from app.services.workflow.definition import (
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
)

bp = Blueprint("dm_kpi_outcomes", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")

#: Projects with a death register (web intake mode), the base of AD-COV and
#: the register half of EQ-02 (kpis.md, "Death-register projects only").
DEATH_REGISTER_INTAKE_MODES = ("death_register", "both")

#: AD-FCOD's base: the CODING-POOL less coder not-codeable (the codeable cases).
_NOT_CODEABLE_STATES = (
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
)

SEXES = ("female", "male", "unknown")

_snap = sa.table(
    COD_SNAPSHOT_MV_NAME,
    sa.column("va_sid"),
    sa.column("authoritative_who_bucket_section"),
    sa.column("authoritative_icd"),
    sa.column("authoritative_icd11_stem"),
    sa.column("coder_final_assessment_id"),
    sa.column("reviewer_final_assessment_id"),
    sa.column("coder_final_who_bucket"),
    sa.column("coder_final_icd"),
    sa.column("coder_final_icd11_stem"),
    sa.column("reviewer_final_who_bucket"),
    sa.column("reviewer_final_icd"),
    sa.column("reviewer_final_icd11_stem"),
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def rate(part: int, whole: int) -> float | None:
    """*part* as a percentage of *whole* to one decimal, None under ``PERCENT_MIN_WHOLE``."""
    if whole < PERCENT_MIN_WHOLE:
        return None
    return round(100 * part / whole, 1)


def sex_sql(column: str) -> str:
    """The one sex normalisation (kpis.md EQ-01): ``female``, ``male`` or
    ``unknown`` from a raw string column. *column* is a hardcoded reference."""
    return (
        f"(CASE lower(btrim({column})) WHEN 'female' THEN 'female'"
        f" WHEN 'male' THEN 'male' ELSE 'unknown' END)"
    )


def scope_clause(scope: DmScope, form: str = "va_forms", sub: str = "va_submissions"):
    """``DmScope.sql()`` as a Core clause over unaliased tables, its arrays bound."""
    sql = scope.sql(form, sub)
    return sa.text(sql).bindparams(
        **{key: value for key, value in scope.params.items() if f":{key}" in sql}
    )


def peer_units_sql() -> str:
    """SELECT of the peer units of a scope: the top units (``nlevel = 1``) of
    the projects held by project or pair grant, and the children of granted
    units in other projects (kpis.md, "Peer comparison": siblings inside the
    grant, never above it). Binds ``peer_params``. A case belongs to the
    peer whose path contains its unit's; only in-scope cases are counted.

    ponytail: two unit grants at different depths give peers at two levels;
    split per grant root if that mix occurs.
    """
    return """
        SELECT pu.org_unit_id, pu.unit_name, pu.project_id, pu.path
        FROM mas_org_unit pu
        WHERE pu.is_active
          AND ((nlevel(pu.path) = 1
                AND pu.project_id = ANY(CAST(:peer_project_ids AS text[])))
               OR (pu.parent_org_unit_id = ANY(CAST(:unit_ids AS uuid[]))
                   AND NOT pu.project_id = ANY(CAST(:peer_project_ids AS text[]))))
    """


def peer_params(scope: DmScope) -> dict:
    return {"peer_project_ids": scope.direct_project_ids, "unit_ids": scope.unit_ids}


def sibling_median(values: dict, key) -> float | None:
    """Median of every value in *values* but *key*'s (the siblings), or None."""
    others = [value for other, value in values.items() if other != key]
    return median(others) if others else None


def _scoped_submissions(*columns):
    """SELECT *columns* over the scope's submissions joined to their form."""
    return (
        sa.select(*columns)
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
    )


# ---------------------------------------------------------------------------
# O-UNK: Unknown Cause Share
# ---------------------------------------------------------------------------

def compute_ounk(scope: DmScope, period=None, by: str | None = None) -> dict:
    """O-UNK: authoritative finals in "Cause of death unknown" ÷ authoritative finals.

    The section is the WHO 2026 VA section of the final (COD snapshot MV,
    refreshed hourly). ``unmapped`` counts finals whose code has no bucket;
    they stay in the base. ``by="icd"`` returns the codes inside the section
    (R54 senility and so on), small cells folded by ``suppress_causes``.
    Cumulative, so *period* is ignored. Raises ``ValueError`` for another *by*.
    """
    if by not in (None, "icd"):
        raise ValueError(f"O-UNK has no by={by!r}")
    if not scope:
        return {"finals": 0, "unknown": 0, "unmapped": 0, "rate": None} if by is None \
            else {"by": "icd", **suppress_causes(0, [])}

    unknown = _snap.c.authoritative_who_bucket_section == UNKNOWN_CAUSE_SECTION
    where = (
        scope_clause(scope),
        submission_is_in_odk(VaSubmissions),
        not_confirmed_duplicate_condition(VaSubmissions.va_sid),
        _has_final_cod(),
    )
    if by == "icd":
        code = sa.func.coalesce(_snap.c.authoritative_icd, _snap.c.authoritative_icd11_stem)
        rows = db.session.execute(
            _scoped_submissions(code.label("code"), sa.func.count().label("n"))
            .join(_snap, _snap.c.va_sid == VaSubmissions.va_sid)
            .where(*where, unknown)
            .group_by(code)
            .order_by(sa.func.count().desc(), code)
        ).all()
        causes = [{"label": row.code or "Unspecified", "coded_count": row.n} for row in rows]
        return {"by": "icd", **suppress_causes(sum(row.n for row in rows), causes)}

    row = db.session.execute(
        _scoped_submissions(
            sa.func.count().label("finals"),
            sa.func.count().filter(unknown).label("unknown"),
            sa.func.count().filter(_snap.c.authoritative_who_bucket_section.is_(None)).label("unmapped"),
        )
        .join(_snap, _snap.c.va_sid == VaSubmissions.va_sid)
        .where(*where)
    ).one()
    return {
        "finals": row.finals,
        "unknown": row.unknown,
        "unmapped": row.unmapped,
        "rate": rate(row.unknown, row.finals),
    }


# ---------------------------------------------------------------------------
# D-QG-09: Coder-Reviewer Disagreement Rate
# ---------------------------------------------------------------------------

def compute_dqg09(scope: DmScope, period=None, by: str | None = None) -> dict:
    """D-QG-09: cases with an active coder and reviewer final whose WHO 2026
    bucket differs ÷ cases with both.

    Where a final has no bucket its code is compared instead: the ICD-10 code,
    else the ICD-11 primary stem (so a post-coordinated code compares by its
    stem). From the COD snapshot MV, refreshed hourly, so the rate can lag a
    recent finalization. Cumulative, so *period* is ignored.
    """
    if by is not None:
        raise ValueError(f"D-QG-09 has no by={by!r}")
    if not scope:
        return {"reviewed": 0, "disagreements": 0, "rate": None}
    coder = sa.func.coalesce(
        _snap.c.coder_final_who_bucket, _snap.c.coder_final_icd, _snap.c.coder_final_icd11_stem
    )
    reviewer = sa.func.coalesce(
        _snap.c.reviewer_final_who_bucket, _snap.c.reviewer_final_icd, _snap.c.reviewer_final_icd11_stem
    )
    row = db.session.execute(
        _scoped_submissions(
            sa.func.count().label("reviewed"),
            sa.func.count().filter(coder.is_distinct_from(reviewer)).label("disagreements"),
        )
        .join(_snap, _snap.c.va_sid == VaSubmissions.va_sid)
        .where(
            scope_clause(scope),
            submission_is_in_odk(VaSubmissions),
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
            _snap.c.coder_final_assessment_id.is_not(None),
            _snap.c.reviewer_final_assessment_id.is_not(None),
        )
    ).one()
    return {
        "reviewed": row.reviewed,
        "disagreements": row.disagreements,
        "rate": rate(row.disagreements, row.reviewed),
    }


# ---------------------------------------------------------------------------
# EQ-01: Female Share Against Peers
# ---------------------------------------------------------------------------

def compute_eq01(scope: DmScope, period=None, by: str | None = None) -> dict:
    """EQ-01: female ÷ (female + male) over ALL-SYNCED, per peer unit, against
    the median of its siblings, in percentage points.

    Unknown sex (anything but female or male after ``sex_sql``) is left out of
    the share and counted as ``unknown``. A peer with fewer than 20 known
    cases has counts only; the sibling median is over the other peers with a
    share. One query. Cumulative, so *period* is ignored; the rows are the
    peers, so *by* may be None or ``"unit"``.
    """
    if by not in (None, "unit"):
        raise ValueError(f"EQ-01 has no by={by!r}")
    empty = {"female": 0, "male": 0, "unknown": 0, "share": None, "units": []}
    if not scope:
        return empty
    sex = sex_sql("s.va_deceased_gender")
    rows = db.session.execute(
        sa.text(f"""
            WITH peers AS ({peer_units_sql()})
            SELECT GROUPING(pu.org_unit_id) = 1 AS total_row,
                   CAST(pu.org_unit_id AS text) AS unit_id,
                   pu.unit_name,
                   {sex} AS sex,
                   COUNT(*) AS n
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            LEFT JOIN mas_org_unit su ON su.org_unit_id = s.org_unit_id
            LEFT JOIN peers pu ON pu.project_id = su.project_id AND su.path <@ pu.path
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
            GROUP BY GROUPING SETS (({sex}), (pu.org_unit_id, pu.unit_name, {sex}))
        """),
        {**IN_ODK_BIND, **scope.params, **peer_params(scope)},
    ).mappings().all()

    total = dict.fromkeys(SEXES, 0)
    units: dict[str, dict] = {}
    for r in rows:
        if r["total_row"]:
            total[r["sex"]] = r["n"]
        elif r["unit_id"] is not None:
            unit = units.setdefault(
                r["unit_id"], {"unit_id": r["unit_id"], "unit_name": r["unit_name"], **dict.fromkeys(SEXES, 0)}
            )
            unit[r["sex"]] = r["n"]

    shares = {}
    for unit in units.values():
        unit["share"] = rate(unit["female"], unit["female"] + unit["male"])
        if unit["share"] is not None:
            shares[unit["unit_id"]] = unit["share"]
    for unit in units.values():
        peer = sibling_median(shares, unit["unit_id"]) if unit["share"] is not None else None
        unit["peer_median"] = peer
        unit["gap_pp"] = None if peer is None else round(unit["share"] - peer, 1)
    return {
        **total,
        "share": rate(total["female"], total["female"] + total["male"]),
        "units": sorted(units.values(), key=lambda u: (u["gap_pp"] is None, u["gap_pp"] or 0, u["unit_name"])),
    }


# ---------------------------------------------------------------------------
# AD-FCOD: Final Cause Coverage (and the final-cause half of EQ-02)
# ---------------------------------------------------------------------------

def _final_cause_counts(scope: DmScope, *, by_sex: bool) -> list:
    """(sex?, codeable, final) over the scope: the codeable cases (CODING-POOL
    less coder not-codeable) and those with an authoritative final cause."""
    sex = sa.literal_column(sex_sql("va_submissions.va_deceased_gender"))
    group = (sex.label("sex"),) if by_sex else ()
    stmt = (
        _scoped_submissions(
            *group,
            sa.func.count().label("codeable"),
            sa.func.count().filter(_has_final_cod()).label("final"),
        )
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(
            scope_clause(scope),
            submission_is_in_odk(VaSubmissions),
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
            VaSubmissionWorkflow.workflow_state.not_in(_NOT_CODEABLE_STATES),
        )
    )
    if by_sex:
        stmt = stmt.group_by(sex)
    return db.session.execute(stmt).all()


def compute_adfcod(scope: DmScope, period=None, by: str | None = None) -> dict:
    """AD-FCOD: codeable cases with an authoritative final cause ÷ codeable
    cases. ``by="sex"`` adds ``rows`` per normalised sex (EQ-02's base).
    Snapshot, so *period* is ignored."""
    if by not in (None, "sex"):
        raise ValueError(f"AD-FCOD has no by={by!r}")
    if not scope:
        return {"codeable": 0, "final": 0, "rate": None}
    if by == "sex":
        rows = {r.sex: r for r in _final_cause_counts(scope, by_sex=True)}
        out = [
            {"sex": sex, "codeable": rows[sex].codeable if sex in rows else 0,
             "final": rows[sex].final if sex in rows else 0}
            for sex in SEXES
        ]
        for row in out:
            row["rate"] = rate(row["final"], row["codeable"])
        codeable = sum(r["codeable"] for r in out)
        final = sum(r["final"] for r in out)
        return {"codeable": codeable, "final": final, "rate": rate(final, codeable), "by": "sex", "rows": out}
    row = _final_cause_counts(scope, by_sex=False)[0]
    return {"codeable": row.codeable, "final": row.final, "rate": rate(row.final, row.codeable)}


# ---------------------------------------------------------------------------
# AD-COV: Reported-Death Interview Coverage (and the register half of EQ-02)
# ---------------------------------------------------------------------------

def _register_project_ids(scope: DmScope) -> list[str]:
    """The scope's projects that keep a death register."""
    if not scope.all_project_ids:
        return []
    return list(db.session.scalars(
        sa.select(VaProjectMaster.project_id).where(
            VaProjectMaster.project_id.in_(scope.all_project_ids),
            VaProjectMaster.web_intake_mode.in_(DEATH_REGISTER_INTAKE_MODES),
        ).order_by(VaProjectMaster.project_id)
    ))


def _register_counts(scope: DmScope, project_ids: list[str], *, by_sex: bool) -> list:
    """Reported deaths of *project_ids* in the scope (confirmed duplicates and
    cancelled cases out), with ``_case_count_columns`` and ``interviewed``
    (a linked submission), optionally per normalised ``deceased_sex``."""
    sex = sa.literal_column(sex_sql("va_death_register.deceased_sex"))
    group = (sex.label("sex"),) if by_sex else ()
    stmt = sa.select(
        *group,
        *_case_count_columns(None),
        sa.func.count().filter(VaDeathRegister.va_sid.is_not(None)).label("interviewed"),
    ).where(
        VaDeathRegister.project_id.in_(project_ids),
        VaDeathRegister.status.not_in([DUPLICATE_CASE_STATUS, CANCELLED_CASE_STATUS]),
        scope_clause(scope, "va_death_register", "va_death_register"),
    )
    if by_sex:
        stmt = stmt.group_by(sex)
    return db.session.execute(stmt).all()


def compute_adcov(scope: DmScope, period=None, by: str | None = None) -> dict:
    """AD-COV: reported deaths with an interview ÷ reported deaths, and the
    blocker count waiting over 30 days with its share of reported deaths.

    Death-register projects only: ``applicable`` is False, with no figures,
    when the scope holds none (an ODK-only scope). Snapshot, so *period* is
    ignored.
    """
    if by is not None:
        raise ValueError(f"AD-COV has no by={by!r}")
    project_ids = _register_project_ids(scope) if scope else []
    if not project_ids:
        return {"applicable": False}
    row = _register_counts(scope, project_ids, by_sex=False)[0]
    return {
        "applicable": True,
        "project_ids": project_ids,
        "deaths_reported": row.deaths_reported,
        "interviewed": row.interviewed,
        "rate": rate(row.interviewed, row.deaths_reported),
        "interviews_pending": row.interviews_pending,
        "pending_over_30_days": row.pending_over_30_days,
        "pending_over_30_days_rate": rate(row.pending_over_30_days, row.deaths_reported),
    }


# ---------------------------------------------------------------------------
# EQ-02: Female-Male Final Cause Gap
# ---------------------------------------------------------------------------

def _gap(rows: list[dict]) -> float | None:
    by_sex = {r["sex"]: r["rate"] for r in rows}
    if by_sex.get("female") is None or by_sex.get("male") is None:
        return None
    return round(by_sex["female"] - by_sex["male"], 1)


def compute_eq02(scope: DmScope, period=None, by: str | None = None) -> dict:
    """EQ-02: AD-FCOD for female cases minus AD-FCOD for male cases, in
    percentage points; unknown sex is counted but left out of the gap. Each
    sex needs a base of 20, else its rate and the gap are None.

    ``register``: for death-register projects, interviewed ÷ reported by
    ``deceased_sex``, female minus male; None for an ODK-only scope.
    Cumulative, so *period* is ignored.
    """
    if by is not None:
        raise ValueError(f"EQ-02 has no by={by!r}")
    final_rows = compute_adfcod(scope, by="sex").get("rows") or [
        {"sex": sex, "codeable": 0, "final": 0, "rate": None} for sex in SEXES
    ]
    project_ids = _register_project_ids(scope) if scope else []
    register = None
    if project_ids:
        counts = {r.sex: r for r in _register_counts(scope, project_ids, by_sex=True)}
        register_rows = []
        for sex in SEXES:
            reported = counts[sex].deaths_reported if sex in counts else 0
            interviewed = counts[sex].interviewed if sex in counts else 0
            register_rows.append({
                "sex": sex, "reported": reported, "interviewed": interviewed,
                "rate": rate(interviewed, reported),
            })
        register = {"rows": register_rows, "gap_pp": _gap(register_rows)}
    return {"rows": final_rows, "gap_pp": _gap(final_rows), "register": register}


# ---------------------------------------------------------------------------
# Routes (thin wrappers; each KPI is its compute function)
# ---------------------------------------------------------------------------

def _serve(kpi_id: str, compute_fn):
    scope = dm_scope()
    by = request.args.get("by") or None
    try:
        return jsonify(cached_kpi(f"outcomes:{kpi_id}", lambda: compute_fn(scope, None, by)))
    except ValueError:
        return api_error(f"Unsupported 'by' for {kpi_id}.", "invalid_request", 400)


@bp.get("/unknown-cause")
@role_required("data_manager", "admin")
def unknown_cause():
    """KPI: O-UNK (``?by=icd`` for the codes inside the section)."""
    return _serve("O-UNK", compute_ounk)


@bp.get("/disagreement")
@role_required("data_manager", "admin")
def disagreement():
    """KPI: D-QG-09 at the WHO 2026 bucket."""
    return _serve("D-QG-09", compute_dqg09)


@bp.get("/female-share")
@role_required("data_manager", "admin")
def female_share():
    """KPI: EQ-01, per peer unit."""
    return _serve("EQ-01", compute_eq01)


@bp.get("/female-final-gap")
@role_required("data_manager", "admin")
def female_final_gap():
    """KPI: EQ-02."""
    return _serve("EQ-02", compute_eq02)


@bp.get("/final-cause-coverage")
@role_required("data_manager", "admin")
def final_cause_coverage():
    """KPI: AD-FCOD (``?by=sex``)."""
    return _serve("AD-FCOD", compute_adfcod)


@bp.get("/register-coverage")
@role_required("data_manager", "admin")
def register_coverage():
    """KPI: AD-COV; ``applicable: false`` outside death-register projects."""
    return _serve("AD-COV", compute_adcov)
