"""Characterization of every DM KPI endpoint (digitva-r8nh.16).

Pins the JSON each ``/api/v1/analytics/dm-kpi/*`` endpoint returns today, for a
data manager, an admin and a DM with no grants, plus the cache key each one
writes, so moving the query code into ``app/services/kpi`` provably changes
nothing. Expected values live in ``golden/dm_kpi_characterization.json``; set
``REGEN_KPI_GOLDEN=1`` to rewrite it, and only for a reviewed behaviour change.

Determinism: the project clock is frozen, seeded timestamps are explicit, and
dates, UUIDs and floats are normalised (see ``_norm``).
"""

import contextlib
import json
import os
import re
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaForms,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaUserAccessGrants,
    VaUsers,
)
from app.routes.api.dm_kpi import dm_kpi_scope
from app.services import dm_dashboard_cache
from app.services.submission_analytics_mv import (
    COD_SNAPSHOT_MV_NAME,
    CORE_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_cod_snapshot_mv_sql,
)
from tests.base import BaseTestCase

GOLDEN = Path(__file__).parent / "golden" / "dm_kpi_characterization.json"

ENDPOINTS = [
    "grid/", "grid/?days=3",
    "sync/status", "sync/status?period=7d", "sync/latency", "sync/latency?range=today",
    "sync/attachment-health", "sync/smartva-failure-rate",
    "language/gap", "language/pendency", "language/distribution", "language/missing",
    "exclusions/rates", "exclusions/not-codeable", "exclusions/not-analysable",
    "exclusions/breakdown", "exclusions/blocked", "exclusions/nqa-sa", "exclusions/odk-issues",
    "coders/utilization", "coders/output", "coders/output?range=today", "coders/roster",
    "coders/disagreement",
    "pipeline/pending", "pipeline/aging", "pipeline/time-to-code",
    "pipeline/time-to-code?range=today", "pipeline/reviewed", "pipeline/upstream-changes",
    "pipeline/inflow-outflow", "pipeline/inflow-outflow?days=3", "pipeline/site-bottleneck",
    "pipeline/reviewer-throughput", "pipeline/backlog-trend",
    "burndown/",
    "workflow/flowchart", "workflow/state-velocity", "workflow/state-velocity?days=7",
    "workflow/stagnation", "workflow/daily-transitions", "workflow/daily-transitions?days=3",
    "outcomes/unknown-cause", "outcomes/disagreement", "outcomes/female-share",
    "outcomes/female-final-gap", "outcomes/final-cause-coverage", "outcomes/register-coverage",
    "critical-path/", "critical-path/?days=7",
]

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](.*))?$")


def _anchor() -> datetime:
    """12:00 UTC, at most 25 hours before now: midday in every project zone."""
    now = datetime.now(timezone.utc)
    day = now.date() if now.hour >= 13 else now.date() - timedelta(days=1)
    return datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=12)


def _norm(value, anchor_day: date):
    if isinstance(value, dict):
        return {k: _norm(v, anchor_day) for k, v in value.items()}
    if isinstance(value, list):
        return [_norm(v, anchor_day) for v in value]
    if isinstance(value, float):
        return round(value, 1)
    if isinstance(value, str):
        value = _UUID.sub("<uuid>", value)
        value = re.sub(r"dmkpi\.[0-9a-f]{8}", "dmkpi.<sfx>", value)
        m = _DATE.match(value)
        if m:
            offset = (anchor_day - date.fromisoformat(m.group(1))).days
            return f"T-{offset}" + (" <time>" if m.group(2) else "")
    return value


def _write_golden(key, value):
    data = json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}
    data[key] = value
    GOLDEN.parent.mkdir(exist_ok=True)
    GOLDEN.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


class DmKpiCharacterizationTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}C9"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.anchor = _anchor()
        cls._ensure_base_research_project_and_site()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="DM_KPI_CHAR_FORM",
                odk_project_id="91",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=cls.anchor - timedelta(days=30),
                form_updated_at=cls.anchor - timedelta(days=30),
            )
        )
        db.session.flush()
        cls._seed("uuid:char-coded", "coder_finalized", "English", None, 6)
        cls._seed("uuid:char-retired", "coder_finalized", "English", "missing_in_odk", 6)
        cls._seed("uuid:char-ready", "ready_for_coding", "Hindi", None, 3)
        for mv in (COD_SNAPSHOT_MV_NAME, CORE_MV_NAME):
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(
            sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True, project_clock=True))
        )
        db.session.execute(sa.text(build_submission_cod_snapshot_mv_sql(icd11_buckets=True)))
        db.session.commit()

    @classmethod
    def _seed(cls, sid, state, language, issue, hours_ago):
        t0 = cls.anchor - timedelta(hours=hours_ago)
        db.session.add(
            VaSubmissions(
                va_sid=sid, va_form_id=cls.FORM_ID,
                va_submission_date=t0, va_odk_updatedat=t0, va_created_at=t0.replace(tzinfo=None),
                va_odk_reviewstate="hasIssues", va_sync_issue_code=issue,
                va_sync_issue_detail="absent from the active ODK list" if issue else None,
                va_sync_issue_updated_at=t0 if issue else None,
                va_data_collector="Collector", va_instance_name=sid, va_uniqueid_real=sid,
                va_uniqueid_masked=f"masked-{sid[-8:]}", va_consent="yes",
                va_narration_language=language, va_deceased_age=55, va_deceased_gender="female",
                va_summary=[], va_catcount={}, va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid, workflow_state=state, workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        coder = cls.base_coder_user.user_id

        def ev(tid, prev, cur, minutes, kind="system", role="vasystem", user=None):
            return VaSubmissionWorkflowEvent(
                va_sid=sid, transition_id=tid, previous_state=prev, current_state=cur,
                actor_kind=kind, actor_role=role, actor_user_id=user,
                transition_reason="test_seed", event_created_at=t0 + timedelta(minutes=minutes),
            )

        events = [
            ev("sync_new_payload_routed", None, "smartva_pending", 0),
            ev("smartva_completed", "smartva_pending", "ready_for_coding", 30),
        ]
        if state == "coder_finalized":
            events += [
                ev("coding_started", "ready_for_coding", "coding_in_progress", 60, "user", "vacoder", coder),
                ev("coder_finalized", "coding_in_progress", "coder_finalized", 120, "user", "vacoder", coder),
            ]
            db.session.add(
                VaFinalAssessments(
                    va_sid=sid, va_finassess_by=coder,
                    va_conclusive_cod="I21-Acute myocardial infarction",
                    va_finassess_status=VaStatuses.active,
                )
            )
            db.session.add(
                VaAllocations(
                    va_sid=sid, va_allocated_to=coder, va_allocation_for=VaAllocation.coding,
                    va_allocation_status=VaStatuses.deactive,
                )
            )
        db.session.add_all(events)
        db.session.flush()

    def _new_dm(self, grant):
        suffix = uuid.uuid4().hex[:8]
        user = VaUsers(
            user_id=uuid.uuid4(), name=f"dmkpi.{suffix}", email=f"dmkpi.{suffix}@example.com",
            vacode_language=["English"], permission={}, landing_page="data_manager",
            pw_reset_t_and_c=True, email_verified=True, user_status=VaStatuses.active,
        )
        user.set_password("DataManager123")
        db.session.add(user)
        db.session.flush()
        if grant:
            ps = db.session.scalar(
                db.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == self.BASE_PROJECT_ID,
                    VaProjectSites.site_id == self.BASE_SITE_ID,
                )
            )
            db.session.add(
                VaUserAccessGrants(
                    user_id=user.user_id, role=VaAccessRoles.data_manager,
                    scope_type=VaAccessScopeTypes.project_site, project_site_id=ps,
                    notes="dm kpi characterization", grant_status=VaStatuses.active,
                )
            )
        db.session.commit()
        return str(user.user_id)

    def _snapshot(self):
        out = {}
        frozen = self.anchor + timedelta(hours=1)
        with mock.patch("app.services.project_clock._now", return_value=frozen):
            for path in ENDPOINTS:
                response = self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
                body = response.get_json(silent=True)
                out[path] = {"status": response.status_code, "json": _norm(body, self.anchor.date())}
        return out

    def _compare(self, who, snapshot):
        if os.environ.get("REGEN_KPI_GOLDEN"):
            _write_golden(who, snapshot)
            return
        expected = json.loads(GOLDEN.read_text())[who]
        for path in ENDPOINTS:
            with self.subTest(who=who, path=path):
                self.assertEqual(
                    json.loads(json.dumps(snapshot[path], sort_keys=True)), expected[path]
                )

    def test_data_manager_responses(self):
        self._login(self._new_dm(grant=True))
        snap = self._snapshot()
        self.assertTrue(any(v["status"] == 200 for v in snap.values()))
        self._compare("dm", snap)

    def test_admin_responses(self):
        self._login(self.base_admin_id)
        self._compare("admin", self._snapshot())

    def test_empty_scope_responses(self):
        # The role check refuses a DM with no scope before a handler runs, so
        # reach every handler's empty-scope branch by resolving an empty scope.
        self._login(self.base_admin_id)
        empty = dm_kpi_scope.DmScope(pairs=[], unit_ids=[])
        with contextlib.ExitStack() as stack:
            for name in sorted(sys.modules):
                if name.startswith("app.routes.api.dm_kpi.dm_kpi_"):
                    mod = sys.modules[name]
                    if hasattr(mod, "dm_scope"):
                        stack.enter_context(mock.patch.object(mod, "dm_scope", return_value=empty))
            snap = self._snapshot()
        self._compare("empty", snap)

    def test_cache_keys(self):
        self._login(self._new_dm(grant=True))
        keys = []
        with mock.patch.object(dm_kpi_scope.grant_cache, "global_version", return_value="v1"), \
                mock.patch.object(dm_dashboard_cache, "generation", return_value=7), \
                mock.patch.object(dm_kpi_scope.cache, "get", return_value=None), \
                mock.patch.object(dm_kpi_scope.cache, "set",
                                  side_effect=lambda k, v, timeout=None: keys.append(k)), \
                mock.patch("app.services.project_clock._now",
                           return_value=self.anchor + timedelta(hours=1)):
            for path in ENDPOINTS:
                self.client.get(f"/api/v1/analytics/dm-kpi/{path}")
        norm = sorted(_UUID.sub("<uid>", k) for k in keys)
        self.assertGreater(len(norm), 30)
        if os.environ.get("REGEN_KPI_GOLDEN"):
            _write_golden("cache_keys", norm)
            return
        self.assertEqual(norm, json.loads(GOLDEN.read_text())["cache_keys"])
