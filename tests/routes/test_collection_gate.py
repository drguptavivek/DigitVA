"""The data-collection gate (bead digitva-jeyy).

Policy: docs/policy/project-clock-and-gates.md ("Data-collection gate").
Only a browser's new start (POST /deaths without client_death_id, POST
/drafts with neither death_id nor client_draft_id) is refused, 403
``collection_closed``; a registered death's interview, device uploads,
syncs, edits and revisions never are. /me/access carries the resolved gate
and never drops the interview or register_death actions.
"""
import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgUnitCollectionGate,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import collection_gate
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.authz.fixture import TA, AuthzFixtureMixin
from tests.base import BaseTestCase

API = "/api/v1/intake"


def _answers():
    return {
        "Id10013": "yes", "Id10017": "Bina", "Id10018": "Sahu", "Id10019": "female",
        "Id10023": (date.today() - timedelta(days=5)).isoformat(), "finalAgeInYears": "71",
        "narr_language": "english",
    }


def _upload_body(project_id, site_id, death_id=None, **extra):
    text = json.dumps(_answers(), separators=(",", ":"))
    return {
        "client_draft_id": str(uuid.uuid4()), "project_id": project_id, "site_id": site_id,
        "death_id": death_id, "draft": {"startedAt": datetime.now(UTC).isoformat()},
        "completion": {"valid": True, "issues": []}, "answers_json": text,
        "answers_sha256": hashlib.sha256(text.encode()).hexdigest(), **extra,
    }


class SiteCollectionGateTests(BaseTestCase):
    """A site project (no tree): the site gate alone."""

    PROJECT_ID = "CGS01"
    SITE_ID = "CG01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID, project_code=cls.PROJECT_ID, project_name="Gate Project",
            project_nickname="Gate", project_status=VaStatuses.active, project_registered_at=now,
            project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID, site_name="Gate Site One", site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID, site_id=cls.SITE_ID, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(cls.PROJECT_ID, cls.SITE_ID)
        db.session.add(VaForms(
            form_id="CGS01CG0101", project_id=cls.PROJECT_ID, site_id=cls.SITE_ID,
            odk_form_id="ODK_GATE", odk_project_id="7", form_type="WHO VA 2022", form_source="odk",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        cls.interviewer = cls._get_or_make_user("gate.interviewer@test.local", "Gate12345")
        db.session.add(VaUserAccessGrants(
            user_id=cls.interviewer.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=cls.PROJECT_ID,
            notes="collection gate test", grant_status=VaStatuses.active,
        ))
        db.session.commit()
        cls.interviewer_id = str(cls.interviewer.user_id)

    def setUp(self):
        super().setUp()
        self._login(self.interviewer_id)

    # ── helpers ────────────────────────────────────────────────────────────

    def _gate(self, **values):
        ps = db.session.scalar(sa.select(VaProjectSites).where(
            VaProjectSites.project_id == self.PROJECT_ID, VaProjectSites.site_id == self.SITE_ID))
        for name, value in values.items():
            setattr(ps, name, value)
        db.session.commit()

    def _project_today(self):
        return collection_gate.project_days([self.PROJECT_ID])[self.PROJECT_ID].today

    def _register(self, **extra):
        return self.client.post(f"{API}/deaths", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": "Bina Sahu",
            "deceased_sex": "female", "date_of_death": (date.today() - timedelta(days=5)).isoformat(),
            "age_years": 71, **extra,
        })

    def _direct_start(self):
        return self.client.post(f"{API}/drafts", headers=self._csrf_headers(),
                                json={"project_id": self.PROJECT_ID, "site_id": self.SITE_ID})

    def _assert_refused(self, response, reason, when=None):
        self.assertEqual(response.status_code, 403, response.get_json())
        body = response.get_json()
        self.assertEqual(body["code"], "collection_closed")
        self.assertEqual(body["reason"], reason)
        self.assertEqual(body["display_name"], "Gate Site One")
        self.assertEqual(body["date"], when.isoformat() if when else None)
        self.assertIn("Gate Site One", body["error"])
        return body

    # ── refusals of a new start ────────────────────────────────────────────

    def test_paused_refuses_a_new_registration_and_a_direct_start(self):
        self._gate(collection_enabled=False)
        body = self._assert_refused(self._register(), collection_gate.PAUSED)
        self.assertEqual(body["error"], "Data collection for Gate Site One is paused.")
        self._assert_refused(self._direct_start(), collection_gate.PAUSED)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister).where(
            VaDeathRegister.project_id == self.PROJECT_ID)), 0)

    def test_an_automatic_site_is_named_by_its_project(self):
        site = db.session.get(VaSiteMaster, self.SITE_ID)
        site.site_name = "Sites_in_project_CGS01"
        db.session.commit()
        self._gate(collection_enabled=False)
        body = self._register().get_json()
        self.assertEqual(body["display_name"], "Gate Project")
        self.assertIn("Gate Project", body["error"])
        self.assertNotIn("Sites_in_project", body["error"])
        site.site_name = "Gate Site One"
        db.session.commit()

    def test_before_the_start_date_refuses_and_the_start_date_itself_is_open(self):
        today = self._project_today()
        self._gate(collection_start_date=today + timedelta(days=1))
        body = self._assert_refused(self._register(), collection_gate.NOT_STARTED, today + timedelta(days=1))
        self.assertIn("opens on", body["error"])
        self._gate(collection_start_date=today)
        self.assertEqual(self._register().status_code, 201)

    def test_after_the_end_date_refuses_and_the_end_date_itself_is_open(self):
        today = self._project_today()
        self._gate(collection_end_date=today - timedelta(days=1))
        body = self._assert_refused(self._direct_start(), collection_gate.ENDED, today - timedelta(days=1))
        self.assertEqual(
            body["error"],
            f"Data collection for Gate Site One ended on {(today - timedelta(days=1)).strftime('%B %-d, %Y')}.")
        self._gate(collection_end_date=today)
        self.assertEqual(self._direct_start().status_code, 201)

    def test_the_daily_limit_counts_registrations_and_direct_starts(self):
        self._gate(daily_interviewer_limit=2)
        self.assertEqual(self._register().status_code, 201)
        self.assertEqual(self._direct_start().status_code, 201)
        body = self._assert_refused(self._register(), collection_gate.DAILY_LIMIT)
        self.assertEqual(body["daily_interviewer_limit"], 2)
        self.assertEqual(body["error"], "You have reached today's limit of 2 new interviews for Gate Site One.")

    def test_a_recorded_refusal_is_not_counted_but_a_registration_is(self):
        self._gate(daily_interviewer_limit=1)
        refusal = self.client.post(f"{API}/refusals", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID,
            "client_draft_id": str(uuid.uuid4()), "refusal_sex": "female", "who_consent": "no"})
        self.assertEqual(refusal.status_code, 201, refusal.get_json())
        target = (self.PROJECT_ID, self.SITE_ID, None)
        count = lambda: collection_gate.resolve(self.interviewer, [target])[target]["today_count"]
        self.assertEqual(count(), 0)
        self.assertEqual(self._register().status_code, 201)
        self.assertEqual(count(), 1)
        self._assert_refused(self._register(), collection_gate.DAILY_LIMIT)

    # ── never refused ──────────────────────────────────────────────────────

    def test_the_interview_of_a_registered_death_is_not_gated(self):
        death_id = self._register().get_json()["case"]["death_id"]
        self._gate(collection_enabled=False)
        response = self.client.post(f"{API}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_id": death_id})
        self.assertEqual(response.status_code, 201, response.get_json())

    def test_device_pushes_are_accepted_after_close_and_over_the_limit(self):
        self._gate(daily_interviewer_limit=1)
        self.assertEqual(self._register().status_code, 201)
        self._assert_refused(self._register(), collection_gate.DAILY_LIMIT)
        # Over the limit: a registration made on the phone, an interview with
        # no registration, and the attachment draft of one.
        self.assertEqual(self._register(client_death_id=str(uuid.uuid4())).status_code, 201)
        response = self.client.post(f"{API}/submissions", headers=self._csrf_headers(),
                                    json=_upload_body(self.PROJECT_ID, self.SITE_ID))
        self.assertEqual(response.status_code, 201, response.get_json())
        response = self.client.post(f"{API}/drafts", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "client_draft_id": str(uuid.uuid4())})
        self.assertEqual(response.status_code, 201, response.get_json())
        # Closed: the same.
        self._gate(collection_enabled=False, collection_end_date=self._project_today() - timedelta(days=3))
        self.assertEqual(self._register(client_death_id=str(uuid.uuid4())).status_code, 201)
        response = self.client.post(f"{API}/submissions", headers=self._csrf_headers(),
                                    json=_upload_body(self.PROJECT_ID, self.SITE_ID))
        self.assertEqual(response.status_code, 201, response.get_json())

    def test_edits_syncs_uploads_and_revisions_of_started_work_are_not_gated(self):
        death_id = self._register().get_json()["case"]["death_id"]
        uploaded = self._register().get_json()["case"]["death_id"]
        first = self.client.post(f"{API}/submissions", headers=self._csrf_headers(),
                                 json=_upload_body(self.PROJECT_ID, self.SITE_ID, uploaded))
        self.assertEqual(first.status_code, 201, first.get_json())
        va_sid = first.get_json()["va_sid"]
        self._gate(collection_enabled=False)

        edit = self.client.patch(f"{API}/deaths/{death_id}", headers=self._csrf_headers(),
                                 json={"deceased_name": "Bina Devi Sahu"})
        self.assertEqual(edit.status_code, 200, edit.get_json())
        now = datetime.now(UTC).isoformat()
        sync = self.client.post(f"{API}/drafts/sync", headers=self._csrf_headers(), json={
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_id": death_id,
            "client_draft_id": str(uuid.uuid4()), "draft": {"startedAt": now},
            "answers_json": '{"Id10013":"yes"}', "answers_sha256": hashlib.sha256(b'{"Id10013":"yes"}').hexdigest(),
            "savedAt": now, "deviceClockAt": now, "base_updated_at": None,
        })
        self.assertEqual(sync.status_code, 200, sync.get_json())
        upload = self.client.post(f"{API}/submissions", headers=self._csrf_headers(),
                                  json=_upload_body(self.PROJECT_ID, self.SITE_ID, death_id))
        self.assertEqual(upload.status_code, 201, upload.get_json())
        text = json.dumps(dict(_answers(), Id10017="Binita"), separators=(",", ":"))
        revision = self.client.post(f"{API}/submissions/{va_sid}/revisions", headers=self._csrf_headers(), json={
            "reason_code": "interviewer_correction", "draft": {}, "completion": {"valid": True, "issues": []},
            "answers_json": text, "answers_sha256": hashlib.sha256(text.encode()).hexdigest(),
        })
        self.assertEqual(revision.status_code, 200, revision.get_json())

    # ── the project clock ──────────────────────────────────────────────────

    def test_today_and_midnight_are_the_project_clock_not_utc(self):
        # 20:00 UTC on Nov 6 is 01:30 on Nov 7 in Asia/Kolkata.
        now = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)
        db.session.get(VaProjectMaster, self.PROJECT_ID).timezone = "Asia/Kolkata"
        self._gate(collection_end_date=date(2026, 11, 6), daily_interviewer_limit=1)
        with patch("app.services.project_clock._now", return_value=now):
            self._assert_refused(self._register(), collection_gate.ENDED, date(2026, 11, 6))
        self._gate(collection_end_date=None)

        def register_at(created_at):
            with patch("app.services.project_clock._now", return_value=now):
                response = self._register()
            self.assertEqual(response.status_code, 201, response.get_json())
            db.session.execute(sa.update(VaDeathRegister).where(
                VaDeathRegister.death_id == uuid.UUID(response.get_json()["case"]["death_id"]),
            ).values(created_at=created_at))
            db.session.commit()

        # 18:00 UTC is 23:30 on Nov 6 in Kolkata: yesterday, not counted.
        register_at(datetime(2026, 11, 6, 18, 0, tzinfo=UTC))
        # 19:00 UTC is 00:30 on Nov 7: today's first, the limit of 1 is reached.
        register_at(datetime(2026, 11, 6, 19, 0, tzinfo=UTC))
        with patch("app.services.project_clock._now", return_value=now):
            self._assert_refused(self._register(), collection_gate.DAILY_LIMIT)

    # ── admin ──────────────────────────────────────────────────────────────

    def _put_site(self, body):
        return self.client.put(
            f"/admin/api/project-sites/{self.PROJECT_ID}/{self.SITE_ID}/collection-settings",
            headers=self._csrf_headers(), json=body)

    def test_admin_saves_the_site_gate_and_validates_it(self):
        self._login(self.base_admin_id)
        good = {"collection_enabled": True, "collection_start_date": "2026-11-01",
                "collection_end_date": "2026-11-01", "daily_interviewer_limit": ""}
        response = self._put_site(good)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["collection_end_date"], "2026-11-01")
        self.assertIsNone(response.get_json()["daily_interviewer_limit"])
        for bad, word in (
            (dict(good, collection_end_date="2026-10-31"), "on or after"),
            (dict(good, daily_interviewer_limit=0), "between 1 and 100000"),
            (dict(good, daily_interviewer_limit=100001), "between 1 and 100000"),
            (dict(good, daily_interviewer_limit="x"), "integer"),
            (dict(good, collection_enabled="yes"), "boolean"),
            (dict(good, collection_start_date="11/01/2026"), "ISO"),
        ):
            with self.subTest(bad=bad):
                response = self._put_site(bad)
                self.assertEqual(response.status_code, 400)
                self.assertIn(word, response.get_json()["error"])
        listed = self.client.get(f"/admin/api/project-sites?project_id={self.PROJECT_ID}").get_json()
        self.assertEqual(listed["project_sites"][0]["collection_start_date"], "2026-11-01")

    def test_only_an_admin_saves_the_site_gate(self):
        self._login(self.interviewer_id)
        response = self._put_site({"collection_enabled": False})
        self.assertEqual(response.status_code, 403)


class TreeCollectionGateTests(AuthzFixtureMixin, BaseTestCase):
    """The AZTA01 tree (D1 > C1 > P1 > SC1, C1 > P2): unit gates and /me/access."""

    SITE = "AZS1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        project = db.session.get(VaProjectMaster, TA)
        project.web_intake_mode = "both"
        project.project_structure_mode = "organization"
        _ensure_legacy_project_site_rows(TA, cls.SITE)
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.user = self.users["interviewer_p1"]
        self._login(str(self.user.user_id))

    def _unit_gate(self, key, **values):
        unit_id = self.units[key].org_unit_id
        gate = db.session.get(MapOrgUnitCollectionGate, unit_id) or MapOrgUnitCollectionGate(org_unit_id=unit_id)
        for name, value in values.items():
            setattr(gate, name, value)
        db.session.add(gate)
        db.session.commit()

    def _site_gate(self, site_id=SITE, **values):
        ps = db.session.get(VaProjectSites, self.project_site_ids[(TA, site_id)])
        for name, value in values.items():
            setattr(ps, name, value)
        db.session.commit()

    def _register(self, unit_key, **extra):
        return self.client.post(f"{API}/deaths", headers=self._csrf_headers(), json={
            "project_id": TA, "site_id": self.SITE, "org_unit_id": str(self.units[unit_key].org_unit_id),
            "deceased_name": "Bina Sahu", "deceased_sex": "female",
            "date_of_death": (date.today() - timedelta(days=5)).isoformat(), "age_years": 71, **extra,
        })

    def test_a_unit_gate_narrows_an_open_site_and_the_nearest_gated_ancestor_wins(self):
        self._unit_gate("C1", collection_enabled=False)
        response = self._register("SC1")
        self.assertEqual(response.status_code, 403, response.get_json())
        self.assertEqual(response.get_json()["reason"], collection_gate.PAUSED)
        self.assertEqual(response.get_json()["display_name"], self.units["C1"].unit_name)
        # P1's own open row is nearer than C1's closed one for P1 and SC1.
        self._unit_gate("P1", collection_enabled=True)
        self.assertEqual(self._register("SC1").status_code, 201)

    def test_an_open_unit_gate_never_opens_a_closed_site(self):
        self._unit_gate("P1", collection_enabled=True)
        self._site_gate(collection_enabled=False)
        response = self._register("P1")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["display_name"], self.SITE)

    def test_a_unit_daily_limit_counts_the_whole_subtree(self):
        self._unit_gate("P1", daily_interviewer_limit=1)
        self.assertEqual(self._register("SC1").status_code, 201)
        response = self._register("P1")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["reason"], collection_gate.DAILY_LIMIT)
        self.assertEqual(response.get_json()["daily_interviewer_limit"], 1)

    # ── /me/access ─────────────────────────────────────────────────────────

    def _project(self):
        response = self.client.get("/api/v1/me/access")
        self.assertEqual(response.status_code, 200)
        return next(p for p in response.get_json()["projects"] if p["project_id"] == TA)

    def test_a_fully_closed_gate_keeps_the_interview_and_register_actions(self):
        before = self._project()
        self.assertTrue(before["actions"]["interview"])
        self.assertTrue(before["actions"]["register_death"])
        for site_id in ("AZS1", "AZS2"):
            self._site_gate(site_id, collection_enabled=False)
        self._unit_gate("D1", collection_enabled=False)
        after = self._project()
        self.assertEqual(after["actions"]["interview"], before["actions"]["interview"])
        self.assertEqual(after["actions"]["register_death"], before["actions"]["register_death"])
        gates = after["collection_gate"]
        self.assertTrue(gates["sites"] and gates["units"])
        self.assertTrue(all(not g["open"] and g["reason"] == collection_gate.PAUSED
                            for g in gates["sites"] + gates["units"]))

    def test_access_carries_the_clock_and_the_resolved_gate_with_today_count(self):
        self._unit_gate("P1", daily_interviewer_limit=3, collection_end_date=date(2099, 1, 31))
        self.assertEqual(self._register("SC1").status_code, 201)
        project = self._project()
        self.assertEqual(project["timezone"], "Asia/Kolkata")
        self.assertEqual(project["project_today"],
                         collection_gate.project_days([TA])[TA].today.isoformat())
        self.assertTrue(project["server_time"].endswith("Z"))
        site = next(g for g in project["collection_gate"]["sites"] if g["site_id"] == self.SITE)
        self.assertEqual((site["open"], site["today_count"], site["daily_interviewer_limit"]), (True, 1, None))
        units = {(g["site_id"], g["org_unit_id"]): g for g in project["collection_gate"]["units"]}
        sc1 = units[(self.SITE, str(self.units["SC1"].org_unit_id))]
        self.assertEqual(sc1, {
            "site_id": self.SITE, "org_unit_id": str(self.units["SC1"].org_unit_id),
            "open": True, "enabled": True, "start_date": None, "end_date": "2099-01-31",
            "daily_interviewer_limit": 3, "today_count": 1, "display_name": self.units["P1"].unit_name,
            "reason": None, "date": None, "message": None,
        })
        # Units outside the interviewer's reach are not listed.
        self.assertNotIn((self.SITE, str(self.units["P2"].org_unit_id)), units)

    # ── admin: unit gate ───────────────────────────────────────────────────

    def test_admin_sets_validates_and_clears_a_unit_collection_gate(self):
        self._login(self.base_admin_id)
        url = f"/admin/api/organization/{TA}/units/{self.units['C1'].org_unit_id}/collection-gate"
        bad = self.client.put(url, headers=self._csrf_headers(), json={
            "collection_enabled": True, "collection_start_date": "2026-11-02", "collection_end_date": "2026-11-01"})
        self.assertEqual(bad.status_code, 400)
        bad = self.client.put(url, headers=self._csrf_headers(), json={
            "collection_enabled": True, "daily_interviewer_limit": 0})
        self.assertEqual(bad.status_code, 400)
        good = self.client.put(url, headers=self._csrf_headers(), json={
            "collection_enabled": False, "daily_interviewer_limit": 5})
        self.assertEqual(good.status_code, 200, good.get_json())
        self.assertEqual(good.get_json()["collection_gate"]["daily_interviewer_limit"], 5)
        self.assertEqual(self.client.get(url).get_json()["collection_gate"]["collection_enabled"], False)
        self.assertTrue(self.client.delete(url, headers=self._csrf_headers()).get_json()["cleared"])
        self.assertIsNone(self.client.get(url).get_json()["collection_gate"])
