"""Visits, contact attempts, pause and phones (digitva-vzk.9, worklist phase 5).

Policy: docs/policy/web-intake.md, "Built in phase 5". Covers:
  - Indian mobile validation and normalisation on register; masking in rows
  - set / clear a visit (registered <-> scheduled), bounds on the date
  - each contact-attempt outcome's state change, rows and dates
  - pause with a reason code; resume through start_draft
  - worklist order: next visit (overdue first, undated last), keyset paging
  - "Mine" counts a logged attempt
  - the API: CSRF, 404 out of scope, the register form's new fields
"""
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseContactAttempt,
    MapCaseTransition,
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
from app.services import case_transition_service as cases
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase


def _dod(days=10):
    return (date.today() - timedelta(days=days)).isoformat()


def _at(**delta):
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


class CaseVisitTests(BaseTestCase):
    PROJECT_ID = "WLV01"
    SITE_ID = "WV11"
    OTHER_PROJECT_ID = "WLV02"
    OTHER_SITE_ID = "WV12"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        pairs = ((cls.PROJECT_ID, cls.SITE_ID), (cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID))
        for project_id, site_id in pairs:
            db.session.add(VaProjectMaster(
                project_id=project_id, project_code=project_id, project_name=project_id,
                project_nickname=project_id, project_status=VaStatuses.active,
                project_registered_at=now, project_updated_at=now, web_intake_mode="both",
            ))
            db.session.add(VaSiteMaster(
                site_id=site_id, site_name=site_id, site_abbr=site_id,
                site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in pairs:
            db.session.add(VaProjectSites(
                project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
                project_site_registered_at=now, project_site_updated_at=now,
            ))
        db.session.flush()
        for project_id, site_id in pairs:
            _ensure_legacy_project_site_rows(project_id, site_id)
            db.session.add(VaForms(
                form_id=f"{project_id}{site_id}01", project_id=project_id, site_id=site_id,
                odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022",
                form_source="odk", form_status=VaStatuses.active,
                form_registered_at=now, form_updated_at=now,
            ))
        cls.alice = cls._get_or_make_user("wv.alice@test.local", "Visits123")
        cls.bob = cls._get_or_make_user("wv.bob@test.local", "Visits123")
        cls.dave = cls._get_or_make_user("wv.dave@test.local", "Visits123")
        for user, project_id in ((cls.alice, cls.PROJECT_ID), (cls.bob, cls.PROJECT_ID),
                                 (cls.dave, cls.OTHER_PROJECT_ID)):
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.interviewer, notes="visits test",
                scope_type=VaAccessScopeTypes.project, project_id=project_id,
                grant_status=VaStatuses.active,
            ))
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────

    def _register(self, user=None, **overrides):
        fields = {"deceased_name": "Meena Rao", "deceased_sex": "female", "date_of_death": _dod()}
        fields.update(overrides)
        return intake_svc.register_death(
            user or self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID, **fields
        )

    def _attempts(self, case):
        return db.session.scalars(
            sa.select(MapCaseContactAttempt).where(MapCaseContactAttempt.death_id == case.death_id)
        ).all()

    def _last_audit(self, case):
        return db.session.scalars(
            sa.select(MapCaseTransition)
            .where(MapCaseTransition.death_id == case.death_id)
            .order_by(MapCaseTransition.created_at.desc())
            .limit(1)
        ).one()

    # ── phones and address ─────────────────────────────────────────────────

    def test_register_normalises_valid_indian_mobiles(self):
        for raw in ("9876543210", "+919876543210", "09876543210", "98765 43210", "+91 98765-43210"):
            case = self._register(informant_phone=raw)
            self.assertEqual(case.informant_phone, "9876543210", raw)
        case = self._register(informant_phone="", informant_phone_2="6123456789")
        self.assertIsNone(case.informant_phone)
        self.assertEqual(case.informant_phone_2, "6123456789")

    def test_register_refuses_invalid_phones(self):
        for raw in ("5876543210", "987654321", "98765432101", "+929876543210", "phone me", "1-800-DEATH"):
            for field in ("informant_phone", "informant_phone_2"):
                with self.assertRaises(cases.WebIntakeError, msg=f"{field}={raw}") as ctx:
                    self._register(**{field: raw})
                self.assertEqual(ctx.exception.status_code, 400)

    def test_structured_address_and_full_phones_on_the_case_only(self):
        case = self._register(
            informant_phone="9876543210", informant_phone_2="+917012345678",
            address_house_street="12 Temple Road", address_village_ward="Ward 4",
            address_landmark="Near the tank",
        )
        full = intake_svc.serialize_death(case)
        self.assertEqual((full["informant_phone"], full["informant_phone_2"]), ("9876543210", "7012345678"))
        self.assertEqual(
            (full["address_house_street"], full["address_village_ward"], full["address_landmark"]),
            ("12 Temple Road", "Ward 4", "Near the tank"),
        )
        with self.assertRaises(cases.WebIntakeError):
            self._register(address_landmark="x" * 201)

        row = intake_svc.serialize_worklist_row(self.alice, case, None, None)
        self.assertEqual(row["informant_phone_masked"], "******3210")
        self.assertEqual(row["informant_phone_2_masked"], "******5678")
        self.assertNotIn("informant_phone", row)
        self.assertNotIn("9876543210", repr(row))
        self.assertNotIn("address_house_street", row)

    def test_mask_phone_tolerates_legacy_text(self):
        self.assertIsNone(intake_svc.mask_phone(None))
        self.assertIsNone(intake_svc.mask_phone(""))
        self.assertEqual(intake_svc.mask_phone("+91 98765 43210"), "******3210")
        self.assertEqual(intake_svc.mask_phone("12"), "******")

    # ── visits ─────────────────────────────────────────────────────────────

    def test_set_reschedule_and_clear_a_visit(self):
        case = self._register()
        intake_svc.set_visit(self.bob, case.death_id, next_visit_at=_at(days=2))
        self.assertEqual(case.status, "scheduled")
        self.assertIsNotNone(case.next_visit_at)
        audit = self._last_audit(case)
        self.assertEqual((audit.action, audit.from_state, audit.to_state, audit.actor_user_id),
                         ("visit_scheduled", "registered", "scheduled", self.bob.user_id))

        first = case.next_visit_at
        intake_svc.set_visit(self.alice, case.death_id, next_visit_at=_at(days=5))
        self.assertEqual(case.status, "scheduled")
        self.assertGreater(case.next_visit_at, first)

        intake_svc.set_visit(self.alice, case.death_id, next_visit_at=None)
        self.assertEqual(case.status, "registered")
        self.assertIsNone(case.next_visit_at)
        self.assertEqual(self._last_audit(case).action, "visit_cleared")

    def test_visit_date_bounds_and_format(self):
        case = self._register()
        naive = datetime.now().replace(microsecond=0).isoformat()
        for bad in (_at(days=-2), _at(days=400), naive, "tomorrow", "2026-13-01T10:00+05:30"):
            with self.assertRaises(cases.WebIntakeError, msg=bad) as ctx:
                intake_svc.set_visit(self.alice, case.death_id, next_visit_at=bad)
            self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(case.status, "registered")
        # Earlier today (overdue by hours) is fine: the visit may be being logged late.
        intake_svc.set_visit(self.alice, case.death_id, next_visit_at=_at(hours=-3))
        self.assertEqual(case.status, "scheduled")

    def test_visit_on_a_case_not_waiting_is_refused(self):
        case = self._register()
        cases.transition(case, "in_progress", actor=self.alice, action="test")
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.set_visit(self.alice, case.death_id, next_visit_at=_at(days=1))
        self.assertEqual(ctx.exception.status_code, 409)

    # ── contact attempts ───────────────────────────────────────────────────

    def test_failed_attempts_make_the_case_not_reachable(self):
        for outcome in ("no_answer", "wrong_number", "moved"):
            case = self._register()
            intake_svc.set_visit(self.alice, case.death_id, next_visit_at=_at(days=1))
            intake_svc.log_contact_attempt(self.bob, case.death_id, outcome=outcome)
            self.assertEqual(case.status, "not_reachable", outcome)
            self.assertIsNone(case.next_visit_at)
            self.assertIsNotNone(case.last_contact_at)
            self.assertEqual(self._last_audit(case).action, f"contact_{outcome}")

            # A second failure keeps the state, takes the follow-up date, adds a row.
            intake_svc.log_contact_attempt(self.bob, case.death_id, outcome=outcome, next_visit_at=_at(days=3))
            self.assertEqual(case.status, "not_reachable")
            self.assertIsNotNone(case.next_visit_at)
            rows = self._attempts(case)
            self.assertEqual([r.outcome for r in rows], [outcome, outcome])
            self.assertEqual({r.by_user_id for r in rows}, {self.bob.user_id})

    def test_reached_schedules_only_with_a_date(self):
        case = self._register()
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="reached")
        self.assertEqual(case.status, "registered")
        self.assertIsNotNone(case.last_contact_at)
        self.assertIsNone(case.next_visit_at)

        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="no_answer")
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="reached", next_visit_at=_at(days=2))
        self.assertEqual(case.status, "scheduled")
        self.assertIsNotNone(case.next_visit_at)
        self.assertEqual(self._last_audit(case).action, "contact_reached")

        # On a scheduled case, reached without a date keeps the appointment.
        kept = case.next_visit_at
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="reached")
        self.assertEqual((case.status, case.next_visit_at), ("scheduled", kept))
        self.assertEqual(len(self._attempts(case)), 4)

    def test_refused_attempt_refuses_the_case(self):
        case = self._register()
        intake_svc.set_visit(self.alice, case.death_id, next_visit_at=_at(days=1))
        with self.assertRaises(cases.WebIntakeError):
            intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="refused", next_visit_at=_at(days=2))
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="refused")
        self.assertEqual(case.status, "refused")
        self.assertIsNone(case.next_visit_at)
        self.assertEqual(self._last_audit(case).action, "contact_refused")

    def test_a_not_reachable_family_can_later_refuse(self):
        case = self._register()
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="no_answer")
        self.assertEqual(case.status, "not_reachable")
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="refused")
        self.assertEqual(case.status, "refused")

    def test_attempt_rules(self):
        case = self._register()
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="left a note")
        self.assertEqual(ctx.exception.status_code, 400)
        cases.transition(case, "in_progress", actor=self.alice, action="test")
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="no_answer")
        self.assertEqual(ctx.exception.status_code, 409)
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.log_contact_attempt(self.dave, case.death_id, outcome="no_answer")
        self.assertEqual(ctx.exception.status_code, 404)

    # ── pause and resume ───────────────────────────────────────────────────

    def test_pause_with_a_reason_code_then_resume_by_starting_the_draft(self):
        case = self._register()
        draft = intake_svc.start_draft(self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                       death_id=case.death_id)
        self.assertEqual(case.status, "in_progress")
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.pause_interview(self.alice, case.death_id, reason="the widow was crying")
        self.assertEqual(ctx.exception.status_code, 400)

        intake_svc.pause_interview(self.alice, case.death_id, reason="respondent_busy", next_visit_at=_at(days=1))
        self.assertEqual(case.status, "paused")
        self.assertIsNotNone(case.next_visit_at)
        audit = self._last_audit(case)
        self.assertEqual((audit.action, audit.reason, audit.to_state),
                         ("interview_paused", "respondent_busy", "paused"))
        with self.assertRaises(cases.WebIntakeError) as ctx:
            intake_svc.pause_interview(self.alice, case.death_id, reason="other")
        self.assertEqual(ctx.exception.status_code, 409)

        resumed = intake_svc.start_draft(self.alice, project_id=self.PROJECT_ID, site_id=self.SITE_ID,
                                         death_id=case.death_id)
        self.assertEqual(resumed.draft_id, draft.draft_id)
        self.assertEqual(case.status, "in_progress")
        self.assertIsNone(case.next_visit_at)

    # ── worklist order and "Mine" ─────────────────────────────────────────

    def test_worklist_sorts_by_next_visit_then_activity_and_pages_without_gaps(self):
        undated_old = self._register(deceased_name="Undated Old")
        undated_new = self._register(deceased_name="Undated New")
        later = self._register(deceased_name="Later")
        sooner = self._register(deceased_name="Sooner")
        overdue = self._register(deceased_name="Overdue")
        intake_svc.set_visit(self.alice, later.death_id, next_visit_at=_at(days=3))
        intake_svc.set_visit(self.alice, sooner.death_id, next_visit_at=_at(days=1))
        intake_svc.set_visit(self.alice, overdue.death_id, next_visit_at=_at(hours=-5))
        # Touch the newer undated case last so it is the most recent activity.
        undated_new.remarks = "touched"
        db.session.flush()
        expected = [overdue.death_id, sooner.death_id, later.death_id,
                    undated_new.death_id, undated_old.death_id]

        full = [row[0].death_id for row in intake_svc.list_worklist(self.alice, limit=200)["cases"]]
        self.assertEqual([d for d in full if d in expected], expected)
        # Every dated case comes before every undated one.
        dated = [row[0].next_visit_at is not None for row in intake_svc.list_worklist(self.alice, limit=200)["cases"]]
        self.assertEqual(dated, sorted(dated, reverse=True))

        paged, cursor = [], None
        while True:
            page = intake_svc.list_worklist(self.alice, cursor=cursor, limit=1)
            paged.extend(row[0].death_id for row in page["cases"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(paged, full)
        for junk in ("zzz", "1_2", "x_1_" + str(overdue.death_id)):
            with self.assertRaises(cases.WebIntakeError):
                intake_svc.list_worklist(self.alice, cursor=junk)

    def test_mine_includes_a_case_where_i_only_logged_an_attempt(self):
        case = self._register(self.alice)
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="no_answer")
        self.assertNotIn(case.death_id,
                         [r[0].death_id for r in intake_svc.list_worklist(self.bob, mine=True, limit=200)["cases"]])
        # Already not reachable: bob's attempt changes no state and writes no audit row.
        intake_svc.log_contact_attempt(self.bob, case.death_id, outcome="no_answer")
        self.assertIn(case.death_id,
                      [r[0].death_id for r in intake_svc.list_worklist(self.bob, mine=True, limit=200)["cases"]])

    # ── API ────────────────────────────────────────────────────────────────

    def _post(self, path, body, csrf=True):
        return self.client.post(path, json=body, headers=self._csrf_headers() if csrf else None)

    def test_api_register_takes_the_new_fields_and_validates_phones(self):
        self._login(str(self.alice.user_id))
        base = {"project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "deceased_name": "Api Case",
                "deceased_sex": "male", "date_of_death": _dod()}
        response = self._post("/intake/api/deaths", {**base, "informant_phone": "5555555555"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("mobile", response.get_json()["error"])

        response = self._post("/intake/api/deaths", {
            **base, "informant_phone": "+91 98765 43210", "informant_phone_2": "07012345678",
            "address_house_street": "4 Mill Lane", "address_village_ward": "Kheda", "address_landmark": "School",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        death = response.get_json()["death"]
        stored = db.session.get(VaDeathRegister, death["death_id"])
        self.assertEqual((stored.informant_phone, stored.informant_phone_2), ("9876543210", "7012345678"))
        self.assertEqual((stored.address_house_street, stored.address_village_ward, stored.address_landmark),
                         ("4 Mill Lane", "Kheda", "School"))

        rows = {r["death_id"]: r for r in self.client.get("/intake/api/cases?limit=200").get_json()["cases"]}
        self.assertIn(death["death_id"], rows)
        self.assertEqual(rows[death["death_id"]]["informant_phone_masked"], "******3210")
        self.assertNotIn("informant_phone", rows[death["death_id"]])

    def test_api_actions_need_csrf_and_scope(self):
        case = self._register()
        db.session.commit()
        visit = f"/intake/api/cases/{case.death_id}/visit"
        attempts = f"/intake/api/cases/{case.death_id}/attempts"
        pause = f"/intake/api/cases/{case.death_id}/pause"

        self._login(str(self.bob.user_id))
        for path, body in ((visit, {"next_visit_at": _at(days=1)}), (attempts, {"outcome": "no_answer"}),
                           (pause, {"reason": "other"})):
            self.assertEqual(self._post(path, body, csrf=False).status_code, 400, path)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaDeathRegister, case.death_id).status, "registered")

        self._login(str(self.dave.user_id))
        for path, body in ((visit, {"next_visit_at": _at(days=1)}), (attempts, {"outcome": "no_answer"}),
                           (pause, {"reason": "other"})):
            response = self._post(path, body)
            self.assertEqual(response.status_code, 404, path)
        self.assertEqual(self._attempts(case), [])

        self._login(str(self.bob.user_id))
        response = self._post(attempts, {"outcome": "no_answer", "next_visit_at": _at(days=2)})
        self.assertEqual(response.status_code, 201, response.get_json())
        ack = response.get_json()["case"]
        self.assertEqual(ack["status"], "not_reachable")
        self.assertIsNotNone(ack["next_visit_at"])
        self.assertNotIn("deceased_name", ack)
        response = self._post(visit, {"next_visit_at": _at(days=4)})
        self.assertEqual((response.status_code, response.get_json()["case"]["status"]), (200, "scheduled"))
        # Pause needs an interview in progress.
        response = self._post(pause, {"reason": "other"})
        self.assertEqual(response.status_code, 409)

    def test_api_refused_attempt_on_not_reachable_is_recorded(self):
        case = self._register()
        intake_svc.log_contact_attempt(self.alice, case.death_id, outcome="no_answer")
        db.session.commit()
        self._login(str(self.alice.user_id))
        response = self._post(f"/intake/api/cases/{case.death_id}/attempts", {"outcome": "refused"})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["case"]["status"], "refused")
        self.assertEqual(len(self._attempts(case)), 2)

    def test_pages_render_the_new_controls(self):
        self._login(str(self.alice.user_id))
        page = self.client.get(f"/intake/deaths/new?project_id={self.PROJECT_ID}&site_id={self.SITE_ID}")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        for name in ("informant_phone_2", "address_house_street", "address_village_ward", "address_landmark",
                     'type="tel"', "10 digits starting 6-9"):
            self.assertIn(name, html)
        dashboard = self.client.get("/intake/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("js/intake/intake_worklist.js", dashboard.get_data(as_text=True))
        script = self.client.get("/static/js/intake/intake_worklist.js")
        text = script.get_data(as_text=True)
        script.close()
        for control in ("'Set visit'", "'Log attempt'", "'Pause'", "'attempts'", "'visit'", "'pause'"):
            self.assertIn(control, text)
