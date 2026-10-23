"""SQL statements per HTTP request for a cookie-session coder (measurement only).

Prints one ``QCOUNT <label> sql=<n> session_store_writes=<m> session_modified=<b>``
line per request so a performance change can be recorded before and after, and
asserts the ceilings digitva-lb6b set (no unit-gate scan without a gate, no
session-store write for an unchanged session, no inline sweep inside the
throttle window). Run with ``-s``; ``QCOUNT_VERBOSE=1`` also prints each
statement's first 120 characters.

Each request is measured the way production sees it: Flask-Login's per-request
user cache on ``g`` (which lives for the whole pytest app context) and the
payload PII cache are dropped first, so a "warm" request keeps only what the
app itself caches across requests (Redis grant and dashboard caches), not test
harness leftovers. The scoped session's identity map is expired too, so the
signed-in user is reloaded by a query as in production.
"""

import os
import sys
import uuid
from datetime import datetime, timezone
from unittest import mock

import sqlalchemy as sa
from flask import g
from sqlalchemy import event

from app import cache, db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
)
from app.services.coder_dashboard_service import bust_coder_dashboard_cache
from app.services.submission_payload_version_service import clear_payload_pii_request_cache
from app.utils.bearer_session import BearerBlindSessionInterface
from tests.base import BaseTestCase

_SUFFIX = uuid.uuid4().hex[:3].upper()
PICK_PROJECT = f"QP{_SUFFIX}"
RANDOM_PROJECT = f"QR{_SUFFIX}"
SITES_PER_PROJECT = 2
SUBMISSIONS_PER_FORM = 15  # 2 projects x 2 sites x 15 = 60 ready cases
SUBMITTED = datetime(2026, 1, 1, tzinfo=timezone.utc)
VERBOSE = os.environ.get("QCOUNT_VERBOSE") == "1"


class RequestQueryCountTests(BaseTestCase):
    @classmethod
    def _seed_project(cls, project_id, mode, letter):
        """A project of ``SITES_PER_PROJECT`` sites, one form each, every form
        holding ``SUBMISSIONS_PER_FORM`` ready_for_coding cases; the coder holds
        a coder grant on each project-site."""
        now = datetime.now(timezone.utc)
        for model, extra in (
            (VaProjectMaster, {"coding_intake_mode": mode}),
            (VaResearchProjects, {}),
        ):
            db.session.add(
                model(
                    project_id=project_id, project_code=project_id,
                    project_name=f"Project {project_id}", project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now, project_updated_at=now, **extra,
                )
            )
        db.session.flush()
        for n in range(SITES_PER_PROJECT):
            site_id = f"{letter}{n}{_SUFFIX[:2]}"  # site ids are 4 characters
            form_id = f"{project_id}{site_id}01"
            db.session.add(
                VaSiteMaster(
                    site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now, site_updated_at=now,
                )
            )
            db.session.add(
                VaSites(
                    site_id=site_id, project_id=project_id, site_name=f"Site {site_id}",
                    site_abbr=site_id, site_status=VaStatuses.active,
                    site_registered_at=now, site_updated_at=now,
                )
            )
            db.session.flush()
            project_site = VaProjectSites(
                project_id=project_id, site_id=site_id,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            )
            db.session.add(project_site)
            db.session.add(
                VaForms(
                    form_id=form_id, project_id=project_id, site_id=site_id,
                    odk_form_id=f"FORM_{project_id}_{n}", odk_project_id="11",
                    form_type="WHO VA 2022", form_status=VaStatuses.active,
                    form_registered_at=now, form_updated_at=now,
                )
            )
            db.session.flush()
            db.session.add(
                VaUserAccessGrants(
                    user_id=cls.coder.user_id, role=VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=project_site.project_site_id,
                    notes="query count test", grant_status=VaStatuses.active,
                )
            )
            for i in range(SUBMISSIONS_PER_FORM):
                sid = f"qc-{form_id}-{i}"
                db.session.add(
                    VaSubmissions(
                        va_sid=sid, va_form_id=form_id,
                        va_submission_date=SUBMITTED, va_odk_updatedat=SUBMITTED,
                        va_data_collector="Collector", va_odk_reviewstate=None,
                        va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                        va_consent="yes", va_narration_language="English",
                        va_deceased_age=42, va_deceased_gender="male",
                        va_summary=[], va_catcount={}, va_category_list=[],
                    )
                )
                db.session.flush()
                db.session.add(
                    VaSubmissionWorkflow(
                        va_sid=sid, workflow_state="ready_for_coding",
                        workflow_reason="test_seed", workflow_updated_by_role="vasystem",
                    )
                )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coder = cls._make_user(f"qcount.coder.{_SUFFIX}@test.local", "QCount123")
        cls._seed_project(PICK_PROJECT, "pick_and_choose", "P")
        cls._seed_project(RANDOM_PROJECT, "random_form_allocation", "R")
        db.session.commit()
        cls.coder_id = str(cls.coder.user_id)

    def setUp(self):
        super().setUp()
        self._login(self.coder_id)
        bust_coder_dashboard_cache(self.coder.user_id)

    def _measure(self, label, method, path, **kwargs):
        """One request through the cookie-session test client; prints and
        returns ``(response, statements)``."""
        interface = self.app.session_interface
        self.assertIsInstance(interface, BearerBlindSessionInterface)
        inner = interface._inner
        real_save = interface.save_session
        modified = []

        def spy_save(app, session, response):
            modified.append(bool(session.modified))
            return real_save(app, session, response)

        statements = []

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        # What a fresh request would not carry over from the pytest-wide app context.
        if hasattr(g, "_login_user"):
            del g._login_user
        clear_payload_pii_request_cache()
        db.session.expire_all()  # production starts a request with an empty identity map

        event.listen(db.engine, "before_cursor_execute", record)
        try:
            with mock.patch.object(
                inner, "_upsert_session", wraps=inner._upsert_session
            ) as writes, mock.patch.object(interface, "save_session", side_effect=spy_save):
                response = getattr(self.client, method)(path, **kwargs)
        finally:
            event.remove(db.engine, "before_cursor_execute", record)

        out = sys.__stdout__
        print(
            f"QCOUNT {label} sql={len(statements)} "
            f"session_store_writes={writes.call_count} session_modified={modified}",
            file=out,
        )
        if VERBOSE:
            for n, statement in enumerate(statements, 1):
                print(f"  {n:3d}. {' '.join(statement.split())[:120]}", file=out)
        out.flush()
        return response, statements, writes.call_count

    def test_coder_request_query_counts(self):
        response, sql, _ = self._measure("available_cold", "get", "/api/v1/coding/available")
        self.assertEqual(response.status_code, 200)
        forms = response.get_json()["forms"]
        self.assertGreaterEqual(len([f for f in forms if f["va_sid"].startswith("qc-")]), 30)
        # No unit gate in these projects: an EXISTS on the gate table, never
        # the DISTINCT org_unit scan of va_submissions.
        self.assertTrue(any("map_org_unit_coding_gate" in s for s in sql))
        self.assertFalse(any("DISTINCT" in s and "org_unit_id" in s for s in sql))
        # 14 + the page's one batched name lookup (case_list_service.coding_names).
        self.assertLessEqual(len(sql), 15)
        response, _, writes = self._measure("available_warm", "get", "/api/v1/coding/available")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(writes, 0)  # unchanged session inside the refresh window

        response, _, _ = self._measure("dashboard_cold", "get", "/coding/")
        self.assertEqual(response.status_code, 200)
        response, _, writes = self._measure("dashboard_warm", "get", "/coding/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(writes, 0)

        # Production throttle (TestConfig turns it off), another request having
        # just swept: the allocation runs no inline stale/demo sweep.
        headers = self._csrf_headers()
        cache.set("coding:stale_sweep", 1, timeout=30)
        try:
            with mock.patch.dict(self.app.config, {"CODING_STALE_SWEEP_MIN_INTERVAL_SECONDS": 30}):
                response, sql, writes = self._measure(
                    "allocation", "post", "/api/v1/coding/allocation", json={}, headers=headers
                )
        finally:
            cache.delete("coding:stale_sweep")
        self.assertEqual(response.status_code, 201, response.get_data(as_text=True))
        self.assertTrue(response.get_json()["va_sid"].startswith("qc-"))
        self.assertFalse(any("va_narrative_assessments" in s for s in sql))
        self.assertEqual(writes, 0)
