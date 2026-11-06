"""Aggregate counts for the public home page (docs/policy/public-home-stats.md).

Only projects with ``home_kpis_included`` are counted. The training project
and demo/training projects are always left out, whatever the flag says. Reads the analytics
materialized views (refreshed hourly) and caches the result for an hour, so
the home page never scans submission tables. Categories with fewer than
``MIN_CELL`` deaths are folded into "Other or unknown". No cause-of-death
distribution is shown.
"""

import sqlalchemy as sa
from flask import current_app

from app import cache, db
from app.services.duplicate_exclusion import not_confirmed_duplicate_condition, not_confirmed_duplicate_sql
from app.services.submission_analytics_mv import CORE_MV_NAME, DEMOGRAPHICS_MV_NAME

MIN_CELL = 5
CACHE_SECONDS = 3600
AGE_BANDS = [
    ("neonate", "Under 28 days"),
    ("child", "28 days to 14 years"),
    ("15_49y", "15–49 years"),
    ("50_64y", "50–64 years"),
    ("65_plus", "65 years and over"),
]
SEXES = [("female", "Female"), ("male", "Male")]
OTHER = "Other or unknown"


def _rows(counts: dict, order: list[tuple[str, str]] | None, total: int) -> list[dict]:
    """Label, n and percent per category; small or unlisted cells go to OTHER."""
    rows, other = [], 0
    keys = order or sorted(((k, (k or "").title()) for k in counts), key=lambda kv: -counts[kv[0]])
    known = {k for k, _ in keys}
    for key, label in keys:
        n = counts.get(key, 0)
        if key in (None, "", "unknown") or n < MIN_CELL:
            other += n
        elif n:
            rows.append({"label": label, "n": n})
    other += sum(n for k, n in counts.items() if k not in known)
    if other:
        rows.append({"label": OTHER, "n": other})
    for r in rows:
        r["pct"] = round(100 * r["n"] / total, 1) if total else 0
    return rows


def _compute(projects: list[str]) -> dict | None:
    core = sa.table(CORE_MV_NAME, sa.column("va_sid"), sa.column("project_id"))
    demo = sa.table(
        DEMOGRAPHICS_MV_NAME, sa.column("va_sid"), sa.column("va_narration_language"),
        sa.column("sex"), sa.column("analytics_age_band"), sa.column("has_smartva"),
        sa.column("has_human_final_cod"),
    )
    base = sa.select().select_from(core.join(demo, demo.c.va_sid == core.c.va_sid)).where(
        core.c.project_id.in_(projects),
        not_confirmed_duplicate_condition(core.c.va_sid),
    )

    def grouped(col):
        q = base.add_columns(col, sa.func.count()).group_by(col)
        return {k: n for k, n in db.session.execute(q).all()}

    total, smartva, coded = db.session.execute(
        base.add_columns(
            sa.func.count(),
            sa.func.count().filter(demo.c.has_smartva.is_(True)),
            sa.func.count().filter(demo.c.has_human_final_cod.is_(True)),
        )
    ).one()
    if not total:
        return None
    coders = db.session.execute(
        sa.text(
            "SELECT count(DISTINCT fa.va_finassess_by) FROM va_final_assessments fa "
            f"JOIN {CORE_MV_NAME} c ON c.va_sid = fa.va_sid "  # fixed constant
            "WHERE fa.va_finassess_status = 'active' AND NOT fa.is_tester "
            "AND fa.demo_expires_at IS NULL AND c.project_id = ANY(:projects) "
            f"AND {not_confirmed_duplicate_sql('fa.va_sid')}"
        ),
        {"projects": projects},
    ).scalar()
    languages = grouped(demo.c.va_narration_language)
    return {
        "interviews": total,
        "coded": coded,
        "coders": coders,
        "smartva": smartva,
        "smartva_pct": round(100 * smartva / total, 1),
        "language_count": sum(1 for k, n in languages.items() if k not in (None, "", "unknown") and n),
        "languages": _rows(languages, None, total),
        "ages": _rows(grouped(demo.c.analytics_age_band), AGE_BANDS, total),
        "sexes": _rows(grouped(demo.c.sex), SEXES, total),
    }


def included_projects() -> list[str]:
    from app.models import VaProjectMaster

    training_id = current_app.config.get("DIGITVA_TRAINING_PROJECT_ID") or None
    q = sa.select(VaProjectMaster.project_id).where(
        VaProjectMaster.home_kpis_included.is_(True),
        VaProjectMaster.demo_training_enabled.is_(False),
        VaProjectMaster.synthetic_demo_reset_enabled.is_(False),
    )
    if training_id:
        q = q.where(VaProjectMaster.project_id != training_id)
    return sorted(db.session.scalars(q))


def public_home_stats() -> dict | None:
    """The cached counts, or None when no project is included or none has data."""
    projects = included_projects()
    if not projects:
        return None
    key = "public-home-stats:" + ",".join(projects)
    stats = cache.get(key)
    if stats is None:
        stats = _compute(projects) or {}
        cache.set(key, stats, timeout=CACHE_SECONDS)
    return stats or None
