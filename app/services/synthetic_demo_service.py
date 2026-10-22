"""Explicitly opted-in synthetic organization demo and recoverable weekly reset."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.orm import Session

from app import db
from app.models import (
    MapProjectOdk,
    MapProjectSiteOdk,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaDbBackup,
    VaDeathRegister,
    VaDemoResetRun,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaInitialAssessments,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaSiteMaster,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.services.db_backup_service import create_db_backup
from app.services import register_pii_accessor
from app.services.user_account_service import creation_other
from app.services.submission_payload_version_service import write_payload_version

log = logging.getLogger(__name__)
DEMO_PROJECT_ID = "DEMO01"
DEMO_ACCOUNTS = (
    ("interviewer", "demo.interviewer@digitva.com", "SN", "/app/collection"),
    ("coder", "demo.coder@digitva.com", "MO", "/app/coding"),
    ("reviewer", "demo.reviewer@digitva.com", "MO", "/reviewing/"),
    ("data_manager", "demo.dm@digitva.com", "DPM", "/data-management/dashboard"),
)
# Child first, including every known inbound operational FK. Objects stay in storage.
DELETE_TABLES = (
    "va_web_intake_attachments",
    "va_web_intake_draft_sections",
    "va_web_intake_drafts",
    "map_case_contact_attempts",
    "map_case_transitions",
    "map_death_identifier",
    "va_bundle_pending_coding",
    "map_bundle_records",
    "va_consent_record_purposes",
    "va_consent_records",
    "va_death_register",
    "va_final_cod_authority",
    "va_submission_notifications",
    "va_submission_upstream_changes",
    "va_coding_episodes",
    "va_reviewer_final_assessments",
    "va_final_assessments",
    "va_reviewer_initial_assessments",
    "va_initial_assessments",
    "va_reviewer_review",
    "va_narrative_assessments",
    "va_social_autopsy_analysis_options",
    "va_social_autopsy_analyses",
    "va_smartva_run_outputs",
    "va_smartva_results",
    "va_smartva_runs",
    "va_allocations",
    "va_coder_review",
    "va_data_manager_review",
    "va_usernotes",
    "va_submission_attachments",
    "va_submission_workflow_events",
    "va_submission_workflow",
    # Training sessions (TRN01) reference submissions; DEMO01 owns none, so
    # this deletes nothing, but the dependency check must know the table.
    "map_training_cases",
    "va_submissions_auditlog",
    "va_smartva_form_runs",
    "va_daily_kpi_aggregates",
    "map_payload_version_pii",
    "va_submission_payload_versions",
    "va_submissions",
)


class SyntheticDemoError(ValueError):
    """A fixed, safe error code explaining why no reset can proceed."""


def get_demo_metadata() -> dict:
    """Return non-secret guide metadata; enabled needs exact config and database opt-in."""
    configured = current_app.config.get("DIGITVA_WEEKLY_DEMO_PROJECT_ID") == DEMO_PROJECT_ID
    project = db.session.get(VaProjectMaster, DEMO_PROJECT_ID) if configured else None
    return {
        "configured": configured,
        "enabled": bool(project and project.synthetic_demo_reset_enabled),
        "project_id": DEMO_PROJECT_ID,
        "accounts": [
            dict(role=role, email=email, landing_path=path)
            for role, email, _cadre, path in DEMO_ACCOUNTS
        ],
    }


def _require_target(session):
    """Validate the exact opt-in and forbid ODK or short-retention demo targets."""
    if current_app.config.get("DIGITVA_WEEKLY_DEMO_PROJECT_ID") != DEMO_PROJECT_ID:
        raise SyntheticDemoError("target_not_configured")
    project = session.get(VaProjectMaster, DEMO_PROJECT_ID)
    if not project or not project.synthetic_demo_reset_enabled:
        raise SyntheticDemoError("target_not_opted_in")
    if (
        project.project_structure_mode != "organization"
        or project.demo_training_enabled
        or project.project_status != VaStatuses.active
    ):
        raise SyntheticDemoError("invalid_target")
    for model in (MapProjectOdk, MapProjectSiteOdk):
        if session.scalar(
            sa.select(model.project_id).where(model.project_id == DEMO_PROJECT_ID).limit(1)
        ):
            raise SyntheticDemoError("odk_mapping_present")
    if session.scalar(
        sa.select(VaForms.form_id)
        .where(VaForms.project_id == DEMO_PROJECT_ID, VaForms.form_source != "web")
        .limit(1)
    ):
        raise SyntheticDemoError("odk_form_present")
    return project


def _scope_predicates():
    """Build fixed SQL predicates; no row IDs or clinical payloads enter Python."""
    tables = db.metadata.tables
    forms = sa.select(VaForms.form_id).where(VaForms.project_id == DEMO_PROJECT_ID)
    sids = sa.select(VaSubmissions.va_sid).where(VaSubmissions.va_form_id.in_(forms))
    deaths = sa.select(VaDeathRegister.death_id).where(
        VaDeathRegister.project_id == DEMO_PROJECT_ID
    )
    drafts = sa.select(tables["va_web_intake_drafts"].c.draft_id).where(
        tables["va_web_intake_drafts"].c.project_id == DEMO_PROJECT_ID
    )
    site_ids = sa.select(VaProjectSites.site_id).where(VaProjectSites.project_id == DEMO_PROJECT_ID)
    predicates = {}
    for name in DELETE_TABLES:
        table = tables[name]
        if name == "va_submissions":
            predicate = table.c.va_form_id.in_(forms)
        elif name in {
            "va_death_register",
            "va_web_intake_drafts",
            "va_smartva_form_runs",
        }:
            predicate = table.c.project_id == DEMO_PROJECT_ID
        elif name == "va_daily_kpi_aggregates":
            predicate = sa.and_(
                table.c.project_id == DEMO_PROJECT_ID, table.c.site_id.in_(site_ids)
            )
        elif "va_sid" in table.c:
            predicate = table.c.va_sid.in_(sids)
        elif "death_id" in table.c:
            predicate = table.c.death_id.in_(deaths)
        elif "draft_id" in table.c:
            predicate = table.c.draft_id.in_(drafts)
        elif name == "va_usernotes":
            predicate = table.c.note_vasubmission.in_(sids)
        elif name == "va_social_autopsy_analysis_options":
            parent = tables["va_social_autopsy_analyses"]
            predicate = table.c.va_saa_id.in_(
                sa.select(parent.c.va_saa_id).where(parent.c.va_sid.in_(sids))
            )
        elif name == "va_consent_record_purposes":
            parent = tables["va_consent_records"]
            predicate = table.c.consent_id.in_(
                sa.select(parent.c.consent_id).where(parent.c.death_id.in_(deaths))
            )
        elif name == "va_smartva_run_outputs":
            parent = tables["va_smartva_runs"]
            predicate = table.c.va_smartva_run_id.in_(
                sa.select(parent.c.va_smartva_run_id).where(parent.c.va_sid.in_(sids))
            )
        else:
            raise SyntheticDemoError("unknown_scope")
        predicates[name] = predicate
    return predicates


def _check_dependencies(connection):
    """Refuse newly added inbound tables instead of relying on FK cascades."""
    unknown = connection.scalar(
        sa.text("""
        SELECT 1
        FROM pg_constraint c
        JOIN pg_class parent ON parent.oid = c.confrelid
        JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
        JOIN pg_class child ON child.oid = c.conrelid
        JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
        WHERE c.contype = 'f' AND parent_ns.nspname = 'public'
          AND parent.relname = ANY(:expected)
          AND (child_ns.nspname <> 'public' OR NOT (child.relname = ANY(:expected)))
        LIMIT 1
    """),
        {"expected": list(DELETE_TABLES)},
    )
    if unknown:
        raise SyntheticDemoError("unknown_dependency")
    known = {
        (
            table.name,
            tuple(element.parent.name for element in fk.elements),
            fk.referred_table.name,
            tuple(element.column.name for element in fk.elements),
            (fk.ondelete or "NO ACTION").upper(),
        )
        for table in db.metadata.tables.values()
        for fk in table.foreign_key_constraints
        if fk.referred_table.name in DELETE_TABLES
    }
    actual = sa.inspect(connection).get_multi_foreign_keys(schema="public")
    for (_schema, name), constraints in actual.items():
        for fk in constraints:
            if fk["referred_table"] not in DELETE_TABLES:
                continue
            signature = (
                name,
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                tuple(fk["referred_columns"]),
                (fk.get("options", {}).get("ondelete") or "NO ACTION").upper(),
            )
            if signature not in known:
                raise SyntheticDemoError("unknown_dependency")


def _check_cross_project_links(session, predicates):
    """Refuse cross-project links that FK SET NULL or CASCADE could otherwise alter."""
    queries = []
    for name in DELETE_TABLES:
        table = db.metadata.tables[name]
        for fk in table.foreign_keys:
            parent = fk.column.table
            if parent.name not in predicates:
                continue
            target = sa.select(fk.column).where(predicates[parent.name])
            queries.append(
                sa.select(sa.literal(1))
                .select_from(table)
                .where(fk.parent.in_(target), predicates[name].is_not(True))
            )
    if queries and session.scalar(sa.union_all(*queries).limit(1)):
        raise SyntheticDemoError("cross_project_dependency")


def _lock_rows(session, predicates):
    """Drain demo writes and block new FK children through backup and reset.

    FOR UPDATE conflicts with FK KEY SHARE. Preserve locked parent rows and
    use one dedicated transaction; the backup service commits its own session.
    """
    session.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    for model in (VaProjectMaster, VaResearchProjects, VaForms):
        table = model.__table__
        result = session.execute(
            sa.select(*table.primary_key.columns)
            .where(table.c.project_id == DEMO_PROJECT_ID)
            .order_by(*table.primary_key.columns)
            .with_for_update(),
            execution_options={"yield_per": 500},
        )
        for _partition in result.partitions(500):
            pass
        result.close()
    site_ids = sa.select(VaProjectSites.site_id).where(VaProjectSites.project_id == DEMO_PROJECT_ID)
    session.execute(
        sa.select(VaSiteMaster.site_id)
        .where(VaSiteMaster.site_id.in_(site_ids))
        .order_by(VaSiteMaster.site_id)
        .with_for_update()
    ).all()
    for name in reversed(DELETE_TABLES):
        table = db.metadata.tables[name]
        result = session.execute(
            sa.select(*table.primary_key.columns)
            .where(predicates[name])
            .order_by(*table.primary_key.columns)
            .with_for_update(),
            execution_options={"yield_per": 500},
        )
        for _partition in result.partitions(500):
            pass
        result.close()


def _scheduled_week(now):
    """Most recent Sunday 23:00 India time; naive timestamps are refused."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise SyntheticDemoError("naive_timestamp")
    local = now.astimezone(ZoneInfo("Asia/Kolkata"))
    sunday = (local - timedelta(days=(local.weekday() + 1) % 7)).replace(
        hour=23, minute=0, second=0, microsecond=0
    )
    if local < sunday:
        sunday -= timedelta(days=7)
    return sunday.astimezone(UTC)


def reset_weekly_demo(now=None, dry_run=False) -> dict:
    """Back up, delete and restore synthetic cases atomically once per scheduled week.

    Only the designated opt-in project is eligible. Failures roll back all
    operational changes, retain stored objects and record a short audit code.
    """
    week = _scheduled_week(now)
    result = dict(status="skipped", project_id=DEMO_PROJECT_ID, week=week.isoformat(), counts={})
    try:
        _require_target(db.session)
    except SyntheticDemoError as exc:
        return dict(result, error_code=str(exc))
    db.session.commit()
    run_id = None
    backup = None
    with db.engine.connect() as connection:
        locked = connection.scalar(sa.text("SELECT pg_try_advisory_lock(184721, 1001)"))
        connection.commit()
        if not locked:
            return dict(result, status="busy")
        try:
            previous = db.session.scalar(
                sa.select(VaDemoResetRun).where(
                    VaDemoResetRun.project_id == DEMO_PROJECT_ID,
                    VaDemoResetRun.scheduled_week == week,
                )
            )
            if previous and previous.status == "success":
                return dict(result, status="already_reset", backup_id=str(previous.backup_id))
            if not dry_run:
                run = previous or VaDemoResetRun(project_id=DEMO_PROJECT_ID, scheduled_week=week)
                run.status, run.error_code = "running", None
                run.backup_id = run.backup_key = run.backup_size_bytes = run.backup_sha256 = None
                run.counts = {}
                run.started_at, run.completed_at = datetime.now(UTC), None
                db.session.add(run)
                db.session.commit()
                run_id = run.reset_run_id
            db.session.commit()
            with connection.begin(), Session(bind=connection) as session:
                predicates = _scope_predicates()
                _check_dependencies(connection)
                _lock_rows(session, predicates)
                _require_target(session)
                _check_cross_project_links(session, predicates)
                counts = {
                    name: session.scalar(
                        sa.select(sa.func.count())
                        .select_from(db.metadata.tables[name])
                        .where(predicates[name])
                    )
                    for name in DELETE_TABLES
                }
                if dry_run:
                    return dict(result, status="dry_run", counts=counts)
                backup = create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)
                if not (
                    backup.ok
                    and backup.backup_id
                    and backup.object_key
                    and backup.size_bytes > 0
                    and backup.sha256
                    and len(backup.sha256) == 64
                ):
                    raise SyntheticDemoError("backup_failed")
                run = session.get(VaDemoResetRun, run_id)
                run.backup_id = uuid.UUID(str(backup.backup_id))
                run.backup_key, run.backup_size_bytes = backup.object_key, backup.size_bytes
                run.backup_sha256 = backup.sha256
                # Break the two intentional FK cycles before ordered child deletes.
                session.execute(
                    sa.update(VaSubmissions)
                    .where(predicates["va_submissions"])
                    .values(active_payload_version_id=None)
                )
                session.execute(
                    sa.update(VaDeathRegister)
                    .where(predicates["va_death_register"])
                    .values(duplicate_of_death_id=None)
                )
                for name in DELETE_TABLES:
                    session.execute(sa.delete(db.metadata.tables[name]).where(predicates[name]))
                _seed_cases(session)
                run.status, run.counts = "success", counts
                run.completed_at = datetime.now(UTC)
                session.flush()
                return dict(result, status="success", counts=counts, backup_id=backup.backup_id)
        except Exception as exc:
            connection.rollback()
            code = str(exc) if isinstance(exc, SyntheticDemoError) else "reset_failed"
            db.session.rollback()
            if run_id:
                run = db.session.get(VaDemoResetRun, run_id)
                run.status, run.error_code = "failed", code
                if backup and db.session.get(VaDbBackup, uuid.UUID(str(backup.backup_id))):
                    run.backup_id = uuid.UUID(str(backup.backup_id))
                    run.backup_key = backup.object_key
                    run.backup_size_bytes = backup.size_bytes
                    run.backup_sha256 = backup.sha256
                run.completed_at = datetime.now(UTC)
                db.session.commit()
            log.warning("Synthetic demo reset refused: %s", code)
            return dict(result, status="failed", error_code=code)
        finally:
            connection.rollback()
            connection.execute(sa.text("SELECT pg_advisory_unlock(184721, 1001)"))
            connection.commit()


def seed_organization_demo() -> dict:
    """Create a fresh demo only with explicit config and dev/test-seed safeguards.

    DIGITVA_DEMO_PASSWORD supplies synthetic account credentials. Existing
    projects/accounts are never adopted, repaired or given new passwords.
    """
    from app.services import organization_service as org

    if current_app.config.get("DIGITVA_WEEKLY_DEMO_PROJECT_ID") != DEMO_PROJECT_ID:
        raise SyntheticDemoError("target_not_configured")
    if not (
        current_app.debug or current_app.testing or os.environ.get("DIGITVA_ALLOW_TEST_SEED") == "1"
    ):
        raise SyntheticDemoError("test_seed_not_allowed")
    if db.session.get(VaProjectMaster, DEMO_PROJECT_ID):
        _require_target(db.session)
        return get_demo_metadata()
    password = os.environ.get("DIGITVA_DEMO_PASSWORD", "")
    if len(password) < 12:
        raise SyntheticDemoError("demo_password_required")
    emails = [email for _role, email, _cadre, _path in DEMO_ACCOUNTS]
    if db.session.scalar(sa.select(VaUsers.user_id).where(VaUsers.email.in_(emails)).limit(1)):
        raise SyntheticDemoError("demo_account_collision")
    if db.session.get(VaResearchProjects, DEMO_PROJECT_ID):
        raise SyntheticDemoError("demo_project_collision")
    try:
        project = VaProjectMaster(
            project_id=DEMO_PROJECT_ID,
            project_code=DEMO_PROJECT_ID,
            project_name="Synthetic organization demonstration",
            project_nickname="Synthetic demo",
            project_structure_mode="organization",
            web_intake_mode="both",
            coding_intake_mode="pick_and_choose",
            synthetic_demo_reset_enabled=True,
            masked_cod_required=False,
            narrative_qa_enabled=False,
            social_autopsy_enabled=False,
            reviewer_social_autopsy_enabled=False,
        )
        db.session.add(project)
        db.session.flush()
        org.ensure_organization_site(DEMO_PROJECT_ID)
        org.seed_default_organization(DEMO_PROJECT_ID)
        level = next(
            level for level in org.list_levels(DEMO_PROJECT_ID) if level.level_code == "district"
        )
        unit = org.create_unit(
            DEMO_PROJECT_ID,
            org_level_id=level.org_level_id,
            unit_code="DEMODH",
            unit_name="Synthetic District Hospital",
        )
        cadres = {cadre.cadre_code: cadre for cadre in org.list_cadres(DEMO_PROJECT_ID)}
        for role, email, cadre, _path in DEMO_ACCOUNTS:
            user = VaUsers(
                name="Demo " + role.replace("_", " "),
                email=email,
                vacode_language=["english"],
                permission={},
                landing_page=role,
                email_verified=True,
                pw_reset_t_and_c=True,
                year_of_birth=1985,
                sex="undetermined",
                job_title="Synthetic demo " + role,
                other=creation_other(
                    "system", extra={"synthetic_demo_project": DEMO_PROJECT_ID}),
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            org.create_worker(
                DEMO_PROJECT_ID,
                org_unit_id=unit.org_unit_id,
                cadre_id=cadres[cadre].cadre_id,
                worker_name=user.name,
                worker_code="DEMO_" + role.upper(),
                user=email,
            )
            db.session.add(
                VaUserAccessGrants(
                    user_id=user.user_id,
                    role=VaAccessRoles(role),
                    scope_type=VaAccessScopeTypes.org_unit,
                    org_unit_id=unit.org_unit_id,
                    cadre_id=cadres[cadre].cadre_id,
                    grant_status=VaStatuses.active,
                )
            )
        db.session.flush()
        _seed_cases(db.session)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return get_demo_metadata()


def _seed_cases(session):
    """Restore four synthetic stages without changing any preserved identity/configuration."""
    form = session.scalar(
        sa.select(VaForms)
        .where(VaForms.project_id == DEMO_PROJECT_ID, VaForms.form_source == "web")
        .order_by(VaForms.form_id)
        .limit(1)
    )
    unit = session.scalar(
        sa.select(MasOrgUnit)
        .where(MasOrgUnit.project_id == DEMO_PROJECT_ID, MasOrgUnit.unit_code == "DEMODH")
        .limit(1)
    )
    accounts = {
        user.email: user
        for user in session.scalars(
            sa.select(VaUsers).where(
                VaUsers.email.in_([email for _role, email, _cadre, _path in DEMO_ACCOUNTS])
            )
        )
    }
    if not form or not unit or len(accounts) != len(DEMO_ACCOUNTS):
        raise SyntheticDemoError("baseline_configuration_missing")
    if any(
        (user.other or {}).get("synthetic_demo_project") != DEMO_PROJECT_ID
        for user in accounts.values()
    ):
        raise SyntheticDemoError("baseline_identity_mismatch")
    interviewer = accounts[DEMO_ACCOUNTS[0][1]]
    coder = accounts[DEMO_ACCOUNTS[1][1]]
    reviewer = accounts[DEMO_ACCOUNTS[2][1]]
    for number in range(1, 5):
        sid = f"synthetic-demo-{number}"
        death = VaDeathRegister(
            project_id=DEMO_PROJECT_ID,
            site_id=form.site_id,
            org_unit_id=unit.org_unit_id,
            death_number=number,
            unique_id=f"DEMO-{number:03d}",
            deceased_name=f"Synthetic person {number}",
            deceased_sex="female",
            age_years=60,
            date_of_death=datetime.now(UTC).date(),
            registered_by=interviewer.user_id,
            status="registered" if number == 1 else "submitted",
            source="register",
            remarks="Synthetic demonstration only; no real person.",
        )
        register_pii_accessor.seal_new_row(death)
        if number == 1:
            session.add(death)
            continue
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=form.form_id,
            va_data_collector="Demo interviewer",
            va_uniqueid_masked=f"DEMO-{number:03d}",
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=60,
            va_deceased_gender="female",
            va_catcount={},
            va_category_list=[],
            va_summary=["Synthetic example: adult with fever and cough; no real person."],
            org_unit_id=unit.org_unit_id,
            org_unit_resolution="manual",
        )
        session.add(submission)
        session.flush()
        payload = {
            "Id10019": f"DEMO-{number:03d}",
            "Id10018": "yes",
            "Id10020": "2",
            "Id10023": 60,
            "Id10418": "Synthetic training narrative: fever and cough; no real person.",
        }
        version = VaSubmissionPayloadVersion(
            va_sid=sid,
            version_status="active",
            created_by=interviewer.user_id,
            created_by_role="interviewer",
        )
        # The one payload writer: the sealed Id10018 goes to the side row
        # with the split on, and the fingerprint follows the shared rule.
        write_payload_version(version, payload, new=True, session=session)
        session.add(version)
        session.flush()
        submission.active_payload_version_id = version.payload_version_id
        death.va_sid = sid
        session.add(death)
        state = "ready_for_coding"
        if number >= 3:
            initial = VaInitialAssessments(
                va_sid=sid,
                va_iniassess_by=coder.user_id,
                va_immediate_cod="Pneumonia",
                va_antecedent_cod="Pneumonia",
            )
            session.add(initial)
            session.flush()
            final = VaFinalAssessments(
                va_sid=sid,
                payload_version_id=version.payload_version_id,
                va_finassess_by=coder.user_id,
                source_initial_assessment_id=initial.va_iniassess_id,
                va_conclusive_cod="J18.9",
                va_finassess_remark="Synthetic training example",
            )
            session.add(final)
            session.flush()
            session.add(
                VaAllocations(
                    va_sid=sid,
                    va_allocated_to=coder.user_id,
                    va_allocation_for=VaAllocation.coding,
                    va_allocation_status=VaStatuses.deactive,
                )
            )
            authority = VaFinalCodAuthority(
                va_sid=sid,
                authoritative_final_assessment_id=final.va_finassess_id,
                authority_source_role="coder",
                authority_reason="synthetic_demo_baseline",
            )
            state = "reviewer_eligible"
            if number == 4:
                reviewed = VaReviewerFinalAssessments(
                    va_sid=sid,
                    payload_version_id=version.payload_version_id,
                    va_rfinassess_by=reviewer.user_id,
                    va_conclusive_cod="J18.9",
                    supersedes_coder_final_assessment_id=final.va_finassess_id,
                )
                session.add(reviewed)
                session.flush()
                authority.authoritative_reviewer_final_assessment_id = reviewed.va_rfinassess_id
                authority.authority_source_role = "reviewer"
                state = "reviewer_finalized"
                session.add(
                    VaAllocations(
                        va_sid=sid,
                        va_allocated_to=reviewer.user_id,
                        va_allocation_for=VaAllocation.reviewing,
                        va_allocation_status=VaStatuses.deactive,
                    )
                )
            session.add(authority)
        session.add(
            VaSubmissionWorkflow(
                va_sid=sid, workflow_state=state, workflow_reason="synthetic_demo_baseline"
            )
        )
    session.flush()
